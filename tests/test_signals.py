from __future__ import annotations

import unittest

from tradecat_auto.signals import build_signal_score

ENRICHMENT_LONG = {
    "schema": "tradecat_auto.market_enrichment.v1",
    "ok": True,
    "symbol": "IRYSUSDT",
    "metrics": {
        "price_change_24h_pct": 24.564,
        "quote_volume_24h": 118_000_000.0,
        "spread_bps": 3.2,
        "open_interest": 121_000_000.0,
        "funding_rate_latest": 0.00005,
        "taker_buy_sell_ratio": 1.0965,
        "global_long_short_account_ratio": 1.1739,
        "sheet_5m_amount_change_pct": 4.3,
    },
}


class SignalScoreTests(unittest.TestCase):
    def test_build_signal_score_promotes_strong_aligned_momentum_to_long_candidate(self) -> None:
        signal = build_signal_score(ENRICHMENT_LONG)

        self.assertEqual(signal["schema"], "tradecat_auto.signal_score.v1")
        self.assertEqual(signal["schema_version"], "1.0.0")
        self.assertIsNone(signal["error_code"])
        self.assertEqual(signal["symbol"], "IRYSUSDT")
        self.assertGreaterEqual(signal["score"], 60)
        self.assertEqual(signal["direction"], "LONG")
        self.assertTrue(signal["tradable_candidate"])
        self.assertEqual(signal["provenance"]["source"], "tradecat_auto.signals.build_signal_score")
        self.assertEqual(signal["provenance"]["enrichment_schema"], "tradecat_auto.market_enrichment.v1")
        self.assertFalse(signal["safety"]["real_orders"])
        self.assertFalse(signal["safety"]["signed_requests"])
        self.assertFalse(signal["safety"]["reads_api_keys"])
        self.assertIn("sheet_anomaly_present", signal["positive_factors"])
        self.assertNotIn("low_score", signal["do_not_trade_reasons"])

    def test_build_signal_score_keeps_low_or_conflicted_signal_watch_only(self) -> None:
        weak = {
            "schema": "tradecat_auto.market_enrichment.v1",
            "ok": True,
            "symbol": "WEAKUSDT",
            "metrics": {
                "price_change_24h_pct": 1.0,
                "quote_volume_24h": 100_000.0,
                "spread_bps": 25.0,
                "open_interest": 0.0,
                "taker_buy_sell_ratio": 0.7,
            },
        }

        signal = build_signal_score(weak)

        self.assertEqual(signal["direction"], "WATCH_ONLY")
        self.assertFalse(signal["tradable_candidate"])
        self.assertIn(signal["error_code"], signal["do_not_trade_reasons"])
        self.assertIn("spread_too_wide", signal["do_not_trade_reasons"])
        self.assertIn("low_score", signal["do_not_trade_reasons"])

    def test_build_signal_score_marks_missing_enrichment_untradable(self) -> None:
        signal = build_signal_score(
            {
                "schema": "tradecat_auto.market_enrichment.v1",
                "ok": False,
                "symbol": "ERRUSDT",
                "errors": {"depth": "timeout"},
                "provenance": {"source": "unit_fixture"},
            }
        )

        self.assertEqual(signal["score"], 0)
        self.assertEqual(signal["direction"], "WATCH_ONLY")
        self.assertEqual(signal["error_code"], "enrichment_not_ok")
        self.assertEqual(signal["provenance"]["enrichment_source"], "unit_fixture")
        self.assertIn("enrichment_not_ok", signal["do_not_trade_reasons"])


if __name__ == "__main__":
    unittest.main()
