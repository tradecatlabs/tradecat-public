PYTHON ?= python3

.PHONY: install install-dev test lint format format-check test-ci-contract security supply-chain agent-smoke paper-status paper-health paper-ops paper-start paper-stop monitor verify

install:
	$(PYTHON) -m pip install -c constraints.txt -e .

install-dev:
	$(PYTHON) -m pip install -c constraints.txt -e ".[dev]"

test:
	PYTHONPATH=src $(PYTHON) -m pytest -q

lint:
	PYTHONPATH=src $(PYTHON) -m ruff check src tests

format:
	$(PYTHON) -m ruff format src tests scripts

format-check:
	$(PYTHON) -m ruff format --check src tests scripts

test-ci-contract:
	$(PYTHON) scripts/validate_testing_ci_contract.py

security:
	bash scripts/security-scan.sh

supply-chain:
	bash scripts/supply-chain-audit.sh

agent-smoke:
	bash scripts/agent-smoke.sh

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
