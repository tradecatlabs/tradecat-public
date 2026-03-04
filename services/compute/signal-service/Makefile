# Signal Service Makefile
# 用法: make <target>

SHELL := /bin/bash
PYTHON := .venv/bin/python
PIP := .venv/bin/pip
RUFF := .venv/bin/ruff
PYTEST := .venv/bin/pytest

.PHONY: help venv install install-dev clean lint format test check run start stop status

# 默认目标
help:
	@echo "Signal Service 常用命令:"
	@echo ""
	@echo "  环境管理:"
	@echo "    make venv        - 创建虚拟环境"
	@echo "    make install     - 安装依赖"
	@echo "    make install-dev - 安装开发依赖"
	@echo "    make clean       - 清理缓存和构建产物"
	@echo "    make reset       - 重建虚拟环境（依赖坏了用这个）"
	@echo ""
	@echo "  代码质量:"
	@echo "    make lint        - 代码检查 (ruff)"
	@echo "    make format      - 代码格式化 (ruff)"
	@echo "    make test        - 运行测试 (pytest)"
	@echo "    make check       - 完整检查 (lint + test)"
	@echo ""
	@echo "  运行服务:"
	@echo "    make run         - 前台运行（调试用）"
	@echo "    make start       - 后台启动"
	@echo "    make stop        - 停止服务"
	@echo "    make status      - 查看状态"

# ==================== 环境管理 ====================

# 创建虚拟环境
venv:
	@if [ ! -d ".venv" ]; then \
		echo "创建虚拟环境..."; \
		python3 -m venv .venv; \
		$(PIP) install -q --upgrade pip; \
	else \
		echo "虚拟环境已存在"; \
	fi

# 安装依赖
install: venv
	@echo "安装依赖..."
	$(PIP) install -q -r requirements.txt
	@echo "✅ 依赖安装完成"

# 安装开发依赖
install-dev: install
	@echo "安装开发依赖..."
	$(PIP) install -q -r requirements-dev.txt
	@echo "✅ 开发依赖安装完成"

# 清理缓存
clean:
	@echo "清理缓存..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf build/ dist/ .coverage htmlcov/
	@echo "✅ 清理完成"

# 重建虚拟环境（依赖坏了用这个）
reset: clean
	@echo "重建虚拟环境..."
	rm -rf .venv
	python3 -m venv .venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r requirements.txt
	@echo "✅ 虚拟环境重建完成"

# 导出当前依赖（生成 lock 文件）
lock:
	$(PIP) freeze > requirements.lock.txt
	@echo "✅ 依赖已锁定到 requirements.lock.txt"

# ==================== 代码质量 ====================

# 代码检查
lint:
	@if [ -f "$(RUFF)" ]; then \
		$(RUFF) check src/ tests/ --ignore E501,E402 --select E,F 2>/dev/null || $(RUFF) check src/ --ignore E501,E402 --select E,F; \
	else \
		echo "⚠️  ruff 未安装，运行 make install-dev"; \
	fi

# 代码格式化
format:
	@if [ -f "$(RUFF)" ]; then \
		$(RUFF) format src/ tests/ 2>/dev/null || $(RUFF) format src/; \
		$(RUFF) check --fix src/ tests/ --ignore E501,E402 --select E,F 2>/dev/null || $(RUFF) check --fix src/ --ignore E501,E402 --select E,F; \
	else \
		echo "⚠️  ruff 未安装，运行 make install-dev"; \
	fi

# 运行测试
test:
	@if [ -f "$(PYTEST)" ]; then \
		$(PYTEST) tests/ -v; \
	else \
		echo "⚠️  pytest 未安装，运行 make install-dev"; \
	fi

# 运行测试 + 覆盖率
test-cov:
	@if [ -f "$(PYTEST)" ]; then \
		$(PYTEST) tests/ -v --cov=src --cov-report=term-missing; \
	else \
		echo "⚠️  pytest 未安装，运行 make install-dev"; \
	fi

# 类型检查
typecheck:
	@if [ -f ".venv/bin/mypy" ]; then \
		.venv/bin/mypy src/; \
	else \
		echo "⚠️  mypy 未安装，运行 make install-dev"; \
	fi

# 完整检查
check: lint test
	@echo "✅ 检查完成"

# 语法验证（快速）
syntax:
	$(PYTHON) -m py_compile src/__init__.py src/config.py src/__main__.py
	@echo "✅ 语法检查通过"

# ==================== 运行服务 ====================

# 前台运行（调试用）
run: install
	$(PYTHON) -m src --all

# 单次检查
run-once: install
	$(PYTHON) -m src --all --once

# 测试配置
run-test: install
	$(PYTHON) -m src --test

# 后台启动
start:
	./scripts/start.sh start

# 停止服务
stop:
	./scripts/start.sh stop

# 查看状态
status:
	./scripts/start.sh status

# 重启
restart:
	./scripts/start.sh restart
