#!/usr/bin/env bash
# telegram-service 启动脚本
# 用法: ./scripts/start.sh {start|stop|status|restart}

set -uo pipefail

# ==================== 配置区 ====================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(cd "$SERVICE_DIR/../../.." && pwd)"
RUN_DIR="$SERVICE_DIR/pids"
LOG_DIR="$SERVICE_DIR/logs"
DAEMON_LOG="$LOG_DIR/daemon.log"
BOT_PID="$RUN_DIR/bot.pid"
BOT_LOG="$LOG_DIR/bot.log"
STOP_TIMEOUT=10

# 安全加载 .env（只读键值解析，拒绝危险行）
safe_load_env() {
    local file="$1"
    [ -f "$file" ] || return 0
    
    # 检查权限（生产环境强制 600）
    if [[ ( "$file" == *"assets/config/.env" ) || ( "$file" == *"config/.env" ) ]] && [[ ! "$file" == *".example" ]]; then
        local perm=$(stat -c %a "$file" 2>/dev/null)
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

# 加载全局配置 → 服务配置
ENV_FILE="$PROJECT_ROOT/assets/config/.env"
if [ ! -f "$ENV_FILE" ] && [ -f "$PROJECT_ROOT/config/.env" ]; then
    # 兼容旧路径（只读回退，不创建旧目录）
    ENV_FILE="$PROJECT_ROOT/config/.env"
fi
safe_load_env "$ENV_FILE"
# 配置已统一到 assets/config/.env
if [ -z "${BINANCE_PING_URL:-}" ]; then
    if [ -n "${BINANCE_REST_BASE_MAINNET:-}" ]; then
        BINANCE_PING_URL="${BINANCE_REST_BASE_MAINNET%/}/api/v3/ping"
    elif [ -n "${BINANCE_FAPI_BASE:-}" ]; then
        BINANCE_PING_URL="${BINANCE_FAPI_BASE%/}/fapi/v1/ping"
    fi
fi

# 代理自检（重试3次+指数退避冷却）
check_proxy() {
    local proxy="${HTTP_PROXY:-${HTTPS_PROXY:-}}"
    [ -z "$proxy" ] && return 0
    
    local retries=3
    local delay=1
    local i=0
    local ping_url="${BINANCE_PING_URL:-}"
    [ -z "$ping_url" ] && return 0
    
    while [ $i -lt $retries ]; do
        if curl -s --max-time 3 --proxy "$proxy" "$ping_url" >/dev/null 2>&1; then
            echo "✓ 代理可用: $proxy"
            return 0
        fi
        ((i++))
        if [ $i -lt $retries ]; then
            echo "  代理检测失败，${delay}秒后重试 ($i/$retries)..."
            sleep $delay
            delay=$((delay * 2))
        fi
    done
    
    echo "⚠️  代理不可用（重试${retries}次失败），已禁用: $proxy"
    unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
}

# ==================== 工具函数 ====================
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$DAEMON_LOG"
}

init_dirs() {
    mkdir -p "$RUN_DIR" "$LOG_DIR"
}

is_running() {
    local pid=$1
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

get_bot_pid() {
    [ -f "$BOT_PID" ] && cat "$BOT_PID"
}

# ==================== Bot 管理 ====================
start_bot() {
    init_dirs
    local pid=$(get_bot_pid)
    if is_running "$pid"; then
        echo "✓ Bot 已运行 (PID: $pid)"
        return 0
    fi
    
    cd "$SERVICE_DIR/src"
    source ../.venv/bin/activate
    # 用 setsid 彻底与当前会话脱钩，避免被调用方会话回收误杀（CI/非交互环境常见）
    setsid python3 -u main.py >> "$BOT_LOG" 2>&1 < /dev/null &
    local new_pid=$!
    echo "$new_pid" > "$BOT_PID"
    
    sleep 2
    if is_running "$new_pid"; then
        log "START Bot (PID: $new_pid)"
        echo "✓ Bot 已启动 (PID: $new_pid)"
        return 0
    else
        log "ERROR Bot 启动失败"
        echo "✗ Bot 启动失败"
        return 1
    fi
}

stop_bot() {
    local pid=$(get_bot_pid)
    if ! is_running "$pid"; then
        echo "Bot 未运行"
        rm -f "$BOT_PID"
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
        log "KILL Bot (PID: $pid) 强制终止"
    else
        log "STOP Bot (PID: $pid)"
    fi
    
    rm -f "$BOT_PID"
    echo "✓ Bot 已停止"
}

status_bot() {
    local pid=$(get_bot_pid)
    if is_running "$pid"; then
        local uptime=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')
        echo "✓ Bot 运行中 (PID: $pid, 运行: $uptime)"
        echo ""
        echo "=== 最近日志 ==="
        tail -10 "$BOT_LOG" 2>/dev/null
        return 0
    else
        echo "✗ Bot 未运行"
        return 1
    fi
}

# ==================== 入口 ====================
case "${1:-status}" in
    start)   check_proxy; start_bot ;;
    stop)    stop_bot ;;
    status)  status_bot ;;
    restart) check_proxy; stop_bot; sleep 2; start_bot ;;
    *)
        echo "用法: $0 {start|stop|status|restart}"
        exit 1
        ;;
esac
