#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPLY=0

usage() {
  cat <<'EOF'
Usage:
  bash scripts/clean-local-runtime.sh [--apply]

Removes ignored local runtime directories from this working tree. Without
--apply, prints the paths that would be removed.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      APPLY=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

cd "$ROOT_DIR"

paths=(
  ".tradecat"
  ".venv"
  ".tools"
  "scripts/project/.tradecat"
  "scripts/project/.venv"
)

generated_names=(
  "__pycache__"
  ".pytest_cache"
  ".ruff_cache"
)

remove_path() {
  path="$1"
  [[ -e "$path" ]] || return 0
  if [[ "$APPLY" -eq 1 ]]; then
    rm -rf "$path"
    echo "removed: $path"
  else
    echo "would remove: $path"
  fi
}

for path in "${paths[@]}"; do
  remove_path "$path"
done

for name in "${generated_names[@]}"; do
  while IFS= read -r path; do
    remove_path "$path"
  done < <(find . -type d -name "$name" -prune)
done
