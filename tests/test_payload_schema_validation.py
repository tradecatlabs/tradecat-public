from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from tradecat_auto.paper_ledger import default_paper_ledger, save_paper_ledger
from tradecat_auto.pipeline import build_paper_pipeline_report
from tradecat_auto.tradecat_source import (
    anomaly_signal_events_payload,
    parse_anomaly_symbols,
    parse_event_stream_payload,
    parse_signal_flow_payload,
    signal_events_payload,
)
from tradecat_sources.dataset_contract import load_dataset_consumption_contract

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = PROJECT_ROOT / "contracts"
REQUEST_SCRIPT = PROJECT_ROOT / "scripts" / "request.py"
WEB_MONITOR_SCRIPT = PROJECT_ROOT / "scripts" / "serve-auto-paper-monitor.py"
REQUEST_REGISTRY_URL = "https://example.local/tradecat-registry.json"
SIGNAL_CSV = "时间(北京),交易对,周期,类型,内容\n2026-05-10 10:00:00,BTCUSDT,5分钟,量比放大,hello\n"
REQUEST_REGISTRY = {
    "workbooks": {"main": {"spreadsheet_id": "sheet-id", "description": "test workbook"}},
    "datasets": {
        "signal_flow": {
            "workbook_key": "main",
            "tab_name": "信号流",
            "gid": None,
            "description": "test signal dataset",
            "data_mode": "stream",
            "active": True,
        }
    },
}


def test_request_script_payloads_validate_against_formal_schemas(capsys, monkeypatch):
    request_module = _load_request_module()
    monkeypatch.setattr(request_module, "fetch_body", _fake_request_fetch)

    datasets = _run_request_json(
        request_module,
        capsys,
        ["--registry-url", REQUEST_REGISTRY_URL, "--datasets", "--format", "json"],
    )
    result = _run_request_json(
        request_module,
        capsys,
        ["signal_flow", "--registry-url", REQUEST_REGISTRY_URL, "--format", "json", "--limit", "1"],
    )

    validate_payload(datasets)
    validate_payload(result)


def test_advertised_automation_payloads_validate_against_formal_schemas(tmp_path):
    ledger_path = tmp_path / "paper_ledger.json"
    save_paper_ledger(ledger_path, default_paper_ledger(initial_balance_usdt=1000.0))
    archive_path = tmp_path / "cycles.jsonl"
    safety = {
        "public_readonly_market_data": True,
        "public_readonly": True,
        "paper_or_watch_only": True,
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "binance_account_state": False,
    }
    archive_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "schema": "tradecat_auto.service_cycle.v1",
                        "schema_version": "1.0.0",
                        "ok": False,
                        "action": "SKIPPED_NO_EVENT",
                        "reason": "no_signal_flow_available",
                        "error_code": "no_signal_flow_available",
                        "safety": safety,
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "schema": "tradecat_auto.service_cycle.v1",
                        "schema_version": "1.0.0",
                        "ok": True,
                        "action": "PROCESSED",
                        "latest_event": {"event_id": "evt-1", "symbol": "BTCUSDT"},
                        "pipeline_report": {
                            "schema": "tradecat_auto.run_once_report.v1",
                            "schema_version": "1.0.0",
                            "ok": True,
                            "selected_symbol": "BTCUSDT",
                            "risk_decision": {"decision": "ALLOW", "reasons": []},
                            "paper_execution": {"status": "OPENED", "side": "LONG"},
                            "safety": safety,
                        },
                        "safety": safety,
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payloads = [
        _run_auto_json(["soft-layer", "--json"]),
        _run_auto_json(["paper-report", "--ledger-path", str(ledger_path), "--json"]),
        _run_auto_json(
            ["replay-report", "--archive-path", str(archive_path), "--ledger-path", str(ledger_path), "--json"]
        ),
        _run_auto_json(["latest-cycle", "--archive-path", str(archive_path), "--json"]),
        _run_auto_json(["latest-decision", "--archive-path", str(archive_path), "--json"]),
        _run_auto_json(
            [
                "daily-report",
                "--archive-path",
                str(archive_path),
                "--ledger-path",
                str(ledger_path),
                "--date",
                "2026-05-10",
                "--json",
            ]
        ),
    ]

    for payload in payloads:
        validate_payload(payload)


def test_dataset_consumption_contract_validates_against_schema():
    validate_payload(load_dataset_consumption_contract())


