from __future__ import annotations

import copy
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

Transport = Callable[[str], bytes]

DEFAULT_BASE_URL = "https://fapi.binance.com"
USER_AGENT = "tradecat-public/0.1 full-lifecycle-public-readonly-paper"
TRANSIENT_HTTP_STATUSES = {418, 429, 500, 502, 503, 504}
DEFAULT_ENDPOINT_WEIGHT = 1
ENDPOINT_WEIGHTS = {
    "/fapi/v1/depth": 2,
}


class BinanceApiError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, url: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.url = url


def _default_transport(url: str, *, timeout: float, headers: dict[str, str]) -> bytes:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise BinanceApiError(f"HTTP {exc.code}: {body}", status=exc.code, url=url) from exc
    except urllib.error.URLError as exc:
        raise BinanceApiError(f"network error: {exc.reason}", url=url) from exc


def extract_trading_usdt_perpetual_symbols(exchange_info: dict[str, Any]) -> list[str]:
    symbols = exchange_info.get("symbols") if isinstance(exchange_info, dict) else []
    result: list[str] = []
    if not isinstance(symbols, list):
        return result
    for item in symbols:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        if item.get("status") != "TRADING":
            continue
        if item.get("quoteAsset") != "USDT":
            continue
        if item.get("contractType") != "PERPETUAL":
            continue
        result.append(symbol)
    return result


def normalize_to_usdt_perp_symbol(raw_symbol: str, tradable_symbols: set[str] | list[str] | tuple[str, ...]) -> str | None:
    tradable = {str(item).upper().strip() for item in tradable_symbols if str(item).strip()}
    text = str(raw_symbol or "").upper().strip()
    if not text:
        return None
    # Common sheet values are either BTCUSDT or bare base asset such as BTC/IRYS.
    candidates = [text]
    if not text.endswith("USDT"):
        candidates.append(f"{text}USDT")
    for candidate in candidates:
        if candidate in tradable:
            return candidate
    return None


def summarize_depth(depth: dict[str, Any]) -> dict[str, Any]:
    bids = depth.get("bids") if isinstance(depth, dict) else []
    asks = depth.get("asks") if isinstance(depth, dict) else []
    best_bid = _first_price(bids)
    best_ask = _first_price(asks)
    bid_qty = _first_qty(bids)
    ask_qty = _first_qty(asks)
    spread = None
    spread_bps = None
    mid = None
    if best_bid is not None and best_ask is not None:
        spread = best_ask - best_bid
        mid = (best_ask + best_bid) / 2
        if mid:
            spread_bps = spread / mid * 10_000
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "best_bid_qty": bid_qty,
        "best_ask_qty": ask_qty,
        "mid": mid,
        "spread": spread,
        "spread_bps": spread_bps,
        "bid_levels": len(bids) if isinstance(bids, list) else 0,
        "ask_levels": len(asks) if isinstance(asks, list) else 0,
    }


def _first_price(levels: Any) -> float | None:
    if not isinstance(levels, list) or not levels:
        return None
    try:
        return float(levels[0][0])
    except (TypeError, ValueError, IndexError):
        return None


def _first_qty(levels: Any) -> float | None:
    if not isinstance(levels, list) or not levels:
        return None
    try:
        return float(levels[0][1])
    except (TypeError, ValueError, IndexError):
        return None


