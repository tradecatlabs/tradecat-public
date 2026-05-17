from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from tradecat_terminal.cache import init_cache, status_cache, sync_all_datasets, sync_dataset
from tradecat_terminal.diagnostics import (
    build_support_bundle,
    cache_waterline,
    load_recent_errors,
    record_recent_error,
)
from tradecat_terminal.migrations import migrate_cache, migration_status
from tradecat_terminal.registry import get_dataset, list_active_datasets
from tradecat_terminal.settings import settings_health


def ensure_local_store(cache_dir: Path) -> dict[str, Any]:
    return init_cache(cache_dir)


def doctor_local_store(
    cache_dir: Path,
    *,
    fix: bool = False,
    repair: bool = False,
    sync: bool = False,
    fetch_timeout: float | None = None,
    verbose: bool = False,
    bundle: bool = False,
) -> dict[str, Any]:
    fixes: list[str] = []
    sync_results: list[dict[str, Any]] = []
    migration_result: dict[str, Any] | None = None
    if fix or repair or sync:
        init_cache(cache_dir)
        fixes.append("已初始化本地缓存目录和 dataset 目录")
    if repair:
        migration_result = migrate_cache(cache_dir, reason="doctor-repair")
        if migration_result.get("changed"):
            fixes.append("已执行本地缓存 schema 迁移")
    if sync:
        sync_results = sync_all_datasets(cache_dir, fetch_timeout=fetch_timeout)
        fixes.append("已尝试同步全部 active dataset")
    payload = status_cache(cache_dir)
    settings_state = settings_health()
    migration_state = migration_status(cache_dir)
    recent_errors = load_recent_errors(cache_dir)
    disk_waterline = cache_waterline(payload)
    errors: list[str] = []
    warnings: list[str] = []
    repair_hints: list[str] = []
    if not Path(cache_dir).exists():
        errors.append("缓存目录不存在")
        repair_hints.append("执行 tradecat doctor --fix 初始化本地缓存目录")
    for dataset in payload.get("datasets", []):
        if dataset.get("manifest_corrupt"):
            errors.append(f"{dataset['dataset_key']} manifest.json 损坏")
            repair_hints.append("执行 tradecat doctor --repair 备份并迁移本地缓存 metadata")
        if dataset.get("active") and dataset.get("cache_state") != "ready":
            warnings.append(f"{dataset['dataset_key']} 尚无 latest 缓存；可执行 tradecat sync {dataset['dataset_key']}")
            repair_hints.append(f"执行 tradecat sync {dataset['dataset_key']} 拉取该 dataset")
    if payload.get("missing_dataset_count"):
        if payload.get("ready_dataset_count") == 0:
            warnings.insert(0, "首次缓存为空；TUI 会先显示 empty-cache，并在后台继续探测远端")
            repair_hints.append("弱网可执行 tradecat config set tui_fetch_timeout.event_stream 3")
        repair_hints.append("执行 tradecat sync-all 拉取全部 active dataset")
    failed_syncs = [result for result in sync_results if not result.get("ok")]
    if failed_syncs:
        failed_keys = ", ".join(str(result.get("dataset_key")) for result in failed_syncs)
        errors.append(f"远端同步失败：{failed_keys}")
        repair_hints.append("检查网络后重试 tradecat doctor --sync --timeout 10")
        for result in failed_syncs:
            if result.get("error_info"):
                record_recent_error(
                    cache_dir,
                    source="doctor-sync",
                    dataset_key=str(result.get("dataset_key") or ""),
                    error=dict(result.get("error_info") or {}),
                )
    if settings_state.get("status") == "corrupt":
        errors.append("本地 settings.json 损坏")
        repair_hints.append("检查 settings.json.corrupt-*.bak 后重新执行 tradecat config set 写入配置")
    if migration_state.get("needed"):
        warnings.append("本地缓存 schema 需要迁移")
        repair_hints.append("执行 tradecat doctor --repair 迁移本地缓存 metadata")
    if disk_waterline.get("level") in {"warning", "critical"}:
        warnings.append(f"本地缓存体积达到 {disk_waterline['cache_bytes']} bytes")
        repair_hints.append(str(disk_waterline.get("hint")))
    payload["errors"] = errors
    payload["warnings"] = warnings
    payload["repair_hints"] = _unique(repair_hints)
    payload["fixes"] = fixes
    payload["sync_results"] = sync_results
    payload["settings_health"] = settings_state
    payload["migration"] = migration_state
    payload["migration_result"] = migration_result
    payload["recent_errors"] = recent_errors
    payload["disk_waterline"] = disk_waterline
    if verbose or bundle:
        payload["support_bundle"] = build_support_bundle(
            cache_dir=cache_dir,
            status=payload,
            settings_health=settings_state,
            migration_status=migration_state,
            recent_errors=recent_errors,
            disk_waterline=disk_waterline,
        )
    payload["ok"] = not errors
    return payload


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


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


def probe_all_datasets(
    cache_dir: Path,
    *,
    write: bool = True,
    fetch_timeout: float | None = None,
) -> list[dict[str, Any]]:
    if not write:
        return [probe_dataset(cache_dir, dataset.key, write=False) for dataset in list_active_datasets()]
    return sync_all_datasets(cache_dir, fetch_timeout=fetch_timeout)


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
