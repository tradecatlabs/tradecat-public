#!/usr/bin/env bash
# tradecat 环境检查脚本
# 用法: ./scripts/check_env.sh
# 检查所有运行依赖，确保"安装即运行"

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# ==================== 工具函数 ====================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

success() { echo -e "${GREEN}✓${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1"; ERRORS=$((ERRORS + 1)); }
warn() { echo -e "${YELLOW}⚠${NC} $1"; WARNINGS=$((WARNINGS + 1)); }
info() { echo -e "${BLUE}→${NC} $1"; }

ERRORS=0
WARNINGS=0

# ==================== 服务目录发现（兼容分层） ====================
find_service_dir() {
    local svc="$1"
    local candidates=(
        "$ROOT/services/$svc"                  # 兼容旧布局
        "$ROOT/services/ingestion/$svc"        # 新布局：采集层
        "$ROOT/services/compute/$svc"          # 新布局：计算层
        "$ROOT/services/consumption/$svc"      # 新布局：消费层
        "$ROOT/services-preview/$svc"          # 历史遗留（如仍存在）
    )
    local cand
    for cand in "${candidates[@]}"; do
        if [ -d "$cand" ]; then
            echo "$cand"
            return 0
        fi
    done
    return 1
}

# ==================== 1. Python 环境 ====================
check_python() {
    echo ""
    echo "=== Python 环境 ==="
    
    # Python 版本
    if command -v python3 &>/dev/null; then
        local py_ver=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
        local py_major=$(python3 -c "import sys; print(sys.version_info.major)")
        local py_minor=$(python3 -c "import sys; print(sys.version_info.minor)")
        
        if [ "$py_major" -ge 3 ] && [ "$py_minor" -ge 10 ]; then
            success "Python: $py_ver"
        else
            fail "Python 版本需要 3.10+，当前: $py_ver"
        fi
    else
        fail "Python3 未安装"
        return 1
    fi
    
    # pip
    if python3 -m pip --version &>/dev/null; then
        local pip_ver=$(python3 -m pip --version | cut -d' ' -f2)
        success "pip: $pip_ver"
    else
        fail "pip 未安装"
    fi
    
    # venv
    if python3 -m venv --help &>/dev/null; then
        success "venv: 可用"
    else
        fail "venv 模块不可用，请安装: sudo apt install python3-venv"
    fi
}

# ==================== 2. 系统依赖 ====================
check_system_deps() {
    echo ""
    echo "=== 系统依赖 ==="
    
    # Git
    if command -v git &>/dev/null; then
        success "git: $(git --version | cut -d' ' -f3)"
    else
        warn "git 未安装 (版本控制不可用)"
    fi
    
    # PostgreSQL client
    if command -v psql &>/dev/null; then
        success "psql: $(psql --version 2>&1 | head -1 | grep -oP '\d+\.\d+')"
    else
        warn "psql 未安装 (数据库操作受限)"
        echo "      安装: sudo apt install postgresql-client"
    fi
    
    # curl
    if command -v curl &>/dev/null; then
        success "curl: 已安装"
    else
        fail "curl 未安装"
    fi
    
    # TA-Lib (可选)
    if python3 -c "import talib" 2>/dev/null; then
        success "TA-Lib: 已安装"
    else
        info "TA-Lib: 未安装 (K线形态检测不可用)"
    fi
}

# ==================== 3. 虚拟环境 ====================
check_venvs() {
    echo ""
    echo "=== 虚拟环境 ==="
    
    local core_services=(trading-service telegram-service ai-service signal-service)
    local optional_services=(binance-vision-service api-service)

    check_one() {
        local svc="$1"
        local mode="$2"  # core|optional
        local svc_dir

        svc_dir="$(find_service_dir "$svc")" || {
            if [ "$mode" = "core" ]; then
                fail "$svc: 服务目录不存在"
            else
                info "$svc: 服务目录不存在（可选）"
            fi
            return 0
        }

        if [ -d "$svc_dir/.venv" ] && [ -f "$svc_dir/.venv/bin/python" ]; then
            success "$svc: .venv 存在"
            return 0
        fi

        if [ "$mode" = "core" ]; then
            fail "$svc: .venv 缺失 (运行 ./scripts/init.sh $svc)"
        else
            warn "$svc: .venv 缺失（可选，运行 ./scripts/init.sh $svc）"
        fi
    }

    local svc
    for svc in "${core_services[@]}"; do
        check_one "$svc" "core"
    done
    for svc in "${optional_services[@]}"; do
        check_one "$svc" "optional"
    done
}

