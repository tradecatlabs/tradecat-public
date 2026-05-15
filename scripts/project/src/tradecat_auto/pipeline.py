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
    requested_notional_usdt: float = 10.0,
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
    strategy_intent = build_strategy_intent(signal, enrichment)
    active_risk_policy = default_risk_policy(mode=mode)
    if risk_policy:
        active_risk_policy.update(risk_policy)
    active_risk_policy["mode"] = mode
    active_risk_policy["requested_notional_usdt"] = requested_notional_usdt
    risk_decision = evaluate_risk(signal, active_risk_policy)
    paper_execution = open_paper_position(
        signal,
        risk_decision,
        enrichment,
        requested_notional_usdt=requested_notional_usdt,
    )
    return {
        "schema": "tradecat_auto.run_once_report.v1",
        "schema_version": "1.0.0",
        "ok": bool(enrichment.get("ok") and signal.get("ok") and risk_decision.get("ok")),
        "mode": mode,
        "generated_at": _now_iso(),
        "selected_symbol": selected,
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
        ],
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


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
