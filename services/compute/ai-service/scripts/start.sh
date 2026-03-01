#!/bin/bash
# ai-service 启动脚本
# 作为 telegram-service 子模块，提供就绪检查与测试入口

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(cd "$SERVICE_DIR/../../.." && pwd)"
RUN_DIR="$SERVICE_DIR/pids"
LOG_DIR="$SERVICE_DIR/logs"
READY_FILE="$RUN_DIR/ai-service.ready"
READY_LOG="$LOG_DIR/ai-service.log"

cd "$SERVICE_DIR"

# 加载全局配置
# 安全加载 .env（只读键值解析，拒绝危险行）
safe_load_env() {
    local file="$1"
    [ -f "$file" ] || return 0

    # 检查权限（生产环境强制 600）
    if [[ ( "$file" == *"assets/config/.env" ) || ( "$file" == *"config/.env" ) ]] && [[ ! "$file" == *".example" ]]; then
        local perm
        perm=$(stat -c %a "$file" 2>/dev/null || echo "")
        if [[ -n "$perm" && "$perm" != "600" && "$perm" != "400" ]]; then
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

ENV_FILE="$PROJECT_ROOT/assets/config/.env"
if [ ! -f "$ENV_FILE" ] && [ -f "$PROJECT_ROOT/config/.env" ]; then
    ENV_FILE="$PROJECT_ROOT/config/.env"
fi
safe_load_env "$ENV_FILE"

# 激活虚拟环境（优先用 telegram-service 的）
TELEGRAM_VENV="$PROJECT_ROOT/services/consumption/telegram-service/.venv"
if [ -d "$TELEGRAM_VENV" ]; then
    source "$TELEGRAM_VENV/bin/activate"
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# 添加项目路径
export PYTHONPATH="$SERVICE_DIR:$PROJECT_ROOT:${PYTHONPATH:-}"

# ==================== 工具函数 ====================
log() {
    mkdir -p "$LOG_DIR"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$READY_LOG"
}

ensure_dirs() {
    mkdir -p "$RUN_DIR" "$LOG_DIR"
}

run_check() {
    python3 - <<'PY'
import sys
errors = []

# 检查 psycopg
try:
    import psycopg
    print('✅ psycopg')
except ImportError:
    print('❌ psycopg (pip install psycopg[binary])')
    errors.append('psycopg')

# 检查 dotenv
try:
    from dotenv import load_dotenv  # noqa: F401
    print('✅ python-dotenv')
except ImportError:
    print('❌ python-dotenv')
    errors.append('dotenv')

# 检查 gemini_client
try:
    from assets.common.utils.gemini_client import call_gemini_with_system  # noqa: F401
    print('✅ gemini_client')
except ImportError as e:
    print(f'⚠️  gemini_client: {e}')

# 检查数据库连接串
try:
    import os
    db_url = os.getenv("DATABASE_URL") or os.getenv("TIMESCALE_DATABASE_URL")
    if db_url:
        print("✅ DATABASE_URL")
    else:
        print("⚠️  未设置 DATABASE_URL / TIMESCALE_DATABASE_URL")
except Exception as e:
    print(f"❌ 配置错误: {e}")

if errors:
    print(f'\n需要安装: pip install {" ".join(errors)}')
    sys.exit(1)
else:
    print('\n✅ 依赖检查通过')
PY
}

start_service() {
    ensure_dirs
    if [ -f "$READY_FILE" ]; then
        echo "✓ ai-service 已就绪 (非独立进程)"
        return 0
    fi

    echo "🔍 检查依赖..."
    if run_check; then
        date '+%Y-%m-%d %H:%M:%S' > "$READY_FILE"
        log "READY ai-service"
        echo "✓ ai-service 就绪 (作为 telegram-service 子模块)"
        return 0
    fi

    echo "✗ ai-service 依赖检查失败"
    return 1
}

stop_service() {
    ensure_dirs
    if [ -f "$READY_FILE" ]; then
        rm -f "$READY_FILE"
        log "STOP ai-service"
        echo "✓ ai-service 已退出就绪状态"
        return 0
    fi
    echo "ai-service 未标记就绪"
    return 0
}

status_service() {
    if [ -f "$READY_FILE" ]; then
        echo "✓ ai-service 就绪 (非独立进程)"
        return 0
    fi
    echo "✗ ai-service 未就绪"
    return 1
}

case "${1:-}" in
    start)
        start_service
        ;;
    stop)
        stop_service
        ;;
    status)
        status_service
        ;;
    restart)
        stop_service
        start_service
        ;;
    test)
        echo "📊 测试数据获取..."
        python3 -c "
from src.data.fetcher import fetch_payload
import json

symbol = '${2:-BTCUSDT}'
payload = fetch_payload(symbol, '15m')

print(f'币种: {symbol}')
print(f'K线周期: {list(payload.get(\"candles_latest_50\", {}).keys())}')
print(f'期货数据: {len(payload.get(\"metrics_5m_latest_50\", []))} 条')
print(f'指标表: {len(payload.get(\"indicator_samples\", {}))} 个')

# 显示部分数据
candles_1h = payload.get('candles_latest_50', {}).get('1h', [])
if candles_1h:
    latest = candles_1h[0]
    print(f'最新1h K线: {latest.get(\"bucket_ts\")} close={latest.get(\"close\")}')
"
        ;;
        
    analyze)
        symbol="${2:-BTCUSDT}"
        interval="${3:-1h}"
        prompt="${4:-市场全局解析}"
        
        echo "🤖 分析 $symbol @ $interval (提示词: $prompt)..."
        python3 -c "
import asyncio
from src.pipeline import run_analysis

async def main():
    result = await run_analysis('$symbol', '$interval', '$prompt')
    if 'error' in result:
        print('❌ 错误:', result['error'])
    else:
        print(result['analysis'])

asyncio.run(main())
"
        ;;
        
    prompts)
        echo "📝 可用提示词:"
        python3 -c "
from src.prompt import PromptRegistry
registry = PromptRegistry()
for item in registry.list_prompts():
    print(f'  - {item[\"name\"]}')
"
        ;;
        
    check)
        echo "🔍 检查依赖..."
        run_check
        ;;
        
    *)
        echo "用法: $0 {start|stop|status|restart|test|analyze|prompts|check} [参数]"
        echo ""
        echo "命令:"
        echo "  start                      就绪检查（非独立进程）"
        echo "  stop                       退出就绪状态"
        echo "  status                     查看就绪状态"
        echo "  restart                    重建就绪状态"
        echo "  test [symbol]              测试数据获取 (默认 BTCUSDT)"
        echo "  analyze [symbol] [interval] [prompt]  运行 AI 分析"
        echo "  prompts                    列出可用提示词"
        echo "  check                      检查依赖"
        echo ""
        echo "示例:"
        echo "  $0 test ETHUSDT"
        echo "  $0 analyze BTCUSDT 1h 市场全局解析"
        ;;
esac
