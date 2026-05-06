#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="$ROOT_DIR/scripts/project"

bash "$ROOT_DIR/scripts/validate-skill.sh" --strict

cd "$PROJECT_DIR"
exec bash scripts/verify.sh
