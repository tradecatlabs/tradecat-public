.PHONY: install install-dev test lint format status init doctor probe start stop watchdog verify

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

init:
	python -m tradecat_terminal init

status:
	python -m tradecat_terminal status

doctor:
	python -m tradecat_terminal doctor

probe:
	python -m tradecat_terminal probe

start:
	bash scripts/start.sh start

stop:
	bash scripts/start.sh stop

watchdog:
	bash scripts/watchdog.sh

verify:
	bash scripts/verify.sh
