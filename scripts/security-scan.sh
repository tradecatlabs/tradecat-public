#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GITLEAKS_IMAGE="${GITLEAKS_IMAGE:-ghcr.io/gitleaks/gitleaks:v8.30.1}"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/security-scan.sh
  bash scripts/security-scan.sh --history '<git-log-range>'

Default mode scans a temporary snapshot of tracked files only, so ignored runtime
directories such as .venv/ and .tradecat/ are not included.
EOF
}

run_dir_scan() {
  scan_dir="$1"
  if command -v gitleaks >/dev/null 2>&1; then
    gitleaks dir --redact --verbose "$scan_dir"
    return
  fi
  if command -v docker >/dev/null 2>&1; then
    docker run --rm -v "$scan_dir:/scan:ro" "$GITLEAKS_IMAGE" dir --redact --verbose /scan
    return
  fi
  echo "ERROR: install gitleaks or docker to run secret scanning." >&2
  exit 1
}

run_history_scan() {
  log_opts="$1"
  if command -v gitleaks >/dev/null 2>&1; then
    gitleaks detect --source "$ROOT_DIR" --log-opts "$log_opts" --redact --verbose
    return
  fi
  if command -v docker >/dev/null 2>&1; then
    docker run --rm -v "$ROOT_DIR:/repo:ro" "$GITLEAKS_IMAGE" detect --source /repo --log-opts "$log_opts" --redact --verbose
    return
  fi
  echo "ERROR: install gitleaks or docker to run secret scanning." >&2
  exit 1
}

case "${1:-}" in
  -h|--help)
    usage
    exit 0
    ;;
  --history)
    [[ $# -eq 2 ]] || { usage >&2; exit 2; }
    run_history_scan "$2"
    ;;
  "")
    tmp_dir="$(mktemp -d)"
    trap 'rm -rf "$tmp_dir"' EXIT
    git -C "$ROOT_DIR" ls-files -z | tar -C "$ROOT_DIR" --null -T - -cf - | tar -xf - -C "$tmp_dir"
    run_dir_scan "$tmp_dir"
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
