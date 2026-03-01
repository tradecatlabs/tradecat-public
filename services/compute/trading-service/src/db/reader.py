"""
数据库读写（高性能版）

优化点：
1. PG 连接池复用 + 扩大池大小
2. 多周期并行查询
3. 批量 SQL 查询（IN 子句）
4. 批量写入
"""
import threading
import logging
from typing import Dict, List, Sequence
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from psycopg import sql
from psycopg import OperationalError, InterfaceError
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from ..config import config
from ..observability import metrics

LOG = logging.getLogger("indicator_service.db")
_pg_query_total = metrics.counter("pg_query_total", "PG 查询次数")
_pg_write_total = metrics.counter("pg_write_total", "PG 写入次数")

# 共享 PG 连接池（默认行工厂）
_shared_pg_pool: ConnectionPool | None = None
_shared_pg_pool_lock = threading.Lock()


def get_db_counters() -> Dict[str, float]:
    """获取 DB 计数器快照"""
    return {
        "pg_query_total": _pg_query_total.get(),
        "pg_write_total": _pg_write_total.get(),
    }


def inc_pg_query():
    """记录 PG 查询次数"""
    _pg_query_total.inc()

def inc_pg_write():
    """记录 PG 写入次数"""
    _pg_write_total.inc()


def get_shared_pg_pool() -> ConnectionPool:
    """获取共享 PG 连接池"""
    global _shared_pg_pool
    if _shared_pg_pool is None:
        with _shared_pg_pool_lock:
            if _shared_pg_pool is None:
                _shared_pg_pool = ConnectionPool(
                    config.db_url,
                    min_size=1,
                    max_size=10,
                    timeout=30,
                    kwargs={"connect_timeout": 3},
                )
    return _shared_pg_pool


def reset_shared_pg_pool() -> None:
    """重置共享连接池（用于应对连接断开/SSL EOF 等瞬时错误）。"""
    global _shared_pg_pool
    with _shared_pg_pool_lock:
        if _shared_pg_pool is not None:
            try:
                _shared_pg_pool.close()
            finally:
                _shared_pg_pool = None


@contextmanager
def shared_pg_conn():
    """共享 PG 连接上下文"""
    with get_shared_pg_pool().connection() as conn:
        yield conn


