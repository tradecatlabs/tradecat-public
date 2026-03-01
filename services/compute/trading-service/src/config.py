"""
配置管理

环境变量:
    DATABASE_URL: TimescaleDB 连接串
    INDICATOR_PG_SCHEMA: PG 指标 schema（默认 tg_cards）
    MAX_WORKERS: 并行计算线程数
    KLINE_INTERVALS: K线指标计算周期
    FUTURES_INTERVALS: 期货情绪计算周期
"""
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List

SERVICE_ROOT = Path(__file__).parents[1]  # src/config.py -> src -> trading-service
PROJECT_ROOT = SERVICE_ROOT.parents[2]    # trading-service -> services -> tradecat

# 加载 assets/config/.env（优先）→ config/.env（兼容只读回退）
_env_file = PROJECT_ROOT / "assets" / "config" / ".env"
if not _env_file.exists():
    _env_file = PROJECT_ROOT / "config" / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _parse_intervals(env_key: str, default: str) -> List[str]:
    return [x.strip() for x in os.getenv(env_key, default).split(",") if x.strip()]


@dataclass
class Config:
    # TimescaleDB（读取K线）
    db_url: str = field(default_factory=lambda: os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5433/market_data"
    ))

    # PG 指标 schema（表名严格对齐历史指标表名）
    indicator_pg_schema: str = field(default_factory=lambda: (os.getenv("INDICATOR_PG_SCHEMA", "tg_cards") or "tg_cards").strip())

    # 计算参数
    default_lookback: int = 300
    max_workers: int = field(default_factory=lambda: int(os.getenv("MAX_WORKERS", "6")))
    exchange: str = "binance_futures_um"
    # 计算后端: thread | process | hybrid（IO用线程，CPU用进程）
    compute_backend: str = field(default_factory=lambda: os.getenv("COMPUTE_BACKEND", "thread").lower())

    # IO/CPU 拆分执行器配置
    max_io_workers: int = field(default_factory=lambda: int(os.getenv("MAX_IO_WORKERS", "8")))
    max_cpu_workers: int = field(default_factory=lambda: int(os.getenv("MAX_CPU_WORKERS", "4")))

    # K线指标周期
    kline_intervals: List[str] = field(default_factory=lambda: _parse_intervals(
        "KLINE_INTERVALS", "1m,5m,15m,1h,4h,1d,1w"
    ))

    # 期货情绪周期
    futures_intervals: List[str] = field(default_factory=lambda: _parse_intervals(
        "FUTURES_INTERVALS", "5m,15m,1h,4h,1d,1w"
    ))

    # 兼容旧代码
    @property
    def intervals(self) -> List[str]:
        return self.kline_intervals


config = Config()
