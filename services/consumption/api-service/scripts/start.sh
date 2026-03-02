#!/bin/bash
# API Service 启动脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_NAME="api-service"
PID_FILE="$SERVICE_DIR/pids/api.pid"
LOG_FILE="$SERVICE_DIR/logs/api.log"
PORT="${API_SERVICE_PORT:-8088}"

cd "$SERVICE_DIR"

# 确保目录存在
mkdir -p pids logs

start() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "✓ API 已运行 (PID: $(cat "$PID_FILE"))"
        return 0
    fi

    echo "启动 API Service (端口: $PORT)..."
    # 必须 setsid 脱钩，避免在非交互/CI 执行器中被“会话回收”误杀
    # 并在子 shell 内 exec，确保 PID 文件指向真实的 Python 进程（而不是 bash 包装器）
    setsid bash -c "exec .venv/bin/python -m src" >> "$LOG_FILE" 2>&1 < /dev/null &
    echo $! > "$PID_FILE"
    sleep 2

    if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "✓ API 已启动 (PID: $(cat "$PID_FILE"))"
    else
        echo "✗ API 启动失败，查看日志: $LOG_FILE"
        return 1
    fi
}

stop() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "停止 API (PID: $PID)..."
            kill "$PID"
            sleep 2
            if kill -0 "$PID" 2>/dev/null; then
                kill -9 "$PID" 2>/dev/null || true
            fi
            echo "✓ API 已停止"
        else
            echo "API 未运行"
        fi
        rm -f "$PID_FILE"
    else
        echo "API 未运行"
    fi
}

status() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        PID=$(cat "$PID_FILE")
        UPTIME=$(ps -p "$PID" -o etime= 2>/dev/null | xargs)
        echo "✓ API 运行中 (PID: $PID, 运行: $UPTIME)"
        echo ""
        echo "=== 最近日志 ==="
        tail -10 "$LOG_FILE" 2>/dev/null || echo "无日志"
    else
        echo "✗ API 未运行"
    fi
}

case "${1:-status}" in
    start)   start ;;
    stop)    stop ;;
    restart) stop; sleep 1; start ;;
    status)  status ;;
    *)       echo "用法: $0 {start|stop|restart|status}"; exit 1 ;;
esac
