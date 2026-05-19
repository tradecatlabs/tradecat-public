from __future__ import annotations

from typing import Any

from tradecat_auto.safety_boundary import paper_watch_safety_boundary

MIN_TRADABLE_SCORE = 60
MAX_SPREAD_BPS = 10.0
MIN_QUOTE_VOLUME_USDT = 1_000_000.0


def build_signal_score(enrichment: dict[str, Any]) -> dict[str, Any]:
    symbol = str(enrichment.get("symbol") or "").upper().strip()
    if not enrichment.get("ok"):
        return _payload(
            symbol=symbol,
            score=0,
            direction="WATCH_ONLY",
            positive_factors=[],
            negative_factors=[],
            do_not_trade_reasons=["enrichment_not_ok"],
            metrics=enrichment.get("metrics") if isinstance(enrichment.get("metrics"), dict) else {},
            enrichment=enrichment,
        )

    metrics = enrichment.get("metrics") if isinstance(enrichment.get("metrics"), dict) else {}
    score = 0
    positive: list[str] = []
    negative: list[str] = []
    do_not_trade: list[str] = []

    score += 20
    positive.append("sheet_anomaly_present")

    price_change = _num(metrics.get("price_change_24h_pct"))
    if price_change is not None:
        abs_change = abs(price_change)
        if abs_change >= 20:
            score += 20
            positive.append("large_24h_price_move")
        elif abs_change >= 10:
            score += 10
            positive.append("moderate_24h_price_move")

    quote_volume = _num(metrics.get("quote_volume_24h"))
    if quote_volume is not None and quote_volume >= MIN_QUOTE_VOLUME_USDT:
        score += 10
        positive.append("liquid_24h_quote_volume")
    else:
        negative.append("low_quote_volume")

    spread_bps = _num(metrics.get("spread_bps"))
    if spread_bps is not None and spread_bps <= MAX_SPREAD_BPS:
        score += 10
        positive.append("tight_spread")
    else:
        negative.append("spread_too_wide")
        do_not_trade.append("spread_too_wide")

    if (_num(metrics.get("open_interest")) or 0) > 0:
        score += 10
        positive.append("open_interest_available")

    funding_abs = abs(_num(metrics.get("funding_rate_latest")) or 0)
    if funding_abs <= 0.001:
        score += 5
        positive.append("funding_not_extreme")
    else:
        negative.append("funding_extreme")

    long_bias = 0
    short_bias = 0
    taker_ratio = _num(metrics.get("taker_buy_sell_ratio"))
    if taker_ratio is not None:
        if taker_ratio >= 1.05:
            long_bias += 1
            score += 10
            positive.append("taker_buy_bias")
        elif taker_ratio <= 0.95:
            short_bias += 1
            score += 10
            positive.append("taker_sell_bias")

    for key in ("global_long_short_account_ratio", "top_long_short_account_ratio", "top_long_short_position_ratio"):
        ratio = _num(metrics.get(key))
        if ratio is None:
            continue
        if ratio >= 1.05:
            long_bias += 1
            score += 3
            positive.append(f"{key}_long_bias")
        elif ratio <= 0.95:
            short_bias += 1
            score += 3
            positive.append(f"{key}_short_bias")

    direction = "WATCH_ONLY"
    if score >= MIN_TRADABLE_SCORE and not do_not_trade:
        if (price_change or 0) >= 0 and long_bias >= short_bias:
            direction = "LONG"
        elif (price_change or 0) < 0 and short_bias > long_bias:
            direction = "SHORT"
        else:
            do_not_trade.append("direction_conflict")
    else:
        do_not_trade.append("low_score")

    # Ensure low_score is not duplicated and reflects final score.
    if score >= MIN_TRADABLE_SCORE and "low_score" in do_not_trade:
        do_not_trade.remove("low_score")
    do_not_trade = _dedupe(do_not_trade)
    return _payload(
        symbol=symbol,
        score=min(score, 100),
        direction=direction,
        positive_factors=_dedupe(positive),
        negative_factors=_dedupe(negative),
        do_not_trade_reasons=do_not_trade,
        metrics=metrics,
        enrichment=enrichment,
    )


def _payload(
    *,
    symbol: str,
    score: int,
    direction: str,
    positive_factors: list[str],
    negative_factors: list[str],
    do_not_trade_reasons: list[str],
    metrics: dict[str, Any],
    enrichment: dict[str, Any],
) -> dict[str, Any]:
    error_code = do_not_trade_reasons[0] if do_not_trade_reasons else None
    return {
        "schema": "tradecat_auto.signal_score.v1",
        "schema_version": "1.0.0",
        "ok": True,
        "error_code": error_code,
        "symbol": symbol,
        "score": score,
        "direction": direction,
        "tradable_candidate": bool(
            direction in {"LONG", "SHORT"} and score >= MIN_TRADABLE_SCORE and not do_not_trade_reasons
        ),
        "positive_factors": positive_factors,
        "negative_factors": negative_factors,
        "do_not_trade_reasons": do_not_trade_reasons,
        "metrics_used": {
            key: metrics.get(key)
            for key in (
                "price_change_24h_pct",
                "quote_volume_24h",
                "spread_bps",
                "open_interest",
                "funding_rate_latest",
                "taker_buy_sell_ratio",
                "global_long_short_account_ratio",
            )
        },
        "provenance": _provenance(enrichment),
        "safety": paper_watch_safety_boundary(),
        "limitations": ["signal only; not an order and not investment advice"],
    }


def _provenance(enrichment: dict[str, Any]) -> dict[str, Any]:
    enrichment_provenance = enrichment.get("provenance") if isinstance(enrichment.get("provenance"), dict) else {}
    return {
        "source": "tradecat_auto.signals.build_signal_score",
        "enrichment_schema": str(enrichment.get("schema") or ""),
        "enrichment_source": str(enrichment_provenance.get("source") or ""),
    }


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
