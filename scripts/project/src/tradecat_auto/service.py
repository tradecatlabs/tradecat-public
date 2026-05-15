from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradecat_auto.binance_market import normalize_to_usdt_perp_symbol
from tradecat_auto.paper_ledger import (
    PaperLedgerError,
    apply_paper_execution,
    load_paper_ledger,
    mark_to_market,
    paper_ledger_summary,
    save_paper_ledger,
)
from tradecat_auto.pipeline import build_paper_pipeline_report

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
            "ok": False,
            "errors": {"symbol": "no tradable symbol selected"},
        }
    )

    if not selected_symbol:
        state["last_error"] = "no_symbol_selected"
        save_service_state(path, state)
        return _cycle_payload(
            action="ERROR",
            ok=False,
            reason="no_symbol_selected",
            state=state,
            events=events,
            latest_event=latest_event,
            universe=_summarize_universe(universe),
            raw_errors=_collect_errors(universe, events, anomaly, market_bundle),
        )

    risk_policy = _risk_policy_from_existing_ledger(args)
    pipeline_report = build_paper_pipeline_report(
        selected_symbol=selected_symbol,
        anomaly_symbols=anomaly,
        market_bundle=market_bundle,
        events=events,
        mode=str(getattr(args, "mode", "paper")),
        requested_notional_usdt=float(getattr(args, "notional_usdt", 10.0)),
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
    _archive_cycle(args, payload)
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
    payload = {"schema": CYCLE_SCHEMA}
    payload.update(kwargs)
    return payload


def _archive_and_return(args: Any, payload: dict[str, Any]) -> dict[str, Any]:
    _archive_cycle(args, payload)
    return payload


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
    return "BTCUSDT" if "BTCUSDT" in tradable else (sorted(tradable)[0] if tradable else "")


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
        )
        save_paper_ledger(ledger_path, ledger)
    summary = paper_ledger_summary(ledger)
    if mark_errors:
        summary["mark_errors"] = mark_errors
    summary["path"] = str(ledger_path)
    return summary


def _risk_policy_from_existing_ledger(args: Any) -> dict[str, Any]:
    ledger_path = _paper_ledger_path(args)
    if ledger_path is None or not ledger_path.exists():
        return {}
    try:
        ledger = load_paper_ledger(ledger_path, initial_balance_usdt=_initial_balance(args))
    except PaperLedgerError as exc:
        return {"force_reject_reasons": ["paper_ledger_load_failed"], "paper_ledger_error": str(exc)}
    open_positions = ledger.get("open_positions") if isinstance(ledger.get("open_positions"), dict) else {}
    current_total_notional = _open_positions_notional(open_positions)
    return {
        "current_open_positions": len(open_positions),
        "current_total_notional_usdt": current_total_notional,
        "daily_realized_pnl_usdt": float(ledger.get("realized_pnl_usdt") or 0.0),
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


def _ledger_error_summary(path: Path, exc: PaperLedgerError) -> dict[str, Any]:
    return {
        "schema": "tradecat_auto.paper_ledger_summary.v1",
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


def _paper_ledger_path(args: Any) -> Path | None:
    text = str(getattr(args, "ledger_path", "") or "").strip()
    return Path(text) if text else None


def _initial_balance(args: Any) -> float:
    return float(getattr(args, "initial_balance_usdt", 1000.0) or 1000.0)


def _paper_fee_bps(args: Any) -> float:
    return float(getattr(args, "paper_fee_bps", 4.0) or 0.0)


def _paper_slippage_bps(args: Any) -> float:
    return float(getattr(args, "paper_slippage_bps", 0.0) or 0.0)


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
