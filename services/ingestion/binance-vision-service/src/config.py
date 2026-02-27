"""配置（骨架）。

目标：支持“两库共存”且最小改动。

约定：
- 默认从环境变量读取，避免引入新的配置系统。
- 为避免两套数据库混淆，binance-vision-service 优先使用 `BINANCE_VISION_DATABASE_URL`；
  若未设置，则回退到通用 `DATABASE_URL`（兼容旧用法）。
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]  # services/ingestion/binance-vision-service


def _find_project_root(start: Path) -> Path:
    """向上查找仓库根目录（以 assets/config/.env.example 与 services/ 作为锚点）。"""
    current = start
    for _ in range(12):
        if (current / "assets" / "config" / ".env.example").exists() and (current / "services").is_dir():
            return current
        # 兼容旧路径（仅用于定位 root）
        if (current / "config" / ".env.example").exists() and (current / "services").is_dir():
            return current
        if current.parent == current:
            break
        current = current.parent
    return start.parents[2]


def _load_env_defaults_from_file(env_file: Path) -> None:
    """从 .env 加载默认环境变量（不覆盖进程外部显式设置的值）。"""
    if not env_file.exists():
        return
    for raw_line in env_file.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            continue
        if "$(" in line or "`" in line:
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if not key:
            continue
        if val.startswith('"') and val.endswith('"') and len(val) >= 2:
            val = val[1:-1]
        if val.startswith("'") and val.endswith("'") and len(val) >= 2:
            val = val[1:-1]
        os.environ.setdefault(key, val)


PROJECT_ROOT = _find_project_root(SERVICE_ROOT)
_env_file = PROJECT_ROOT / "assets" / "config" / ".env"
if not _env_file.exists():
    _env_file = PROJECT_ROOT / "config" / ".env"  # legacy（只读）
_load_env_defaults_from_file(_env_file)


@dataclass(frozen=True)
class AppConfig:
    """应用配置（最小占位）。"""

    database_url: str = os.getenv("BINANCE_VISION_DATABASE_URL") or os.getenv("DATABASE_URL", "")
    binance_data_base: str = os.getenv("BINANCE_DATA_BASE", "https://data.binance.vision")


def load_config() -> AppConfig:
    return AppConfig()
