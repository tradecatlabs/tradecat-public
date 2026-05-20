#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

SCHEMA = "tradecat_public.ops_audit.v1"
SCHEMA_VERSION = "1.0.0"
TRADECAT_UNITS = ("tradecat-auto-paper.service", "tradecat-auto-paper.timer", "tradecat-daemon.service")
PROCESS_PATTERN = re.compile(
    r"tradecat-public/scripts/start-auto-paper\.sh|tradecat_auto.*run-loop|serve-auto-paper-monitor|auto-paper"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit local TradeCat runtime and service residue without starting it."
    )
    parser.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    report = build_report(root)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_text(report)
    return 0 if report["ok"] else 1


def build_report(root: Path) -> dict[str, Any]:
    systemd_user_dir = Path(
        os.environ.get("TRADECAT_AUTO_PAPER_SYSTEMD_USER_DIR")
        or os.environ.get("TRADECAT_OPS_AUDIT_SYSTEMD_USER_DIR")
        or Path.home() / ".config/systemd/user"
    )
    status = _service_status(root)
    systemd = _systemd_status(systemd_user_dir)
    processes = _process_matches()
    ports = _port_matches()
    cron = _cron_matches()
    runtime = _runtime_status(root, status)
    issues: list[str] = []
    warnings: list[str] = []
    if status.get("running") is True:
        issues.append("auto_paper_loop_running")
    for name, state in systemd["active"].items():
        if state == "active":
            issues.append(f"systemd_unit_active:{name}")
    for name, state in systemd["enabled"].items():
        if state not in {"disabled", "not-found", "masked", "static", "indirect", "generated", ""}:
            warnings.append(f"systemd_unit_enabled:{name}:{state}")
    for path in systemd["residue_paths"]:
        warnings.append(f"systemd_residue:{path}")
    if processes:
        issues.append("runtime_process_residue")
    if ports:
        warnings.append("monitor_or_tradecat_port_listening")
    if cron:
        warnings.append("cron_residue")
    if runtime["paper_autonomy_profile_exists"] and not runtime["paper_autonomy_profile_configured"]:
        warnings.append("ignored_runtime_paper_autonomy_profile_present_but_not_configured")
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ok": not issues and not systemd["residue_paths"] and not processes and not cron,
        "manual_mode": status.get("running") is not True,
        "ci_runtime_note": "CI validates code and contracts only; it does not prove local auto-paper is running.",
        "root": str(root),
        "status": status,
        "systemd": systemd,
        "processes": processes,
        "ports": ports,
        "cron": cron,
        "runtime": runtime,
        "issues": issues,
        "warnings": warnings,
        "safety": {
            "public_readonly": True,
            "paper_or_watch_only": True,
            "real_orders": False,
            "signed_requests": False,
            "reads_api_keys": False,
            "binance_account_state": False,
        },
    }


def _service_status(root: Path) -> dict[str, Any]:
    script = Path(os.environ.get("TRADECAT_OPS_AUDIT_START_SCRIPT") or root / "scripts/start-auto-paper.sh")
    proc = _run(["bash", str(script), "status", "--json"], cwd=root)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("command_returncode", proc.returncode)
    return payload


def _systemd_status(systemd_user_dir: Path) -> dict[str, Any]:
    active = _systemctl_states("is-active")
    enabled = _systemctl_states("is-enabled")
    residue_paths = []
    if systemd_user_dir.exists():
        for path in systemd_user_dir.rglob("*"):
            if path.name.startswith("tradecat") or "auto-paper" in path.name:
                residue_paths.append(str(path))
    return {
        "user_dir": str(systemd_user_dir),
        "active": active,
        "enabled": enabled,
        "residue_paths": sorted(residue_paths),
    }