# ==================== 4. 配置文件 ====================
check_config() {
    echo ""
    echo "=== 配置文件 ==="
    
    local config_file="$ROOT/assets/config/.env"
    if [ ! -f "$config_file" ] && [ -f "$ROOT/config/.env" ]; then
        # 兼容旧路径（只读回退）
        config_file="$ROOT/config/.env"
    fi
    
    if [ -f "$config_file" ]; then
        get_kv() {
            local key="$1"
            local value=""
            value=$(grep "^${key}=" "$config_file" 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d '"' | tr -d "'")
            if [ -z "$value" ]; then
                value="${!key:-}"
            fi
            echo "$value"
        }

        # 权限检查
        local rel_path="${config_file#$ROOT/}"
        local perms=$(stat -c %a "$config_file" 2>/dev/null || stat -f %Lp "$config_file" 2>/dev/null)
        if [ "$perms" = "600" ] || [ "$perms" = "400" ]; then
            success "$rel_path: 权限 $perms"
        else
            warn "$rel_path: 权限 $perms (建议 600)"
        fi
        
        # 必填字段检查
        local required_keys=(BOT_TOKEN DATABASE_URL)
        for key in "${required_keys[@]}"; do
            local value
            value="$(get_kv "$key")"
            if [ -n "$value" ] && [ "$value" != "your_token_here" ]; then
                success "$key: 已配置"
            else
                fail "$key: 未配置或为默认值"
            fi
        done

        # Query Service / 消费端配置（禁止漏配导致裸奔/全挂）
        local query_base_url
        query_base_url="$(get_kv "QUERY_SERVICE_BASE_URL")"
        if [ -n "$query_base_url" ]; then
            success "QUERY_SERVICE_BASE_URL: 已配置"
        else
            fail "QUERY_SERVICE_BASE_URL: 未配置"
        fi

        local query_auth_mode
        query_auth_mode="$(get_kv "QUERY_SERVICE_AUTH_MODE")"
        query_auth_mode="$(echo "${query_auth_mode:-required}" | tr '[:upper:]' '[:lower:]' | xargs)"
        [ -z "$query_auth_mode" ] && query_auth_mode="required"

        if [ "$query_auth_mode" = "disabled" ] || [ "$query_auth_mode" = "off" ]; then
            warn "QUERY_SERVICE_AUTH_MODE: $query_auth_mode (已关闭鉴权，仅限本地/受控环境)"
        else
            if [ "$query_auth_mode" != "required" ]; then
                warn "QUERY_SERVICE_AUTH_MODE: $query_auth_mode (未知值，按 required 处理)"
            else
                success "QUERY_SERVICE_AUTH_MODE: required"
            fi

            local query_token
            query_token="$(get_kv "QUERY_SERVICE_TOKEN")"
            if [ -n "$query_token" ] && [ "$query_token" != "dev-token-change-me" ] && [ "$query_token" != "your_token_here" ]; then
                success "QUERY_SERVICE_TOKEN: 已配置"
            else
                fail "QUERY_SERVICE_TOKEN: 未配置或为默认值"
            fi
        fi

        local cors_allow
        cors_allow="$(get_kv "API_CORS_ALLOW_ORIGINS")"
        if [ -n "$cors_allow" ]; then
            success "API_CORS_ALLOW_ORIGINS: 已配置"
        else
            info "API_CORS_ALLOW_ORIGINS: 未配置（默认不下发 CORS 头）"
        fi
        
        # 代理配置
        local http_proxy
        http_proxy="$(get_kv "HTTP_PROXY")"
        local telegram_api_base
        telegram_api_base="$(get_kv "TELEGRAM_API_BASE")"
        [ -z "$telegram_api_base" ] && telegram_api_base="${TELEGRAM_API_BASE:-}"
        if [ -n "$http_proxy" ]; then
            if [ -n "$telegram_api_base" ] && curl -s --connect-timeout 3 -x "$http_proxy" "$telegram_api_base" -o /dev/null 2>/dev/null; then
                success "HTTP_PROXY: $http_proxy (可用)"
            else
                warn "HTTP_PROXY: $http_proxy (连接失败)"
            fi
        else
            info "HTTP_PROXY: 未配置"
        fi

        # 信号服务新鲜度/冷却（可选）
        local signal_age
        signal_age="$(get_kv "SIGNAL_DATA_MAX_AGE")"
        if [ -n "$signal_age" ]; then
            success "SIGNAL_DATA_MAX_AGE: $signal_age 秒"
        else
            warn "SIGNAL_DATA_MAX_AGE: 未配置，默认 600 秒"
        fi

        local pg_cooldown
        pg_cooldown="$(get_kv "COOLDOWN_SECONDS")"
        if [ -n "$pg_cooldown" ]; then
            success "COOLDOWN_SECONDS: $pg_cooldown 秒"
        else
            info "COOLDOWN_SECONDS: 未配置，使用代码默认值"
        fi
    else
        fail "配置文件不存在（assets/config/.env 或 config/.env）"
        echo "      创建: cp assets/config/.env.example assets/config/.env && chmod 600 assets/config/.env"
    fi
}

