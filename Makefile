# ==============================================================================
# TradeCat Makefile
# ==============================================================================

.PHONY: help init start stop status daemon daemon-stop verify clean export-db

# 默认目标
help:
	@echo "TradeCat - 加密货币量化交易数据平台"
	@echo ""
	@echo "Usage:"
	@echo "    make init        - 初始化所有服务（虚拟环境 + 依赖）"
	@echo "    make start       - 启动所有服务"
	@echo "    make stop        - 停止所有服务"
	@echo "    make status      - 查看服务状态"
	@echo "    make daemon      - 启动守护进程（自动重启）"
	@echo "    make daemon-stop - 停止守护进程"
	@echo "    make verify      - 运行代码验证"
	@echo "    make clean       - 清理缓存文件"
	@echo "    make export-db   - 导出 TimescaleDB 数据"
	@echo ""

# 初始化
init:
	@./scripts/init.sh

# 一键安装
install:
	@./scripts/install.sh

# 启动服务
start:
	@./scripts/start.sh start

# 停止服务
stop:
	@./scripts/start.sh stop

# 查看状态
status:
	@./scripts/start.sh status

# 守护进程模式
daemon:
	@./scripts/start.sh daemon

# 停止守护进程
daemon-stop:
	@./scripts/start.sh daemon-stop

# 代码验证
verify:
	@./scripts/verify.sh

# 清理缓存
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf cache/pytest cache/ruff artifacts/coverage artifacts/dist artifacts/i18n 2>/dev/null || true
	@echo "✓ 缓存已清理"

# 数据库导出
export-db:
	@./scripts/export_timescaledb.sh
