from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from tradecat_auto.agent_trade_thesis import paper_intent_from_agent_trade_thesis
from tradecat_auto.market_enrichment import build_market_enrichment
from tradecat_auto.paper_autonomy import synthesize_agent_trade_thesis
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
    paper_autonomy_profile: dict[str, Any] | None = None,
    risk_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected = str(selected_symbol or "").upper().strip()
    anomaly_item = _find_anomaly_symbol(anomaly_symbols, selected)
    if anomaly_item:
        anomaly_item = _merge_anomaly_item_with_latest_event(anomaly_item, events, selected)
    else:
        anomaly_item = _anomaly_item_from_latest_event(events, selected)
    if not anomaly_item:
        return {
            "schema": "tradecat_auto.run_once_report.v1",
            "schema_version": "1.0.0",
            "ok": False,
            "real_orders": False,
            "signed_requests": False,
            "reads_api_keys": False,
            "mode": mode,
            "selected_symbol": selected,
            "error_code": "selected_symbol_not_found_in_anomaly_symbols",
            "error": "selected_symbol_not_found_in_anomaly_symbols",
            "events_count": len(events.get("events") or []) if isinstance(events, dict) else 0,
            "provenance": _report_provenance(selected, market_bundle),
            "safety": _safety_boundary(),
        }
    enrichment = build_market_enrichment(anomaly_item, market_bundle)
    signal = build_signal_score(enrichment)
    resolved_agent_trade_thesis = synthesize_agent_trade_thesis(
        agent_trade_thesis=agent_trade_thesis,
        paper_autonomy_profile=paper_autonomy_profile,
        signal=signal,
        enrichment=enrichment,
        events=events,
    )
    decision_signal = _apply_agent_signal_override(signal, resolved_agent_trade_thesis)
    strategy_intent = build_strategy_intent(decision_signal, enrichment, agent_trade_thesis=resolved_agent_trade_thesis)
    active_risk_policy = default_risk_policy(mode=mode)
    if risk_policy:
        active_risk_policy.update(risk_policy)
    if active_risk_policy.get("current_abnormal_move_bps") is None:
        move_bps = _market_move_bps(market_bundle)
        if move_bps is not None:
            active_risk_policy["current_abnormal_move_bps"] = move_bps
    if mode == "paper" and _agent_exit_plan_missing(strategy_intent):
        force_reject_reasons = list(active_risk_policy.get("force_reject_reasons") or [])
        force_reject_reasons.append("agent_exit_plan_required")
        active_risk_policy["force_reject_reasons"] = force_reject_reasons
    thesis_sizing = _paper_sizing_from_agent_trade_thesis(resolved_agent_trade_thesis)
    cli_sizing_supplied = any(value is not None for value in (requested_notional_usdt, requested_margin_usdt, paper_leverage))
    if cli_sizing_supplied:
        resolved_requested_notional = requested_notional_usdt
        resolved_requested_margin = requested_margin_usdt
        resolved_paper_leverage = paper_leverage
        resolved_sizing_source = sizing_source
    elif thesis_sizing:
        resolved_requested_notional = thesis_sizing.get("requested_notional_usdt")
        resolved_requested_margin = thesis_sizing.get("requested_margin_usdt")
        resolved_paper_leverage = thesis_sizing.get("paper_leverage")
        resolved_sizing_source = "agent_trade_thesis.paper_intent"
    else:
        resolved_requested_notional = requested_notional_usdt
        resolved_requested_margin = requested_margin_usdt
        resolved_paper_leverage = paper_leverage
        resolved_sizing_source = sizing_source
    sizing = resolve_paper_sizing(
        requested_notional_usdt=resolved_requested_notional,
        requested_margin_usdt=resolved_requested_margin,
        paper_leverage=resolved_paper_leverage,
        margin_budget_usdt=margin_budget_usdt,
        sizing_source=resolved_sizing_source,
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
    risk_decision = evaluate_risk(decision_signal, active_risk_policy)
    paper_execution = open_paper_position(
        decision_signal,
        risk_decision,
        enrichment,
        requested_notional_usdt=sizing["effective_notional_usdt"],
        requested_margin_usdt=sizing["requested_margin_usdt"],
        paper_leverage=sizing["paper_leverage"],
        sizing_source=sizing["source"],
        strategy_intent=strategy_intent,
        allow_multiple_open_positions_per_symbol=_allow_multiple_open_positions_per_symbol(resolved_agent_trade_thesis),
        max_concurrent_positions_per_symbol=_max_concurrent_positions_per_symbol(resolved_agent_trade_thesis),
    )
    research_cycle_run_id = _research_cycle_run_id(resolved_agent_trade_thesis)
    if research_cycle_run_id:
        paper_execution["research_cycle_run_id"] = research_cycle_run_id
    paper_ok = bool(paper_execution.get("ok") and paper_execution.get("status") == "OPENED")
    report_ok = bool(
        enrichment.get("ok")
        and signal.get("ok")
        and risk_decision.get("ok")
        and (mode != "paper" or (risk_decision.get("decision") == "ALLOW" and paper_ok))
    )
    error = None
    if mode == "paper" and not report_ok:
        sizing_error = sizing.get("error_code")
        execution_reasons = paper_execution.get("reasons") if isinstance(paper_execution.get("reasons"), list) else []
        risk_reasons = risk_decision.get("reasons") if isinstance(risk_decision.get("reasons"), list) else []
        error_code = str(sizing_error or (risk_reasons[0] if risk_reasons else None) or (execution_reasons[0] if execution_reasons else None) or "paper_pipeline_rejected")
        error = {
            "code": error_code,
            "kind": "risk_reject" if risk_decision.get("decision") != "ALLOW" else "paper_execution_reject",
            "message": "paper pipeline did not open a position",
            "retryable": error_code in {"agent_sizing_required", "agent_exit_plan_required"},
        }
    return {
        "schema": "tradecat_auto.run_once_report.v1",
        "schema_version": "1.0.0",
        "ok": report_ok,
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "mode": mode,
        "generated_at": _now_iso(),
        "selected_symbol": selected,
        "error_code": error["code"] if isinstance(error, dict) else None,
        "error": error,
        "provenance": _report_provenance(selected, market_bundle),
        "research_cycle_run_id": research_cycle_run_id,
        "safety": _safety_boundary(),
        "agent_trade_thesis": _agent_trade_thesis_summary(resolved_agent_trade_thesis),
        "paper_sizing": sizing,
        "paper_margin_budget_usdt": sizing["margin_budget_usdt"],
        "requested_margin_usdt": sizing["requested_margin_usdt"],
        "paper_leverage": sizing["paper_leverage"],
        "effective_notional_usdt": sizing["effective_notional_usdt"],
        "events_count": len(events.get("events") or []) if isinstance(events, dict) else 0,
        "latest_event": (events.get("events") or [None])[0] if isinstance(events, dict) else None,
        "enrichment": enrichment,
        "signal": decision_signal,
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
    """Resolve paper sizing without inventing a default order amount or cap.

    TradeCat no longer sets a default paper margin budget.  Actual paper sizing
    must come from an Agent/Hermes thesis or explicit override as margin +
    leverage; an explicit effective notional is accepted only for low-level
    tests/backward-compatible callers.  A positive `margin_budget_usdt`, when
    explicitly supplied by an operator, is treated as an optional policy cap;
    omitted/None/0 means unbounded paper sizing subject only to hard safety
    boundaries.
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
    budget_exceeded = bool(margin_budget is not None and margin_budget > 0 and margin is not None and margin > margin_budget)
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


def _paper_sizing_from_agent_trade_thesis(agent_trade_thesis: dict[str, Any] | None) -> dict[str, Any]:
    paper_intent = paper_intent_from_agent_trade_thesis(agent_trade_thesis)
    if not paper_intent:
        return {}
    leverage = paper_intent.get("paper_leverage")
    if leverage is None:
        leverage = paper_intent.get("requested_leverage")
    if leverage is None:
        leverage = paper_intent.get("leverage")
    return {
        "requested_margin_usdt": paper_intent.get("requested_margin_usdt"),
        "paper_leverage": leverage,
        "requested_notional_usdt": paper_intent.get("requested_notional_usdt"),
    }


def _anomaly_item_from_latest_event(events: dict[str, Any], selected_symbol: str) -> dict[str, Any] | None:
    event = _latest_event(events)
    if not event:
        return None
    symbol = str(event.get("symbol") or "").upper().strip()
    selected = str(selected_symbol or "").upper().strip()
    if selected and symbol and symbol != selected:
        return None
    source_values = _event_source_values(event)
    if not source_values:
        return None
    raw_symbol = str(event.get("raw_symbol") or source_values.get("交易对") or selected or symbol).upper().strip()
    return {
        "raw_symbol": raw_symbol,
        "normalized_symbol": selected or symbol,
        "first_row_index": event.get("row_index"),
        "source_dataset_key": str(event.get("source_dataset_key") or "signal_flow"),
        "source_values": source_values,
    }


def _merge_anomaly_item_with_latest_event(
    anomaly_item: dict[str, Any],
    events: dict[str, Any],
    selected_symbol: str,
) -> dict[str, Any]:
    event_item = _anomaly_item_from_latest_event(events, selected_symbol)
    if not event_item:
        return anomaly_item
    event_values = event_item.get("source_values") if isinstance(event_item.get("source_values"), dict) else {}
    anomaly_values = anomaly_item.get("source_values") if isinstance(anomaly_item.get("source_values"), dict) else {}
    merged = dict(anomaly_item)
    merged["source_dataset_key"] = str(event_item.get("source_dataset_key") or anomaly_item.get("source_dataset_key") or "")
    merged["source_values"] = {**event_values, **anomaly_values}
    merged["related_signal_flow_values"] = event_values
    return merged


def _event_source_values(event: dict[str, Any]) -> dict[str, Any]:
    values = event.get("source_values") if isinstance(event.get("source_values"), dict) else {}
    related = event.get("related_anomaly_panel") if isinstance(event.get("related_anomaly_panel"), dict) else {}
    related_values = related.get("source_values") if isinstance(related.get("source_values"), dict) else {}
    return {**values, **related_values}


def _latest_event(events: dict[str, Any]) -> dict[str, Any] | None:
    rows = events.get("events") if isinstance(events, dict) else []
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    return None


def _apply_agent_signal_override(signal: dict[str, Any], agent_trade_thesis: dict[str, Any] | None) -> dict[str, Any]:
    paper_intent = paper_intent_from_agent_trade_thesis(agent_trade_thesis)
    if paper_intent.get("allow_agent_direction_override") is not True:
        return signal
    thesis = agent_trade_thesis if isinstance(agent_trade_thesis, dict) else {}
    direction = str(thesis.get("direction") or paper_intent.get("paper_direction") or paper_intent.get("direction") or "").upper().strip()
    if direction not in {"LONG", "SHORT"}:
        return signal
    reasons = [str(item) for item in signal.get("do_not_trade_reasons") or [] if str(item)]
    remaining_reasons = [item for item in reasons if item != "direction_conflict"]
    if remaining_reasons:
        return signal
    updated = dict(signal)
    updated["direction"] = direction
    updated["do_not_trade_reasons"] = remaining_reasons
    updated["tradable_candidate"] = True
    positives = list(signal.get("positive_factors") or [])
    positives.append("agent_direction_override")
    updated["positive_factors"] = _dedupe([str(item) for item in positives])
    updated["agent_direction_override"] = {
        "schema": "tradecat_auto.agent_signal_override.v1",
        "schema_version": "1.0.0",
        "ok": True,
        "source": "agent_trade_thesis.paper_intent",
        "reason": "direction_conflict overridden by explicit Agent paper-only authorization",
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "safety": _safety_boundary(),
    }
    return updated


def _market_move_bps(market_bundle: dict[str, Any]) -> float | None:
    ticker = market_bundle.get("ticker24hr") if isinstance(market_bundle.get("ticker24hr"), dict) else {}
    value = _positive_or_negative_float(ticker.get("priceChangePercent"))
    if value is None:
        return None
    return abs(value) * 100.0


def _allow_multiple_open_positions_per_symbol(agent_trade_thesis: dict[str, Any] | None) -> bool:
    paper_intent = paper_intent_from_agent_trade_thesis(agent_trade_thesis)
    max_concurrent = _positive_float(paper_intent.get("max_concurrent_positions_per_symbol"))
    return bool(paper_intent.get("allow_multiple_open_positions_per_symbol") is True or (max_concurrent is not None and max_concurrent > 1))


def _max_concurrent_positions_per_symbol(agent_trade_thesis: dict[str, Any] | None) -> int | None:
    paper_intent = paper_intent_from_agent_trade_thesis(agent_trade_thesis)
    try:
        if paper_intent.get("max_concurrent_positions_per_symbol") in (None, ""):
            return None
        value = int(paper_intent["max_concurrent_positions_per_symbol"])
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _agent_exit_plan_missing(strategy_intent: dict[str, Any]) -> bool:
    return str(strategy_intent.get("exit_plan_source") or "") == "agent_required_missing"


def _research_cycle_run_id(agent_trade_thesis: dict[str, Any] | None) -> str:
    thesis = agent_trade_thesis if isinstance(agent_trade_thesis, dict) else {}
    provenance = thesis.get("provenance") if isinstance(thesis.get("provenance"), dict) else {}
    for source in (provenance, thesis):
        for key in ("research_cycle_run_id", "run_id"):
            value = str(source.get(key) or "").strip()
            if value:
                return value
    return ""


def _agent_trade_thesis_summary(agent_trade_thesis: dict[str, Any] | None) -> dict[str, Any]:
    thesis = agent_trade_thesis if isinstance(agent_trade_thesis, dict) else {}
    provenance = thesis.get("provenance") if isinstance(thesis.get("provenance"), dict) else {}
    return {
        "schema": str(thesis.get("schema") or ""),
        "schema_version": str(thesis.get("schema_version") or ""),
        "ok": thesis.get("ok"),
        "symbol": str(thesis.get("symbol") or ""),
        "direction": str(thesis.get("direction") or ""),
        "mode": str(thesis.get("mode") or ""),
        "confidence": thesis.get("confidence"),
        "holding_horizon": str(thesis.get("holding_horizon") or ""),
        "rationale": str(thesis.get("rationale") or ""),
        "risk_notes": [str(item) for item in thesis.get("risk_notes") or []],
        "limitations": [str(item) for item in thesis.get("limitations") or []],
        "exit_rationale": str(thesis.get("exit_rationale") or ""),
        "paper_intent_present": isinstance(thesis.get("paper_intent"), dict),
        "exit_plan_present": any(thesis.get(key) not in (None, "") for key in ("invalidation_price", "take_profit_price", "max_holding_minutes")),
        "paper_autonomy_profile": bool(provenance.get("paper_autonomy_profile")),
        "provenance": provenance,
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


def _positive_or_negative_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _report_provenance(selected_symbol: str, market_bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "tradecat_auto.pipeline.build_paper_pipeline_report",
        "selected_symbol": selected_symbol,
        "market_bundle_schema": str(market_bundle.get("schema") or ""),
        "market_bundle_source": str(market_bundle.get("source") or "binance_public_market_bundle"),
    }


def _safety_boundary() -> dict[str, bool]:
    return {
        "public_readonly_market_data": True,
        "paper_or_watch_only": True,
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "binance_account_state": False,
    }
