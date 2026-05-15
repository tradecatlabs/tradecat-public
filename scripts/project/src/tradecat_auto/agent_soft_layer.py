from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0.0"
AGENT_SOFT_LAYER_SCHEMA = "tradecat_auto.agent_soft_layer.v1"
AGENT_TRADE_THESIS_SCHEMA = "tradecat_auto.agent_trade_thesis.v1"
RESOURCE_ROOT = Path(__file__).resolve().parents[2] / "resources" / "agent_soft_layer"
RESOURCE_ROOT_CONTRACT_PATH = "scripts/project/resources/agent_soft_layer"
PROMPT_TEMPLATE_FILES = (
    "prompts/system.zh.md",
    "prompts/context-request.zh.md",
    "prompts/trade-thesis.zh.md",
)


def build_agent_soft_layer_bundle(*, include_prompt_text: bool = True) -> dict[str, Any]:
    endpoint_policy = _load_json(RESOURCE_ROOT / "endpoint_policy.json")
    return {
        "schema": AGENT_SOFT_LAYER_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "resource_root": RESOURCE_ROOT_CONTRACT_PATH,
        "purpose": "Self-contained Agent/Hermes soft prompt and endpoint-policy layer for public-readonly paper research.",
        "prompt_templates": _prompt_templates(include_prompt_text=include_prompt_text),
        "endpoint_policy": endpoint_policy,
        "soft_output_contract": {
            "schema": AGENT_TRADE_THESIS_SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "mode": "paper_research",
            "allowed_directions": ["LONG", "SHORT", "WATCH_ONLY"],
            "real_order": False,
            "description": "Agent may emit a research thesis; TradeCat deterministic gates decide paper/watch handling.",
        },
        "hard_boundaries": {
            "market_context_audit_schema": "tradecat_auto.agent_market_context_audit.v1",
            "paper_account_state_schema": "tradecat_auto.paper_account_state.v1",
            "real_orders": False,
            "signed_requests": False,
            "reads_api_keys": False,
            "account_state_source": "local TradeCat paper ledger only",
            "forbidden": [
                "Binance API keys or secrets",
                "signed requests",
                "real account/balance/position/order endpoints",
                "real order place/cancel/modify/query flows",
                "real exchange order/fill/account state in Agent context",
            ],
        },
        "provenance": {
            "binance_source_manifest": "scripts/project/resources/agent_market_context/binance/provenance.manifest.json",
            "reference_doc": "references/agent-soft-decision-layer.md",
            "extraction_mode": "soft_prompt_and_document_layer_with_hard_safety_guards",
        },
    }


def _prompt_templates(*, include_prompt_text: bool) -> list[dict[str, Any]]:
    templates: list[dict[str, Any]] = []
    for rel_path in PROMPT_TEMPLATE_FILES:
        path = RESOURCE_ROOT / rel_path
        item: dict[str, Any] = {
            "id": Path(rel_path).stem,
            "language": "zh-CN",
            "path": f"{RESOURCE_ROOT_CONTRACT_PATH}/{rel_path}",
        }
        if include_prompt_text:
            item["template"] = path.read_text(encoding="utf-8")
        templates.append(item)
    return templates


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"agent_soft_layer_resource_invalid: {path} is not a JSON object")
    return payload
