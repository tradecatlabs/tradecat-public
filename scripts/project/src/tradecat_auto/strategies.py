from __future__ import annotations

from typing import Any


def build_strategy_intent(
    signal: dict[str, Any],
    enrichment: dict[str, Any],
    *,
    agent_trade_thesis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    symbol = str(signal.get("symbol") or enrichment.get("symbol") or "").upper().strip()
    direction = str(signal.get("direction") or "WATCH_ONLY").upper().strip()
    do_not_trade = [str(item) for item in signal.get("do_not_trade_reasons") or [] if str(item)]
    tradable = bool(signal.get("tradable_candidate") and direction in {"LONG", "SHORT"} and not do_not_trade)
    metrics = enrichment.get("metrics") if isinstance(enrichment.get("metrics"), dict) else {}
    entry_price = _num(metrics.get("last_price"))

    if not tradable or not entry_price or entry_price <= 0:
        return {
            "schema": "tradecat_auto.strategy_intent.v1",
            "ok": True,
            "symbol": symbol,
            "action": "WATCH",
            "direction": "WATCH_ONLY",
            "confidence_score": _num(signal.get("score")) or 0.0,
            "entry_type": None,
            "entry_price": None,
            "invalidation_price": None,
            "take_profit_price": None,
            "max_holding_minutes": None,
            "exit_management": "watch_only",
            "exit_plan_source": None,
            "exit_rationale": None,
            "strategy_tags": _strategy_tags(signal, metrics),
            "do_not_trade_reasons": do_not_trade or ["signal_not_tradable"],
            "explanation": _explanation(signal, metrics),
            "limitations": ["strategy intent only; not an order and not investment advice"],
        }

    exit_plan = _agent_exit_plan(agent_trade_thesis)
    return {
        "schema": "tradecat_auto.strategy_intent.v1",
        "ok": True,
        "symbol": symbol,
        "action": "ENTER",
        "direction": direction,
        "confidence_score": _num(signal.get("score")) or 0.0,
        "entry_type": "MARKET_PAPER",
        "entry_price": entry_price,
        "invalidation_price": exit_plan["invalidation_price"],
        "take_profit_price": exit_plan["take_profit_price"],
        "max_holding_minutes": exit_plan["max_holding_minutes"],
        "exit_management": exit_plan["exit_management"],
        "exit_plan_source": exit_plan["exit_plan_source"],
        "exit_rationale": exit_plan["exit_rationale"],
        "strategy_tags": _strategy_tags(signal, metrics),
        "do_not_trade_reasons": [],
        "explanation": _explanation(signal, metrics),
        "limitations": ["strategy intent only; not an order and not investment advice"],
    }


def _strategy_tags(signal: dict[str, Any], metrics: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    positives = {str(item) for item in signal.get("positive_factors") or []}
    price_change = _num(metrics.get("price_change_24h_pct")) or 0.0
    taker_ratio = _num(metrics.get("taker_buy_sell_ratio"))
    if abs(price_change) >= 10 or "large_24h_price_move" in positives or "moderate_24h_price_move" in positives:
        tags.append("momentum_breakout")
    if taker_ratio is not None and (taker_ratio >= 1.05 or taker_ratio <= 0.95):
        tags.append("taker_flow_bias")
    if any("long_short" in item for item in positives):
        tags.append("positioning_bias")
    if not tags:
        tags.append("watchlist_candidate")
    return list(dict.fromkeys(tags))


def _explanation(signal: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "positive_factors": list(signal.get("positive_factors") or []),
        "negative_factors": list(signal.get("negative_factors") or []),
        "metrics_used": {
            "price_change_24h_pct": metrics.get("price_change_24h_pct"),
            "spread_bps": metrics.get("spread_bps"),
            "quote_volume_24h": metrics.get("quote_volume_24h"),
            "taker_buy_sell_ratio": metrics.get("taker_buy_sell_ratio"),
            "global_long_short_account_ratio": metrics.get("global_long_short_account_ratio"),
        },
    }


def _agent_exit_plan(agent_trade_thesis: dict[str, Any] | None) -> dict[str, Any]:
    thesis = agent_trade_thesis if isinstance(agent_trade_thesis, dict) else {}
    invalidation = _num(thesis.get("invalidation_price"))
    take_profit = _num(thesis.get("take_profit_price"))
    max_holding = _num(thesis.get("max_holding_minutes"))
    if max_holding is not None and max_holding <= 0:
        max_holding = None
    supplied = any(value is not None for value in (invalidation, take_profit, max_holding))
    return {
        "invalidation_price": invalidation,
        "take_profit_price": take_profit,
        "max_holding_minutes": max_holding,
        "exit_management": "agent_supplied" if supplied else "agent_managed",
        "exit_plan_source": str(thesis.get("source") or "agent_trade_thesis") if supplied else "agent_required_missing",
        "exit_rationale": thesis.get("exit_rationale") if supplied else None,
    }


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
