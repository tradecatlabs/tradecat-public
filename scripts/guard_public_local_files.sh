#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

blocked=(
  "AGENTS.md"
  "DEBUG.md"
  "DEBUG.archive.md"
)

failed=0
for path in "${blocked[@]}"; do
  if git ls-files --error-unmatch "$path" >/dev/null 2>&1; then
    echo "ERROR: $path is local-only and must not be tracked in the public repo." >&2
    failed=1
  fi
done

if [[ "$failed" -ne 0 ]]; then
  echo "Fix: git rm --cached AGENTS.md DEBUG.md DEBUG.archive.md" >&2
  exit 1
fi

echo "public local-file guard ok"