# ==================== 5. 数据库连接 ====================
check_database() {
    echo ""
    echo "=== 数据库连接 ==="
    
    local config_file="$ROOT/assets/config/.env"
    if [ ! -f "$config_file" ] && [ -f "$ROOT/config/.env" ]; then
        # 兼容旧路径（只读回退）
        config_file="$ROOT/config/.env"
    fi
    if [ ! -f "$config_file" ]; then
        info "跳过 (assets/config/.env 不存在)"
        return 0
    fi
    
    local db_url=$(grep "^DATABASE_URL=" "$config_file" | cut -d= -f2- | tr -d '"' | tr -d "'")
    if [ -z "$db_url" ]; then
        fail "DATABASE_URL 未配置"
        return 1
    fi
    
    # 解析连接信息
    local db_host=$(echo "$db_url" | sed -n 's|.*@\([^:/]*\).*|\1|p')
    local db_port=$(echo "$db_url" | grep -oP ':\K\d+(?=/)' || echo "5432")
    # 数据库名取最后一个 '/' 之后，并去掉 query string
    local db_name=$(echo "$db_url" | sed -n 's|.*/||p' | cut -d'?' -f1)
    [ -z "$db_name" ] && db_name="market_data"
    
    [ -z "$db_host" ] && db_host="localhost"
    
    info "连接: $db_host:$db_port/$db_name"
    
    # pg_isready 检查
    if command -v pg_isready &>/dev/null; then
        if pg_isready -h "$db_host" -p "$db_port" -q 2>/dev/null; then
            success "PostgreSQL: 服务可达"
        else
            fail "PostgreSQL: $db_host:$db_port 无法连接"
            return 1
        fi
    else
        warn "pg_isready 不可用，跳过连接检查"
        return 0
    fi
    
    # 表检查
    # 解析 user/password（支持无密码）
    local userinfo=$(echo "$db_url" | sed -n 's|.*//\([^@]*\)@.*|\1|p')
    local db_user="${userinfo%%:*}"
    local db_pass=""
    if [[ "$userinfo" == *:* ]]; then
        db_pass="${userinfo#*:}"
    fi
    
    if [ -n "$db_user" ] && [ -n "$db_pass" ]; then
        if PGPASSWORD="$db_pass" psql -h "$db_host" -p "$db_port" -U "$db_user" -d "$db_name" \
            -c "SELECT 1 FROM market_data.candles_1m LIMIT 1" -q >/dev/null 2>&1; then
            success "数据表: candles_1m 存在"
        else
            warn "数据表: candles_1m 不存在或无数据"
            # 判断是否误把 DATABASE_URL 指向 HF（原子事实库）
            if PGPASSWORD="$db_pass" psql -h "$db_host" -p "$db_port" -U "$db_user" -d "$db_name" \
                -Atq -c "SELECT to_regclass('crypto.raw_futures_um_trades') IS NOT NULL" 2>/dev/null | grep -q "^t$"; then
                warn "DATABASE_URL 看起来指向 HF（存在 crypto.raw_futures_um_trades），但本脚本期望 LF（candles_1m）"
                echo "      建议：把 DATABASE_URL 指向 LF（例如 :5433），并用 BINANCE_VISION_DATABASE_URL 指向 HF（例如 :15432）"
                echo "      参考：assets/database/db/README.md"
            else
                echo "      请导入 LF 栈（K线/指标）:"
                echo "        PGPASSWORD=<密码> psql -h $db_host -p $db_port -U $db_user -d $db_name -f assets/database/db/stacks/lf.sql"
            fi
        fi
    fi

    # 可选：检查 HF（binance-vision-service 专用库）
    local hf_url=$(grep "^BINANCE_VISION_DATABASE_URL=" "$config_file" | cut -d= -f2- | tr -d '"' | tr -d "'")
    [ -z "$hf_url" ] && hf_url="${BINANCE_VISION_DATABASE_URL:-}"
    if [ -n "$hf_url" ]; then
        echo ""
        echo "=== 高频/HF 数据库（BINANCE_VISION_DATABASE_URL） ==="

        local hf_host=$(echo "$hf_url" | sed -n 's|.*@\([^:/]*\).*|\1|p')
        local hf_port=$(echo "$hf_url" | grep -oP ':\K\d+(?=/)' || echo "5432")
        local hf_name=$(echo "$hf_url" | sed -n 's|.*/||p' | cut -d'?' -f1)
        [ -z "$hf_name" ] && hf_name="market_data"
        [ -z "$hf_host" ] && hf_host="localhost"
        info "连接: $hf_host:$hf_port/$hf_name"

        if command -v pg_isready &>/dev/null; then
            if pg_isready -h "$hf_host" -p "$hf_port" -q 2>/dev/null; then
                success "PostgreSQL: 服务可达"
            else
                fail "PostgreSQL: $hf_host:$hf_port 无法连接"
                return 1
            fi
        else
            warn "pg_isready 不可用，跳过连接检查"
            return 0
        fi

        local hf_userinfo=$(echo "$hf_url" | sed -n 's|.*//\([^@]*\)@.*|\1|p')
        local hf_user="${hf_userinfo%%:*}"
        local hf_pass=""
        if [[ "$hf_userinfo" == *:* ]]; then
            hf_pass="${hf_userinfo#*:}"
        fi

        if [ -n "$hf_user" ] && [ -n "$hf_pass" ]; then
            if PGPASSWORD="$hf_pass" psql -h "$hf_host" -p "$hf_port" -U "$hf_user" -d "$hf_name" -Atq \
                -c "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='crypto' AND table_name='raw_futures_um_trades' AND column_name='venue_id')" \
                2>/dev/null | grep -q "^t$"; then
                success "HF 事实表: crypto.raw_futures_um_trades(ids) 已就绪"
            else
                warn "HF 事实表未就绪（缺少 crypto.raw_futures_um_trades.venue_id）"
                echo "      初始化：PGPASSWORD=<密码> psql -h $hf_host -p $hf_port -U $hf_user -d $hf_name -f assets/database/db/stacks/hf.sql"
                echo "      若运行库存在旧表结构漂移：按 docs/analysis/* 的 rename-swap playbook 迁移"
            fi
        fi
    fi
}

