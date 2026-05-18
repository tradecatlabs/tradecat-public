from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from tradecat_auto.agent_market_context import (
    agent_market_context_to_market_bundle,
    audit_agent_market_context,
    build_paper_report_from_agent_market_context,
)
from tradecat_auto.cli import context_audit_report, run_context_public


def sample_context() -> dict:
    return {
        "schema": "tradecat_auto.agent_market_context.v1",
        "schema_version": "1.0.0",
        "symbol": "IRYSUSDT",
        "generated_at": "2026-05-15T10:00:00Z",
        "mode": "public_readonly",
        "provenance": {
            "agent": "unit-test-agent",
            "source_manifest": "resources/agent_market_context/binance/provenance.manifest.json",
            "notes": "fixture uses public/read-only Binance market fields only",
        },
        "source_event": {"event_id": "evt-ctx", "content": "IRYS 异动"},
        "anomaly_symbol": {
            "raw_symbol": "IRYS",
            "normalized_symbol": "IRYSUSDT",
            "source_values": {"交易对": "IRYS", "5m量变化率": "1.2%", "5m额变化率": "3.4%"},
        },
        "market_data": [
            {
                "family": "24h_ticker",
                "endpoint": "/fapi/v1/ticker/24hr",
                "method": "GET",
                "ok": True,
                "fetched_at": "2026-05-15T10:00:01Z",
                "provenance": {"source": "binance_public_rest"},
                "data": {
                    "symbol": "IRYSUSDT",
                    "lastPrice": "0.062",
                    "priceChangePercent": "24",
                    "quoteVolume": "50000000",
                },
            },
            {
                "family": "order_book_depth",
                "endpoint": "/fapi/v1/depth",
                "method": "GET",
                "ok": True,
                "fetched_at": "2026-05-15T10:00:01Z",
                "provenance": {"source": "binance_public_rest"},
                "data": {"bids": [["0.0619", "100"]], "asks": [["0.0621", "120"]]},
            },
            {
                "family": "open_interest",
                "endpoint": "/fapi/v1/openInterest",
                "method": "GET",
                "ok": True,
                "fetched_at": "2026-05-15T10:00:01Z",
                "provenance": {"source": "binance_public_rest"},
                "data": {"openInterest": "1000000"},
            },
            {
                "family": "open_interest_history",
                "endpoint": "/futures/data/openInterestHist",
                "method": "GET",
                "ok": True,
                "fetched_at": "2026-05-15T10:00:01Z",
                "provenance": {"source": "binance_public_rest"},
                "data": [{"sumOpenInterestValue": "100000"}],
            },
            {
                "family": "funding_rate",
                "endpoint": "/fapi/v1/fundingRate",
                "method": "GET",
                "ok": True,
                "fetched_at": "2026-05-15T10:00:01Z",
                "provenance": {"source": "binance_public_rest"},
                "data": [{"fundingRate": "0.00005"}],
            },
            {
                "family": "premium_index",
                "endpoint": "/fapi/v1/premiumIndex",
                "method": "GET",
                "ok": True,
                "fetched_at": "2026-05-15T10:00:01Z",
                "provenance": {"source": "binance_public_rest"},
                "data": {"markPrice": "0.062", "indexPrice": "0.0619"},
            },
            {
                "family": "long_short_ratios",
                "endpoint": "/futures/data/globalLongShortAccountRatio",
                "method": "GET",
                "ok": True,
                "fetched_at": "2026-05-15T10:00:01Z",
                "provenance": {"source": "binance_public_rest"},
                "data": [{"longShortRatio": "1.1"}],
            },
            {
                "family": "taker_buy_sell_volume",
                "endpoint": "/futures/data/takerlongshortRatio",
                "method": "GET",
                "ok": True,
                "fetched_at": "2026-05-15T10:00:01Z",
                "provenance": {"source": "binance_public_rest"},
                "data": [{"buySellRatio": "1.2"}],
            },
        ],
    }


