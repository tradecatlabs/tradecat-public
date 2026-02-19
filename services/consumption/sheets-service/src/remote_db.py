# ruff: noqa: UP017
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RemoteDbSpec:
    mode: str  # off|ssh
    ssh_host: str
    ssh_user: str
    ssh_key_path: str
    remote_db_path: str
    local_db_path: Path
    min_refresh_seconds: int
    meta_path: Path


def _read_meta(path: Path) -> dict[str, str]:
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        out: dict[str, str] = {}
        for k, v in data.items():
            if k is None:
                continue
            out[str(k)] = "" if v is None else str(v)
        return out
    except Exception:
        return {}


def _write_meta(path: Path, kv: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cur = _read_meta(path)
    for k, v in kv.items():
        cur[str(k)] = "" if v is None else str(v)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _ssh_args(*, key_path: str) -> list[str]:
    args = [
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ServerAliveInterval=10",
        "-o",
        "ServerAliveCountMax=3",
    ]
    if key_path:
        args += ["-i", key_path, "-o", "IdentitiesOnly=yes"]
    return args


def _run(cmd: list[str], *, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, text=True, capture_output=True, timeout=timeout_seconds)


def _ssh_run(
    *, user_at_host: str, key_path: str, remote_cmd: str, timeout_seconds: int
) -> subprocess.CompletedProcess[str]:
    return _run(["ssh", *_ssh_args(key_path=key_path), user_at_host, remote_cmd], timeout_seconds=timeout_seconds)


def _scp_get(*, user_at_host: str, key_path: str, remote_path: str, local_path: Path, timeout_seconds: int) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = local_path.with_suffix(local_path.suffix + ".tmp")
    if tmp.exists():
        try:
            tmp.unlink()
        except Exception:
            pass
    res = _run(
        ["scp", *_ssh_args(key_path=key_path), f"{user_at_host}:{remote_path}", str(tmp)],
        timeout_seconds=timeout_seconds,
    )
    if res.returncode != 0:
        raise RuntimeError(f"scp_failed rc={res.returncode} stderr={res.stderr.strip()[:500]}")
    tmp.replace(local_path)


def _rsync_get(*, user_at_host: str, key_path: str, remote_path: str, local_path: Path, timeout_seconds: int) -> None:
    """
    优先使用 rsync（支持断点续传），比 scp 更稳。
    - 写入到 `.part`，成功后原子替换为目标文件
    """
    local_path.parent.mkdir(parents=True, exist_ok=True)
    part = local_path.with_suffix(local_path.suffix + ".part")
    ssh_cmd = ["ssh", *_ssh_args(key_path=key_path)]
    # rsync -e 需要一个字符串命令
    ssh_str = " ".join(ssh_cmd)

    res = _run(
        [
            "rsync",
            "-a",
            "--partial",
            "--inplace",
            "--no-owner",
            "--no-group",
            "-e",
            ssh_str,
            f"{user_at_host}:{remote_path}",
            str(part),
        ],
        timeout_seconds=timeout_seconds,
    )
    if res.returncode != 0:
        raise RuntimeError(f"rsync_failed rc={res.returncode} stderr={res.stderr.strip()[:500]}")
    part.replace(local_path)


def _remote_sig_ssh(*, user_at_host: str, key_path: str, remote_path: str) -> tuple[int, int]:
    # mtime_epoch size_bytes
    cmd = f"stat -c '%Y %s' {sh_quote(remote_path)}"
    res = _ssh_run(user_at_host=user_at_host, key_path=key_path, remote_cmd=cmd, timeout_seconds=15)
    if res.returncode != 0:
        raise RuntimeError(f"remote_stat_failed rc={res.returncode} stderr={res.stderr.strip()[:500]}")
    parts = (res.stdout or "").strip().split()
    if len(parts) < 2:
        raise RuntimeError(f"remote_stat_bad_output:{(res.stdout or '').strip()[:200]}")
    return int(parts[0]), int(parts[1])


def sh_quote(s: str) -> str:
    v = str(s)
    return "'" + v.replace("'", "'\"'\"'") + "'"


def ensure_local_market_db(spec: RemoteDbSpec) -> dict[str, Any]:
    """
    准备一个本地可读的 market_data.db：
    - mode=off：不做任何事
    - mode=ssh：通过 ssh/scp 拉取远程 DB 到 local_db_path（带最小刷新间隔与签名缓存）
    - 会写入 meta_path（JSON）记录 remote_db.*，避免每轮重复拉取
    """
    mode = (spec.mode or "off").strip().lower()
    if mode not in {"off", "ssh"}:
        mode = "off"
    if mode == "off":
        return {"ok": True, "mode": "off"}

    if not spec.ssh_host or not spec.remote_db_path:
        return {"ok": False, "mode": mode, "error": "missing_ssh_host_or_remote_db_path"}

    user = (spec.ssh_user or "nvidia").strip() or "nvidia"
    uah = f"{user}@{spec.ssh_host}"
    key_path = (spec.ssh_key_path or "").strip()

    now = int(time.time())
    meta = _read_meta(spec.meta_path)
    try:
        last_pull = int(str(meta.get("remote_db.last_pull_epoch") or "0").strip() or "0")
    except Exception:
        last_pull = 0

    # 最小刷新间隔：避免每次 --once 都 scp 170MB
    if spec.local_db_path.exists() and spec.min_refresh_seconds > 0 and (now - last_pull) < spec.min_refresh_seconds:
        os.environ["MARKET_DATA_DB_PATH"] = str(spec.local_db_path)
        os.environ["TELEGRAM_MARKET_DATA_DB_PATH"] = str(spec.local_db_path)
        return {
            "ok": True,
            "mode": mode,
            "action": "skip_by_interval",
            "local_db": str(spec.local_db_path),
            "age_seconds": int(now - last_pull),
        }

    mtime, size = _remote_sig_ssh(user_at_host=uah, key_path=key_path, remote_path=spec.remote_db_path)
    sig = f"{mtime}:{size}"

    prev_sig = str(meta.get("remote_db.sig") or "").strip()
    if spec.local_db_path.exists() and prev_sig == sig:
        _write_meta(spec.meta_path, {"remote_db.last_pull_epoch": str(now)})
        os.environ["MARKET_DATA_DB_PATH"] = str(spec.local_db_path)
        os.environ["TELEGRAM_MARKET_DATA_DB_PATH"] = str(spec.local_db_path)
        return {"ok": True, "mode": mode, "action": "skip_same_sig", "sig": sig, "local_db": str(spec.local_db_path)}

    # 兼容历史残留：scp 的 `.tmp` 若存在，迁移为 rsync 的 `.part` 以便断点续传
    tmp = spec.local_db_path.with_suffix(spec.local_db_path.suffix + ".tmp")
    part = spec.local_db_path.with_suffix(spec.local_db_path.suffix + ".part")
    if tmp.exists() and (not part.exists()):
        try:
            tmp.replace(part)
        except Exception:
            pass

    # 更稳：优先 rsync（支持断点续传）；失败再退回 scp
    try:
        _rsync_get(
            user_at_host=uah,
            key_path=key_path,
            remote_path=spec.remote_db_path,
            local_path=spec.local_db_path,
            timeout_seconds=3600,
        )
    except Exception:
        _scp_get(
            user_at_host=uah,
            key_path=key_path,
            remote_path=spec.remote_db_path,
            local_path=spec.local_db_path,
            timeout_seconds=3600,
        )
    _write_meta(
        spec.meta_path,
        {
            "remote_db.mode": mode,
            "remote_db.host": spec.ssh_host,
            "remote_db.user": user,
            "remote_db.remote_path": spec.remote_db_path,
            "remote_db.local_path": str(spec.local_db_path),
            "remote_db.sig": sig,
            "remote_db.last_pull_epoch": str(now),
        },
    )

    os.environ["MARKET_DATA_DB_PATH"] = str(spec.local_db_path)
    os.environ["TELEGRAM_MARKET_DATA_DB_PATH"] = str(spec.local_db_path)
    return {"ok": True, "mode": mode, "action": "pulled", "sig": sig, "local_db": str(spec.local_db_path)}
