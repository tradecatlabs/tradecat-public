from __future__ import annotations

import json
import subprocess
from pathlib import Path

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_PACKAGE_ROOT = REPO_ROOT / "skills" / "tradecat-public"

REQUEST_SCHEMA_FILES = {
    "tradecat-request-result.schema.json": "tradecat.request_result.v1",
    "tradecat-request-dataset-list.schema.json": "tradecat.request_dataset_list.v1",
}

RESOURCE_SCHEMA_FILES = {
    "tradecat-dataset-consumption-contract.schema.json": "tradecat.dataset_consumption_contract.v1",
    "tradecat-agent-market-context-sources.schema.json": "tradecat.agent_market_context_sources.v1",
}

AUTO_SCHEMA_FILES = {
    "tradecat-auto-agent-market-context.schema.json": "tradecat_auto.agent_market_context.v1",
    "tradecat-auto-agent-market-context-audit.schema.json": "tradecat_auto.agent_market_context_audit.v1",
    "tradecat-auto-agent-research-cycle.schema.json": "tradecat_auto.agent_research_cycle.v1",
    "tradecat-auto-agent-soft-layer.schema.json": "tradecat_auto.agent_soft_layer.v1",
    "tradecat-auto-agent-trade-thesis.schema.json": "tradecat_auto.agent_trade_thesis.v1",
    "tradecat-auto-audited-intent-handoff.schema.json": "tradecat_auto.audited_intent_handoff.v1",
    "tradecat-auto-audit-journal-summary.schema.json": "tradecat_auto.audit_journal_summary.v1",
    "tradecat-auto-audit-journal-write.schema.json": "tradecat_auto.audit_journal_write.v1",
    "tradecat-auto-daily-paper-report.schema.json": "tradecat_auto.daily_paper_report.v1",
    "tradecat-auto-decision-quality-report.schema.json": "tradecat_auto.decision_quality_report.v1",
    "tradecat-auto-decision-trace-report.schema.json": "tradecat_auto.decision_trace_report.v1",
    "tradecat-auto-latest-cycle-report.schema.json": "tradecat_auto.latest_cycle_report.v1",
    "tradecat-auto-latest-decision-report.schema.json": "tradecat_auto.latest_decision_report.v1",
    "tradecat-auto-market-universe.schema.json": "tradecat_auto.market_universe.v1",
    "tradecat-auto-paper-account-state.schema.json": "tradecat_auto.paper_account_state.v1",
    "tradecat-auto-paper-autonomy-profile.schema.json": "tradecat_auto.paper_autonomy_profile.v1",
    "tradecat-auto-paper-backtest-report.schema.json": "tradecat_auto.paper_backtest_report.v1",
    "tradecat-auto-paper-execution-cost-model.schema.json": "tradecat_auto.paper_execution_cost_model.v1",
    "tradecat-auto-paper-ops-report.schema.json": "tradecat_auto.paper_ops_report.v1",
    "tradecat-auto-paper-report.schema.json": "tradecat_auto.paper_report.v1",
    "tradecat-auto-paper-service-status.schema.json": "tradecat_auto.paper_service_status.v1",
    "tradecat-auto-paper-web-monitor-decision-text.schema.json": "tradecat_auto.paper_web_monitor_decision_text.v1",
    "tradecat-auto-paper-web-monitor-snapshot.schema.json": "tradecat_auto.paper_web_monitor_snapshot.v1",
    "tradecat-auto-portfolio-risk-policy.schema.json": "tradecat_auto.portfolio_risk_policy.v1",
    "tradecat-auto-position-management-action-report.schema.json": "tradecat_auto.position_management_action_report.v1",
    "tradecat-auto-position-management-thesis.schema.json": "tradecat_auto.position_management_thesis.v1",
    "tradecat-auto-production-health.schema.json": "tradecat_auto.production_health.v1",
    "tradecat-auto-public-market-bundle-batch.schema.json": "tradecat_auto.public_market_bundle_batch.v1",
    "tradecat-auto-public-market-snapshot.schema.json": "tradecat_auto.public_market_snapshot.v1",
    "tradecat-auto-public-probe.schema.json": "tradecat_auto.public_probe.v1",
    "tradecat-auto-replay-report.schema.json": "tradecat_auto.replay_report.v1",
    "tradecat-auto-run-once-report.schema.json": "tradecat_auto.run_once_report.v1",
    "tradecat-auto-service-cycle.schema.json": "tradecat_auto.service_cycle.v1",
    "tradecat-auto-strategy-review-report.schema.json": "tradecat_auto.strategy_review_report.v1",
    "tradecat-auto-strategy-state.schema.json": "tradecat_auto.strategy_state.v1",
    "tradecat-auto-telegram-alerts.schema.json": "tradecat_auto.telegram_alerts.v1",
}

