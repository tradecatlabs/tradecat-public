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


def test_soft_layer_cli_can_list_prompt_paths_without_template_text() -> None:
    report = soft_layer_report(argparse.Namespace(no_prompt_text=True))

    assert report["schema"] == "tradecat_auto.agent_soft_layer.v1"
    assert report["ok"] is True
    assert all("template" not in item for item in report["prompt_templates"])
