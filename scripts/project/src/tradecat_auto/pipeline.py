from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from tradecat_auto.market_enrichment import build_market_enrichment
from tradecat_auto.paper_broker import open_paper_position
from tradecat_auto.risk import default_risk_policy, evaluate_risk
from tradecat_auto.signals import build_signal_score
from tradecat_auto.strategies import build_strategy_intent


def build_paper_pipeline_report(
    *,
    selected_symbol: str,
    anomaly_symbols: dict[str, Any],
    market_bundle: dict[str, Any],
    events: dict[str, Any],
    mode: str = "paper",
    requested_notional_usdt: float | None = None,
    requested_margin_usdt: float | None = None,
    paper_leverage: float | None = None,
    margin_budget_usdt: float | None = None,
    sizing_source: str = "agent_supplied_or_explicit",
    agent_trade_thesis: dict[str, Any] | None = None,
    risk_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected = str(selected_symbol or "").upper().strip()
    anomaly_item = _find_anomaly_symbol(anomaly_symbols, selected)
    if not anomaly_item:
        return {
            "schema": "tradecat_auto.run_once_report.v1",
            "schema_version": "1.0.0",
            "ok": False,
            "mode": mode,
            "selected_symbol": selected,
            "error": "selected_symbol_not_found_in_anomaly_symbols",
            "events_count": len(events.get("events") or []) if isinstance(events, dict) else 0,
        }
    enrichment = build_market_enrichment(anomaly_item, market_bundle)
    signal = build_signal_score(enrichment)
    strategy_intent = build_strategy_intent(signal, enrichment, agent_trade_thesis=agent_trade_thesis)
    active_risk_policy = default_risk_policy(mode=mode)
    if risk_policy:
        active_risk_policy.update(risk_policy)
    sizing = resolve_paper_sizing(
        requested_notional_usdt=requested_notional_usdt,
        requested_margin_usdt=requested_margin_usdt,
        paper_leverage=paper_leverage,
        margin_budget_usdt=margin_budget_usdt,
        sizing_source=sizing_source,
        sizing_required=(mode == "paper"),
    )
    risk_sizing_update = {
        "mode": mode,
        "sizing_required": sizing["sizing_required"],
        "sizing_source": sizing["source"],
        "paper_leverage": sizing["paper_leverage"],
        "requested_margin_usdt": sizing["requested_margin_usdt"],
        "requested_notional_usdt": sizing["effective_notional_usdt"],
    }
    if sizing["margin_budget_usdt"] is not None:
        risk_sizing_update["paper_margin_budget_usdt"] = sizing["margin_budget_usdt"]
    active_risk_policy.update(risk_sizing_update)
    risk_decision = evaluate_risk(signal, active_risk_policy)
    paper_execution = open_paper_position(
        signal,
        risk_decision,
        enrichment,
        requested_notional_usdt=sizing["effective_notional_usdt"],
        requested_margin_usdt=sizing["requested_margin_usdt"],
        paper_leverage=sizing["paper_leverage"],
        sizing_source=sizing["source"],
        strategy_intent=strategy_intent,
    )
    return {
        "schema": "tradecat_auto.run_once_report.v1",
        "schema_version": "1.0.0",
        "ok": bool(enrichment.get("ok") and signal.get("ok") and risk_decision.get("ok")),
        "mode": mode,
        "generated_at": _now_iso(),
        "selected_symbol": selected,
        "paper_sizing": sizing,
        "paper_margin_budget_usdt": sizing["margin_budget_usdt"],
        "requested_margin_usdt": sizing["requested_margin_usdt"],
        "paper_leverage": sizing["paper_leverage"],
        "effective_notional_usdt": sizing["effective_notional_usdt"],
        "events_count": len(events.get("events") or []) if isinstance(events, dict) else 0,
        "latest_event": (events.get("events") or [None])[0] if isinstance(events, dict) else None,
        "enrichment": enrichment,
        "signal": signal,
        "strategy_intent": strategy_intent,
        "risk_decision": risk_decision,
        "paper_execution": paper_execution,
        "limitations": [
            "paper run only; no Binance credentials were read",
            "no real order was placed",
            "paper size/leverage must be Agent-supplied or explicitly provided; TradeCat has no default trade amount",
        ],
    }


def resolve_paper_sizing(
    *,
    requested_notional_usdt: Any = None,
    requested_margin_usdt: Any = None,
    paper_leverage: Any = None,
    margin_budget_usdt: Any = None,
    sizing_source: str = "agent_supplied_or_explicit",
    sizing_required: bool = True,
) -> dict[str, Any]:
    """Resolve paper sizing without treating the 12U budget as an order amount.

    `margin_budget_usdt` is the local paper margin budget (12U by default in the
    wrapper).  It is not enough to open a paper position.  Actual paper sizing
    must come from an Agent/Hermes thesis or explicit override as margin +
    leverage; an explicit effective notional is accepted only for low-level
    tests/backward-compatible callers.
    """

    leverage = _positive_float(paper_leverage)
    margin_budget = _positive_float(margin_budget_usdt)
    margin = _positive_float(requested_margin_usdt)
    requested_notional = _positive_float(requested_notional_usdt)
    effective_notional: float | None = None
    mode = "missing"
    if margin is not None and leverage is not None:
        effective_notional = margin * leverage
        mode = "margin_times_leverage"
    elif requested_notional is not None and leverage is not None:
        effective_notional = requested_notional
        margin = requested_notional / leverage
        mode = "explicit_effective_notional"
    complete = effective_notional is not None and effective_notional > 0 and leverage is not None and leverage > 0
    budget_exceeded = bool(margin_budget is not None and margin is not None and margin > margin_budget)
    return {
        "schema": "tradecat_auto.paper_sizing_decision.v1",
        "schema_version": "1.0.0",
        "ok": bool(complete),
        "source": str(sizing_source or "agent_supplied_or_explicit"),
        "agent_decided": str(sizing_source or "").startswith("agent"),
        "sizing_required": bool(sizing_required),
        "mode": mode,
        "margin_budget_usdt": margin_budget,
        "requested_margin_usdt": margin,
        "paper_leverage": leverage,
        "requested_notional_usdt": requested_notional,
        "effective_notional_usdt": effective_notional,
        "budget_exceeded": budget_exceeded,
        "notional_semantics": "effective_notional_usdt; margin_budget_usdt is not an order amount",
        "error_code": None if complete or not sizing_required else "agent_sizing_required",
    }


def _find_anomaly_symbol(anomaly_symbols: dict[str, Any], selected_symbol: str) -> dict[str, Any] | None:
    symbols = anomaly_symbols.get("symbols") if isinstance(anomaly_symbols, dict) else []
    if not isinstance(symbols, list):
        return None
    for item in symbols:
        if not isinstance(item, dict):
            continue
        if str(item.get("normalized_symbol") or "").upper().strip() == selected_symbol:
            return item
    return None


def _positive_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric > 0 else None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
