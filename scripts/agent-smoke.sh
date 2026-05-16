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
PYTHONPATH="$PROJECT_DIR/src" python3 scripts/project/scripts/validate_agent_market_context_resources.py >/dev/null

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

bash scripts/run-tradecat.sh auto paper-report --ledger-path "$TMP_DIR/paper-ledger.json" --json >"$TMP_DIR/auto-paper-report.json"
json_expect "$TMP_DIR/auto-paper-report.json" "tradecat_auto.paper_report.v1"

python3 - "$TMP_DIR" <<'PY'
import json
import sys
from pathlib import Path

base = Path(sys.argv[1])
context = {
    "schema": "tradecat_auto.agent_market_context.v1",
    "schema_version": "1.0.0",
    "symbol": "IRYSUSDT",
    "mode": "public_readonly",
    "provenance": {
        "agent": "agent-smoke",
        "source_manifest": "scripts/project/resources/agent_market_context/binance/provenance.manifest.json",
    },
    "source_event": {"event_id": "smoke-event", "content": "IRYS 异动"},
    "anomaly_symbol": {
        "raw_symbol": "IRYS",
        "normalized_symbol": "IRYSUSDT",
        "source_values": {"交易对": "IRYS", "5m量变化率": "1.2%", "5m额变化率": "3.4%"},
    },
    "market_data": [
        {"family": "24h_ticker", "endpoint": "/fapi/v1/ticker/24hr", "method": "GET", "ok": True, "provenance": {"source": "binance_public_rest"}, "data": {"symbol": "IRYSUSDT", "lastPrice": "0.062", "priceChangePercent": "24", "quoteVolume": "50000000"}},
        {"family": "order_book_depth", "endpoint": "/fapi/v1/depth", "method": "GET", "ok": True, "provenance": {"source": "binance_public_rest"}, "data": {"bids": [["0.0619", "100"]], "asks": [["0.0621", "120"]]}},
        {"family": "open_interest", "endpoint": "/fapi/v1/openInterest", "method": "GET", "ok": True, "provenance": {"source": "binance_public_rest"}, "data": {"openInterest": "1000000"}},
        {"family": "open_interest_history", "endpoint": "/futures/data/openInterestHist", "method": "GET", "ok": True, "provenance": {"source": "binance_public_rest"}, "data": [{"sumOpenInterestValue": "100000"}]},
        {"family": "funding_rate", "endpoint": "/fapi/v1/fundingRate", "method": "GET", "ok": True, "provenance": {"source": "binance_public_rest"}, "data": [{"fundingRate": "0.00005"}]},
        {"family": "premium_index", "endpoint": "/fapi/v1/premiumIndex", "method": "GET", "ok": True, "provenance": {"source": "binance_public_rest"}, "data": {"markPrice": "0.062", "indexPrice": "0.0619"}},
        {"family": "long_short_ratios", "endpoint": "/futures/data/globalLongShortAccountRatio", "method": "GET", "ok": True, "provenance": {"source": "binance_public_rest"}, "data": [{"longShortRatio": "1.1"}]},
        {"family": "taker_buy_sell_volume", "endpoint": "/futures/data/takerlongshortRatio", "method": "GET", "ok": True, "provenance": {"source": "binance_public_rest"}, "data": [{"buySellRatio": "1.2"}]},
    ],
}
(base / "agent-context.json").write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")
cycle = {
    "schema": "tradecat_auto.service_cycle.v1",
    "schema_version": "1.0.0",
    "action": "PROCESSED",
    "ok": True,
    "latest_event": {"event_id": "smoke-event", "source_time_bj": "2026-05-15 18:00:00", "content": "IRYS 异动"},
    "pipeline_report": {
        "schema": "tradecat_auto.run_once_report.v1",
        "schema_version": "1.0.0",
        "ok": True,
        "selected_symbol": "IRYSUSDT",
        "latest_event": {"event_id": "smoke-event", "content": "IRYS 异动"},
        "signal": {"schema": "tradecat_auto.signal_score.v1", "ok": True, "symbol": "IRYSUSDT", "direction": "LONG", "positive_factors": ["large_24h_price_move", "taker_buy_bias"], "do_not_trade_reasons": []},
        "strategy_intent": {"schema": "tradecat_auto.strategy_intent.v1", "ok": True, "symbol": "IRYSUSDT", "action": "ENTER", "direction": "LONG", "strategy_tags": ["momentum_breakout", "taker_flow_bias"], "explanation": {"positive_factors": ["large_24h_price_move", "taker_buy_bias"]}},
        "risk_decision": {"schema": "tradecat_auto.risk_decision.v1", "ok": True, "decision": "ALLOW", "reasons": []},
        "paper_execution": {"schema": "tradecat_auto.paper_execution_report.v1", "ok": True, "status": "OPENED", "symbol": "IRYSUSDT", "side": "LONG", "notional_usdt": 12.0},
    },
}
(base / "cycle.json").write_text(json.dumps(cycle, ensure_ascii=False), encoding="utf-8")
(base / "cycles.jsonl").write_text(json.dumps(cycle, ensure_ascii=False) + "\n", encoding="utf-8")
(base / "paper-ledger-complete.json").write_text(json.dumps({"schema": "tradecat_auto.paper_ledger.v1", "initial_balance_usdt": 1000.0, "cash_balance_usdt": 1003.0, "equity_usdt": 1003.0, "realized_pnl_usdt": 3.0, "unrealized_pnl_usdt": 0.0, "open_positions": {}, "closed_positions": [{"net_pnl_usdt": 3.0}], "fills": [{}], "applied_execution_ids": [], "ignored_execution_ids": [], "equity_curve": [{"equity_usdt": 1000.0}, {"equity_usdt": 1003.0}]}), encoding="utf-8")
PY

bash scripts/run-tradecat.sh auto context-audit --input "$TMP_DIR/agent-context.json" --json >"$TMP_DIR/context-audit.json"
json_expect "$TMP_DIR/context-audit.json" "tradecat_auto.agent_market_context_audit.v1"

bash scripts/run-tradecat.sh auto run-context --input "$TMP_DIR/agent-context.json" --mode paper --agent-margin-usdt 6 --paper-leverage 2 --paper-margin-budget-usdt 12 --json >"$TMP_DIR/run-context.json"
json_expect "$TMP_DIR/run-context.json" "tradecat_auto.run_once_report.v1"

bash scripts/run-tradecat.sh auto replay-report --archive-path "$TMP_DIR/cycles.jsonl" --ledger-path "$TMP_DIR/paper-ledger-complete.json" --json >"$TMP_DIR/replay-report.json"
json_expect "$TMP_DIR/replay-report.json" "tradecat_auto.replay_report.v1"


set +e
TRADECAT_AUTO_PAPER_RUNTIME_DIR="$TMP_DIR/auto-paper" \
bash scripts/project/scripts/start-auto-paper.sh status --json >"$TMP_DIR/auto-paper-status.json"
auto_status_exit_code=$?
set -e
if [[ "$auto_status_exit_code" -ne 1 ]]; then
  echo "agent-smoke: stopped auto paper status returned exit $auto_status_exit_code" >&2
  exit 1
fi
json_expect "$TMP_DIR/auto-paper-status.json" "tradecat_auto.paper_service_status.v1"
json_expect_error_code "$TMP_DIR/auto-paper-status.json" "paper_service_not_running"

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