class DataReader:
    """从 TimescaleDB 读取 K 线数据（高性能版）"""

    def __init__(self, db_url: str = None, pool_size: int = 10):
        self.db_url = db_url or config.db_url
        self._pool = None
        self._pool_size = pool_size
        self._pool_lock = threading.Lock()

    @property
    def pool(self):
        """懒加载连接池（线程安全）"""
        if self._pool is None:
            with self._pool_lock:
                if self._pool is None:
                    self._pool = ConnectionPool(
                        self.db_url,
                        min_size=2,
                        max_size=self._pool_size,
                        kwargs={"row_factory": dict_row},
                        timeout=120,
                    )
        return self._pool

    @contextmanager
    def _conn(self):
        """从连接池获取连接"""
        with self.pool.connection() as conn:
            yield conn

    def _execute_pg(self, conn, sql: str, params=None):
        """执行 PG 查询并计数"""
        inc_pg_query()
        return conn.execute(sql, params) if params is not None else conn.execute(sql)

    def get_klines(self, symbols: Sequence[str], interval: str, limit: int = 300, exchange: str = None) -> Dict[str, pd.DataFrame]:
        """批量获取 K 线数据 - 并行查询"""
        exchange = exchange or config.exchange
        if not symbols:
            return {}

        table = f"candles_{interval}"
        symbols_list = list(symbols)

        # 根据周期计算时间范围，避免扫描全部分区
        interval_minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440, "1w": 10080}
        minutes = interval_minutes.get(interval, 5) * limit * 2

        # 对于大量币种，使用并行单币种查询更快
        if len(symbols_list) > 50:
            return self._get_klines_parallel(symbols_list, interval, limit, exchange)

        # 小批量使用窗口函数
        sql = f"""
            WITH ranked AS (
                SELECT symbol, bucket_ts, open, high, low, close, volume,
                       quote_volume, trade_count, taker_buy_volume, taker_buy_quote_volume,
                       ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY bucket_ts DESC) as rn
                FROM market_data.{table}
                WHERE symbol = ANY(%s) AND exchange = %s AND bucket_ts > NOW() - INTERVAL '{minutes} minutes'
            )
            SELECT symbol, bucket_ts, open, high, low, close, volume,
                   quote_volume, trade_count, taker_buy_volume, taker_buy_quote_volume
            FROM ranked WHERE rn <= %s
            ORDER BY symbol, bucket_ts ASC
        """

        result = {}
        try:
            with self._conn() as conn:
                rows = self._execute_pg(conn, sql, (symbols_list, exchange, limit)).fetchall()
                if rows:
                    from itertools import groupby
                    for symbol, group in groupby(rows, key=lambda x: x['symbol']):
                        row_list = list(group)
                        if row_list:
                            result[symbol] = self._rows_to_df(row_list)
        except Exception as e:
            LOG.warning(f"批量查询失败，回退并行查询: {e}")
            result = self._get_klines_parallel(symbols_list, interval, limit, exchange)

        return result

    def _get_klines_parallel(self, symbols: Sequence[str], interval: str, limit: int, exchange: str) -> Dict[str, pd.DataFrame]:
        """并行查询多币种"""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        result = {}
        table = f"candles_{interval}"

        # 根据周期计算时间范围，避免扫描全部分区
        interval_minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440, "1w": 10080}
        minutes = interval_minutes.get(interval, 5) * limit * 2  # 2倍余量

        def fetch_one(symbol: str):
            try:
                with self.pool.connection() as conn:
                    sql = f"""
                        SELECT bucket_ts, open, high, low, close, volume, 
                               quote_volume, trade_count, taker_buy_volume, taker_buy_quote_volume
                        FROM market_data.{table}
                        WHERE symbol = %s AND exchange = %s AND bucket_ts > NOW() - INTERVAL '{minutes} minutes'
                        ORDER BY bucket_ts DESC
                        LIMIT %s
                    """
                    rows = self._execute_pg(conn, sql, (symbol, exchange, limit)).fetchall()
                    if rows:
                        return symbol, self._rows_to_df(list(reversed(rows)))
            except Exception:
                pass
            return symbol, None

        workers = min(self._pool_size - 1, 8)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(fetch_one, s) for s in symbols]
            for future in as_completed(futures):
                sym, df = future.result()
                if df is not None:
                    result[sym] = df

        return result

    def get_klines_multi_interval(self, symbols: Sequence[str], intervals: Sequence[str], limit: int = 300, exchange: str = None) -> Dict[str, Dict[str, pd.DataFrame]]:
        """多周期并行获取数据"""
        exchange = exchange or config.exchange
        if not symbols or not intervals:
            return {}

        result = {}

        # 并行查询所有周期
        workers = min(len(intervals), self._pool_size - 1, 7)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(self.get_klines, symbols, iv, limit, exchange): iv
                for iv in intervals
            }
            for future in as_completed(futures):
                iv = futures[future]
                try:
                    result[iv] = future.result()
                except Exception as e:
                    LOG.error(f"[{iv}] 查询失败: {e}")
                    result[iv] = {}

        return result

    def _get_klines_fallback(self, symbols: Sequence[str], interval: str, limit: int, exchange: str) -> Dict[str, pd.DataFrame]:
        """回退方案：逐个查询"""
        result = {}
        table = f"candles_{interval}"

        with self._conn() as conn:
            for symbol in symbols:
                sql = f"""
                    SELECT bucket_ts, open, high, low, close, volume, 
                           quote_volume, trade_count, taker_buy_volume, taker_buy_quote_volume
                    FROM market_data.{table}
                    WHERE symbol = %s AND exchange = %s
                    ORDER BY bucket_ts DESC
                    LIMIT %s
                """
                try:
                    rows = self._execute_pg(conn, sql, (symbol, exchange, limit)).fetchall()
                except Exception:
                    continue

                if rows:
                    result[symbol] = self._rows_to_df(list(reversed(rows)))

        return result

    def _rows_to_df(self, rows: list) -> pd.DataFrame:
        """将行数据转换为 DataFrame"""
        df = pd.DataFrame([dict(r) for r in rows])
        if "symbol" in df.columns:
            df.drop(columns=["symbol"], inplace=True)
        df.set_index(pd.DatetimeIndex(df["bucket_ts"], tz="UTC"), inplace=True)
        df.drop(columns=["bucket_ts"], inplace=True)
        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    def get_symbols(self, exchange: str = None, interval: str = "1m") -> List[str]:
        """获取交易所所有交易对"""
        exchange = exchange or config.exchange
        with self._conn() as conn:
            sql = f"SELECT DISTINCT symbol FROM market_data.candles_{interval} WHERE exchange = %s"
            return [r["symbol"] for r in self._execute_pg(conn, sql, (exchange,)).fetchall()]

    def get_latest_ts(self, interval: str, exchange: str = None):
        """获取某周期最新 K 线时间戳"""
        exchange = exchange or config.exchange
        try:
            with self._conn() as conn:
                sql = f"SELECT MAX(bucket_ts) FROM market_data.candles_{interval} WHERE exchange = %s"
                row = self._execute_pg(conn, sql, (exchange,)).fetchone()
                if row and row["max"]:
                    return row["max"]
        except Exception:
            pass
        return None

    def close(self):
        """关闭连接池"""
        if self._pool:
            self._pool.close()
            self._pool = None


