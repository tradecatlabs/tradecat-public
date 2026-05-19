from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradecat_auto.agent_trade_thesis import load_agent_trade_thesis
from tradecat_auto.audit_journal import record_service_cycle
from tradecat_auto.binance_market import normalize_to_usdt_perp_symbol
from tradecat_auto.paper_autonomy import load_paper_autonomy_profile
from tradecat_auto.paper_costs import BINANCE_USDM_PUBLIC_TAKER_FEE_BPS, BINANCE_USDM_TAKER_FEE_MODEL
from tradecat_auto.paper_ledger import (
    PaperLedgerError,
    apply_paper_execution,
    load_paper_ledger,
    mark_to_market,
    paper_ledger_summary,
    save_paper_ledger,
)
from tradecat_auto.pipeline import build_paper_pipeline_report, resolve_paper_sizing
from tradecat_auto.risk import load_portfolio_risk_policy
from tradecat_auto.strategy_review import load_strategy_state, strategy_state_policy
from tradecat_auto.tradecat_source import signal_events_payload

DEFAULT_STATE_PATH = Path(".runtime/service_state.json")
STATE_SCHEMA = "tradecat_auto.service_state.v1"
CYCLE_SCHEMA = "tradecat_auto.service_cycle.v1"
BEIJING = timezone(timedelta(hours=8))


