#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if "$APP_DIR/scripts/start.sh" status >/dev/null 2>&1; then
  "$APP_DIR/scripts/start.sh" status
else
  echo "watch process missing; restarting"
  "$APP_DIR/scripts/start.sh" start
fi

