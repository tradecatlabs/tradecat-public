# ruff: noqa: UP017
from __future__ import annotations

import csv
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.remote_db import sh_quote
from src.repo import find_repo_root


@dataclass(frozen=True)
class PolymarketStatsSheet:
    """
    Polymarket CSV 统计导出（写入 Google Sheets 的真表格）。

    values: 2D 表格（每个元素为单元格值；尽量保留 number 以便排序/图表）
    panel_title_rows/panel_header_rows: 1-based 行号，用于 writer 上色/合并
    merge_ranges: 0-based merge 范围 (r0,r1,c0,c1) end exclusive
    """

    values: list[list[Any]]
    panel_title_rows: list[int]
    panel_header_rows: list[int]
    merge_ranges: list[tuple[int, int, int, int]]
    n_rows: int
    n_cols: int


_NUM_SUFFIX = {
    "K": 1_000.0,
    "M": 1_000_000.0,
    "B": 1_000_000_000.0,
    "T": 1_000_000_000_000.0,
}


def _coerce_number(v: object) -> float | int | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return v

    if not isinstance(v, str):
        return None

    s = v.strip()
    if not s or s == "-":
        return None

    sign = 1.0
    if s[0] == "+":
        s = s[1:].strip()
    elif s[0] == "-":
        sign = -1.0
        s = s[1:].strip()

    is_percent = s.endswith("%")
    if is_percent:
        s = s[:-1].strip()

    mult = 1.0
    if s and s[-1].upper() in _NUM_SUFFIX:
        mult = _NUM_SUFFIX[s[-1].upper()]
        s = s[:-1].strip()

    s = s.replace(",", "")
    try:
        x = float(s)
    except Exception:
        return None

    x = sign * x * mult
    # 百分号按“百分数”保留（例如 "0.15%" -> 0.15），不转小数 0.0015
    if is_percent:
        return int(x) if float(int(x)) == x else x
    return int(x) if float(int(x)) == x else x


def _detect_polymarket_service_dir() -> Path | None:
    """
    尽量自动定位 polymarket 服务目录；找不到则返回 None（由上层决定是否降级/报错）。
    """
    env_dir = (os.environ.get("SHEETS_POLYMARKET_SERVICE_DIR", "") or "").strip()
    if env_dir:
        p = Path(env_dir).expanduser()
        return p if p.is_dir() else None

    start = Path(__file__).resolve()
    try:
        repo_root = find_repo_root(start)
    except Exception:
        repo_root = None

    candidates: list[Path] = []
    if repo_root is not None:
        candidates += [
            repo_root / "services-preview" / "predict-service" / "services" / "polymarket",
            repo_root / "services" / "polymarket",
        ]
    candidates += [
        Path.home() / ".projects" / "tradecat" / "services-preview" / "predict-service" / "services" / "polymarket",
    ]

    for p in candidates:
        if p.is_dir() and (p / "scripts" / "csv-report.js").is_file():
            return p
    return None


def _default_log_path(service_dir: Path) -> Path:
    env_log = (os.environ.get("SHEETS_POLYMARKET_LOG_FILE", "") or "").strip()
    if env_log:
        p = Path(env_log).expanduser()
        if p.is_absolute():
            return p
        return (service_dir / p).resolve()
    # 现实部署中 polymarket 往往由 systemd user service 托管，
    # stdout/stderr 会落在 $HOME/.local/state/tradecat/polymarket.log（而不是服务目录下 logs/）。
    # 为了“开箱即用”，优先使用该路径（若存在），否则回退旧日志路径。
    runtime_log = (Path.home() / ".local" / "state" / "tradecat" / "polymarket.log").resolve()
    if runtime_log.exists():
        return runtime_log
    return (service_dir / "logs" / "polymarket_bot.log").resolve()


