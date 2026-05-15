from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

DEFAULT_REQUESTED_NOTIONAL_USDT = 10.0
DEFAULT_STOP_LOSS_PCT = 0.03
DEFAULT_TAKE_PROFIT_PCT = 0.06


def open_paper_position(
    signal: dict[str, Any],
    risk_decision: dict[str, Any],
    enrichment: dict[str, Any],
    *,
    requested_notional_usdt: float = DEFAULT_REQUESTED_NOTIONAL_USDT,
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
    max_notional = _num(risk_decision.get("max_notional_usdt")) or 0.0
    notional = min(float(requested_notional_usdt), max_notional) if max_notional > 0 else 0.0
    if notional <= 0:
        return _rejected(signal, risk_decision, ["non_positive_notional"])
    quantity = notional / entry_price
    stop_loss = entry_price * (1 - DEFAULT_STOP_LOSS_PCT if side == "LONG" else 1 + DEFAULT_STOP_LOSS_PCT)
    take_profit = entry_price * (1 + DEFAULT_TAKE_PROFIT_PCT if side == "LONG" else 1 - DEFAULT_TAKE_PROFIT_PCT)
    opened_at = _now_iso()
    symbol = str(signal.get("symbol") or enrichment.get("symbol") or "")
    return {
        "schema": "tradecat_auto.paper_execution_report.v1",
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
        "stop_loss_price": stop_loss,
        "take_profit_price": take_profit,
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
        "ok": False,
        "status": "REJECTED",
        "mode": risk_decision.get("mode", "paper"),
        "symbol": str(signal.get("symbol") or ""),
        "side": signal.get("direction", "WATCH_ONLY"),
        "reasons": reasons,
        "risk_decision": risk_decision,
        "limitations": ["paper simulation only; no exchange order was placed"],
    }


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _execution_id(symbol: str, side: str, opened_at: str, entry_price: float, quantity: float, notional: float) -> str:
    material = f"{symbol}\n{side}\n{opened_at}\n{entry_price:.12f}\n{quantity:.12f}\n{notional:.12f}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
