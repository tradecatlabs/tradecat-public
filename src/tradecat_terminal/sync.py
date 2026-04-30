from __future__ import annotations

from pathlib import Path
from typing import Any

from tradecat_terminal.cache import sync_all_datasets as _sync_all_datasets
from tradecat_terminal.cache import sync_dataset as _sync_dataset


def sync_dataset(
    cache_dir: Path,
    dataset_key: str,
    url_override: str | None = None,
    *,
    fetch_timeout: float | None = None,
) -> dict[str, Any]:
    return _sync_dataset(cache_dir, dataset_key, url_override=url_override, fetch_timeout=fetch_timeout)


def sync_all_datasets(cache_dir: Path, *, fetch_timeout: float | None = None) -> list[dict[str, Any]]:
    return _sync_all_datasets(cache_dir, fetch_timeout=fetch_timeout)
