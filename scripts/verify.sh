#!/bin/bash
# 验证脚本 - 统一执行格式化、静态检查、测试

set -e

echo "=========================================="
echo "tradecat Pro 验证脚本"
echo "=========================================="

cd "$(dirname "$0")/.."
ROOT_DIR=$(pwd)

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

success() { echo -e "${GREEN}✓ $1${NC}"; }
fail() { echo -e "${RED}✗ $1${NC}"; exit 1; }
warn() { echo -e "${YELLOW}⚠ $1${NC}"; }

# 0) 目录结构守护（防止旧目录/软链接回潮）
echo ""
echo "0. 目录结构守护..."

# 顶层软链接（不允许）
TOP_SYMLINKS="$(find . -maxdepth 1 -type l -print 2>/dev/null | tr '\n' ' ' | xargs echo)"
if [ -n "${TOP_SYMLINKS:-}" ]; then
    fail "发现顶层 symlink（禁止）：${TOP_SYMLINKS}"
else
    success "顶层无 symlink"
fi

# 遗留顶层目录/文件（不允许）
LEGACY_TOP=(config docs tasks artifacts libs)
LEGACY_FOUND=0
for d in "${LEGACY_TOP[@]}"; do
    if [ -e "$d" ]; then
        warn "发现遗留顶层路径: $d（应迁移到 assets/ 并删除顶层）"
        LEGACY_FOUND=1
    fi
done
if [ "$LEGACY_FOUND" -ne 0 ]; then
    fail "目录结构不符合约定：请移除顶层 config/docs/tasks/artifacts/libs"
else
    success "目录结构符合 assets/ 约定"
fi

# 0.1) SQLite 依赖守护（核心链路必须 PG-only）
echo ""
echo "0.1 SQLite 依赖守护..."
if command -v rg &> /dev/null; then
    SQLITE_SCAN_DIRS=(
        services/compute/trading-service/src
        services/compute/signal-service/src
        services/compute/ai-service/src
        services/consumption/telegram-service/src
        services/consumption/sheets-service/src
        services/consumption/api-service/src
    )
    SQLITE_HITS="$(
        rg -n --hidden --no-ignore-vcs -F 'import sqlite3' "${SQLITE_SCAN_DIRS[@]}" --glob '!**/.venv/**' --glob '!**/node_modules/**' --glob '!**/libs/external/**' || true
        rg -n --hidden --no-ignore-vcs -F 'sqlite3.connect(' "${SQLITE_SCAN_DIRS[@]}" --glob '!**/.venv/**' --glob '!**/node_modules/**' --glob '!**/libs/external/**' || true
        rg -n --hidden --no-ignore-vcs -F 'aiosqlite' "${SQLITE_SCAN_DIRS[@]}" --glob '!**/.venv/**' --glob '!**/node_modules/**' --glob '!**/libs/external/**' || true
        rg -n --hidden --no-ignore-vcs -F 'sqlite://' "${SQLITE_SCAN_DIRS[@]}" --glob '!**/.venv/**' --glob '!**/node_modules/**' --glob '!**/libs/external/**' || true
    )"
    if [ -n "${SQLITE_HITS:-}" ]; then
        echo "$SQLITE_HITS"
        fail "发现 SQLite 引用（核心链路必须 PG-only）"
    else
        success "核心链路无 SQLite 引用"
    fi
else
    warn "rg 未安装，跳过 SQLite 引用检查"
fi

