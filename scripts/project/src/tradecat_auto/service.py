from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradecat_auto.audit_journal import record_service_cycle
from tradecat_auto.binance_market import normalize_to_usdt_perp_symbol
from tradecat_auto.paper_ledger import (
    PaperLedgerError,
    apply_paper_execution,
    load_paper_ledger,
    mark_to_market,
    paper_ledger_summary,
    save_paper_ledger,
)
from tradecat_auto.pipeline import build_paper_pipeline_report, resolve_paper_sizing

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
    state["last_attempt_at"] = _iso(cycle_time)
    state["cycles_attempted"] = int(state.get("cycles_attempted") or 0) + 1

    events = _safe_call(source.fetch_events, limit=getattr(args, "event_limit", 5))
    latest_event = _latest_event(events)
    if not events.get("ok") or not latest_event:
        state["last_error"] = events.get("error") or "no_events_available"
        save_service_state(path, state)
        return _archive_and_return(
            args,
            _cycle_payload(
                action="SKIPPED_NO_EVENT",
                ok=False,
                reason=str(state["last_error"]),
                state=state,
                events=events,
                latest_event=latest_event,
            ),
        )

    event_id = str(latest_event.get("event_id") or "").strip()
    event_age_seconds = _event_age_seconds(latest_event, cycle_time)
    max_age = getattr(args, "max_event_age_seconds", None)
    if max_age is not None and (event_age_seconds is None or event_age_seconds > float(max_age)):
        state["last_error"] = "stale_event"
        state["last_skipped_event_id"] = event_id
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
            ),
        )

    seen_event_ids = _seen_event_ids(state)
    if event_id and event_id in seen_event_ids:
        paper_ledger = _monitor_existing_paper_positions(args, client, cycle_time)
        ledger_failed = bool(paper_ledger and paper_ledger.get("ok") is False)
        state["last_duplicate_event_id"] = event_id
        state["last_error"] = paper_ledger.get("error") if ledger_failed else None
        save_service_state(path, state)
        return _archive_and_return(
            args,
            _cycle_payload(
                action="SKIPPED_DUPLICATE_EVENT",
                ok=not ledger_failed,
                reason="paper_ledger_monitor_failed" if ledger_failed else "event_id_already_seen",
                state=state,
                events=events,
                latest_event=latest_event,
                event_age_seconds=event_age_seconds,
                paper_ledger=paper_ledger,
            ),
        )

    universe = _safe_call(client.market_universe)
    tradable = set(universe.get("symbols") or []) if universe.get("ok") else set()
    anomaly = _safe_call(
        source.fetch_anomaly_symbols,
        tradable_symbols=tradable,
        limit=getattr(args, "anomaly_limit", 20),
    )
    selected_symbol = _select_symbol(str(getattr(args, "symbol", "auto")), tradable, anomaly)
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
                raw_errors=_collect_errors(universe, events, anomaly, market_bundle),
            ),
        )

    risk_policy = _risk_policy_from_runtime(args, cycle_time)
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
        risk_policy=risk_policy,
    )
    pipeline_report["universe"] = _summarize_universe(universe)
    pipeline_report["anomaly_symbols"] = {
        "ok": anomaly.get("ok"),
        "count": len(anomaly.get("symbols") or []),
        "rejected_count": len(anomaly.get("rejected") or []),
    }
    pipeline_report["raw_errors"] = _collect_errors(universe, events, anomaly, market_bundle)
    paper_ledger = _update_paper_ledger_from_cycle(args, client, pipeline_report, market_bundle, cycle_time)
    if paper_ledger:
        pipeline_report["paper_ledger"] = paper_ledger

    if event_id:
        _remember_event_id(state, event_id)
    state["last_success_at"] = _iso(cycle_time) if pipeline_report.get("ok") else state.get("last_success_at")
    state["last_processed_event_id"] = event_id
    state["last_selected_symbol"] = selected_symbol
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
        "last_attempt_at": None,
        "last_success_at": None,
        "last_error": None,
    }


