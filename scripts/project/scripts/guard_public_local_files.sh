#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(git -C "$PROJECT_DIR" rev-parse --show-toplevel)"

cd "$REPO_ROOT"

blocked=(
  "AGENTS.md"
  "DEBUG.md"
  "DEBUG.archive.md"
  "scripts/project/AGENTS.md"
  "scripts/project/DEBUG.md"
  "scripts/project/DEBUG.archive.md"
)

failed=0
for path in "${blocked[@]}"; do
  if git ls-files --error-unmatch "$path" >/dev/null 2>&1; then
    echo "ERROR: $path is local-only and must not be tracked in the public repo." >&2
    failed=1
  fi
done

if [[ "$failed" -ne 0 ]]; then
  echo "Fix: git rm --cached <listed local-only paths>" >&2
  exit 1
fi

echo "public local-file guard ok"
