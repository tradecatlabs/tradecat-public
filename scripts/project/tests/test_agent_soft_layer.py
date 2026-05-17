from __future__ import annotations

import argparse

from tradecat_auto.agent_soft_layer import build_agent_soft_layer_bundle
from tradecat_auto.cli import soft_layer_report


def test_soft_layer_bundle_is_self_contained_and_prompt_oriented() -> None:
    bundle = build_agent_soft_layer_bundle(include_prompt_text=True)

    assert bundle["schema"] == "tradecat_auto.agent_soft_layer.v1"
    assert bundle["ok"] is True
    assert bundle["resource_root"] == "scripts/project/resources/agent_soft_layer"
    assert len(bundle["prompt_templates"]) >= 3
    assert all(item["template"] for item in bundle["prompt_templates"])
    prompt_templates = {item["id"]: item["template"] for item in bundle["prompt_templates"]}
    assert "requested_margin_usdt" in prompt_templates["trade-thesis.zh"]
    assert "paper_leverage" in prompt_templates["trade-thesis.zh"]
    assert "invalidation_price" in prompt_templates["trade-thesis.zh"]
    assert "max_holding_minutes" in prompt_templates["trade-thesis.zh"]
    assert "agent_sizing_required" in prompt_templates["trade-thesis.zh"]
    assert bundle["endpoint_policy"]["schema"] == "tradecat_auto.agent_soft_endpoint_policy.v1"
    allowed = {item["family"] for item in bundle["endpoint_policy"]["allowed_market_context_families"]}
    assert "klines" in allowed
    assert "open_interest" in allowed
    forbidden_categories = {item["category"] for item in bundle["endpoint_policy"]["hard_forbidden_endpoint_categories"]}
    assert "real_order_lifecycle" in forbidden_categories
    assert "real_account_state" in forbidden_categories
    assert bundle["hard_boundaries"]["account_state_source"] == "local TradeCat paper ledger only"
    assert bundle["hard_boundaries"]["real_orders"] is False
    assert bundle["hard_boundaries"]["signed_requests"] is False
    assert bundle["hard_boundaries"]["reads_api_keys"] is False


def test_soft_layer_bundle_exposes_configurable_trader_role_profile() -> None:
    bundle = build_agent_soft_layer_bundle(include_prompt_text=True)

    profiles = {item["id"]: item for item in bundle["role_profiles"]}
    trader = profiles["discretionary_futures_trader"]

    assert trader["role"] == "paper_futures_trader"
    assert trader["path"] == "scripts/project/resources/agent_soft_layer/profiles/discretionary-futures-trader.zh.md"
    assert "不设固定保证金或杠杆上限" in trader["template"]
    assert "paper margin budget" not in trader["template"]
    assert "agent_margin_usdt" in trader["template"]
    assert "paper_leverage" in trader["template"]
    assert "agent_sizing_required" in trader["template"]
    assert "WATCH_ONLY" in trader["template"]
    assert trader["sizing_contract"]["default_order_size"] is False
    assert trader["sizing_contract"]["margin_budget_usdt_is_cap"] is False
    assert trader["sizing_contract"]["margin_budget_usdt"] is None
    assert trader["exit_contract"]["default_stop_loss"] is False
    assert trader["exit_contract"]["default_take_profit"] is False
    assert trader["exit_contract"]["default_max_holding_minutes"] is None
    assert trader["safety_boundary"]["real_orders"] is False
    assert trader["safety_boundary"]["signed_requests"] is False


def test_soft_layer_cli_can_list_prompt_paths_without_template_text() -> None:
    report = soft_layer_report(argparse.Namespace(no_prompt_text=True))

    assert report["schema"] == "tradecat_auto.agent_soft_layer.v1"
    assert report["ok"] is True
    assert all("template" not in item for item in report["prompt_templates"])
    assert all("template" not in item for item in report["role_profiles"])
