from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[3]

REQUIRED_AGENT_JSON_SCHEMAS = {
    "tradecat.analysis_report.v1",
    "tradecat.feature_bundle.v1",
    "tradecat.status.v1",
    "tradecat.dataset_list.v1",
    "tradecat.request_dataset_list.v1",
    "tradecat.path_map.v1",
    "tradecat.sync_result.v1",
    "tradecat.request_result.v1",
    "tradecat.dataset_view.v1",
    "tradecat.probe_result.v1",
    "tradecat.watch_status.v1",
}

REQUIRED_FAILURE_CODES = {
    "invalid_dataset_key",
    "remote_timeout",
    "remote_http_status",
    "watch_not_running",
    "empty_analysis_cache",
    "empty_feature_cache",
    "invalid_analysis_request",
    "invalid_feature_request",
    "invalid_runtime_configuration",
    "local_runtime_error",
}

COMMAND_SCHEMA_FILES = {
    "tradecat-analysis-report.schema.json": "tradecat.analysis_report.v1",
    "tradecat-config.schema.json": "tradecat.config.v1",
    "tradecat-feature-bundle.schema.json": "tradecat.feature_bundle.v1",
    "tradecat-doctor.schema.json": "tradecat.doctor.v1",
    "tradecat-init.schema.json": "tradecat.init.v1",
    "tradecat-status.schema.json": "tradecat.status.v1",
    "tradecat-path-map.schema.json": "tradecat.path_map.v1",
    "tradecat-dataset-list.schema.json": "tradecat.dataset_list.v1",
    "tradecat-sync-result.schema.json": "tradecat.sync_result.v1",
    "tradecat-sync-results.schema.json": "tradecat.sync_results.v1",
    "tradecat-probe-result.schema.json": "tradecat.probe_result.v1",
    "tradecat-probe-results.schema.json": "tradecat.probe_results.v1",
    "tradecat-prune-result.schema.json": "tradecat.prune_result.v1",
    "tradecat-request-result.schema.json": "tradecat.request_result.v1",
    "tradecat-request-dataset-list.schema.json": "tradecat.request_dataset_list.v1",
    "tradecat-dataset-view.schema.json": "tradecat.dataset_view.v1",
    "tradecat-support-bundle.schema.json": "tradecat.support_bundle.v1",
    "tradecat-watch-status.schema.json": "tradecat.watch_status.v1",
}

RESOURCE_SCHEMA_FILES = {
    "tradecat-dataset-consumption-contract.schema.json": "tradecat.dataset_consumption_contract.v1",
    "tradecat-agent-market-context-sources.schema.json": "tradecat.agent_market_context_sources.v1",
}

AUTO_SCHEMA_FILES = {
    "tradecat-auto-agent-market-context.schema.json": "tradecat_auto.agent_market_context.v1",
    "tradecat-auto-agent-market-context-audit.schema.json": "tradecat_auto.agent_market_context_audit.v1",
    "tradecat-auto-agent-soft-layer.schema.json": "tradecat_auto.agent_soft_layer.v1",
    "tradecat-auto-agent-trade-thesis.schema.json": "tradecat_auto.agent_trade_thesis.v1",
    "tradecat-auto-audit-journal-summary.schema.json": "tradecat_auto.audit_journal_summary.v1",
    "tradecat-auto-audit-journal-write.schema.json": "tradecat_auto.audit_journal_write.v1",
    "tradecat-auto-daily-paper-report.schema.json": "tradecat_auto.daily_paper_report.v1",
    "tradecat-auto-paper-account-state.schema.json": "tradecat_auto.paper_account_state.v1",
    "tradecat-auto-paper-backtest-report.schema.json": "tradecat_auto.paper_backtest_report.v1",
    "tradecat-auto-paper-service-status.schema.json": "tradecat_auto.paper_service_status.v1",
    "tradecat-auto-production-health.schema.json": "tradecat_auto.production_health.v1",
    "tradecat-auto-replay-report.schema.json": "tradecat_auto.replay_report.v1",
    "tradecat-auto-telegram-alerts.schema.json": "tradecat_auto.telegram_alerts.v1",
}

INTERNAL_CLI_SCHEMA_ALLOWLIST = {
    "tradecat.watch_cycle.v1",
}


def test_agent_manifest_is_canonical_machine_contract():
    manifest_path = SKILL_ROOT / "agents" / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert payload["schema"] == "tradecat.agent_manifest.v1"
    assert payload["schema_version"] == "1.0.0"
    assert payload["project_root"] == "scripts/project"
    assert payload["default_workdir"] == "."
    assert payload["important_paths"]["project_readme"] == "scripts/project/README.md"
    assert payload["safe_order_of_operations"][0] == "read agents/manifest.json"


