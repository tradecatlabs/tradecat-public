from __future__ import annotations

import unittest

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


class PipelineTests(unittest.TestCase):
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
        )

        self.assertEqual(report["schema"], "tradecat_auto.run_once_report.v1")
        self.assertTrue(report["ok"])
        self.assertEqual(report["selected_symbol"], "IRYSUSDT")
        self.assertEqual(report["enrichment"]["schema"], "tradecat_auto.market_enrichment.v1")
        self.assertEqual(report["signal"]["schema"], "tradecat_auto.signal_score.v1")
        self.assertEqual(report["strategy_intent"]["schema"], "tradecat_auto.strategy_intent.v1")
        self.assertEqual(report["risk_decision"]["schema"], "tradecat_auto.risk_decision.v1")
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
        )

        self.assertEqual(report["paper_sizing"]["margin_budget_usdt"], None)
        self.assertFalse(report["paper_sizing"]["budget_exceeded"])
        self.assertEqual(report["effective_notional_usdt"], 125_000_000.0)
        self.assertEqual(report["risk_decision"]["decision"], "ALLOW")
        self.assertEqual(report["risk_decision"]["max_notional_usdt"], None)
        self.assertEqual(report["paper_execution"]["status"], "OPENED")
        self.assertEqual(report["paper_execution"]["notional_usdt"], 125_000_000.0)

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
