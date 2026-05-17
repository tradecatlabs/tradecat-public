from __future__ import annotations

from typing import Any


def parse_float(value: Any) -> float | None:
    text = str(value if value is not None else "").strip().replace(",", "")
    if not text:
        return None
    if text.endswith("%"):
        text = text[:-1].strip()
    try:
        return float(text)
    except ValueError:
        return None


def parse_percent(value: Any) -> float | None:
    return parse_float(value)


def build_market_enrichment(anomaly_symbol: dict[str, Any], market_bundle: dict[str, Any]) -> dict[str, Any]:
    symbol = str(anomaly_symbol.get("normalized_symbol") or market_bundle.get("symbol") or "").upper().strip()
    source_values = anomaly_symbol.get("source_values") if isinstance(anomaly_symbol.get("source_values"), dict) else {}
    metrics = _sheet_metrics(source_values)
    metrics.update(_market_metrics(market_bundle))
    errors = dict(market_bundle.get("errors") or {}) if isinstance(market_bundle.get("errors"), dict) else {}
    missing_required = [name for name in ("last_price", "spread_bps", "open_interest") if metrics.get(name) is None]
    if missing_required:
        errors.setdefault("missing_required_metrics", ",".join(missing_required))
    return {
        "schema": "tradecat_auto.market_enrichment.v1",
        "schema_version": "1.0.0",
        "ok": bool(market_bundle.get("ok") and symbol and not missing_required),
        "symbol": symbol,
        "raw_symbol": anomaly_symbol.get("raw_symbol"),
        "source_layers": ["tradecat_anomaly_panel", "binance_public_market"],
        "source_values": source_values,
        "metrics": metrics,
        "errors": errors,
        "limitations": [
            "public market enrichment only; no account, no position, no orders",
            "not investment advice and not an execution instruction",
        ],
    }


def _sheet_metrics(source_values: dict[str, Any]) -> dict[str, float | None]:
    return {
        "sheet_5m_volume_change_pct": parse_percent(source_values.get("5m量变化率")),
        "sheet_5m_amount_change_pct": parse_percent(source_values.get("5m额变化率")),
        "sheet_volume_amount_divergence_pct": parse_percent(source_values.get("量额背离")),
        "sheet_volume_anomaly_strength": parse_float(source_values.get("量异常强度")),
        "sheet_amount_anomaly_strength": parse_float(source_values.get("额异常强度")),
        "sheet_open_interest_value": parse_float(source_values.get("现持仓额")),
    }


def _market_metrics(market_bundle: dict[str, Any]) -> dict[str, float | None]:
    ticker = market_bundle.get("ticker24hr") if isinstance(market_bundle.get("ticker24hr"), dict) else {}
    depth_summary = market_bundle.get("depth_summary") if isinstance(market_bundle.get("depth_summary"), dict) else {}
    open_interest = market_bundle.get("openInterest") if isinstance(market_bundle.get("openInterest"), dict) else {}
    oi_hist_latest = _latest(market_bundle.get("openInterestHist"))
    funding_latest = _latest(market_bundle.get("fundingRate"))
    premium = market_bundle.get("premiumIndex") if isinstance(market_bundle.get("premiumIndex"), dict) else {}
    top_account = _latest(market_bundle.get("topLongShortAccountRatio"))
    top_position = _latest(market_bundle.get("topLongShortPositionRatio"))
    global_ratio = _latest(market_bundle.get("globalLongShortAccountRatio"))
    taker = _latest(market_bundle.get("takerlongshortRatio"))

    mark_price = parse_float(premium.get("markPrice"))
    index_price = parse_float(premium.get("indexPrice"))
    basis_bps = None
    if mark_price is not None and index_price:
        basis_bps = (mark_price - index_price) / index_price * 10_000

    return {
        "last_price": parse_float(ticker.get("lastPrice")),
        "price_change_24h_pct": parse_percent(ticker.get("priceChangePercent")),
        "base_volume_24h": parse_float(ticker.get("volume")),
        "quote_volume_24h": parse_float(ticker.get("quoteVolume")),
        "best_bid": parse_float(depth_summary.get("best_bid")),
        "best_ask": parse_float(depth_summary.get("best_ask")),
        "spread_bps": parse_float(depth_summary.get("spread_bps")),
        "open_interest": parse_float(open_interest.get("openInterest")),
        "open_interest_value_latest": parse_float(oi_hist_latest.get("sumOpenInterestValue")),
        "funding_rate_latest": parse_float(funding_latest.get("fundingRate")),
        "mark_price": mark_price,
        "index_price": index_price,
        "mark_index_basis_bps": basis_bps,
        "top_long_short_account_ratio": parse_float(top_account.get("longShortRatio")),
        "top_long_short_position_ratio": parse_float(top_position.get("longShortRatio")),
        "global_long_short_account_ratio": parse_float(global_ratio.get("longShortRatio")),
        "taker_buy_sell_ratio": parse_float(taker.get("buySellRatio")),
    }


def _latest(value: Any) -> dict[str, Any]:
    if isinstance(value, list) and value:
        item = value[-1]
        return item if isinstance(item, dict) else {}
    return {}
