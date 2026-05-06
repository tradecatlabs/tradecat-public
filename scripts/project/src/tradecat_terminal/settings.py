from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from tradecat_terminal.i18n import SUPPORTED_LANGS, normalize_lang
from tradecat_terminal.registry import get_dataset

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
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_settings(settings: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    target = path or settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    clean = _clean_settings(settings)
    target.write_text(json.dumps(clean, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return clean


def set_setting(key: str, value: str, path: Path | None = None) -> dict[str, Any]:
    settings = load_settings(path)
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
    return save_settings(settings, path)


def unset_setting(key: str, path: Path | None = None) -> dict[str, Any]:
    settings = load_settings(path)
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
    return save_settings(settings, path)


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
