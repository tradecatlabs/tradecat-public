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
        report = open_paper_position(SIGNAL, ALLOW_DECISION, ENRICHMENT, requested_notional_usdt=50.0)

        self.assertEqual(report["schema"], "tradecat_auto.paper_execution_report.v1")
        self.assertEqual(report["status"], "OPENED")
        self.assertEqual(report["symbol"], "IRYSUSDT")
        self.assertEqual(report["side"], "LONG")
        self.assertEqual(report["notional_usdt"], 20.0)
        self.assertAlmostEqual(report["quantity"], 20.0 / 0.062)
        self.assertEqual(report["entry_price"], 0.062)

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
        opened = open_paper_position(SIGNAL, ALLOW_DECISION, ENRICHMENT, requested_notional_usdt=10.0)

        closed = close_paper_position(opened, exit_price=0.068)

        self.assertEqual(closed["status"], "CLOSED")
        self.assertGreater(closed["pnl_usdt"], 0)
        self.assertAlmostEqual(closed["exit_price"], 0.068)


if __name__ == "__main__":
    unittest.main()
