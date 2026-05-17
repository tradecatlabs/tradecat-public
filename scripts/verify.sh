#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="$ROOT_DIR/project"

bash "$ROOT_DIR/scripts/validate-skill.sh" --strict

if [[ ! -x "$PROJECT_DIR/.venv/bin/python" || ! -x "$PROJECT_DIR/.venv/bin/pytest" || ! -x "$PROJECT_DIR/.venv/bin/ruff" ]]; then
  if ! command -v pytest >/dev/null 2>&1 || ! command -v ruff >/dev/null 2>&1; then
    echo "verify: dev tools missing; bootstrapping $PROJECT_DIR/.venv" >&2
    bash "$ROOT_DIR/scripts/bootstrap-dev.sh"
  fi
fi

cd "$PROJECT_DIR"
exec bash scripts/verify.sh
