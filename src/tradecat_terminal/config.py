from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from tradecat_terminal.settings import cache_dir_from_settings

DEFAULT_APP_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_DIR = DEFAULT_APP_ROOT / ".tradecat" / "cache"


@dataclass(frozen=True)
class AppConfig:
    cache_dir: Path


def load_config(cache_dir: str | None = None) -> AppConfig:
    raw_path = (
        cache_dir
        or os.environ.get("TRADECAT_CACHE_DIR")
        or cache_dir_from_settings()
        or str(DEFAULT_CACHE_DIR)
    )
    return AppConfig(cache_dir=Path(raw_path).expanduser())
