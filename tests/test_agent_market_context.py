from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from tradecat_auto.agent_market_context import (
    agent_market_context_to_market_bundle,
    audit_agent_market_context,
    build_agent_market_context_from_public_bundle,
    build_paper_report_from_agent_market_context,
    load_agent_market_context,
)
from tradecat_auto.cli import context_audit_report, run_context_public
from tradecat_auto.paper_ledger import load_paper_ledger
from tradecat_auto.safety_boundary import paper_watch_report_flags, paper_watch_safety_boundary


def assert_public_readonly_flags(testcase: unittest.TestCase, payload: dict) -> None:
    for key, expected in paper_watch_report_flags().items():
        testcase.assertIs(payload[key], expected)


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


class AgentMarketContextLoadTests(unittest.TestCase):
    def test_load_agent_market_context_returns_structured_error_for_malformed_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-context.json"
            path.write_text("{not-json", encoding="utf-8")

            payload = load_agent_market_context(path)

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_code"], "agent_market_context_load_failed")
        self.assertEqual(payload["error"]["code"], "agent_market_context_load_failed")
        self.assertEqual(
            payload["provenance"]["source"], "tradecat_auto.agent_market_context.load_agent_market_context"
        )
        assert_public_readonly_flags(self, payload)
        self.assertEqual(payload["safety"], paper_watch_safety_boundary())

    def test_load_agent_market_context_returns_structured_error_for_non_object_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-context.json"
            path.write_text("[]\n", encoding="utf-8")

            payload = load_agent_market_context(path)

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_code"], "agent_market_context_invalid_json_root")
        self.assertEqual(payload["error"]["code"], "agent_market_context_invalid_json_root")
        self.assertEqual(
            payload["provenance"]["source"], "tradecat_auto.agent_market_context.load_agent_market_context"
        )
        assert_public_readonly_flags(self, payload)
        self.assertEqual(payload["safety"], paper_watch_safety_boundary())


