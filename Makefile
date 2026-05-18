.PHONY: install install-dev test lint format paper-status paper-health paper-ops paper-start paper-stop monitor verify

install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"

test:
	pytest -q

lint:
	ruff check src tests

format:
	ruff format src tests

paper-status:
	bash scripts/start-auto-paper.sh status --json

paper-health:
	bash scripts/start-auto-paper.sh health --json

paper-ops:
	bash scripts/start-auto-paper.sh ops-check --json

paper-start:
	bash scripts/start-auto-paper.sh start --json

paper-stop:
	bash scripts/start-auto-paper.sh stop --json

monitor:
	python scripts/serve-auto-paper-monitor.py

verify:
	bash scripts/verify.sh
