#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="$ROOT_DIR/scripts/project"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$PROJECT_DIR"

if command -v uv >/dev/null 2>&1; then
  uv venv .venv
  if [[ -f constraints.txt ]]; then
    uv pip install --python .venv/bin/python -c constraints.txt -e ".[dev]"
  else
    uv pip install --python .venv/bin/python -e ".[dev]"
  fi
else
  "$PYTHON_BIN" -m venv .venv
  .venv/bin/python -m pip install -U pip
  if [[ -f constraints.txt ]]; then
    .venv/bin/python -m pip install -c constraints.txt -e ".[dev]"
  else
    .venv/bin/python -m pip install -e ".[dev]"
  fi
fi

echo "dev environment ready: $PROJECT_DIR/.venv"
