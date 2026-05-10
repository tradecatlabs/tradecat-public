#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JSON=0

for arg in "$@"; do
  case "$arg" in
    --json) JSON=1 ;;
    *) echo "usage: $0 [--json]" >&2; exit 2 ;;
  esac
done

if [[ "$JSON" -eq 1 ]]; then
  set +e
  status_output="$("$APP_DIR/scripts/start.sh" status --json)"
  status_code=$?
  set -e
  if [[ "$status_code" -eq 0 ]]; then
    printf '%s\n' "$status_output"
    exit 0
  fi
  "$APP_DIR/scripts/start.sh" start --json
  exit $?
fi

if "$APP_DIR/scripts/start.sh" status >/dev/null 2>&1; then
  "$APP_DIR/scripts/start.sh" status
else
  echo "watch process missing; restarting"
  "$APP_DIR/scripts/start.sh" start
fi
