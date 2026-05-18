from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0.0"
AGENT_SOFT_LAYER_SCHEMA = "tradecat_auto.agent_soft_layer.v1"
AGENT_TRADE_THESIS_SCHEMA = "tradecat_auto.agent_trade_thesis.v1"
RESOURCE_ROOT = Path(__file__).resolve().parents[2] / "resources" / "agent_soft_layer"
RESOURCE_ROOT_CONTRACT_PATH = "resources/agent_soft_layer"
PROMPT_TEMPLATE_FILES = (
    "prompts/system.zh.md",
    "prompts/context-request.zh.md",
    "prompts/trade-thesis.zh.md",
)
ROLE_PROFILE_FILES = ("profiles/discretionary-futures-trader.zh.md",)


def build_agent_soft_layer_bundle(*, include_prompt_text: bool = True) -> dict[str, Any]:
    endpoint_policy = _load_json(RESOURCE_ROOT / "endpoint_policy.json")
    return {
        "schema": AGENT_SOFT_LAYER_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "resource_root": RESOURCE_ROOT_CONTRACT_PATH,
        "purpose": "Self-contained Agent/Hermes soft prompt and endpoint-policy layer for public-readonly paper research.",
        "prompt_templates": _prompt_templates(include_prompt_text=include_prompt_text),
        "role_profiles": _role_profiles(include_prompt_text=include_prompt_text),
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
            "binance_source_manifest": "resources/agent_market_context/binance/provenance.manifest.json",
            "reference_doc": "skills/tradecat-public/references/agent-soft-decision-layer.md",
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


def _role_profiles(*, include_prompt_text: bool) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for rel_path in ROLE_PROFILE_FILES:
        path = RESOURCE_ROOT / rel_path
        profile_id = Path(rel_path).name.removesuffix(".zh.md").removesuffix(".md").replace("-", "_")
        item: dict[str, Any] = {
            "id": profile_id,
            "role": "paper_futures_trader",
            "language": "zh-CN",
            "path": f"{RESOURCE_ROOT_CONTRACT_PATH}/{rel_path}",
            "sizing_contract": {
                "margin_budget_usdt_is_cap": False,
                "margin_budget_usdt": None,
                "default_order_size": False,
                "required_for_non_watch": ["requested_margin_usdt", "paper_leverage"],
                "missing_sizing_error_code": "agent_sizing_required",
                "legacy_notional_default_allowed": False,
                "upper_cap_semantics": "unbounded_by_default; Agent/Hermes chooses explicit paper sizing while hard public-readonly + paper/watch boundaries stay enforced",
            },
            "exit_contract": {
                "default_stop_loss": False,
                "default_take_profit": False,
                "default_max_holding_minutes": None,
                "optional_fields": ["invalidation_price", "take_profit_price", "max_holding_minutes", "exit_rationale"],
                "missing_exit_plan_behavior": "keep paper position open for Agent/strategy-managed review; no fixed TP/SL/time stop",
            },
            "safety_boundary": {
                "mode": "public_readonly_plus_paper_watch",
                "real_orders": False,
                "signed_requests": False,
                "reads_api_keys": False,
                "account_state_source": "local TradeCat paper ledger only",
            },
        }
        if include_prompt_text:
            item["template"] = path.read_text(encoding="utf-8")
        profiles.append(item)
    return profiles


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"agent_soft_layer_resource_invalid: {path} is not a JSON object")
    return payload
