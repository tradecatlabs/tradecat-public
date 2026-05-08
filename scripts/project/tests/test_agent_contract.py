from __future__ import annotations

import json
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[3]


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

    assert {
        "tradecat.status.v1",
        "tradecat.dataset_list.v1",
        "tradecat.request_dataset_list.v1",
        "tradecat.path_map.v1",
        "tradecat.sync_result.v1",
        "tradecat.request_result.v1",
        "tradecat.dataset_view.v1",
    }.issubset(schemas)


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
    }
    for path in schemas:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["$schema"] == "https://json-schema.org/draft/2020-12/schema"
