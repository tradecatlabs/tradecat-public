#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${TRADECAT_AUTO_PAPER_RUNTIME_DIR:-$APP_DIR/.runtime/auto-paper}"
SYSTEMD_USER_DIR="${TRADECAT_AUTO_PAPER_SYSTEMD_USER_DIR:-${HOME:-}/.config/systemd/user}"
SYSTEMCTL_BIN="${TRADECAT_AUTO_PAPER_SYSTEMCTL_BIN:-systemctl}"
SYSTEMD_SERVICE_UNIT="tradecat-auto-paper.service"
SYSTEMD_TIMER_UNIT="tradecat-auto-paper.timer"
INTERVAL_SECONDS="${TRADECAT_AUTO_PAPER_INTERVAL_SECONDS:-60}"
MAINTENANCE_INTERVAL_SECONDS="${TRADECAT_AUTO_PAPER_MAINTENANCE_INTERVAL_SECONDS:-300}"
PAPER_MARGIN_BUDGET_USDT="${TRADECAT_AUTO_PAPER_MARGIN_BUDGET_USDT:-}"
AGENT_MARGIN_USDT="${TRADECAT_AUTO_PAPER_AGENT_MARGIN_USDT:-}"
EFFECTIVE_NOTIONAL_USDT="${TRADECAT_AUTO_PAPER_EFFECTIVE_NOTIONAL_USDT:-}"
PAPER_LEVERAGE="${TRADECAT_AUTO_PAPER_LEVERAGE:-}"
AGENT_TRADE_THESIS_PATH="${TRADECAT_AUTO_PAPER_AGENT_TRADE_THESIS_PATH:-}"
PAPER_AUTONOMY_PROFILE_PATH="${TRADECAT_AUTO_PAPER_AUTONOMY_PROFILE_PATH:-}"
INITIAL_BALANCE_USDT="${TRADECAT_AUTO_PAPER_INITIAL_BALANCE_USDT:-1000}"
PAPER_FEE_BPS="${TRADECAT_AUTO_PAPER_FEE_BPS:-2}"
PAPER_SLIPPAGE_BPS="${TRADECAT_AUTO_PAPER_SLIPPAGE_BPS:-0.5}"
PAPER_MAX_HOLDING_MINUTES="${TRADECAT_AUTO_PAPER_MAX_HOLDING_MINUTES:-0}"
MAX_EVENT_AGE_SECONDS="${TRADECAT_AUTO_PAPER_MAX_EVENT_AGE_SECONDS:-300}"
EVENT_LIMIT="${TRADECAT_AUTO_PAPER_EVENT_LIMIT:-5}"
ANOMALY_LIMIT="${TRADECAT_AUTO_PAPER_ANOMALY_LIMIT:-0}"
SYMBOL="${TRADECAT_AUTO_PAPER_SYMBOL:-auto}"
BASE_URL="${TRADECAT_AUTO_PAPER_BASE_URL:-https://fapi.binance.com}"
MAX_HEARTBEAT_AGE_SECONDS="${TRADECAT_AUTO_PAPER_MAX_HEARTBEAT_AGE_SECONDS:-180}"
PORTFOLIO_RISK_POLICY_PATH="${TRADECAT_AUTO_PAPER_PORTFOLIO_RISK_POLICY_PATH:-}"
PAPER_KILL_SWITCH_PATH="${TRADECAT_AUTO_PAPER_KILL_SWITCH_PATH:-}"
MIN_FREE_BYTES="${TRADECAT_AUTO_PAPER_MIN_FREE_BYTES:-104857600}"
MIN_NOFILE="${TRADECAT_AUTO_PAPER_MIN_NOFILE:-1024}"
MIN_NPROC="${TRADECAT_AUTO_PAPER_MIN_NPROC:-128}"
LIMIT_NOFILE="${TRADECAT_AUTO_PAPER_LIMIT_NOFILE:-4096}"
TASKS_MAX="${TRADECAT_AUTO_PAPER_TASKS_MAX:-64}"
RESTART_SEC="${TRADECAT_AUTO_PAPER_RESTART_SEC:-30s}"
START_LIMIT_BURST="${TRADECAT_AUTO_PAPER_START_LIMIT_BURST:-5}"
START_LIMIT_INTERVAL_SECONDS="${TRADECAT_AUTO_PAPER_START_LIMIT_INTERVAL_SECONDS:-600}"
TIMEOUT_START_SECONDS="${TRADECAT_AUTO_PAPER_TIMEOUT_START_SECONDS:-120}"
STATE_PATH="${TRADECAT_AUTO_PAPER_STATE_PATH:-$RUNTIME_DIR/service_state.json}"
LEDGER_PATH="${TRADECAT_AUTO_PAPER_LEDGER_PATH:-$RUNTIME_DIR/paper_ledger.json}"
ARCHIVE_PATH="${TRADECAT_AUTO_PAPER_ARCHIVE_PATH:-$RUNTIME_DIR/cycles.jsonl}"
JOURNAL_PATH="${TRADECAT_AUTO_PAPER_JOURNAL_PATH:-$RUNTIME_DIR/paper_audit.sqlite3}"
PID_FILE="$RUNTIME_DIR/paper-run-loop.pid"
LOG_FILE="${TRADECAT_AUTO_PAPER_LOG_FILE:-$RUNTIME_DIR/paper-run-loop.log}"
ACTION="status"
JSON=0

for arg in "$@"; do
  case "$arg" in
    --json) JSON=1 ;;
    start|stop|restart|status|ops-check|heal|systemd-install|systemd-uninstall|health|daily|alert|_run|_cycle) ACTION="$arg" ;;
    *) echo "usage: $0 [--json] start|stop|restart|status|ops-check|heal|health|daily|alert|systemd-install|systemd-uninstall" >&2; exit 2 ;;
  esac
done

python_bin() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    printf '%s\n' "$PYTHON_BIN"
    return 0
  fi
  if [[ -x "$APP_DIR/.venv/bin/python" ]]; then
    printf '%s\n' "$APP_DIR/.venv/bin/python"
    return 0
  fi
  printf '%s\n' "python3"
}

