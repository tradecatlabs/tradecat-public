"""
数据库读写（高性能版）

优化点：
1. PG 连接池复用 + 扩大池大小
2. 多周期并行查询
3. 批量 SQL 查询（IN 子句）
4. SQLite 连接复用 + WAL 模式
5. 批量写入
"""
import sqlite3
import threading
import logging
from pathlib import Path
from typing import Dict, List, Sequence
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from ..config import config
from ..observability import metrics

_sqlite_lock = threading.Lock()
LOG = logging.getLogger("indicator_service.db")
_pg_query_total = metrics.counter("pg_query_total", "PG 查询次数")
_pg_write_total = metrics.counter("pg_write_total", "PG 写入次数")
_sqlite_commit_total = metrics.counter("sqlite_commit_total", "SQLite 提交次数")

# 共享 PG 连接池（默认行工厂）
_shared_pg_pool: ConnectionPool | None = None
_shared_pg_pool_lock = threading.Lock()


def get_db_counters() -> Dict[str, float]:
    """获取 DB 计数器快照"""
    return {
        "pg_query_total": _pg_query_total.get(),
        "pg_write_total": _pg_write_total.get(),
        "sqlite_commit_total": _sqlite_commit_total.get(),
    }


def inc_pg_query():
    """记录 PG 查询次数"""
    _pg_query_total.inc()

def inc_pg_write():
    """记录 PG 写入次数"""
    _pg_write_total.inc()


def inc_sqlite_commit():
    """记录 SQLite commit 次数"""
    _sqlite_commit_total.inc()


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


class DataWriter:
    """将指标结果写入 SQLite（优化版）"""

    def __init__(self, sqlite_path: Path = None):
        self.sqlite_path = sqlite_path or config.sqlite_path
        self._conn = None
        self._lock = threading.Lock()

    def _get_conn(self) -> sqlite3.Connection:
        """获取或创建连接"""
        if self._conn is None:
            self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.sqlite_path), check_same_thread=False)
            self._conn.execute("PRAGMA auto_vacuum=FULL")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA cache_size=10000")
        return self._conn

    def write(self, table: str, df: pd.DataFrame, interval: str = None):
        """写入单个表 - 批量 INSERT"""
        with self._lock:
            conn = self._get_conn()
            self._write_table(conn, table, df)
            inc_sqlite_commit()
            conn.commit()

    def _write_table(self, conn, table: str, df: pd.DataFrame):
        """写入单表 - 复用逻辑，便于批量事务"""
        if df.empty:
            return

        # 检查表是否存在及列是否匹配
        try:
            existing_cols = [c[1] for c in conn.execute(f'PRAGMA table_info([{table}])').fetchall()]
        except Exception:
            existing_cols = []

        df_cols = list(df.columns)

        if existing_cols:
            # 对齐列：缺失的补 None，多余的丢弃，避免因列不匹配重建表
            missing = [c for c in existing_cols if c not in df_cols]
            for c in missing:
                df[c] = None
            df = df[existing_cols]
            df_cols = existing_cols
        else:
            # 表不存在，按当前列创建
            df.head(0).to_sql(table, conn, if_exists="replace", index=False)
            existing_cols = df_cols

        # 先删除同一 (交易对, 周期, 数据时间) 的旧数据
        if "交易对" in df_cols and "周期" in df_cols and "数据时间" in df_cols:
            dup_rows = df[["交易对", "周期", "数据时间"]].drop_duplicates()
            if not dup_rows.empty:
                delete_sql = f"DELETE FROM [{table}] WHERE [交易对]=? AND [周期]=? AND [数据时间]=?"
                delete_params = list(dup_rows.itertuples(index=False, name=None))
                conn.executemany(delete_sql, delete_params)

        # 批量 INSERT - 列名用方括号包裹以支持特殊字符
        placeholders = ",".join(["?"] * len(df_cols))
        cols_escaped = ",".join(f"[{c}]" for c in df_cols)
        sql = f"INSERT INTO [{table}] ({cols_escaped}) VALUES ({placeholders})"
        data = list(df.itertuples(index=False, name=None))
        conn.executemany(sql, data)

        # 清理旧数据
        self._cleanup_old_data(conn, table, df)

    def _cleanup_old_data(self, conn, table: str, df: pd.DataFrame):
        """清理旧数据，保留每个币种每个周期最新N条"""
        # 保留条数配置（约4GB总量）
        RETENTION = {
            '1m': 120,   # 2小时
            '5m': 120,   # 10小时
            '15m': 96,   # 24小时
            '1h': 144,   # 6天
            '4h': 120,   # 20天，满足长窗口计算
            '1d': 180,   # 6个月
            '1w': 104,   # 2年
        }

        if "周期" not in df.columns or "交易对" not in df.columns or "数据时间" not in df.columns:
            return

        keys = df[["交易对", "周期"]].drop_duplicates()
        if keys.empty:
            return

        params = []
        for symbol, interval in keys.itertuples(index=False, name=None):
            limit = RETENTION.get(interval, 60)
            params.append((symbol, interval, symbol, interval, limit))

        try:
            # 删除超出保留数量的旧数据
            conn.executemany(f"""
                DELETE FROM [{table}]
                WHERE 交易对 = ? AND 周期 = ?
                AND 数据时间 NOT IN (
                    SELECT 数据时间 FROM [{table}]
                    WHERE 交易对 = ? AND 周期 = ?
                    ORDER BY 数据时间 DESC
                    LIMIT ?
                )
            """, params)
        except Exception:
            pass

    def write_batch(self, data: Dict[str, pd.DataFrame], interval: str = None):
        """批量写入多个表 - 单次事务，executemany 批量插入"""
        if not data:
            return

        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute("BEGIN IMMEDIATE")

                for table, df in data.items():
                    self._write_table(conn, table, df)

                inc_sqlite_commit()
                conn.commit()
            except Exception as e:
                conn.rollback()
                raise e

    def close(self):
        """关闭连接"""
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None


# ==================== PG 写入（tg_cards schema，严格对齐 SQLite） ====================

class PgDataWriter:
    """
    将指标结果写入 PostgreSQL（tg_cards schema）。

    语义对齐 SQLite DataWriter：
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
            with shared_pg_conn() as conn:
                try:
                    with conn.cursor() as cur:
                        self._write_table(conn, cur, table, df)
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise

    def write_batch(self, data: Dict[str, pd.DataFrame]) -> None:
        if not data:
            return
        with self._lock:
            with shared_pg_conn() as conn:
                try:
                    with conn.cursor() as cur:
                        for table, df in data.items():
                            self._write_table(conn, cur, table, df)
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise

    def _write_table(self, conn, cur, table: str, df: pd.DataFrame) -> None:
        if df is None or df.empty:
            return

        cols_meta = self._load_table_columns(conn, table)
        if not cols_meta:
            LOG.warning("PG 指标表不存在或不可见: %s.%s（请先初始化 DDL）", self.schema, table)
            return

        pg_cols = [c for c, _t in cols_meta]
        df_cols = list(df.columns)

        # 对齐列：缺失补 None，多余丢弃
        missing = [c for c in pg_cols if c not in df_cols]
        for c in missing:
            df[c] = None
        df = df[pg_cols]

        # NaN -> None（避免 PG 插入 NaN 造成后续聚合/排序异常）
        df = df.where(pd.notnull(df), None)

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
        placeholders = sql.SQL(",").join(sql.Placeholder() for _ in pg_cols)
        insert_sql = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier(self.schema, table),
            sql.SQL(",").join(sql.Identifier(c) for c in pg_cols),
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
writer = DataWriter()
pg_writer = PgDataWriter()
