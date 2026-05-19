from __future__ import annotations

import unittest

from tradecat_auto.paper_autonomy import normalize_paper_autonomy_profile
from tradecat_auto.pipeline import build_paper_pipeline_report

ANOMALY = {
    "symbols": [
        {
            "raw_symbol": "IRYS",
            "normalized_symbol": "IRYSUSDT",
            "source_values": {"交易对": "IRYS", "5m量变化率": "1.2%", "5m额变化率": "3.4%"},
        }
    ]
}
MARKET_BUNDLE = {
    "schema": "tradecat_auto.public_market_bundle.v1",
    "ok": True,
    "symbol": "IRYSUSDT",
    "ticker24hr": {"lastPrice": "0.062", "priceChangePercent": "24.0", "quoteVolume": "50000000"},
    "depth_summary": {"spread_bps": 3.0, "best_bid": 0.0619, "best_ask": 0.0621},
    "openInterest": {"openInterest": "1000000"},
    "openInterestHist": [{"sumOpenInterestValue": "100000"}],
    "fundingRate": [{"fundingRate": "0.00005"}],
    "premiumIndex": {"markPrice": "0.062", "indexPrice": "0.0619"},
    "topLongShortAccountRatio": [{"longShortRatio": "1.1"}],
    "topLongShortPositionRatio": [{"longShortRatio": "1.2"}],
    "globalLongShortAccountRatio": [{"longShortRatio": "1.1"}],
    "takerlongshortRatio": [{"buySellRatio": "1.2"}],
    "errors": {},
}
EVENTS = {"events": [{"event_id": "abc", "content": "IRYS 异动"}]}
AGENT_EXIT_PLAN = {
    "schema": "tradecat_auto.agent_trade_thesis.v1",
    "schema_version": "1.0.0",
    "invalidation_price": 0.055,
    "take_profit_price": 0.08,
    "max_holding_minutes": 45,
    "exit_rationale": "agent supplied invalidation and target",
}
PAPER_AUTONOMY_PROFILE = {
    "schema": "tradecat_auto.paper_autonomy_profile.v1",
    "schema_version": "1.0.0",
    "ok": True,
    "enabled": True,
    "mode": "paper",
    "paper_intent": {
        "allow_tradecat_paper_gate_to_decide": True,
        "requested_margin_usdt": 7.5,
        "paper_leverage": 2.0,
        "allow_agent_direction_override": True,
        "direction_policy": "price_momentum_on_conflict",
        "min_signal_score": 60,
        "allow_multiple_open_positions_per_symbol": True,
        "max_concurrent_positions_per_symbol": 2,
        "real_order": False,
    },
    "exit_plan": {
        "stop_loss_bps": 100,
        "take_profit_bps": 200,
        "max_holding_minutes": 45,
        "exit_rationale": "operator delegated paper autonomy",
    },
    "provenance": {"source": "test_pipeline"},
    "safety": {
        "public_readonly_market_data": True,
        "public_readonly": True,
        "paper_or_watch_only": True,
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "binance_account_state": False,
    },
}


