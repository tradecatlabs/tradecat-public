#!/usr/bin/env bash
# sheets-service 启动脚本
# 用法: ./scripts/start.sh {start|stop|status|restart}

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_DIR="$(dirname "$SCRIPT_DIR")"

find_repo_root() {
    local start="$1"
    local p="$start"
    while [[ -n "$p" && "$p" != "/" ]]; do
        if [[ -d "$p/services" && ( -e "$p/assets/config/.env.example" || -e "$p/config/.env.example" ) && ( -d "$p/assets" || -d "$p/libs" ) ]]; then
            echo "$p"
            return 0
        fi
        p="$(dirname "$p")"
    done
    return 1
}

PROJECT_ROOT="$(find_repo_root "$SERVICE_DIR" || true)"
if [[ -z "$PROJECT_ROOT" ]]; then
    echo "❌ 错误: 无法定位 PROJECT_ROOT（从 $SERVICE_DIR 向上未找到 services + assets/config/.env.example）"
    exit 1
fi

RUN_DIR="$SERVICE_DIR/pids"
LOG_DIR="$SERVICE_DIR/logs"
DAEMON_LOG="$LOG_DIR/daemon.log"
PID_FILE="$RUN_DIR/sheets.pid"
OUT_LOG="$LOG_DIR/sheets.log"
STOP_TIMEOUT=10

safe_load_env() {
    local file="$1"
    [ -f "$file" ] || return 0
    if [[ ( "$file" == *"assets/config/.env" ) || ( "$file" == *"config/.env" ) ]] && [[ ! "$file" == *".example" ]]; then
        local perm
        perm=$(stat -c %a "$file" 2>/dev/null || echo "")
        if [[ -n "$perm" && "$perm" != "600" && "$perm" != "400" ]]; then
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
safe_load_env "$SERVICE_DIR/.env"

init_dirs() {
    mkdir -p "$RUN_DIR" "$LOG_DIR" "$SERVICE_DIR/data"
}

is_running() {
    local pid=$1
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

get_pid() {
    [ -f "$PID_FILE" ] && cat "$PID_FILE"
}

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$DAEMON_LOG"
}

start_svc() {
    init_dirs
    local pid
    pid="$(get_pid)"
    if is_running "$pid"; then
        echo "✓ sheets-service 已运行 (PID: $pid)"
        return 0
    fi

    cd "$SERVICE_DIR"
    source .venv/bin/activate
    export PYTHONDONTWRITEBYTECODE=1
    nohup python3 -u -B -m src --daemon >> "$OUT_LOG" 2>&1 &
    local new_pid=$!
    echo "$new_pid" > "$PID_FILE"

    sleep 2
    if is_running "$new_pid"; then
        log "START sheets-service (PID: $new_pid)"
        echo "✓ sheets-service 已启动 (PID: $new_pid)"
        return 0
    fi

    log "ERROR sheets-service 启动失败"
    echo "✗ sheets-service 启动失败，查看日志: $OUT_LOG"
    return 1
}

stop_svc() {
    local pid
    pid="$(get_pid)"
    if ! is_running "$pid"; then
        echo "sheets-service 未运行"
        rm -f "$PID_FILE"
        return 0
    fi

    kill "$pid" 2>/dev/null
    local waited=0
    while is_running "$pid" && [ $waited -lt $STOP_TIMEOUT ]; do
        sleep 1
        ((waited++))
    done

    if is_running "$pid"; then
        kill -9 "$pid" 2>/dev/null
        log "KILL sheets-service (PID: $pid) 强制终止"
    else
        log "STOP sheets-service (PID: $pid)"
    fi

    rm -f "$PID_FILE"
    echo "✓ sheets-service 已停止"
}

status_svc() {
    local pid
    pid="$(get_pid)"
    if is_running "$pid"; then
        local uptime
        uptime=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')
        echo "✓ sheets-service 运行中 (PID: $pid, 运行: $uptime)"
        echo ""
        echo "=== 最近日志 ==="
        tail -10 "$OUT_LOG" 2>/dev/null || true
        return 0
    fi
    echo "✗ sheets-service 未运行"
    return 1
}

case "${1:-status}" in
    start) start_svc ;;
    stop) stop_svc ;;
    status) status_svc ;;
    restart) stop_svc; sleep 2; start_svc ;;
    *) echo "用法: $0 {start|stop|status|restart}"; exit 1 ;;
esac
