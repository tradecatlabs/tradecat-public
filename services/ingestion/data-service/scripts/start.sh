#!/usr/bin/env bash
# data-service 启动/守护脚本
# 用法: ./scripts/start.sh {start|stop|status|restart}

set -uo pipefail

# ==================== 配置区 ====================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_DIR="$(dirname "$SCRIPT_DIR")"
# 目录迁移后 services 层级可能变化，避免写死 ../../../.. 导致指向错误根目录
find_project_root() {
    local current="$1"
    for _ in {1..12}; do
        if [[ -f "$current/assets/config/.env.example" ]] && [[ -d "$current/services" ]]; then
            echo "$current"
            return 0
        fi
        if [[ -f "$current/config/.env.example" ]] && [[ -d "$current/services" ]]; then
            # 兼容旧路径（仅用于定位 root）
            echo "$current"
            return 0
        fi
        local parent
        parent="$(dirname "$current")"
        [[ "$parent" == "$current" ]] && break
        current="$parent"
    done
    # 兜底：兼容当前分层（services/ingestion/data-service）
    (cd "$SERVICE_DIR/../../.." && pwd)
}
PROJECT_ROOT="$(find_project_root "$SERVICE_DIR")"
RUN_DIR="$SERVICE_DIR/pids"
LOG_DIR="$SERVICE_DIR/logs"
DAEMON_PID="$RUN_DIR/daemon.pid"
DAEMON_LOG="$LOG_DIR/daemon.log"
CHECK_INTERVAL="${CHECK_INTERVAL:-30}"
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
            # 不覆盖外部已显式设置的环境变量（便于两库共存/临时覆盖）
            if [[ -z "${!key+x}" ]]; then
                export "$key=$val"
            fi
        fi
    done < "$file"
}

# 记录外部是否已显式指定 DATABASE_URL（用于两库共存时避免被 .env 覆盖）
DATABASE_URL_PRESET=0
if [[ -n "${DATABASE_URL:-}" ]]; then
    DATABASE_URL_PRESET=1
fi

# 加载全局配置（不覆盖外部环境）
ENV_FILE="$PROJECT_ROOT/assets/config/.env"
if [ ! -f "$ENV_FILE" ] && [ -f "$PROJECT_ROOT/config/.env" ]; then
    ENV_FILE="$PROJECT_ROOT/config/.env"
fi
safe_load_env "$ENV_FILE"

# data-service 专用 DB：若外部未显式指定 DATABASE_URL，则优先使用 DATA_SERVICE_DATABASE_URL
if [[ "$DATABASE_URL_PRESET" = "0" ]] && [[ -n "${DATA_SERVICE_DATABASE_URL:-}" ]]; then
    export DATABASE_URL="$DATA_SERVICE_DATABASE_URL"
fi

# 配置已统一到 assets/config/.env
if [ -z "${BINANCE_PING_URL:-}" ]; then
    if [ -n "${BINANCE_REST_BASE_MAINNET:-}" ]; then
        BINANCE_PING_URL="${BINANCE_REST_BASE_MAINNET%/}/api/v3/ping"
    elif [ -n "${BINANCE_FAPI_BASE:-}" ]; then
        BINANCE_PING_URL="${BINANCE_FAPI_BASE%/}/fapi/v1/ping"
    fi
fi

