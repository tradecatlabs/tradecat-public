#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$SKILL_DIR/../.." && pwd)"

exec bash "$REPO_ROOT/scripts/validate-skill.sh" "$@" "$SKILL_DIR"
