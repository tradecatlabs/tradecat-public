#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="$ROOT_DIR/scripts/project"
PIP_AUDIT_VERSION="${PIP_AUDIT_VERSION:-2.10.0}"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/supply-chain-audit.sh

Audits the bundled Python project with pip-audit. The script prefers pipx or uvx
and falls back to a temporary virtual environment so a fresh workstation can run
the gate without preinstalled audit tooling.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

run_audit() {
  "$@" "$PROJECT_DIR" --progress-spinner off --skip-editable
}

if command -v pipx >/dev/null 2>&1; then
  run_audit python3 -m pipx run --spec "pip-audit==$PIP_AUDIT_VERSION" pip-audit
  exit 0
fi

if command -v uvx >/dev/null 2>&1; then
  run_audit uvx --from "pip-audit==$PIP_AUDIT_VERSION" pip-audit
  exit 0
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

python3 -m venv "$tmp_dir/venv"
"$tmp_dir/venv/bin/python" -m pip install --upgrade pip >/dev/null
"$tmp_dir/venv/bin/python" -m pip install "pip-audit==$PIP_AUDIT_VERSION" >/dev/null
run_audit "$tmp_dir/venv/bin/pip-audit"