# ==================== 自愈配置（DB 新鲜度）====================
# 目标：当 WebSocket 进程仍在，但 DB 长时间不再写入新 K 线时，自动重启 ws。
# 说明：
# - 只监控 1m K 线表（candles_1m），以“最新 bucket_ts 距离当前时间的秒数”衡量新鲜度。
# - 连续 N 次陈旧才触发重启，避免短暂抖动导致误杀。
WS_DB_SELF_HEAL_ENABLED="${DATA_SERVICE_WS_DB_SELF_HEAL_ENABLED:-1}"
WS_DB_STALE_MAX_AGE_SECONDS="${DATA_SERVICE_WS_DB_STALE_MAX_AGE_SECONDS:-240}"
WS_DB_STALE_CONSECUTIVE="${DATA_SERVICE_WS_DB_STALE_CONSECUTIVE:-3}"
WS_DB_SELF_HEAL_WARMUP_SECONDS="${DATA_SERVICE_WS_DB_SELF_HEAL_WARMUP_SECONDS:-300}"
WS_DB_SELF_HEAL_SKIP_ON_BAN="${DATA_SERVICE_WS_DB_SELF_HEAL_SKIP_ON_BAN:-1}"
export DATA_SERVICE_WS_DB_CHECK_CONNECT_TIMEOUT_SECONDS="${DATA_SERVICE_WS_DB_CHECK_CONNECT_TIMEOUT_SECONDS:-3}"

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
            delay=$((delay * 2))  # 指数退避: 1s, 2s, 4s
        fi
    done
    
    echo "⚠️  代理不可用（重试${retries}次失败），已禁用: $proxy"
    unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
}

# 组件定义
COMPONENTS=(backfill metrics ws)

# 启动命令
declare -A START_CMDS=(
[backfill]="python3 -c \"
import time, logging, sys
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger('backfill.patrol')
from collectors.backfill import DataBackfiller, get_backfill_config, compute_lookback

mode, env_days, on_start, start_date = get_backfill_config()
lookback = compute_lookback(mode, env_days, start_date)

if lookback <= 0:
    logger.info('BACKFILL_MODE=none，跳过巡检')
    sys.exit(0)

logger.info('补齐巡检启动: mode=%s lookback=%d days', mode, lookback)
bf = DataBackfiller(lookback_days=lookback)

if on_start:
    try:
        logger.info('启动时执行一次全量补齐...')
        result = bf.run_all()
        logger.info('启动补齐完成: %s', result)
    except Exception as e:
        logger.error('启动补齐异常: %s', e, exc_info=True)

while True:
    try:
        logger.info('开始缺口巡检...')
        result = bf.run_all()
        klines = result.get('klines', {})
        metrics = result.get('metrics', {})
        logger.info('巡检完成: K线填充 %d 条, Metrics填充 %d 条, 5分钟后再次检查',
                    klines.get('filled', 0), metrics.get('filled', 0))
    except Exception as e:
        logger.error('巡检异常: %s', e, exc_info=True)
    time.sleep(300)
\""
    [metrics]="python3 -c \"
import time, logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
from collectors.metrics import MetricsCollector
c = MetricsCollector()
while True:
    c.run_once()
    time.sleep(300)
\""
    [ws]="python3 -m collectors.ws"
)

# ==================== 工具函数 ====================
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$DAEMON_LOG"
}

is_uint() {
    [[ "${1:-}" =~ ^[0-9]+$ ]]
}

ban_remaining_seconds() {
    # rate_limiter.py 使用 $SERVICE_ROOT/logs/.ban_until；这里用 LOG_DIR 对齐
    local file="$LOG_DIR/.ban_until"
    [ -f "$file" ] || return 1

    local until
    until="$(head -n 1 "$file" 2>/dev/null | tr -d ' \t\r\n')"
    [ -z "$until" ] && return 1

    local now
    now="$(date +%s)"

    # until 可能是 float；用 awk 做浮点比较与取整差值
    awk -v until="$until" -v now="$now" 'BEGIN { if (until > now) printf "%d", (until - now); else printf "0" }'
}

init_dirs() {
    mkdir -p "$RUN_DIR" "$LOG_DIR"
}

