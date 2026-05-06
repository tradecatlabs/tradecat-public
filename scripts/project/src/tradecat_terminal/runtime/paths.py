from __future__ import annotations

from pathlib import Path

from tradecat_terminal.config import DEFAULT_CACHE_DIR


def ensure_runtime_dir(path: Path | None = None) -> Path:
    runtime_dir = path or DEFAULT_CACHE_DIR
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir
