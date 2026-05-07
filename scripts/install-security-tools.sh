#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GITLEAKS_VERSION="${GITLEAKS_VERSION:-8.30.1}"
BIN_DIR="${TRADECAT_LOCAL_TOOLS_DIR:-$ROOT_DIR/.tools/bin}"
TOOL="gitleaks"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/install-security-tools.sh [--tool gitleaks] [--bin-dir DIR]

Installs local security tools under .tools/bin by default. The directory is
ignored by Git and is intended for developer workstations that lack Docker.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tool)
      TOOL="${2:-}"
      shift 2
      ;;
    --bin-dir)
      BIN_DIR="${2:-}"
      shift 2
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

[[ "$TOOL" == "gitleaks" ]] || { echo "ERROR: unsupported tool: $TOOL" >&2; exit 2; }
[[ -n "$BIN_DIR" ]] || { echo "ERROR: --bin-dir is required" >&2; exit 2; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "ERROR: missing command: $1" >&2; exit 1; }
}

platform_name() {
  case "$(uname -s | tr '[:upper:]' '[:lower:]')" in
    linux*) echo "linux" ;;
    darwin*) echo "darwin" ;;
    *) echo "ERROR: unsupported OS: $(uname -s)" >&2; exit 1 ;;
  esac
}

arch_name() {
  case "$(uname -m)" in
    x86_64|amd64) echo "x64" ;;
    aarch64|arm64) echo "arm64" ;;
    armv7l) echo "armv7" ;;
    armv6l) echo "armv6" ;;
    i386|i686) echo "x32" ;;
    *) echo "ERROR: unsupported architecture: $(uname -m)" >&2; exit 1 ;;
  esac
}

verify_checksum() {
  archive="$1"
  checksums="$2"
  archive_name="$(basename "$archive")"
  grep "  $archive_name\$" "$checksums" > "$checksums.one"
  if command -v sha256sum >/dev/null 2>&1; then
    (cd "$(dirname "$archive")" && sha256sum -c "$checksums.one")
  elif command -v shasum >/dev/null 2>&1; then
    (cd "$(dirname "$archive")" && shasum -a 256 -c "$checksums.one")
  else
    echo "WARN: sha256sum/shasum not found; skipping checksum verification" >&2
  fi
}

install_gitleaks() {
  need_cmd curl
  need_cmd tar
  os="$(platform_name)"
  arch="$(arch_name)"
  archive_name="gitleaks_${GITLEAKS_VERSION}_${os}_${arch}.tar.gz"
  base_url="https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}"
  tmp_dir="$(mktemp -d)"
  trap 'rm -rf "$tmp_dir"' EXIT

  curl -fsSL "$base_url/$archive_name" -o "$tmp_dir/$archive_name"
  curl -fsSL "$base_url/gitleaks_${GITLEAKS_VERSION}_checksums.txt" -o "$tmp_dir/checksums.txt"
  verify_checksum "$tmp_dir/$archive_name" "$tmp_dir/checksums.txt"

  tar -xzf "$tmp_dir/$archive_name" -C "$tmp_dir" gitleaks
  mkdir -p "$BIN_DIR"
  install -m 0755 "$tmp_dir/gitleaks" "$BIN_DIR/gitleaks"
  "$BIN_DIR/gitleaks" version
}

install_gitleaks
