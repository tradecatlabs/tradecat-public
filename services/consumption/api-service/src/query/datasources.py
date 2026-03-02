from __future__ import annotations

import os
from dataclasses import dataclass
from threading import Lock
from urllib.parse import urlsplit, urlunsplit

from psycopg_pool import ConnectionPool


@dataclass(frozen=True)
class DataSourceSpec:
    """数据源定义（只读）"""

    id: str
    env_key: str
    default_from_env: str | None = None


INDICATORS = DataSourceSpec(id="indicators", env_key="QUERY_PG_INDICATORS_URL", default_from_env="DATABASE_URL")
MARKET = DataSourceSpec(id="market", env_key="QUERY_PG_MARKET_URL", default_from_env="DATABASE_URL")
OTHER = DataSourceSpec(id="other", env_key="QUERY_PG_OTHER_URL", default_from_env=None)

ALL_SOURCES: tuple[DataSourceSpec, ...] = (INDICATORS, MARKET, OTHER)


_POOLS: dict[str, ConnectionPool] = {}
_LOCK = Lock()


def _resolve_dsn(spec: DataSourceSpec) -> str:
    raw = (os.getenv(spec.env_key) or "").strip()
    if raw:
        return raw
    if spec.default_from_env:
        return (os.getenv(spec.default_from_env) or "").strip()
    return ""


def redact_dsn(dsn: str) -> str:
    """避免把密码打到日志/health。"""
    dsn = (dsn or "").strip()
    if not dsn:
        return ""
    try:
        p = urlsplit(dsn)
        if not p.scheme or not p.hostname:
            return dsn
        # 仅保留 username@host:port/db
        netloc = ""
        if p.username:
            netloc += p.username + "@"
        netloc += p.hostname
        if p.port:
            netloc += f":{p.port}"
        return urlunsplit((p.scheme, netloc, p.path or "", p.query or "", p.fragment or ""))
    except Exception:
        return dsn


def get_pool(spec: DataSourceSpec) -> ConnectionPool:
    """获取数据源连接池（进程内单例）。"""
    with _LOCK:
        pool = _POOLS.get(spec.id)
        if pool is not None:
            return pool

        dsn = _resolve_dsn(spec)
        if not dsn:
            raise RuntimeError(f"missing_dsn:{spec.env_key}")

        pool = ConnectionPool(
            dsn,
            min_size=1,
            max_size=10,
            timeout=30,
            kwargs={"connect_timeout": 3},
        )
        _POOLS[spec.id] = pool
        return pool


def check_sources() -> list[dict[str, str | bool]]:
    """用于 health：逐源探测连通性（不抛出密码）。"""
    out: list[dict[str, str | bool]] = []
    for spec in ALL_SOURCES:
        dsn = _resolve_dsn(spec)
        if not dsn:
            out.append({"id": spec.id, "ok": False, "dsn": "", "error": f"missing_env:{spec.env_key}"})
            continue
        try:
            pool = get_pool(spec)
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            out.append({"id": spec.id, "ok": True, "dsn": redact_dsn(dsn)})
        except Exception as exc:
            out.append({"id": spec.id, "ok": False, "dsn": redact_dsn(dsn), "error": str(exc)})
    return out