class BinanceMarketClient:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 15.0,
        transport: Callable[..., bytes] | None = None,
        cache_ttl_seconds: float = 0.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
        sleep_func: Callable[[float], Any] | None = None,
        now_func: Callable[[], float] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport or _default_transport
        self.cache_ttl_seconds = max(0.0, float(cache_ttl_seconds or 0.0))
        self.max_retries = max(0, int(max_retries or 0))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds or 0.0))
        self.sleep_func = sleep_func or time.sleep
        self.now_func = now_func or time.monotonic
        self._cache: dict[str, tuple[float, Any]] = {}
        self._usage = _new_usage()

    def api_usage(self) -> dict[str, Any]:
        return copy.deepcopy(self._usage)

    def reset_api_usage(self) -> None:
        self._usage = _new_usage()

    def request_json(self, path: str, params: dict[str, Any] | None = None, *, cache_ttl_seconds: float | None = None) -> Any:
        clean_path = path if path.startswith("/") else f"/{path}"
        url = self._url(clean_path, params)
        ttl = self.cache_ttl_seconds if cache_ttl_seconds is None else max(0.0, float(cache_ttl_seconds or 0.0))
        if ttl > 0:
            cached = self._cache.get(url)
            if cached and cached[0] >= self.now_func():
                self._usage["cache_hits"] += 1
                return copy.deepcopy(cached[1])
            self._usage["cache_misses"] += 1

        last_exc: Exception | None = None
        for attempt_index in range(self.max_retries + 1):
            self._record_attempt(clean_path)
            try:
                raw = self.transport(url, timeout=self.timeout, headers={"User-Agent": USER_AGENT})
                try:
                    data = json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    raise BinanceApiError(f"invalid JSON from Binance: {exc}", url=url) from exc
                self._record_success(clean_path)
                if ttl > 0:
                    self._cache[url] = (self.now_func() + ttl, copy.deepcopy(data))
                return data
            except BinanceApiError as exc:
                last_exc = exc
                self._record_error(clean_path, exc)
                if attempt_index < self.max_retries and _is_transient(exc):
                    self._usage["retries"] += 1
                    self.sleep_func(self.retry_backoff_seconds * (2**attempt_index))
                    continue
                raise
        assert last_exc is not None
        raise last_exc

    def exchange_info(self) -> dict[str, Any]:
        data = self.request_json("/fapi/v1/exchangeInfo")
        if not isinstance(data, dict):
            raise BinanceApiError("exchangeInfo response is not an object")
        return data

    def market_universe(self) -> dict[str, Any]:
        exchange_info = self.exchange_info()
        symbols = extract_trading_usdt_perpetual_symbols(exchange_info)
        return {
            "schema": "tradecat_auto.market_universe.v1",
            "schema_version": "1.0.0",
            "ok": bool(symbols),
            "error_code": None,
            "real_orders": False,
            "signed_requests": False,
            "reads_api_keys": False,
            "base_url": self.base_url,
            "symbol_count": len(symbols),
            "symbols": symbols,
            "rate_limits": exchange_info.get("rateLimits", []),
            "api_usage": self.api_usage(),
            "provenance": {"source": "binance_usdm_public_exchange_info", "endpoint": "/fapi/v1/exchangeInfo"},
            "safety": _safety_boundary(),
        }

    def fetch_public_market_bundle(self, symbol: str, *, period: str = "5m", depth_limit: int = 5, hist_limit: int = 2) -> dict[str, Any]:
        normalized_symbol = str(symbol or "").upper().strip()
        endpoints: dict[str, tuple[str, dict[str, Any]]] = {
            "ticker24hr": ("/fapi/v1/ticker/24hr", {"symbol": normalized_symbol}),
            "bookTicker": ("/fapi/v1/ticker/bookTicker", {"symbol": normalized_symbol}),
            "depth": ("/fapi/v1/depth", {"symbol": normalized_symbol, "limit": depth_limit}),
            "openInterest": ("/fapi/v1/openInterest", {"symbol": normalized_symbol}),
            "openInterestHist": ("/futures/data/openInterestHist", {"symbol": normalized_symbol, "period": period, "limit": hist_limit}),
            "fundingRate": ("/fapi/v1/fundingRate", {"symbol": normalized_symbol, "limit": 1}),
            "premiumIndex": ("/fapi/v1/premiumIndex", {"symbol": normalized_symbol}),
            "topLongShortAccountRatio": ("/futures/data/topLongShortAccountRatio", {"symbol": normalized_symbol, "period": period, "limit": 1}),
            "topLongShortPositionRatio": ("/futures/data/topLongShortPositionRatio", {"symbol": normalized_symbol, "period": period, "limit": 1}),
            "globalLongShortAccountRatio": ("/futures/data/globalLongShortAccountRatio", {"symbol": normalized_symbol, "period": period, "limit": 1}),
            "takerlongshortRatio": ("/futures/data/takerlongshortRatio", {"symbol": normalized_symbol, "period": period, "limit": 1}),
        }
        bundle: dict[str, Any] = {
            "schema": "tradecat_auto.public_market_bundle.v1",
            "schema_version": "1.0.0",
            "ok": True,
            "error_code": None,
            "real_orders": False,
            "signed_requests": False,
            "reads_api_keys": False,
            "base_url": self.base_url,
            "symbol": normalized_symbol,
            "period": period,
            "errors": {},
            "provenance": {"source": "binance_usdm_public_market_bundle", "endpoint_count": len(endpoints)},
            "safety": _safety_boundary(),
        }
        for name, (endpoint_path, params) in endpoints.items():
            try:
                bundle[name] = self.request_json(endpoint_path, params)
            except Exception as exc:  # keep a probe useful even on partial endpoint failure
                bundle["ok"] = False
                bundle["error_code"] = "public_market_bundle_partial_failure"
                bundle["errors"][name] = f"{type(exc).__name__}: {exc}"
        if isinstance(bundle.get("depth"), dict):
            bundle["depth_summary"] = summarize_depth(bundle["depth"])
        bundle["api_usage"] = self.api_usage()
        return bundle

    def _url(self, path: str, params: dict[str, Any] | None = None) -> str:
        clean_path = path if path.startswith("/") else f"/{path}"
        query = urllib.parse.urlencode({key: value for key, value in (params or {}).items() if value is not None})
        if query:
            return f"{self.base_url}{clean_path}?{query}"
        return f"{self.base_url}{clean_path}"

    def _record_attempt(self, path: str) -> None:
        endpoint = _endpoint_usage(self._usage, path)
        endpoint["requests_attempted"] += 1
        endpoint["request_weight"] += _endpoint_weight(path)
        self._usage["requests_attempted"] += 1
        self._usage["request_weight"] += _endpoint_weight(path)

    def _record_success(self, path: str) -> None:
        endpoint = _endpoint_usage(self._usage, path)
        endpoint["requests_succeeded"] += 1
        self._usage["requests_succeeded"] += 1

    def _record_error(self, path: str, exc: Exception) -> None:
        endpoint = _endpoint_usage(self._usage, path)
        endpoint["requests_failed"] += 1
        status = str(getattr(exc, "status", "unknown") or "unknown")
        endpoint["errors"][status] = int(endpoint["errors"].get(status, 0)) + 1
        self._usage["requests_failed"] += 1
        self._usage["errors"][status] = int(self._usage["errors"].get(status, 0)) + 1


def _new_usage() -> dict[str, Any]:
    return {
        "schema": "tradecat_auto.binance_api_usage.v1",
        "schema_version": "1.0.0",
        "requests_attempted": 0,
        "requests_succeeded": 0,
        "requests_failed": 0,
        "request_weight": 0,
        "retries": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "errors": {},
        "endpoints": {},
    }


def _endpoint_usage(usage: dict[str, Any], path: str) -> dict[str, Any]:
    endpoints = usage.setdefault("endpoints", {})
    if path not in endpoints:
        endpoints[path] = {
            "requests_attempted": 0,
            "requests_succeeded": 0,
            "requests_failed": 0,
            "request_weight": 0,
            "errors": {},
        }
    return endpoints[path]


def _endpoint_weight(path: str) -> int:
    return int(ENDPOINT_WEIGHTS.get(path, DEFAULT_ENDPOINT_WEIGHT))


def _is_transient(exc: BinanceApiError) -> bool:
    return exc.status in TRANSIENT_HTTP_STATUSES or exc.status is None


def _safety_boundary() -> dict[str, bool]:
    return {
        "public_readonly_market_data": True,
        "paper_or_watch_only": True,
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "binance_account_state": False,
    }
