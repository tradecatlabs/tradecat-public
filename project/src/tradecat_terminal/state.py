from __future__ import annotations

import gzip
import json
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

LOCK_TIMEOUT_ENV = "TRADECAT_LOCAL_STATE_LOCK_TIMEOUT"
DEFAULT_LOCK_TIMEOUT_SECONDS = 10.0


class LocalStateLockError(RuntimeError):
    def __init__(self, path: Path, timeout: float) -> None:
        self.path = path
        self.timeout = timeout
        super().__init__(f"local state lock timeout: {path} after {timeout:g}s")


def lock_timeout_seconds() -> float:
    raw = os.environ.get(LOCK_TIMEOUT_ENV, "").strip()
    if not raw:
        return DEFAULT_LOCK_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_LOCK_TIMEOUT_SECONDS
    return max(0.1, value)


@contextmanager
def locked_path(path: Path, *, timeout: float | None = None) -> Iterator[Path]:
    target = Path(path)
    lock_path = _lock_path(target)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    wait_seconds = lock_timeout_seconds() if timeout is None else max(0.1, float(timeout))
    lock = FileLock(str(lock_path), timeout=wait_seconds)
    try:
        with lock:
            yield lock_path
    except Timeout as exc:
        raise LocalStateLockError(lock_path, wait_seconds) from exc


def atomic_write_json(path: Path, payload: dict[str, Any], *, backup: bool = False) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_write_text(path, text, backup=backup)


def atomic_write_text(path: Path, text: str, *, backup: bool = False) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if backup and target.exists():
        shutil.copy2(target, backup_path(target))
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()


def atomic_write_json_gzip(path: Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    os.close(fd)
    tmp = Path(tmp_name)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        with gzip.open(tmp, "wt", encoding="utf-8") as file:
            file.write(text)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()


def read_json_file(path: Path, *, default: dict[str, Any] | None = None) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {} if default is None else dict(default)
    if target.name.endswith(".gz"):
        with gzip.open(target, "rt", encoding="utf-8") as file:
            payload = json.load(file)
    else:
        payload = json.loads(target.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else ({} if default is None else dict(default))


def backup_path(path: Path) -> Path:
    return Path(str(path) + ".bak")


def corrupt_backup_path(path: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path(str(path) + f".corrupt-{stamp}.bak")


def preserve_corrupt_file(path: Path) -> Path | None:
    target = Path(path)
    if not target.exists():
        return None
    backup = corrupt_backup_path(target)
    shutil.copy2(target, backup)
    return backup


def _lock_path(path: Path) -> Path:
    target = Path(path)
    if target.suffix:
        return target.with_name(f"{target.name}.lock")
    return target / ".lock"
