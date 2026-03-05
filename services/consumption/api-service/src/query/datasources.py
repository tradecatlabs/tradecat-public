from __future__ import annotations

import logging
import os
import re
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
    optional: bool = False


INDICATORS = DataSourceSpec(id="indicators", env_key="QUERY_PG_INDICATORS_URL", default_from_env="DATABASE_URL")
MARKET = DataSourceSpec(id="market", env_key="QUERY_PG_MARKET_URL", default_from_env="DATABASE_URL")
OTHER = DataSourceSpec(id="other", env_key="QUERY_PG_OTHER_URL", default_from_env=None, optional=True)

ALL_SOURCES: tuple[DataSourceSpec, ...] = (INDICATORS, MARKET, OTHER)


_POOLS: dict[str, ConnectionPool] = {}
_LOCK = Lock()

LOG = logging.getLogger("tradecat.api.datasources")


def _statement_timeout_ms() -> int:
    """
    PostgreSQL statement_timeout（毫秒）：

    - 目的：避免慢查询/卡死把连接池拖住，导致请求排队雪崩
    - env: QUERY_PG_STATEMENT_TIMEOUT_MS
      - <=0：禁用（不设置 statement_timeout）
      - 默认：8000（8s）
    """
    raw = (os.getenv("QUERY_PG_STATEMENT_TIMEOUT_MS") or "").strip()
    if not raw:
        return 8000
    try:
        v = int(raw)
    except Exception:
        return 8000
    return max(int(v), 0)


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
        # libpq: "host=.. user=.. password=.. dbname=.."
        if re.search(r"(?i)\bpassword\s*=", dsn):
            return re.sub(
                r"(?i)(\bpassword\s*=\s*)(\"[^\"]*\"|'[^']*'|\S+)",
                r"\1***",
                dsn,
            )

        # URL DSN: postgresql://user:pass@host:port/db?sslmode=...
        if "://" not in dsn:
            return dsn

        p = urlsplit(dsn)
        if not p.scheme:
            return "***"

        # 仅保留 username@host:port/path（不回显 password/query/fragment）
        netloc = ""
        if p.username:
            netloc += p.username
            # host 可能为空（postgresql://user:pass@/db）
            if p.hostname is None:
                netloc += "@"
        if p.hostname:
            if netloc and not netloc.endswith("@"):
                netloc += "@"
            netloc += p.hostname
        if p.port and p.hostname:
            netloc += f":{p.port}"
        return urlunsplit((p.scheme, netloc, p.path or "", "", ""))
    except Exception:
        return "***"


def get_pool(spec: DataSourceSpec) -> ConnectionPool:
    """获取数据源连接池（进程内单例）。"""
    with _LOCK:
        pool = _POOLS.get(spec.id)
        if pool is not None:
            return pool

        dsn = _resolve_dsn(spec)
        if not dsn:
            raise RuntimeError(f"missing_dsn:{spec.env_key}")

        kwargs: dict[str, object] = {"connect_timeout": 3}
        statement_timeout_ms = int(_statement_timeout_ms())
        if statement_timeout_ms > 0:
            # libpq: options='-c statement_timeout=8000'
            kwargs["options"] = f"-c statement_timeout={statement_timeout_ms}"

        pool = ConnectionPool(
            dsn,
            min_size=1,
            max_size=10,
            timeout=30,
            kwargs=kwargs,
        )
        _POOLS[spec.id] = pool
        return pool


def check_sources() -> list[dict[str, str | bool]]:
    """用于 health：逐源探测连通性（不抛出密码）。"""
    out: list[dict[str, str | bool]] = []
    for spec in ALL_SOURCES:
        dsn = _resolve_dsn(spec)
        if not dsn:
            if spec.optional:
                continue
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
            LOG.warning("数据源探测失败 source=%s", spec.id, exc_info=True)
            out.append({"id": spec.id, "ok": False, "dsn": redact_dsn(dsn), "error": type(exc).__name__})
    return out