def test_manifest_advertises_required_agent_json_schemas():
    payload = json.loads((SKILL_ROOT / "agents" / "manifest.json").read_text(encoding="utf-8"))
    schemas = {item["schema"] for item in payload["json_outputs"]}

    assert REQUIRED_AGENT_JSON_SCHEMAS.issubset(schemas)


def test_manifest_json_output_records_are_unique_and_versioned():
    payload = json.loads((SKILL_ROOT / "agents" / "manifest.json").read_text(encoding="utf-8"))
    outputs = payload["json_outputs"]

    commands = [item["command"] for item in outputs]
    schemas = [item["schema"] for item in outputs]

    assert len(commands) == len(set(commands))
    assert len(schemas) == len(set(schemas))
    assert all(item["schema_version"] == "1.0.0" for item in outputs)


def test_manifest_entrypoint_schema_references_are_declared():
    payload = json.loads((SKILL_ROOT / "agents" / "manifest.json").read_text(encoding="utf-8"))
    declared = {item["schema"] for item in payload["json_outputs"]}
    referenced: set[str] = set()

    for group in ("preferred_readonly_entrypoints", "preferred_mutating_entrypoints"):
        for item in payload[group]:
            schema = item.get("schema")
            if isinstance(schema, str) and schema.startswith("tradecat."):
                referenced.add(schema)
            alternative = item.get("json_alternative")
            if isinstance(alternative, dict):
                referenced.add(str(alternative["schema"]))

    assert referenced.issubset(declared)


def test_manifest_advertises_tradecat_auto_lifecycle_entrypoints():
    payload = json.loads((SKILL_ROOT / "agents" / "manifest.json").read_text(encoding="utf-8"))
    commands = {item["command"] for item in payload.get("automation_entrypoints", [])}

    assert "bash scripts/run-tradecat.sh auto paper-report --json" in commands
    assert "bash scripts/run-tradecat.sh auto soft-layer --json" in commands
    assert "bash scripts/run-tradecat.sh auto run-once --mode paper --agent-margin-usdt 6 --paper-leverage 2 --paper-margin-budget-usdt 12 --json" in commands
    assert "bash scripts/run-tradecat.sh auto run-loop --mode paper --agent-margin-usdt 6 --paper-leverage 2 --paper-margin-budget-usdt 12 --once --json" in commands
    assert "bash scripts/run-tradecat.sh auto audit-journal --json" in commands
    assert "bash scripts/run-tradecat.sh auto health-report --json" in commands
    assert "bash scripts/run-tradecat.sh auto daily-report --json" in commands
    assert "bash scripts/run-tradecat.sh auto alert-payload --kind daily --json" in commands
    assert "bash scripts/project/scripts/start-auto-paper.sh status --json" in commands
    assert payload["important_paths"]["automation_source"] == "scripts/project/src/tradecat_auto"
    assert payload["important_paths"]["automation_audit_journal"] == "scripts/project/.runtime/auto-paper/paper_audit.sqlite3"


def test_manifest_advertises_tradecat_auto_contracts_and_safety_boundaries():
    payload = json.loads((SKILL_ROOT / "agents" / "manifest.json").read_text(encoding="utf-8"))
    automation_contracts = {item["schema"]: item for item in payload.get("automation_output_contracts", [])}

    assert {
        "tradecat_auto.paper_report.v1",
        "tradecat_auto.market_universe.v1",
        "tradecat_auto.public_probe.v1",
        "tradecat_auto.run_once_report.v1",
        "tradecat_auto.service_cycle.v1",
        "tradecat_auto.paper_service_status.v1",
        "tradecat_auto.agent_market_context_audit.v1",
        "tradecat_auto.agent_soft_layer.v1",
        "tradecat_auto.agent_trade_thesis.v1",
        "tradecat_auto.paper_account_state.v1",
        "tradecat_auto.paper_backtest_report.v1",
        "tradecat_auto.replay_report.v1",
        "tradecat_auto.audit_journal_summary.v1",
        "tradecat_auto.audit_journal_write.v1",
        "tradecat_auto.production_health.v1",
        "tradecat_auto.daily_paper_report.v1",
        "tradecat_auto.telegram_alerts.v1",
    }.issubset(automation_contracts)
    for contract in automation_contracts.values():
        assert contract["schema_version"] == "1.0.0"
        assert contract["real_orders"] is False
        assert contract["signed_requests"] is False
        assert contract["reads_api_keys"] is False
        assert contract["safety_boundary"]

    for entrypoint in payload.get("automation_entrypoints", []):
        assert entrypoint["schema"] in automation_contracts
        assert entrypoint["real_orders"] is False
        assert entrypoint["signed_requests"] is False
        assert entrypoint["reads_api_keys"] is False


