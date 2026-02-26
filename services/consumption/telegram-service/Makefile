# Telegram Service Makefile
# 用法: make <target>

SHELL := /bin/bash
PYTHON := .venv/bin/python
PIP := .venv/bin/pip
RUFF := .venv/bin/ruff
PYTEST := .venv/bin/pytest

.PHONY: help venv install install-dev clean lint format test check run start stop status

help:
	@echo "Telegram Service 常用命令:"
	@echo ""
	@echo "  环境管理:"
	@echo "    make venv        - 创建虚拟环境"
	@echo "    make install     - 安装依赖"
	@echo "    make install-dev - 安装开发依赖"
	@echo "    make clean       - 清理缓存和构建产物"
	@echo "    make reset       - 重建虚拟环境"
	@echo ""
	@echo "  代码质量:"
	@echo "    make lint        - 代码检查 (ruff)"
	@echo "    make format      - 代码格式化 (ruff)"
	@echo "    make test        - 运行测试 (pytest)"
	@echo "    make check       - 完整检查 (lint + test)"
	@echo ""
	@echo "  国际化:"
	@echo "    make i18n-compile - 编译 .po 到 .mo"
	@echo ""
	@echo "  运行服务:"
	@echo "    make run         - 前台运行（调试用）"
	@echo "    make start       - 后台启动"
	@echo "    make stop        - 停止服务"
	@echo "    make status      - 查看状态"

# ==================== 环境管理 ====================

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
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
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

# ==================== 代码质量 ====================

lint:
	@if [ -f "$(RUFF)" ]; then \
		$(RUFF) check src/ tests/ 2>/dev/null || $(RUFF) check src/; \
	else \
		echo "⚠️  ruff 未安装，运行 make install-dev"; \
	fi

format:
	@if [ -f "$(RUFF)" ]; then \
		$(RUFF) format src/ tests/ 2>/dev/null || $(RUFF) format src/; \
		$(RUFF) check --fix src/ tests/ 2>/dev/null || $(RUFF) check --fix src/; \
	else \
		echo "⚠️  ruff 未安装，运行 make install-dev"; \
	fi

test:
	@if [ -f "$(PYTEST)" ]; then \
		$(PYTEST) tests/ -v; \
	else \
		echo "⚠️  pytest 未安装，运行 make install-dev"; \
	fi

test-cov:
	@if [ -f "$(PYTEST)" ]; then \
		$(PYTEST) tests/ -v --cov=src --cov-report=term-missing; \
	else \
		echo "⚠️  pytest 未安装，运行 make install-dev"; \
	fi

typecheck:
	@if [ -f ".venv/bin/mypy" ]; then \
		.venv/bin/mypy src/; \
	else \
		echo "⚠️  mypy 未安装，运行 make install-dev"; \
	fi

check: lint test
	@echo "✅ 检查完成"

syntax:
	$(PYTHON) -m py_compile src/__main__.py src/bot/app.py
	@echo "✅ 语法检查通过"

# ==================== 国际化 ====================

i18n-compile:
	@echo "编译国际化文件..."
	@LOCALE_DIR=$$(python3 - <<'PY'\nfrom pathlib import Path\nroot = Path(__file__).resolve().parents[2]\ndefault = root / \"services\" / \"consumption\" / \"telegram-service\" / \"locales\"\n\ndef has_bot(p: Path) -> bool:\n    for lang in (\"zh_CN\", \"en\"):\n        lc = p / lang / \"LC_MESSAGES\"\n        if (lc / \"bot.po\").exists() or (lc / \"bot.mo\").exists():\n            return True\n    return False\n\nif has_bot(default):\n    print(default)\n    raise SystemExit(0)\n\ncandidates = set()\nfor po in root.rglob(\"bot.po\"):\n    parts = po.parts\n    if \"node_modules\" in parts:\n        continue\n    # 目录结构迁移后：第三方镜像库位于 assets/repo；预览服务位于 assets/services-preview\n    # 这两类目录不应参与 i18n 发现（避免误命中/性能问题）。\n    if (\"assets\" in parts and \"repo\" in parts) or (\"assets\" in parts and \"services-preview\" in parts):\n        continue\n    if po.parent.name != \"LC_MESSAGES\":\n        continue\n    candidates.add(po.parents[2])\n\nfor cand in sorted(candidates):\n    if has_bot(cand):\n        print(cand)\n        raise SystemExit(0)\n\nprint(default)\nPY\n); \\\n	for po in $$LOCALE_DIR/*/LC_MESSAGES/*.po; do \\\n		mo=$${po%.po}.mo; \\\n		msgfmt -o $$mo $$po && echo \"  ✅ $$mo\"; \\\n	done
	@echo "✅ 国际化编译完成"

# ==================== 运行服务 ====================

run: install
	$(PYTHON) -m src

start:
	./scripts/start.sh start

stop:
	./scripts/start.sh stop

status:
	./scripts/start.sh status

restart:
	./scripts/start.sh restart
