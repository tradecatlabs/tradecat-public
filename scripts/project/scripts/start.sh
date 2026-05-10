#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${TRADECAT_TERMINAL_RUNTIME_DIR:-$HOME/.tradecat-terminal/run}"
CACHE_DIR="${TRADECAT_CACHE_DIR:-$APP_DIR/.tradecat/cache}"
INTERVAL="${TRADECAT_TERMINAL_WATCH_INTERVAL:-60}"
DATASET="${TRADECAT_TERMINAL_WATCH_DATASET:-}"
WATCH_NO_WRITE="${TRADECAT_TERMINAL_WATCH_NO_WRITE:-}"
PID_FILE="$RUNTIME_DIR/watch.pid"
LOG_FILE="$RUNTIME_DIR/watch.log"
ACTION="status"
JSON=0

mkdir -p "$RUNTIME_DIR"

for arg in "$@"; do
  case "$arg" in
    --json) JSON=1 ;;
    start|stop|restart|status) ACTION="$arg" ;;
    *) echo "usage: $0 [--json] start|stop|restart|status" >&2; exit 2 ;;
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
  [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1
}

truthy() {
  case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
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
  WATCH_JSON_ACTION="$action" \
  WATCH_JSON_STATE="$state" \
  WATCH_JSON_RUNNING="$running" \
  WATCH_JSON_OK="$ok" \
  WATCH_JSON_EVENT="$event" \
  WATCH_JSON_PID="$pid" \
  WATCH_JSON_ERROR_CODE="$error_code" \
  WATCH_JSON_ERROR_MESSAGE="$error_message" \
  WATCH_JSON_RUNTIME_DIR="$RUNTIME_DIR" \
  WATCH_JSON_CACHE_DIR="$CACHE_DIR" \
  WATCH_JSON_LOG_FILE="$LOG_FILE" \
  WATCH_JSON_INTERVAL="$INTERVAL" \
  WATCH_JSON_DATASET="$DATASET" \
  WATCH_JSON_PYTHON="$py" \
  WATCH_JSON_NO_WRITE="$WATCH_NO_WRITE" \
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
    try:
        return float(value)
    except ValueError:
        return value


ok = truthy(os.environ["WATCH_JSON_OK"])
payload = {
    "schema": "tradecat.watch_status.v1",
    "schema_version": "1.0.0",
    "ok": ok,
    "command": "watch-status",
    "action": os.environ["WATCH_JSON_ACTION"],
    "state": os.environ["WATCH_JSON_STATE"],
    "event": os.environ["WATCH_JSON_EVENT"],
    "running": truthy(os.environ["WATCH_JSON_RUNNING"]),
    "pid": optional_int(os.environ["WATCH_JSON_PID"]),
    "runtime_dir": os.environ["WATCH_JSON_RUNTIME_DIR"],
    "cache_dir": os.environ["WATCH_JSON_CACHE_DIR"],
    "log_file": os.environ["WATCH_JSON_LOG_FILE"],
    "dataset": os.environ["WATCH_JSON_DATASET"] or None,
    "interval_seconds": optional_float(os.environ["WATCH_JSON_INTERVAL"]),
    "write": not truthy(os.environ["WATCH_JSON_NO_WRITE"]),
    "python": os.environ["WATCH_JSON_PYTHON"],
    "health": "spawned_unverified" if truthy(os.environ["WATCH_JSON_RUNNING"]) else "not_running",
}
if not ok:
    payload["error"] = {
        "code": os.environ["WATCH_JSON_ERROR_CODE"] or "watch_not_running",
        "kind": "runtime",
        "message": os.environ["WATCH_JSON_ERROR_MESSAGE"] or "watch process is not running",
        "hint": "Run scripts/project/scripts/start.sh start --json, then verify remote data with tradecat probe --json --no-write.",
        "retryable": False,
    }
print(json.dumps(payload, ensure_ascii=False))
PY
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

start() {
  if is_running; then
    local pid
    pid="$(read_pid)"
    emit_text_or_json "start" "running" "1" "1" "already_running" "running pid=$pid cache=$CACHE_DIR log=$LOG_FILE" "$pid"
    return 0
  fi
  rm -f "$PID_FILE"
  local py
  py="$(python_bin)"
  local cmd=("$py" -m tradecat_terminal --cache-dir "$CACHE_DIR" watch --interval "$INTERVAL")
  if [[ -n "$DATASET" ]]; then
    cmd=("$py" -m tradecat_terminal --cache-dir "$CACHE_DIR" watch "$DATASET" --interval "$INTERVAL")
  fi
  if truthy "$WATCH_NO_WRITE"; then
    cmd+=("--no-write")
  fi
  (
    cd "$APP_DIR"
    export PYTHONPATH="$APP_DIR/src:${PYTHONPATH:-}"
    nohup "${cmd[@]}" >>"$LOG_FILE" 2>&1 &
    echo "$!" >"$PID_FILE"
  )
  local pid
  pid="$(read_pid)"
  emit_text_or_json "start" "running" "1" "1" "started" "started pid=$pid cache=$CACHE_DIR interval=$INTERVAL log=$LOG_FILE" "$pid"
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
  for _ in $(seq 1 20); do
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
    emit_text_or_json "status" "running" "1" "1" "running" "running pid=$pid cache=$CACHE_DIR log=$LOG_FILE" "$pid"
  else
    emit_text_or_json "status" "not_running" "0" "0" "not_running" "not running cache=$CACHE_DIR log=$LOG_FILE" "" "watch_not_running" "watch process is not running"
    return 1
  fi
}

restart() {
  if [[ "$JSON" -eq 1 ]]; then
    stop >/dev/null || true
    start
    return $?
  fi
  stop
  start
}

case "$ACTION" in
  start) start ;;
  stop) stop ;;
  restart) restart ;;
  status) status ;;
  *) echo "usage: $0 [--json] start|stop|restart|status" >&2; exit 2 ;;
esac
