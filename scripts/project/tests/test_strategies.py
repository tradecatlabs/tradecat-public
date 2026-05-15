from __future__ import annotations

import unittest

from tradecat_auto.strategies import build_strategy_intent

ENRICHMENT = {
    "schema": "tradecat_auto.market_enrichment.v1",
    "ok": True,
    "symbol": "IRYSUSDT",
    "metrics": {
        "last_price": 0.062,
        "spread_bps": 3.0,
        "price_change_24h_pct": 24.0,
        "taker_buy_sell_ratio": 1.2,
        "global_long_short_account_ratio": 1.1,
    },
}


class StrategyIntentTests(unittest.TestCase):
    def test_long_signal_creates_entry_exit_plan_with_invalidation(self) -> None:
        signal = {
            "schema": "tradecat_auto.signal_score.v1",
            "ok": True,
            "symbol": "IRYSUSDT",
            "score": 84,
            "direction": "LONG",
            "tradable_candidate": True,
            "positive_factors": ["large_24h_price_move", "taker_buy_bias"],
            "negative_factors": [],
            "do_not_trade_reasons": [],
        }

        intent = build_strategy_intent(signal, ENRICHMENT)

        self.assertEqual(intent["schema"], "tradecat_auto.strategy_intent.v1")
        self.assertTrue(intent["ok"])
        self.assertEqual(intent["action"], "ENTER")
        self.assertEqual(intent["direction"], "LONG")
        self.assertEqual(intent["entry_type"], "MARKET_PAPER")
        self.assertAlmostEqual(intent["entry_price"], 0.062)
        self.assertLess(intent["invalidation_price"], intent["entry_price"])
        self.assertGreater(intent["take_profit_price"], intent["entry_price"])
        self.assertIn("momentum_breakout", intent["strategy_tags"])
        self.assertIn("not an order", " ".join(intent["limitations"]))

    def test_watch_only_signal_creates_no_trade_intent_with_reasons(self) -> None:
        signal = {
            "schema": "tradecat_auto.signal_score.v1",
            "ok": True,
            "symbol": "IRYSUSDT",
            "score": 55,
            "direction": "WATCH_ONLY",
            "tradable_candidate": False,
            "positive_factors": [],
            "negative_factors": ["spread_too_wide"],
            "do_not_trade_reasons": ["spread_too_wide"],
        }

        intent = build_strategy_intent(signal, ENRICHMENT)

        self.assertEqual(intent["action"], "WATCH")
        self.assertEqual(intent["direction"], "WATCH_ONLY")
        self.assertEqual(intent["do_not_trade_reasons"], ["spread_too_wide"])
        self.assertIsNone(intent["entry_price"])


if __name__ == "__main__":
    unittest.main()