# 0.2) consumption 直连 PG/SQL 守护（除 Query Service 外必须 HTTP-only）
echo ""
echo "0.2 consumption 直连 PG/SQL 守护..."
if command -v rg &> /dev/null; then
    # 注意：
    # - 仅扫描核心消费链路（TG/Sheets/Vis），不扫 nofx-dev 等外部镜像项目
    # - 禁止出现 psycopg/psycopg_pool，以及显式 SQL 片段（tg_cards/market_data）
    CONSUMPTION_PG_SCAN_DIRS=()
    for d in services/consumption/telegram-service/src services/consumption/sheets-service/src services/consumption/vis-service/src; do
        if [ -d "$d" ]; then
            CONSUMPTION_PG_SCAN_DIRS+=("$d")
        fi
    done
    if [ "${#CONSUMPTION_PG_SCAN_DIRS[@]}" -eq 0 ]; then
        warn "未找到可扫描的 consumption/src 目录，跳过 PG/SQL 守护"
    else
    PG_HITS="$(
        rg -n --hidden --no-ignore-vcs -S "\\b(psycopg|psycopg_pool)\\b" "${CONSUMPTION_PG_SCAN_DIRS[@]}" --glob '!**/.venv/**' --glob '!**/node_modules/**' || true
        rg -n --hidden --no-ignore-vcs -S -i 'from\\s+tg_cards\\.' "${CONSUMPTION_PG_SCAN_DIRS[@]}" --glob '*.py' --glob '!**/.venv/**' --glob '!**/node_modules/**' || true
        rg -n --hidden --no-ignore-vcs -S -i 'join\\s+tg_cards\\.' "${CONSUMPTION_PG_SCAN_DIRS[@]}" --glob '*.py' --glob '!**/.venv/**' --glob '!**/node_modules/**' || true
        rg -n --hidden --no-ignore-vcs -S -i 'into\\s+tg_cards\\.' "${CONSUMPTION_PG_SCAN_DIRS[@]}" --glob '*.py' --glob '!**/.venv/**' --glob '!**/node_modules/**' || true
        rg -n --hidden --no-ignore-vcs -S -i 'update\\s+tg_cards\\.' "${CONSUMPTION_PG_SCAN_DIRS[@]}" --glob '*.py' --glob '!**/.venv/**' --glob '!**/node_modules/**' || true
        rg -n --hidden --no-ignore-vcs -S -i 'from\\s+market_data\\.' "${CONSUMPTION_PG_SCAN_DIRS[@]}" --glob '*.py' --glob '!**/.venv/**' --glob '!**/node_modules/**' || true
        rg -n --hidden --no-ignore-vcs -S -i 'join\\s+market_data\\.' "${CONSUMPTION_PG_SCAN_DIRS[@]}" --glob '*.py' --glob '!**/.venv/**' --glob '!**/node_modules/**' || true
        rg -n --hidden --no-ignore-vcs -S -i 'into\\s+market_data\\.' "${CONSUMPTION_PG_SCAN_DIRS[@]}" --glob '*.py' --glob '!**/.venv/**' --glob '!**/node_modules/**' || true
        rg -n --hidden --no-ignore-vcs -S -i 'update\\s+market_data\\.' "${CONSUMPTION_PG_SCAN_DIRS[@]}" --glob '*.py' --glob '!**/.venv/**' --glob '!**/node_modules/**' || true
    )"
    if [ -n "${PG_HITS:-}" ]; then
        echo "$PG_HITS"
        fail "发现 consumption 直连 PG/SQL（必须仅走 Query Service）"
    else
        success "consumption 无 PG 直连与 SQL 片段"
    fi
    fi
else
    warn "rg 未安装，跳过 consumption PG/SQL 守护"
fi

# 0.3) consumption legacy API 路径守护（必须只走 /api/v1/*）
echo ""
echo "0.3 consumption API 路径守护..."
if command -v rg &> /dev/null; then
    CONSUMPTION_API_SCAN_DIRS=()
    for d in services/consumption/telegram-service/src services/consumption/sheets-service/src services/consumption/vis-service/src; do
        if [ -d "$d" ]; then
            CONSUMPTION_API_SCAN_DIRS+=("$d")
        fi
    done
    if [ "${#CONSUMPTION_API_SCAN_DIRS[@]}" -eq 0 ]; then
        warn "未找到可扫描的 consumption/src 目录，跳过 API 路径守护"
    else
        LEGACY_API_HITS="$(
            rg -n --hidden --no-ignore-vcs -S "/api/futures/" "${CONSUMPTION_API_SCAN_DIRS[@]}" --glob '!**/.venv/**' --glob '!**/node_modules/**' || true
        )"
        if [ -n "${LEGACY_API_HITS:-}" ]; then
            echo "$LEGACY_API_HITS"
            fail "发现 consumption 引用 legacy /api/futures/（必须只走 /api/v1/*）"
        else
            success "consumption 未引用 legacy /api/futures/"
        fi
    fi
else
    warn "rg 未安装，跳过 consumption API 路径守护"
fi

# 1. 检查 Python 环境
echo ""
echo "1. 检查 Python 环境..."
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
    success "虚拟环境已激活"
else
    warn "未找到 .venv，使用系统 Python"
fi

# 2. 代码格式检查 (ruff)
echo ""
echo "2. 代码格式检查 (ruff)..."
if command -v ruff &> /dev/null; then
    if ruff check services/ --quiet; then
        success "ruff 检查通过"
    else
        fail "ruff 检查失败"
    fi
else
    warn "ruff 未安装，跳过"
fi

# 3. 语法检查
echo ""
echo "3. Python 语法检查..."
# 3.1 关键入口文件
if python3 -m py_compile services/consumption/telegram-service/src/bot/app.py 2>/dev/null; then
    success "telegram-service app.py 语法正确"
else
    fail "telegram-service app.py 语法错误"
fi
# 3.2 ai-service 全量（compileall，确保真正命中所有文件）
if python3 -m compileall -q services/compute/ai-service/src 2>/dev/null; then
    success "ai-service 源码语法正确"
else
    fail "ai-service 语法检查失败"
