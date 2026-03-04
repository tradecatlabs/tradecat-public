# sheets-service Makefile

SHELL := /bin/bash
PYTHON := .venv/bin/python
PIP := .venv/bin/pip
RUFF := .venv/bin/ruff
PYTEST := .venv/bin/pytest

.PHONY: help venv install install-dev clean reset lock lint format test check syntax run start stop status restart

help:
	@echo "sheets-service 常用命令:"
	@echo ""
	@echo "  环境管理:"
	@echo "    make venv        - 创建虚拟环境"
	@echo "    make install     - 安装依赖"
	@echo "    make install-dev - 安装开发依赖"
	@echo "    make reset       - 重建虚拟环境"
	@echo "    make lock        - 导出 requirements.lock.txt"
	@echo ""
	@echo "  代码质量:"
	@echo "    make lint        - ruff check"
	@echo "    make format      - ruff format + fix"
	@echo "    make test        - pytest"
	@echo "    make check       - 完整检查 (lint + test)"
	@echo "    make syntax      - py_compile 快速语法检查"
	@echo ""
	@echo "  运行:"
	@echo "    make run         - 前台跑一次"
	@echo "    make start       - 后台 daemon"
	@echo "    make stop        - 停止 daemon"
	@echo "    make status      - 查看状态"

venv:
	@if [ ! -d ".venv" ]; then \
		echo "创建虚拟环境..."; \
		python3 -m venv .venv; \
		$(PIP) install -q --upgrade pip; \
	else \
		echo "虚拟环境已存在"; \
	fi

install: venv
	@echo "安装依赖..."
	$(PIP) install -q -r requirements.txt
	@echo "✅ 依赖安装完成"

install-dev: install
	@echo "安装开发依赖..."
	$(PIP) install -q -r requirements-dev.txt
	@echo "✅ 开发依赖安装完成"

clean:
	@echo "清理缓存..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf build/ dist/ .coverage htmlcov/
	@echo "✅ 清理完成"

reset: clean
	@echo "重建虚拟环境..."
	rm -rf .venv
	python3 -m venv .venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r requirements.txt
	@echo "✅ 虚拟环境重建完成"

lock:
	$(PIP) freeze > requirements.lock.txt
	@echo "✅ 依赖已锁定到 requirements.lock.txt"

lint:
	@if [ -f "$(RUFF)" ]; then \
		$(RUFF) check src/ tests/ --ignore E501,E402 --select E,F 2>/dev/null || $(RUFF) check src/ --ignore E501,E402 --select E,F; \
	else \
		echo "⚠️  ruff 未安装，运行 make install-dev"; \
	fi

format:
	@if [ -f "$(RUFF)" ]; then \
		$(RUFF) format src/ tests/ 2>/dev/null || $(RUFF) format src/; \
		$(RUFF) check --fix src/ tests/ --ignore E501,E402 --select E,F 2>/dev/null || $(RUFF) check --fix src/ --ignore E501,E402 --select E,F; \
	else \
		echo "⚠️  ruff 未安装，运行 make install-dev"; \
	fi

test:
	@if [ -f "$(PYTEST)" ]; then \
		$(PYTEST) tests/ -v; \
	else \
		echo "⚠️  pytest 未安装，运行 make install-dev"; \
	fi

check: lint test
	@echo "✅ 检查完成"

syntax:
	$(PYTHON) -m py_compile src/__main__.py
	@echo "✅ 语法检查通过"

run: install
	$(PYTHON) -m src --once

start:
	./scripts/start.sh start

stop:
	./scripts/start.sh stop

status:
	./scripts/start.sh status

restart:
	./scripts/start.sh restart