class AgentMarketContextTests(unittest.TestCase):
    def test_audit_accepts_public_readonly_context_with_provenance(self) -> None:
        audit = audit_agent_market_context(sample_context())

        self.assertEqual(audit["schema"], "tradecat_auto.agent_market_context_audit.v1")
        self.assertEqual(audit["schema_version"], "1.0.0")
        self.assertTrue(audit["ok"])
        self.assertEqual(audit["symbol"], "IRYSUSDT")
        self.assertIn("24h_ticker", audit["accepted_families"])
        self.assertFalse(audit["real_orders"])
        self.assertFalse(audit["signed_requests"])
        self.assertFalse(audit["reads_api_keys"])

    def test_false_safety_declarations_are_allowed_but_true_flags_are_rejected(self) -> None:
        context = sample_context()
        context["signed_requests"] = False
        context["reads_api_keys"] = False
        context["market_data"][0]["signed"] = False
        context["market_data"][0]["requires_signature"] = False

        accepted = audit_agent_market_context(context)
        self.assertTrue(accepted["ok"])

        context["reads_api_keys"] = True
        rejected = audit_agent_market_context(context)
        self.assertFalse(rejected["ok"])
        codes = {item["code"] for item in rejected["errors"]}
        self.assertIn("credential_material_forbidden", codes)

    def test_audit_rejects_missing_top_level_source_manifest(self) -> None:
        context = sample_context()
        context["provenance"] = {"agent": "unit-test-agent"}

        audit = audit_agent_market_context(context)

        self.assertFalse(audit["ok"])
        codes = {item["code"] for item in audit["errors"]}
        self.assertIn("missing_source_manifest", codes)

    def test_audit_rejects_signed_or_trade_endpoint_even_when_wrapped_by_agent(self) -> None:
        context = sample_context()
        context["market_data"].append(
            {
                "family": "24h_ticker",
                "endpoint": "/fapi/v1/order",
                "method": "POST",
                "requires_signature": True,
                "ok": True,
                "provenance": {"source": "bad_agent"},
                "data": {"status": "FILLED"},
            }
        )

        audit = audit_agent_market_context(context)

        self.assertFalse(audit["ok"])
        codes = {item["code"] for item in audit["errors"]}
        self.assertIn("forbidden_endpoint", codes)
        self.assertIn("signed_request_forbidden", codes)
        self.assertTrue(audit["safety_boundary_enforced"])

    def test_audit_rejects_real_account_or_order_state_material(self) -> None:
        context = sample_context()
        context["paper_or_account_state"] = {
            "account_state": {"balance": "1000"},
            "open_orders": [{"exchange_order_id": "123", "status": "NEW"}],
        }
        context["market_data"].append(
            {
                "family": "open_interest",
                "endpoint": "https://fapi.binance.com/fapi/v2/positionRisk",
                "method": "GET",
                "ok": True,
                "provenance": {"source": "bad_agent"},
                "data": {"positionAmt": "1"},
            }
        )

        audit = audit_agent_market_context(context)

        self.assertFalse(audit["ok"])
        codes = {item["code"] for item in audit["errors"]}
        self.assertIn("account_or_order_state_forbidden", codes)
        self.assertIn("forbidden_endpoint", codes)

    def test_audit_rejects_broad_real_order_account_and_credential_field_names(self) -> None:
        context = sample_context()
        context["market_data"].append(
            {
                "family": "24h_ticker",
                "endpoint": "/fapi/v1/ticker/24hr",
                "method": "GET",
                "ok": True,
                "provenance": {"source": "bad_agent"},
                "requires_signature": True,
                "data": {
                    "orderId": 12345,
                    "clientOrderId": "cli-123",
                    "account": {"balance": "1000"},
                    "position": {"positionAmt": "1"},
                    "apiKey": "placeholder",
                    "signature": "abc",
                    "timestamp": 1234567890,
                    "fills": [{"price": "1", "qty": "2"}],
                    "newClientOrderId": "cli-456",
                    "origQty": "10",
                    "transactTime": 1234567890,
                    "avgPrice": "1.23",
                    "reduceOnly": True,
                },
            }
        )

        audit = audit_agent_market_context(context)

        self.assertFalse(audit["ok"])
        codes = {item["code"] for item in audit["errors"]}
        self.assertIn("credential_material_forbidden", codes)
        self.assertIn("signed_timestamp_forbidden", codes)
        self.assertIn("account_or_order_state_forbidden", codes)
        self.assertIn("signed_request_forbidden", codes)

    def test_context_to_market_bundle_maps_allowed_families_for_existing_pipeline(self) -> None:
        bundle = agent_market_context_to_market_bundle(sample_context())

        self.assertEqual(bundle["schema"], "tradecat_auto.public_market_bundle.v1")
        self.assertTrue(bundle["ok"])
        self.assertEqual(bundle["symbol"], "IRYSUSDT")
        self.assertEqual(bundle["ticker24hr"]["lastPrice"], "0.062")
        self.assertEqual(bundle["depth_summary"]["spread_bps"], 32.258064516129956)
        self.assertEqual(bundle["openInterest"]["openInterest"], "1000000")
        self.assertEqual(bundle["globalLongShortAccountRatio"][0]["longShortRatio"], "1.1")

    def test_context_can_drive_paper_pipeline_without_network_or_credentials(self) -> None:
        report = build_paper_report_from_agent_market_context(
            sample_context(),
            mode="paper",
            requested_margin_usdt=7.5,
            paper_leverage=1.0,
        )

        self.assertEqual(report["schema"], "tradecat_auto.run_once_report.v1")
        self.assertFalse(report["real_orders"])
        self.assertFalse(report["signed_requests"])
        self.assertFalse(report["reads_api_keys"])
        self.assertFalse(report["safety"]["binance_account_state"])
        self.assertEqual(
            report["provenance"]["agent_market_context"]["source_manifest"],
            "resources/agent_market_context/binance/provenance.manifest.json",
        )
        self.assertEqual(report["agent_market_context_audit"]["schema"], "tradecat_auto.agent_market_context_audit.v1")
        self.assertTrue(report["agent_market_context_audit"]["ok"])
        self.assertEqual(report["selected_symbol"], "IRYSUSDT")
        self.assertEqual(report["paper_sizing"]["mode"], "margin_times_leverage")
        self.assertEqual(report["requested_margin_usdt"], 7.5)
        self.assertIn(report["paper_execution"]["status"], {"OPENED", "REJECTED"})
        self.assertIn("agent-supplied public/read-only market context", report["limitations"])

    def test_context_without_agent_sizing_is_rejected_before_paper_execution_defaults(self) -> None:
        report = build_paper_report_from_agent_market_context(sample_context(), mode="paper")

        self.assertEqual(report["paper_sizing"]["error_code"], "agent_sizing_required")
        self.assertIn(report["risk_decision"]["decision"], {"REJECT", "WATCH_ONLY"})
        self.assertIn("agent_sizing_required", report["risk_decision"]["reasons"])
        self.assertEqual(report["paper_execution"]["status"], "REJECTED")

    def test_context_with_sizing_but_missing_agent_exit_plan_is_rejected_before_paper_open(self) -> None:
        context = sample_context()
        context["market_data"][1]["data"] = {"bids": [["0.06190", "100"]], "asks": [["0.06195", "120"]]}
        report = build_paper_report_from_agent_market_context(
            context,
            mode="paper",
            requested_margin_usdt=7.5,
            paper_leverage=1.0,
        )

        self.assertEqual(report["error_code"], "agent_exit_plan_required")
        self.assertIn("agent_exit_plan_required", report["risk_decision"]["reasons"])
        self.assertEqual(report["paper_execution"]["status"], "REJECTED")
        self.assertEqual(report["strategy_intent"]["exit_plan_source"], "agent_required_missing")
        self.assertFalse(report["real_orders"])

    def test_context_embedded_agent_trade_thesis_opens_paper_with_sizing_and_exit_plan(self) -> None:
        context = sample_context()
        context["market_data"][1]["data"] = {"bids": [["0.06190", "100"]], "asks": [["0.06195", "120"]]}
        context["agent_trade_thesis"] = {
            "schema": "tradecat_auto.agent_trade_thesis.v1",
            "schema_version": "1.0.0",
            "paper_intent": {
                "requested_margin_usdt": 7.5,
                "paper_leverage": 2.0,
            },
            "invalidation_price": 0.055,
            "take_profit_price": 0.08,
            "max_holding_minutes": 45,
            "exit_rationale": "agent supplied invalidation and target",
        }

        report = build_paper_report_from_agent_market_context(context, mode="paper")

        self.assertTrue(report["ok"])
        self.assertEqual(report["paper_sizing"]["source"], "agent_trade_thesis.paper_intent")
        self.assertEqual(report["paper_execution"]["status"], "OPENED")
        self.assertEqual(report["paper_execution"]["sizing_source"], "agent_trade_thesis.paper_intent")
        self.assertEqual(report["paper_execution"]["stop_loss_price"], 0.055)
        self.assertEqual(report["paper_execution"]["take_profit_price"], 0.08)
        self.assertEqual(report["paper_execution"]["max_holding_minutes"], 45.0)
        self.assertEqual(report["paper_execution"]["exit_plan_source"], "agent_trade_thesis")

    def test_context_audit_cli_reads_json_file_and_returns_audit_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "context.json"
            path.write_text(json.dumps(sample_context()), encoding="utf-8")

            report = context_audit_report(argparse.Namespace(input=str(path)))

        self.assertEqual(report["schema"], "tradecat_auto.agent_market_context_audit.v1")
        self.assertTrue(report["ok"])

    def test_run_context_cli_entrypoint_returns_run_once_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "context.json"
            path.write_text(json.dumps(sample_context()), encoding="utf-8")

            report = run_context_public(
                argparse.Namespace(
                    input=str(path),
                    mode="paper",
                    notional_usdt=None,
                    agent_margin_usdt=7.5,
                    paper_leverage=1.0,
                    paper_margin_budget_usdt=None,
                )
            )

        self.assertEqual(report["schema"], "tradecat_auto.run_once_report.v1")
        self.assertEqual(report["agent_market_context_audit"]["schema"], "tradecat_auto.agent_market_context_audit.v1")
        self.assertFalse(report["agent_market_context_audit"]["signed_requests"])


if __name__ == "__main__":
    unittest.main()
