"""TimescaleDB 适配器"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from config import normalize_interval, settings

logger = logging.getLogger(__name__)

_CANDLE_DEDUPE_KEY = ("exchange", "symbol", "bucket_ts")
_METRICS_DEDUPE_KEY = ("symbol", "create_time")


def _dedupe_rows(rows: Sequence[dict], key_cols: Tuple[str, ...]) -> List[dict]:
    """
    对输入 rows 做幂等去重，避免 TEMP TABLE -> INSERT ... ON CONFLICT 时因“同 key 重复”触发：
    `ON CONFLICT DO UPDATE command cannot affect row a second time`。

    约定：
    - 以 key_cols 组成的 key 作为唯一键。
    - 若重复，保留“最后一次出现”的值（覆盖旧值），但保持首次出现的顺序（dict 赋值不会改变插入顺序）。
    """
    if not rows:
        return []
    deduped: Dict[tuple, dict] = {}
    for row in rows:
        key = tuple(row.get(c) for c in key_cols)
        deduped[key] = row
    return list(deduped.values())


class TimescaleAdapter:
    """TimescaleDB 操作"""

    def __init__(self, db_url: Optional[str] = None, schema: Optional[str] = None,
                 pool_min: int = 2, pool_max: int = 10, timeout: float = 30.0):
        self.db_url = db_url or settings.database_url
        self.schema = schema or settings.db_schema
        self._pool_min = pool_min
        self._pool_max = pool_max
        self._timeout = timeout
        self._pool: Optional[ConnectionPool] = None

    @property
    def pool(self) -> ConnectionPool:
        if self._pool is None:
            self._pool = ConnectionPool(
                self.db_url,
                min_size=self._pool_min,
                max_size=self._pool_max,
                timeout=self._timeout,  # 获取连接超时
                max_idle=300,           # 空闲连接最大存活 5 分钟
                max_lifetime=3600,      # 连接最大存活 1 小时
            )
        return self._pool

    def close(self) -> None:
        if self._pool:
            self._pool.close()
            self._pool = None

    @contextmanager
    def connection(self) -> Iterator:
        with self.pool.connection() as conn:
            yield conn

    def upsert_candles(
        self,
        interval: str,
        rows: Sequence[dict],
        batch_size: int = 2000,
        *,
        update_on_conflict: bool = True,
    ) -> int:
        """
        使用 COPY 命令批量 upsert K线，实现最高性能。

        工作流程:
        1. 创建一个与目标表结构相同的临时表。
        2. 使用高效的 COPY 命令将所有数据流式传输到临时表。
        3. 从临时表执行一次 INSERT ... ON CONFLICT 操作到目标表。
        4. 事务结束时，临时表会自动删除。
        """
        if not rows:
            return 0

        rows = _dedupe_rows(rows, _CANDLE_DEDUPE_KEY)
        interval = normalize_interval(interval)
        table_name = f"candles_{interval}"
        cols = list(rows[0].keys()) # 从第一行获取列名，确保顺序一致

        # 确保关键列存在
        if "bucket_ts" not in cols or "symbol" not in cols or "exchange" not in cols:
            raise ValueError("Rows must contain bucket_ts, symbol, and exchange")

        temp_table_name = f"temp_{table_name}_{int(datetime.now().timestamp() * 1000)}"

        sql_create_temp = sql.SQL("""
            CREATE TEMP TABLE {temp_table} (LIKE {target_table} INCLUDING DEFAULTS)
            ON COMMIT DROP;
        """).format(
            temp_table=sql.Identifier(temp_table_name),
            target_table=sql.Identifier(self.schema, table_name)
        )

        if update_on_conflict:
            # ON CONFLICT 更新的列（排除冲突键）
            update_cols = [col for col in cols if col not in ("exchange", "symbol", "bucket_ts")]
            sql_upsert_from_temp = sql.SQL("""
                INSERT INTO {target_table} ({cols})
                SELECT {cols} FROM {temp_table}
                ON CONFLICT (exchange, symbol, bucket_ts) DO UPDATE SET
                    {update_assignments},
                    updated_at = NOW();
            """).format(
                target_table=sql.Identifier(self.schema, table_name),
                cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
                temp_table=sql.Identifier(temp_table_name),
                update_assignments=sql.SQL(", ").join(
                    sql.SQL("{col} = EXCLUDED.{col}").format(col=sql.Identifier(col))
                    for col in update_cols
                )
            )
        else:
            # 缺口补齐/历史导入：只插入，不覆盖已有行（避免 REST/ZIP 覆盖 WS 行）
            sql_upsert_from_temp = sql.SQL("""
                INSERT INTO {target_table} ({cols})
                SELECT {cols} FROM {temp_table}
                ON CONFLICT (exchange, symbol, bucket_ts) DO NOTHING;
            """).format(
                target_table=sql.Identifier(self.schema, table_name),
                cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
                temp_table=sql.Identifier(temp_table_name),
            )

        total_inserted = 0
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql_create_temp)

                # 分批处理
                for i in range(0, len(rows), batch_size):
                    batch = rows[i:i + batch_size]

                    # 使用 COPY 命令高效写入临时表
                    with cur.copy(sql.SQL("COPY {temp_table} ({cols}) FROM STDIN").format(
                        temp_table=sql.Identifier(temp_table_name),
                        cols=sql.SQL(", ").join(map(sql.Identifier, cols))
                    )) as copy:
                        for row in batch:
                            copy.write_row(tuple(row.get(col) for col in cols))

                # 从临时表一次性 upsert 到目标表
                cur.execute(sql_upsert_from_temp)
                total_inserted = cur.rowcount if cur.rowcount > 0 else len(rows)

            conn.commit()

        return total_inserted

    def upsert_metrics(self, rows: Sequence[dict], batch_size: int = 2000) -> int:
        """使用 COPY 命令批量 upsert 指标数据，实现最高性能。"""
        if not rows:
            return 0

        rows = _dedupe_rows(rows, _METRICS_DEDUPE_KEY)
        table_name = "binance_futures_metrics_5m"
        cols = list(rows[0].keys())

        if "create_time" not in cols or "symbol" not in cols:
            raise ValueError("Rows must contain create_time and symbol")

        temp_table_name = f"temp_{table_name}_{int(datetime.now().timestamp() * 1000)}"

        sql_create_temp = sql.SQL("""
            CREATE TEMP TABLE {temp_table} (LIKE {target_table} INCLUDING DEFAULTS)
            ON COMMIT DROP;
        """).format(
            temp_table=sql.Identifier(temp_table_name),
            target_table=sql.Identifier(self.schema, table_name)
        )

        update_cols = [col for col in cols if col not in ("symbol", "create_time")]
        sql_upsert_from_temp = sql.SQL("""
            INSERT INTO {target_table} ({cols})
            SELECT {cols} FROM {temp_table}
            ON CONFLICT (symbol, create_time) DO UPDATE SET
                {update_assignments},
                updated_at = NOW();
        """).format(
            target_table=sql.Identifier(self.schema, table_name),
            cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
            temp_table=sql.Identifier(temp_table_name),
            update_assignments=sql.SQL(", ").join(
                sql.SQL("{col} = EXCLUDED.{col}").format(col=sql.Identifier(col))
                for col in update_cols
            )
        )

        total_inserted = 0
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql_create_temp)

                for i in range(0, len(rows), batch_size):
                    batch = rows[i:i + batch_size]
                    with cur.copy(sql.SQL("COPY {temp_table} ({cols}) FROM STDIN").format(
                        temp_table=sql.Identifier(temp_table_name),
                        cols=sql.SQL(", ").join(map(sql.Identifier, cols))
                    )) as copy:
                        for row in batch:
                            copy.write_row(tuple(row.get(col) for col in cols))

                cur.execute(sql_upsert_from_temp)
                total_inserted = cur.rowcount if cur.rowcount > 0 else len(rows)

            conn.commit()

        return total_inserted

    def _quote_val(self, v) -> str:
        """SQL 值转义 (在此重构中已不再需要，保留以兼容旧代码)"""
        if v is None:
            return "NULL"
        if isinstance(v, str):
            return f"'{v.replace(chr(39), chr(39)+chr(39))}'"
        if isinstance(v, datetime):
            return f"'{v.isoformat()}'"
        if isinstance(v, bool):
            return "TRUE" if v else "FALSE"
        # Decimal, int, float 都直接转 str
        return str(v)

    def get_symbols(self, exchange: str, interval: str = "1m") -> List[str]:
        table = f"{self.schema}.candles_{normalize_interval(interval)}"
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT DISTINCT symbol FROM {table} WHERE exchange = %s ORDER BY symbol", (exchange,))
                return [r[0] for r in cur.fetchall()]

    def get_counts(self, exchange: str, interval: str, symbols: Sequence[str]) -> Dict[str, int]:
        if not symbols:
            return {}
        table = f"{self.schema}.candles_{normalize_interval(interval)}"
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT symbol, COUNT(*) FROM {table} WHERE exchange = %s AND symbol = ANY(%s) GROUP BY symbol", (exchange, list(symbols)))
                return {r[0]: r[1] for r in cur.fetchall()}

    def detect_gaps(self, exchange: str, interval: str, symbols: Sequence[str], lookback_min: int = 10080, threshold_sec: int = 120, limit: int = 50) -> List[tuple]:
        table = f"{self.schema}.candles_{normalize_interval(interval)}"
        sql = f"""
            WITH o AS (SELECT symbol, bucket_ts, LEAD(bucket_ts) OVER (PARTITION BY symbol ORDER BY bucket_ts) AS next_ts
                       FROM {table} WHERE exchange = %(ex)s AND symbol = ANY(%(sym)s) AND bucket_ts >= NOW() - INTERVAL '{lookback_min} minutes')
            SELECT symbol, bucket_ts, next_ts FROM o WHERE next_ts IS NOT NULL AND next_ts - bucket_ts >= INTERVAL '{threshold_sec} seconds' ORDER BY bucket_ts LIMIT %(lim)s
        """
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, {"ex": exchange, "sym": list(symbols), "lim": limit})
                return cur.fetchall()

    def query(self, exchange: str, symbol: str, interval: str, start: Optional[datetime] = None, end: Optional[datetime] = None, limit: int = 1000) -> List[dict]:
        table = f"{self.schema}.candles_{normalize_interval(interval)}"
        conds, params = ["exchange = %s", "symbol = %s"], [exchange, symbol]
        if start:
            conds.append("bucket_ts >= %s")
            params.append(start)
        if end:
            conds.append("bucket_ts <= %s")
            params.append(end)
        params.append(limit)
        with self.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(f"SELECT * FROM {table} WHERE {' AND '.join(conds)} ORDER BY bucket_ts DESC LIMIT %s", params)
                return cur.fetchall()
