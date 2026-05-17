#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="$ROOT_DIR/project"
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
  tmp_pipx_dir="$(mktemp -d)"
  if PIPX_HOME="$tmp_pipx_dir/home" \
    PIPX_BIN_DIR="$tmp_pipx_dir/bin" \
    PIPX_LOG_DIR="$tmp_pipx_dir/log" \
    run_audit pipx run --spec "pip-audit==$PIP_AUDIT_VERSION" pip-audit; then
    rm -rf "$tmp_pipx_dir"
    exit 0
  fi
  rm -rf "$tmp_pipx_dir"
  echo "WARN: pipx pip-audit failed; trying next available audit runner." >&2
fi

if command -v uvx >/dev/null 2>&1; then
  tmp_uv_dir="$(mktemp -d)"
  if UV_CACHE_DIR="$tmp_uv_dir/cache" \
    UV_TOOL_DIR="$tmp_uv_dir/tools" \
    run_audit uvx --from "pip-audit==$PIP_AUDIT_VERSION" pip-audit; then
    rm -rf "$tmp_uv_dir"
    exit 0
  fi
  rm -rf "$tmp_uv_dir"
  echo "WARN: uvx pip-audit failed; trying temporary virtualenv audit runner." >&2
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

python3 -m venv "$tmp_dir/venv"
"$tmp_dir/venv/bin/python" -m pip install --upgrade pip >/dev/null
"$tmp_dir/venv/bin/python" -m pip install "pip-audit==$PIP_AUDIT_VERSION" >/dev/null
run_audit "$tmp_dir/venv/bin/pip-audit"