# ==================== 6. 网络连接 ====================
check_network() {
    echo ""
    echo "=== 网络连接 ==="
    
    local config_file="$ROOT/assets/config/.env"
    if [ ! -f "$config_file" ] && [ -f "$ROOT/config/.env" ]; then
        # 兼容旧路径（只读回退）
        config_file="$ROOT/config/.env"
    fi
    local proxy=""
    
    if [ -f "$config_file" ]; then
        proxy=$(grep "^HTTP_PROXY=" "$config_file" | cut -d= -f2- | tr -d '"' | tr -d "'")
    fi
    local telegram_api_base=""
    local binance_ping_url=""
    if [ -f "$config_file" ]; then
        telegram_api_base=$(grep "^TELEGRAM_API_BASE=" "$config_file" | cut -d= -f2- | tr -d '"' | tr -d "'")
        binance_ping_url=$(grep "^BINANCE_PING_URL=" "$config_file" | cut -d= -f2- | tr -d '"' | tr -d "'")
        if [ -z "$binance_ping_url" ]; then
            local binance_rest_base=$(grep "^BINANCE_REST_BASE_MAINNET=" "$config_file" | cut -d= -f2- | tr -d '"' | tr -d "'")
            local binance_fapi_base=$(grep "^BINANCE_FAPI_BASE=" "$config_file" | cut -d= -f2- | tr -d '"' | tr -d "'")
            if [ -n "$binance_rest_base" ]; then
                binance_ping_url="${binance_rest_base%/}/api/v3/ping"
            elif [ -n "$binance_fapi_base" ]; then
                binance_ping_url="${binance_fapi_base%/}/fapi/v1/ping"
            fi
        fi
    fi
    [ -z "$telegram_api_base" ] && telegram_api_base="${TELEGRAM_API_BASE:-}"
    if [ -z "$binance_ping_url" ]; then
        if [ -n "${BINANCE_PING_URL:-}" ]; then
            binance_ping_url="${BINANCE_PING_URL}"
        elif [ -n "${BINANCE_REST_BASE_MAINNET:-}" ]; then
            binance_ping_url="${BINANCE_REST_BASE_MAINNET%/}/api/v3/ping"
        elif [ -n "${BINANCE_FAPI_BASE:-}" ]; then
            binance_ping_url="${BINANCE_FAPI_BASE%/}/fapi/v1/ping"
        fi
    fi
    
    local curl_opts="-s --connect-timeout 5"
    [ -n "$proxy" ] && curl_opts="$curl_opts -x $proxy"
    
    # Telegram API
    if [ -n "$telegram_api_base" ] && eval "curl $curl_opts $telegram_api_base -o /dev/null" 2>/dev/null; then
        success "Telegram API: 可达"
    else
        fail "Telegram API: 无法连接 (检查代理配置)"
    fi
    
    # Binance API
    if [ -n "$binance_ping_url" ] && eval "curl $curl_opts $binance_ping_url -o /dev/null" 2>/dev/null; then
        success "Binance API: 可达"
    else
        warn "Binance API: 无法连接"
    fi
}

