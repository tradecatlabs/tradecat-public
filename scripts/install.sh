#!/bin/bash
# tradecat 一键安装脚本
set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m'

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo -e "${GREEN}🐱 tradecat 一键安装${NC}"
echo "安装目录: $ROOT"
cd "$ROOT"

# ========== 1. 检查系统依赖 ==========
echo -e "\n${YELLOW}[1/6] 检查系统依赖...${NC}"

check_cmd() {
    command -v "$1" &>/dev/null || { echo -e "${RED}❌ 未安装 $1${NC}"; return 1; }
    echo -e "  ✅ $1"
}

check_cmd python3 || { echo "请先安装 Python 3.10+"; exit 1; }
check_cmd pip3 || { echo "请先安装 pip"; exit 1; }

# 检查 Python 版本
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if ! python3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"; then
    echo -e "${RED}❌ Python 版本需要 3.10+，当前: $PY_VER${NC}"
    exit 1
fi
echo -e "  ✅ Python $PY_VER"

# ========== 2. 初始化服务环境 ==========
echo -e "\n${YELLOW}[2/6] 初始化服务环境...${NC}"
./scripts/init.sh --all

# ========== 3. 配置文件 ==========
echo -e "\n${YELLOW}[3/6] 配置文件...${NC}"
if [ ! -f "$ROOT/config/.env" ]; then
    cp "$ROOT/config/.env.example" "$ROOT/config/.env"
    chmod 600 "$ROOT/config/.env" 2>/dev/null || true
    echo -e "  ✅ 已创建 config/.env（请编辑 BOT_TOKEN / DATABASE_URL 等）"
else
    echo -e "  ⏭️ config/.env 已存在"
fi

# ========== 4. 数据目录 ==========
echo -e "\n${YELLOW}[4/6] 检查数据目录...${NC}"
mkdir -p "$ROOT/assets/database/db/state" 2>/dev/null || true
echo -e "  ✅ 目录检查完成"

# ========== 5. 检查数据库 ==========
echo -e "\n${YELLOW}[5/6] 检查数据库...${NC}"

if command -v psql &>/dev/null; then
    echo -e "  ✅ PostgreSQL 客户端已安装"
    echo -e "  ${YELLOW}⚠️ 请确保 TimescaleDB 已运行并导入 schema:${NC}"
    echo -e "     # LF（低频/分时/K线与指标库）"
    echo -e "     psql -h localhost -p 5433 -U opentd -d market_data -f assets/database/db/stacks/lf.sql"
    echo -e ""
    echo -e "     # HF（高频/原子事实库，可选）"
    echo -e "     psql -h localhost -p 15432 -U opentd -d market_data -f assets/database/db/stacks/hf.sql"
else
    echo -e "  ${YELLOW}⚠️ 未检测到 psql，请手动安装 TimescaleDB${NC}"
fi

# ========== 6. 完成 ==========
echo -e "\n${GREEN}✅ 安装完成！${NC}"
echo ""
echo "下一步："
echo "  1. 编辑配置文件:"
echo "     - config/.env (设置 BOT_TOKEN / DATABASE_URL / 代理等)"
echo ""
echo "  2. 导入数据库 schema (如果是新数据库):"
echo "     # LF（低频/分时/K线与指标库）"
echo "     psql -h localhost -p 5433 -U opentd -d market_data -f assets/database/db/stacks/lf.sql"
echo ""
echo "     # HF（高频/原子事实库，可选）"
echo "     psql -h localhost -p 15432 -U opentd -d market_data -f assets/database/db/stacks/hf.sql"
echo ""
echo "  3. 启动服务:"
echo "     ./scripts/start.sh start"
echo ""
echo "  4. 或单独启动:"
echo "     cd services/ingestion/binance-vision-service && python3 -m src --version"
echo "     cd services/compute/trading-service && ./scripts/start.sh start"
echo "     cd services/consumption/telegram-service && ./scripts/start.sh start"
