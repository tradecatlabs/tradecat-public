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
        has_symbol = "symbol" in query
        symbol = query.get("symbol", ["BTCUSDT"])[0]
        if parsed.path == "/fapi/v1/exchangeInfo":
            return json.dumps(
                {
                    "symbols": [
                        {"symbol": "BTCUSDT", "status": "TRADING", "quoteAsset": "USDT", "contractType": "PERPETUAL"},
                        {"symbol": "ETHUSDT", "status": "TRADING", "quoteAsset": "USDT", "contractType": "PERPETUAL"},
                        {
                            "symbol": "BTCDOMUSDT",
                            "status": "TRADING",
                            "quoteAsset": "USDT",
                            "contractType": "PERPETUAL",
                        },
                        {"symbol": "BTCUSDC", "status": "TRADING", "quoteAsset": "USDC", "contractType": "PERPETUAL"},
                        {"symbol": "OLDUSDT", "status": "BREAK", "quoteAsset": "USDT", "contractType": "PERPETUAL"},
                        {
                            "symbol": "BTCUSDT_260626",
                            "status": "TRADING",
                            "quoteAsset": "USDT",
                            "contractType": "CURRENT_QUARTER",
                        },
                    ],
                    "rateLimits": [{"rateLimitType": "REQUEST_WEIGHT", "interval": "MINUTE", "limit": 2400}],
                }
            ).encode()
        if parsed.path == "/fapi/v1/ticker/24hr":
            if not has_symbol:
                return json.dumps(
                    [
                        {"symbol": "BTCUSDT", "lastPrice": "100.0", "priceChangePercent": "1.23"},
                        {"symbol": "ETHUSDT", "lastPrice": "3000.0", "priceChangePercent": "-0.50"},
                    ]
                ).encode()
            return json.dumps({"symbol": symbol, "lastPrice": "100.0", "priceChangePercent": "1.23"}).encode()
        if parsed.path == "/fapi/v1/ticker/price":
            if not has_symbol:
                return json.dumps(
                    [
                        {"symbol": "BTCUSDT", "price": "100.0", "time": 1700000000000},
                        {"symbol": "ETHUSDT", "price": "3000.0", "time": 1700000000000},
                    ]
                ).encode()
            return json.dumps({"symbol": symbol, "price": "100.0", "time": 1700000000000}).encode()
        if parsed.path == "/fapi/v1/ticker/bookTicker":
            if not has_symbol:
                return json.dumps(
                    [
                        {
                            "symbol": "BTCUSDT",
                            "bidPrice": "99.9",
                            "bidQty": "10",
                            "askPrice": "100.1",
                            "askQty": "11",
                        },
                        {
                            "symbol": "ETHUSDT",
                            "bidPrice": "2999.0",
                            "bidQty": "5",
                            "askPrice": "3001.0",
                            "askQty": "6",
                        },
                    ]
                ).encode()
            return json.dumps(
                {"symbol": symbol, "bidPrice": "99.9", "bidQty": "10", "askPrice": "100.1", "askQty": "11"}
            ).encode()
        if parsed.path == "/fapi/v1/depth":
            return json.dumps(
                {"bids": [["99.9", "10"], ["99.8", "5"]], "asks": [["100.1", "8"], ["100.2", "6"]]}
            ).encode()
        if parsed.path == "/fapi/v1/openInterest":
            return json.dumps({"symbol": symbol, "openInterest": "12345.6", "time": 1700000000000}).encode()
        if parsed.path == "/futures/data/openInterestHist":
            return json.dumps(
                [
                    {
                        "symbol": symbol,
                        "sumOpenInterest": "100",
                        "sumOpenInterestValue": "10000",
                        "timestamp": 1700000000000,
                    }
                ]
            ).encode()
        if parsed.path == "/fapi/v1/fundingRate":
            return json.dumps([{"symbol": symbol, "fundingRate": "0.0001", "fundingTime": 1700000000000}]).encode()
        if parsed.path == "/fapi/v1/premiumIndex":
            if not has_symbol:
                return json.dumps(
                    [
                        {"symbol": "BTCUSDT", "markPrice": "100", "indexPrice": "99.8", "lastFundingRate": "0.0001"},
                        {
                            "symbol": "ETHUSDT",
                            "markPrice": "3000",
                            "indexPrice": "2999",
                            "lastFundingRate": "0.0002",
                        },
                    ]
                ).encode()
            return json.dumps(
                {"symbol": symbol, "markPrice": "100", "indexPrice": "99.8", "lastFundingRate": "0.0001"}
            ).encode()
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
        self.assertFalse(bundle["real_orders"])
        self.assertFalse(bundle["signed_requests"])
        self.assertFalse(bundle["reads_api_keys"])
        self.assertEqual(bundle["provenance"]["source"], "binance_usdm_public_market_bundle")
        self.assertFalse(bundle["safety"]["binance_account_state"])
        self.assertGreaterEqual(len(transport.calls), 10)

    def test_client_fetches_lightweight_last_price_for_mark_to_market(self) -> None:
        transport = FakeTransport()
        client = BinanceMarketClient(base_url="https://example.test", transport=transport)

        payload = client.fetch_last_price("BTCUSDT")

        self.assertEqual(payload["schema"], "tradecat_auto.public_last_price.v1")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["last_price"], 100.0)
        self.assertFalse(payload["real_orders"])
        self.assertFalse(payload["signed_requests"])
        self.assertFalse(payload["reads_api_keys"])
        self.assertEqual(urlparse(transport.calls[-1]).path, "/fapi/v1/ticker/price")

    def test_client_fetches_batch_last_prices_with_one_public_request(self) -> None:
        transport = FakeTransport()
        client = BinanceMarketClient(base_url="https://example.test", transport=transport)

        payload = client.fetch_last_prices(["BTCUSDT", "ETHUSDT"])

        self.assertEqual(payload["schema"], "tradecat_auto.public_last_prices.v1")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["prices"], {"BTCUSDT": 100.0, "ETHUSDT": 3000.0})
        self.assertEqual(payload["missing_symbols"], [])
        self.assertFalse(payload["real_orders"])
        self.assertFalse(payload["signed_requests"])
        self.assertFalse(payload["reads_api_keys"])
        price_calls = [url for url in transport.calls if urlparse(url).path == "/fapi/v1/ticker/price"]
        self.assertEqual(len(price_calls), 1)
        self.assertNotIn("symbol=", price_calls[0])

    def test_client_fetches_batch_market_snapshot_for_batchable_endpoint_families(self) -> None:
        transport = FakeTransport()
        client = BinanceMarketClient(base_url="https://example.test", transport=transport)

        payload = client.fetch_public_market_snapshot(["BTCUSDT", "ETHUSDT"])

        self.assertEqual(payload["schema"], "tradecat_auto.public_market_snapshot.v1")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["symbols"], ["BTCUSDT", "ETHUSDT"])
        self.assertEqual(payload["prices"]["ETHUSDT"], 3000.0)
        self.assertEqual(payload["ticker24hr"]["BTCUSDT"]["lastPrice"], "100.0")
        self.assertEqual(payload["bookTicker"]["ETHUSDT"]["askPrice"], "3001.0")
        self.assertIn("open_interest", payload["per_symbol_endpoint_families"])
        self.assertFalse(payload["real_orders"])
        self.assertFalse(payload["signed_requests"])
        self.assertFalse(payload["reads_api_keys"])
        paths = [urlparse(url).path for url in transport.calls]
        self.assertEqual(paths.count("/fapi/v1/ticker/price"), 1)
        self.assertEqual(paths.count("/fapi/v1/ticker/24hr"), 1)
        self.assertEqual(paths.count("/fapi/v1/ticker/bookTicker"), 1)
        self.assertEqual(paths.count("/fapi/v1/premiumIndex"), 1)

    def test_market_universe_uses_ttl_cache_and_reports_usage(self) -> None:
        transport = FakeTransport()
        client = BinanceMarketClient(base_url="https://example.test", transport=transport, cache_ttl_seconds=60)

        first = client.market_universe()
        second = client.market_universe()

        self.assertEqual(first["symbol_count"], 3)
        self.assertEqual(second["symbol_count"], 3)
        self.assertFalse(first["real_orders"])
        self.assertFalse(first["signed_requests"])
        self.assertFalse(first["reads_api_keys"])
        self.assertEqual(first["provenance"]["endpoint"], "/fapi/v1/exchangeInfo")
        self.assertFalse(first["safety"]["binance_account_state"])
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