def test_run_once_report_schema_validates_nested_agent_pipeline_contracts():
    payload = build_paper_pipeline_report(
        selected_symbol="BTCUSDT",
        anomaly_symbols={
            "schema": "tradecat_auto.anomaly_symbols.v1",
            "ok": True,
            "symbols": [
                {
                    "raw_symbol": "BTC",
                    "normalized_symbol": "BTCUSDT",
                    "source_dataset_key": "anomaly_panel",
                    "source_values": {"交易对": "BTC", "5m量变化率": "1.0%", "5m额变化率": "2.0%"},
                }
            ],
        },
        market_bundle={
            "schema": "tradecat_auto.public_market_bundle.v1",
            "ok": True,
            "symbol": "BTCUSDT",
            "ticker24hr": {"lastPrice": "100000", "priceChangePercent": "2.5", "quoteVolume": "100000000"},
            "depth_summary": {"spread_bps": 1.0, "best_bid": 99999.0, "best_ask": 100001.0},
            "openInterest": {"openInterest": "100000"},
            "openInterestHist": [{"sumOpenInterestValue": "10000000"}],
            "fundingRate": [{"fundingRate": "0.0001"}],
            "premiumIndex": {"markPrice": "100000", "indexPrice": "99990"},
            "topLongShortAccountRatio": [{"longShortRatio": "1.1"}],
            "topLongShortPositionRatio": [{"longShortRatio": "1.1"}],
            "globalLongShortAccountRatio": [{"longShortRatio": "1.1"}],
            "takerlongshortRatio": [{"buySellRatio": "1.1"}],
            "errors": {},
        },
        events={"events": [{"event_id": "evt-1", "symbol": "BTCUSDT"}]},
        requested_margin_usdt=10.0,
        paper_leverage=1.0,
        agent_trade_thesis={
            "schema": "tradecat_auto.agent_trade_thesis.v1",
            "schema_version": "1.0.0",
            "invalidation_price": 99000.0,
            "take_profit_price": 102000.0,
            "max_holding_minutes": 60,
            "exit_rationale": "schema validation fixture",
        },
    )
    safety = payload["safety"]
    payload["signal_flow_events"] = {
        "ok": True,
        "source_dataset_key": "signal_flow",
        "count": 1,
        "error_code": None,
        "provenance": {"source": "tradecat_auto.service.summarize_signal_flow_events"},
        "safety": safety,
    }
    payload["anomaly_symbols"] = {
        "ok": True,
        "source_dataset_key": "anomaly_panel",
        "count": 1,
        "error_code": None,
        "provenance": {"source": "tradecat_auto.service.summarize_anomaly_symbols"},
        "safety": safety,
    }

    validate_payload(payload)


def test_source_adapter_payloads_validate_against_formal_schema():
    event_stream = parse_event_stream_payload(
        {
            "schema": "tradecat.request_result.v1",
            "ok": True,
            "dataset_key": "event_stream",
            "rows": [{"时间(北京)": "2026-05-10 10:00:00", "内容": "BTCUSDT 波动"}],
        }
    )
    signal_flow = parse_signal_flow_payload(
        {
            "schema": "tradecat.request_result.v1",
            "ok": True,
            "dataset_key": "signal_flow",
            "rows": [
                {
                    "时间(北京)": "2026-05-10 10:00:00",
                    "交易对": "BTC",
                    "周期": "5分钟",
                    "类型": "量比放大",
                    "内容": "量比放大",
                }
            ],
        },
        tradable_symbols={"BTCUSDT"},
    )
    anomaly = parse_anomaly_symbols(
        {
            "schema": "tradecat.request_result.v1",
            "ok": True,
            "dataset_key": "anomaly_panel",
            "rows": [{"交易对": "BTC", "5m量变化率": "1.0%"}],
        },
        tradable_symbols={"BTCUSDT"},
    )
    combined = signal_events_payload(signal_flow, anomaly, selected_symbol="BTCUSDT")
    anomaly_events = anomaly_signal_events_payload(anomaly, selected_symbol="BTCUSDT")
    source_error = parse_event_stream_payload(
        {
            "schema": "tradecat.request_result.v1",
            "ok": False,
            "dataset_key": "event_stream",
            "error": {"code": "remote_http_status", "status": 404},
        }
    )
    direct_source_error = {
        "schema": "tradecat_auto.source_error.v1",
        "schema_version": "1.0.0",
        "ok": False,
        "error_code": "request_dataset_failed",
        "provenance": {"source": "unit_fixture"},
        "safety": {
            "public_readonly_market_data": True,
            "public_readonly": True,
            "paper_or_watch_only": True,
            "real_orders": False,
            "signed_requests": False,
            "reads_api_keys": False,
            "binance_account_state": False,
        },
    }

    for payload in (event_stream, signal_flow, anomaly, combined, anomaly_events, source_error, direct_source_error):
        validate_payload(payload)