def run_service_cycle(
    args: Any,
    *,
    state_path: Path | str = DEFAULT_STATE_PATH,
    client: Any,
    source: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run one safe service cycle around the paper pipeline.

    The service layer intentionally checks sheet freshness and duplicate event IDs
    before making Binance market calls. This keeps the first daemon phase public,
    read-only, and low frequency.
    """

    cycle_time = _coerce_now(now)
    path = Path(state_path)
    state = load_service_state(path)
    previous_state = dict(state)
    state["last_attempt_at"] = _iso(cycle_time)
    state["cycles_attempted"] = int(state.get("cycles_attempted") or 0) + 1
    save_service_state(path, state)

    try:
        agent_trade_thesis = _agent_trade_thesis_from_args(args)
    except ValueError as exc:
        state["last_error"] = "agent_trade_thesis_load_failed"
        save_service_state(path, state)
        return _archive_and_return(
            args,
            _cycle_payload(
                action="ERROR",
                ok=False,
                reason="agent_trade_thesis_load_failed",
                error_code="agent_trade_thesis_load_failed",
                error=_agent_trade_thesis_error(exc),
                state=state,
            ),
        )
    try:
        paper_autonomy_profile = _paper_autonomy_profile_from_args(args)
    except ValueError as exc:
        state["last_error"] = "paper_autonomy_profile_load_failed"
        save_service_state(path, state)
        return _archive_and_return(
            args,
            _cycle_payload(
                action="ERROR",
                ok=False,
                reason="paper_autonomy_profile_load_failed",
                error_code="paper_autonomy_profile_load_failed",
                error=_paper_autonomy_profile_error(exc),
                state=state,
            ),
        )

    universe = _safe_call(client.market_universe)
    tradable = set(universe.get("symbols") or []) if universe.get("ok") else set()
    anomaly = _safe_call(
        source.fetch_anomaly_symbols,
        tradable_symbols=tradable,
        limit=getattr(args, "anomaly_limit", 20),
    )
    signal_flow = _fetch_signal_flow_events(source, tradable, limit=getattr(args, "event_limit", 20))
    source_snapshot = _source_snapshot(signal_flow, anomaly)
    snapshot_delta = _source_snapshot_delta(previous_state, source_snapshot)
    selected_symbol, selected_event_id = _select_symbol_for_cycle(
        str(getattr(args, "symbol", "auto")),
        tradable,
        anomaly,
        signal_flow,
        seen_event_ids=_seen_event_ids(previous_state),
        prefer_anomaly=bool(snapshot_delta.get("anomaly_panel_changed"))
        and not bool(snapshot_delta.get("new_signal_flow_event_id")),
    )
    events = signal_events_payload(signal_flow, anomaly, selected_symbol=selected_symbol)
    if selected_event_id:
        events = _prioritize_event(events, selected_event_id)
    latest_event = _latest_event(events)
    if not events.get("ok") or not latest_event:
        paper_ledger = _monitor_existing_paper_positions(args, client, cycle_time)
        ledger_failed = bool(paper_ledger and paper_ledger.get("ok") is False)
        reason = _event_source_reason(events)
        state["last_error"] = "paper_ledger_monitor_failed" if ledger_failed else reason
        _remember_source_snapshot(state, source_snapshot, snapshot_delta, cycle_time)
        save_service_state(path, state)
        return _archive_and_return(
            args,
            _cycle_payload(
                action="SKIPPED_NO_EVENT",
                ok=False,
                reason="paper_ledger_monitor_failed" if ledger_failed else reason,
                error_code="paper_ledger_monitor_failed" if ledger_failed else reason,
                state=state,
                events=events,
                latest_event=latest_event,
                universe=_summarize_universe(universe),
                signal_flow_events=_summarize_signal_flow_events(signal_flow),
                anomaly_symbols=_summarize_anomaly_symbols(anomaly),
                source_snapshot=source_snapshot,
                input_change=snapshot_delta,
                paper_ledger=paper_ledger,
                raw_errors=_collect_errors(universe, signal_flow, anomaly, events),
            ),
        )

    event_id = str(latest_event.get("event_id") or "").strip()
    event_age_seconds = _event_age_seconds(latest_event, cycle_time)
    seen_event_ids = _seen_event_ids(state)
    snapshot_changed = bool(snapshot_delta.get("source_snapshot_changed"))
    maintenance_due = _maintenance_due(args, previous_state, cycle_time)
    new_event = bool(event_id and event_id not in seen_event_ids)
    trigger_reason = _trigger_reason(
        new_event=new_event, snapshot_delta=snapshot_delta, maintenance_due=maintenance_due
    )
    max_age = getattr(args, "max_event_age_seconds", None)
    if max_age is not None and event_age_seconds is not None and event_age_seconds > float(max_age):
        state["last_error"] = "stale_event"
        state["last_skipped_event_id"] = event_id
        _remember_source_snapshot(state, source_snapshot, snapshot_delta, cycle_time)
        save_service_state(path, state)
        return _archive_and_return(
            args,
            _cycle_payload(
                action="SKIPPED_STALE_EVENT",
                ok=True,
                reason="stale_event_or_unparseable_source_time",
                state=state,
                events=events,
                latest_event=latest_event,
                event_age_seconds=event_age_seconds,
                universe=_summarize_universe(universe),
                signal_flow_events=_summarize_signal_flow_events(signal_flow),
                anomaly_symbols=_summarize_anomaly_symbols(anomaly),
                source_snapshot=source_snapshot,
                input_change={**snapshot_delta, "trigger_reason": "stale_event"},
            ),
        )

    if event_id and event_id in seen_event_ids and not snapshot_changed:
        paper_ledger = _monitor_existing_paper_positions(args, client, cycle_time)
        ledger_failed = bool(paper_ledger and paper_ledger.get("ok") is False)
        state["last_duplicate_event_id"] = event_id
        if maintenance_due and not ledger_failed:
            state["last_maintenance_at"] = _iso(cycle_time)
            state["cycles_maintenance"] = int(state.get("cycles_maintenance") or 0) + 1
        state["last_error"] = paper_ledger.get("error") if ledger_failed else None
        save_service_state(path, state)
        action = "MAINTENANCE_NO_INPUT_CHANGE" if maintenance_due else "SKIPPED_DUPLICATE_EVENT"
        return _archive_and_return(
            args,
            _cycle_payload(
                action=action,
                ok=not ledger_failed,
                reason="paper_ledger_monitor_failed"
                if ledger_failed
                else "maintenance_due"
                if maintenance_due
                else "input_snapshot_unchanged",
                state=state,
                events=events,
                latest_event=latest_event,
                event_age_seconds=event_age_seconds,
                universe=_summarize_universe(universe),
                signal_flow_events=_summarize_signal_flow_events(signal_flow),
                anomaly_symbols=_summarize_anomaly_symbols(anomaly),
                source_snapshot=source_snapshot,
                input_change={
                    **snapshot_delta,
                    "maintenance_due": maintenance_due,
                    "trigger_reason": "maintenance_due" if maintenance_due else "input_snapshot_unchanged",
                },
                paper_ledger=paper_ledger,
            ),
        )

    market_bundle = (
        _safe_call(client.fetch_public_market_bundle, selected_symbol)
        if selected_symbol
        else {
            "schema": "tradecat_auto.public_market_bundle.v1",
            "schema_version": "1.0.0",
            "ok": False,
            "errors": {"symbol": "no tradable symbol selected"},
        }
    )

    if not selected_symbol:
        state["last_error"] = "no_symbol_selected"
        _remember_source_snapshot(state, source_snapshot, snapshot_delta, cycle_time)
        save_service_state(path, state)
        return _archive_and_return(
            args,
            _cycle_payload(
                action="ERROR",
                ok=False,
                reason="no_symbol_selected",
                state=state,
                events=events,
                latest_event=latest_event,
                event_age_seconds=event_age_seconds,
                universe=_summarize_universe(universe),
                signal_flow_events=_summarize_signal_flow_events(signal_flow),
                anomaly_symbols=_summarize_anomaly_symbols(anomaly),
                source_snapshot=source_snapshot,
                input_change={**snapshot_delta, "trigger_reason": "no_symbol_selected"},
                raw_errors=_collect_errors(universe, signal_flow, events, anomaly, market_bundle),
            ),
        )

    risk_policy = _risk_policy_from_runtime(
        args,
        cycle_time,
        state=previous_state,
        selected_symbol=selected_symbol,
        latest_event=latest_event,
    )
    sizing = _paper_sizing_from_args(args)
    pipeline_report = build_paper_pipeline_report(
        selected_symbol=selected_symbol,
        anomaly_symbols=anomaly,
        market_bundle=market_bundle,
        events=events,
        mode=str(getattr(args, "mode", "paper")),
        requested_margin_usdt=sizing["requested_margin_usdt"],
        paper_leverage=sizing["paper_leverage"],
        margin_budget_usdt=sizing["margin_budget_usdt"],
        sizing_source=sizing["source"],
        agent_trade_thesis=agent_trade_thesis,
        paper_autonomy_profile=paper_autonomy_profile,
        risk_policy=risk_policy,
        paper_fee_bps=_paper_fee_bps(args),
        paper_slippage_bps=_paper_slippage_bps(args),
    )
    pipeline_report["universe"] = _summarize_universe(universe)
    pipeline_report["signal_flow_events"] = _summarize_signal_flow_events(signal_flow)
    pipeline_report["anomaly_symbols"] = _summarize_anomaly_symbols(anomaly)
    pipeline_report["raw_errors"] = _collect_errors(universe, signal_flow, events, anomaly, market_bundle)
    paper_ledger = _update_paper_ledger_from_cycle(args, client, pipeline_report, market_bundle, cycle_time)
    if paper_ledger:
        pipeline_report["paper_ledger"] = paper_ledger

    if event_id:
        _remember_event_id(state, event_id)
    _remember_source_snapshot(state, source_snapshot, snapshot_delta, cycle_time)
    state["last_success_at"] = _iso(cycle_time) if pipeline_report.get("ok") else state.get("last_success_at")
    state["last_full_cycle_at"] = _iso(cycle_time)
    state["last_processed_event_id"] = event_id
    state["last_selected_symbol"] = selected_symbol
    state["last_trigger_reason"] = trigger_reason
    state["last_error"] = None if pipeline_report.get("ok") else pipeline_report.get("error") or "pipeline_not_ok"
    state["cycles_processed"] = int(state.get("cycles_processed") or 0) + 1
    save_service_state(path, state)

    payload = _cycle_payload(
        action="PROCESSED",
        ok=bool(pipeline_report.get("ok")),
        reason="new_event_processed",
        state=state,
        events=events,
        latest_event=latest_event,
        event_age_seconds=event_age_seconds,
        source_snapshot=source_snapshot,
        input_change={**snapshot_delta, "maintenance_due": maintenance_due, "trigger_reason": trigger_reason},
        pipeline_report=pipeline_report,
        paper_ledger=paper_ledger,
        raw_errors=pipeline_report.get("raw_errors", []),
    )
    _finalize_cycle(args, payload)
    return payload


def load_service_state(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return _new_state()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    state = _new_state()
    state.update(data)
    state["schema"] = STATE_SCHEMA
    state["seen_event_ids"] = list(dict.fromkeys(str(item) for item in state.get("seen_event_ids") or [] if str(item)))
    return state


def save_service_state(path: Path | str, state: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(state)
    payload["schema"] = STATE_SCHEMA
    tmp = p.with_suffix(f"{p.suffix}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


def _new_state() -> dict[str, Any]:
    return {
        "schema": STATE_SCHEMA,
        "seen_event_ids": [],
        "cycles_attempted": 0,
        "cycles_processed": 0,
        "cycles_maintenance": 0,
        "last_attempt_at": None,
        "last_success_at": None,
        "last_full_cycle_at": None,
        "last_maintenance_at": None,
        "last_input_changed_at": None,
        "last_source_snapshot_hash": None,
        "last_signal_flow_snapshot_hash": None,
        "last_anomaly_panel_snapshot_hash": None,
        "last_trigger_reason": None,
        "last_error": None,
    }


def _cycle_payload(**kwargs: Any) -> dict[str, Any]:
    payload = {
        "schema": CYCLE_SCHEMA,
        "schema_version": "1.0.0",
        "error_code": None,
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "provenance": {"source": "tradecat_auto.service.run_service_cycle"},
        "safety": {
            "public_readonly_market_data": True,
            "paper_or_watch_only": True,
            "real_orders": False,
            "signed_requests": False,
            "reads_api_keys": False,
            "binance_account_state": False,
        },
    }
    payload.update(kwargs)
    if payload.get("ok") is False and not payload.get("error_code"):
        pipeline_report = payload.get("pipeline_report")
        if isinstance(pipeline_report, dict) and pipeline_report.get("error_code"):
            payload["error_code"] = str(pipeline_report["error_code"])
        else:
            payload["error_code"] = str(payload.get("reason") or payload.get("action") or "service_cycle_failed")
    return payload


def _archive_and_return(args: Any, payload: dict[str, Any]) -> dict[str, Any]:
    _finalize_cycle(args, payload)
    return payload


def _finalize_cycle(args: Any, payload: dict[str, Any]) -> None:
    journal_path = _journal_path(args)
    if journal_path is not None:
        journal_payload = dict(payload)
        journal_result = record_service_cycle(
            journal_path,
            journal_payload,
            run_id=_journal_run_id(journal_payload),
            config_snapshot=_journal_config_snapshot(args),
            created_at=_cycle_created_at(journal_payload),
        )
        payload["audit_journal"] = journal_result
    _archive_cycle(args, payload)


def _archive_cycle(args: Any, payload: dict[str, Any]) -> None:
    text = str(getattr(args, "archive_path", "") or "").strip()
    if not text:
        return
    path = Path(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def _safe_call(func, *args, **kwargs) -> dict[str, Any]:
    try:
        result = func(*args, **kwargs)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return result if isinstance(result, dict) else {"ok": False, "error": "non-object result"}


def _latest_event(events: dict[str, Any]) -> dict[str, Any] | None:
    rows = events.get("events") if isinstance(events, dict) else []
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    return None


def _event_source_reason(events: dict[str, Any]) -> str:
    error_code = str(events.get("error_code") or "").strip()
    if error_code:
        return error_code
    error = events.get("error")
    if isinstance(error, dict):
        code = str(error.get("code") or "").strip()
        if code:
            return code
    return "no_events_available"


def _seen_event_ids(state: dict[str, Any]) -> set[str]:
    return {str(item) for item in state.get("seen_event_ids") or [] if str(item)}


def _remember_event_id(state: dict[str, Any], event_id: str, *, max_ids: int = 500) -> None:
    existing = [str(item) for item in state.get("seen_event_ids") or [] if str(item)]
    updated = list(dict.fromkeys([event_id, *existing]))
    state["seen_event_ids"] = updated[:max_ids]


def _source_snapshot(signal_flow: dict[str, Any], anomaly: dict[str, Any]) -> dict[str, Any]:
    signal_events = signal_flow.get("events") if isinstance(signal_flow.get("events"), list) else []
    anomaly_rows = (
        anomaly.get("rows")
        if isinstance(anomaly.get("rows"), list)
        else anomaly.get("symbols")
        if isinstance(anomaly.get("symbols"), list)
        else []
    )
    signal_material = [
        {
            "event_id": str(item.get("event_id") or ""),
            "source_time_bj": str(item.get("source_time_bj") or ""),
            "symbol": str(item.get("symbol") or "").upper().strip(),
            "period": str(item.get("period") or ""),
            "signal_type": str(item.get("signal_type") or ""),
            "content": str(item.get("content") or ""),
        }
        for item in signal_events
        if isinstance(item, dict)
    ]
    anomaly_material = [
        {
            "section": str(item.get("section") or ""),
            "normalized_symbol": str(item.get("normalized_symbol") or "").upper().strip(),
            "raw_symbol": str(item.get("raw_symbol") or "").upper().strip(),
            "source_values": _stable_source_values(item.get("source_values")),
        }
        for item in anomaly_rows
        if isinstance(item, dict)
    ]
    signal_hash = _stable_hash(signal_material)
    anomaly_hash = _stable_hash(anomaly_material)
    return {
        "schema": "tradecat_auto.source_snapshot.v1",
        "schema_version": "1.0.0",
        "signal_flow_event_ids": [item["event_id"] for item in signal_material if item.get("event_id")],
        "signal_flow_count": len(signal_material),
        "signal_flow_snapshot_hash": signal_hash,
        "anomaly_panel_row_count": len(anomaly_material),
        "anomaly_panel_section_count": len(anomaly.get("sections") or [])
        if isinstance(anomaly.get("sections"), list)
        else 0,
        "anomaly_panel_snapshot_hash": anomaly_hash,
        "source_snapshot_hash": _stable_hash(
            {
                "signal_flow_snapshot_hash": signal_hash,
                "anomaly_panel_snapshot_hash": anomaly_hash,
            }
        ),
    }


def _source_snapshot_delta(state: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    seen = _seen_event_ids(state)
    new_signal_event_id = ""
    for event_id in snapshot.get("signal_flow_event_ids") or []:
        if str(event_id) and str(event_id) not in seen:
            new_signal_event_id = str(event_id)
            break
    signal_hash = str(snapshot.get("signal_flow_snapshot_hash") or "")
    anomaly_hash = str(snapshot.get("anomaly_panel_snapshot_hash") or "")
    source_hash = str(snapshot.get("source_snapshot_hash") or "")
    previous_signal_hash = str(state.get("last_signal_flow_snapshot_hash") or "")
    previous_anomaly_hash = str(state.get("last_anomaly_panel_snapshot_hash") or "")
    previous_source_hash = str(state.get("last_source_snapshot_hash") or "")
    return {
        "schema": "tradecat_auto.input_change.v1",
        "schema_version": "1.0.0",
        "new_signal_flow_event_id": new_signal_event_id or None,
        "signal_flow_changed": bool(signal_hash and signal_hash != previous_signal_hash),
        "anomaly_panel_changed": bool(anomaly_hash and anomaly_hash != previous_anomaly_hash),
        "source_snapshot_changed": bool(source_hash and source_hash != previous_source_hash),
        "previous_source_snapshot_hash": previous_source_hash or None,
        "current_source_snapshot_hash": source_hash or None,
    }


def _remember_source_snapshot(
    state: dict[str, Any],
    snapshot: dict[str, Any],
    delta: dict[str, Any],
    cycle_time: datetime,
) -> None:
    state["last_source_snapshot_hash"] = snapshot.get("source_snapshot_hash")
    state["last_signal_flow_snapshot_hash"] = snapshot.get("signal_flow_snapshot_hash")
    state["last_anomaly_panel_snapshot_hash"] = snapshot.get("anomaly_panel_snapshot_hash")
    state["last_signal_flow_event_ids"] = list(snapshot.get("signal_flow_event_ids") or [])[:20]
    if delta.get("source_snapshot_changed"):
        state["last_input_changed_at"] = _iso(cycle_time)


def _maintenance_due(args: Any, state: dict[str, Any], cycle_time: datetime) -> bool:
    interval = _maintenance_interval_seconds(args)
    if interval <= 0:
        return False
    anchor = _parse_state_time(
        state.get("last_maintenance_at")
        or state.get("last_full_cycle_at")
        or state.get("last_success_at")
        or state.get("last_attempt_at")
    )
    if anchor is None:
        return False
    return (cycle_time.astimezone(UTC) - anchor.astimezone(UTC)).total_seconds() >= interval


def _maintenance_interval_seconds(args: Any) -> float:
    try:
        value = float(getattr(args, "maintenance_interval_seconds", 300.0) or 0.0)
    except (TypeError, ValueError):
        return 300.0
    return max(0.0, value)


def _trigger_reason(*, new_event: bool, snapshot_delta: dict[str, Any], maintenance_due: bool) -> str:
    if new_event:
        return "new_signal_event"
    if snapshot_delta.get("anomaly_panel_changed"):
        return "anomaly_panel_snapshot_changed"
    if snapshot_delta.get("signal_flow_changed"):
        return "signal_flow_snapshot_changed"
    if snapshot_delta.get("source_snapshot_changed"):
        return "source_snapshot_changed"
    if maintenance_due:
        return "maintenance_due"
    return "input_snapshot_unchanged"


def _stable_source_values(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(child) for key, child in value.items() if str(child or "").strip()}


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _fetch_signal_flow_events(source: Any, tradable: set[str], *, limit: int) -> dict[str, Any]:
    fetch = getattr(source, "fetch_signal_flow_events", None)
    if not callable(fetch):
        return {
            "schema": "tradecat_auto.signal_flow_events.v1",
            "schema_version": "1.0.0",
            "ok": False,
            "source_dataset_key": "signal_flow",
            "events": [],
            "rejected": [],
            "error_code": "signal_flow_source_not_available",
            "error": {"code": "signal_flow_source_not_available", "message": "source has no fetch_signal_flow_events"},
        }
    return _safe_call(fetch, tradable_symbols=tradable, limit=limit)


def _select_symbol(
    requested: str, tradable: set[str], anomaly: dict[str, Any], signal_flow: dict[str, Any] | None = None
) -> str:
    selected, _ = _select_symbol_for_cycle(
        requested,
        tradable,
        anomaly,
        signal_flow,
        seen_event_ids=set(),
        prefer_anomaly=False,
    )
    return selected


def _select_symbol_for_cycle(
    requested: str,
    tradable: set[str],
    anomaly: dict[str, Any],
    signal_flow: dict[str, Any] | None = None,
    *,
    seen_event_ids: set[str],
    prefer_anomaly: bool,
) -> tuple[str, str]:
    text = str(requested or "auto").upper().strip()
    if text and text != "AUTO":
        return normalize_to_usdt_perp_symbol(text, tradable) or text, ""
    if not prefer_anomaly:
        for item in (signal_flow or {}).get("events") or []:
            if not isinstance(item, dict) or not item.get("symbol"):
                continue
            event_id = str(item.get("event_id") or "")
            if event_id and event_id not in seen_event_ids:
                return str(item["symbol"]).upper().strip(), event_id
        for item in (signal_flow or {}).get("events") or []:
            if isinstance(item, dict) and item.get("symbol"):
                return str(item["symbol"]).upper().strip(), str(item.get("event_id") or "")
    for item in anomaly.get("symbols") or []:
        if isinstance(item, dict) and item.get("normalized_symbol"):
            return str(item["normalized_symbol"]), ""
    for item in (signal_flow or {}).get("events") or []:
        if isinstance(item, dict) and item.get("symbol"):
            return str(item["symbol"]).upper().strip(), str(item.get("event_id") or "")
    return "", ""


def _prioritize_event(events: dict[str, Any], event_id: str) -> dict[str, Any]:
    rows = events.get("events") if isinstance(events, dict) else []
    target = str(event_id or "")
    if not target or not isinstance(rows, list):
        return events
    selected = [item for item in rows if isinstance(item, dict) and str(item.get("event_id") or "") == target]
    if not selected:
        return events
    remaining = [item for item in rows if not (isinstance(item, dict) and str(item.get("event_id") or "") == target)]
    updated = dict(events)
    updated["events"] = [*selected, *remaining]
    return updated


def _summarize_universe(universe: dict[str, Any]) -> dict[str, Any]:
    symbols = universe.get("symbols") or []
    return {
        "ok": universe.get("ok"),
        "symbol_count": len(symbols),
        "first_10": symbols[:10],
        "rate_limits": universe.get("rate_limits", [])[:3],
        "error": universe.get("error"),
    }


def _summarize_anomaly_symbols(anomaly: dict[str, Any]) -> dict[str, Any]:
    symbols = anomaly.get("symbols") if isinstance(anomaly.get("symbols"), list) else []
    rows = anomaly.get("rows") if isinstance(anomaly.get("rows"), list) else symbols
    rejected = anomaly.get("rejected") if isinstance(anomaly.get("rejected"), list) else []
    return {
        "ok": anomaly.get("ok"),
        "source_dataset_key": anomaly.get("source_dataset_key", "anomaly_panel"),
        "count": len(symbols),
        "row_count": len(rows),
        "sections": anomaly.get("sections") if isinstance(anomaly.get("sections"), list) else [],
        "first_10": symbols[:10],
        "first_10_rows": rows[:10],
        "rejected_count": len(rejected),
        "error_code": anomaly.get("error_code"),
        "error": anomaly.get("error"),
    }


def _summarize_signal_flow_events(signal_flow: dict[str, Any]) -> dict[str, Any]:
    events = signal_flow.get("events") if isinstance(signal_flow.get("events"), list) else []
    rejected = signal_flow.get("rejected") if isinstance(signal_flow.get("rejected"), list) else []
    duplicates = signal_flow.get("duplicates") if isinstance(signal_flow.get("duplicates"), list) else []
    return {
        "ok": signal_flow.get("ok"),
        "source_dataset_key": signal_flow.get("source_dataset_key", "signal_flow"),
        "count": len(events),
        "first_10": events[:10],
        "rejected_count": len(rejected),
        "duplicate_count": int(signal_flow.get("duplicate_count") or len(duplicates)),
        "error_code": signal_flow.get("error_code"),
        "error": signal_flow.get("error"),
    }


def _collect_errors(*payloads: dict[str, Any]) -> list[Any]:
    errors: list[Any] = []
    for payload in payloads:
        if payload.get("ok") is False:
            errors.append(payload.get("error") or payload.get("errors") or payload)
    return errors


def _update_paper_ledger_from_cycle(
    args: Any,
    client: Any,
    pipeline_report: dict[str, Any],
    selected_market_bundle: dict[str, Any],
    cycle_time: datetime,
) -> dict[str, Any]:
    ledger_path = _paper_ledger_path(args)
    if ledger_path is None:
        return {}
    try:
        ledger = load_paper_ledger(ledger_path, initial_balance_usdt=_initial_balance(args))
    except PaperLedgerError as exc:
        return _ledger_error_summary(ledger_path, exc)
    prices, mark_errors = _prices_for_open_positions(ledger, client, selected_market_bundle)
    if prices:
        ledger = mark_to_market(
            ledger,
            prices,
            fee_bps=_paper_fee_bps(args),
            slippage_bps=_paper_slippage_bps(args),
            now_iso=_iso(cycle_time),
            max_holding_minutes=_paper_max_holding_minutes(args),
        )
    ledger = apply_paper_execution(
        ledger,
        pipeline_report.get("paper_execution") if isinstance(pipeline_report.get("paper_execution"), dict) else {},
        fee_bps=_paper_fee_bps(args),
        slippage_bps=_paper_slippage_bps(args),
        now_iso=_iso(cycle_time),
    )
    save_paper_ledger(ledger_path, ledger)
    summary = paper_ledger_summary(ledger)
    summary["recent_paper_orders"] = list(ledger.get("paper_orders") or [])[-20:]
    summary["recent_fills"] = list(ledger.get("fills") or [])[-20:]
    if mark_errors:
        summary["mark_errors"] = mark_errors
    summary["path"] = str(ledger_path)
    return summary


def _monitor_existing_paper_positions(args: Any, client: Any, cycle_time: datetime) -> dict[str, Any]:
    ledger_path = _paper_ledger_path(args)
    if ledger_path is None or not ledger_path.exists():
        return {}
    try:
        ledger = load_paper_ledger(ledger_path, initial_balance_usdt=_initial_balance(args))
    except PaperLedgerError as exc:
        return _ledger_error_summary(ledger_path, exc)
    if not ledger.get("open_positions"):
        return {**paper_ledger_summary(ledger), "path": str(ledger_path)}
    prices, mark_errors = _prices_for_open_positions(ledger, client, {})
    if prices:
        ledger = mark_to_market(
            ledger,
            prices,
            fee_bps=_paper_fee_bps(args),
            slippage_bps=_paper_slippage_bps(args),
            now_iso=_iso(cycle_time),
            max_holding_minutes=_paper_max_holding_minutes(args),
        )
        save_paper_ledger(ledger_path, ledger)
    summary = paper_ledger_summary(ledger)
    if mark_errors:
        summary["mark_errors"] = mark_errors
    summary["path"] = str(ledger_path)
    return summary


def _risk_policy_from_runtime(
    args: Any,
    cycle_time: datetime | None = None,
    state: dict[str, Any] | None = None,
    selected_symbol: str = "",
    latest_event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = _risk_policy_from_existing_ledger(args, cycle_time, selected_symbol=selected_symbol)
    policy.update(_strategy_state_policy_from_args(args, selected_symbol=selected_symbol, latest_event=latest_event))
    policy.update(_portfolio_risk_policy_from_args(args))
    _apply_reject_cooldown(policy, state or {}, cycle_time)
    sizing = _paper_sizing_from_args(args)
    leverage = _num(sizing.get("paper_leverage"))
    policy.update(
        {
            "paper_margin_budget_usdt": sizing["margin_budget_usdt"],
            "paper_leverage": leverage,
            "requested_margin_usdt": sizing["requested_margin_usdt"],
            "requested_notional_usdt": sizing["effective_notional_usdt"],
            "sizing_required": str(getattr(args, "mode", "paper") or "paper") == "paper",
            "sizing_source": sizing["source"],
            "max_leverage": _num(policy.get("max_leverage")),
            "max_symbol_notional_usdt": _num(policy.get("max_symbol_notional_usdt")),
            "max_total_notional_usdt": _num(policy.get("max_total_notional_usdt")),
        }
    )
    return policy


def _strategy_state_policy_from_args(
    args: Any, *, selected_symbol: str = "", latest_event: dict[str, Any] | None = None
) -> dict[str, Any]:
    path = str(getattr(args, "strategy_state_path", "") or "").strip()
    if not path:
        return {}
    try:
        state = load_strategy_state(path)
    except ValueError as exc:
        return {
            "force_reject_reasons": ["strategy_state_load_failed"],
            "strategy_state_error": str(exc),
        }
    return strategy_state_policy(state, selected_symbol=selected_symbol, latest_event=latest_event)


def _portfolio_risk_policy_from_args(args: Any) -> dict[str, Any]:
    policy: dict[str, Any] = {}
    kill_switch_path = str(getattr(args, "paper_kill_switch_path", "") or "").strip()
    if kill_switch_path:
        policy["kill_switch_file"] = kill_switch_path
    policy_path = str(getattr(args, "portfolio_risk_policy_path", "") or "").strip()
    if not policy_path:
        return policy
    try:
        loaded = load_portfolio_risk_policy(policy_path)
    except ValueError as exc:
        policy.setdefault("force_reject_reasons", []).append("portfolio_risk_policy_load_failed")
        policy["portfolio_risk_policy_error"] = str(exc)
        return policy
    if loaded is not None:
        policy["portfolio_risk_policy"] = loaded
    return policy


def _apply_reject_cooldown(policy: dict[str, Any], state: dict[str, Any], cycle_time: datetime | None) -> None:
    if not state.get("last_error") or cycle_time is None:
        return
    portfolio = policy.get("portfolio_risk_policy") if isinstance(policy.get("portfolio_risk_policy"), dict) else {}
    limits = portfolio.get("limits") if isinstance(portfolio.get("limits"), dict) else {}
    cooldown_minutes = _num(limits.get("cooldown_minutes_after_reject"))
    if cooldown_minutes is None or cooldown_minutes <= 0:
        return
    last_attempt = _parse_closed_at(state.get("last_attempt_at"))
    if last_attempt is None:
        return
    elapsed_minutes = max(0.0, (cycle_time.astimezone(UTC) - last_attempt.astimezone(UTC)).total_seconds() / 60.0)
    if elapsed_minutes < cooldown_minutes:
        policy["cooldown_active"] = True
        policy["cooldown_elapsed_minutes"] = elapsed_minutes
        policy["cooldown_limit_minutes"] = cooldown_minutes


def _risk_policy_from_existing_ledger(
    args: Any, cycle_time: datetime | None = None, *, selected_symbol: str = ""
) -> dict[str, Any]:
    ledger_path = _paper_ledger_path(args)
    if ledger_path is None or not ledger_path.exists():
        return {}
    try:
        ledger = load_paper_ledger(ledger_path, initial_balance_usdt=_initial_balance(args))
    except PaperLedgerError as exc:
        return {"force_reject_reasons": ["paper_ledger_load_failed"], "paper_ledger_error": str(exc)}
    open_positions = ledger.get("open_positions") if isinstance(ledger.get("open_positions"), dict) else {}
    raw_closed_positions = ledger.get("closed_positions")
    closed_positions: list[Any] = raw_closed_positions if isinstance(raw_closed_positions, list) else []
    current_total_notional = _open_positions_notional(open_positions)
    daily_realized = _daily_realized_pnl(closed_positions, cycle_time) if cycle_time is not None else None
    if daily_realized is None:
        daily_realized = float(ledger.get("realized_pnl_usdt") or 0.0)
    return {
        "current_open_positions": len(open_positions),
        "current_symbol_open_positions": _open_positions_for_symbol(open_positions, selected_symbol),
        "current_total_notional_usdt": current_total_notional,
        "daily_realized_pnl_usdt": daily_realized,
        "consecutive_losses": _consecutive_losses(closed_positions),
    }


def _open_positions_notional(open_positions: dict[str, Any]) -> float:
    total = 0.0
    for position in open_positions.values():
        if not isinstance(position, dict):
            continue
        notional = _num(position.get("notional_usdt"))
        if notional is None:
            entry_price = _num(position.get("entry_price")) or 0.0
            quantity = _num(position.get("quantity")) or 0.0
            notional = entry_price * quantity
        total += abs(float(notional or 0.0))
    return total


def _open_positions_for_symbol(open_positions: dict[str, Any], selected_symbol: str) -> int:
    symbol = str(selected_symbol or "").upper().strip()
    if not symbol:
        return 0
    return sum(
        1
        for position in open_positions.values()
        if isinstance(position, dict) and str(position.get("symbol") or "").upper().strip() == symbol
    )


def _daily_realized_pnl(closed_positions: list[Any], cycle_time: datetime) -> float | None:
    target_date = cycle_time.astimezone(UTC).date()
    total = 0.0
    matched = False
    for position in closed_positions:
        if not isinstance(position, dict):
            continue
        closed_at = _parse_closed_at(position.get("closed_at"))
        if closed_at is None or closed_at.astimezone(UTC).date() != target_date:
            continue
        pnl = _num(position.get("net_pnl_usdt"))
        if pnl is None:
            pnl = _num(position.get("pnl_usdt"))
        if pnl is None:
            continue
        total += pnl
        matched = True
    return total if matched else 0.0


def _consecutive_losses(closed_positions: list[Any]) -> int:
    ordered = [position for position in closed_positions if isinstance(position, dict)]
    ordered.sort(key=lambda item: _closed_sort_key(item))
    streak = 0
    for position in reversed(ordered):
        pnl = _num(position.get("net_pnl_usdt"))
        if pnl is None:
            pnl = _num(position.get("pnl_usdt"))
        if pnl is None:
            continue
        if pnl < 0:
            streak += 1
            continue
        break
    return streak


def _closed_sort_key(position: dict[str, Any]) -> tuple[int, str]:
    closed_at = _parse_closed_at(position.get("closed_at"))
    return (1 if closed_at is not None else 0, _iso(closed_at) if closed_at is not None else "")


def _parse_closed_at(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_state_time(value: Any) -> datetime | None:
    return _parse_closed_at(value)


def _ledger_error_summary(path: Path, exc: PaperLedgerError) -> dict[str, Any]:
    return {
        "schema": "tradecat_auto.paper_ledger_summary.v1",
        "schema_version": "1.0.0",
        "ok": False,
        "error": str(exc),
        "path": str(path),
    }


def _prices_for_open_positions(
    ledger: dict[str, Any], client: Any, selected_market_bundle: dict[str, Any]
) -> tuple[dict[str, float], list[Any]]:
    prices: dict[str, float] = {}
    errors: list[Any] = []
    open_positions = ledger.get("open_positions") if isinstance(ledger.get("open_positions"), dict) else {}
    selected_symbol = str(selected_market_bundle.get("symbol") or "").upper().strip()
    selected_price = _last_price_from_bundle(selected_market_bundle)
    symbols = list(
        dict.fromkeys(
            _position_symbol(position, fallback=key)
            for key, position in open_positions.items()
            if _position_symbol(position, fallback=key)
        )
    )
    fallback_symbols: list[str] = []
    remaining_symbols: list[str] = []
    for normalized in symbols:
        if not normalized:
            continue
        if normalized == selected_symbol and selected_price is not None:
            prices[normalized] = selected_price
            continue
        remaining_symbols.append(normalized)

    fetch_last_prices = getattr(client, "fetch_last_prices", None)
    if callable(fetch_last_prices) and remaining_symbols:
        price_payload = _safe_call(fetch_last_prices, remaining_symbols)
        price_map = price_payload.get("prices") if isinstance(price_payload.get("prices"), dict) else {}
        for normalized in remaining_symbols:
            price = _num(price_map.get(normalized))
            if price is None:
                fallback_symbols.append(normalized)
            else:
                prices[normalized] = price
        if price_payload.get("ok") is False and not price_map:
            errors.append(
                {
                    "symbols": remaining_symbols,
                    "error": price_payload.get("error")
                    or price_payload.get("errors")
                    or "missing_batch_lightweight_mark_prices",
                }
            )
    else:
        fallback_symbols = remaining_symbols

    for normalized in fallback_symbols:
        fetch_last_price = getattr(client, "fetch_last_price", None)
        if callable(fetch_last_price):
            price_payload = _safe_call(fetch_last_price, normalized)
            price = _last_price_from_bundle(price_payload)
            if price is None:
                errors.append(
                    {
                        "symbol": normalized,
                        "error": price_payload.get("error")
                        or price_payload.get("errors")
                        or "missing_lightweight_mark_price",
                    }
                )
            else:
                prices[normalized] = price
            continue
        bundle = _safe_call(client.fetch_public_market_bundle, normalized)
        price = _last_price_from_bundle(bundle)
        if price is None:
            errors.append(
                {"symbol": normalized, "error": bundle.get("error") or bundle.get("errors") or "missing_mark_price"}
            )
        else:
            prices[normalized] = price
    return prices, errors


def _position_symbol(position: Any, *, fallback: Any = "") -> str:
    if isinstance(position, dict):
        symbol = str(position.get("symbol") or "").upper().strip()
        if symbol:
            return symbol
    return str(fallback or "").upper().strip()


def _last_price_from_bundle(bundle: dict[str, Any]) -> float | None:
    ticker = bundle.get("ticker24hr") if isinstance(bundle.get("ticker24hr"), dict) else {}
    value = ticker.get("lastPrice") or bundle.get("last_price") or bundle.get("price")
    return _num(value)


def _journal_path(args: Any) -> Path | None:
    text = str(getattr(args, "journal_path", "") or "").strip()
    return Path(text) if text else None


def _journal_run_id(payload: dict[str, Any]) -> str:
    raw_latest_event = payload.get("latest_event")
    latest_event: dict[str, Any] = raw_latest_event if isinstance(raw_latest_event, dict) else {}
    event_id = str(latest_event.get("event_id") or "").strip()
    if event_id:
        return event_id
    raw_state = payload.get("state")
    state: dict[str, Any] = raw_state if isinstance(raw_state, dict) else {}
    last_attempt_at = str(state.get("last_attempt_at") or "").strip()
    action = str(payload.get("action") or "cycle")
    return f"{action}:{last_attempt_at}" if last_attempt_at else action


def _cycle_created_at(payload: dict[str, Any]) -> str | None:
    raw_state = payload.get("state")
    state: dict[str, Any] = raw_state if isinstance(raw_state, dict) else {}
    text = str(state.get("last_attempt_at") or "").strip()
    return text or None


def _journal_config_snapshot(args: Any) -> dict[str, Any]:
    sizing = _paper_sizing_from_args(args)
    return {
        "schema": "tradecat_auto.paper_runtime_config_snapshot.v1",
        "schema_version": "1.0.0",
        "source": "tradecat_auto.service",
        "mode": str(getattr(args, "mode", "paper") or "paper"),
        "symbol": str(getattr(args, "symbol", "auto") or "auto"),
        "notional_usdt": sizing["requested_notional_usdt"],
        "notional_semantics": "deprecated explicit effective notional override; no default paper order amount or budget cap",
        "paper_margin_budget_usdt": sizing["margin_budget_usdt"],
        "agent_margin_usdt": sizing["requested_margin_usdt"],
        "paper_leverage": sizing["paper_leverage"],
        "effective_notional_usdt": sizing["effective_notional_usdt"],
        "paper_sizing": sizing,
        "initial_balance_usdt": float(getattr(args, "initial_balance_usdt", 1000.0) or 0.0),
        "paper_fee_bps": float(getattr(args, "paper_fee_bps", BINANCE_USDM_PUBLIC_TAKER_FEE_BPS) or 0.0),
        "paper_fee_model": BINANCE_USDM_TAKER_FEE_MODEL,
        "paper_slippage_bps": float(getattr(args, "paper_slippage_bps", 0.0) or 0.0),
        "paper_max_holding_minutes": float(getattr(args, "paper_max_holding_minutes", 0.0) or 0.0),
        "paper_max_holding_minutes_semantics": "legacy status/config field only; time stops require Agent strategy_intent/agent_trade_thesis max_holding_minutes on the paper position",
        "event_limit": int(getattr(args, "event_limit", 0) or 0),
        "anomaly_limit": int(getattr(args, "anomaly_limit", 20) or 0),
        "max_event_age_seconds": _optional_float(getattr(args, "max_event_age_seconds", None)),
        "interval_seconds": float(getattr(args, "interval_seconds", 60.0) or 0.0),
        "maintenance_interval_seconds": _maintenance_interval_seconds(args),
        "base_url": str(getattr(args, "base_url", "") or ""),
        "runtime_paths": {
            "state_path": str(getattr(args, "state_path", "") or ""),
            "ledger_path": str(getattr(args, "ledger_path", "") or ""),
            "archive_path": str(getattr(args, "archive_path", "") or ""),
            "journal_path": str(getattr(args, "journal_path", "") or ""),
            "agent_trade_thesis_path": str(getattr(args, "agent_trade_thesis_path", "") or ""),
            "paper_autonomy_profile_path": str(getattr(args, "paper_autonomy_profile_path", "") or ""),
            "portfolio_risk_policy_path": str(getattr(args, "portfolio_risk_policy_path", "") or ""),
            "paper_kill_switch_path": str(getattr(args, "paper_kill_switch_path", "") or ""),
        },
        "safety": {
            "public_readonly_market_data": True,
            "paper_or_watch_only": True,
            "real_orders": False,
            "signed_requests": False,
            "reads_api_keys": False,
        },
    }


def _paper_ledger_path(args: Any) -> Path | None:
    text = str(getattr(args, "ledger_path", "") or "").strip()
    return Path(text) if text else None


def _agent_trade_thesis_from_args(args: Any) -> dict[str, Any] | None:
    return load_agent_trade_thesis(
        getattr(args, "agent_trade_thesis_path", "") or "",
        mode=str(getattr(args, "mode", "paper") or "paper"),
    )


def _agent_trade_thesis_error(exc: Exception) -> dict[str, Any]:
    return {
        "code": "agent_trade_thesis_load_failed",
        "kind": "input_validation",
        "message": str(exc),
        "retryable": False,
    }


def _paper_autonomy_profile_from_args(args: Any) -> dict[str, Any] | None:
    return load_paper_autonomy_profile(
        getattr(args, "paper_autonomy_profile_path", "") or "",
        mode=str(getattr(args, "mode", "paper") or "paper"),
    )


def _paper_autonomy_profile_error(exc: Exception) -> dict[str, Any]:
    return {
        "code": "paper_autonomy_profile_load_failed",
        "kind": "input_validation",
        "message": str(exc),
        "retryable": False,
    }


def _initial_balance(args: Any) -> float:
    return float(getattr(args, "initial_balance_usdt", 1000.0) or 1000.0)


def _paper_fee_bps(args: Any) -> float:
    return float(getattr(args, "paper_fee_bps", BINANCE_USDM_PUBLIC_TAKER_FEE_BPS) or 0.0)


def _paper_slippage_bps(args: Any) -> float:
    return float(getattr(args, "paper_slippage_bps", 0.0) or 0.0)


def _paper_sizing_from_args(args: Any) -> dict[str, Any]:
    explicit_effective_notional = getattr(args, "notional_usdt", None)
    agent_margin = getattr(args, "agent_margin_usdt", None)
    if agent_margin is None:
        agent_margin = getattr(args, "requested_margin_usdt", None)
    paper_leverage = getattr(args, "paper_leverage", None)
    margin_budget = getattr(args, "paper_margin_budget_usdt", None)
    return resolve_paper_sizing(
        requested_notional_usdt=explicit_effective_notional,
        requested_margin_usdt=agent_margin,
        paper_leverage=paper_leverage,
        margin_budget_usdt=margin_budget,
        sizing_source=_paper_sizing_source_from_args(args),
        sizing_required=str(getattr(args, "mode", "paper") or "paper") == "paper",
    )


def _paper_sizing_source_from_args(args: Any) -> str:
    if getattr(args, "agent_margin_usdt", None) is not None or getattr(args, "requested_margin_usdt", None) is not None:
        return "agent_supplied_cli_margin"
    if getattr(args, "notional_usdt", None) is not None:
        return "explicit_cli_effective_notional"
    if getattr(args, "paper_leverage", None) is not None:
        return "incomplete_cli_sizing"
    return "agent_required_missing"


def _paper_leverage(args: Any) -> float:
    value = _num(getattr(args, "paper_leverage", None))
    return value if value is not None and value > 0 else 0.0


def _paper_max_holding_minutes(args: Any) -> float:
    return float(getattr(args, "paper_max_holding_minutes", 0.0) or 0.0)


def _optional_float(value: Any) -> float | None:
    parsed = _num(value)
    return parsed if parsed is not None else None


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _event_age_seconds(event: dict[str, Any], now: datetime) -> float | None:
    source_time = _parse_source_time_bj(str(event.get("source_time_bj") or ""))
    if source_time is None:
        return None
    return max(0.0, (now.astimezone(UTC) - source_time.astimezone(UTC)).total_seconds())


def _parse_source_time_bj(text: str) -> datetime | None:
    clean = text.strip()
    if not clean:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(clean, fmt).replace(tzinfo=BEIJING)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=BEIJING)


def _coerce_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    return now if now.tzinfo else now.replace(tzinfo=UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