class AgentMarketContextTests(unittest.TestCase):
    def test_builds_agent_market_context_from_public_market_bundle(self) -> None:
        bundle = {
            "schema": "tradecat_auto.public_market_bundle.v1",
            "schema_version": "1.0.0",
            "ok": True,
            "symbol": "IRYSUSDT",
            "ticker24hr": {"symbol": "IRYSUSDT", "lastPrice": "0.062", "quoteVolume": "50000000"},
            "bookTicker": {"symbol": "IRYSUSDT", "bidPrice": "0.0619", "askPrice": "0.0621"},
            "depth": {"bids": [["0.0619", "100"]], "asks": [["0.0621", "120"]]},
            "klines": [[1700000000000, "0.060", "0.063", "0.059", "0.062", "123"]],
            "openInterest": {"openInterest": "1000000"},
            "openInterestHist": [{"sumOpenInterestValue": "100000"}],
            "fundingRate": [{"fundingRate": "0.00005"}],
            "premiumIndex": {"markPrice": "0.062", "indexPrice": "0.0619"},
            "topLongShortAccountRatio": [{"longShortRatio": "1.2"}],
            "topLongShortPositionRatio": [{"longShortRatio": "1.3"}],
            "globalLongShortAccountRatio": [{"longShortRatio": "1.1"}],
            "takerlongshortRatio": [{"buySellRatio": "1.2"}],
            "errors": {},
            "provenance": {"source": "binance_usdm_public_market_bundle"},
        }

        context = build_agent_market_context_from_public_bundle(
            bundle,
            source_event={"event_id": "evt-bundle"},
            anomaly_symbol={"normalized_symbol": "IRYSUSDT"},
            agent="unit-test-agent",
        )
        audit = audit_agent_market_context(context)
        mapped = agent_market_context_to_market_bundle(context)

        self.assertEqual(context["schema"], "tradecat_auto.agent_market_context.v1")
        self.assertTrue(audit["ok"])
        self.assertIn("klines", audit["accepted_families"])
        self.assertIn("order_book_depth", audit["accepted_families"])
        self.assertEqual(mapped["klines"][0][4], "0.062")
        self.assertEqual(context["safety"], paper_watch_safety_boundary())
        assert_public_readonly_flags(self, context["market_data"][0])

    def test_audit_accepts_public_readonly_context_with_provenance(self) -> None:
        audit = audit_agent_market_context(sample_context())

        self.assertEqual(audit["schema"], "tradecat_auto.agent_market_context_audit.v1")
        self.assertEqual(audit["schema_version"], "1.0.0")
        self.assertTrue(audit["ok"])
        self.assertEqual(audit["symbol"], "IRYSUSDT")
        self.assertIn("24h_ticker", audit["accepted_families"])
        assert_public_readonly_flags(self, audit)

    def test_audit_allows_benign_signed_reference_provenance_without_credentials(self) -> None:
        context = sample_context()
        context["provenance"]["commission_reference_requires_signed_user_data"] = True

        audit = audit_agent_market_context(context)

        self.assertTrue(audit["ok"])
        self.assertNotIn("credential_material_forbidden", {item["code"] for item in audit["errors"]})
        self.assertFalse(audit["signed_requests"])

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

        for key, unsafe_value, expected_code in (
            ("signed", "true", "signed_request_forbidden"),
            ("requires_signature", 1, "signed_request_forbidden"),
            ("reads_api_keys", "yes", "safety_boundary_violation"),
            ("real_orders", 1, "safety_boundary_violation"),
        ):
            context = sample_context()
            context["market_data"][0][key] = unsafe_value
            rejected = audit_agent_market_context(context)
            codes = {item["code"] for item in rejected["errors"]}

            self.assertFalse(rejected["ok"])
            self.assertIn(expected_code, codes)

        context = sample_context()
        context["safety"] = {
            "public_readonly_market_data": True,
            "public_readonly": False,
            "paper_or_watch_only": True,
            "real_orders": False,
            "signed_requests": False,
            "reads_api_keys": False,
            "binance_account_state": False,
        }
        rejected = audit_agent_market_context(context)
        self.assertFalse(rejected["ok"])
        self.assertIn("safety_boundary_violation", {item["code"] for item in rejected["errors"]})

        context = sample_context()
        context["safety"] = "not-an-object"
        rejected = audit_agent_market_context(context)
        self.assertFalse(rejected["ok"])
        self.assertIn("safety_boundary_violation", {item["code"] for item in rejected["errors"]})

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
        assert_public_readonly_flags(self, report)
        self.assertEqual(report["safety"], paper_watch_safety_boundary())
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

    def test_context_audit_cli_load_failure_keeps_public_readonly_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken-context.json"
            path.write_text("{not-json", encoding="utf-8")

            report = context_audit_report(argparse.Namespace(input=str(path)))

        self.assertFalse(report["ok"])
        self.assertEqual(report["schema"], "tradecat_auto.agent_market_context_audit.v1")
        self.assertEqual(report["errors"][0]["code"], "agent_market_context_load_failed")
        assert_public_readonly_flags(self, report)

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

    def test_run_context_cli_load_failure_keeps_public_readonly_safety(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken-context.json"
            path.write_text("{not-json", encoding="utf-8")

            report = run_context_public(
                argparse.Namespace(
                    input=str(path),
                    mode="paper",
                    notional_usdt=None,
                    agent_margin_usdt=None,
                    paper_leverage=None,
                    paper_margin_budget_usdt=None,
                    portfolio_risk_policy_path="",
                    paper_kill_switch_path="",
                    ledger_path="",
                    archive_path="",
                    journal_path="",
                    initial_balance_usdt=1000.0,
                    paper_fee_bps=4.0,
                    paper_slippage_bps=0.0,
                    now="",
                )
            )

        self.assertFalse(report["ok"])
        self.assertEqual(report["error_code"], "agent_market_context_load_failed")
        self.assertEqual(report["selected_symbol"], "")
        assert_public_readonly_flags(self, report)
        self.assertEqual(report["safety"], paper_watch_safety_boundary())

    def test_run_context_cli_can_write_local_paper_runtime_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = sample_context()
            context["market_data"][1]["data"] = {"bids": [["0.06190", "100"]], "asks": [["0.06195", "120"]]}
            context["agent_trade_thesis"] = {
                "schema": "tradecat_auto.agent_trade_thesis.v1",
                "schema_version": "1.0.0",
                "direction": "LONG",
                "paper_intent": {"requested_margin_usdt": 7.5, "paper_leverage": 2.0},
                "invalidation_price": 0.055,
                "take_profit_price": 0.08,
                "max_holding_minutes": 45,
                "exit_rationale": "agent supplied invalidation and target",
                "provenance": {"research_cycle_run_id": "research-cycle-context-write"},
            }
            path = root / "context.json"
            ledger_path = root / "paper_ledger.json"
            archive_path = root / "cycles.jsonl"
            journal_path = root / "paper_audit.sqlite3"
            path.write_text(json.dumps(context), encoding="utf-8")

            report = run_context_public(
                argparse.Namespace(
                    input=str(path),
                    mode="paper",
                    notional_usdt=None,
                    agent_margin_usdt=None,
                    paper_leverage=None,
                    paper_margin_budget_usdt=None,
                    portfolio_risk_policy_path="",
                    paper_kill_switch_path="",
                    ledger_path=str(ledger_path),
                    archive_path=str(archive_path),
                    journal_path=str(journal_path),
                    initial_balance_usdt=1000.0,
                    paper_fee_bps=4.0,
                    paper_slippage_bps=0.0,
                    now="2026-05-18T00:00:00Z",
                )
            )

            self.assertTrue(report["ok"])
            self.assertEqual(report["paper_execution"]["status"], "OPENED")
            self.assertTrue(report["paper_runtime_write"]["ledger_written"])
            self.assertTrue(report["paper_runtime_write"]["archive_written"])
            self.assertTrue(report["paper_runtime_write"]["journal_written"])
            self.assertFalse(report["paper_runtime_write"]["safety"]["real_orders"])
            self.assertEqual(report["paper_ledger"]["open_positions_count"], 1)
            ledger = load_paper_ledger(ledger_path)
            self.assertEqual(len(ledger["open_positions"]), 1)
            self.assertTrue(archive_path.exists())
            archived_cycle = json.loads(archive_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(archived_cycle["action"], "RUN_CONTEXT_PAPER")
            assert_public_readonly_flags(self, archived_cycle)
            self.assertTrue(journal_path.exists())

    def test_run_context_cli_rejects_invalid_runtime_cost_inputs_structured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "context.json"
            path.write_text(json.dumps(sample_context()), encoding="utf-8")

            report = run_context_public(
                argparse.Namespace(
                    input=str(path),
                    mode="paper",
                    notional_usdt=None,
                    agent_margin_usdt=None,
                    paper_leverage=None,
                    paper_margin_budget_usdt=None,
                    portfolio_risk_policy_path="",
                    paper_kill_switch_path="",
                    ledger_path="",
                    archive_path="",
                    journal_path="",
                    initial_balance_usdt=1000.0,
                    paper_fee_bps=-1.0,
                    paper_slippage_bps=0.0,
                    now="",
                )
            )

            self.assertFalse(report["ok"])
            self.assertEqual(report["error_code"], "run_context_invalid_numeric_input")
            self.assertEqual(report["error"]["kind"], "operator_input")
            self.assertFalse(report["safety"]["real_orders"])
            self.assertFalse(report["safety"]["signed_requests"])
            self.assertFalse(report["safety"]["reads_api_keys"])


if __name__ == "__main__":
    unittest.main()