def test_service_cycle_schema_validates_source_summaries():
    safety = {
        "public_readonly_market_data": True,
        "public_readonly": True,
        "paper_or_watch_only": True,
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "binance_account_state": False,
    }
    validate_payload(
        {
            "schema": "tradecat_auto.service_cycle.v1",
            "schema_version": "1.0.0",
            "ok": False,
            "action": "SKIPPED_NO_EVENT",
            "error_code": "no_signal_flow_available",
            "real_orders": False,
            "signed_requests": False,
            "reads_api_keys": False,
            "provenance": {"source": "tradecat_auto.service.run_service_cycle"},
            "safety": safety,
            "signal_flow_events": {
                "ok": False,
                "source_dataset_key": "signal_flow",
                "count": 0,
                "error_code": "no_signal_flow_available",
                "provenance": {"source": "tradecat_auto.service.summarize_signal_flow_events"},
                "safety": safety,
            },
            "anomaly_symbols": {
                "ok": True,
                "source_dataset_key": "anomaly_panel",
                "count": 0,
                "error_code": None,
                "provenance": {"source": "tradecat_auto.service.summarize_anomaly_symbols"},
                "safety": safety,
            },
            "source_snapshot": {
                "schema": "tradecat_auto.source_snapshot.v1",
                "schema_version": "1.0.0",
                "error_code": None,
                "source_snapshot_hash": "hash",
                "provenance": {"source": "tradecat_auto.service.source_snapshot"},
                "safety": safety,
            },
            "input_change": {
                "schema": "tradecat_auto.input_change.v1",
                "schema_version": "1.0.0",
                "error_code": None,
                "source_snapshot_changed": False,
                "provenance": {"source": "tradecat_auto.service.source_snapshot_delta"},
                "safety": safety,
            },
        }
    )


def test_web_monitor_payloads_validate_against_formal_schemas(tmp_path, monkeypatch):
    monitor = _load_web_monitor_module()

    def fake_run_json(command: list[str], *, runtime_dir: Path, timeout_seconds: float = 10.0) -> dict[str, Any]:
        del runtime_dir, timeout_seconds
        if command[:3] == ["bash", "scripts/start-auto-paper.sh", "status"]:
            return {
                "schema": "tradecat_auto.paper_service_status.v1",
                "schema_version": "1.0.0",
                "ok": True,
                "mode": "paper",
                "real_orders": False,
                "signed_requests": False,
                "reads_api_keys": False,
                "command": "auto-paper-service",
                "action": "status",
                "state": "running",
                "event": "running",
                "running": True,
                "runtime_dir": str(tmp_path),
                "health": "running_pid_verified",
                "process_health": "running_pid_verified",
                "_monitor_elapsed_ms": 1.0,
                "health_report_command": "bash scripts/start-auto-paper.sh health --json",
                "safety": {
                    "public_readonly_market_data": True,
                    "public_readonly": True,
                    "paper_or_watch_only": True,
                    "real_orders": False,
                    "signed_requests": False,
                    "reads_api_keys": False,
                    "binance_account_state": False,
                },
            }
        if command[:3] == ["bash", "scripts/start-auto-paper.sh", "health"]:
            return {
                "schema": "tradecat_auto.production_health.v1",
                "schema_version": "1.0.0",
                "ok": True,
                "status": "healthy",
                "_monitor_elapsed_ms": 2.0,
                "heartbeat": {"ok": True, "stale": False},
                "alerts": [],
                "safety": {
                    "public_readonly_market_data": True,
                    "public_readonly": True,
                    "paper_or_watch_only": True,
                    "real_orders": False,
                    "signed_requests": False,
                    "reads_api_keys": False,
                    "binance_account_state": False,
                },
            }
        return {"ok": True, "_monitor_elapsed_ms": 1.0}

    monkeypatch.setattr(monitor, "run_json", fake_run_json)

    decision = monitor.build_decision_text({})
    snapshot = monitor.build_snapshot(tmp_path)

    assert snapshot["monitor_command_elapsed_ms"]["status"] == 1.0
    validate_payload(decision)
    validate_payload(snapshot)


