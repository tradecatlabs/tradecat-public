from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tradecat_terminal.registry import list_datasets
from tradecat_terminal.state import atomic_write_json, locked_path, read_json_file

CURRENT_CACHE_SCHEMA_VERSION = 1
MIGRATIONS_SCHEMA = "tradecat.cache_migrations.v1"
BACKUP_DIR = "migration_backups"


def migration_status(cache_dir: Path) -> dict[str, Any]:
    cache_root = Path(cache_dir)
    items = _migration_items(cache_root)
    needs = [item for item in items if item["needs_migration"]]
    return {
        "schema": MIGRATIONS_SCHEMA,
        "current_schema_version": CURRENT_CACHE_SCHEMA_VERSION,
        "needed": bool(needs),
        "pending_count": len(needs),
        "items": items,
        "backup_dir": str(cache_root / BACKUP_DIR),
    }


def migrate_cache(cache_dir: Path, *, reason: str = "manual") -> dict[str, Any]:
    cache_root = Path(cache_dir)
    with locked_path(cache_root / "manifest.json"):
        status = migration_status(cache_root)
        if not status["needed"]:
            return {
                "ok": True,
                "changed": False,
                "reason": reason,
                "backup_dir": "",
                "migrated": [],
                "status": status,
            }
        backup_dir = cache_root / BACKUP_DIR / _stamp()
        migrated: list[dict[str, Any]] = []
        try:
            for item in status["items"]:
                if not item["needs_migration"]:
                    continue
                path = Path(item["path"])
                if not path.exists():
                    continue
                backup_path = backup_dir / path.relative_to(cache_root)
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, backup_path)
                payload = read_json_file(path)
                payload["schema_version"] = CURRENT_CACHE_SCHEMA_VERSION
                payload.setdefault("migrated_from_schema_version", item.get("schema_version"))
                payload["migrated_at"] = _now_iso()
                atomic_write_json(path, payload)
                migrated.append({"path": str(path), "backup": str(backup_path)})
        except Exception:
            if backup_dir.exists():
                _restore_backup(cache_root, backup_dir)
            raise
        return {
            "ok": True,
            "changed": True,
            "reason": reason,
            "backup_dir": str(backup_dir),
            "migrated": migrated,
            "status": migration_status(cache_root),
        }


def _migration_items(cache_dir: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for dataset in list_datasets(include_inactive=True):
        dataset_dir = cache_dir / "datasets" / dataset.key
        for path in (dataset_dir / "manifest.json", dataset_dir / "stream_events.json"):
            if not path.exists():
                continue
            try:
                payload = read_json_file(path)
                schema_version = payload.get("schema_version")
                needs = not isinstance(schema_version, int) or schema_version < CURRENT_CACHE_SCHEMA_VERSION
                error = ""
            except Exception as exc:
                schema_version = None
                needs = False
                error = str(exc)
            items.append(
                {
                    "path": str(path),
                    "dataset_key": dataset.key,
                    "schema_version": schema_version,
                    "target_schema_version": CURRENT_CACHE_SCHEMA_VERSION,
                    "needs_migration": needs,
                    "error": error,
                }
            )
    return items


def _restore_backup(cache_dir: Path, backup_dir: Path) -> None:
    for backup_path in sorted(backup_dir.rglob("*")):
        if not backup_path.is_file():
            continue
        target = cache_dir / backup_path.relative_to(backup_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_path, target)


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _now_iso() -> str:
    return datetime.now(UTC).astimezone().isoformat()
