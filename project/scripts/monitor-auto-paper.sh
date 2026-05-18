#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT_DIR="$(cd "$APP_DIR/.." && pwd)"
INTERVAL_SECONDS="${TRADECAT_AUTO_PAPER_MONITOR_INTERVAL_SECONDS:-5}"
ONCE=0
CLEAR_SCREEN=1

usage() {
  cat <<'EOF'
Usage:
  bash project/scripts/monitor-auto-paper.sh [--once] [--no-clear] [--interval SECONDS]

Shows a terminal/HDMI-friendly local monitor for the public-readonly paper/watch
auto-paper runtime. It only reads local status, health, ledger, audit, and log
files; it never reads Binance keys, signs requests, or places real orders.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --once)
      ONCE=1
      shift
      ;;
    --no-clear)
      CLEAR_SCREEN=0
      shift
      ;;
    --interval)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      INTERVAL_SECONDS="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

capture_json() {
  local name="$1"
  shift
  local file="$TMP_DIR/$name.json"
  if "$@" >"$file" 2>"$TMP_DIR/$name.err"; then
    printf '%s\n' "$file"
  else
    printf '%s\n' "$file"
  fi
}

render_once() {
  TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "$TMP_DIR"' RETURN

  local status_file health_file paper_file audit_file ops_file
  status_file="$(capture_json status bash "$APP_DIR/scripts/start-auto-paper.sh" status --json)"
  health_file="$(capture_json health bash "$APP_DIR/scripts/start-auto-paper.sh" health --json)"
  paper_file="$(capture_json paper bash "$ROOT_DIR/scripts/run-tradecat.sh" auto paper-report --ledger-path "$APP_DIR/.runtime/auto-paper/paper_ledger.json" --json)"
  audit_file="$(capture_json audit bash "$ROOT_DIR/scripts/run-tradecat.sh" auto audit-journal --journal-path "$APP_DIR/.runtime/auto-paper/paper_audit.sqlite3" --json)"
  ops_file="$(capture_json ops bash "$APP_DIR/scripts/start-auto-paper.sh" ops-check --json)"

  if [[ "$CLEAR_SCREEN" -eq 1 ]]; then
    printf '\033[2J\033[H'
  fi

  "$APP_DIR/.venv/bin/python" - "$status_file" "$health_file" "$paper_file" "$audit_file" "$ops_file" <<'PY'
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def load(path: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "error": {"code": "monitor_load_failed", "message": str(exc)}}
    return payload if isinstance(payload, dict) else {"ok": False, "error": {"code": "monitor_not_object"}}


def yn(value: object) -> str:
    return "yes" if value is True else "no"


def num(value: object, digits: int = 4) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}"
    return "-"


status, health, paper, audit, ops = [load(item) for item in sys.argv[1:6]]
ledger_summary = ((health.get("ledger") or {}).get("summary") or {}) if isinstance(health.get("ledger"), dict) else {}
paper_summary = paper.get("summary") if isinstance(paper.get("summary"), dict) else {}
archive = health.get("archive") if isinstance(health.get("archive"), dict) else {}
heartbeat = health.get("heartbeat") if isinstance(health.get("heartbeat"), dict) else {}
safety = status.get("safety") if isinstance(status.get("safety"), dict) else {}
ops_checks = ops.get("checks") if isinstance(ops.get("checks"), list) else []
blocking_checks = ops.get("blocking_checks") if isinstance(ops.get("blocking_checks"), list) else []
alerts = health.get("alerts") if isinstance(health.get("alerts"), list) else []
audit_safety = audit.get("safety") if isinstance(audit.get("safety"), dict) else {}
now = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

print("TradeCat Auto Paper Monitor")
print("=" * 88)
print(f"generated_at={now}")
print(f"service_state={status.get('state', '-')} running={yn(status.get('running'))} pid={status.get('pid') or '-'} event={status.get('event', '-')}")
print(f"health={health.get('status', '-')} ok={yn(health.get('ok'))} alerts={','.join(str(item) for item in alerts) or '-'}")
print(f"heartbeat_ok={yn(heartbeat.get('ok'))} stale={yn(heartbeat.get('stale'))} age_seconds={num(heartbeat.get('age_seconds'), 1)} max_age={num(heartbeat.get('max_age_seconds'), 1)}")
print("-" * 88)
print("Safety")
print(f"real_orders={safety.get('real_orders', False)} signed_requests={safety.get('signed_requests', False)} reads_api_keys={safety.get('reads_api_keys', False)} binance_account_state={safety.get('binance_account_state', False)}")
print(f"audit_chain_valid={audit.get('chain_valid', '-')} audit_ok={audit.get('ok', '-')} audit_safety_real_orders={audit_safety.get('real_orders', False)}")
print("-" * 88)
print("Paper Ledger")
summary = ledger_summary or paper_summary
print(
    "cash={cash} equity={equity} realized={realized} unrealized={unrealized} open={open_count} closed={closed_count} orders={orders} fills={fills}".format(
        cash=num(summary.get("cash_balance_usdt")),
        equity=num(summary.get("equity_usdt")),
        realized=num(summary.get("realized_pnl_usdt")),
        unrealized=num(summary.get("unrealized_pnl_usdt")),
        open_count=summary.get("open_positions_count", "-"),
        closed_count=summary.get("closed_positions_count", "-"),
        orders=summary.get("paper_orders_count", "-"),
        fills=summary.get("fills_count", "-"),
    )
)
print("-" * 88)
print("Cycles")
print(f"cycle_count={archive.get('cycle_count', '-')} last_action={archive.get('last_action', '-')}")
action_counts = archive.get("action_counts") if isinstance(archive.get("action_counts"), dict) else {}
print("action_counts=" + (", ".join(f"{k}:{v}" for k, v in sorted(action_counts.items())) or "-"))
print("-" * 88)
print("Ops Preflight")
print(f"ops_ok={yn(ops.get('ok'))} blocking_checks={','.join(str(item) for item in blocking_checks) or '-'}")
for item in ops_checks:
    if not isinstance(item, dict):
        continue
    if item.get("severity") == "block" and item.get("ok") is not True:
        print(f"BLOCK {item.get('id')}: {item.get('message')}")
print("-" * 88)
print("Commands")
print("start/heal: bash project/scripts/start-auto-paper.sh heal --json")
print("status:     bash project/scripts/start-auto-paper.sh status --json")
print("health:     bash project/scripts/start-auto-paper.sh health --json")
print("stop:       bash project/scripts/start-auto-paper.sh stop --json")
PY

  local log_file="$APP_DIR/.runtime/auto-paper/paper-run-loop.log"
  printf '%s\n' "----------------------------------------------------------------------------------------"
  printf '%s\n' "Log tail: $log_file"
  if [[ -f "$log_file" ]]; then
    tail -n 12 "$log_file"
  else
    printf '%s\n' "(log file missing)"
  fi
}

while true; do
  render_once
  [[ "$ONCE" -eq 1 ]] && break
  sleep "$INTERVAL_SECONDS"
done