read_pid() {
  if [[ -f "$PID_FILE" ]]; then
    cat "$PID_FILE"
  fi
}

is_running() {
  local pid
  pid="$(read_pid)"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" >/dev/null 2>&1 || return 1
  if [[ -r "/proc/$pid/cmdline" ]]; then
    tr '\0' ' ' <"/proc/$pid/cmdline" | grep -F "start-auto-paper.sh _run" >/dev/null 2>&1
    return $?
  fi
  return 0
}

proc_env_value() {
  local pid="$1"
  local key="$2"
  local env_path="/proc/$pid/environ"
  local entry
  local prefix="$key="
  [[ -r "$env_path" ]] || return 1
  while IFS= read -r -d '' entry; do
    if [[ "$entry" == "$prefix"* ]]; then
      printf '%s\n' "${entry#"$prefix"}"
      return 0
    fi
  done <"$env_path"
  return 1
}

load_running_env_config() {
  local pid="$1"
  local value
  if value="$(proc_env_value "$pid" "TRADECAT_AUTO_PAPER_INTERVAL_SECONDS")"; then INTERVAL_SECONDS="$value"; fi
  if value="$(proc_env_value "$pid" "TRADECAT_AUTO_PAPER_MAINTENANCE_INTERVAL_SECONDS")"; then MAINTENANCE_INTERVAL_SECONDS="$value"; fi
  if value="$(proc_env_value "$pid" "TRADECAT_AUTO_PAPER_MARGIN_BUDGET_USDT")"; then PAPER_MARGIN_BUDGET_USDT="$value"; fi
  if value="$(proc_env_value "$pid" "TRADECAT_AUTO_PAPER_AGENT_MARGIN_USDT")"; then AGENT_MARGIN_USDT="$value"; fi
  if value="$(proc_env_value "$pid" "TRADECAT_AUTO_PAPER_EFFECTIVE_NOTIONAL_USDT")"; then EFFECTIVE_NOTIONAL_USDT="$value"; fi
  if value="$(proc_env_value "$pid" "TRADECAT_AUTO_PAPER_LEVERAGE")"; then PAPER_LEVERAGE="$value"; fi
  if value="$(proc_env_value "$pid" "TRADECAT_AUTO_PAPER_AGENT_TRADE_THESIS_PATH")"; then AGENT_TRADE_THESIS_PATH="$value"; fi
  if value="$(proc_env_value "$pid" "TRADECAT_AUTO_PAPER_AUTONOMY_PROFILE_PATH")"; then PAPER_AUTONOMY_PROFILE_PATH="$value"; fi
  if value="$(proc_env_value "$pid" "TRADECAT_AUTO_PAPER_INITIAL_BALANCE_USDT")"; then INITIAL_BALANCE_USDT="$value"; fi
  if value="$(proc_env_value "$pid" "TRADECAT_AUTO_PAPER_FEE_BPS")"; then PAPER_FEE_BPS="$value"; fi
  if value="$(proc_env_value "$pid" "TRADECAT_AUTO_PAPER_SLIPPAGE_BPS")"; then PAPER_SLIPPAGE_BPS="$value"; fi
  if value="$(proc_env_value "$pid" "TRADECAT_AUTO_PAPER_MAX_HOLDING_MINUTES")"; then PAPER_MAX_HOLDING_MINUTES="$value"; fi
  if value="$(proc_env_value "$pid" "TRADECAT_AUTO_PAPER_MAX_EVENT_AGE_SECONDS")"; then MAX_EVENT_AGE_SECONDS="$value"; fi
  if value="$(proc_env_value "$pid" "TRADECAT_AUTO_PAPER_EVENT_LIMIT")"; then EVENT_LIMIT="$value"; fi
  if value="$(proc_env_value "$pid" "TRADECAT_AUTO_PAPER_ANOMALY_LIMIT")"; then ANOMALY_LIMIT="$value"; fi
  if value="$(proc_env_value "$pid" "TRADECAT_AUTO_PAPER_SYMBOL")"; then SYMBOL="$value"; fi
  if value="$(proc_env_value "$pid" "TRADECAT_AUTO_PAPER_BASE_URL")"; then BASE_URL="$value"; fi
  if value="$(proc_env_value "$pid" "TRADECAT_AUTO_PAPER_PORTFOLIO_RISK_POLICY_PATH")"; then PORTFOLIO_RISK_POLICY_PATH="$value"; fi
  if value="$(proc_env_value "$pid" "TRADECAT_AUTO_PAPER_KILL_SWITCH_PATH")"; then PAPER_KILL_SWITCH_PATH="$value"; fi
}

