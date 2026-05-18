from __future__ import annotations

import unittest

from tradecat_auto.paper_broker import close_paper_position, open_paper_position

ENRICHMENT = {
    "symbol": "IRYSUSDT",
    "metrics": {
        "last_price": 0.062,
        "spread_bps": 3.2,
    },
}
SIGNAL = {
    "symbol": "IRYSUSDT",
    "direction": "LONG",
    "score": 75,
    "tradable_candidate": True,
}
ALLOW_DECISION = {
    "decision": "ALLOW",
    "mode": "paper",
    "max_notional_usdt": 20.0,
}


class PaperBrokerTests(unittest.TestCase):
    def test_open_paper_position_uses_risk_capped_notional_and_entry_price(self) -> None:
        report = open_paper_position(
            SIGNAL, ALLOW_DECISION, ENRICHMENT, requested_notional_usdt=50.0, paper_leverage=2.0
        )

        self.assertEqual(report["schema"], "tradecat_auto.paper_execution_report.v1")
        self.assertEqual(report["status"], "OPENED")
        self.assertEqual(report["symbol"], "IRYSUSDT")
        self.assertEqual(report["side"], "LONG")
        self.assertEqual(report["notional_usdt"], 20.0)
        self.assertAlmostEqual(report["quantity"], 20.0 / 0.062)
        self.assertEqual(report["entry_price"], 0.062)
        self.assertIsNone(report["stop_loss_price"])
        self.assertIsNone(report["take_profit_price"])
        self.assertIsNone(report["max_holding_minutes"])
        self.assertEqual(report["exit_management"], "agent_managed")

    def test_open_paper_position_does_not_clip_agent_notional_without_explicit_cap(self) -> None:
        decision = {"decision": "ALLOW", "mode": "paper", "max_notional_usdt": None}

        report = open_paper_position(
            SIGNAL, decision, ENRICHMENT, requested_notional_usdt=50_000_000.0, paper_leverage=125.0
        )

        self.assertEqual(report["status"], "OPENED")
        self.assertEqual(report["notional_usdt"], 50_000_000.0)
        self.assertAlmostEqual(report["quantity"], 50_000_000.0 / 0.062)
        self.assertEqual(report["leverage"], 125.0)

    def test_open_paper_position_uses_agent_supplied_exit_plan(self) -> None:
        strategy_intent = {
            "invalidation_price": 0.058,
            "take_profit_price": 0.071,
            "max_holding_minutes": 240,
            "exit_management": "agent_supplied",
            "exit_plan_source": "agent_trade_thesis",
        }

        report = open_paper_position(
            SIGNAL,
            ALLOW_DECISION,
            ENRICHMENT,
            requested_notional_usdt=10.0,
            paper_leverage=2.0,
            strategy_intent=strategy_intent,
        )

        self.assertEqual(report["stop_loss_price"], 0.058)
        self.assertEqual(report["take_profit_price"], 0.071)
        self.assertEqual(report["max_holding_minutes"], 240.0)
        self.assertEqual(report["exit_management"], "agent_supplied")
        self.assertEqual(report["exit_plan_source"], "agent_trade_thesis")

    def test_open_paper_position_rejects_missing_agent_size_or_leverage(self) -> None:
        report = open_paper_position(SIGNAL, ALLOW_DECISION, ENRICHMENT, requested_notional_usdt=10.0)

        self.assertEqual(report["status"], "REJECTED")
        self.assertIn("agent_sizing_required", report["reasons"])

    def test_open_paper_position_rejects_when_risk_does_not_allow(self) -> None:
        decision = {"decision": "WATCH_ONLY", "mode": "paper", "max_notional_usdt": 20.0}

        report = open_paper_position(SIGNAL, decision, ENRICHMENT)

        self.assertEqual(report["status"], "REJECTED")
        self.assertIn("risk_decision_not_allow", report["reasons"])

    def test_open_paper_position_revalidates_signal_is_tradable_even_when_risk_allows(self) -> None:
        invalid_signal = {**SIGNAL, "direction": "WATCH_ONLY", "tradable_candidate": False}

        report = open_paper_position(invalid_signal, ALLOW_DECISION, ENRICHMENT)

        self.assertEqual(report["status"], "REJECTED")
        self.assertFalse(report["ok"])
        self.assertIn("signal_not_tradable", report["reasons"])
        self.assertEqual(report["side"], "WATCH_ONLY")

    def test_close_paper_position_calculates_long_pnl(self) -> None:
        opened = open_paper_position(
            SIGNAL, ALLOW_DECISION, ENRICHMENT, requested_notional_usdt=10.0, paper_leverage=2.0
        )

        closed = close_paper_position(opened, exit_price=0.068)

        self.assertEqual(closed["status"], "CLOSED")
        self.assertGreater(closed["pnl_usdt"], 0)
        self.assertAlmostEqual(closed["exit_price"], 0.068)


if __name__ == "__main__":
    unittest.main()