fi
# 3.3 其他服务（粗粒度）
for service_dir in services/ingestion/binance-vision-service services/compute/trading-service services/compute/signal-service; do
    if [ -d "$service_dir/src" ]; then
        if python3 -m compileall -q "$service_dir/src" 2>/dev/null; then
            success "$service_dir 源码语法正确"
        else
            warn "$service_dir 语法检查失败或部分文件跳过"
        fi
    fi
done

# 4. i18n 翻译检查
echo ""
echo "4. i18n 翻译检查..."
if command -v msgfmt &> /dev/null; then
    LOCALE_DIR=$(python3 - <<'PY'
from pathlib import Path
root = Path(__file__).resolve().parents[1]
default = root / "services" / "consumption" / "telegram-service" / "locales"
def has_bot(p: Path) -> bool:
    for lang in ("zh_CN", "en"):
        lc = p / lang / "LC_MESSAGES"
        if (lc / "bot.po").exists() or (lc / "bot.mo").exists():
            return True
    return False
if has_bot(default):
    print(default)
    raise SystemExit(0)
candidates = set()
for po in root.rglob("bot.po"):
    parts = po.parts
    if "node_modules" in parts:
        continue
    if ("assets" in parts and "repo" in parts) or ("assets" in parts and "services-preview" in parts):
        continue
    if po.parent.name != "LC_MESSAGES":
        continue
    candidates.add(po.parents[2])
for cand in sorted(candidates):
    if has_bot(cand):
        print(cand)
        raise SystemExit(0)
print(default)
PY
)
    if msgfmt --check -o /dev/null "$LOCALE_DIR/zh_CN/LC_MESSAGES/bot.po" >/dev/null && \
       msgfmt --check -o /dev/null "$LOCALE_DIR/en/LC_MESSAGES/bot.po" >/dev/null; then
        success "i18n 词条检查通过"
    else
        fail "i18n 词条检查失败，请修复缺失或语法错误"
    fi
else
    warn "未安装 gettext/msgfmt，跳过 i18n 检查"
fi

# 5. i18n 词条对齐检查
echo ""
echo "5. i18n 词条对齐检查..."
if python3 scripts/check_i18n_keys.py; then
    success "i18n 代码键与词条对齐"
else
    fail "i18n 代码键缺失，请补充 bot.po"
fi

# 6. 文档链接检查
echo ""
echo "6. 文档链接检查..."
DOCS_ROOT="assets/docs"
if [ -f "$DOCS_ROOT/index.md" ]; then
    BROKEN_LINKS=0
    while IFS= read -r line; do
        if [[ $line =~ \[.*\]\((.*)\) ]]; then
            link="${BASH_REMATCH[1]}"
            if [[ $link != http* ]] && [[ $link != \#* ]]; then
                full_path="$DOCS_ROOT/$link"
                if [ ! -f "$full_path" ] && [ ! -d "$full_path" ]; then
                    warn "死链: $link"
                    BROKEN_LINKS=$((BROKEN_LINKS + 1))
                fi
            fi
        fi
    done < "$DOCS_ROOT/index.md"
    
    if [ $BROKEN_LINKS -eq 0 ]; then
        success "$DOCS_ROOT/index.md 链接检查通过"
    else
        warn "发现 $BROKEN_LINKS 个死链"
    fi
else
    warn "$DOCS_ROOT/index.md 不存在，跳过文档链接检查（团队单入口文档约定已禁用）"
fi

# 7. ADR 编号检查
echo ""
echo "7. ADR 编号检查..."
if [ -d "$DOCS_ROOT/decisions/adr" ]; then
    ADR_COUNT=$(ls "$DOCS_ROOT/decisions/adr"/*.md 2>/dev/null | wc -l)
    success "ADR 文件数: $ADR_COUNT"
else
    warn "$DOCS_ROOT/decisions/adr 目录不存在"
fi

# 8. Prompt 模板检查
echo ""
echo "8. Prompt 模板检查..."
if [ -d "$DOCS_ROOT/prompts" ]; then
    PROMPT_COUNT=$(ls "$DOCS_ROOT/prompts"/*.md 2>/dev/null | wc -l)
    success "Prompt 文件数: $PROMPT_COUNT"
else
    warn "$DOCS_ROOT/prompts 目录不存在"
fi

# 9. 单元测试 (如有)
echo ""
echo "9. 单元测试..."
if command -v pytest &> /dev/null; then
    if [ -d "tests" ] && [ "$(ls -A tests 2>/dev/null)" ]; then
        if pytest tests/ -q --tb=no 2>/dev/null; then
            success "单元测试通过"
        else
            warn "单元测试失败或无测试"
        fi
    elif [ -d "assets/tests" ] && [ "$(ls -A assets/tests 2>/dev/null)" ]; then
        if pytest assets/tests/ -q --tb=no 2>/dev/null; then
            success "单元测试通过"
        else
            warn "单元测试失败或无测试"
        fi
    else
        warn "无测试文件，跳过"
    fi
else
    warn "pytest 未安装，跳过"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}验证完成${NC}"
echo "=========================================="
