from __future__ import annotations

import json
import os
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tradecat_terminal import __version__
from tradecat_terminal.state import atomic_write_json, locked_path, read_json_file

DIAGNOSTICS_DIR = "diagnostics"
RECENT_ERRORS_FILE = "recent_errors.json"
RECENT_ERROR_LIMIT = 50
CACHE_WARN_BYTES = 100 * 1024 * 1024
CACHE_CRITICAL_BYTES = 500 * 1024 * 1024


def record_recent_error(
    cache_dir: Path,
    *,
    source: str,
    dataset_key: str | None,
    error: dict[str, Any],
) -> None:
    path = recent_errors_path(cache_dir)
    with locked_path(path):
        payload = read_json_file(path, default={"errors": []})
        errors = list(payload.get("errors") or [])
        errors.insert(
            0,
            {
                "at": _now_iso(),
                "source": source,
                "dataset_key": dataset_key or "",
                "error": sanitize_error(error),
            },
        )
        atomic_write_json(path, {"schema": "tradecat.recent_errors.v1", "errors": errors[:RECENT_ERROR_LIMIT]})


def load_recent_errors(cache_dir: Path, *, limit: int = 10) -> list[dict[str, Any]]:
    payload = read_json_file(recent_errors_path(cache_dir), default={"errors": []})
    return [item for item in list(payload.get("errors") or [])[: max(0, int(limit))] if isinstance(item, dict)]


def recent_errors_path(cache_dir: Path) -> Path:
    return Path(cache_dir) / DIAGNOSTICS_DIR / RECENT_ERRORS_FILE


def sanitize_error(error: dict[str, Any] | Exception | str) -> dict[str, Any]:
    if hasattr(error, "to_dict"):
        raw = error.to_dict()  # type: ignore[union-attr]
    elif isinstance(error, dict):
        raw = dict(error)
    else:
        raw = {"code": "unknown_error", "message": str(error), "kind": "unknown", "retryable": False}
    allowed = {
        "code",
        "kind",
        "message",
        "hint",
        "retryable",
        "status",
        "attempts",
        "url_host",
    }
    return {key: raw[key] for key in allowed if key in raw and raw[key] not in {None, ""}}


def cache_waterline(status: dict[str, Any], *, warn_bytes: int | None = None) -> dict[str, Any]:
    if warn_bytes is None:
        warn_bytes = _cache_warn_bytes()
    cache_bytes = int(status.get("cache_bytes") or 0)
    datasets = list(status.get("datasets") or [])
    largest = sorted(
        (
            {
                "dataset_key": str(item.get("dataset_key") or ""),
                "cache_bytes": int(item.get("cache_bytes") or 0),
                "snapshot_count": int(item.get("snapshot_count") or 0),
            }
            for item in datasets
            if isinstance(item, dict)
        ),
        key=lambda item: item["cache_bytes"],
        reverse=True,
    )
    level = "ok"
    if cache_bytes >= CACHE_CRITICAL_BYTES:
        level = "critical"
    elif cache_bytes >= int(warn_bytes):
        level = "warning"
    return {
        "level": level,
        "cache_bytes": cache_bytes,
        "warn_bytes": int(warn_bytes),
        "critical_bytes": CACHE_CRITICAL_BYTES,
        "largest_datasets": largest[:5],
        "hint": "执行 tradecat prune --max-snapshots 20 预览清理计划；确认后再加 --apply",
    }


def _cache_warn_bytes() -> int:
    raw = os.environ.get("TRADECAT_CACHE_WARN_BYTES", "").strip()
    if not raw:
        return CACHE_WARN_BYTES
    try:
        return max(1, int(raw))
    except ValueError:
        return CACHE_WARN_BYTES


def build_support_bundle(
    *,
    cache_dir: Path,
    status: dict[str, Any],
    settings_health: dict[str, Any],
    migration_status: dict[str, Any],
    recent_errors: list[dict[str, Any]],
    disk_waterline: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": "tradecat.support_bundle.v1",
        "schema_version": "1.0.0",
        "generated_at": _now_iso(),
        "app": {"name": "tradecat-terminal", "version": __version__},
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "executable": Path(sys.executable).name,
        },
        "cache": {
            "cache_dir": str(cache_dir),
            "exists": bool(status.get("exists")),
            "dataset_count": int(status.get("dataset_count") or 0),
            "ready_dataset_count": int(status.get("ready_dataset_count") or 0),
            "missing_dataset_count": int(status.get("missing_dataset_count") or 0),
            "cache_bytes": int(status.get("cache_bytes") or 0),
            "datasets": [
                {
                    "dataset_key": item.get("dataset_key"),
                    "active": item.get("active"),
                    "cache_state": item.get("cache_state"),
                    "snapshot_count": item.get("snapshot_count"),
                    "event_count": item.get("event_count"),
                    "row_count": item.get("row_count"),
                    "column_count": item.get("column_count"),
                    "cache_bytes": item.get("cache_bytes"),
                    "fetched_at": item.get("fetched_at"),
                }
                for item in status.get("datasets", [])
                if isinstance(item, dict)
            ],
        },
        "settings": settings_health,
        "migration": migration_status,
        "disk_waterline": disk_waterline,
        "recent_errors": recent_errors,
    }


def write_support_bundle(path: Path, bundle: dict[str, Any]) -> Path:
    target = Path(path).expanduser()
    atomic_write_json(target, bundle)
    return target


def bundle_to_json(bundle: dict[str, Any]) -> str:
    return json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _now_iso() -> str:
    return datetime.now(UTC).astimezone().isoformat()
