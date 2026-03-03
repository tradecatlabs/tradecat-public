#!/usr/bin/env bash
# tradecat Pro 初始化脚本
# 用法: ./scripts/init.sh [service-name]
# 示例: ./scripts/init.sh              # 初始化全部核心服务
#       ./scripts/init.sh binance-vision-service  # 初始化单个服务
#       ./scripts/init.sh --all         # 初始化全部（含可选服务）

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# 核心服务（services/ 目录，按分层组织）
# 注意：采集层服务默认不在核心启动链路（避免采集任务“长跑”污染开发机）
# - 低频/分时（1m K线、5m 指标）: ./scripts/init.sh data-service
# - 高频/HFT 原子事实（trades/book*）: ./scripts/init.sh binance-vision-service
CORE_SERVICES=(trading-service telegram-service ai-service signal-service)

# 可选服务（默认不在核心启动链）
OPTIONAL_SERVICES=(api-service sheets-service)

# ==================== 工具函数 ====================
success() { echo -e "\033[0;32m✓ $1\033[0m"; }
fail() { echo -e "\033[0;31m✗ $1\033[0m"; exit 1; }
info() { echo -e "\033[0;34m→ $1\033[0m"; }
warn() { echo -e "\033[0;33m⚠ $1\033[0m"; }

# ==================== 查找服务目录 ====================
find_service_dir() {
    local svc="$1"
    
    local candidates=(
        "$ROOT/services/$svc"                  # 兼容旧布局
        "$ROOT/services/ingestion/$svc"        # 新布局：采集层
        "$ROOT/services/compute/$svc"          # 新布局：计算层
        "$ROOT/services/consumption/$svc"      # 新布局：消费层
        "$ROOT/services-preview/$svc"          # 历史遗留（如仍存在）
    )
    for cand in "${candidates[@]}"; do
        if [ -d "$cand" ]; then
            echo "$cand"
            return 0
        fi
    done
    
    return 1
}

# ==================== 初始化单个服务 ====================
init_service() {
    local svc="$1"
    local svc_dir
    
    svc_dir=$(find_service_dir "$svc") || {
        warn "服务目录不存在: $svc (跳过)"
        return 0
    }
    
    echo ""
    echo "=== 初始化 $svc ==="
    cd "$svc_dir"
    
    # 1. 创建虚拟环境
    if [ ! -d ".venv" ]; then
        info "创建虚拟环境..."
        python3 -m venv .venv
    else
        info "虚拟环境已存在"
    fi
    
    # 2. 安装依赖
    info "安装依赖..."
    source .venv/bin/activate
    pip install -q --upgrade pip
    
    if [ -f "requirements.lock.txt" ]; then
        pip install -q -r requirements.lock.txt 2>/dev/null || {
            warn "部分依赖安装失败，请检查 requirements.lock.txt"
        }
    elif [ -f "requirements.txt" ]; then
        pip install -q -r requirements.txt 2>/dev/null || {
            warn "部分依赖安装失败，请检查 requirements.txt"
        }
    elif [ -f "pyproject.toml" ]; then
        pip install -q -e . 2>/dev/null || {
            warn "pyproject.toml 安装失败"
        }
    fi
    
    # 3. 创建运行时目录
    mkdir -p pids logs data/cache 2>/dev/null || true
    
    # 4. 设置脚本权限
    [ -f "scripts/start.sh" ] && chmod +x scripts/start.sh
    
    deactivate 2>/dev/null || true
    success "$svc 初始化完成"
}

# ==================== 系统依赖检查 ====================
check_system() {
    echo "=== 系统依赖检查 ==="
    
    # Python 版本检查
    if command -v python3 &>/dev/null; then
        local py_ver=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        if python3 -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)"; then
            success "Python3: $py_ver"
        else
            fail "Python 版本需要 3.10+，当前: $py_ver"
        fi
    else
        fail "Python3 未安装"
    fi
    
    # pip
    if python3 -m pip --version &>/dev/null; then
        success "pip: $(python3 -m pip --version | cut -d' ' -f2)"
    else
        fail "pip 未安装，请运行: python3 -m ensurepip"
    fi
    
    # TA-Lib (可选)
    if python3 -c "import talib" 2>/dev/null; then
        success "TA-Lib: 已安装"
    else
        info "TA-Lib: 未安装（K线形态检测需要）"
    fi
    
    # PostgreSQL client (可选)
    if command -v psql &>/dev/null; then
        success "psql: $(psql --version 2>&1 | head -1)"
    else
        info "psql: 未安装（数据库操作需要）"
    fi
}

# ==================== 创建全局目录 ====================
init_global() {
    echo ""
    echo "=== 创建全局目录 ==="
    mkdir -p "$ROOT/run" "$ROOT/logs" "$ROOT/backups"
    mkdir -p "$ROOT/assets/database/services/telegram-service"
    chmod +x "$ROOT/scripts/"*.sh 2>/dev/null || true
    success "全局目录已创建"
}