AGGREGATE_SCHEMA_FILES = {
    "tradecat-auto-source-payload.schema.json": {
        "tradecat_auto.sheet_events.v1",
        "tradecat_auto.signal_flow_events.v1",
        "tradecat_auto.anomaly_symbols.v1",
        "tradecat_auto.signal_events.v1",
        "tradecat_auto.anomaly_signal_events.v1",
        "tradecat_auto.source_error.v1",
    }
}


def test_agent_manifest_is_canonical_machine_contract():
    payload = _manifest()

    assert payload["schema"] == "tradecat.agent_manifest.v1"
    assert payload["schema_version"] == "1.0.0"
    assert payload["project_root"] == "."
    assert payload["default_workdir"] == "."
    assert payload["skill_root"] == "skills/tradecat-public"
    assert payload["important_paths"]["project_readme"] == "README.md"
    assert payload["safe_order_of_operations"][0] == "read skills/tradecat-public/agents/manifest.json"


def test_agent_manifest_validates_against_formal_schema():
    schema = json.loads((REPO_ROOT / "contracts" / "tradecat-agent-manifest.schema.json").read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(_manifest()), key=lambda error: list(error.path))

    assert errors == []


def test_skill_package_governance_is_agent_runtime_focused():
    governance = _manifest()["skill_package_governance"]

    assert governance["shape"] == "project_with_embedded_hermes_skill"
    assert governance["canonical_machine_contract"] == "skills/tradecat-public/agents/manifest.json"
    assert governance["implementation_project_root"] == "."
    assert governance["no_second_truth"] is True
    assert "src/tradecat_terminal" in governance["forbidden_root_paths"]
    assert {".runtime/**", ".hermes/**", ".venv/**", "project/**", "tasks/**"} <= set(governance["local_runtime_paths"])
    assert "paper/watch" in governance["safety_boundary"]


def test_retired_terminal_paths_are_not_tracked():
    tracked = set(
        subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.splitlines()
    )

    assert not any(path.startswith("src/tradecat_terminal/") for path in tracked)
    assert "install.sh" not in tracked
    assert "scripts/start.sh" not in tracked
    assert "scripts/watchdog.sh" not in tracked
    assert not (REPO_ROOT / "src" / "tradecat_terminal").exists()


def test_manifest_important_static_paths_exist_and_runtime_paths_are_local_only():
    payload = _manifest()

    for key, value in payload["important_paths"].items():
        if ".runtime" in value or "*" in value:
            continue
        assert (REPO_ROOT / value).exists(), f"{key}: {value}"

    assert payload["important_paths"]["dataset_registry"] == "src/tradecat_sources/dataset_registry.json"
    assert payload["important_paths"]["automation_runtime"].startswith(".runtime/")


def test_agent_role_profiles_are_soft_paper_only_configs():
    payload = _manifest()
    roles = {item["id"]: item for item in payload["agent_role_profiles"]}
    trader = roles["discretionary_futures_trader"]

    assert trader["kind"] == "paper_research_trader_profile"
    assert trader["path"] == payload["important_paths"]["agent_soft_layer_trader_profile"]
    assert (REPO_ROOT / trader["path"]).exists()
    assert trader["bundle_command"] == "bash scripts/run-tradecat.sh soft-layer --json"
    assert trader["real_orders"] is False
    assert trader["signed_requests"] is False
    assert trader["reads_api_keys"] is False


def test_manifest_advertises_agent_runtime_entrypoints_only():
    payload = _manifest()
    readonly = {item["command"] for item in payload["preferred_readonly_entrypoints"]}
    mutating = {item["command"] for item in payload["preferred_mutating_entrypoints"]}

    assert "python3 scripts/request.py signal_flow --format json --limit 5" in readonly
    assert "bash scripts/binance-public-snapshot.sh --symbols BTCUSDT,ETHUSDT --json" in readonly
    assert "bash scripts/binance-public-bundle.sh --symbols BTCUSDT,ETHUSDT --json" in readonly
    assert "bash scripts/run-tradecat.sh agent-market-context --symbol BTCUSDT --json" in readonly
    assert "bash scripts/run-tradecat.sh soft-layer --json" in readonly
    assert "bash scripts/run-tradecat.sh latest-decision --json" in readonly
    assert (
        "bash scripts/run-tradecat.sh strategy-review --ledger-path .runtime/auto-paper/paper_ledger.json --archive-path .runtime/auto-paper/cycles.jsonl --json"
        in readonly
    )
    assert "bash scripts/run-tradecat.sh context-audit --input /path/to/agent-market-context.json --json" in readonly
    assert (
        "bash scripts/run-tradecat.sh run-context --input /path/to/agent-market-context.json --mode paper --json"
        in mutating
    )
    assert "bash scripts/start-auto-paper.sh start --json" in mutating
    assert not any("tradecat tui" in item or "scripts/start.sh" in item for item in readonly | mutating)