is_running() {
    local pid=$1
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

get_pid() {
    local name=$1
    local pid_file="$RUN_DIR/${name}.pid"
    [ -f "$pid_file" ] && cat "$pid_file"
}

db_latest_candle_age_seconds() {
    local db_url="${DATABASE_URL:-}"
    if [ -z "$db_url" ]; then
        return 2
    fi

    local python_bin="$SERVICE_DIR/.venv/bin/python3"
    if [ ! -x "$python_bin" ]; then
        python_bin="python3"
    fi

    local out
    out="$(
        "$python_bin" - <<'PY'
import os
import sys
from datetime import datetime, timezone

try:
    import psycopg
    from psycopg import sql
except Exception:
    sys.exit(3)

db_url = os.getenv("DATABASE_URL", "")
schema = os.getenv("KLINE_DB_SCHEMA", "market_data")
exchange = os.getenv("BINANCE_WS_DB_EXCHANGE", "binance_futures_um")
timeout_s = int(os.getenv("DATA_SERVICE_WS_DB_CHECK_CONNECT_TIMEOUT_SECONDS", "3") or "3")

if not db_url:
    sys.exit(2)

try:
    with psycopg.connect(db_url, connect_timeout=timeout_s) as conn:
        with conn.cursor() as cur:
            q = sql.SQL("SELECT bucket_ts FROM {} WHERE exchange = %s ORDER BY bucket_ts DESC LIMIT 1").format(
                sql.Identifier(schema, "candles_1m")
            )
            cur.execute(q, (exchange,))
            row = cur.fetchone()
except Exception:
    sys.exit(4)

if not row or not row[0]:
    # DB 为空：用一个极大值表示“非常陈旧”，由 bash 侧 warmup / consecutive 逻辑兜底
    print(10**9)
    sys.exit(0)

ts = row[0]
if ts.tzinfo is None:
    ts = ts.replace(tzinfo=timezone.utc)
age = (datetime.now(timezone.utc) - ts).total_seconds()
print(int(age))
PY
    )" || return 1

    if ! is_uint "$out"; then
        return 1
    fi
    echo "$out"
}

# ==================== 组件管理 ====================
start_component() {
    local name=$1
    local pid_file="$RUN_DIR/${name}.pid"
    local log_file="$LOG_DIR/${name}.log"
    
    local pid=$(get_pid "$name")
    if is_running "$pid"; then
        echo "  $name: 已运行 (PID: $pid)"
        return 0
    fi
    
    cd "$SERVICE_DIR"
    source .venv/bin/activate
    export PYTHONPATH=src
    # 用 setsid 彻底与当前会话脱钩，避免在非交互/CI 执行器中被“会话回收”误杀
    # 并在子 shell 内 exec，确保 pidfile 指向真实的 Python 进程（而不是 bash 包装器）
    local cmd="exec ${START_CMDS[$name]}"
    setsid bash -c "$cmd" >> "$log_file" 2>&1 < /dev/null &
    local new_pid=$!
    echo "$new_pid" > "$pid_file"

    if [ "$name" = "ws" ]; then
        WS_LAST_START_EPOCH="$(date +%s)"
    fi
    
    sleep 1
    if is_running "$new_pid"; then
        log "START $name (PID: $new_pid)"
        echo "  $name: 已启动 (PID: $new_pid)"
        return 0
    else
        log "ERROR $name 启动失败"
        echo "  $name: 启动失败"
        return 1
    fi
}

stop_component() {
    local name=$1
    local pid_file="$RUN_DIR/${name}.pid"
    local pid=$(get_pid "$name")
    
    if ! is_running "$pid"; then
        echo "  $name: 未运行"
        rm -f "$pid_file"
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
        log "KILL $name (PID: $pid) 强制终止"
    else
        log "STOP $name (PID: $pid)"
    fi
    
    rm -f "$pid_file"
    echo "  $name: 已停止"
}

status_component() {
    local name=$1
    local pid=$(get_pid "$name")
    
    if is_running "$pid"; then
        local uptime=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')
        echo "  ✓ $name: 运行中 (PID: $pid, 运行: $uptime)"
        return 0
    else
        echo "  ✗ $name: 未运行"
        return 1
    fi
}

