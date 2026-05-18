#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_DIR="$ROOT_DIR/skills/tradecat-public"
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

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected = sys.argv[2]
if payload.get("schema") != expected:
    raise SystemExit(f"{sys.argv[1]}: schema {payload.get('schema')!r} != {expected!r}")
if payload.get("schema_version") != "1.0.0":
    raise SystemExit(f"{sys.argv[1]}: missing schema_version=1.0.0")
if payload.get("ok") is False and not isinstance(payload.get("error"), dict):
    raise SystemExit(f"{sys.argv[1]}: ok=false without error object")
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
error = payload.get("error") or {}
if payload.get("ok") is not False:
    raise SystemExit(f"{sys.argv[1]}: expected ok=false")
if error.get("code") != sys.argv[2]:
    raise SystemExit(f"{sys.argv[1]}: error.code {error.get('code')!r} != {sys.argv[2]!r}")
PY
}

cd "$ROOT_DIR"

bash scripts/validate-skill.sh --strict >/dev/null
python3 -m json.tool "$SKILL_DIR/agents/manifest.json" >/dev/null
python3 -m json.tool src/tradecat_sources/dataset_consumption_contract.json >/dev/null
python3 -m json.tool src/tradecat_sources/dataset_registry.json >/dev/null
for schema_file in contracts/*.schema.json; do
  python3 -m json.tool "$schema_file" >/dev/null
done

if ! PYTHONPATH="$ROOT_DIR/src" python3 - <<'PY' >/dev/null 2>&1
import tradecat_auto.cli
import tradecat_sources.registry
PY
then
  bash scripts/bootstrap-dev.sh >/dev/null
fi

PYTHONPATH="$ROOT_DIR/src" python3 scripts/validate_dataset_consumption_contract.py >/dev/null
PYTHONPATH="$ROOT_DIR/src" python3 scripts/validate_agent_market_context_resources.py >/dev/null

TRADECAT_REQUEST_REGISTRY_URL="$(python3 - "$ROOT_DIR/src/tradecat_sources/dataset_registry.json" <<'PY'
import sys
from pathlib import Path

print(Path(sys.argv[1]).resolve().as_uri())
PY
)" python3 scripts/request.py --datasets --format json >"$TMP_DIR/request-datasets.json"
json_expect "$TMP_DIR/request-datasets.json" "tradecat.request_dataset_list.v1"

set +e
TRADECAT_REQUEST_REGISTRY_URL="$(python3 - "$ROOT_DIR/src/tradecat_sources/dataset_registry.json" <<'PY'
import sys
from pathlib import Path

print(Path(sys.argv[1]).resolve().as_uri())
PY
)" python3 scripts/request.py missing --format json >"$TMP_DIR/request-invalid.json"
request_invalid_code=$?
set -e
if [[ "$request_invalid_code" -eq 0 ]]; then
  echo "agent-smoke: invalid request dataset returned exit 0" >&2
  exit 1
fi
json_expect "$TMP_DIR/request-invalid.json" "tradecat.request_result.v1"
json_expect_error_code "$TMP_DIR/request-invalid.json" "invalid_request"

bash scripts/run-tradecat.sh paper-report --ledger-path "$TMP_DIR/paper-ledger.json" --json >"$TMP_DIR/auto-paper-report.json"
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
        "source_manifest": "resources/agent_market_context/binance/provenance.manifest.json",
    },
    "source_event": {"event_id": "smoke-event", "content": "IRYS 异动"},
    "anomaly_symbol": {
        "raw_symbol": "IRYS",
        "normalized_symbol": "IRYSUSDT",
        "source_values": {"交易对": "IRYS", "5m量变化率": "1.2%", "5m额变化率": "3.4%"},
    },
    "agent_trade_thesis": {
        "schema": "tradecat_auto.agent_trade_thesis.v1",
        "schema_version": "1.0.0",
        "ok": True,
        "symbol": "IRYSUSDT",
        "mode": "paper_research",
        "direction": "LONG",
        "confidence": 0.72,
        "holding_horizon": "intraday",
        "entry_context": {
            "reference_price": 0.062,
            "price_source": "agent_supplied_mark_price",
            "not_order_instruction": True,
        },
        "paper_intent": {
            "allow_tradecat_paper_gate_to_decide": True,
            "requested_margin_usdt": 7.5,
            "paper_leverage": 3.0,
            "real_order": False,
        },
        "invalidation_price": 0.058,
        "take_profit_price": 0.068,
        "max_holding_minutes": 120,
        "exit_rationale": "Agent smoke fixture exit plan; paper/watch only.",
        "rationale": "Synthetic public-readonly market context for local smoke validation.",
        "risk_notes": ["synthetic fixture; not investment advice"],
        "limitations": ["paper/watch only; no Binance key; no real order"],
        "provenance": {"source": "agent-smoke synthetic fixture"},
        "safety": {"real_orders": False, "signed_requests": False, "reads_api_keys": False},
    },
    "market_data": [
        {"family": "24h_ticker", "endpoint": "/fapi/v1/ticker/24hr", "method": "GET", "ok": True, "provenance": {"source": "binance_public_rest"}, "data": {"symbol": "IRYSUSDT", "lastPrice": "0.062", "priceChangePercent": "24", "quoteVolume": "50000000"}},
        {"family": "order_book_depth", "endpoint": "/fapi/v1/depth", "method": "GET", "ok": True, "provenance": {"source": "binance_public_rest"}, "data": {"bids": [["0.06199", "100"]], "asks": [["0.06201", "120"]]}},
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
        "signal": {"schema": "tradecat_auto.signal_score.v1", "ok": True, "symbol": "IRYSUSDT", "direction": "LONG", "positive_factors": ["large_24h_price_move"], "do_not_trade_reasons": []},
        "strategy_intent": {"schema": "tradecat_auto.strategy_intent.v1", "ok": True, "symbol": "IRYSUSDT", "action": "ENTER", "direction": "LONG", "strategy_tags": ["momentum_breakout"]},
        "risk_decision": {"schema": "tradecat_auto.risk_decision.v1", "ok": True, "decision": "ALLOW", "reasons": []},
        "paper_execution": {"schema": "tradecat_auto.paper_execution_report.v1", "ok": True, "status": "OPENED", "symbol": "IRYSUSDT", "side": "LONG", "notional_usdt": 22.5},
    },
}
(base / "cycles.jsonl").write_text(json.dumps(cycle, ensure_ascii=False) + "\n", encoding="utf-8")
(base / "paper-ledger-complete.json").write_text(json.dumps({"schema": "tradecat_auto.paper_ledger.v1", "initial_balance_usdt": 1000.0, "cash_balance_usdt": 1003.0, "equity_usdt": 1003.0, "realized_pnl_usdt": 3.0, "unrealized_pnl_usdt": 0.0, "open_positions": {}, "closed_positions": [{"net_pnl_usdt": 3.0}], "fills": [{}], "applied_execution_ids": [], "ignored_execution_ids": [], "equity_curve": [{"equity_usdt": 1000.0}, {"equity_usdt": 1003.0}]}), encoding="utf-8")
PY

bash scripts/run-tradecat.sh context-audit --input "$TMP_DIR/agent-context.json" --json >"$TMP_DIR/context-audit.json"
json_expect "$TMP_DIR/context-audit.json" "tradecat_auto.agent_market_context_audit.v1"

bash scripts/run-tradecat.sh run-context \
  --input "$TMP_DIR/agent-context.json" \
  --mode paper \
  --agent-margin-usdt 7.5 \
  --paper-leverage 3.0 \
  --ledger-path "$TMP_DIR/run-context-ledger.json" \
  --archive-path "$TMP_DIR/run-context-cycles.jsonl" \
  --journal-path "$TMP_DIR/run-context-audit.sqlite3" \
  --json >"$TMP_DIR/run-context.json"
json_expect "$TMP_DIR/run-context.json" "tradecat_auto.run_once_report.v1"

bash scripts/run-tradecat.sh replay-report --archive-path "$TMP_DIR/cycles.jsonl" --ledger-path "$TMP_DIR/paper-ledger-complete.json" --json >"$TMP_DIR/replay-report.json"
json_expect "$TMP_DIR/replay-report.json" "tradecat_auto.replay_report.v1"

set +e
TRADECAT_AUTO_PAPER_RUNTIME_DIR="$TMP_DIR/auto-paper" \
bash scripts/start-auto-paper.sh status --json >"$TMP_DIR/auto-paper-status.json"
auto_status_exit_code=$?
set -e
if [[ "$auto_status_exit_code" -ne 1 ]]; then
  echo "agent-smoke: stopped auto paper status returned exit $auto_status_exit_code" >&2
  exit 1
fi
json_expect "$TMP_DIR/auto-paper-status.json" "tradecat_auto.paper_service_status.v1"
json_expect_error_code "$TMP_DIR/auto-paper-status.json" "paper_service_not_running"

echo "agent-smoke: ok"