def test_tradecat_auto_safety_schemas_require_canonical_public_readonly_fields():
    required = {
        "public_readonly_market_data",
        "public_readonly",
        "paper_or_watch_only",
        "real_orders",
        "signed_requests",
        "reads_api_keys",
        "binance_account_state",
    }
    expected_consts = {
        "public_readonly_market_data": True,
        "public_readonly": True,
        "paper_or_watch_only": True,
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "binance_account_state": False,
    }
    safety_markers = {
        "public_readonly_market_data",
        "paper_or_watch_only",
        "real_orders",
        "signed_requests",
        "reads_api_keys",
    }
    checked = []

    def iter_safety_schemas(node: Any, location: str):
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict) and isinstance(properties.get("safety"), dict):
                yield location + ".properties.safety", properties["safety"]
            defs = node.get("$defs")
            if isinstance(defs, dict):
                for def_name, def_schema in defs.items():
                    if "safety" in str(def_name).lower() and isinstance(def_schema, dict):
                        yield f"{location}.$defs.{def_name}", def_schema
            for key, value in node.items():
                if key not in {"properties", "$defs"}:
                    yield from iter_safety_schemas(value, f"{location}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                yield from iter_safety_schemas(value, f"{location}[{index}]")

    for schema_path in sorted(CONTRACTS_DIR.glob("tradecat-auto-*.schema.json")):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        for location, safety_schema in iter_safety_schemas(schema, "$"):
            if "$ref" in safety_schema:
                continue
            properties = safety_schema.get("properties")
            if not isinstance(properties, dict) or not safety_markers.intersection(properties):
                continue
            checked.append(f"{schema_path.name}:{location}")
            assert required <= set(properties), f"{schema_path.name}:{location} missing safety properties"
            assert required <= set(safety_schema.get("required") or []), (
                f"{schema_path.name}:{location} missing required safety fields"
            )
            for key, expected in expected_consts.items():
                assert properties[key].get("const") is expected, (
                    f"{schema_path.name}:{location}.{key} must const {expected!r}"
                )

    assert checked, "no tradecat-auto safety schemas were checked"


def validate_payload(payload: dict[str, Any]) -> None:
    schema_name = _schema_name_for(payload)
    schema = json.loads((CONTRACTS_DIR / schema_name).read_text(encoding="utf-8"))
    registry = _schema_registry()
    validator = Draft202012Validator(schema, registry=registry)
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.path))
    assert errors == []


def _schema_name_for(payload: dict[str, Any]) -> str:
    schema = payload.get("schema")
    mapping = {
        "tradecat.request_dataset_list.v1": "tradecat-request-dataset-list.schema.json",
        "tradecat.request_result.v1": "tradecat-request-result.schema.json",
        "tradecat.dataset_consumption_contract.v1": "tradecat-dataset-consumption-contract.schema.json",
        "tradecat_auto.agent_soft_layer.v1": "tradecat-auto-agent-soft-layer.schema.json",
        "tradecat_auto.paper_report.v1": "tradecat-auto-paper-report.schema.json",
        "tradecat_auto.paper_web_monitor_decision_text.v1": "tradecat-auto-paper-web-monitor-decision-text.schema.json",
        "tradecat_auto.paper_web_monitor_snapshot.v1": "tradecat-auto-paper-web-monitor-snapshot.schema.json",
        "tradecat_auto.replay_report.v1": "tradecat-auto-replay-report.schema.json",
        "tradecat_auto.daily_paper_report.v1": "tradecat-auto-daily-paper-report.schema.json",
        "tradecat_auto.latest_cycle_report.v1": "tradecat-auto-latest-cycle-report.schema.json",
        "tradecat_auto.latest_decision_report.v1": "tradecat-auto-latest-decision-report.schema.json",
        "tradecat_auto.run_once_report.v1": "tradecat-auto-run-once-report.schema.json",
        "tradecat_auto.service_cycle.v1": "tradecat-auto-service-cycle.schema.json",
        "tradecat_auto.sheet_events.v1": "tradecat-auto-source-payload.schema.json",
        "tradecat_auto.signal_flow_events.v1": "tradecat-auto-source-payload.schema.json",
        "tradecat_auto.anomaly_symbols.v1": "tradecat-auto-source-payload.schema.json",
        "tradecat_auto.signal_events.v1": "tradecat-auto-source-payload.schema.json",
        "tradecat_auto.anomaly_signal_events.v1": "tradecat-auto-source-payload.schema.json",
        "tradecat_auto.source_error.v1": "tradecat-auto-source-payload.schema.json",
    }
    return mapping[str(schema)]


def _schema_registry() -> Registry:
    resources = []
    for path in CONTRACTS_DIR.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        if schema.get("$id"):
            resources.append((schema["$id"], Resource.from_contents(schema, default_specification=DRAFT202012)))
    return Registry().with_resources(resources)


def _load_request_module() -> object:
    spec = importlib.util.spec_from_file_location("tradecat_request_script", REQUEST_SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_web_monitor_module() -> object:
    spec = importlib.util.spec_from_file_location("tradecat_auto_web_monitor", WEB_MONITOR_SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _fake_request_fetch(url: str, *, timeout: float) -> str:
    del timeout
    if url == REQUEST_REGISTRY_URL:
        return json.dumps(REQUEST_REGISTRY)
    return SIGNAL_CSV


def _run_request_json(module: object, capsys: Any, args: list[str]) -> dict[str, Any]:
    assert module.main(args) == 0
    return json.loads(capsys.readouterr().out)


def _run_auto_json(args: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "tradecat_auto.cli", *args],
        cwd=PROJECT_ROOT,
        env={"PYTHONPATH": str(PROJECT_ROOT / "src")},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)
