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
    def test_long_signal_does_not_create_fixed_exit_plan_without_agent_thesis(self) -> None:
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
        self.assertIsNone(intent["error_code"])
        self.assertEqual(intent["action"], "ENTER")
        self.assertEqual(intent["direction"], "LONG")
        self.assertEqual(intent["entry_type"], "MARKET_PAPER")
        self.assertAlmostEqual(intent["entry_price"], 0.062)
        self.assertIsNone(intent["invalidation_price"])
        self.assertIsNone(intent["take_profit_price"])
        self.assertIsNone(intent["max_holding_minutes"])
        self.assertEqual(intent["exit_management"], "agent_managed")
        self.assertEqual(intent["exit_plan_source"], "agent_required_missing")
        self.assertIn("momentum_breakout", intent["strategy_tags"])
        self.assertEqual(intent["provenance"]["source"], "tradecat_auto.strategies.build_strategy_intent")
        self.assertEqual(intent["provenance"]["signal_schema"], "tradecat_auto.signal_score.v1")
        self.assertEqual(intent["provenance"]["enrichment_schema"], "tradecat_auto.market_enrichment.v1")
        self.assertFalse(intent["safety"]["real_orders"])
        self.assertFalse(intent["safety"]["signed_requests"])
        self.assertFalse(intent["safety"]["reads_api_keys"])
        self.assertIn("not an order", " ".join(intent["limitations"]))

    def test_agent_thesis_exit_plan_is_passed_through_without_fixed_defaults(self) -> None:
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
        thesis = {
            "schema": "tradecat_auto.agent_trade_thesis.v1",
            "source": "agent_trade_thesis",
            "invalidation_price": 0.058,
            "take_profit_price": 0.071,
            "max_holding_minutes": 240,
            "exit_rationale": "volatility-adjusted invalidation and target from Agent thesis",
        }

        intent = build_strategy_intent(signal, ENRICHMENT, agent_trade_thesis=thesis)

        self.assertEqual(intent["invalidation_price"], 0.058)
        self.assertEqual(intent["take_profit_price"], 0.071)
        self.assertEqual(intent["max_holding_minutes"], 240.0)
        self.assertEqual(intent["exit_management"], "agent_supplied")
        self.assertEqual(intent["exit_plan_source"], "agent_trade_thesis")
        self.assertEqual(intent["provenance"]["agent_trade_thesis_schema"], "tradecat_auto.agent_trade_thesis.v1")
        self.assertEqual(intent["provenance"]["agent_trade_thesis_source"], "agent_trade_thesis")

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
        self.assertEqual(intent["error_code"], "spread_too_wide")
        self.assertEqual(intent["do_not_trade_reasons"], ["spread_too_wide"])
        self.assertIsNone(intent["entry_price"])


if __name__ == "__main__":
    unittest.main()
