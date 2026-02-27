#!/usr/bin/env bash
# trading-service 启动/守护脚本
# 用法: ./scripts/start.sh {start|stop|status|restart|daemon}

set -uo pipefail

# ==================== 配置区 ====================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_DIR="$(dirname "$SCRIPT_DIR")"
# 目录迁移后 services 层级可能变化，避免写死 ../../.. 导致指向错误根目录
find_project_root() {
    local current="$1"
    for _ in {1..12}; do
        if [[ -f "$current/config/.env.example" ]] && [[ -d "$current/services" ]]; then
            echo "$current"
            return 0
        fi
        local parent
        parent="$(dirname "$current")"
        [[ "$parent" == "$current" ]] && break
        current="$parent"
    done
    # 兜底：兼容当前分层（services/compute/trading-service）
    (cd "$SERVICE_DIR/../../.." && pwd)
}
PROJECT_ROOT="$(find_project_root "$SERVICE_DIR")"
RUN_DIR="$SERVICE_DIR/pids"
LOG_DIR="$SERVICE_DIR/logs"
DAEMON_PID="$RUN_DIR/daemon.pid"
DAEMON_LOG="$LOG_DIR/daemon.log"
SERVICE_PID="$RUN_DIR/service.pid"
SERVICE_LOG="$LOG_DIR/service.log"
CHECK_INTERVAL="${CHECK_INTERVAL:-30}"
STOP_TIMEOUT=10

# 安全加载 .env（只读键值解析，拒绝危险行）
safe_load_env() {
    local file="$1"
    [ -f "$file" ] || return 0
    
    # 检查权限（生产环境强制 600）
    if [[ "$file" == *"config/.env" ]] && [[ ! "$file" == *".example" ]]; then
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
safe_load_env "$PROJECT_ROOT/config/.env"
# 配置已统一到 config/.env
if [ -z "${BINANCE_PING_URL:-}" ]; then
    if [ -n "${BINANCE_REST_BASE_MAINNET:-}" ]; then
        BINANCE_PING_URL="${BINANCE_REST_BASE_MAINNET%/}/api/v3/ping"
    elif [ -n "${BINANCE_FAPI_BASE:-}" ]; then
        BINANCE_PING_URL="${BINANCE_FAPI_BASE%/}/fapi/v1/ping"
    fi
fi

# ==================== 计算后端强制配置 ====================
# 避免线程后端被 GIL 限制，默认走进程后端；如需覆盖，设置 FORCE_* 环境变量。
cpu_count="$(command -v nproc >/dev/null 2>&1 && nproc || getconf _NPROCESSORS_ONLN || echo 4)"
export COMPUTE_BACKEND="${FORCE_COMPUTE_BACKEND:-process}"
export MAX_CPU_WORKERS="${FORCE_MAX_CPU_WORKERS:-$cpu_count}"
export MAX_WORKERS="${FORCE_MAX_WORKERS:-$cpu_count}"

# 校验 SYMBOLS_* 格式
validate_symbols() {
    local errors=0
    for var in $(env | grep -E '^SYMBOLS_(GROUP_|EXTRA|EXCLUDE)' | cut -d= -f1); do
        local val="${!var}"
        [ -z "$val" ] && continue
        for sym in ${val//,/ }; do
            sym="${sym^^}"
            if [[ ! "$sym" =~ ^[A-Z0-9]+USDT$ ]]; then
                echo "❌ 无效币种 $var: $sym"
                errors=1
            fi
        done
    done
    [ $errors -eq 1 ] && exit 1
}
validate_symbols

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

# 启动命令
MODE="${MODE:-simple}"
START_CMD="python3 -u -m src.simple_scheduler"
[ "$MODE" = "listener" ] && START_CMD="python3 -u -m src.kline_listener"

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

get_service_pid() {
    [ -f "$SERVICE_PID" ] && cat "$SERVICE_PID"
}

# ==================== 服务管理 ====================
start_service() {
    init_dirs
    local pid=$(get_service_pid)
    if is_running "$pid"; then
        echo "✓ 服务已运行 (PID: $pid)"
        return 0
    fi
    
    cd "$SERVICE_DIR"
    source .venv/bin/activate
    export PYTHONPATH="$SERVICE_DIR"
    # 用 setsid 彻底与当前会话脱钩，避免在非交互/CI 执行器中被“会话回收”误杀
    setsid $START_CMD >> "$SERVICE_LOG" 2>&1 < /dev/null &
    local new_pid=$!
    echo "$new_pid" > "$SERVICE_PID"
    
    sleep 1
    if is_running "$new_pid"; then
        log "START 服务 (PID: $new_pid, MODE: $MODE)"
        echo "✓ 服务已启动 (PID: $new_pid, MODE: $MODE)"
        return 0
    else
        log "ERROR 服务启动失败"
        echo "✗ 服务启动失败"
        return 1
    fi
}

stop_service() {
    local pid=$(get_service_pid)
    if ! is_running "$pid"; then
        echo "服务未运行"
        rm -f "$SERVICE_PID"
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
        log "KILL 服务 (PID: $pid) 强制终止"
    else
        log "STOP 服务 (PID: $pid)"
    fi
    
    rm -f "$SERVICE_PID"
    echo "✓ 服务已停止"
}

status_service() {
    local pid=$(get_service_pid)
    if is_running "$pid"; then
        local uptime=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')
        echo "✓ 服务运行中 (PID: $pid, 运行: $uptime)"
        echo ""
        echo "=== 最近日志 ==="
        tail -10 "$SERVICE_LOG" 2>/dev/null
        return 0
    else
        echo "✗ 服务未运行"
        return 1
    fi
}

# ==================== 入口 ====================
case "${1:-status}" in
    start)   check_proxy; start_service ;;
    stop)    stop_service ;;
    status)  status_service ;;
    restart) check_proxy; stop_service; sleep 2; start_service ;;
    *)
        echo "用法: $0 {start|stop|status|restart}"
        exit 1
        ;;
esac
