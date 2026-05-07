from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from tradecat_terminal.cache import init_cache, status_cache, sync_all_datasets, sync_dataset
from tradecat_terminal.registry import get_dataset, list_active_datasets


def ensure_local_store(cache_dir: Path) -> dict[str, Any]:
    return init_cache(cache_dir)


def doctor_local_store(cache_dir: Path) -> dict[str, Any]:
    payload = status_cache(cache_dir)
    errors: list[str] = []
    warnings: list[str] = []
    if not Path(cache_dir).exists():
        errors.append("缓存目录不存在")
    for dataset in payload.get("datasets", []):
        if dataset.get("active") and dataset.get("cache_state") != "ready":
            warnings.append(f"{dataset['dataset_key']} 尚无 latest 缓存；可执行 tradecat sync {dataset['dataset_key']}")
    payload["errors"] = errors
    payload["warnings"] = warnings
    payload["ok"] = not errors
    return payload


def probe_dataset(
    cache_dir: Path,
    dataset_key: str,
    *,
    write: bool = True,
    fetch_timeout: float | None = None,
) -> dict[str, Any]:
    if not write:
        dataset = get_dataset(dataset_key)
        return {
            "ok": True,
            "dataset_key": dataset.key,
            "tab_name": dataset.tab_name,
            "data_mode": dataset.data_mode,
            "status": "dry-run",
            "changed": False,
            "wrote": False,
            "cache_dir": str(cache_dir),
        }
    return sync_dataset(cache_dir, dataset_key, fetch_timeout=fetch_timeout)


def probe_all_datasets(cache_dir: Path, *, write: bool = True) -> list[dict[str, Any]]:
    if not write:
        return [probe_dataset(cache_dir, dataset.key, write=False) for dataset in list_active_datasets()]
    return sync_all_datasets(cache_dir)


def watch_datasets(
    cache_dir: Path,
    *,
    dataset_key: str | None = None,
    interval_seconds: float = 60.0,
    max_cycles: int | None = None,
    write: bool = True,
) -> list[list[dict[str, Any]]]:
    cycles: list[list[dict[str, Any]]] = []
    ensure_local_store(cache_dir)
    cycle = 0
    while True:
        if dataset_key:
            results = [probe_dataset(cache_dir, dataset_key, write=write)]
        else:
            results = probe_all_datasets(cache_dir, write=write)
        cycles.append(results)
        cycle += 1
        if max_cycles is not None and cycle >= max_cycles:
            return cycles
        time.sleep(interval_seconds)
