#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)"

cd "$REPO_ROOT"

runtime_paths=(
  ".runtime"
  ".hermes"
  ".venv"
  ".tradecat"
  ".tools"
)

forbidden_project_roots=(
  "scripts/project"
  "project/src"
  "project/tests"
  "project/contracts"
  "project/resources"
)

forbidden_root_paths=(
  "SKILL.md"
  "agents"
  "references"
)

retired_product_paths=(
  "src/tradecat_terminal"
  "install.sh"
  "install.ps1"
  "uninstall.sh"
  "uninstall.ps1"
  "scripts/start.sh"
  "scripts/watchdog.sh"
)

failed=0
for path in "${runtime_paths[@]}"; do
  tracked_matches="$(git ls-files "$path")"
  if [[ -n "$tracked_matches" ]]; then
    echo "ERROR: runtime path must not be tracked in the public repo: $path" >&2
    echo "$tracked_matches" >&2
    failed=1
  fi
done

for path in "${forbidden_project_roots[@]}"; do
  if [[ -e "$path" ]]; then
    echo "ERROR: legacy project root path must not exist: $path" >&2
    failed=1
  fi
  tracked_matches="$(git ls-files "$path")"
  if [[ -n "$tracked_matches" ]]; then
    echo "ERROR: legacy nested project files are still tracked: $path" >&2
    echo "$tracked_matches" >&2
    failed=1
  fi
done

for path in "${forbidden_root_paths[@]}"; do
  if [[ -e "$path" ]]; then
    echo "ERROR: Skill package path must live under skills/tradecat-public/, not repository root: $path" >&2
    failed=1
  fi
done

for path in "${retired_product_paths[@]}"; do
  if [[ -e "$path" ]]; then
    echo "ERROR: retired local TUI/install product path must not exist: $path" >&2
    failed=1
  fi
  tracked_matches="$(git ls-files "$path")"
  if [[ -n "$tracked_matches" ]]; then
    echo "ERROR: retired local TUI/install product files are still tracked: $path" >&2
    echo "$tracked_matches" >&2
    failed=1
  fi
done

if [[ "$failed" -ne 0 ]]; then
  echo "Fix: git rm --cached <listed runtime paths>" >&2
  echo "Fix: keep the Python project at repository root and the Skill package under skills/tradecat-public/." >&2
  exit 1
fi

echo "public project/skill boundary guard ok"
