#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${TRADECAT_TERMINAL_RUNTIME_DIR:-$HOME/.tradecat-terminal/run}"
CACHE_DIR="${TRADECAT_CACHE_DIR:-$APP_DIR/.tradecat/cache}"
INTERVAL="${TRADECAT_TERMINAL_WATCH_INTERVAL:-60}"
DATASET="${TRADECAT_TERMINAL_WATCH_DATASET:-}"
PID_FILE="$RUNTIME_DIR/watch.pid"
LOG_FILE="$RUNTIME_DIR/watch.log"

mkdir -p "$RUNTIME_DIR"

is_running() {
  [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" >/dev/null 2>&1
}

start() {
  if is_running; then
    echo "running pid=$(cat "$PID_FILE") cache=$CACHE_DIR log=$LOG_FILE"
    return 0
  fi
  rm -f "$PID_FILE"
  local cmd=(python3 -m tradecat_terminal --cache-dir "$CACHE_DIR" watch --interval "$INTERVAL")
  if [[ -n "$DATASET" ]]; then
    cmd=(python3 -m tradecat_terminal --cache-dir "$CACHE_DIR" watch "$DATASET" --interval "$INTERVAL")
  fi
  (
    cd "$APP_DIR"
    export PYTHONPATH="$APP_DIR/src:${PYTHONPATH:-}"
    nohup "${cmd[@]}" >>"$LOG_FILE" 2>&1 &
    echo "$!" >"$PID_FILE"
  )
  echo "started pid=$(cat "$PID_FILE") cache=$CACHE_DIR interval=$INTERVAL log=$LOG_FILE"
}

stop() {
  if ! is_running; then
    rm -f "$PID_FILE"
    echo "stopped"
    return 0
  fi
  local pid
  pid="$(cat "$PID_FILE")"
  kill "$pid" >/dev/null 2>&1 || true
  for _ in $(seq 1 20); do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      rm -f "$PID_FILE"
      echo "stopped"
      return 0
    fi
    sleep 0.2
  done
  kill -9 "$pid" >/dev/null 2>&1 || true
  rm -f "$PID_FILE"
  echo "killed pid=$pid"
}

status() {
  if is_running; then
    echo "running pid=$(cat "$PID_FILE") cache=$CACHE_DIR log=$LOG_FILE"
  else
    echo "not running cache=$CACHE_DIR log=$LOG_FILE"
    return 1
  fi
}

case "${1:-status}" in
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  status) status ;;
  *) echo "usage: $0 start|stop|restart|status" >&2; exit 2 ;;
esac
