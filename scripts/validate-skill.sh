#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash scripts/validate-skill.sh [--strict] [skill-dir]

Defaults:
  skill-dir defaults to the repository root.

Environment:
  CODEX_HOME overrides the Codex home directory used to find auto-skill.
  TRADECAT_SKILL_NAME overrides the expected frontmatter name.
EOF
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

strip_outer_quotes() {
  local value="$1"
  value="${value#\"}"
  value="${value%\"}"
  value="${value#\'}"
  value="${value%\'}"
  printf "%s" "$value"
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
EXPECTED_SKILL_NAME="${TRADECAT_SKILL_NAME:-tradecat-public}"
strict=0
skill_dir="$ROOT_DIR"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --strict)
      strict=1
      shift
      ;;
    --)
      shift
      break
      ;;
    -*)
      die "Unknown argument: $1"
      ;;
    *)
      skill_dir="$1"
      shift
      ;;
  esac
done

if [[ "$skill_dir" != /* ]]; then
  skill_dir="$(cd "$skill_dir" && pwd)"
fi

external_validator="$CODEX_HOME/skills/auto-skill/scripts/validate-skill.sh"
if [[ -x "$external_validator" ]]; then
  if [[ "$strict" -eq 1 ]]; then
    exec bash "$external_validator" "$skill_dir" --strict
  fi
  exec bash "$external_validator" "$skill_dir"
fi

skill_md="$skill_dir/SKILL.md"
[[ -f "$skill_md" ]] || die "Missing SKILL.md: $skill_md"

base_name="$(basename -- "${skill_dir%/}")"

frontmatter="$(
  awk '
    BEGIN { in_fm=0; closed=0 }
    NR==1 {
      if ($0 != "---") exit 2
      in_fm=1
      next
    }
    in_fm==1 {
      if ($0 == "---") { closed=1; exit 0 }
      print
      next
    }
    END {
      if (closed == 0) exit 3
    }
  ' "$skill_md"
)" || {
  rc=$?
  case "$rc" in
    2) die "SKILL.md must start with YAML frontmatter" ;;
    3) die "SKILL.md frontmatter is not closed" ;;
    *) die "Failed to parse SKILL.md frontmatter" ;;
  esac
}

name="$(
  printf "%s\n" "$frontmatter" | awk -F: '
    tolower($1) ~ /^name$/ {
      sub(/^[^:]*:[[:space:]]*/, "", $0)
      gsub(/[[:space:]]+$/, "", $0)
      print
      exit
    }
  '
)"

description="$(
  printf "%s\n" "$frontmatter" | awk -F: '
    tolower($1) ~ /^description$/ {
      sub(/^[^:]*:[[:space:]]*/, "", $0)
      gsub(/[[:space:]]+$/, "", $0)
      print
      exit
    }
  '
)"

name="$(strip_outer_quotes "$name")"
description="$(strip_outer_quotes "$description")"

[[ -n "$name" ]] || die "Missing frontmatter field: name"
[[ -n "$description" ]] || die "Missing frontmatter field: description"

if [[ ! "$name" =~ ^[a-z][a-z0-9-]*$ ]]; then
  die "Invalid skill name: $name"
fi

if [[ "$strict" -eq 1 && "$name" != "$base_name" && "$name" != "$EXPECTED_SKILL_NAME" ]]; then
  die "Strict mode: frontmatter name '$name' must match directory name '$base_name' or expected name '$EXPECTED_SKILL_NAME'"
fi

filtered_md="$(mktemp)"
trap 'rm -f "$filtered_md"' EXIT

awk '
  BEGIN { in_fence=0 }
  /^[[:space:]]*```/ { in_fence = !in_fence; next }
  in_fence==0 { print }
' "$skill_md" > "$filtered_md"

required_h2=(
  "When to Use This Skill"
  "Not For / Boundaries"
  "Quick Reference"
  "Examples"
  "References"
  "Maintenance"
)

for title in "${required_h2[@]}"; do
  if ! grep -Eq "^##[[:space:]]+${title}([[:space:]]*)$" "$filtered_md"; then
    die "Missing required section heading: ## $title"
  fi
done

if [[ -d "$skill_dir/references" && ! -f "$skill_dir/references/index.md" ]]; then
  die "references/ exists but references/index.md is missing"
fi

example_count="$(
  awk '
    /^##[[:space:]]+Examples[[:space:]]*$/ { in_examples=1; next }
    in_examples && /^##[[:space:]]+/ { in_examples=0 }
    in_examples && /^###[[:space:]]+Example([[:space:]]|$)/ { c++ }
    END { print c+0 }
  ' "$filtered_md"
)"

if [[ "$strict" -eq 1 && "$example_count" -lt 3 ]]; then
  die "Strict mode: expected at least 3 examples; found $example_count"
fi

echo "OK: $skill_dir"