# ==================== PG 写入（tg_cards schema，对齐历史表结构） ====================

class PgDataWriter:
    """
    将指标结果写入 PostgreSQL（tg_cards schema）。

    语义对齐历史 DataWriter：
    - 对齐列：缺失补 NULL，多余丢弃
    - 幂等：先删同一 (交易对, 周期, 数据时间) 再插入
    - 保留窗口：按 (交易对, 周期) 保留每周期最新 N 条
    """

    def __init__(self, *, schema: str | None = None) -> None:
        self.schema = (schema or config.indicator_pg_schema or "tg_cards").strip() or "tg_cards"
        self._lock = threading.Lock()
        self._cols_cache: dict[str, list[tuple[str, str]]] = {}

    def _load_table_columns(self, conn, table: str) -> list[tuple[str, str]]:
        cached = self._cols_cache.get(table)
        if cached is not None:
            return cached

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
                """,
                (self.schema, table),
            )
            rows = cur.fetchall() or []

        cols = [(str(r[0]), str(r[1])) for r in rows]
        self._cols_cache[table] = cols
        return cols

    def write(self, table: str, df: pd.DataFrame) -> None:
        with self._lock:
            for attempt in (1, 2):
                with shared_pg_conn() as conn:
                    try:
                        with conn.cursor() as cur:
                            try:
                                self._write_table(conn, cur, table, df)
                            except (OperationalError, InterfaceError):
                                raise
                            except Exception as exc:
                                raise RuntimeError(f"写入指标表失败: {self.schema}.{table}") from exc
                        conn.commit()
                        return
                    except (OperationalError, InterfaceError):
                        # 连接断开/SSL EOF：回滚可能失败，忽略并重置连接池重试一次
                        try:
                            conn.rollback()
                        except Exception:
                            pass
                        if attempt == 1:
                            reset_shared_pg_pool()
                            continue
                        raise
                    except Exception:
                        try:
                            conn.rollback()
                        except Exception:
                            pass
                        raise

    def write_batch(self, data: Dict[str, pd.DataFrame]) -> None:
        if not data:
            return
        with self._lock:
            for attempt in (1, 2):
                with shared_pg_conn() as conn:
                    try:
                        with conn.cursor() as cur:
                            for table, df in data.items():
                                try:
                                    self._write_table(conn, cur, table, df)
                                except (OperationalError, InterfaceError):
                                    raise
                                except Exception as exc:
                                    raise RuntimeError(f"写入指标表失败: {self.schema}.{table}") from exc
                        conn.commit()
                        return
                    except (OperationalError, InterfaceError):
                        try:
                            conn.rollback()
                        except Exception:
                            pass
                        if attempt == 1:
                            reset_shared_pg_pool()
                            continue
                        raise
                    except Exception:
                        try:
                            conn.rollback()
                        except Exception:
                            pass
                        raise

    def _write_table(self, conn, cur, table: str, df: pd.DataFrame) -> None:
        if df is None or df.empty:
            return

        cols_meta = self._load_table_columns(conn, table)
        if not cols_meta:
            raise RuntimeError(
                f"PG 指标表不存在或不可见: {self.schema}.{table}（请先执行 assets/database/db/schema/021_tg_cards_sqlite_parity.sql）"
            )

        pg_cols = [c for c, _t in cols_meta]
        df_cols = list(df.columns)

        # 对齐列：缺失补 None，多余丢弃
        missing = [c for c in pg_cols if c not in df_cols]
        for c in missing:
            df[c] = None
        df = df[pg_cols]

        # NaN -> None（避免 PG 插入 NaN 造成后续聚合/排序异常）
        df = df.where(pd.notnull(df), None)

        # ==================== 三键防线（避免无键脏数据写入） ====================
        #
        # 历史上曾出现某些指标未输出 (交易对/周期/数据时间) 导致写入 NULL 或 "nan"，
        # 这类行会绕过幂等删除与保留窗口清理，最终让表无限膨胀并破坏消费端筛选。
        #
        # 规则：只要表结构包含三键，则写入前强制丢弃任何三键缺失/空白/NaN 的行。
        bad_tokens = {"", "-", "nan", "nat", "none", "null"}
        if {"交易对", "周期", "数据时间"}.issubset(set(pg_cols)):
            def _ok_key(series: pd.Series) -> pd.Series:
                s = series.astype(str).str.strip()
                return (~series.isna()) & (~s.str.lower().isin(bad_tokens)) & (s != "None") & (s != "")

            mask = _ok_key(df["交易对"]) & _ok_key(df["周期"]) & _ok_key(df["数据时间"])
            if not mask.all():
                df = df[mask]
            if df.empty:
                return

        # 幂等删除：同一 (交易对, 周期, 数据时间) 先删再插
        if {"交易对", "周期", "数据时间"}.issubset(set(pg_cols)):
            keys = df[["交易对", "周期", "数据时间"]].drop_duplicates()
            # 过滤空 key，避免误删
            keys = keys[(keys["交易对"].notna()) & (keys["周期"].notna()) & (keys["数据时间"].notna())]
            if not keys.empty:
                delete_sql = sql.SQL(
                    'DELETE FROM {} WHERE "交易对"=%s AND "周期"=%s AND "数据时间"=%s'
                ).format(sql.Identifier(self.schema, table))
                cur.executemany(delete_sql, list(keys.itertuples(index=False, name=None)))
                inc_pg_write()

        # 插入
        #
        # ⚠️ 重要：psycopg 的占位符语法使用 `%s`，因此 SQL 文本中的任意 `%` 都会被解析器扫描。
        # 我们的历史表结构中存在列名包含 `%`（例如 "距离趋势线%" / "持仓变动%"），且这些列名需要出现在 INSERT 列表里；
        # 若不做转义，驱动会把 `%"` 误判为非法占位符并抛出：
        #   ProgrammingError: only '%s', '%b', '%t' are allowed as placeholders, got '%"'
        #
        # 解决：将 Identifier 渲染为字符串后把 `%` 变为 `%%`（仅用于驱动解析阶段的“字面量%”转义），
        # 最终发送到 PG 的 SQL 仍会是单个 `%`，不会改变真实列名。
        def _ident_sql(*parts: str) -> sql.SQL:
            rendered = sql.Identifier(*parts).as_string(conn)
            if "%" in rendered:
                rendered = rendered.replace("%", "%%")
            return sql.SQL(rendered)

        placeholders = sql.SQL(",").join(sql.Placeholder() for _ in pg_cols)
        insert_sql = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            _ident_sql(self.schema, table),
            sql.SQL(",").join(_ident_sql(c) for c in pg_cols),
            placeholders,
        )

        rows: list[tuple] = []
        for tup in df.itertuples(index=False, name=None):
            out: list[object] = []
            for (_col, typ), val in zip(cols_meta, tup):
                if val is None:
                    out.append(None)
                    continue
                if typ == "integer":
                    try:
                        out.append(int(val))
                    except Exception:
                        out.append(None)
                    continue
                if typ == "double precision":
                    try:
                        out.append(float(val))
                    except Exception:
                        out.append(None)
                    continue
                # text
                try:
                    out.append(str(val))
                except Exception:
                    out.append(None)
            rows.append(tuple(out))

        if rows:
            cur.executemany(insert_sql, rows)
            inc_pg_write()

        # 保留窗口清理
        self._cleanup_old_data(cur, table, df)

    def _cleanup_old_data(self, cur, table: str, df: pd.DataFrame) -> None:
        RETENTION = {
            "1m": 120,   # 2小时
            "5m": 120,   # 10小时
            "15m": 96,   # 24小时
            "1h": 144,   # 6天
            "4h": 120,   # 20天，满足长窗口计算
            "1d": 180,   # 6个月
            "1w": 104,   # 2年
        }

        if df is None or df.empty:
            return
        if not {"交易对", "周期", "数据时间"}.issubset(set(df.columns)):
            return

        keys = df[["交易对", "周期"]].drop_duplicates()
        if keys.empty:
            return

        by_interval: dict[str, list[str]] = {}
        for symbol, interval in keys.itertuples(index=False, name=None):
            sym = str(symbol).strip() if symbol is not None else ""
            iv = str(interval).strip() if interval is not None else ""
            if not sym or not iv:
                continue
            by_interval.setdefault(iv, []).append(sym)

        if not by_interval:
            return

        cleanup_sql = sql.SQL(
            """
            WITH ranked AS (
                SELECT ctid,
                       row_number() OVER (PARTITION BY {sym_col} ORDER BY {ts_col} DESC) AS rn
                FROM {tbl}
                WHERE {period_col} = %s AND {sym_col} = ANY(%s)
            )
            DELETE FROM {tbl} t
            USING ranked r
            WHERE t.ctid = r.ctid AND r.rn > %s
            """
        ).format(
            tbl=sql.Identifier(self.schema, table),
            sym_col=sql.Identifier("交易对"),
            period_col=sql.Identifier("周期"),
            ts_col=sql.Identifier("数据时间"),
        )

        for iv, symbols in by_interval.items():
            limit = int(RETENTION.get(iv, 60))
            uniq = sorted({s for s in symbols if s})
            if not uniq:
                continue
            cur.execute(cleanup_sql, (iv, uniq, limit))
            inc_pg_write()


# 全局单例
reader = DataReader()
pg_writer = PgDataWriter()


class WriterCompat:
    """兼容旧调用：保留 interval 参数但不使用（PG 写入由 df 自带 周期 字段决定）。"""

    def __init__(self, impl: PgDataWriter) -> None:
        self._impl = impl

    def write(self, table: str, df: pd.DataFrame, interval: str | None = None) -> None:  # noqa: ARG002
        self._impl.write(table, df)

    def write_batch(self, data: Dict[str, pd.DataFrame], interval: str | None = None) -> None:  # noqa: ARG002
        self._impl.write_batch(data)


writer = WriterCompat(pg_writer)
