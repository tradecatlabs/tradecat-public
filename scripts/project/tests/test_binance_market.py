from __future__ import annotations

import json
import unittest
from urllib.parse import parse_qs, urlparse

from tradecat_auto.binance_market import (
    BinanceApiError,
    BinanceMarketClient,
    extract_trading_usdt_perpetual_symbols,
    normalize_to_usdt_perp_symbol,
    summarize_depth,
)


class FakeTransport:
    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, url: str, *, timeout: float, headers: dict[str, str]) -> bytes:
        self.calls.append(url)
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        symbol = query.get("symbol", ["BTCUSDT"])[0]
        if parsed.path == "/fapi/v1/exchangeInfo":
            return json.dumps(
                {
                    "symbols": [
                        {"symbol": "BTCUSDT", "status": "TRADING", "quoteAsset": "USDT", "contractType": "PERPETUAL"},
                        {"symbol": "ETHUSDT", "status": "TRADING", "quoteAsset": "USDT", "contractType": "PERPETUAL"},
                        {"symbol": "BTCDOMUSDT", "status": "TRADING", "quoteAsset": "USDT", "contractType": "PERPETUAL"},
                        {"symbol": "BTCUSDC", "status": "TRADING", "quoteAsset": "USDC", "contractType": "PERPETUAL"},
                        {"symbol": "OLDUSDT", "status": "BREAK", "quoteAsset": "USDT", "contractType": "PERPETUAL"},
                        {"symbol": "BTCUSDT_260626", "status": "TRADING", "quoteAsset": "USDT", "contractType": "CURRENT_QUARTER"},
                    ],
                    "rateLimits": [{"rateLimitType": "REQUEST_WEIGHT", "interval": "MINUTE", "limit": 2400}],
                }
            ).encode()
        if parsed.path == "/fapi/v1/ticker/24hr":
            return json.dumps({"symbol": symbol, "lastPrice": "100.0", "priceChangePercent": "1.23"}).encode()
        if parsed.path == "/fapi/v1/ticker/bookTicker":
            return json.dumps({"symbol": symbol, "bidPrice": "99.9", "bidQty": "10", "askPrice": "100.1", "askQty": "11"}).encode()
        if parsed.path == "/fapi/v1/depth":
            return json.dumps({"bids": [["99.9", "10"], ["99.8", "5"]], "asks": [["100.1", "8"], ["100.2", "6"]]}).encode()
        if parsed.path == "/fapi/v1/openInterest":
            return json.dumps({"symbol": symbol, "openInterest": "12345.6", "time": 1700000000000}).encode()
        if parsed.path == "/futures/data/openInterestHist":
            return json.dumps([{"symbol": symbol, "sumOpenInterest": "100", "sumOpenInterestValue": "10000", "timestamp": 1700000000000}]).encode()
        if parsed.path == "/fapi/v1/fundingRate":
            return json.dumps([{"symbol": symbol, "fundingRate": "0.0001", "fundingTime": 1700000000000}]).encode()
        if parsed.path == "/fapi/v1/premiumIndex":
            return json.dumps({"symbol": symbol, "markPrice": "100", "indexPrice": "99.8", "lastFundingRate": "0.0001"}).encode()
        if parsed.path in {
            "/futures/data/topLongShortAccountRatio",
            "/futures/data/topLongShortPositionRatio",
            "/futures/data/globalLongShortAccountRatio",
            "/futures/data/takerlongshortRatio",
        }:
            return json.dumps([{"symbol": symbol, "longShortRatio": "1.1", "timestamp": 1700000000000}]).encode()
        raise AssertionError(f"unexpected url: {url}")


class BinanceMarketTests(unittest.TestCase):
    def test_extracts_only_trading_usdt_perpetual_symbols(self) -> None:
        payload = json.loads(FakeTransport()("https://example.test/fapi/v1/exchangeInfo", timeout=1, headers={}))

        symbols = extract_trading_usdt_perpetual_symbols(payload)

        self.assertEqual(symbols, ["BTCUSDT", "ETHUSDT", "BTCDOMUSDT"])

    def test_normalizes_sheet_symbols_to_tradable_usdt_perp_symbols(self) -> None:
        tradable = {"BTCUSDT", "IRYSUSDT"}

        self.assertEqual(normalize_to_usdt_perp_symbol("BTC", tradable), "BTCUSDT")
        self.assertEqual(normalize_to_usdt_perp_symbol("irys", tradable), "IRYSUSDT")
        self.assertEqual(normalize_to_usdt_perp_symbol("BTCUSDT", tradable), "BTCUSDT")
        self.assertIsNone(normalize_to_usdt_perp_symbol("NOPE", tradable))

    def test_summarizes_depth_spread_and_top_liquidity(self) -> None:
        summary = summarize_depth({"bids": [["99.9", "10"]], "asks": [["100.1", "8"]]})

        self.assertEqual(summary["best_bid"], 99.9)
        self.assertEqual(summary["best_ask"], 100.1)
        self.assertAlmostEqual(summary["spread"], 0.2)
        self.assertGreater(summary["spread_bps"], 0)

    def test_client_builds_public_market_bundle_with_expected_endpoint_results(self) -> None:
        transport = FakeTransport()
        client = BinanceMarketClient(base_url="https://example.test", transport=transport)

        bundle = client.fetch_public_market_bundle("BTCUSDT")

        self.assertEqual(bundle["schema"], "tradecat_auto.public_market_bundle.v1")
        self.assertEqual(bundle["symbol"], "BTCUSDT")
        self.assertTrue(bundle["ok"])
        self.assertEqual(bundle["ticker24hr"]["lastPrice"], "100.0")
        self.assertEqual(bundle["openInterest"]["openInterest"], "12345.6")
        self.assertIn("depth_summary", bundle)
        self.assertIn("api_usage", bundle)
        self.assertGreaterEqual(len(transport.calls), 10)

    def test_market_universe_uses_ttl_cache_and_reports_usage(self) -> None:
        transport = FakeTransport()
        client = BinanceMarketClient(base_url="https://example.test", transport=transport, cache_ttl_seconds=60)

        first = client.market_universe()
        second = client.market_universe()

        self.assertEqual(first["symbol_count"], 3)
        self.assertEqual(second["symbol_count"], 3)
        exchange_info_calls = [url for url in transport.calls if urlparse(url).path == "/fapi/v1/exchangeInfo"]
        self.assertEqual(len(exchange_info_calls), 1)
        self.assertGreaterEqual(second["api_usage"]["cache_hits"], 1)

    def test_request_json_retries_transient_errors_and_records_usage(self) -> None:
        attempts: list[str] = []
        sleeps: list[float] = []

        def flaky_transport(url: str, *, timeout: float, headers: dict[str, str]) -> bytes:
            attempts.append(url)
            if len(attempts) == 1:
                raise BinanceApiError("too many requests", status=429, url=url)
            return json.dumps({"serverTime": 1700000000000}).encode()

        client = BinanceMarketClient(
            base_url="https://example.test",
            transport=flaky_transport,
            max_retries=1,
            retry_backoff_seconds=0.25,
            sleep_func=sleeps.append,
        )

        payload = client.request_json("/fapi/v1/time")

        self.assertEqual(payload["serverTime"], 1700000000000)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(sleeps, [0.25])
        usage = client.api_usage()
        self.assertEqual(usage["requests_attempted"], 2)
        self.assertEqual(usage["retries"], 1)
        self.assertIn("/fapi/v1/time", usage["endpoints"])


if __name__ == "__main__":
    unittest.main()
