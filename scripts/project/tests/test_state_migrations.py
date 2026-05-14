from __future__ import annotations

import gzip
import json

import pytest

from tradecat_terminal.migrations import migrate_cache, migration_status
from tradecat_terminal.state import (
    DEFAULT_LOCK_TIMEOUT_SECONDS,
    atomic_write_json,
    atomic_write_json_gzip,
    lock_timeout_seconds,
    preserve_corrupt_file,
    read_json_file,
)


def test_lock_timeout_env_is_clamped_and_invalid_values_fall_back(monkeypatch):
    monkeypatch.delenv("TRADECAT_LOCAL_STATE_LOCK_TIMEOUT", raising=False)
    assert lock_timeout_seconds() == DEFAULT_LOCK_TIMEOUT_SECONDS

    monkeypatch.setenv("TRADECAT_LOCAL_STATE_LOCK_TIMEOUT", "bad")
    assert lock_timeout_seconds() == DEFAULT_LOCK_TIMEOUT_SECONDS

    monkeypatch.setenv("TRADECAT_LOCAL_STATE_LOCK_TIMEOUT", "0")
    assert lock_timeout_seconds() == 0.1

    monkeypatch.setenv("TRADECAT_LOCAL_STATE_LOCK_TIMEOUT", "2.5")
    assert lock_timeout_seconds() == 2.5


def test_atomic_json_writes_backup_and_read_json_gzip_round_trip(tmp_path):
    target = tmp_path / "state.json"
    gzip_target = tmp_path / "state.json.gz"

    atomic_write_json(target, {"version": 1})
    atomic_write_json(target, {"version": 2}, backup=True)
    atomic_write_json_gzip(gzip_target, {"compressed": True})

    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 2}
    assert json.loads((tmp_path / "state.json.bak").read_text(encoding="utf-8")) == {"version": 1}
    assert read_json_file(gzip_target) == {"compressed": True}
    with gzip.open(gzip_target, "rt", encoding="utf-8") as file:
        assert json.load(file) == {"compressed": True}


def test_read_json_file_returns_default_for_missing_or_non_object_payload(tmp_path):
    missing = tmp_path / "missing.json"
    array_payload = tmp_path / "array.json"
    array_payload.write_text("[1, 2, 3]", encoding="utf-8")

    assert read_json_file(missing) == {}
    assert read_json_file(missing, default={"ok": False}) == {"ok": False}
    assert read_json_file(array_payload) == {}
    assert read_json_file(array_payload, default={"kind": "fallback"}) == {"kind": "fallback"}


def test_preserve_corrupt_file_leaves_original_and_creates_backup(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text("{broken", encoding="utf-8")

    backup = preserve_corrupt_file(target)

    assert backup is not None
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == "{broken"
    assert target.read_text(encoding="utf-8") == "{broken"


def test_migration_rollback_restores_manifest_when_write_fails(tmp_path, monkeypatch):
    import tradecat_terminal.migrations as migrations

    cache_dir = tmp_path / "cache"
    manifest = cache_dir / "datasets" / "event_stream" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    original = {
        "dataset_key": "event_stream",
        "schema_version": 0,
        "current_hash": "old",
        "snapshots": [],
    }
    manifest.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")

    def broken_atomic_write_json(path, payload):
        path.write_text(json.dumps({"schema_version": 999}, ensure_ascii=False), encoding="utf-8")
        raise RuntimeError("simulated migration write failure")

    monkeypatch.setattr(migrations, "atomic_write_json", broken_atomic_write_json)

    with pytest.raises(RuntimeError, match="simulated migration write failure"):
        migrate_cache(cache_dir, reason="test")

    assert json.loads(manifest.read_text(encoding="utf-8")) == original
    status = migration_status(cache_dir)
    assert status["needed"] is True
    assert status["pending_count"] == 1
