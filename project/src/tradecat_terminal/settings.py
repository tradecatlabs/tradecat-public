from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from tradecat_terminal.i18n import SUPPORTED_LANGS, normalize_lang
from tradecat_terminal.registry import get_dataset
from tradecat_terminal.state import atomic_write_text, backup_path, locked_path, preserve_corrupt_file

DEFAULT_APP_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS_PATH = DEFAULT_APP_ROOT / ".tradecat" / "settings.json"
SETTINGS_PATH_ENV = "TRADECAT_SETTINGS_PATH"

SCALAR_KEYS = {
    "cache_dir",
    "default_dataset",
    "default_lang",
    "tui_probe_interval_seconds",
    "tui_fetch_timeout_seconds",
}


def settings_path() -> Path:
    return Path(os.environ.get(SETTINGS_PATH_ENV, str(DEFAULT_SETTINGS_PATH))).expanduser()


def load_settings(path: Path | None = None) -> dict[str, Any]:
    target = path or settings_path()
    if not target.exists():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        preserve_corrupt_file(target)
        return {}
    except OSError:
        return {}
    return payload if isinstance(payload, dict) else {}


def save_settings(settings: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    target = path or settings_path()
    with locked_path(target):
        clean = _clean_settings(settings)
        atomic_write_text(
            target,
            json.dumps(clean, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            backup=True,
        )
        return clean


def set_setting(key: str, value: str, path: Path | None = None) -> dict[str, Any]:
    target = path or settings_path()
    with locked_path(target):
        settings = load_settings(target)
        normalized_key = key.strip()
        if normalized_key in SCALAR_KEYS:
            settings[normalized_key] = _parse_scalar(normalized_key, value)
        elif normalized_key.startswith("tui_probe_interval."):
            dataset_key = normalized_key.split(".", maxsplit=1)[1]
            get_dataset(dataset_key)
            bucket = settings.setdefault("tui_probe_intervals", {})
            if not isinstance(bucket, dict):
                bucket = {}
                settings["tui_probe_intervals"] = bucket
            bucket[dataset_key] = _parse_float(value, normalized_key)
        elif normalized_key.startswith("tui_fetch_timeout."):
            dataset_key = normalized_key.split(".", maxsplit=1)[1]
            get_dataset(dataset_key)
            bucket = settings.setdefault("tui_fetch_timeouts", {})
            if not isinstance(bucket, dict):
                bucket = {}
                settings["tui_fetch_timeouts"] = bucket
            bucket[dataset_key] = _parse_float(value, normalized_key)
        else:
            raise ValueError(f"未知配置键：{key}")
        return _save_settings_unlocked(settings, target)


def unset_setting(key: str, path: Path | None = None) -> dict[str, Any]:
    target = path or settings_path()
    with locked_path(target):
        settings = load_settings(target)
        normalized_key = key.strip()
        if normalized_key in SCALAR_KEYS:
            settings.pop(normalized_key, None)
        elif normalized_key.startswith("tui_probe_interval."):
            dataset_key = normalized_key.split(".", maxsplit=1)[1]
            bucket = settings.get("tui_probe_intervals")
            if isinstance(bucket, dict):
                bucket.pop(dataset_key, None)
        elif normalized_key.startswith("tui_fetch_timeout."):
            dataset_key = normalized_key.split(".", maxsplit=1)[1]
            bucket = settings.get("tui_fetch_timeouts")
            if isinstance(bucket, dict):
                bucket.pop(dataset_key, None)
        else:
            raise ValueError(f"未知配置键：{key}")
        return _save_settings_unlocked(settings, target)


def settings_health(path: Path | None = None) -> dict[str, Any]:
    target = path or settings_path()
    payload: dict[str, Any] = {
        "path": str(target),
        "exists": target.exists(),
        "status": "missing",
        "backup": str(backup_path(target)) if backup_path(target).exists() else "",
    }
    if not target.exists():
        return payload
    try:
        parsed = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        corrupt = preserve_corrupt_file(target)
        payload.update(
            {
                "status": "corrupt",
                "error": str(exc),
                "corrupt_backup": str(corrupt or ""),
            }
        )
        return payload
    except OSError as exc:
        payload.update({"status": "unreadable", "error": str(exc)})
        return payload
    if not isinstance(parsed, dict):
        payload.update({"status": "invalid", "error": "settings root must be an object"})
        return payload
    payload.update({"status": "ok", "key_count": len(parsed)})
    return payload


def default_dataset_from_settings() -> str | None:
    value = load_settings().get("default_dataset")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        get_dataset(value.strip())
    except ValueError:
        return None
    return value.strip()


def default_lang_from_settings() -> str | None:
    value = normalize_lang(str(load_settings().get("default_lang") or ""))
    return value if value in SUPPORTED_LANGS else None


def cache_dir_from_settings() -> str | None:
    value = load_settings().get("cache_dir")
    return str(value) if isinstance(value, str) and value.strip() else None


def tui_probe_interval_from_settings(dataset_key: str | None = None) -> float | None:
    settings = load_settings()
    if dataset_key:
        bucket = settings.get("tui_probe_intervals")
        if isinstance(bucket, dict) and dataset_key in bucket:
            return _optional_float(bucket.get(dataset_key))
    return _optional_float(settings.get("tui_probe_interval_seconds"))


def tui_fetch_timeout_from_settings(dataset_key: str | None = None) -> float | None:
    settings = load_settings()
    if dataset_key:
        bucket = settings.get("tui_fetch_timeouts")
        if isinstance(bucket, dict) and dataset_key in bucket:
            return _optional_float(bucket.get(dataset_key))
    return _optional_float(settings.get("tui_fetch_timeout_seconds"))


def _clean_settings(settings: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key in sorted(SCALAR_KEYS):
        if key in settings and settings[key] not in {None, ""}:
            clean[key] = settings[key]
    for key in ("tui_probe_intervals", "tui_fetch_timeouts"):
        bucket = settings.get(key)
        if isinstance(bucket, dict):
            clean[key] = {str(name): value for name, value in sorted(bucket.items()) if value not in {None, ""}}
    return clean


def _save_settings_unlocked(settings: dict[str, Any], target: Path) -> dict[str, Any]:
    clean = _clean_settings(settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.copy2(target, backup_path(target))
    atomic_write_text(target, json.dumps(clean, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return clean


def _parse_scalar(key: str, value: str) -> str | float:
    if key == "default_lang":
        lang = normalize_lang(value)
        if not lang:
            raise ValueError("default_lang 必须是 zh / en / ko")
        return lang
    if key == "default_dataset":
        get_dataset(value)
        return value
    if key in {"tui_probe_interval_seconds", "tui_fetch_timeout_seconds"}:
        return _parse_float(value, key)
    return value


def _parse_float(value: str, key: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{key} 必须是数字") from exc
    if parsed <= 0:
        raise ValueError(f"{key} 必须大于 0")
    return parsed


def _optional_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
