from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATA_DIR = Path.home() / ".tradecat"
DEFAULT_CACHE_DIR = DEFAULT_DATA_DIR / "cache"


@dataclass(frozen=True)
class AppConfig:
    cache_dir: Path


def load_config(cache_dir: str | None = None) -> AppConfig:
    raw_path = (
        cache_dir
        or os.environ.get("TRADECAT_CACHE_DIR")
        or os.environ.get("TRADECAT_TERMINAL_CACHE_DIR")
        or str(DEFAULT_CACHE_DIR)
    )
    return AppConfig(cache_dir=Path(raw_path).expanduser())
