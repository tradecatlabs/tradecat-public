from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any


def open_paper_position(
    signal: dict[str, Any],
    risk_decision: dict[str, Any],
    enrichment: dict[str, Any],
    *,
    requested_notional_usdt: float | None = None,
    requested_margin_usdt: float | None = None,
    paper_leverage: float | None = None,
    sizing_source: str = "agent_supplied_or_explicit",
    strategy_intent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if risk_decision.get("decision") != "ALLOW":
        return _rejected(signal, risk_decision, ["risk_decision_not_allow"])
    if risk_decision.get("mode") != "paper":
        return _rejected(signal, risk_decision, ["paper_mode_required"])
    side = str(signal.get("direction") or "").upper().strip()
    if not signal.get("tradable_candidate") or side not in {"LONG", "SHORT"}:
        return _rejected(signal, risk_decision, ["signal_not_tradable"])
    metrics = enrichment.get("metrics") if isinstance(enrichment.get("metrics"), dict) else {}
    entry_price = _num(metrics.get("last_price"))
    if not entry_price or entry_price <= 0:
        return _rejected(signal, risk_decision, ["missing_entry_price"])
    requested_notional = _num(requested_notional_usdt)
    leverage = _positive_float(paper_leverage)
    if requested_notional is None or requested_notional <= 0 or leverage is None:
        return _rejected(signal, risk_decision, ["agent_sizing_required"])
    max_notional = _num(risk_decision.get("max_notional_usdt"))
    notional = min(requested_notional, max_notional) if max_notional is not None and max_notional > 0 else requested_notional
    if notional <= 0:
        return _rejected(signal, risk_decision, ["non_positive_notional"])
    requested_margin = _num(requested_margin_usdt)
    margin = notional / leverage if leverage > 0 else requested_margin
    quantity = notional / entry_price
    exit_plan = _exit_plan_from_strategy_intent(strategy_intent)
    opened_at = _now_iso()
    symbol = str(signal.get("symbol") or enrichment.get("symbol") or "")
    return {
        "schema": "tradecat_auto.paper_execution_report.v1",
        "schema_version": "1.0.0",
        "ok": True,
        "status": "OPENED",
        "paper_execution_id": _execution_id(symbol, side, opened_at, entry_price, quantity, notional),
        "mode": "paper",
        "opened_at": opened_at,
        "symbol": symbol,
        "side": side,
        "score": signal.get("score"),
        "entry_price": entry_price,
        "quantity": quantity,
        "notional_usdt": notional,
        "requested_notional_usdt": requested_notional,
        "requested_margin_usdt": requested_margin,
        "margin_usdt": margin,
        "leverage": leverage,
        "sizing_source": str(sizing_source or "agent_supplied_or_explicit"),
        "stop_loss_price": exit_plan["stop_loss_price"],
        "take_profit_price": exit_plan["take_profit_price"],
        "max_holding_minutes": exit_plan["max_holding_minutes"],
        "exit_management": exit_plan["exit_management"],
        "exit_plan_source": exit_plan["exit_plan_source"],
        "exit_rationale": exit_plan["exit_rationale"],
        "risk_decision": risk_decision,
        "limitations": ["paper simulation only; no exchange order was placed"],
    }


def close_paper_position(position: dict[str, Any], *, exit_price: float) -> dict[str, Any]:
    if position.get("status") != "OPENED":
        return {**position, "status": "REJECTED", "reasons": ["position_not_open"]}
    entry = float(position.get("entry_price") or 0)
    quantity = float(position.get("quantity") or 0)
    side = str(position.get("side") or "").upper()
    exit_value = float(exit_price)
    if side == "LONG":
        pnl = (exit_value - entry) * quantity
    elif side == "SHORT":
        pnl = (entry - exit_value) * quantity
    else:
        pnl = 0.0
    notional = float(position.get("notional_usdt") or 0)
    return {
        **position,
        "status": "CLOSED",
        "closed_at": _now_iso(),
        "exit_price": exit_value,
        "pnl_usdt": pnl,
        "pnl_pct_on_notional": (pnl / notional * 100) if notional else 0.0,
    }


def _rejected(signal: dict[str, Any], risk_decision: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    return {
        "schema": "tradecat_auto.paper_execution_report.v1",
        "schema_version": "1.0.0",
        "ok": False,
        "status": "REJECTED",
        "mode": risk_decision.get("mode", "paper"),
        "symbol": str(signal.get("symbol") or ""),
        "side": signal.get("direction", "WATCH_ONLY"),
        "reasons": reasons,
        "risk_decision": risk_decision,
        "limitations": ["paper simulation only; no exchange order was placed"],
    }


def _exit_plan_from_strategy_intent(strategy_intent: dict[str, Any] | None) -> dict[str, Any]:
    intent = strategy_intent if isinstance(strategy_intent, dict) else {}
    stop_loss = _num(intent.get("invalidation_price"))
    take_profit = _num(intent.get("take_profit_price"))
    max_holding = _num(intent.get("max_holding_minutes"))
    if max_holding is not None and max_holding <= 0:
        max_holding = None
    supplied = any(value is not None for value in (stop_loss, take_profit, max_holding))
    return {
        "stop_loss_price": stop_loss,
        "take_profit_price": take_profit,
        "max_holding_minutes": max_holding,
        "exit_management": str(intent.get("exit_management") or "agent_supplied") if supplied else "agent_managed",
        "exit_plan_source": str(intent.get("exit_plan_source") or "agent_trade_thesis") if supplied else "agent_required_missing",
        "exit_rationale": intent.get("exit_rationale") if supplied else None,
    }


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_float(value: Any) -> float | None:
    numeric = _num(value)
    return numeric if numeric is not None and numeric > 0 else None


def _execution_id(symbol: str, side: str, opened_at: str, entry_price: float, quantity: float, notional: float) -> str:
    material = f"{symbol}\n{side}\n{opened_at}\n{entry_price:.12f}\n{quantity:.12f}\n{notional:.12f}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
