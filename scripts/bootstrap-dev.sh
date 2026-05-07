#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="$ROOT_DIR/scripts/project"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$PROJECT_DIR"

if command -v uv >/dev/null 2>&1; then
  uv venv .venv
  uv pip install --python .venv/bin/python -e ".[dev]"
else
  "$PYTHON_BIN" -m venv .venv
  .venv/bin/python -m pip install -U pip
  .venv/bin/python -m pip install -e ".[dev]"
fi

echo "dev environment ready: $PROJECT_DIR/.venv"
