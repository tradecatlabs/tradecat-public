#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

cleanup_generated() {
  find scripts src tests -path '*/__pycache__' -type d -prune -exec rm -rf {} +
  rm -rf .pytest_cache .ruff_cache
}

trap cleanup_generated EXIT
cleanup_generated

bash scripts/guard_public_local_files.sh
PYTHONPATH=src python3 -m compileall src tests
PYTHONPATH=src pytest -q -p no:cacheprovider tests
if command -v ruff >/dev/null 2>&1; then
  ruff check src tests
elif [[ -x ".venv/bin/ruff" ]]; then
  .venv/bin/ruff check src tests
else
  echo "ERROR: ruff is required for local verification." >&2
  echo "Fix: cd scripts/project && python3 -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'" >&2
  exit 1
fi
bash -n install.sh uninstall.sh scripts/start.sh scripts/watchdog.sh scripts/guard_public_local_files.sh
python3 -m py_compile scripts/request.py
