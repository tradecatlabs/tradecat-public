#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

bash scripts/guard_public_local_files.sh
PYTHONPATH=src python3 -m compileall src tests
PYTHONPATH=src pytest -q tests
bash -n install.sh uninstall.sh scripts/start.sh scripts/watchdog.sh scripts/guard_public_local_files.sh
python3 -m py_compile scripts/request.py
