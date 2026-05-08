#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="$ROOT_DIR/scripts/project"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

json_expect() {
  local file="$1"
  local schema="$2"
  python3 - "$file" "$schema" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected = sys.argv[2]
payload = json.loads(path.read_text(encoding="utf-8"))
if payload.get("schema") != expected:
    raise SystemExit(f"{path}: schema {payload.get('schema')!r} != {expected!r}")
if payload.get("schema_version") != "1.0.0":
    raise SystemExit(f"{path}: missing schema_version=1.0.0")
if payload.get("ok") is False and not isinstance(payload.get("error"), dict):
    raise SystemExit(f"{path}: ok=false without error object")
PY
}

cd "$ROOT_DIR"

bash scripts/validate-skill.sh --strict >/dev/null
python3 -m json.tool agents/manifest.json >/dev/null
for schema_file in scripts/project/contracts/*.schema.json; do
  python3 -m json.tool "$schema_file" >/dev/null
done

if ! PYTHONPATH="$PROJECT_DIR/src" python3 - <<'PY' >/dev/null 2>&1
import tradecat_terminal.cli
PY
then
  bash scripts/bootstrap-dev.sh >/dev/null
fi

bash scripts/run-tradecat.sh status --json >"$TMP_DIR/status.json"
json_expect "$TMP_DIR/status.json" "tradecat.status.v1"

bash scripts/run-tradecat.sh datasets --json >"$TMP_DIR/datasets.json"
json_expect "$TMP_DIR/datasets.json" "tradecat.dataset_list.v1"

bash scripts/run-tradecat.sh path event_stream --json >"$TMP_DIR/path.json"
json_expect "$TMP_DIR/path.json" "tradecat.path_map.v1"

TRADECAT_REQUEST_REGISTRY_URL="$(python3 - "$PROJECT_DIR/src/tradecat_terminal/dataset_registry.json" <<'PY'
import sys
from pathlib import Path

print(Path(sys.argv[1]).resolve().as_uri())
PY
)" python3 scripts/project/scripts/request.py --datasets --format json >"$TMP_DIR/request-datasets.json"
json_expect "$TMP_DIR/request-datasets.json" "tradecat.request_dataset_list.v1"

set +e
bash scripts/run-tradecat.sh sync invalid_dataset --json >"$TMP_DIR/invalid.json" 2>"$TMP_DIR/invalid.err"
exit_code=$?
set -e
if [[ "$exit_code" -eq 0 ]]; then
  echo "agent-smoke: invalid dataset returned exit 0" >&2
  exit 1
fi
json_expect "$TMP_DIR/invalid.json" "tradecat.sync_result.v1"
python3 - "$TMP_DIR/invalid.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
error = payload.get("error") or {}
if payload.get("ok") is not False:
    raise SystemExit("invalid dataset payload must set ok=false")
if error.get("code") != "invalid_dataset_key":
    raise SystemExit(f"unexpected error code: {error.get('code')!r}")
PY

echo "agent-smoke: ok"