def test_manifest_never_advertises_real_order_capability():
    findings: list[str] = []

    def walk(value: object, path: str) -> None:
        if isinstance(value, dict):
            for key in ("real_orders", "signed_requests", "reads_api_keys"):
                if value.get(key) is not None and value.get(key) is not False:
                    findings.append(f"{path}.{key}={value.get(key)!r}")
            for key, child in value.items():
                walk(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")

    walk(_manifest(), "manifest")

    assert findings == []


def test_automation_output_contracts_have_formal_schemas():
    payload = _manifest()
    automation_schemas = {item["schema"] for item in payload.get("automation_output_contracts", [])}

    assert automation_schemas <= set(AUTO_SCHEMA_FILES.values())
    assert "tradecat_auto.paper_service_status.v1" in automation_schemas
    assert "tradecat_auto.agent_market_context_audit.v1" in automation_schemas
    assert "tradecat_auto.run_once_report.v1" in automation_schemas
    for item in payload.get("automation_output_contracts", []):
        schema_file = item.get("schema_file")
        if not schema_file:
            continue
        schema_path = REPO_ROOT / schema_file
        assert schema_path.exists()
        schema_payload = json.loads(schema_path.read_text(encoding="utf-8"))
        assert schema_payload["properties"]["schema"]["const"] == item["schema"]


def test_manifest_json_outputs_advertise_source_payload_contracts():
    payload = _manifest()
    json_outputs = payload.get("json_outputs", [])
    output_schemas = {item["schema"] for item in json_outputs}

    assert AGGREGATE_SCHEMA_FILES["tradecat-auto-source-payload.schema.json"] <= output_schemas
    for item in json_outputs:
        if item.get("schema_file") != "contracts/tradecat-auto-source-payload.schema.json":
            continue
        schema_path = REPO_ROOT / item["schema_file"]
        schema_payload = json.loads(schema_path.read_text(encoding="utf-8"))
        assert item["schema"] in set(schema_payload["properties"]["schema"]["enum"])
        assert item["real_orders"] is False
        assert item["signed_requests"] is False
        assert item["reads_api_keys"] is False


def test_manifest_json_outputs_have_existing_schema_files_and_safe_flags():
    payload = _manifest()

    for item in payload.get("json_outputs", []):
        schema = item["schema"]
        schema_path = REPO_ROOT / item["schema_file"]
        assert schema_path.exists(), f"{schema}: missing {schema_path}"

        schema_payload = json.loads(schema_path.read_text(encoding="utf-8"))
        assert _schema_payload_accepts_schema(schema_payload, schema), f"{schema}: not declared by {schema_path.name}"

        if schema.startswith("tradecat_auto."):
            assert item["real_orders"] is False
            assert item["signed_requests"] is False
            assert item["reads_api_keys"] is False


def test_formal_contract_schemas_are_valid_json():
    schemas = sorted((REPO_ROOT / "contracts").glob("*.schema.json"))

    assert {path.name for path in schemas} == {
        "tradecat-agent-manifest.schema.json",
        "tradecat-command-envelope.schema.json",
        "tradecat-error.schema.json",
        *REQUEST_SCHEMA_FILES,
        *RESOURCE_SCHEMA_FILES,
        *AUTO_SCHEMA_FILES,
        *AGGREGATE_SCHEMA_FILES,
    }
    for path in schemas:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_schema_files_pin_expected_payload_schema_names():
    for filename, expected_schema in {**REQUEST_SCHEMA_FILES, **RESOURCE_SCHEMA_FILES, **AUTO_SCHEMA_FILES}.items():
        payload = json.loads((REPO_ROOT / "contracts" / filename).read_text(encoding="utf-8"))
        properties = payload.get("properties", {})

        assert properties["schema"]["const"] == expected_schema
        assert properties["schema_version"]["const"] == "1.0.0"
    for filename, expected_schemas in AGGREGATE_SCHEMA_FILES.items():
        payload = json.loads((REPO_ROOT / "contracts" / filename).read_text(encoding="utf-8"))
        properties = payload.get("properties", {})

        assert set(properties["schema"]["enum"]) == expected_schemas
        assert properties["schema_version"]["const"] == "1.0.0"


def _manifest() -> dict:
    return json.loads((SKILL_PACKAGE_ROOT / "agents" / "manifest.json").read_text(encoding="utf-8"))


def _schema_payload_accepts_schema(payload: dict, schema: str) -> bool:
    schema_property = payload.get("properties", {}).get("schema", {})
    return schema_property.get("const") == schema or schema in set(schema_property.get("enum") or [])
