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
from tradecat_sources.dataset_contract import load_dataset_consumption_contract

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = PROJECT_ROOT / "contracts"
REQUEST_SCRIPT = PROJECT_ROOT / "scripts" / "request.py"
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
                        "safety": {"real_orders": False, "signed_requests": False, "reads_api_keys": False},
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
                            "safety": {"real_orders": False, "signed_requests": False, "reads_api_keys": False},
                        },
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
        "tradecat_auto.replay_report.v1": "tradecat-auto-replay-report.schema.json",
        "tradecat_auto.daily_paper_report.v1": "tradecat-auto-daily-paper-report.schema.json",
        "tradecat_auto.latest_cycle_report.v1": "tradecat-auto-latest-cycle-report.schema.json",
        "tradecat_auto.latest_decision_report.v1": "tradecat-auto-latest-decision-report.schema.json",
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
