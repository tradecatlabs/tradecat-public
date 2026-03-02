#!/usr/bin/env bash
# vis-service 启动/守护脚本
# 用法: ./scripts/start.sh {start|stop|status|restart}

set -uo pipefail

# ==================== 路径配置 ====================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(cd "$SERVICE_DIR/../../.." && pwd)"
RUN_DIR="$SERVICE_DIR/pids"
LOG_DIR="$SERVICE_DIR/logs"
SERVICE_PID="$RUN_DIR/service.pid"
SERVICE_LOG="$LOG_DIR/service.log"

# ==================== 环境加载 ====================
safe_load_env() {
    local file="$1"
    [ -f "$file" ] || return 0

    # 生产配置必须 600 权限
    if [[ "$file" == *"config/.env" ]] && [[ ! "$file" == *".example" ]]; then
        local perm
        perm=$(stat -c %a "$file" 2>/dev/null)
        if [[ "$perm" != "600" && "$perm" != "400" ]]; then
            if [[ "${CODESPACES:-}" == "true" ]]; then
                echo "⚠️  Codespace 环境，跳过权限检查 ($file: $perm)"
            else
                echo "❌ 错误: $file 权限为 $perm，必须设为 600"
                echo "   执行: chmod 600 $file"
                exit 1
            fi
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

# 优先读取统一配置入口：assets/config/.env
safe_load_env "$PROJECT_ROOT/assets/config/.env"
# 兼容：少量历史环境仍可能使用顶层 config/.env（不推荐）
safe_load_env "$PROJECT_ROOT/config/.env"

HOST="${VIS_SERVICE_HOST:-0.0.0.0}"
PORT="${VIS_SERVICE_PORT:-8087}"
TOKEN="${VIS_SERVICE_TOKEN:-}"

START_CMD="uvicorn src.main:app --host $HOST --port $PORT"

# ==================== 工具函数 ====================
init_dirs() {
    mkdir -p "$RUN_DIR" "$LOG_DIR"
}

is_running() {
    local pid="$1"
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

get_service_pid() {
    [ -f "$SERVICE_PID" ] && cat "$SERVICE_PID"
}

# ==================== 服务控制 ====================
start_service() {
    init_dirs
    local pid
    pid=$(get_service_pid)
    if is_running "$pid"; then
        echo "✓ 服务已运行 (PID: $pid)"
        return 0
    fi

    cd "$SERVICE_DIR"
    if [ ! -d ".venv" ]; then
        echo "⚠️  未发现 .venv，请先运行 ./scripts/init.sh vis-service"
        return 1
    fi

    source .venv/bin/activate
    export PYTHONPATH=src
    nohup $START_CMD >> "$SERVICE_LOG" 2>&1 &
    local new_pid=$!
    echo "$new_pid" > "$SERVICE_PID"
    sleep 1

    if is_running "$new_pid"; then
        echo "✓ 服务已启动 (PID: $new_pid, 端口: $PORT)"
    else
        echo "✗ 服务启动失败，查看日志: $SERVICE_LOG"
        return 1
    fi
}

stop_service() {
    local pid
    pid=$(get_service_pid)
    if ! is_running "$pid"; then
        echo "服务未运行"
        rm -f "$SERVICE_PID"
        return 0
    fi
    kill "$pid" 2>/dev/null
    sleep 1
    if is_running "$pid"; then
        kill -9 "$pid" 2>/dev/null
    fi
    rm -f "$SERVICE_PID"
    echo "✓ 服务已停止"
}

status_service() {
    local pid
    pid=$(get_service_pid)
    if is_running "$pid"; then
        echo "✓ 服务运行中 (PID: $pid)"
        echo "=== 最近日志 ==="
        tail -n 10 "$SERVICE_LOG" 2>/dev/null
    else
        echo "✗ 服务未运行"
    fi
}

case "${1:-status}" in
    start) start_service ;;
    stop) stop_service ;;
    status) status_service ;;
    restart) stop_service; sleep 1; start_service ;;
    *)
        echo "用法: $0 {start|stop|status|restart}"
        exit 1
        ;;
esac