# ==================== 配置文件检查 ====================
check_config() {
    echo ""
    echo "=== 配置文件检查 ==="
    
    local config_file="$ROOT/assets/config/.env"
    local config_example="$ROOT/assets/config/.env.example"
    
    if [ -f "$config_file" ]; then
        local perms=$(stat -c %a "$config_file" 2>/dev/null || stat -f %Lp "$config_file" 2>/dev/null)
        if [ "$perms" = "600" ] || [ "$perms" = "400" ]; then
            success "assets/config/.env 存在 (权限: $perms)"
        else
            warn "assets/config/.env 权限不安全: $perms (建议: chmod 600 assets/config/.env)"
        fi
        
        # 检查关键配置
        if grep -q "^BOT_TOKEN=" "$config_file" && ! grep -q "^BOT_TOKEN=$" "$config_file"; then
            success "BOT_TOKEN: 已配置"
        else
            warn "BOT_TOKEN: 未配置 (Telegram Bot 无法启动)"
        fi
        
        # 显示 DATABASE_URL 端口
        local db_url=$(grep "^DATABASE_URL=" "$config_file" | cut -d= -f2-)
        if [ -n "$db_url" ]; then
            local db_port=$(echo "$db_url" | grep -oP ':\K\d+(?=/)')
            success "DATABASE_URL: 端口 $db_port"
        else
            warn "DATABASE_URL: 未配置"
        fi
    else
        if [ -f "$config_example" ]; then
            info "assets/config/.env 不存在，请执行:"
            echo "    cp assets/config/.env.example assets/config/.env && chmod 600 assets/config/.env"
        else
            fail "配置模板不存在: assets/config/.env.example"
        fi
    fi
}

# ==================== 数据库连接检查 ====================
check_database() {
    echo ""
    echo "=== 数据库连接检查 ==="
    
    local config_file="$ROOT/assets/config/.env"
    if [ ! -f "$config_file" ]; then
        info "跳过数据库检查 (assets/config/.env 不存在)"
        return 0
    fi
    
    # 解析 DATABASE_URL
    local db_url=$(grep "^DATABASE_URL=" "$config_file" | cut -d= -f2- | tr -d '"' | tr -d "'")
    if [ -z "$db_url" ]; then
        info "跳过数据库检查 (DATABASE_URL 未配置)"
        return 0
    fi
    
    # 提取 host 和 port
    local db_host=$(echo "$db_url" | sed -n 's|.*@\([^:/]*\).*|\1|p')
    local db_port=$(echo "$db_url" | grep -oP ':\K\d+(?=/)' || echo "5432")
    
    if [ -z "$db_host" ]; then
        db_host="localhost"
    fi
    
    if command -v pg_isready &>/dev/null; then
        if pg_isready -h "$db_host" -p "$db_port" -q 2>/dev/null; then
            success "PostgreSQL: $db_host:$db_port 可连接"
        else
            warn "PostgreSQL: $db_host:$db_port 无法连接"
            echo "    请确保 TimescaleDB 已启动"
        fi
    else
        info "跳过数据库连接检查 (pg_isready 未安装)"
    fi
}

# ==================== 打印完成信息 ====================
print_summary() {
    echo ""
    echo "=========================================="
    echo -e "\033[0;32m✓ 初始化完成\033[0m"
    echo "=========================================="
    echo ""
    echo "下一步："
    
    local config_file="$ROOT/assets/config/.env"
    if [ ! -f "$config_file" ]; then
        echo "  1. 创建配置文件:"
        echo "     cp assets/config/.env.example assets/config/.env && chmod 600 assets/config/.env"
        echo ""
        echo "  2. 编辑配置 (必填 BOT_TOKEN, DATABASE_URL):"
        echo "     vim assets/config/.env"
        echo ""
        echo "  3. 启动服务:"
    else
        echo "  1. 启动服务:"
    fi
    echo "     ./scripts/start.sh start"
    echo ""
    echo "  查看状态: ./scripts/start.sh status"
    echo "  停止服务: ./scripts/start.sh stop"
}

# ==================== 入口 ====================
case "${1:-}" in
    --all)
        # 初始化全部（含可选服务）
        check_system
        init_global
        
        for svc in "${CORE_SERVICES[@]}"; do
            init_service "$svc"
        done
        
        echo ""
        info "初始化可选服务..."
        for svc in "${OPTIONAL_SERVICES[@]}"; do
            init_service "$svc"
        done
        
        check_config
        check_database
        print_summary
        ;;
    "")
        # 默认：仅初始化核心服务
        check_system
        init_global
        
        for svc in "${CORE_SERVICES[@]}"; do
            init_service "$svc"
        done
        
        check_config
        check_database
        print_summary
        ;;
    *)
        # 初始化单个服务
        init_service "$1"
        ;;
esac
