from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[3]

REQUIRED_AGENT_JSON_SCHEMAS = {
    "tradecat.status.v1",
    "tradecat.dataset_list.v1",
    "tradecat.request_dataset_list.v1",
    "tradecat.path_map.v1",
    "tradecat.sync_result.v1",
    "tradecat.request_result.v1",
    "tradecat.dataset_view.v1",
    "tradecat.probe_result.v1",
}

REQUIRED_FAILURE_CODES = {
    "invalid_dataset_key",
    "remote_timeout",
    "remote_http_status",
    "invalid_runtime_configuration",
    "local_runtime_error",
}

COMMAND_SCHEMA_FILES = {
    "tradecat-config.schema.json": "tradecat.config.v1",
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

    assert "agent-contract.md" in index
    assert "Agent Fast Path" in contract
    assert "Command Risk Classes" in contract


def test_formal_contract_schemas_are_valid_json():
    contracts_dir = SKILL_ROOT / "scripts" / "project" / "contracts"
    schemas = sorted(contracts_dir.glob("*.schema.json"))

    assert {path.name for path in schemas} == {
        "tradecat-agent-manifest.schema.json",
        "tradecat-command-envelope.schema.json",
        "tradecat-error.schema.json",
        *COMMAND_SCHEMA_FILES,
    }
    for path in schemas:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_command_schema_files_pin_expected_payload_schema_names():
    contracts_dir = SKILL_ROOT / "scripts" / "project" / "contracts"

    for filename, expected_schema in COMMAND_SCHEMA_FILES.items():
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
