#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GITLEAKS_IMAGE="${GITLEAKS_IMAGE:-ghcr.io/gitleaks/gitleaks@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f}"
LOCAL_TOOLS_DIR="${TRADECAT_LOCAL_TOOLS_DIR:-$ROOT_DIR/.tools/bin}"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/security-scan.sh
  bash scripts/security-scan.sh --history '<git-log-range>'

Default mode scans a temporary snapshot of tracked files only, so ignored runtime
directories such as .venv/ and .tradecat/ are not included.
EOF
}

ensure_gitleaks() {
  if command -v gitleaks >/dev/null 2>&1; then
    return 0
  fi
  if [[ -x "$LOCAL_TOOLS_DIR/gitleaks" ]]; then
    PATH="$LOCAL_TOOLS_DIR:$PATH"
    export PATH
    return 0
  fi
  if docker_available; then
    return 0
  fi
  if [[ "${TRADECAT_SECURITY_AUTO_INSTALL:-1}" == "0" ]]; then
    return 0
  fi
  if bash "$ROOT_DIR/scripts/install-security-tools.sh" --tool gitleaks --bin-dir "$LOCAL_TOOLS_DIR"; then
    PATH="$LOCAL_TOOLS_DIR:$PATH"
    export PATH
  fi
}

docker_available() {
  command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1
}

run_fallback_scan() {
  scan_dir="$1"
  echo "WARN: gitleaks/docker unavailable; running limited local secret pattern scan." >&2
  python3 - "$scan_dir" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
patterns = {
    "private_key": re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}\b"),
    "github_pat": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}_[A-Za-z0-9_]{59,}\b"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{32,}\b"),
    "binance_secret_assignment": re.compile(
        r"(?i)\b(?:BINANCE_)?(?:API_)?SECRET(?:_KEY)?\b\s*[:=]\s*['\"]?([A-Za-z0-9/+=_-]{24,})"
    ),
}
placeholder_markers = (
    "your_",
    "example",
    "placeholder",
    "changeme",
    "dummy",
    "test_",
    "xxx",
)
findings: list[str] = []
for path in sorted(item for item in root.rglob("*") if item.is_file()):
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        findings.append(f"{path.relative_to(root)}: unreadable: {exc}")
        continue
    for line_number, line in enumerate(text.splitlines(), start=1):
        for name, pattern in patterns.items():
            match = pattern.search(line)
            if not match:
                continue
            sample = match.group(0).lower()
            if any(marker in sample for marker in placeholder_markers):
                continue
            findings.append(f"{path.relative_to(root)}:{line_number}: {name}")

if findings:
    for item in findings:
        print(f"ERROR: possible secret: {item}", file=sys.stderr)
    raise SystemExit(1)
print("limited secret pattern scan ok")
PY
}

run_dir_scan() {
  scan_dir="$1"
  ensure_gitleaks
  if command -v gitleaks >/dev/null 2>&1; then
    gitleaks dir --redact --verbose "$scan_dir"
    return
  fi
  if command -v docker >/dev/null 2>&1; then
    docker_available || {
      run_fallback_scan "$scan_dir"
      return
    }
    docker run --rm -v "$scan_dir:/scan:ro" "$GITLEAKS_IMAGE" dir --redact --verbose /scan
    return
  fi
  run_fallback_scan "$scan_dir"
}

run_history_scan() {
  log_opts="$1"
  ensure_gitleaks
  if command -v gitleaks >/dev/null 2>&1; then
    gitleaks detect --source "$ROOT_DIR" --log-opts "$log_opts" --redact --verbose
    return
  fi
  if command -v docker >/dev/null 2>&1; then
    docker_available || {
      echo "ERROR: gitleaks is required for history scanning when Docker is unavailable." >&2
      exit 1
    }
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
    git -C "$ROOT_DIR" ls-files -z |
      while IFS= read -r -d '' tracked_path; do
        if [[ -e "$ROOT_DIR/$tracked_path" ]]; then
          printf '%s\0' "$tracked_path"
        fi
      done |
      tar -C "$ROOT_DIR" --null -T - -cf - |
      tar -xf - -C "$tmp_dir"
    run_dir_scan "$tmp_dir"
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
