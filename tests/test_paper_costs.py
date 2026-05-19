from __future__ import annotations

from tradecat_auto.paper_costs import build_public_taker_cost_model

DEPTH = {
    "bids": [["99.0", "1.0"], ["98.0", "2.0"]],
    "asks": [["101.0", "1.0"], ["102.0", "2.0"]],
}


def test_public_taker_cost_model_estimates_fill_from_public_depth() -> None:
    model = build_public_taker_cost_model(
        symbol="btcusdt",
        side="LONG",
        action="OPEN",
        notional_usdt=150.0,
        depth=DEPTH,
        fallback_price=100.0,
    )

    assert model["schema"] == "tradecat_auto.paper_execution_cost_model.v1"
    assert model["ok"] is True
    assert model["error_code"] is None
    assert model["symbol"] == "BTCUSDT"
    assert model["book_side"] == "asks"
    assert model["price_source"] == "binance_usdm_public_order_book_depth"
    assert model["fill_price_includes_slippage"] is True
    assert model["depth_estimated"] is True
    assert model["estimated_fill_price"] > 101.0
    assert model["safety"]["real_orders"] is False
    assert model["safety"]["signed_requests"] is False
    assert model["safety"]["reads_api_keys"] is False


def test_public_taker_cost_model_uses_configured_fallback_slippage_when_depth_unavailable() -> None:
    model = build_public_taker_cost_model(
        symbol="ETHUSDT",
        side="SHORT",
        action="OPEN",
        notional_usdt=100.0,
        depth={},
        fallback_price=100.0,
        fallback_slippage_bps=10.0,
    )

    assert model["ok"] is True
    assert model["error_code"] == "paper_cost_depth_fallback_used"
    assert model["book_side"] == "bids"
    assert model["price_source"] == "fallback_price_with_configured_slippage"
    assert model["estimated_fill_price"] == 99.9
    assert model["fill_price_includes_slippage"] is True


def test_public_taker_cost_model_fails_closed_without_agent_notional_or_valid_side() -> None:
    missing_notional = build_public_taker_cost_model(
        symbol="BTCUSDT",
        side="LONG",
        action="OPEN",
        notional_usdt=None,
        depth=DEPTH,
    )
    invalid_side = build_public_taker_cost_model(
        symbol="BTCUSDT",
        side="WATCH_ONLY",
        action="OPEN",
        notional_usdt=100.0,
        depth=DEPTH,
    )

    assert missing_notional["ok"] is False
    assert missing_notional["error_code"] == "paper_cost_notional_required"
    assert invalid_side["ok"] is False
    assert invalid_side["error_code"] == "paper_cost_side_required"
