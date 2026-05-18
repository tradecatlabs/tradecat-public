#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_DIR="$ROOT_DIR/skills/tradecat-public"

bash "$ROOT_DIR/scripts/validate-skill.sh" --strict "$SKILL_DIR"

if [[ ! -x "$ROOT_DIR/.venv/bin/python" || ! -x "$ROOT_DIR/.venv/bin/pytest" || ! -x "$ROOT_DIR/.venv/bin/ruff" ]]; then
  if ! command -v pytest >/dev/null 2>&1 || ! command -v ruff >/dev/null 2>&1; then
    echo "verify: dev tools missing; bootstrapping $ROOT_DIR/.venv" >&2
    bash "$ROOT_DIR/scripts/bootstrap-dev.sh"
  fi
fi

cd "$ROOT_DIR"
exec bash scripts/verify-project.sh
