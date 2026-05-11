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

json_expect_error_code() {
  local file="$1"
  local code="$2"
  python3 - "$file" "$code" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected = sys.argv[2]
error = payload.get("error") or {}
if payload.get("ok") is not False:
    raise SystemExit(f"{sys.argv[1]}: expected ok=false")
if error.get("code") != expected:
    raise SystemExit(f"{sys.argv[1]}: error.code {error.get('code')!r} != {expected!r}")
PY
}

cd "$ROOT_DIR"

bash scripts/validate-skill.sh --strict >/dev/null
python3 -m json.tool agents/manifest.json >/dev/null
python3 -m json.tool scripts/project/src/tradecat_terminal/dataset_consumption_contract.json >/dev/null
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
python3 - "$TMP_DIR/datasets.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for dataset in payload.get("datasets") or []:
    contract = dataset.get("consumption_contract")
    if not isinstance(contract, dict):
        raise SystemExit(f"{dataset.get('key')}: missing consumption_contract")
    if contract.get("schema") != "tradecat.dataset_consumption_contract.v1":
        raise SystemExit(f"{dataset.get('key')}: invalid consumption contract schema")
PY

PYTHONPATH="$PROJECT_DIR/src" python3 scripts/project/scripts/validate_dataset_consumption_contract.py >/dev/null

bash scripts/run-tradecat.sh path event_stream --json >"$TMP_DIR/path.json"
json_expect "$TMP_DIR/path.json" "tradecat.path_map.v1"

bash scripts/run-tradecat.sh --cache-dir "$TMP_DIR/cache" init --json >"$TMP_DIR/init.json"
json_expect "$TMP_DIR/init.json" "tradecat.init.v1"

bash scripts/run-tradecat.sh --cache-dir "$TMP_DIR/cache" doctor --json >"$TMP_DIR/doctor.json"
json_expect "$TMP_DIR/doctor.json" "tradecat.doctor.v1"

bash scripts/run-tradecat.sh config show --json >"$TMP_DIR/config.json"
json_expect "$TMP_DIR/config.json" "tradecat.config.v1"

bash scripts/run-tradecat.sh --cache-dir "$TMP_DIR/cache" prune --json >"$TMP_DIR/prune.json"
json_expect "$TMP_DIR/prune.json" "tradecat.prune_result.v1"

set +e
bash scripts/run-tradecat.sh --cache-dir "$TMP_DIR/cache" analyze --json >"$TMP_DIR/analyze-empty.json"
analyze_exit_code=$?
set -e
if [[ "$analyze_exit_code" -ne 1 ]]; then
  echo "agent-smoke: empty analysis cache returned exit $analyze_exit_code" >&2
  exit 1
fi
json_expect "$TMP_DIR/analyze-empty.json" "tradecat.analysis_report.v1"
json_expect_error_code "$TMP_DIR/analyze-empty.json" "empty_analysis_cache"

set +e
bash scripts/run-tradecat.sh --cache-dir "$TMP_DIR/cache" features --json >"$TMP_DIR/features-empty.json"
features_exit_code=$?
set -e
if [[ "$features_exit_code" -ne 1 ]]; then
  echo "agent-smoke: empty feature cache returned exit $features_exit_code" >&2
  exit 1
fi
json_expect "$TMP_DIR/features-empty.json" "tradecat.feature_bundle.v1"
json_expect_error_code "$TMP_DIR/features-empty.json" "empty_feature_cache"

bash scripts/run-tradecat.sh --cache-dir "$TMP_DIR/cache" probe event_stream --json --no-write >"$TMP_DIR/probe.json"
json_expect "$TMP_DIR/probe.json" "tradecat.probe_result.v1"

bash scripts/run-tradecat.sh --cache-dir "$TMP_DIR/cache" probe --json --no-write >"$TMP_DIR/probe-all.json"
json_expect "$TMP_DIR/probe-all.json" "tradecat.probe_results.v1"

set +e
TRADECAT_TERMINAL_RUNTIME_DIR="$TMP_DIR/run" \
TRADECAT_CACHE_DIR="$TMP_DIR/cache" \
bash scripts/project/scripts/start.sh status --json >"$TMP_DIR/watch-status.json"
watch_status_exit_code=$?
set -e
if [[ "$watch_status_exit_code" -ne 1 ]]; then
  echo "agent-smoke: stopped watch status returned exit $watch_status_exit_code" >&2
  exit 1
fi
json_expect "$TMP_DIR/watch-status.json" "tradecat.watch_status.v1"
json_expect_error_code "$TMP_DIR/watch-status.json" "watch_not_running"

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
json_expect_error_code "$TMP_DIR/invalid.json" "invalid_dataset_key"

set +e
TRADECAT_CACHE_COMPRESSION=bad \
TRADECAT_AGENT_SMOKE_CACHE="$TMP_DIR/config-cache" \
PYTHONPATH="$PROJECT_DIR/src" \
python3 - <<'PY' >"$TMP_DIR/config-error.json"
import os

from tradecat_terminal import cli
import tradecat_terminal.cache as cache_module


def fake_fetch_csv_body(url, *, timeout=30.0):
    return "\n".join(
        [
            "https://example.invalid/market",
            "数据源,market",
            "排名,交易对,价格",
            "1,BTCUSDT,100",
        ]
    )


cache_module.fetch_csv_body = fake_fetch_csv_body
raise SystemExit(
    cli.main(
        [
            "--cache-dir",
            os.environ["TRADECAT_AGENT_SMOKE_CACHE"],
            "sync",
            "market_snapshot",
            "--json",
        ]
    )
)
PY
config_exit_code=$?
set -e
if [[ "$config_exit_code" -ne 2 ]]; then
  echo "agent-smoke: invalid runtime configuration returned exit $config_exit_code" >&2
  exit 1
fi
json_expect "$TMP_DIR/config-error.json" "tradecat.sync_result.v1"
json_expect_error_code "$TMP_DIR/config-error.json" "invalid_runtime_configuration"

echo "agent-smoke: ok"