def test_manifest_known_failure_modes_cover_agent_error_contract():
    payload = json.loads((SKILL_ROOT / "agents" / "manifest.json").read_text(encoding="utf-8"))
    failure_codes = {item["code"] for item in payload["known_failure_modes"]}

    assert REQUIRED_FAILURE_CODES.issubset(failure_codes)


def test_agent_profiles_point_to_manifest_instead_of_second_truth():
    openai = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
    hermes = (SKILL_ROOT / "agents" / "hermes.yaml").read_text(encoding="utf-8")

    assert "manifest: agents/manifest.json" in openai
    assert "manifest: agents/manifest.json" in hermes
    assert "agent_contract: references/agent-contract.md" in openai
    assert "agent_contract: references/agent-contract.md" in hermes


def test_agent_contract_reference_is_indexed():
    index = (SKILL_ROOT / "references" / "index.md").read_text(encoding="utf-8")
    contract = (SKILL_ROOT / "references" / "agent-contract.md").read_text(encoding="utf-8")
    guide = (SKILL_ROOT / "references" / "hermes-agent-guide.md").read_text(encoding="utf-8")
    manifest = json.loads((SKILL_ROOT / "agents" / "manifest.json").read_text(encoding="utf-8"))

    assert "agent-contract.md" in index
    assert "hermes-agent-guide.md" in index
    assert "agent-soft-decision-layer.md" in index
    assert "references/hermes-agent-guide.md" in manifest["human_docs"]
    assert "references/hermes-agent-guide.md" in manifest["agent_docs"]
    assert "references/agent-soft-decision-layer.md" in manifest["agent_docs"]
    assert manifest["important_paths"]["hermes_agent_guide"] == "references/hermes-agent-guide.md"
    assert manifest["important_paths"]["agent_soft_layer_resources"] == "scripts/project/resources/agent_soft_layer"
    assert manifest["important_paths"]["agent_soft_layer_trader_profile"] == "scripts/project/resources/agent_soft_layer/profiles/discretionary-futures-trader.zh.md"
    assert "Agent Fast Path" in contract
    assert "Command Risk Classes" in contract
    assert "Agent-supplied Market Context Contract" in contract
    assert "Production Paper Runtime Reports" in contract
    assert "给 Hermes/Agent 的最小流程" in guide
    assert "Agent-supplied market context 输入契约" in guide
    assert "纸面生产运行态与审计报告" in guide


def test_formal_contract_schemas_are_valid_json():
    contracts_dir = SKILL_ROOT / "scripts" / "project" / "contracts"
    schemas = sorted(contracts_dir.glob("*.schema.json"))

    assert {path.name for path in schemas} == {
        "tradecat-agent-manifest.schema.json",
        "tradecat-command-envelope.schema.json",
        "tradecat-error.schema.json",
        *COMMAND_SCHEMA_FILES,
        *RESOURCE_SCHEMA_FILES,
        *AUTO_SCHEMA_FILES,
    }
    for path in schemas:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_command_schema_files_pin_expected_payload_schema_names():
    contracts_dir = SKILL_ROOT / "scripts" / "project" / "contracts"

    for filename, expected_schema in {**COMMAND_SCHEMA_FILES, **RESOURCE_SCHEMA_FILES, **AUTO_SCHEMA_FILES}.items():
        payload = json.loads((contracts_dir / filename).read_text(encoding="utf-8"))
        properties = payload.get("properties", {})

        assert properties["schema"]["const"] == expected_schema
        assert properties["schema_version"]["const"] == "1.0.0"


def test_manifest_json_outputs_match_command_schema_files_one_to_one():
    manifest = json.loads((SKILL_ROOT / "agents" / "manifest.json").read_text(encoding="utf-8"))
    manifest_schemas = {item["schema"] for item in manifest["json_outputs"]}

    assert manifest_schemas == set(COMMAND_SCHEMA_FILES.values())


def test_cli_schemas_are_advertised_or_explicitly_internal():
    cli_schemas = set(_load_cli_schemas().values())
    manifest = json.loads((SKILL_ROOT / "agents" / "manifest.json").read_text(encoding="utf-8"))
    manifest_schemas = {item["schema"] for item in manifest["json_outputs"]}

    assert INTERNAL_CLI_SCHEMA_ALLOWLIST.isdisjoint(manifest_schemas)
    assert cli_schemas - INTERNAL_CLI_SCHEMA_ALLOWLIST <= manifest_schemas


def _load_cli_schemas() -> dict[str, str]:
    module_path = SKILL_ROOT / "scripts" / "project" / "src" / "tradecat_terminal" / "contracts.py"
    spec = importlib.util.spec_from_file_location("tradecat_contracts_for_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return dict(module.CLI_SCHEMAS)