emit_json() {
  local action="$1"
  local state="$2"
  local running="$3"
  local ok="$4"
  local event="$5"
  local pid="${6:-}"
  local error_code="${7:-}"
  local error_message="${8:-}"
  local py
  py="$(python_bin)"
  AUTO_JSON_ACTION="$action" \
  AUTO_JSON_STATE="$state" \
  AUTO_JSON_RUNNING="$running" \
  AUTO_JSON_OK="$ok" \
  AUTO_JSON_EVENT="$event" \
  AUTO_JSON_PID="$pid" \
  AUTO_JSON_ERROR_CODE="$error_code" \
  AUTO_JSON_ERROR_MESSAGE="$error_message" \
  AUTO_JSON_RUNTIME_DIR="$RUNTIME_DIR" \
  AUTO_JSON_STATE_PATH="$STATE_PATH" \
  AUTO_JSON_LEDGER_PATH="$LEDGER_PATH" \
  AUTO_JSON_ARCHIVE_PATH="$ARCHIVE_PATH" \
  AUTO_JSON_JOURNAL_PATH="$JOURNAL_PATH" \
  AUTO_JSON_LOG_FILE="$LOG_FILE" \
  AUTO_JSON_SYSTEMD_USER_DIR="$SYSTEMD_USER_DIR" \
  AUTO_JSON_SYSTEMD_SERVICE_UNIT="$SYSTEMD_SERVICE_UNIT" \
  AUTO_JSON_SYSTEMD_TIMER_UNIT="$SYSTEMD_TIMER_UNIT" \
  AUTO_JSON_INTERVAL_SECONDS="$INTERVAL_SECONDS" \
  AUTO_JSON_MAINTENANCE_INTERVAL_SECONDS="$MAINTENANCE_INTERVAL_SECONDS" \
  AUTO_JSON_PAPER_MARGIN_BUDGET_USDT="$PAPER_MARGIN_BUDGET_USDT" \
  AUTO_JSON_AGENT_MARGIN_USDT="$AGENT_MARGIN_USDT" \
  AUTO_JSON_EFFECTIVE_NOTIONAL_USDT="$EFFECTIVE_NOTIONAL_USDT" \
  AUTO_JSON_PAPER_LEVERAGE="$PAPER_LEVERAGE" \
  AUTO_JSON_AGENT_TRADE_THESIS_PATH="$AGENT_TRADE_THESIS_PATH" \
  AUTO_JSON_PAPER_AUTONOMY_PROFILE_PATH="$PAPER_AUTONOMY_PROFILE_PATH" \
  AUTO_JSON_INITIAL_BALANCE_USDT="$INITIAL_BALANCE_USDT" \
  AUTO_JSON_PAPER_FEE_BPS="$PAPER_FEE_BPS" \
  AUTO_JSON_PAPER_SLIPPAGE_BPS="$PAPER_SLIPPAGE_BPS" \
  AUTO_JSON_PAPER_MAX_HOLDING_MINUTES="$PAPER_MAX_HOLDING_MINUTES" \
  AUTO_JSON_MAX_EVENT_AGE_SECONDS="$MAX_EVENT_AGE_SECONDS" \
  AUTO_JSON_EVENT_LIMIT="$EVENT_LIMIT" \
  AUTO_JSON_ANOMALY_LIMIT="$ANOMALY_LIMIT" \
  AUTO_JSON_SYMBOL="$SYMBOL" \
  AUTO_JSON_BASE_URL="$BASE_URL" \
  AUTO_JSON_PORTFOLIO_RISK_POLICY_PATH="$PORTFOLIO_RISK_POLICY_PATH" \
  AUTO_JSON_PAPER_KILL_SWITCH_PATH="$PAPER_KILL_SWITCH_PATH" \
  AUTO_JSON_PYTHON="$py" \
  "$py" - <<'PY'
import json
import os


def truthy(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


def optional_int(value: str):
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def optional_float(value: str):
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return value

ok = truthy(os.environ["AUTO_JSON_OK"])
paper_margin_budget_usdt = optional_float(os.environ["AUTO_JSON_PAPER_MARGIN_BUDGET_USDT"])
agent_margin_usdt = optional_float(os.environ["AUTO_JSON_AGENT_MARGIN_USDT"])
explicit_effective_notional_usdt = optional_float(os.environ["AUTO_JSON_EFFECTIVE_NOTIONAL_USDT"])
paper_leverage = optional_float(os.environ["AUTO_JSON_PAPER_LEVERAGE"])
paper_autonomy_profile_path = os.environ["AUTO_JSON_PAPER_AUTONOMY_PROFILE_PATH"]
effective_notional_usdt = (
    agent_margin_usdt * paper_leverage
    if isinstance(agent_margin_usdt, (int, float)) and isinstance(paper_leverage, (int, float))
    else explicit_effective_notional_usdt if isinstance(explicit_effective_notional_usdt, (int, float)) and isinstance(paper_leverage, (int, float))
    else None
)
payload = {
    "schema": "tradecat_auto.paper_service_status.v1",
    "schema_version": "1.0.0",
    "ok": ok,
    "mode": "paper",
    "real_orders": False,
    "signed_requests": False,
    "reads_api_keys": False,
    "command": "auto-paper-service",
    "action": os.environ["AUTO_JSON_ACTION"],
    "state": os.environ["AUTO_JSON_STATE"],
    "event": os.environ["AUTO_JSON_EVENT"],
    "running": truthy(os.environ["AUTO_JSON_RUNNING"]),
    "pid": optional_int(os.environ["AUTO_JSON_PID"]),
    "runtime_dir": os.environ["AUTO_JSON_RUNTIME_DIR"],
    "state_path": os.environ["AUTO_JSON_STATE_PATH"],
    "ledger_path": os.environ["AUTO_JSON_LEDGER_PATH"],
    "archive_path": os.environ["AUTO_JSON_ARCHIVE_PATH"],
    "journal_path": os.environ["AUTO_JSON_JOURNAL_PATH"],
    "log_file": os.environ["AUTO_JSON_LOG_FILE"],
    "systemd_user_dir": os.environ["AUTO_JSON_SYSTEMD_USER_DIR"],
    "systemd_service_unit": os.environ["AUTO_JSON_SYSTEMD_SERVICE_UNIT"],
    "systemd_timer_unit": os.environ["AUTO_JSON_SYSTEMD_TIMER_UNIT"],
    "interval_seconds": optional_float(os.environ["AUTO_JSON_INTERVAL_SECONDS"]),
    "maintenance_interval_seconds": optional_float(os.environ["AUTO_JSON_MAINTENANCE_INTERVAL_SECONDS"]),
    "paper_margin_budget_usdt": paper_margin_budget_usdt,
    "agent_margin_usdt": agent_margin_usdt,
    "notional_usdt": explicit_effective_notional_usdt,
    "notional_semantics": "deprecated explicit effective notional; no default paper order amount or budget cap",
    "paper_leverage": paper_leverage,
    "agent_trade_thesis_path": os.environ["AUTO_JSON_AGENT_TRADE_THESIS_PATH"],
    "agent_trade_thesis_configured": bool(os.environ["AUTO_JSON_AGENT_TRADE_THESIS_PATH"]),
    "paper_autonomy_profile_path": paper_autonomy_profile_path,
    "paper_autonomy_profile_configured": bool(paper_autonomy_profile_path),
    "effective_notional_usdt": effective_notional_usdt,
    "agent_sizing_required": effective_notional_usdt is None and not paper_autonomy_profile_path,
    "paper_sizing": {
        "schema": "tradecat_auto.paper_sizing_decision.v1",
        "schema_version": "1.0.0",
        "source": "service_environment" if effective_notional_usdt is not None else "paper_autonomy_profile" if paper_autonomy_profile_path else "agent_required_missing",
        "margin_budget_usdt": paper_margin_budget_usdt,
        "requested_margin_usdt": agent_margin_usdt,
        "paper_leverage": paper_leverage,
        "effective_notional_usdt": effective_notional_usdt,
        "notional_semantics": "effective_notional_usdt; no default paper order amount or budget cap",
    },
    "initial_balance_usdt": optional_float(os.environ["AUTO_JSON_INITIAL_BALANCE_USDT"]),
    "paper_fee_bps": optional_float(os.environ["AUTO_JSON_PAPER_FEE_BPS"]),
    "paper_fee_model": "binance_usdm_vip0_maker_assumption",
    "paper_slippage_bps": optional_float(os.environ["AUTO_JSON_PAPER_SLIPPAGE_BPS"]),
    "paper_max_holding_minutes": optional_float(os.environ["AUTO_JSON_PAPER_MAX_HOLDING_MINUTES"]),
    "paper_max_holding_minutes_semantics": "legacy status/config field only; time stops require Agent strategy_intent/agent_trade_thesis max_holding_minutes on the paper position",
    "max_event_age_seconds": optional_float(os.environ["AUTO_JSON_MAX_EVENT_AGE_SECONDS"]),
    "event_limit": optional_int(os.environ["AUTO_JSON_EVENT_LIMIT"]),
    "anomaly_limit": optional_int(os.environ["AUTO_JSON_ANOMALY_LIMIT"]),
    "symbol": os.environ["AUTO_JSON_SYMBOL"],
    "base_url": os.environ["AUTO_JSON_BASE_URL"],
    "portfolio_risk_policy_path": os.environ["AUTO_JSON_PORTFOLIO_RISK_POLICY_PATH"],
    "paper_kill_switch_path": os.environ["AUTO_JSON_PAPER_KILL_SWITCH_PATH"],
    "python": os.environ["AUTO_JSON_PYTHON"],
    "health": "spawned_unverified" if truthy(os.environ["AUTO_JSON_RUNNING"]) else "not_running",
    "safety": {
        "public_readonly_market_data": True,
        "paper_or_watch_only": True,
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "binance_account_state": False,
    },
    "limitations": [
        "public Binance market data only",
        "paper/watch mode only",
        "no Binance API keys are read",
        "no signed account or order endpoints are called",
        "no real order is placed",
    ],
}
if not ok:
    payload["error"] = {
        "code": os.environ["AUTO_JSON_ERROR_CODE"] or "paper_service_not_running",
        "kind": "runtime",
        "message": os.environ["AUTO_JSON_ERROR_MESSAGE"] or "auto paper run-loop is not running",
        "hint": "Run project/scripts/start-auto-paper.sh start --json, then inspect paper-report and .runtime/auto-paper/cycles.jsonl.",
        "retryable": False,
    }
print(json.dumps(payload, ensure_ascii=False))
PY
}

json_flag_args() {
  if [[ "$JSON" -eq 1 ]]; then
    printf '%s\n' "--json"
  fi
}

emit_text_or_json() {
  local action="$1"
  local state="$2"
  local running="$3"
  local ok="$4"
  local event="$5"
  local text="$6"
  local pid="${7:-}"
  local error_code="${8:-}"
  local error_message="${9:-}"
  if [[ "$JSON" -eq 1 ]]; then
    emit_json "$action" "$state" "$running" "$ok" "$event" "$pid" "$error_code" "$error_message"
  else
    echo "$text"
  fi
}

run_cycle() {
  local py
  py="$(python_bin)"
  cd "$APP_DIR"
  export PYTHONPATH="$APP_DIR/src:${PYTHONPATH:-}"
  export PYTHONUNBUFFERED=1
  mkdir -p "$RUNTIME_DIR"
  local -a sizing_args=()
  if [[ -n "$PAPER_MARGIN_BUDGET_USDT" ]]; then
    sizing_args+=(--paper-margin-budget-usdt "$PAPER_MARGIN_BUDGET_USDT")
  fi
  if [[ -n "$AGENT_MARGIN_USDT" ]]; then
    sizing_args+=(--agent-margin-usdt "$AGENT_MARGIN_USDT")
  fi
  if [[ -n "$EFFECTIVE_NOTIONAL_USDT" ]]; then
    sizing_args+=(--notional-usdt "$EFFECTIVE_NOTIONAL_USDT")
  fi
  if [[ -n "$PAPER_LEVERAGE" ]]; then
    sizing_args+=(--paper-leverage "$PAPER_LEVERAGE")
  fi
  if [[ -n "$AGENT_TRADE_THESIS_PATH" ]]; then
    sizing_args+=(--agent-trade-thesis-path "$AGENT_TRADE_THESIS_PATH")
  fi
  if [[ -n "$PAPER_AUTONOMY_PROFILE_PATH" ]]; then
    sizing_args+=(--paper-autonomy-profile-path "$PAPER_AUTONOMY_PROFILE_PATH")
  fi
  if [[ -n "$PORTFOLIO_RISK_POLICY_PATH" ]]; then
    sizing_args+=(--portfolio-risk-policy-path "$PORTFOLIO_RISK_POLICY_PATH")
  fi
  if [[ -n "$PAPER_KILL_SWITCH_PATH" ]]; then
    sizing_args+=(--paper-kill-switch-path "$PAPER_KILL_SWITCH_PATH")
  fi
  printf '{"event":"cycle_start","ts":"%s"}\n' "$(date -Iseconds)"
  "$py" -m tradecat_auto.cli run-loop \
    --mode paper \
    "${sizing_args[@]}" \
    --state-path "$STATE_PATH" \
    --ledger-path "$LEDGER_PATH" \
    --archive-path "$ARCHIVE_PATH" \
    --journal-path "$JOURNAL_PATH" \
    --initial-balance-usdt "$INITIAL_BALANCE_USDT" \
    --paper-fee-bps "$PAPER_FEE_BPS" \
    --paper-slippage-bps "$PAPER_SLIPPAGE_BPS" \
    --paper-max-holding-minutes "$PAPER_MAX_HOLDING_MINUTES" \
    --interval-seconds "$INTERVAL_SECONDS" \
    --maintenance-interval-seconds "$MAINTENANCE_INTERVAL_SECONDS" \
    --max-event-age-seconds "$MAX_EVENT_AGE_SECONDS" \
    --event-limit "$EVENT_LIMIT" \
    --anomaly-limit "$ANOMALY_LIMIT" \
    --symbol "$SYMBOL" \
    --base-url "$BASE_URL" \
    --once \
    --json
}

run_forever() {
  mkdir -p "$RUNTIME_DIR"
  while true; do
    if ! run_cycle; then
      printf '{"event":"cycle_error","ts":"%s","ok":false}\n' "$(date -Iseconds)"
    fi
    sleep "$INTERVAL_SECONDS"
  done
}

start() {
  local action="${1:-start}"
  if is_running; then
    local pid
    pid="$(read_pid)"
    load_running_env_config "$pid"
    emit_text_or_json "$action" "running" "1" "1" "already_running" "running pid=$pid ledger=$LEDGER_PATH log=$LOG_FILE" "$pid"
    return 0
  fi
  rm -f "$PID_FILE"
  mkdir -p "$RUNTIME_DIR"
  (
    cd "$APP_DIR"
    if command -v setsid >/dev/null 2>&1; then
      setsid bash "$APP_DIR/scripts/start-auto-paper.sh" _run </dev/null >>"$LOG_FILE" 2>&1 &
    else
      nohup bash "$APP_DIR/scripts/start-auto-paper.sh" _run </dev/null >>"$LOG_FILE" 2>&1 &
    fi
    echo "$!" >"$PID_FILE"
  )
  local pid
  pid="$(read_pid)"
  emit_text_or_json "$action" "running" "1" "1" "started" "started pid=$pid ledger=$LEDGER_PATH archive=$ARCHIVE_PATH log=$LOG_FILE" "$pid"
}

stop() {
  if ! is_running; then
    rm -f "$PID_FILE"
    emit_text_or_json "stop" "stopped" "0" "1" "already_stopped" "stopped"
    return 0
  fi
  local pid
  pid="$(read_pid)"
  kill "$pid" >/dev/null 2>&1 || true
  for _ in $(seq 1 30); do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      rm -f "$PID_FILE"
      emit_text_or_json "stop" "stopped" "0" "1" "stopped" "stopped" "$pid"
      return 0
    fi
    sleep 0.2
  done
  kill -9 "$pid" >/dev/null 2>&1 || true
  rm -f "$PID_FILE"
  emit_text_or_json "stop" "stopped" "0" "1" "killed" "killed pid=$pid" "$pid"
}

status() {
  if is_running; then
    local pid
    pid="$(read_pid)"
    load_running_env_config "$pid"
    emit_text_or_json "status" "running" "1" "1" "running" "running pid=$pid ledger=$LEDGER_PATH log=$LOG_FILE" "$pid"
  else
    emit_text_or_json "status" "not_running" "0" "0" "not_running" "not running ledger=$LEDGER_PATH log=$LOG_FILE" "" "paper_service_not_running" "auto paper run-loop is not running"
    return 1
  fi
}

run_health_report() {
  local py
  py="$(python_bin)"
  cd "$APP_DIR"
  export PYTHONPATH="$APP_DIR/src:${PYTHONPATH:-}"
  "$py" -m tradecat_auto.cli health-report \
    --state-path "$STATE_PATH" \
    --ledger-path "$LEDGER_PATH" \
    --archive-path "$ARCHIVE_PATH" \
    --journal-path "$JOURNAL_PATH" \
    --max-heartbeat-age-seconds "$MAX_HEARTBEAT_AGE_SECONDS" \
    $(json_flag_args)
}

run_daily_report() {
  local py
  py="$(python_bin)"
  cd "$APP_DIR"
  export PYTHONPATH="$APP_DIR/src:${PYTHONPATH:-}"
  "$py" -m tradecat_auto.cli daily-report \
    --ledger-path "$LEDGER_PATH" \
    --archive-path "$ARCHIVE_PATH" \
    $(json_flag_args)
}

run_alert_payload() {
  local py
  py="$(python_bin)"
  cd "$APP_DIR"
  export PYTHONPATH="$APP_DIR/src:${PYTHONPATH:-}"
  "$py" -m tradecat_auto.cli alert-payload \
    --kind daily \
    --ledger-path "$LEDGER_PATH" \
    --archive-path "$ARCHIVE_PATH" \
    $(json_flag_args)
}

ops_check() {
  local py
  py="$(python_bin)"
  AUTO_OPS_RUNTIME_DIR="$RUNTIME_DIR" \
  AUTO_OPS_STATE_PATH="$STATE_PATH" \
  AUTO_OPS_LEDGER_PATH="$LEDGER_PATH" \
  AUTO_OPS_ARCHIVE_PATH="$ARCHIVE_PATH" \
  AUTO_OPS_JOURNAL_PATH="$JOURNAL_PATH" \
  AUTO_OPS_LOG_FILE="$LOG_FILE" \
  AUTO_OPS_PID_FILE="$PID_FILE" \
  AUTO_OPS_PYTHON="$py" \
  AUTO_OPS_APP_DIR="$APP_DIR" \
  AUTO_OPS_BASE_URL="$BASE_URL" \
  AUTO_OPS_SYSTEMCTL_BIN="$SYSTEMCTL_BIN" \
  AUTO_OPS_SYSTEMD_USER_DIR="$SYSTEMD_USER_DIR" \
  AUTO_OPS_SYSTEMD_SERVICE_UNIT="$SYSTEMD_SERVICE_UNIT" \
  AUTO_OPS_SYSTEMD_TIMER_UNIT="$SYSTEMD_TIMER_UNIT" \
  AUTO_OPS_MIN_FREE_BYTES="$MIN_FREE_BYTES" \
  AUTO_OPS_MIN_NOFILE="$MIN_NOFILE" \
  AUTO_OPS_MIN_NPROC="$MIN_NPROC" \
  AUTO_OPS_LIMIT_NOFILE="$LIMIT_NOFILE" \
  AUTO_OPS_TASKS_MAX="$TASKS_MAX" \
  AUTO_OPS_RESTART_SEC="$RESTART_SEC" \
  AUTO_OPS_START_LIMIT_BURST="$START_LIMIT_BURST" \
  AUTO_OPS_START_LIMIT_INTERVAL_SECONDS="$START_LIMIT_INTERVAL_SECONDS" \
  AUTO_OPS_TIMEOUT_START_SECONDS="$TIMEOUT_START_SECONDS" \
  "$py" - <<'PY'
import json
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

try:
    import resource
except ImportError:  # pragma: no cover - Windows fallback
    resource = None


def as_int(value: str, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def is_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except ValueError:
        return False
    return True


def check(checks, check_id, ok, severity, message, **extra):
    item = {"id": check_id, "ok": bool(ok), "severity": severity, "message": message}
    item.update(extra)
    checks.append(item)


runtime_dir = Path(os.environ["AUTO_OPS_RUNTIME_DIR"])
state_path = Path(os.environ["AUTO_OPS_STATE_PATH"])
ledger_path = Path(os.environ["AUTO_OPS_LEDGER_PATH"])
archive_path = Path(os.environ["AUTO_OPS_ARCHIVE_PATH"])
journal_path = Path(os.environ["AUTO_OPS_JOURNAL_PATH"])
log_file = Path(os.environ["AUTO_OPS_LOG_FILE"])
pid_file = Path(os.environ["AUTO_OPS_PID_FILE"])
app_dir = Path(os.environ["AUTO_OPS_APP_DIR"])
python_bin = Path(os.environ["AUTO_OPS_PYTHON"])
base_url = os.environ["AUTO_OPS_BASE_URL"]
systemctl_bin = os.environ["AUTO_OPS_SYSTEMCTL_BIN"]
min_free_bytes = as_int(os.environ["AUTO_OPS_MIN_FREE_BYTES"], 104857600)
min_nofile = as_int(os.environ["AUTO_OPS_MIN_NOFILE"], 1024)
min_nproc = as_int(os.environ["AUTO_OPS_MIN_NPROC"], 128)
checks = []

runtime_parent = runtime_dir.parent if runtime_dir.parent != Path("") else Path(".")
runtime_parent_exists = runtime_parent.exists()
free_bytes = shutil.disk_usage(runtime_parent if runtime_parent_exists else app_dir).free
check(checks, "runtime_parent_exists", runtime_parent_exists, "block", "runtime parent directory exists", path=str(runtime_parent))
check(checks, "runtime_parent_writable", os.access(runtime_parent if runtime_parent_exists else app_dir, os.W_OK), "block", "runtime parent is writable", path=str(runtime_parent))
check(checks, "disk_free_bytes", free_bytes >= min_free_bytes, "block", "runtime filesystem has enough free bytes", free_bytes=free_bytes, min_free_bytes=min_free_bytes)
for path_id, path in {
    "state_path_under_runtime": state_path,
    "ledger_path_under_runtime": ledger_path,
    "archive_path_under_runtime": archive_path,
    "journal_path_under_runtime": journal_path,
    "log_file_under_runtime": log_file,
    "pid_file_under_runtime": pid_file,
}.items():
    check(checks, path_id, is_under(path, runtime_dir), "block", f"{path_id} stays inside runtime_dir", path=str(path))

check(checks, "python_available", python_bin.exists() or shutil.which(str(python_bin)) is not None, "block", "python executable is available", python=str(python_bin))
check(checks, "project_source_exists", (app_dir / "src" / "tradecat_auto").exists(), "block", "tradecat_auto source tree exists", path=str(app_dir / "src" / "tradecat_auto"))
check(checks, "base_url_https", base_url.startswith("https://"), "block", "base_url uses https public endpoint", base_url=base_url)
check(checks, "systemctl_available", shutil.which(systemctl_bin) is not None, "warn", "systemctl is available for user timer install", systemctl=systemctl_bin)

uid = getattr(os, "geteuid", lambda: None)()
check(
    checks,
    "identity_detected",
    True,
    "info",
    "process identity detected; root is allowed only by operator policy, non-root is safer for public paper/watch",
    uid=uid,
    run_as_root=uid == 0,
)

credential_env_names = sorted(
    key for key in os.environ
    if re.search(r"BINANCE_.*(?:KEY|SECRET|SIGNATURE|LISTEN)", key, flags=re.IGNORECASE)
)
check(
    checks,
    "no_binance_credential_env_names",
    not credential_env_names,
    "block",
    "environment does not expose Binance credential-like variable names to this public paper process",
    env_names=credential_env_names,
)

if resource is not None:
    nofile_soft, nofile_hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    check(checks, "nofile_limit", nofile_soft >= min_nofile, "warn", "file descriptor soft limit is high enough", soft=nofile_soft, hard=nofile_hard, min_soft=min_nofile)
    if hasattr(resource, "RLIMIT_NPROC"):
        nproc_soft, nproc_hard = resource.getrlimit(resource.RLIMIT_NPROC)
        nproc_ok = nproc_soft == resource.RLIM_INFINITY or nproc_soft >= min_nproc
        check(checks, "process_task_limit", nproc_ok, "warn", "process/task soft limit is high enough", soft=nproc_soft, hard=nproc_hard, min_soft=min_nproc)
else:
    check(checks, "resource_limits_available", True, "info", "resource module unavailable; skip OS limit checks")

pid_text = ""
try:
    pid_text = pid_file.read_text(encoding="utf-8").strip()
except OSError:
    pass
check(checks, "single_pid_file", not pid_text or pid_text.isdigit(), "block", "pid file is absent or contains one numeric pid", pid=pid_text or None)

blocking = [item for item in checks if item["severity"] == "block" and not item["ok"]]
payload = {
    "schema": "tradecat_auto.paper_ops_report.v1",
    "schema_version": "1.0.0",
    "ok": not blocking,
    "mode": "paper",
    "command": "auto-paper-service",
    "action": "ops-check",
    "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "dependency_chain": [
        "Hermes/operator supervisor",
        "tradecat-public Skill package",
        "project Python environment",
        "public online sheet signal source",
        "Agent-supplied Binance public-readonly market context",
        "context-audit",
        "Agent trade thesis or paper autonomy profile with explicit paper sizing and exits",
        "portfolio risk policy / paper kill switch",
        "auto-paper run-loop",
        "paper ledger / cycle archive / audit journal",
        "health-report / daily-report / alert-payload",
    ],
    "runtime": {
        "runtime_dir": str(runtime_dir),
        "state_path": str(state_path),
        "ledger_path": str(ledger_path),
        "archive_path": str(archive_path),
        "journal_path": str(journal_path),
        "log_file": str(log_file),
        "pid_file": str(pid_file),
    },
    "systemd": {
        "user_dir": os.environ["AUTO_OPS_SYSTEMD_USER_DIR"],
        "service_unit": os.environ["AUTO_OPS_SYSTEMD_SERVICE_UNIT"],
        "timer_unit": os.environ["AUTO_OPS_SYSTEMD_TIMER_UNIT"],
        "start_limit_burst": as_int(os.environ["AUTO_OPS_START_LIMIT_BURST"], 5),
        "start_limit_interval_seconds": as_int(os.environ["AUTO_OPS_START_LIMIT_INTERVAL_SECONDS"], 600),
        "restart_sec": os.environ["AUTO_OPS_RESTART_SEC"],
        "timeout_start_seconds": as_int(os.environ["AUTO_OPS_TIMEOUT_START_SECONDS"], 120),
        "limit_nofile": as_int(os.environ["AUTO_OPS_LIMIT_NOFILE"], 4096),
        "tasks_max": as_int(os.environ["AUTO_OPS_TASKS_MAX"], 64),
    },
    "checks": checks,
    "blocking_checks": [item["id"] for item in blocking],
    "operations": {
        "lifecycle": "systemd timer or Hermes/operator heal should restart missing paper loop",
        "restart_storm": "systemd StartLimitBurst/StartLimitIntervalSec and RestartSec bound retry pressure",
        "identity": "uid/run_as_root is reported; public paper/watch does not require Binance credentials",
        "logging_audit": "log_file plus paper_audit.sqlite3 preserve service behavior and audit chain",
        "health": "health-report detects heartbeat_stale, ledger/archive/audit failures, and process-alive-but-stale cases",
        "dependencies": "ops-check validates Python, paths, disk, limits, systemctl availability, and credential env names",
        "rollback": "use git checkout/tag outside runtime; runtime ledger/archive remain isolated under .runtime",
    },
    "safety": {
        "public_readonly_market_data": True,
        "paper_or_watch_only": True,
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "binance_account_state": False,
    },
}
if blocking:
    payload["error"] = {
        "code": "paper_ops_preflight_failed",
        "kind": "configuration",
        "message": "one or more blocking auto-paper ops checks failed",
        "retryable": False,
    }
print(json.dumps(payload, ensure_ascii=False))
raise SystemExit(0 if payload["ok"] else 1)
PY
}

heal() {
  if ! is_running; then
    start "heal"
    return $?
  fi
  local tmp_health
  local previous_json="$JSON"
  local py
  py="$(python_bin)"
  tmp_health="$(mktemp)"
  JSON=1
  if ! run_health_report >"$tmp_health" 2>/dev/null; then
    JSON="$previous_json"
    rm -f "$tmp_health"
    restart
    return $?
  fi
  JSON="$previous_json"
  if "$py" - "$tmp_health" <<'PY' >/dev/null 2>&1; then
import json
import sys
payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
alerts = set(payload.get("alerts") or [])
raise SystemExit(0 if payload.get("ok") and "heartbeat_stale" not in alerts else 1)
PY
    rm -f "$tmp_health"
    status
  else
    rm -f "$tmp_health"
    restart
  fi
}

restart() {
  if [[ "$JSON" -eq 1 ]]; then
    stop >/dev/null || true
    start "restart"
    return $?
  fi
  stop
  start
}

write_systemd_units() {
  mkdir -p "$SYSTEMD_USER_DIR" "$RUNTIME_DIR"
  local service_path="$SYSTEMD_USER_DIR/$SYSTEMD_SERVICE_UNIT"
  local timer_path="$SYSTEMD_USER_DIR/$SYSTEMD_TIMER_UNIT"
  {
    cat <<UNIT
[Unit]
Description=TradeCat auto paper trading cycle (public data, paper only)
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=$START_LIMIT_INTERVAL_SECONDS
StartLimitBurst=$START_LIMIT_BURST

[Service]
Type=oneshot
WorkingDirectory=$APP_DIR
TimeoutStartSec=$TIMEOUT_START_SECONDS
Restart=on-failure
RestartSec=$RESTART_SEC
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=$APP_DIR/src
Environment=TRADECAT_AUTO_PAPER_RUNTIME_DIR=$RUNTIME_DIR
Environment=TRADECAT_AUTO_PAPER_STATE_PATH=$STATE_PATH
Environment=TRADECAT_AUTO_PAPER_LEDGER_PATH=$LEDGER_PATH
Environment=TRADECAT_AUTO_PAPER_ARCHIVE_PATH=$ARCHIVE_PATH
Environment=TRADECAT_AUTO_PAPER_JOURNAL_PATH=$JOURNAL_PATH
Environment=TRADECAT_AUTO_PAPER_LOG_FILE=$LOG_FILE
Environment=TRADECAT_AUTO_PAPER_INTERVAL_SECONDS=$INTERVAL_SECONDS
Environment=TRADECAT_AUTO_PAPER_MAINTENANCE_INTERVAL_SECONDS=$MAINTENANCE_INTERVAL_SECONDS
UNIT
    local proxy_key proxy_value
    for proxy_key in HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY http_proxy https_proxy all_proxy no_proxy; do
      proxy_value="${!proxy_key:-}"
      if [[ -n "$proxy_value" ]]; then
        printf 'Environment=%s=%s\n' "$proxy_key" "$proxy_value"
      fi
    done
    if [[ -n "$PAPER_MARGIN_BUDGET_USDT" ]]; then
      printf 'Environment=TRADECAT_AUTO_PAPER_MARGIN_BUDGET_USDT=%s\n' "$PAPER_MARGIN_BUDGET_USDT"
    fi
    if [[ -n "$AGENT_MARGIN_USDT" ]]; then
      printf 'Environment=TRADECAT_AUTO_PAPER_AGENT_MARGIN_USDT=%s\n' "$AGENT_MARGIN_USDT"
    fi
    if [[ -n "$EFFECTIVE_NOTIONAL_USDT" ]]; then
      printf 'Environment=TRADECAT_AUTO_PAPER_EFFECTIVE_NOTIONAL_USDT=%s\n' "$EFFECTIVE_NOTIONAL_USDT"
    fi
    if [[ -n "$PAPER_LEVERAGE" ]]; then
      printf 'Environment=TRADECAT_AUTO_PAPER_LEVERAGE=%s\n' "$PAPER_LEVERAGE"
    fi
    if [[ -n "$AGENT_TRADE_THESIS_PATH" ]]; then
      printf 'Environment=TRADECAT_AUTO_PAPER_AGENT_TRADE_THESIS_PATH=%s\n' "$AGENT_TRADE_THESIS_PATH"
    fi
    if [[ -n "$PAPER_AUTONOMY_PROFILE_PATH" ]]; then
      printf 'Environment=TRADECAT_AUTO_PAPER_AUTONOMY_PROFILE_PATH=%s\n' "$PAPER_AUTONOMY_PROFILE_PATH"
    fi
    cat <<UNIT
Environment=TRADECAT_AUTO_PAPER_INITIAL_BALANCE_USDT=$INITIAL_BALANCE_USDT
Environment=TRADECAT_AUTO_PAPER_FEE_BPS=$PAPER_FEE_BPS
Environment=TRADECAT_AUTO_PAPER_SLIPPAGE_BPS=$PAPER_SLIPPAGE_BPS
Environment=TRADECAT_AUTO_PAPER_MAX_HOLDING_MINUTES=$PAPER_MAX_HOLDING_MINUTES
Environment=TRADECAT_AUTO_PAPER_MAX_EVENT_AGE_SECONDS=$MAX_EVENT_AGE_SECONDS
Environment=TRADECAT_AUTO_PAPER_EVENT_LIMIT=$EVENT_LIMIT
Environment=TRADECAT_AUTO_PAPER_ANOMALY_LIMIT=$ANOMALY_LIMIT
Environment=TRADECAT_AUTO_PAPER_SYMBOL=$SYMBOL
Environment=TRADECAT_AUTO_PAPER_BASE_URL=$BASE_URL
Environment=TRADECAT_AUTO_PAPER_PORTFOLIO_RISK_POLICY_PATH=$PORTFOLIO_RISK_POLICY_PATH
Environment=TRADECAT_AUTO_PAPER_KILL_SWITCH_PATH=$PAPER_KILL_SWITCH_PATH
ExecStart=$APP_DIR/scripts/start-auto-paper.sh _cycle
StandardOutput=append:$LOG_FILE
StandardError=append:$LOG_FILE
UMask=0077
LimitNOFILE=$LIMIT_NOFILE
TasksMax=$TASKS_MAX
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
LockPersonality=true
RestrictSUIDSGID=true

[Install]
WantedBy=default.target
UNIT
  } >"$service_path"
  cat >"$timer_path" <<UNIT
[Unit]
Description=Run TradeCat auto paper cycle every $INTERVAL_SECONDS seconds

[Timer]
OnBootSec=30s
OnUnitActiveSec=${INTERVAL_SECONDS}s
AccuracySec=5s
Persistent=true
Unit=$SYSTEMD_SERVICE_UNIT

[Install]
WantedBy=timers.target
UNIT
}

systemd_install() {
  write_systemd_units
  if ! "$SYSTEMCTL_BIN" --user daemon-reload; then
    emit_text_or_json "systemd-install" "failed" "0" "0" "daemon_reload_failed" "systemd daemon-reload failed" "" "systemd_daemon_reload_failed" "systemctl --user daemon-reload failed"
    return 1
  fi
  if ! "$SYSTEMCTL_BIN" --user enable --now "$SYSTEMD_TIMER_UNIT"; then
    emit_text_or_json "systemd-install" "failed" "0" "0" "enable_failed" "systemd timer enable failed" "" "systemd_timer_enable_failed" "systemctl --user enable --now $SYSTEMD_TIMER_UNIT failed"
    return 1
  fi
  emit_text_or_json "systemd-install" "enabled" "1" "1" "timer_enabled" "installed and enabled $SYSTEMD_TIMER_UNIT in $SYSTEMD_USER_DIR"
}

systemd_uninstall() {
  mkdir -p "$SYSTEMD_USER_DIR"
  "$SYSTEMCTL_BIN" --user disable --now "$SYSTEMD_TIMER_UNIT" >/dev/null 2>&1 || true
  rm -f "$SYSTEMD_USER_DIR/$SYSTEMD_SERVICE_UNIT" "$SYSTEMD_USER_DIR/$SYSTEMD_TIMER_UNIT"
  "$SYSTEMCTL_BIN" --user daemon-reload >/dev/null 2>&1 || true
  emit_text_or_json "systemd-uninstall" "disabled" "0" "1" "timer_disabled" "disabled and removed $SYSTEMD_TIMER_UNIT from $SYSTEMD_USER_DIR"
}

case "$ACTION" in
  start) start ;;
  stop) stop ;;
  restart) restart ;;
  status) status ;;
  ops-check) ops_check ;;
  heal) heal ;;
  health) run_health_report ;;
  daily) run_daily_report ;;
  alert) run_alert_payload ;;
  systemd-install) systemd_install ;;
  systemd-uninstall) systemd_uninstall ;;
  _run) run_forever ;;
  _cycle) run_cycle ;;
  *) echo "usage: $0 [--json] start|stop|restart|status|ops-check|heal|systemd-install|systemd-uninstall" >&2; exit 2 ;;
esac
