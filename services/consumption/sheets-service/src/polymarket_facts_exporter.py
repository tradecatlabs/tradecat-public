# ruff: noqa: UP017
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.polymarket_exporter import PolymarketStatsSheet, _coerce_number

def _parse_ts_utc(v: object) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(float(v), tz=timezone.utc)
        except Exception:
            return None
    if not isinstance(v, str):
        return None

    s = v.strip()
    if not s:
        return None
    # 支持：2026-02-21T15:17:54Z / 2026-02-21T15:17:54+00:00
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _iter_jsonl_lines(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in (text or "").splitlines():
        s = str(raw or "").strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _read_local_jsonl_files(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for obj in _iter_jsonl_lines(text):
            records.append(obj)
    return records


def _read_ssh_jsonl_glob(
    *,
    ssh_host: str,
    ssh_user: str,
    ssh_key_path: str,
    glob_pattern: str,
    timeout_seconds: int,
    max_bytes: int,
) -> str:
    host = (ssh_host or "").strip()
    if not host:
        raise RuntimeError("missing_ssh_host")
    user = (ssh_user or "nvidia").strip() or "nvidia"
    uah = f"{user}@{host}"

    key_path = (ssh_key_path or "").strip()
    ssh_args = [
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
        ssh_args += ["-i", key_path, "-o", "IdentitiesOnly=yes"]

    # 只拉最后 N 字节，避免 jsonl 日志过大导致超时/内存压力
    # NOTE: tail -c 对多文件 glob 需要 shell 展开，因此用 bash -lc
    tail_clause = f"tail -c {int(max_bytes)}" if int(max_bytes) > 0 else "cat"
    remote_cmd = "\n".join(
        [
            "set -e",
            f"ls -1 {glob_pattern} 1>/dev/null 2>/dev/null || exit 0",
            f"cat {glob_pattern} | {tail_clause}",
        ]
    )
    res = subprocess.run(
        ["ssh", *ssh_args, uah, "bash", "-lc", remote_cmd],
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    out = (res.stdout or "") + ("\n" + res.stderr if res.stderr else "")
    if res.returncode != 0:
        raise RuntimeError(f"remote_read_failed rc={res.returncode} out={out.strip()[:800]}")
    return res.stdout or ""


def export_polymarket_facts_events_sheet(*, lang: str = "zh_CN") -> PolymarketStatsSheet:
    """
    导出 Polymarket facts（结构化 JSONL）事件表：
    - 优先 ssh 读取远端 facts（若配置了 host），否则读本机目录
    - 仅展示最近 24h（为看板/审计台账服务，避免写入配额爆炸）
    """
    mode = (os.environ.get("SHEETS_POLYMARKET_FACTS_MODE", "auto") or "auto").strip().lower()
    if mode not in {"auto", "local", "ssh"}:
        mode = "auto"

    now_dt = datetime.now(timezone.utc).replace(microsecond=0)
    tz8 = timezone(timedelta(hours=8))
    now = now_dt.astimezone(tz8).isoformat()
    since_dt = now_dt - timedelta(hours=24)

    timeout_seconds = int((os.environ.get("SHEETS_POLYMARKET_FACTS_TIMEOUT_SECONDS", "20") or "20").strip() or "20")
    max_mb = int((os.environ.get("SHEETS_POLYMARKET_FACTS_MAX_MB", "10") or "10").strip() or "10")
    max_bytes = int(max_mb) * 1024 * 1024 if int(max_mb) > 0 else 0

    facts_dir = (os.environ.get("SHEETS_POLYMARKET_FACTS_DIR", "") or "").strip()
    if not facts_dir:
        facts_dir = str(Path.home() / ".local" / "state" / "tradecat" / "polymarket" / "facts")
    facts_dir = str(Path(facts_dir).expanduser())

    # ssh 默认复用 remote-db 的 ssh 参数（否则用户要配两遍）
    ssh_host = (
        os.environ.get("SHEETS_POLYMARKET_SSH_HOST", "") or os.environ.get("SHEETS_REMOTE_DB_SSH_HOST", "") or ""
    ).strip()
    ssh_user = (
        os.environ.get("SHEETS_POLYMARKET_SSH_USER", "")
        or os.environ.get("SHEETS_REMOTE_DB_SSH_USER", "nvidia")
        or "nvidia"
    ).strip()
    ssh_key_path = (
        os.environ.get("SHEETS_POLYMARKET_SSH_KEY_PATH", "") or os.environ.get("SHEETS_REMOTE_DB_SSH_KEY_PATH", "") or ""
    ).strip()

    # auto：优先 ssh（如果配置了 host），否则 local
    eff_mode = mode
    if eff_mode == "auto":
        eff_mode = "ssh" if ssh_host else "local"

    # 读取最近两天（跨日边界），再按 since 过滤
    day0 = now_dt.date().isoformat()
    day1 = (now_dt.date() - timedelta(days=1)).isoformat()

    records: list[dict[str, Any]] = []
    source_desc = ""
    path_desc = ""

    try:
        if eff_mode == "ssh":
            glob_pattern = " ".join(
                [
                    sh_quote(f"{facts_dir}/events/{day1}.jsonl"),
                    sh_quote(f"{facts_dir}/events/{day0}.jsonl"),
                ]
            )
            text = _read_ssh_jsonl_glob(
                ssh_host=ssh_host,
                ssh_user=ssh_user,
                ssh_key_path=ssh_key_path,
                glob_pattern=glob_pattern,
                timeout_seconds=timeout_seconds,
                max_bytes=max_bytes,
            )
            records = _iter_jsonl_lines(text)
            source_desc = f"ssh，{ssh_user}@{ssh_host}"
            path_desc = f"facts，{facts_dir}，events，{day1}/{day0}"
        else:
            p_dir = Path(facts_dir).expanduser().resolve()
            paths = [
                (p_dir / "events" / f"{day1}.jsonl").resolve(),
                (p_dir / "events" / f"{day0}.jsonl").resolve(),
            ]
            records = _read_local_jsonl_files(paths)
            source_desc = "local"
            path_desc = f"facts，{p_dir}，events，{day1}/{day0}"
    except Exception as exc:
        meta_text = f"数据源，PolymarketFacts，导出时间(UTC+8)，{now}，语言，{lang}，错误，{type(exc).__name__}:{exc}"
        return PolymarketStatsSheet(
            values=[[meta_text]],
            panel_title_rows=[],
            panel_header_rows=[],
            merge_ranges=[(0, 1, 0, 1)],
            n_rows=1,
            n_cols=1,
        )

    # 过滤 + 规范化
    rows: list[tuple[datetime, dict[str, Any]]] = []
    for obj in records:
        ts = _parse_ts_utc(obj.get("ts_utc") or obj.get("ts") or obj.get("timestamp"))
        if ts is None:
            continue
        if ts < since_dt:
            continue
        rows.append((ts, obj))

    rows.sort(key=lambda x: x[0], reverse=True)

    # 限制行数，避免写入配额/样式请求爆炸
    try:
        limit = int((os.environ.get("SHEETS_POLYMARKET_FACTS_EVENTS_LIMIT", "400") or "400").strip() or "400")
    except Exception:
        limit = 400
    if limit > 0:
        rows = rows[: int(limit)]

    meta_text = (
        f"数据源，PolymarketFacts，导出时间(UTC+8)，{now}，语言，{lang}，模式，{source_desc}，{path_desc}，"
        f"窗口，24h，事件数，{len(rows)}"
    )
    values: list[list[Any]] = [[meta_text]]
    values.append(
        [
            "时间(UTC)",
            "event_key",
            "模块",
            "类型",
            "市场",
            "方向",
            "价格",
            "数量",
            "分数",
            "链接",
        ]
    )

    for ts, obj in rows:
        event_key = str(obj.get("event_key") or obj.get("key") or "").strip()
        module = str(obj.get("module") or obj.get("module_name") or obj.get("source_module") or "").strip()
        event_type = str(obj.get("event_type") or obj.get("type") or "signal").strip()
        market = str(
            obj.get("market_title")
            or obj.get("market")
            or obj.get("question")
            or obj.get("title")
            or obj.get("market_id")
            or ""
        ).strip()
        side = str(obj.get("side") or obj.get("direction") or "").strip()
        price = _coerce_number(obj.get("price"))
        size = _coerce_number(obj.get("size") or obj.get("qty"))
        score = _coerce_number(obj.get("score") or obj.get("profit_pct") or obj.get("imbalance"))
        url = str(obj.get("url") or obj.get("market_url") or obj.get("link") or "").strip()

        values.append(
            [
                ts.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                event_key,
                module,
                event_type,
                market,
                side,
                price if price is not None else "",
                size if size is not None else "",
                score if score is not None else "",
                url,
            ]
        )

    n_cols = max((len(r) for r in values if isinstance(r, list)), default=1)
    for r in values:
        if isinstance(r, list) and len(r) < n_cols:
            r.extend([""] * (n_cols - len(r)))

    merge_ranges: list[tuple[int, int, int, int]] = []
    if n_cols > 1:
        merge_ranges.append((0, 1, 0, int(n_cols)))

    return PolymarketStatsSheet(
        values=values,
        panel_title_rows=[],
        panel_header_rows=[2],  # 1-based
        merge_ranges=merge_ranges,
        n_rows=len(values),
        n_cols=n_cols,
    )
