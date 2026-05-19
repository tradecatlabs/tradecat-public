from __future__ import annotations

import unittest

from tradecat_auto.market_enrichment import build_market_enrichment, parse_percent

ANOMALY = {
    "raw_symbol": "IRYS",
    "normalized_symbol": "IRYSUSDT",
    "source_values": {
        "交易对": "IRYS",
        "5m量变化率": "-1.84%",
        "5m额变化率": "-5.298%",
        "量异常强度": "-5.166",
        "额异常强度": "-6.098",
        "现持仓额": "7476046.79",
    },
}

MARKET_BUNDLE = {
    "schema": "tradecat_auto.public_market_bundle.v1",
    "ok": True,
    "symbol": "IRYSUSDT",
    "ticker24hr": {"lastPrice": "0.0620700", "priceChangePercent": "24.564", "quoteVolume": "118133071.9522760"},
    "depth_summary": {"spread_bps": 3.218, "best_bid": 0.06214, "best_ask": 0.06216},
    "openInterest": {"openInterest": "121513878", "time": 1778647615811},
    "openInterestHist": [
        {"sumOpenInterest": "120000000", "sumOpenInterestValue": "7429024.43008000", "timestamp": 1778647200000},
        {"sumOpenInterest": "121000000", "sumOpenInterestValue": "7510000.00000000", "timestamp": 1778647500000},
    ],
    "fundingRate": [{"fundingRate": "0.00005000", "fundingTime": 1778644800003}],
    "premiumIndex": {"markPrice": "0.06211000", "indexPrice": "0.06201964", "lastFundingRate": "0.00005000"},
    "topLongShortAccountRatio": [{"longShortRatio": "1.0559", "timestamp": 1778647500000}],
    "topLongShortPositionRatio": [{"longShortRatio": "1.1564", "timestamp": 1778647500000}],
    "globalLongShortAccountRatio": [{"longShortRatio": "1.1739", "timestamp": 1778647500000}],
    "takerlongshortRatio": [{"buySellRatio": "1.0965", "timestamp": 1778646900000}],
    "errors": {},
}


class MarketEnrichmentTests(unittest.TestCase):
    def test_parse_percent_accepts_percent_sign_and_plain_number(self) -> None:
        self.assertEqual(parse_percent("-1.84%"), -1.84)
        self.assertEqual(parse_percent("24.564"), 24.564)
        self.assertIsNone(parse_percent(""))

    def test_build_market_enrichment_extracts_sheet_and_binance_metrics(self) -> None:
        payload = build_market_enrichment(ANOMALY, MARKET_BUNDLE)

        self.assertEqual(payload["schema"], "tradecat_auto.market_enrichment.v1")
        self.assertTrue(payload["ok"])
        self.assertIsNone(payload["error_code"])
        self.assertEqual(payload["symbol"], "IRYSUSDT")
        metrics = payload["metrics"]
        self.assertEqual(metrics["sheet_5m_volume_change_pct"], -1.84)
        self.assertEqual(metrics["price_change_24h_pct"], 24.564)
        self.assertEqual(metrics["last_price"], 0.06207)
        self.assertEqual(metrics["quote_volume_24h"], 118133071.952276)
        self.assertEqual(metrics["spread_bps"], 3.218)
        self.assertEqual(metrics["open_interest"], 121513878.0)
        self.assertEqual(metrics["open_interest_value_latest"], 7510000.0)
        self.assertEqual(metrics["funding_rate_latest"], 0.00005)
        self.assertGreater(metrics["mark_index_basis_bps"], 0)
        self.assertEqual(metrics["top_long_short_position_ratio"], 1.1564)
        self.assertIn("binance_public_market", payload["source_layers"])
        self.assertEqual(payload["provenance"]["source"], "tradecat_auto.market_enrichment.build_market_enrichment")
        self.assertEqual(payload["provenance"]["market_bundle_schema"], "tradecat_auto.public_market_bundle.v1")
        self.assertFalse(payload["safety"]["real_orders"])
        self.assertFalse(payload["safety"]["signed_requests"])
        self.assertFalse(payload["safety"]["reads_api_keys"])

    def test_build_market_enrichment_preserves_endpoint_errors(self) -> None:
        broken = dict(MARKET_BUNDLE)
        broken["ok"] = False
        broken["errors"] = {"depth": "timeout"}
        broken["provenance"] = {"source": "unit_public_bundle"}

        payload = build_market_enrichment(ANOMALY, broken)

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_code"], "market_bundle_not_ok")
        self.assertEqual(payload["errors"], {"depth": "timeout"})
        self.assertEqual(payload["provenance"]["market_bundle_source"], "unit_public_bundle")

    def test_build_market_enrichment_reports_missing_required_metrics(self) -> None:
        missing = dict(MARKET_BUNDLE)
        missing["depth_summary"] = {}

        payload = build_market_enrichment(ANOMALY, missing)

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_code"], "missing_required_metrics")
        self.assertEqual(payload["errors"]["missing_required_metrics"], "spread_bps")


if __name__ == "__main__":
    unittest.main()