class PipelineTests(unittest.TestCase):
    def test_build_paper_pipeline_report_keeps_missing_sizing_fail_closed_without_thesis(self) -> None:
        report = build_paper_pipeline_report(
            selected_symbol="IRYSUSDT",
            anomaly_symbols=ANOMALY,
            market_bundle=MARKET_BUNDLE,
            events=EVENTS,
            mode="paper",
        )

        self.assertFalse(report["ok"])
        self.assertEqual(report["error_code"], "agent_sizing_required")
        self.assertEqual(report["paper_sizing"]["error_code"], "agent_sizing_required")
        self.assertEqual(report["paper_execution"]["status"], "REJECTED")
        self.assertIn("agent_sizing_required", report["risk_decision"]["reasons"])

    def test_build_paper_pipeline_report_combines_enrichment_signal_risk_and_paper_execution(self) -> None:
        report = build_paper_pipeline_report(
            selected_symbol="IRYSUSDT",
            anomaly_symbols=ANOMALY,
            market_bundle=MARKET_BUNDLE,
            events=EVENTS,
            mode="paper",
            requested_margin_usdt=7.5,
            paper_leverage=3.0,
            sizing_source="agent_supplied_cli_margin",
            agent_trade_thesis=AGENT_EXIT_PLAN,
        )

        self.assertEqual(report["schema"], "tradecat_auto.run_once_report.v1")
        self.assertTrue(report["ok"])
        self.assertEqual(report["selected_symbol"], "IRYSUSDT")
        self.assertEqual(report["enrichment"]["schema"], "tradecat_auto.market_enrichment.v1")
        self.assertEqual(report["signal"]["schema"], "tradecat_auto.signal_score.v1")
        self.assertEqual(report["strategy_intent"]["schema"], "tradecat_auto.strategy_intent.v1")
        for stage_name in ("enrichment", "signal", "strategy_intent"):
            self.assertEqual(report[stage_name]["schema_version"], "1.0.0")
            self.assertIn("error_code", report[stage_name])
            self.assertIn("provenance", report[stage_name])
            self.assertFalse(report[stage_name]["safety"]["real_orders"])
            self.assertFalse(report[stage_name]["safety"]["signed_requests"])
            self.assertFalse(report[stage_name]["safety"]["reads_api_keys"])
        self.assertEqual(report["risk_decision"]["schema"], "tradecat_auto.risk_decision.v1")
        self.assertEqual(report["risk_decision"]["schema_version"], "1.0.0")
        self.assertEqual(report["risk_decision"]["provenance"]["source"], "tradecat_auto.risk.evaluate_risk")
        self.assertFalse(report["risk_decision"]["real_orders"])
        self.assertFalse(report["risk_decision"]["signed_requests"])
        self.assertFalse(report["risk_decision"]["reads_api_keys"])
        self.assertFalse(report["risk_decision"]["safety"]["real_orders"])
        self.assertEqual(report["paper_sizing"]["schema"], "tradecat_auto.paper_sizing_decision.v1")
        self.assertEqual(report["paper_sizing"]["schema_version"], "1.0.0")
        self.assertEqual(
            report["paper_sizing"]["provenance"]["source"],
            "tradecat_auto.pipeline.paper_sizing_decision",
        )
        self.assertFalse(report["paper_sizing"]["safety"]["real_orders"])
        self.assertFalse(report["paper_sizing"]["safety"]["signed_requests"])
        self.assertFalse(report["paper_sizing"]["safety"]["reads_api_keys"])
        self.assertEqual(report["paper_execution"]["schema"], "tradecat_auto.paper_execution_report.v1")
        self.assertIn(report["paper_execution"]["status"], {"OPENED", "REJECTED"})

    def test_build_paper_pipeline_report_honors_unbounded_agent_sizing_by_default(self) -> None:
        report = build_paper_pipeline_report(
            selected_symbol="IRYSUSDT",
            anomaly_symbols=ANOMALY,
            market_bundle=MARKET_BUNDLE,
            events=EVENTS,
            mode="paper",
            requested_margin_usdt=1_000_000.0,
            paper_leverage=125.0,
            sizing_source="agent_supplied_cli_margin",
            agent_trade_thesis=AGENT_EXIT_PLAN,
        )

        self.assertEqual(report["paper_sizing"]["margin_budget_usdt"], None)
        self.assertFalse(report["paper_sizing"]["budget_exceeded"])
        self.assertEqual(report["effective_notional_usdt"], 125_000_000.0)
        self.assertEqual(report["risk_decision"]["decision"], "ALLOW")
        self.assertEqual(report["risk_decision"]["max_notional_usdt"], None)
        self.assertEqual(report["paper_execution"]["status"], "OPENED")
        self.assertEqual(report["paper_execution"]["notional_usdt"], 125_000_000.0)

    def test_build_paper_pipeline_report_uses_agent_trade_thesis_paper_intent_and_exit_plan(self) -> None:
        thesis = {
            "schema": "tradecat_auto.agent_trade_thesis.v1",
            "schema_version": "1.0.0",
            "provenance": {"source": ""},
            "paper_intent": {
                "requested_margin_usdt": 7.5,
                "paper_leverage": 2.0,
            },
            "invalidation_price": 0.055,
            "take_profit_price": 0.08,
            "max_holding_minutes": 45,
            "exit_rationale": "agent supplied invalidation and target",
        }

        report = build_paper_pipeline_report(
            selected_symbol="IRYSUSDT",
            anomaly_symbols=ANOMALY,
            market_bundle=MARKET_BUNDLE,
            events=EVENTS,
            mode="paper",
            agent_trade_thesis=thesis,
        )

        self.assertTrue(report["ok"])
        self.assertEqual(report["agent_trade_thesis"]["provenance"]["source"], "agent_supplied_trade_thesis")
        self.assertFalse(report["agent_trade_thesis"]["safety"]["real_orders"])
        self.assertFalse(report["agent_trade_thesis"]["safety"]["signed_requests"])
        self.assertFalse(report["agent_trade_thesis"]["safety"]["reads_api_keys"])
        self.assertEqual(report["paper_sizing"]["source"], "agent_trade_thesis.paper_intent")
        self.assertEqual(report["requested_margin_usdt"], 7.5)
        self.assertEqual(report["paper_leverage"], 2.0)
        self.assertEqual(report["effective_notional_usdt"], 15.0)
        self.assertEqual(report["strategy_intent"]["invalidation_price"], 0.055)
        self.assertEqual(report["strategy_intent"]["take_profit_price"], 0.08)
        self.assertEqual(report["strategy_intent"]["max_holding_minutes"], 45.0)
        self.assertEqual(report["paper_execution"]["status"], "OPENED")
        self.assertEqual(report["paper_execution"]["sizing_source"], "agent_trade_thesis.paper_intent")
        self.assertEqual(report["paper_execution"]["stop_loss_price"], 0.055)
        self.assertEqual(report["paper_execution"]["take_profit_price"], 0.08)
        self.assertEqual(report["paper_execution"]["max_holding_minutes"], 45.0)
        self.assertEqual(report["paper_execution"]["exit_plan_source"], "agent_trade_thesis")
        self.assertFalse(report["paper_execution"]["allow_multiple_open_positions_per_symbol"])

    def test_build_paper_pipeline_report_accepts_wrapped_agent_trade_thesis(self) -> None:
        wrapped_thesis = {
            "agent_trade_thesis": {
                "schema": "tradecat_auto.agent_trade_thesis.v1",
                "schema_version": "1.0.0",
                "paper_intent": {
                    "requested_margin_usdt": 5.0,
                    "paper_leverage": 3.0,
                },
                "invalidation_price": 0.055,
                "take_profit_price": 0.08,
                "max_holding_minutes": 45,
            }
        }

        report = build_paper_pipeline_report(
            selected_symbol="IRYSUSDT",
            anomaly_symbols=ANOMALY,
            market_bundle=MARKET_BUNDLE,
            events=EVENTS,
            mode="paper",
            agent_trade_thesis=wrapped_thesis,
        )

        self.assertTrue(report["ok"])
        self.assertEqual(report["paper_sizing"]["source"], "agent_trade_thesis.paper_intent")
        self.assertEqual(report["effective_notional_usdt"], 15.0)
        self.assertEqual(report["paper_execution"]["status"], "OPENED")

    def test_build_paper_pipeline_report_rejects_unsafe_raw_agent_trade_thesis(self) -> None:
        thesis = {
            "schema": "tradecat_auto.agent_trade_thesis.v1",
            "schema_version": "1.0.0",
            "paper_intent": {
                "requested_margin_usdt": 7.5,
                "paper_leverage": 2.0,
                "real_order": True,
            },
            "invalidation_price": 0.055,
            "take_profit_price": 0.08,
            "max_holding_minutes": 45,
        }

        with self.assertRaisesRegex(ValueError, "agent_trade_thesis_synthesis_failed: forbidden"):
            build_paper_pipeline_report(
                selected_symbol="IRYSUSDT",
                anomaly_symbols=ANOMALY,
                market_bundle=MARKET_BUNDLE,
                events=EVENTS,
                mode="paper",
                agent_trade_thesis=thesis,
            )

        with self.assertRaisesRegex(ValueError, "agent_trade_thesis_synthesis_failed: forbidden"):
            build_paper_pipeline_report(
                selected_symbol="IRYSUSDT",
                anomaly_symbols=ANOMALY,
                market_bundle=MARKET_BUNDLE,
                events=EVENTS,
                mode="paper",
                agent_trade_thesis={
                    "agent_trade_thesis": {**thesis, "paper_intent": {"real_order": False}},
                    "api_key": "x",
                },
            )

        with self.assertRaisesRegex(
            ValueError,
            r"agent_trade_thesis_synthesis_failed: safety\.public_readonly must be True",
        ):
            build_paper_pipeline_report(
                selected_symbol="IRYSUSDT",
                anomaly_symbols=ANOMALY,
                market_bundle=MARKET_BUNDLE,
                events=EVENTS,
                mode="paper",
                agent_trade_thesis={
                    "safety": {
                        "public_readonly_market_data": True,
                        "public_readonly": False,
                        "paper_or_watch_only": True,
                        "real_orders": False,
                        "signed_requests": False,
                        "reads_api_keys": False,
                        "binance_account_state": False,
                    },
                    "agent_trade_thesis": {**thesis, "paper_intent": {"real_order": False}},
                },
            )

    def test_build_paper_pipeline_report_estimates_taker_cost_from_public_depth(self) -> None:
        thesis = {
            "schema": "tradecat_auto.agent_trade_thesis.v1",
            "schema_version": "1.0.0",
            "paper_intent": {"requested_margin_usdt": 7.5, "paper_leverage": 2.0},
            "invalidation_price": 0.055,
            "take_profit_price": 0.08,
            "max_holding_minutes": 45,
        }
        market_bundle = {
            **MARKET_BUNDLE,
            "depth": {
                "bids": [["0.0619", "1000"]],
                "asks": [["0.0621", "1000"]],
            },
        }

        report = build_paper_pipeline_report(
            selected_symbol="IRYSUSDT",
            anomaly_symbols=ANOMALY,
            market_bundle=market_bundle,
            events=EVENTS,
            mode="paper",
            agent_trade_thesis=thesis,
        )

        self.assertTrue(report["ok"])
        self.assertEqual(report["paper_execution_cost"]["schema"], "tradecat_auto.paper_execution_cost_model.v1")
        self.assertTrue(report["paper_execution_cost"]["ok"])
        self.assertEqual(report["paper_execution_cost"]["price_source"], "binance_usdm_public_order_book_depth")
        self.assertEqual(report["paper_execution_cost"]["fee_bps"], 4.0)
        self.assertEqual(report["paper_execution"]["paper_fee_bps"], 4.0)
        self.assertEqual(report["paper_execution"]["paper_fee_model"], "binance_usdm_public_docs_vip0_taker_fallback")
        self.assertEqual(report["paper_execution"]["entry_price_source"], "binance_usdm_public_order_book_depth")
        self.assertTrue(report["paper_execution"]["entry_price_includes_slippage"])
        self.assertAlmostEqual(report["paper_execution"]["raw_entry_price"], 0.062)
        self.assertAlmostEqual(report["paper_execution"]["entry_price"], 0.0621)

    def test_build_paper_pipeline_report_uses_paper_autonomy_profile_when_thesis_missing(self) -> None:
        report = build_paper_pipeline_report(
            selected_symbol="IRYSUSDT",
            anomaly_symbols=ANOMALY,
            market_bundle=MARKET_BUNDLE,
            events=EVENTS,
            mode="paper",
            paper_autonomy_profile=PAPER_AUTONOMY_PROFILE,
        )

        self.assertTrue(report["ok"])
        self.assertTrue(report["agent_trade_thesis"]["paper_autonomy_profile"])
        self.assertEqual(
            report["agent_trade_thesis"]["rationale"],
            "operator-delegated paper autonomy profile supplied sizing/exits for Agent paper research.",
        )
        self.assertEqual(report["agent_trade_thesis"]["exit_rationale"], "operator delegated paper autonomy")
        self.assertIn("paper/watch only", report["agent_trade_thesis"]["limitations"][0])
        self.assertFalse(report["agent_trade_thesis"]["safety"]["real_orders"])
        self.assertFalse(report["agent_trade_thesis"]["safety"]["signed_requests"])
        self.assertFalse(report["agent_trade_thesis"]["safety"]["reads_api_keys"])
        self.assertEqual(report["paper_sizing"]["source"], "agent_trade_thesis.paper_intent")
        self.assertEqual(report["requested_margin_usdt"], 7.5)
        self.assertEqual(report["paper_leverage"], 2.0)
        self.assertEqual(report["effective_notional_usdt"], 15.0)
        self.assertAlmostEqual(report["strategy_intent"]["invalidation_price"], 0.06138)
        self.assertAlmostEqual(report["strategy_intent"]["take_profit_price"], 0.06324)
        self.assertEqual(report["strategy_intent"]["max_holding_minutes"], 45.0)
        self.assertEqual(report["paper_execution"]["status"], "OPENED")
        self.assertEqual(report["paper_execution"]["exit_plan_source"], "agent_trade_thesis")
        self.assertTrue(report["paper_execution"]["allow_multiple_open_positions_per_symbol"])
        self.assertEqual(report["paper_execution"]["max_concurrent_positions_per_symbol"], 2)
        self.assertFalse(report["paper_execution"]["real_orders"])
        self.assertFalse(report["paper_execution"]["signed_requests"])
        self.assertFalse(report["paper_execution"]["reads_api_keys"])

    def test_paper_autonomy_profile_rejects_unknown_safety_keys(self) -> None:
        profile = {
            **PAPER_AUTONOMY_PROFILE,
            "safety": {**PAPER_AUTONOMY_PROFILE["safety"], "can_place_real_orders": False},
        }

        with self.assertRaisesRegex(ValueError, r"paper_autonomy_profile_load_failed: safety\.can_place_real_orders"):
            normalize_paper_autonomy_profile(profile)

    def test_build_paper_pipeline_report_allows_agent_direction_override_on_conflict(self) -> None:
        conflict_bundle = {
            **MARKET_BUNDLE,
            "ticker24hr": {"lastPrice": "300", "priceChangePercent": "-12.4", "quoteVolume": "50000000"},
            "premiumIndex": {"markPrice": "300", "indexPrice": "300.1"},
            "takerlongshortRatio": [{"buySellRatio": "0.82"}],
            "topLongShortAccountRatio": [{"longShortRatio": "1.4"}],
            "topLongShortPositionRatio": [{"longShortRatio": "1.5"}],
            "globalLongShortAccountRatio": [{"longShortRatio": "1.6"}],
        }

        without_override = build_paper_pipeline_report(
            selected_symbol="IRYSUSDT",
            anomaly_symbols=ANOMALY,
            market_bundle=conflict_bundle,
            events=EVENTS,
            mode="paper",
        )
        with_override = build_paper_pipeline_report(
            selected_symbol="IRYSUSDT",
            anomaly_symbols=ANOMALY,
            market_bundle=conflict_bundle,
            events=EVENTS,
            mode="paper",
            paper_autonomy_profile=PAPER_AUTONOMY_PROFILE,
        )

        self.assertEqual(without_override["signal"]["direction"], "WATCH_ONLY")
        self.assertIn("direction_conflict", without_override["signal"]["do_not_trade_reasons"])
        self.assertEqual(without_override["paper_execution"]["status"], "REJECTED")
        self.assertTrue(with_override["ok"])
        self.assertEqual(with_override["signal"]["direction"], "SHORT")
        self.assertTrue(with_override["signal"]["tradable_candidate"])
        self.assertEqual(with_override["signal"]["do_not_trade_reasons"], [])
        self.assertEqual(with_override["paper_execution"]["status"], "OPENED")
        self.assertEqual(with_override["paper_execution"]["side"], "SHORT")
        self.assertAlmostEqual(with_override["paper_execution"]["stop_loss_price"], 303.0)
        self.assertAlmostEqual(with_override["paper_execution"]["take_profit_price"], 294.0)
        self.assertFalse(with_override["paper_execution"]["real_orders"])

    def test_paper_autonomy_profile_can_follow_sheet_signal_direction(self) -> None:
        anomaly = {
            "symbols": [
                {
                    "raw_symbol": "IRYS",
                    "normalized_symbol": "IRYSUSDT",
                    "source_dataset_key": "signal_flow",
                    "source_values": {
                        "交易对": "IRYS",
                        "类型": "主动卖盘占优",
                        "内容": "主动卖盘占优；方向=卖出，强度=87",
                    },
                }
            ]
        }
        profile = {
            **PAPER_AUTONOMY_PROFILE,
            "paper_intent": {
                **PAPER_AUTONOMY_PROFILE["paper_intent"],
                "direction_policy": "sheet_signal_or_taker_flow",
                "allow_signal_reject_override": True,
                "min_signal_score": 0,
            },
        }
        report = build_paper_pipeline_report(
            selected_symbol="IRYSUSDT",
            anomaly_symbols=anomaly,
            market_bundle=MARKET_BUNDLE,
            events=EVENTS,
            mode="paper",
            paper_autonomy_profile=profile,
        )

        self.assertTrue(report["ok"])
        self.assertEqual(report["agent_trade_thesis"]["direction"], "SHORT")
        self.assertEqual(report["paper_execution"]["status"], "OPENED")
        self.assertEqual(report["paper_execution"]["side"], "SHORT")
        self.assertTrue(report["signal"]["agent_direction_override"]["ok"])

    def test_build_paper_pipeline_report_rejects_missing_anomaly_symbol(self) -> None:
        report = build_paper_pipeline_report(
            selected_symbol="NOPEUSDT",
            anomaly_symbols=ANOMALY,
            market_bundle=MARKET_BUNDLE,
            events=EVENTS,
            mode="paper",
        )

        self.assertFalse(report["ok"])
        self.assertEqual(report["error_code"], "selected_symbol_not_found_in_anomaly_symbols")
        self.assertEqual(report["error"], "selected_symbol_not_found_in_anomaly_symbols")

    def test_build_paper_pipeline_report_applies_risk_policy_context(self) -> None:
        report = build_paper_pipeline_report(
            selected_symbol="IRYSUSDT",
            anomaly_symbols=ANOMALY,
            market_bundle=MARKET_BUNDLE,
            events=EVENTS,
            mode="paper",
            risk_policy={"max_open_positions": 1, "current_open_positions": 1},
        )

        self.assertEqual(report["risk_decision"]["decision"], "REJECT")
        self.assertIn("max_open_positions_reached", report["risk_decision"]["reasons"])
        self.assertEqual(report["paper_execution"]["status"], "REJECTED")

    def test_build_paper_pipeline_report_keeps_requested_mode_authoritative(self) -> None:
        report = build_paper_pipeline_report(
            selected_symbol="IRYSUSDT",
            anomaly_symbols=ANOMALY,
            market_bundle=MARKET_BUNDLE,
            events=EVENTS,
            mode="mainnet",
            risk_policy={"mode": "paper", "min_score": 0},
        )

        self.assertEqual(report["mode"], "mainnet")
        self.assertEqual(report["risk_decision"]["mode"], "mainnet")
        self.assertEqual(report["risk_decision"]["decision"], "REJECT")
        self.assertIn("mainnet_execution_not_implemented", report["risk_decision"]["reasons"])
        self.assertEqual(report["paper_execution"]["status"], "REJECTED")


if __name__ == "__main__":
    unittest.main()