# ==================== 7. 数据目录 ====================
check_data_dirs() {
    echo ""
    echo "=== 数据目录 ==="
    
    local dirs=(
        "$ROOT/assets/database/services/telegram-service"
        "$ROOT/services/consumption/telegram-service/data/cache"
        "$ROOT/services/compute/trading-service/logs"
        "$ROOT/services/compute/signal-service/logs"
        "$ROOT/services/compute/ai-service/logs"
        "$ROOT/services/consumption/telegram-service/logs"
    )

    # 可选：采集侧（不进入核心启动链路，但允许单独运行）
    local bv_dir
    bv_dir="$(find_service_dir "binance-vision-service")" && dirs+=("$bv_dir/logs")
    
    for dir in "${dirs[@]}"; do
        if [ -d "$dir" ]; then
            success "$(basename $(dirname $dir))/$(basename $dir): 存在"
        else
            warn "$dir: 不存在"
        fi
    done

    # 可选：低频/分时采集（不进入核心启动链路，但允许单独运行）
    local ds_dir
    ds_dir="$(find_service_dir "data-service")" && info "data-service 可选服务：$ds_dir（不参与默认检查）"
    
    info "指标库：PostgreSQL（tg_cards.*）"
}

# ==================== 8. 磁盘空间 ====================
check_disk_space() {
    echo ""
    echo "=== 磁盘空间 ==="
    
    local available=$(df -h "$ROOT" | tail -1 | awk '{print $4}')
    local used_pct=$(df -h "$ROOT" | tail -1 | awk '{print $5}' | tr -d '%')
    
    if [ "$used_pct" -lt 90 ]; then
        success "可用空间: $available (使用率: $used_pct%)"
    else
        warn "磁盘空间不足: $available (使用率: $used_pct%)"
    fi
}

# ==================== 主程序 ====================
main() {
    echo "=========================================="
    echo "  TradeCat 环境检查"
    echo "=========================================="
    echo "  项目路径: $ROOT"
    echo "  检查时间: $(date '+%Y-%m-%d %H:%M:%S')"
    
    check_python
    check_system_deps
    check_venvs
    check_config
    check_database
    check_network
    check_data_dirs
    check_disk_space
    
    echo ""
    echo "=========================================="
    if [ $ERRORS -gt 0 ]; then
        echo -e "${RED}检查完成: $ERRORS 个错误, $WARNINGS 个警告${NC}"
        echo "请修复上述错误后再启动服务"
        exit 1
    elif [ $WARNINGS -gt 0 ]; then
        echo -e "${YELLOW}检查完成: $WARNINGS 个警告${NC}"
        echo "建议修复警告项以获得最佳体验"
        exit 0
    else
        echo -e "${GREEN}检查完成: 所有项目通过${NC}"
        echo "可以启动服务: ./scripts/start.sh start"
        exit 0
    fi
}

main "$@"
