#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

cleanup_generated() {
  find scripts src tests -path '*/__pycache__' -type d -prune -exec rm -rf {} +
  rm -rf .pytest_cache .ruff_cache
}

ensure_dev_environment() {
  if [[ -x ".venv/bin/python" && -x ".venv/bin/pytest" && -x ".venv/bin/ruff" ]]; then
    return 0
  fi
  if command -v pytest >/dev/null 2>&1 && command -v ruff >/dev/null 2>&1; then
    return 0
  fi
  if [[ -f "../../scripts/bootstrap-dev.sh" ]]; then
    echo "verify: dev tools missing; bootstrapping $(pwd)/.venv" >&2
    bash ../../scripts/bootstrap-dev.sh
  fi
}

resolve_tooling() {
  PYTHON_BIN="${PYTHON_BIN:-python3}"
  PYTEST_BIN="${PYTEST_BIN:-pytest}"
  RUFF_BIN="${RUFF_BIN:-ruff}"

  if [[ -x ".venv/bin/python" ]]; then
    PYTHON_BIN=".venv/bin/python"
  fi
  if [[ -x ".venv/bin/pytest" ]]; then
    PYTEST_BIN=".venv/bin/pytest"
  fi
  if [[ -x ".venv/bin/ruff" ]]; then
    RUFF_BIN=".venv/bin/ruff"
  fi
}

trap cleanup_generated EXIT
cleanup_generated
ensure_dev_environment
resolve_tooling

bash scripts/guard_public_local_files.sh
PYTHONPATH=src "$PYTHON_BIN" -m compileall src tests
PYTHONPATH=src "$PYTEST_BIN" -q -p no:cacheprovider tests
PYTHONPATH=src "$PYTHON_BIN" scripts/validate_data_contract.py
PYTHONPATH=src "$PYTHON_BIN" scripts/validate_dataset_consumption_contract.py
PYTHONPATH=src "$PYTHON_BIN" scripts/validate_agent_market_context_resources.py
if command -v "$RUFF_BIN" >/dev/null 2>&1 || [[ -x "$RUFF_BIN" ]]; then
  "$RUFF_BIN" check src tests
else
  echo "ERROR: ruff is required for local verification." >&2
  echo "Fix: bash ../../scripts/bootstrap-dev.sh" >&2
  exit 1
fi
bash -n install.sh uninstall.sh scripts/start.sh scripts/start-auto-paper.sh scripts/watchdog.sh scripts/guard_public_local_files.sh
"$PYTHON_BIN" -m py_compile scripts/request.py scripts/validate_data_contract.py scripts/validate_dataset_consumption_contract.py scripts/validate_agent_market_context_resources.py