def _systemctl_states(action: str) -> dict[str, str]:
    systemctl = os.environ.get("TRADECAT_OPS_AUDIT_SYSTEMCTL_BIN") or "systemctl"
    states: dict[str, str] = {}
    for unit in TRADECAT_UNITS:
        proc = _run([systemctl, "--user", action, unit])
        states[unit] = (
            (proc.stdout or proc.stderr).strip().splitlines()[0] if (proc.stdout or proc.stderr).strip() else ""
        )
        if not states[unit]:
            states[unit] = "unknown"
    return states


def _process_matches() -> list[dict[str, str]]:
    fixture = os.environ.get("TRADECAT_OPS_AUDIT_PS_FIXTURE")
    if fixture:
        text = Path(fixture).read_text(encoding="utf-8")
    else:
        proc = _run(["ps", "-eo", "pid=,ppid=,stat=,cmd="])
        text = proc.stdout
    matches = []
    current_pid = str(os.getpid())
    for line in text.splitlines():
        if not PROCESS_PATTERN.search(line):
            continue
        parts = line.strip().split(maxsplit=3)
        if len(parts) < 4 or parts[0] == current_pid:
            continue
        if "ops-audit" in parts[3]:
            continue
        matches.append({"pid": parts[0], "ppid": parts[1], "stat": parts[2], "cmd": parts[3]})
    return matches


def _port_matches() -> list[str]:
    fixture = os.environ.get("TRADECAT_OPS_AUDIT_SS_FIXTURE")
    if fixture:
        text = Path(fixture).read_text(encoding="utf-8")
    else:
        ss = os.environ.get("TRADECAT_OPS_AUDIT_SS_BIN") or "ss"
        proc = _run([ss, "-ltnp"])
        text = proc.stdout
    return [line.strip() for line in text.splitlines() if re.search(r":8765\b|tradecat|auto-paper", line)]


def _cron_matches() -> list[str]:
    fixture = os.environ.get("TRADECAT_OPS_AUDIT_CRON_FIXTURE")
    if fixture:
        text = Path(fixture).read_text(encoding="utf-8")
    else:
        crontab = os.environ.get("TRADECAT_OPS_AUDIT_CRONTAB_BIN") or "crontab"
        proc = _run([crontab, "-l"])
        text = proc.stdout
    return [line.strip() for line in text.splitlines() if re.search(r"tradecat|auto-paper|start-auto-paper", line)]


def _runtime_status(root: Path, status: dict[str, Any]) -> dict[str, Any]:
    runtime_dir = Path(str(status.get("runtime_dir") or root / ".runtime/auto-paper"))
    profile_path = Path(str(status.get("paper_autonomy_profile_path") or runtime_dir / "paper_autonomy_profile.json"))
    return {
        "runtime_dir": str(runtime_dir),
        "paper_autonomy_profile_path": str(profile_path),
        "paper_autonomy_profile_exists": profile_path.exists(),
        "paper_autonomy_profile_configured": bool(status.get("paper_autonomy_profile_configured")),
        "paper_autonomy_profile_defaulted": bool(status.get("paper_autonomy_profile_defaulted")),
        "paper_autonomy_enabled": bool(status.get("paper_autonomy_enabled")),
        "paper_sizing_source": (status.get("paper_sizing") or {}).get("source")
        if isinstance(status.get("paper_sizing"), dict)
        else None,
    }


def _run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)
    except OSError as exc:
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))


def _print_text(report: dict[str, Any]) -> None:
    print(f"ops-audit ok={str(report['ok']).lower()} manual_mode={str(report['manual_mode']).lower()}")
    print(f"auto-paper state={report['status'].get('state')} running={report['status'].get('running')}")
    print(
        f"systemd residue={len(report['systemd']['residue_paths'])} processes={len(report['processes'])} cron={len(report['cron'])}"
    )
    if report["issues"]:
        print("issues:")
        for issue in report["issues"]:
            print(f"- {issue}")
    if report["warnings"]:
        print("warnings:")
        for warning in report["warnings"]:
            print(f"- {warning}")


if __name__ == "__main__":
    raise SystemExit(main())