def _run_local_csv_report(
    *,
    service_dir: Path,
    log_path: Path,
    timeout_seconds: int,
    translate: bool,
    api_rankings: bool,
    max_log_bytes: int,
) -> str:
    if not service_dir.is_dir():
        raise RuntimeError(f"missing_service_dir:{service_dir}")
    script = service_dir / "scripts" / "csv-report.js"
    if not script.is_file():
        raise RuntimeError(f"missing_csv_report_js:{script}")
    if not log_path.exists():
        raise RuntimeError(f"missing_log:{log_path}")
    try:
        size = int(log_path.stat().st_size)
    except Exception:
        size = -1
    if max_log_bytes > 0 and size > max_log_bytes:
        raise RuntimeError(f"log_too_large bytes={size} limit={max_log_bytes} path={log_path}")

    env = os.environ.copy()
    env["CSV_TRANSLATE"] = "true" if translate else "false"
    env["CSV_ENABLE_API_RANKINGS"] = "true" if api_rankings else "false"

    res = subprocess.run(
        ["node", "scripts/csv-report.js", str(log_path)],
        cwd=str(service_dir),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    out = (res.stdout or "") + ("\n" + res.stderr if res.stderr else "")
    if res.returncode != 0:
        raise RuntimeError(f"csv_report_failed rc={res.returncode} out={out.strip()[:800]}")
    return out


def _run_ssh_csv_report(
    *,
    ssh_host: str,
    ssh_user: str,
    ssh_key_path: str,
    service_dir: str,
    log_path: str,
    timeout_seconds: int,
    translate: bool,
    api_rankings: bool,
    max_log_bytes: int,
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

    # 先检查日志大小，避免误扫 7GB 导致 node 卡死/超时
    if max_log_bytes > 0:
        stat_cmd = "\n".join(
            [
                "set -e",
                f"cd {sh_quote(service_dir)}",
                f"stat -c '%s' {sh_quote(log_path)}",
            ]
        )
        stat_res = subprocess.run(
            ["ssh", *ssh_args, uah, stat_cmd],
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        if stat_res.returncode != 0:
            raise RuntimeError(f"remote_stat_failed rc={stat_res.returncode} stderr={stat_res.stderr.strip()[:500]}")
        try:
            size = int((stat_res.stdout or "").strip().split()[0])
        except Exception:
            size = -1
        if size > max_log_bytes:
            raise RuntimeError(f"remote_log_too_large bytes={size} limit={max_log_bytes} path={log_path}")

    env_pairs = [
        f"CSV_TRANSLATE={'true' if translate else 'false'}",
        f"CSV_ENABLE_API_RANKINGS={'true' if api_rankings else 'false'}",
    ]
    remote_cmd = "\n".join(
        [
            "set -e",
            f"cd {sh_quote(service_dir)}",
            " ".join(["env", *env_pairs, "node", "scripts/csv-report.js", sh_quote(log_path), "2>&1"]),
        ]
    )
    res = subprocess.run(
        ["ssh", *ssh_args, uah, remote_cmd],
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    out = (res.stdout or "") + ("\n" + res.stderr if res.stderr else "")
    if res.returncode != 0:
        raise RuntimeError(f"remote_csv_report_failed rc={res.returncode} out={out.strip()[:800]}")
    return out


def _parse_sectioned_csv(text: str) -> tuple[list[list[Any]], list[int], list[int]]:
    """
    解析 node csv-report.js 的 stdout：
    - 按 `# ` 分段
    - 每段：第一个 CSV 行视为表头
    - 返回：values（不含 meta 行）、title_rows_0based、header_rows_0based
    """
    lines = (text or "").splitlines()
    sections: list[tuple[str, list[str]]] = []
    cur_title = "Polymarket统计"
    cur_lines: list[str] = []

    def flush() -> None:
        nonlocal cur_title, cur_lines
        if cur_lines:
            sections.append((cur_title, cur_lines))
        cur_lines = []

    for raw in lines:
        s = str(raw or "").rstrip("\n")
        if s.startswith("#"):
            flush()
            cur_title = s.lstrip("#").strip() or "未命名分段"
            continue
        if not s.strip():
            continue
        cur_lines.append(s)
    flush()

    values: list[list[Any]] = []
    title_rows: list[int] = []
    header_rows: list[int] = []

    for title, csv_lines in sections:
        if not csv_lines:
            continue
        title_rows.append(len(values))
        values.append([str(title)])

        # csv 逐行解析
        reader = csv.reader(csv_lines)
        header = None
        rows: list[list[Any]] = []
        for row in reader:
            if not row:
                continue
            if header is None:
                header = [c.strip() for c in row]
                continue
            parsed: list[Any] = []
            for c in row:
                c2 = str(c).strip()
                num = _coerce_number(c2)
                parsed.append(num if num is not None else c2)
            rows.append(parsed)

        if header is None:
            # 分段只有标题，没有 CSV 表头（异常输出）
            continue

        # -------------------- compact: merge consecutive identical rows --------------------
        # 用户需求：把大量“小时=00:00..10:00, 信号数=0, 环比=N/A, 其余空”的行压缩合并成一行：
        #   00:00–10:00  0  N/A ...
        # 原则：无损压缩（只在“相邻行除第一列外完全一致”时才合并）
        enable_compact = (os.environ.get("SHEETS_POLYMARKET_COMPACT_TABLE_ROWS", "1") or "1").strip() != "0"
        if enable_compact:
            try:
                rows = _compact_consecutive_rows_if_applicable(header=header, rows=rows)
            except Exception:
                # 压缩是纯展示优化：失败不应影响导出
                pass

        header_rows.append(len(values))
        values.append([str(c) for c in header])
        values.extend(rows)

    return values, title_rows, header_rows


_HOUR_RE = re.compile(r"^\d{2}:\d{2}$")


def _compact_consecutive_rows_if_applicable(*, header: list[str], rows: list[list[Any]]) -> list[list[Any]]:
    """
    将“相邻行（除第 1 列外）完全相同”的连续区间压缩为一行，首列改为 `start–end`。
    - 只对“小时分布”这种表启用（避免误伤排名/榜单）。
    """
    if not rows or not header:
        return rows

    h0 = str(header[0] or "").strip()
    if h0 not in {"小时", "hour", "Hour"}:
        return rows

    # hour col must look like HH:MM for most rows
    ok_cnt = 0
    for r in rows[: min(len(rows), 6)]:
        if not r:
            continue
        v = str(r[0] or "").strip()
        if _HOUR_RE.match(v):
            ok_cnt += 1
    if ok_cnt < max(1, min(len(rows), 6) // 2):
        return rows

    def norm_cell(x: Any) -> str:
        if x is None:
            return ""
        if isinstance(x, (int, float)):
            return str(x)
        s = str(x).strip()
        return "N/A" if s.upper() == "N/A" else s

    out: list[list[Any]] = []
    i = 0
    while i < len(rows):
        r0 = rows[i]
        if not r0:
            i += 1
            continue
        base_key = tuple(norm_cell(c) for c in (r0[1:] if len(r0) > 1 else []))
        j = i + 1
        while j < len(rows):
            rj = rows[j]
            if not rj:
                break
            keyj = tuple(norm_cell(c) for c in (rj[1:] if len(rj) > 1 else []))
            if keyj != base_key:
                break
            j += 1

        if j - i >= 2:
            start = str(r0[0] or "").strip()
            end = str(rows[j - 1][0] or "").strip()
            label = f"{start}–{end}" if start and end else str(r0[0] or "")
            merged = [label]
            if len(r0) > 1:
                merged.extend(r0[1:])
            out.append(merged)
        else:
            out.append(r0)

        i = j

    return out


def export_polymarket_stats_sheet(*, lang: str = "zh_CN") -> PolymarketStatsSheet:
    """
    导出 Polymarket 统计表：
    - local：在本机直接运行 node 脚本读取日志
    - ssh：在远端（服务器）运行 node 脚本，stdout 回传到本机解析
    - auto：优先 ssh（若配置了 host），否则 local
    """
    mode = (os.environ.get("SHEETS_POLYMARKET_MODE", "auto") or "auto").strip().lower()
    if mode not in {"auto", "local", "ssh"}:
        mode = "auto"

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    translate = (os.environ.get("SHEETS_POLYMARKET_TRANSLATE", "0") or "0").strip() == "1"
    api_rankings = (os.environ.get("SHEETS_POLYMARKET_ENABLE_API_RANKINGS", "0") or "0").strip() == "1"
    timeout_seconds = int((os.environ.get("SHEETS_POLYMARKET_TIMEOUT_SECONDS", "30") or "30").strip() or "30")
    max_log_mb = int((os.environ.get("SHEETS_POLYMARKET_MAX_LOG_MB", "200") or "200").strip() or "200")
    max_log_bytes = int(max_log_mb) * 1024 * 1024 if int(max_log_mb) > 0 else 0

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

    try:
        # auto：优先 ssh（如果配置了 host），否则 local
        eff_mode = mode
        if eff_mode == "auto":
            eff_mode = "ssh" if ssh_host else "local"

        # 远端/本机的路径字符串（ssh 时不做本地 resolve）
        if eff_mode == "ssh":
            # ssh 模式不要求本机存在 service_dir：
            # - remote_service_dir/remote_log 默认可显式配置
            # - 未配置时尝试用本机 auto-detect 的路径作为“远端默认路径”（仅在两端目录一致时成立）
            local_service_dir = _detect_polymarket_service_dir()
            remote_service_dir = (os.environ.get("SHEETS_POLYMARKET_REMOTE_SERVICE_DIR", "") or "").strip()
            if not remote_service_dir:
                remote_service_dir = str(local_service_dir) if local_service_dir is not None else ""
            if not remote_service_dir:
                raise RuntimeError("missing_remote_service_dir（设置 SHEETS_POLYMARKET_REMOTE_SERVICE_DIR）")

            remote_log = (os.environ.get("SHEETS_POLYMARKET_REMOTE_LOG_FILE", "") or "").strip()
            if not remote_log:
                # 默认优先读取 systemd user service 的 stdout/stderr 落地日志（更可能是“正在跑”的数据源）
                remote_log = "$HOME/.local/state/tradecat/polymarket.log"

            out = _run_ssh_csv_report(
                ssh_host=ssh_host,
                ssh_user=ssh_user,
                ssh_key_path=ssh_key_path,
                service_dir=remote_service_dir,
                log_path=remote_log,
                timeout_seconds=timeout_seconds,
                translate=translate,
                api_rankings=api_rankings,
                max_log_bytes=max_log_bytes,
            )
            source_desc = f"ssh，{ssh_user}@{ssh_host}"
            path_desc = f"服务目录，{remote_service_dir}，日志，{remote_log}"
        else:
            service_dir = _detect_polymarket_service_dir()
            if service_dir is None:
                raise RuntimeError("无法定位 polymarket 服务目录（设置 SHEETS_POLYMARKET_SERVICE_DIR）")

            log_path = _default_log_path(service_dir)
            out = _run_local_csv_report(
                service_dir=service_dir,
                log_path=log_path,
                timeout_seconds=timeout_seconds,
                translate=translate,
                api_rankings=api_rankings,
                max_log_bytes=max_log_bytes,
            )
            source_desc = "local"
            path_desc = f"服务目录，{service_dir}，日志，{log_path}"
    except Exception as exc:
        meta_text = f"数据源，Polymarket，导出时间(UTC)，{now}，语言，{lang}，错误，{type(exc).__name__}:{exc}"
        values = [[meta_text]]
        return PolymarketStatsSheet(
            values=values,
            panel_title_rows=[],
            panel_header_rows=[],
            merge_ranges=[(0, 1, 0, 1)],
            n_rows=1,
            n_cols=1,
        )

    values0, title_rows0, header_rows0 = _parse_sectioned_csv(out)

    meta_text = f"数据源，Polymarket，导出时间(UTC)，{now}，语言，{lang}，模式，{source_desc}，{path_desc}"
    values: list[list[Any]] = [[meta_text]]
    values.extend(values0)

    title_rows = [int(r) + 2 for r in title_rows0]  # +1 meta, +1 1-based
    header_rows = [int(r) + 2 for r in header_rows0]

    # 统一列宽：按全表最大列数补齐
    n_cols = max((len(r) for r in values if isinstance(r, list)), default=1)
    for r in values:
        if isinstance(r, list) and len(r) < n_cols:
            r.extend([""] * (n_cols - len(r)))
        elif not isinstance(r, list):
            # 保底：不允许出现非 list
            r = [str(r)]

    n_rows = len(values)

    merge_ranges: list[tuple[int, int, int, int]] = []
    # meta row 横向合并
    if n_cols > 1:
        merge_ranges.append((0, 1, 0, int(n_cols)))
    # 各分段标题行横向合并
    for r1 in title_rows:
        r0 = int(r1) - 1
        if 0 <= r0 < n_rows and n_cols > 1:
            merge_ranges.append((int(r0), int(r0 + 1), 0, int(n_cols)))

    return PolymarketStatsSheet(
        values=values,
        panel_title_rows=title_rows,
        panel_header_rows=header_rows,
        merge_ranges=merge_ranges,
        n_rows=n_rows,
        n_cols=n_cols,
    )
