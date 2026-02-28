"""配置管理"""

import os
from functools import lru_cache
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv
from psycopg_pool import ConnectionPool

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
# 优先加载 assets/config/.env；兼容旧路径 config/.env（只读回退）
ENV_FILE = PROJECT_ROOT / "assets" / "config" / ".env"
if not ENV_FILE.exists():
    ENV_FILE = PROJECT_ROOT / "config" / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE, override=False)

def _resolve_repo_path(env_key: str, default: Path) -> Path:
    raw = (os.getenv(env_key) or "").strip()
    if not raw:
        return default
    p = Path(raw)
    return p if p.is_absolute() else (PROJECT_ROOT / p)


class Settings:
    """服务配置"""

    # API 服务
    HOST: str = os.getenv("API_SERVICE_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("API_SERVICE_PORT", "8088"))
    DEBUG: bool = os.getenv("API_SERVICE_DEBUG", "false").lower() == "true"

    # TimescaleDB
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5433/market_data"
    )


_PG_POOL: ConnectionPool | None = None
_PG_POOL_LOCK = Lock()


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_pg_pool() -> ConnectionPool:
    """获取共享 PG 连接池"""
    global _PG_POOL
    if _PG_POOL is None:
        with _PG_POOL_LOCK:
            if _PG_POOL is None:
                settings = get_settings()
                _PG_POOL = ConnectionPool(
                    settings.DATABASE_URL,
                    min_size=1,
                    max_size=10,
                    timeout=30,
                    kwargs={"connect_timeout": 3},
                )
    return _PG_POOL
