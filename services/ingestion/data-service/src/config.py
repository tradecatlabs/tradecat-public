"""配置与数据模型"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# ==================== 路径定位（避免目录迁移导致 parents[...] 失效） ====================
SERVICE_ROOT = Path(__file__).resolve().parents[1]  # services/ingestion/data-service


def _find_project_root(start: Path) -> Path:
    """向上查找仓库根目录（以 config/.env.example 与 services/ 作为锚点）。"""
    current = start
    for _ in range(12):
        if (current / "config" / ".env.example").exists() and (current / "services").is_dir():
            return current
        if current.parent == current:
            break
        current = current.parent
    # 兜底：兼容 services/ingestion/<svc> 布局
    return start.parents[2]


PROJECT_ROOT = _find_project_root(SERVICE_ROOT)

# 外部是否已显式设置 DATABASE_URL（用于两库共存时，允许命令行临时覆盖）
_DATABASE_URL_PRESET = bool(os.environ.get("DATABASE_URL"))

# 加载 config/.env
_env_file = PROJECT_ROOT / "config" / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    """服务配置"""
    database_url: str = field(default_factory=lambda: (
        os.getenv("DATABASE_URL", "")
        if _DATABASE_URL_PRESET
        else (os.getenv("DATA_SERVICE_DATABASE_URL") or os.getenv("DATABASE_URL", ""))
    ))
    http_proxy: Optional[str] = field(default_factory=lambda: os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY"))
    binance_fapi_base: str = field(default_factory=lambda: (
        os.getenv("DATA_SERVICE_BINANCE_FAPI_BASE")
        or os.getenv("BINANCE_FAPI_BASE")
        or ""
    ).rstrip("/"))
    binance_data_base: str = field(default_factory=lambda: (
        os.getenv("DATA_SERVICE_BINANCE_DATA_BASE")
        or os.getenv("BINANCE_DATA_BASE")
        or ""
    ).rstrip("/"))
    binance_alpha_url: str = field(default_factory=lambda: (
        os.getenv("DATA_SERVICE_BINANCE_ALPHA_URL")
        or os.getenv("BINANCE_ALPHA_URL")
        or ""
    ))

    # 日志和数据目录改为项目内
    log_dir: Path = field(default_factory=lambda: Path(os.getenv(
        "DATA_SERVICE_LOG_DIR", str(SERVICE_ROOT / "logs")
    )))
    data_dir: Path = field(default_factory=lambda: Path(os.getenv(
        "DATA_SERVICE_DATA_DIR", str(PROJECT_ROOT / "assets" / "database" / "csv")
    )))

    ws_gap_interval: int = field(default_factory=lambda: _int_env("BINANCE_WS_GAP_INTERVAL", 600))
    ws_gap_lookback: int = field(default_factory=lambda: _int_env("BINANCE_WS_GAP_LOOKBACK", 10080))
    ws_source: str = field(default_factory=lambda: os.getenv("BINANCE_WS_SOURCE", "binance_ws"))

    db_schema: str = field(default_factory=lambda: os.getenv("KLINE_DB_SCHEMA", "market_data"))
    db_exchange: str = field(default_factory=lambda: os.getenv("BINANCE_WS_DB_EXCHANGE", "binance_futures_um"))
    ccxt_exchange: str = field(default_factory=lambda: os.getenv("BINANCE_WS_CCXT_EXCHANGE", "binance"))

    def __post_init__(self):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()


INTERVAL_TO_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "6h": 21_600_000, "12h": 43_200_000,
    "1d": 86_400_000, "1w": 604_800_000, "1M": 2_592_000_000,
}


@dataclass(slots=True)
class GapTask:
    """缺口任务"""
    symbol: str
    gap_start: datetime
    gap_end: datetime


def normalize_interval(interval: str) -> str:
    interval = interval.strip()
    if interval == "1M":
        return "1M"
    normalized = interval.lower()
    if normalized not in INTERVAL_TO_MS:
        raise ValueError(f"不支持的周期: {interval}")
    return normalized