# ==================== 守护进程 ====================
daemon_loop() {
    log "守护进程启动 (检查间隔: ${CHECK_INTERVAL}s)"
    local ws_db_stale_count=0
    local ws_last_start_epoch=0
    while true; do
        for name in "${COMPONENTS[@]}"; do
            local pid=$(get_pid "$name")
            if ! is_running "$pid"; then
                log "检测到 $name 未运行，重启..."
                start_component "$name" >/dev/null
            fi
        done

        # 同步 ws 最近启动时间（由 start_component ws 更新）
        if is_uint "${WS_LAST_START_EPOCH:-}"; then
            ws_last_start_epoch="$WS_LAST_START_EPOCH"
        fi

        # -------------------- ws 自愈：按 DB 新鲜度重启 --------------------
        if [ "${WS_DB_SELF_HEAL_ENABLED:-0}" = "1" ]; then
            if is_uint "$WS_DB_STALE_MAX_AGE_SECONDS" && is_uint "$WS_DB_STALE_CONSECUTIVE" && is_uint "$WS_DB_SELF_HEAL_WARMUP_SECONDS"; then
                local ws_pid
                ws_pid="$(get_pid ws)"
                if is_running "$ws_pid"; then
                    # 兜底：若 ws 是外部已有进程，首次进入守护时记录一个“近似启动时间”，避免立即误判。
                    if [ "$ws_last_start_epoch" -le 0 ]; then
                        ws_last_start_epoch="$(date +%s)"
                    fi

                    local now_epoch
                    now_epoch="$(date +%s)"
                    local ws_uptime
	                    ws_uptime=$((now_epoch - ws_last_start_epoch))

	                    if [ "$ws_uptime" -ge "$WS_DB_SELF_HEAL_WARMUP_SECONDS" ]; then
	                        local age
	                        if age="$(db_latest_candle_age_seconds)"; then
	                            if [ "$age" -ge "$WS_DB_STALE_MAX_AGE_SECONDS" ]; then
	                                if [ "${WS_DB_SELF_HEAL_SKIP_ON_BAN:-0}" = "1" ]; then
	                                    local ban_remain
	                                    ban_remain="$(ban_remaining_seconds 2>/dev/null || echo "")"
	                                    if is_uint "$ban_remain" && [ "$ban_remain" -gt 0 ]; then
	                                        log "ws DB 自愈跳过: DB陈旧(age=${age}s) 但 ban 剩余 ${ban_remain}s"
	                                        ws_db_stale_count=0
	                                    else
	                                        ws_db_stale_count=$((ws_db_stale_count + 1))
	                                        log "ws DB 新鲜度陈旧: age=${age}s 连续=${ws_db_stale_count}/${WS_DB_STALE_CONSECUTIVE}"
	                                        if [ "$ws_db_stale_count" -ge "$WS_DB_STALE_CONSECUTIVE" ]; then
	                                            log "ws DB 连续陈旧，执行自愈重启 ws..."
	                                            stop_component ws >/dev/null
	                                            start_component ws >/dev/null
	                                            ws_db_stale_count=0
	                                            ws_last_start_epoch="${WS_LAST_START_EPOCH:-$(date +%s)}"
	                                        fi
	                                    fi
	                                else
	                                    ws_db_stale_count=$((ws_db_stale_count + 1))
	                                    log "ws DB 新鲜度陈旧: age=${age}s 连续=${ws_db_stale_count}/${WS_DB_STALE_CONSECUTIVE}"
	                                    if [ "$ws_db_stale_count" -ge "$WS_DB_STALE_CONSECUTIVE" ]; then
	                                        log "ws DB 连续陈旧，执行自愈重启 ws..."
	                                        stop_component ws >/dev/null
	                                        start_component ws >/dev/null
	                                        ws_db_stale_count=0
	                                        ws_last_start_epoch="${WS_LAST_START_EPOCH:-$(date +%s)}"
	                                    fi
	                                fi
	                            else
	                                ws_db_stale_count=0
	                            fi
	                        else
	                            # DB 检查失败：不做“强动作”，只记录日志，避免 DB/网络抖动导致重启风暴
                            log "ws DB 新鲜度检查失败，跳过本轮自愈"
                        fi
                    fi
                fi
            else
                log "ws DB 自愈配置非法，已跳过（请检查 DATA_SERVICE_WS_DB_STALE_*）"
            fi
        fi

        sleep "$CHECK_INTERVAL"
    done
}

