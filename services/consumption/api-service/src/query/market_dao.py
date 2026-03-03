from __future__ import annotations

import os
import time
from functools import lru_cache

from psycopg_pool import ConnectionPool

from src.query.datasources import MARKET, get_pool


def get_market_pool() -> ConnectionPool:
    """获取 market 数据源连接池（用于 market_data.* 等表）。"""
    return get_pool(MARKET)


def split_qualified_table(qualified: str) -> tuple[str, str]:
    """拆分 `schema.table`。

    说明：
    - 这里只服务于路由内的白名单常量表名，不做通用 SQL 解析。
    """
    q = (qualified or "").strip()
    if not q:
        raise ValueError("empty_table")
    if "." not in q:
        raise ValueError("missing_schema")
    schema, table = q.split(".", 1)
    # 对齐 PostgreSQL 的“未加引号标识符”规则：默认折叠为小写。
    # 旧实现通过 f-string 拼接（未加引号）查询表名，因此 `candles_1M` 实际等价于 `candles_1m`。
    schema = schema.strip().lower()
    table = table.strip().lower()
    if not schema or not table:
        raise ValueError("invalid_table")
    return schema, table


def _qualified_name(schema: str, table: str) -> str:
    s = (schema or "").strip()
    t = (table or "").strip()
    if not s or not t:
        raise ValueError("invalid_table")
    return f"{s}.{t}"


def _table_exists_ttl_sec() -> int:
    raw = (os.environ.get("QUERY_MARKET_TABLE_EXISTS_TTL_SEC") or "").strip()
    if not raw:
        return 30
    try:
        v = int(raw)
        return max(0, v)
    except Exception:
        return 30


@lru_cache(maxsize=2048)
def _table_exists_cached(schema: str, table: str, bucket: int) -> bool:
    """带 TTL bucket 的表存在性检查（避免每次走信息_schema）。"""
    pool = get_market_pool()
    qualified = _qualified_name(schema, table)
    with pool.connection() as conn:
        with conn.cursor() as cur:
            # 使用 to_regclass 以模拟 SQL 解析/大小写折叠行为，避免 `candles_1M` 等大小写差异误判。
            cur.execute("SELECT to_regclass(%s) IS NOT NULL", (qualified,))
            row = cur.fetchone()
            return bool(row[0]) if row else False


def table_exists(schema: str, table: str) -> bool:
    """检查表是否存在（带 TTL cache）。"""
    ttl = _table_exists_ttl_sec()
    bucket = int(time.time() // ttl) if ttl > 0 else 0
    return _table_exists_cached(schema, table, bucket)


def clear_table_exists_cache() -> None:
    """清理表存在性缓存（仅用于调试/测试）。"""
    _table_exists_cached.cache_clear()
