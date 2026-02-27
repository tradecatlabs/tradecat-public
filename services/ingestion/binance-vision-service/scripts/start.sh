#!/usr/bin/env bash
# binance-vision-service 启动脚本（最小骨架）
# 用法: ./scripts/start.sh {start|stop|status|restart}

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(cd "$SERVICE_DIR/../../.." && pwd)"
RUN_DIR="$SERVICE_DIR/pids"
LOG_DIR="$SERVICE_DIR/logs"
SERVICE_PID="$RUN_DIR/service.pid"
SERVICE_LOG="$LOG_DIR/service.log"
STOP_TIMEOUT=10

safe_load_env() {
    local file="$1"
    [ -f "$file" ] || return 0

    if [[ ( "$file" == *"assets/config/.env" ) || ( "$file" == *"config/.env" ) ]] && [[ ! "$file" == *".example" ]]; then
        local perm
        perm=$(stat -c %a "$file" 2>/dev/null || echo "")
        if [[ -n "$perm" ]] && [[ "$perm" != "600" && "$perm" != "400" ]]; then
            echo "❌ 错误: $file 权限为 $perm，必须设为 600"
            echo "   执行: chmod 600 $file"
            exit 1
        fi
    fi

    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
        [[ "$line" =~ ^[[:space:]]*export ]] && continue
        [[ "$line" =~ \$\( ]] && continue
        [[ "$line" =~ \` ]] && continue
        if [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
            local key="${BASH_REMATCH[1]}"
            local val="${BASH_REMATCH[2]}"
            val="${val#\"}" && val="${val%\"}"
            val="${val#\'}" && val="${val%\'}"
            export "$key=$val"
        fi
    done < "$file"
}

ENV_FILE="$PROJECT_ROOT/assets/config/.env"
if [ ! -f "$ENV_FILE" ] && [ -f "$PROJECT_ROOT/config/.env" ]; then
    ENV_FILE="$PROJECT_ROOT/config/.env"
fi
safe_load_env "$ENV_FILE"

init_dirs() {
    mkdir -p "$RUN_DIR" "$LOG_DIR"
}

is_running() {
    local pid=$1
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

get_pid() {
    [ -f "$SERVICE_PID" ] && cat "$SERVICE_PID"
}

start_service() {
    init_dirs
    local pid
    pid="$(get_pid)"
    if is_running "$pid"; then
        echo "✓ 服务已运行 (PID: $pid)"
        return 0
    fi

    cd "$SERVICE_DIR"
    if [ -f ".venv/bin/activate" ]; then
        # shellcheck disable=SC1091
        source .venv/bin/activate
    fi
    export PYTHONPATH="$SERVICE_DIR"

    nohup python3 -u -m src >> "$SERVICE_LOG" 2>&1 &
    local new_pid=$!
    echo "$new_pid" > "$SERVICE_PID"
    sleep 1

    if is_running "$new_pid"; then
        echo "✓ 服务已启动 (PID: $new_pid)"
        return 0
    fi
    echo "✗ 服务启动失败"
    return 1
}

stop_service() {
    local pid
    pid="$(get_pid)"
    if ! is_running "$pid"; then
        echo "服务未运行"
        rm -f "$SERVICE_PID"
        return 0
    fi

    kill "$pid" 2>/dev/null || true
    local waited=0
    while is_running "$pid" && [ $waited -lt $STOP_TIMEOUT ]; do
        sleep 1
        ((waited++))
    done

    if is_running "$pid"; then
        kill -9 "$pid" 2>/dev/null || true
    fi

    rm -f "$SERVICE_PID"
    echo "✓ 服务已停止"
}

status_service() {
    local pid
    pid="$(get_pid)"
    if is_running "$pid"; then
        local uptime
        uptime="$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ' || true)"
        echo "✓ 服务运行中 (PID: $pid, 运行: ${uptime:-unknown})"
        echo "  日志: $SERVICE_LOG"
        return 0
    fi
    echo "✗ 服务未运行"
    return 1
}

case "${1:-}" in
    start) start_service ;;
    stop) stop_service ;;
    status) status_service ;;
    restart)
        stop_service || true
        start_service
        ;;
    *)
        echo "用法: $0 {start|stop|status|restart}"
        exit 1
        ;;
 esac
