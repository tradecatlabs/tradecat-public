from __future__ import annotations

from typing import Any

SCHEMA_VERSION = "1.0.0"
PAPER_COST_MODEL_SCHEMA = "tradecat_auto.paper_execution_cost_model.v1"
BINANCE_USDM_PUBLIC_TAKER_FEE_BPS = 4.0
BINANCE_USDM_PUBLIC_MAKER_FEE_BPS = 2.0
DEFAULT_PAPER_SLIPPAGE_BPS = 0.0
BINANCE_USDM_TAKER_FEE_MODEL = "binance_usdm_public_docs_vip0_taker_fallback"


def build_public_taker_cost_model(
    *,
    symbol: str,
    side: str,
    action: str,
    notional_usdt: Any,
    depth: Any,
    fallback_price: Any = None,
    fee_bps: Any = BINANCE_USDM_PUBLIC_TAKER_FEE_BPS,
    fallback_slippage_bps: Any = DEFAULT_PAPER_SLIPPAGE_BPS,
) -> dict[str, Any]:
    """Estimate paper execution cost from public Binance USD-M depth.

    This intentionally does not call the signed commission endpoint. The fee
    fallback is the public Binance USD-M documentation example for VIP0 taker
    commission, while the fill price is estimated from public order-book depth
    whenever the supplied bundle contains enough levels.
    """

    normalized_symbol = str(symbol or "").upper().strip()
    normalized_side = str(side or "").upper().strip()
    normalized_action = str(action or "OPEN").upper().strip()
    notional = _positive_float(notional_usdt)
    configured_fee_bps = _non_negative_float(fee_bps, BINANCE_USDM_PUBLIC_TAKER_FEE_BPS)
    configured_fallback_slippage_bps = _non_negative_float(fallback_slippage_bps, DEFAULT_PAPER_SLIPPAGE_BPS)
    buying = (normalized_action == "OPEN" and normalized_side == "LONG") or (
        normalized_action == "CLOSE" and normalized_side == "SHORT"
    )
    book_side = "asks" if buying else "bids"
    base = {
        "schema": PAPER_COST_MODEL_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "error_code": "paper_cost_model_unavailable",
        "symbol": normalized_symbol,
        "side": normalized_side,
        "action": normalized_action,
        "liquidity_role": "taker",
        "book_side": book_side,
        "requested_notional_usdt": notional,
        "fee_bps": configured_fee_bps,
        "maker_fee_bps": BINANCE_USDM_PUBLIC_MAKER_FEE_BPS,
        "taker_fee_bps": BINANCE_USDM_PUBLIC_TAKER_FEE_BPS,
        "fee_model": BINANCE_USDM_TAKER_FEE_MODEL,
        "fee_source": "binance_usdm_user_commission_rate_docs_example_no_signed_lookup",
        "fallback_slippage_bps": configured_fallback_slippage_bps,
        "fill_price_includes_slippage": False,
        "depth_estimated": False,
        "provenance": {
            "source": "binance_usdm_public_order_book_depth",
            "endpoint": "/fapi/v1/depth",
            "commission_reference_endpoint": "/fapi/v1/commissionRate",
            "commission_reference_requires_signed_user_data": True,
        },
        "safety": _safety_boundary(),
        "limitations": [
            "public order-book estimate only; no real order was placed",
            "does not query signed account commission rate",
            "actual account VIP/BNB/symbol discounts can differ and must be supplied by a private executor if needed",
        ],
    }
    if notional is None:
        return {**base, "error_code": "paper_cost_notional_required"}
    if normalized_side not in {"LONG", "SHORT"}:
        return {**base, "error_code": "paper_cost_side_required"}
    levels = _levels(depth, book_side)
    best_bid, best_ask = _best_bid_ask(depth)
    mid = (best_bid + best_ask) / 2 if best_bid is not None and best_ask is not None else None
    if levels and mid and mid > 0:
        fill = _consume_quote_notional(levels, notional)
        if fill is not None:
            estimated_price, estimated_quantity = fill
            best_price = best_ask if buying else best_bid
            spread_bps = (
                ((best_ask - best_bid) / mid * 10_000) if best_bid is not None and best_ask is not None else None
            )
            slippage_bps_vs_mid = (
                (estimated_price - mid) / mid * 10_000 if buying else (mid - estimated_price) / mid * 10_000
            )
            depth_impact_bps = None
            if best_price is not None:
                depth_impact_bps = (
                    (estimated_price - best_price) / mid * 10_000
                    if buying
                    else (best_price - estimated_price) / mid * 10_000
                )
            return {
                **base,
                "ok": True,
                "error_code": None,
                "price_source": "binance_usdm_public_order_book_depth",
                "best_bid": best_bid,
                "best_ask": best_ask,
                "mid_price": mid,
                "spread_bps": spread_bps,
                "estimated_fill_price": estimated_price,
                "estimated_quantity": estimated_quantity,
                "estimated_notional_usdt": notional,
                "slippage_bps_vs_mid": slippage_bps_vs_mid,
                "depth_impact_bps_over_best": depth_impact_bps,
                "fill_price_includes_slippage": True,
                "depth_estimated": True,
            }
    fallback = _positive_float(fallback_price)
    if fallback is None:
        return {**base, "error_code": "paper_cost_depth_unavailable"}
    fallback_fill = _slipped_price(fallback, buying=buying, slippage_bps=configured_fallback_slippage_bps)
    return {
        **base,
        "ok": True,
        "error_code": "paper_cost_depth_fallback_used",
        "price_source": "fallback_price_with_configured_slippage",
        "estimated_fill_price": fallback_fill,
        "estimated_quantity": notional / fallback_fill if fallback_fill > 0 else None,
        "estimated_notional_usdt": notional,
        "slippage_bps_vs_mid": configured_fallback_slippage_bps,
        "fill_price_includes_slippage": True,
    }


def _levels(depth: Any, side: str) -> list[tuple[float, float]]:
    if not isinstance(depth, dict):
        return []
    raw_levels = depth.get(side)
    if not isinstance(raw_levels, list):
        return []
    levels: list[tuple[float, float]] = []
    for item in raw_levels:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        price = _positive_float(item[0])
        quantity = _positive_float(item[1])
        if price is not None and quantity is not None:
            levels.append((price, quantity))
    return levels


def _best_bid_ask(depth: Any) -> tuple[float | None, float | None]:
    bids = _levels(depth, "bids")
    asks = _levels(depth, "asks")
    best_bid = bids[0][0] if bids else None
    best_ask = asks[0][0] if asks else None
    return best_bid, best_ask


def _consume_quote_notional(levels: list[tuple[float, float]], notional: float) -> tuple[float, float] | None:
    remaining = notional
    quantity = 0.0
    filled_notional = 0.0
    for price, available_quantity in levels:
        level_notional = price * available_quantity
        take_notional = min(remaining, level_notional)
        if take_notional <= 0:
            continue
        quantity += take_notional / price
        filled_notional += take_notional
        remaining -= take_notional
        if remaining <= 1e-9:
            break
    if remaining > 1e-6 or quantity <= 0:
        return None
    return filled_notional / quantity, quantity


def _slipped_price(price: float, *, buying: bool, slippage_bps: float) -> float:
    slip = max(0.0, float(slippage_bps or 0.0)) / 10_000
    return price * (1 + slip if buying else 1 - slip)


def _positive_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _non_negative_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _safety_boundary() -> dict[str, bool]:
    return {
        "public_readonly_market_data": True,
        "paper_or_watch_only": True,
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "binance_account_state": False,
    }