def _cycle_payload(**kwargs: Any) -> dict[str, Any]:
    payload = {
        "schema": CYCLE_SCHEMA,
        "schema_version": "1.0.0",
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
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


def _seen_event_ids(state: dict[str, Any]) -> set[str]:
    return {str(item) for item in state.get("seen_event_ids") or [] if str(item)}


def _remember_event_id(state: dict[str, Any], event_id: str, *, max_ids: int = 500) -> None:
    existing = [str(item) for item in state.get("seen_event_ids") or [] if str(item)]
    updated = list(dict.fromkeys([event_id, *existing]))
    state["seen_event_ids"] = updated[:max_ids]


def _select_symbol(requested: str, tradable: set[str], anomaly: dict[str, Any]) -> str:
    text = str(requested or "auto").upper().strip()
    if text and text != "AUTO":
        return normalize_to_usdt_perp_symbol(text, tradable) or text
    for item in anomaly.get("symbols") or []:
        if isinstance(item, dict) and item.get("normalized_symbol"):
            return str(item["normalized_symbol"])
    return ""


def _summarize_universe(universe: dict[str, Any]) -> dict[str, Any]:
    symbols = universe.get("symbols") or []
    return {
        "ok": universe.get("ok"),
        "symbol_count": len(symbols),
        "first_10": symbols[:10],
        "rate_limits": universe.get("rate_limits", [])[:3],
        "error": universe.get("error"),
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


def _risk_policy_from_runtime(args: Any, cycle_time: datetime | None = None) -> dict[str, Any]:
    policy = _risk_policy_from_existing_ledger(args, cycle_time)
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


def _risk_policy_from_existing_ledger(args: Any, cycle_time: datetime | None = None) -> dict[str, Any]:
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


def _ledger_error_summary(path: Path, exc: PaperLedgerError) -> dict[str, Any]:
    return {
        "schema": "tradecat_auto.paper_ledger_summary.v1",
        "schema_version": "1.0.0",
        "ok": False,
        "error": str(exc),
        "path": str(path),
    }


def _prices_for_open_positions(ledger: dict[str, Any], client: Any, selected_market_bundle: dict[str, Any]) -> tuple[dict[str, float], list[Any]]:
    prices: dict[str, float] = {}
    errors: list[Any] = []
    open_positions = ledger.get("open_positions") if isinstance(ledger.get("open_positions"), dict) else {}
    selected_symbol = str(selected_market_bundle.get("symbol") or "").upper().strip()
    selected_price = _last_price_from_bundle(selected_market_bundle)
    for symbol in open_positions:
        normalized = str(symbol or "").upper().strip()
        if not normalized:
            continue
        if normalized == selected_symbol and selected_price is not None:
            prices[normalized] = selected_price
            continue
        bundle = _safe_call(client.fetch_public_market_bundle, normalized)
        price = _last_price_from_bundle(bundle)
        if price is None:
            errors.append({"symbol": normalized, "error": bundle.get("error") or bundle.get("errors") or "missing_mark_price"})
        else:
            prices[normalized] = price
    return prices, errors


def _last_price_from_bundle(bundle: dict[str, Any]) -> float | None:
    ticker = bundle.get("ticker24hr") if isinstance(bundle.get("ticker24hr"), dict) else {}
    value = ticker.get("lastPrice") or bundle.get("last_price")
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
        "paper_fee_bps": float(getattr(args, "paper_fee_bps", 2.0) or 0.0),
        "paper_fee_model": "binance_usdm_vip0_maker_assumption",
        "paper_slippage_bps": float(getattr(args, "paper_slippage_bps", 0.5) or 0.0),
        "paper_max_holding_minutes": float(getattr(args, "paper_max_holding_minutes", 0.0) or 0.0),
        "paper_max_holding_minutes_semantics": "legacy status/config field only; time stops require Agent strategy_intent/agent_trade_thesis max_holding_minutes on the paper position",
        "event_limit": int(getattr(args, "event_limit", 5) or 0),
        "anomaly_limit": int(getattr(args, "anomaly_limit", 20) or 0),
        "max_event_age_seconds": float(getattr(args, "max_event_age_seconds", 300.0) or 0.0),
        "interval_seconds": float(getattr(args, "interval_seconds", 60.0) or 0.0),
        "base_url": str(getattr(args, "base_url", "") or ""),
        "runtime_paths": {
            "state_path": str(getattr(args, "state_path", "") or ""),
            "ledger_path": str(getattr(args, "ledger_path", "") or ""),
            "archive_path": str(getattr(args, "archive_path", "") or ""),
            "journal_path": str(getattr(args, "journal_path", "") or ""),
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


def _initial_balance(args: Any) -> float:
    return float(getattr(args, "initial_balance_usdt", 1000.0) or 1000.0)


def _paper_fee_bps(args: Any) -> float:
    return float(getattr(args, "paper_fee_bps", 2.0) or 0.0)


def _paper_slippage_bps(args: Any) -> float:
    return float(getattr(args, "paper_slippage_bps", 0.5) or 0.0)


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
