#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(git -C "$PROJECT_DIR" rev-parse --show-toplevel)"

cd "$REPO_ROOT"

runtime_paths=(
  ".venv"
  ".tradecat"
  "scripts/project/.venv"
  "scripts/project/.tradecat"
)

forbidden_root_paths=(
  "assets"
  "src"
  "tests"
  "pyproject.toml"
  "Makefile"
  "install.sh"
  "install.ps1"
  "uninstall.sh"
  "uninstall.ps1"
)

failed=0
for path in "${runtime_paths[@]}"; do
  tracked_matches="$(git ls-files "$path")"
  if [[ -n "$tracked_matches" ]]; then
    echo "ERROR: runtime path must not be tracked in the public repo: $path" >&2
    echo "$tracked_matches" >&2
    failed=1
  fi
done

for path in "${forbidden_root_paths[@]}"; do
  if [[ -e "$path" ]]; then
    echo "ERROR: root path is forbidden in the Skill wrapper: $path" >&2
    failed=1
  fi
done

if [[ "$failed" -ne 0 ]]; then
  echo "Fix: git rm --cached <listed runtime paths>" >&2
  echo "Fix: move forbidden root project files under scripts/project/." >&2
  exit 1
fi

echo "public root-boundary guard ok"