# 独立的守护循环入口：用于 setsid 启动，避免 bash 函数后台运行被会话回收
cmd_daemon_loop() {
    init_dirs
    daemon_loop
}

cmd_daemon() {
    init_dirs
    
    # 检查是否已有守护进程
    if [ -f "$DAEMON_PID" ]; then
        local pid=$(cat "$DAEMON_PID")
        if is_running "$pid"; then
            echo "守护进程已运行 (PID: $pid)"
            return 0
        fi
    fi
    
    # 先启动所有服务
    echo "=== 启动守护模式 ==="
    for name in "${COMPONENTS[@]}"; do
        start_component "$name"
    done
    
    # 后台启动守护循环
    # - 必须断开 stdin/stdout/stderr，避免继承上层管道导致卡死
    # - 必须 setsid 脱钩，避免在非交互执行器中被进程组清理
    # daemon-loop 内部使用 log() 写入 $DAEMON_LOG；此处将 stdout/stderr 丢弃，避免 tee 写同一文件导致重复行
    setsid bash "$SCRIPT_DIR/start.sh" daemon-loop >/dev/null 2>&1 < /dev/null &
    local dpid=$!
    echo "$dpid" > "$DAEMON_PID"
    log "守护进程已启动 (PID: $dpid)"
    echo "守护进程已启动 (PID: $dpid)"
}

cmd_stop() {
    echo "=== 停止全部服务 ==="
    
    # 先停守护进程
    if [ -f "$DAEMON_PID" ]; then
        local dpid=$(cat "$DAEMON_PID")
        if is_running "$dpid"; then
            kill "$dpid" 2>/dev/null
            log "STOP daemon (PID: $dpid)"
            echo "  daemon: 已停止"
        fi
        rm -f "$DAEMON_PID"
    fi
    
    for name in "${COMPONENTS[@]}"; do
        stop_component "$name"
    done
}

# ==================== 主命令 ====================
cmd_start() {
    # 启动前打印目标 DB（避免两库共存时写错库）
    if [ -n "${DATABASE_URL:-}" ]; then
        python3 - <<'PY' || true
import os
from urllib.parse import urlparse

u = os.environ.get("DATABASE_URL", "")
p = urlparse(u)
host = p.hostname or ""
port = p.port or ""
db = (p.path or "").lstrip("/")
schema = os.environ.get("KLINE_DB_SCHEMA", "market_data")
print(f"→ data-service 目标库: {host}:{port}/{db} schema={schema}")
PY
    else
        echo "⚠️  data-service 未配置 DATABASE_URL（将无法写库）"
    fi
    # 默认就是守护模式
    cmd_daemon
}

cmd_status() {
    echo "=== 服务状态 ==="
    local all_running=0
    
    # 守护进程状态
    if [ -f "$DAEMON_PID" ]; then
        local dpid=$(cat "$DAEMON_PID")
        if is_running "$dpid"; then
            echo "  ✓ daemon: 运行中 (PID: $dpid)"
        else
            echo "  ✗ daemon: 未运行"
            all_running=1
        fi
    else
        echo "  ✗ daemon: 未运行"
        all_running=1
    fi
    
    for name in "${COMPONENTS[@]}"; do
        if ! status_component "$name"; then
            all_running=1
        fi
    done
    
    return $all_running
}

cmd_restart() {
    cmd_stop
    sleep 2
    cmd_start
}

# ==================== 入口 ====================
case "${1:-status}" in
    start)   check_proxy; cmd_start ;;
    stop)    cmd_stop ;;
    status)  cmd_status ;;
    restart) check_proxy; cmd_restart ;;
    daemon-loop) cmd_daemon_loop ;;
    *)
        echo "用法: $0 {start|stop|status|restart}"
        exit 1
        ;;
esac
