from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from tradecat_auto.audit_journal import journal_summary
from tradecat_auto.paper_ledger import PaperLedgerError, load_paper_ledger, paper_ledger_summary

SCHEMA_VERSION = "1.0.0"
BENIGN_LAST_ERRORS = {"no_events_available"}


def build_health_report(
    *,
    state_path: Path | str,
    ledger_path: Path | str,
    archive_path: Path | str,
    journal_path: Path | str,
    now_iso: str | None = None,
    max_heartbeat_age_seconds: float = 180.0,
) -> dict[str, Any]:
    now_text = now_iso or _now_iso()
    state_payload = _read_json_object(Path(state_path))
    state = state_payload.get("data") if state_payload.get("ok") else {}
    state = state if isinstance(state, dict) else {}
    heartbeat = _heartbeat(state, now_text, max_heartbeat_age_seconds=max_heartbeat_age_seconds)
    ledger = _ledger_health(Path(ledger_path))
    archive = _archive_health(Path(archive_path))
    audit = journal_summary(Path(journal_path))

    alerts: list[str] = []
    if not state_payload.get("ok"):
        alerts.append("service_state_missing")
    if heartbeat.get("stale"):
        alerts.append("heartbeat_stale")
    last_error = state.get("last_error")
    if last_error and str(last_error) not in BENIGN_LAST_ERRORS:
        alerts.append("last_error_present")
    if not ledger.get("ok"):
        alerts.append(str(ledger.get("alert") or "paper_ledger_unhealthy"))
    if not archive.get("ok"):
        alerts.append(str(archive.get("alert") or "cycle_archive_unhealthy"))
    if not audit.get("ok"):
        raw_error_value = audit.get("error")
        raw_error: dict[str, Any] = raw_error_value if isinstance(raw_error_value, dict) else {}
        alerts.append(str(raw_error.get("code") or "audit_journal_unhealthy"))
    if not audit.get("chain_valid", True):
        alerts.append("audit_chain_invalid")

    status = "healthy" if not alerts else "degraded"
    return {
        "schema": "tradecat_auto.production_health.v1",
        "schema_version": SCHEMA_VERSION,
        "ok": not alerts,
        "status": status,
        "generated_at": now_text,
        "heartbeat": heartbeat,
        "service_state": {
            "ok": bool(state_payload.get("ok")),
            "path": str(state_path),
            "cycles_attempted": int(state.get("cycles_attempted") or 0),
            "cycles_processed": int(state.get("cycles_processed") or 0),
            "last_attempt_at": state.get("last_attempt_at"),
            "last_success_at": state.get("last_success_at"),
            "last_processed_event_id": state.get("last_processed_event_id"),
            "last_selected_symbol": state.get("last_selected_symbol"),
            "last_error": state.get("last_error"),
        },
        "ledger": ledger,
        "archive": archive,
        "audit_journal": audit,
        "alerts": alerts,
        "safety": _safety_boundary(),
    }


def build_daily_report(*, ledger_path: Path | str, archive_path: Path | str, date: str | None = None) -> dict[str, Any]:
    report_date = date or _today_iso()
    ledger_health = _ledger_health(Path(ledger_path))
    archive = _archive_health(Path(archive_path))
    ledger_data: dict[str, Any] = {}
    if Path(ledger_path).exists():
        try:
            ledger_data = load_paper_ledger(Path(ledger_path))
        except PaperLedgerError:
            ledger_data = {}
    cycle_counts = archive.get("action_counts") if isinstance(archive.get("action_counts"), dict) else {}
    trades = _closed_positions_for_date(ledger_data, report_date)
    fills = _fills_for_date(ledger_data, report_date)
    return {
        "schema": "tradecat_auto.daily_paper_report.v1",
        "schema_version": SCHEMA_VERSION,
        "ok": bool(ledger_health.get("ok") and archive.get("ok")),
        "date": report_date,
        "ledger_path": str(ledger_path),
        "archive_path": str(archive_path),
        "ledger_summary": ledger_health.get("summary") or {},
        "cycle_counts": cycle_counts,
        "cycle_count": int(archive.get("cycle_count") or 0),
        "trades": trades,
        "fills": fills,
        "alerts": [] if ledger_health.get("ok") and archive.get("ok") else [
            item for item in [ledger_health.get("alert"), archive.get("alert")] if item
        ],
        "safety": _safety_boundary(),
    }


def build_telegram_alerts(report: dict[str, Any]) -> dict[str, Any]:
    schema = str(report.get("schema") or "")
    if schema == "tradecat_auto.daily_paper_report.v1":
        text = _daily_alert_text(report)
        kind = "daily_report"
    elif schema == "tradecat_auto.production_health.v1":
        text = _health_alert_text(report)
        kind = "health"
    else:
        text = f"TradeCat paper report: schema={schema or 'unknown'} ok={bool(report.get('ok'))}"
        kind = "generic"
    return {
        "schema": "tradecat_auto.telegram_alerts.v1",
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "alerts": [
            {
                "kind": kind,
                "text": text,
                "parse_mode": "plain_text",
                "real_orders": False,
                "signed_requests": False,
                "reads_api_keys": False,
            }
        ],
        "safety": _safety_boundary(),
    }


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"ok": False, "path": str(path), "error": "missing"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "path": str(path), "error": f"load_failed: {exc}"}
    if not isinstance(data, dict):
        return {"ok": False, "path": str(path), "error": "not_object"}
    return {"ok": True, "path": str(path), "data": data}


def _heartbeat(state: dict[str, Any], now_iso: str, *, max_heartbeat_age_seconds: float) -> dict[str, Any]:
    last_attempt = str(state.get("last_attempt_at") or "").strip()
    age = _age_seconds(last_attempt, now_iso)
    stale = age is None or age > float(max_heartbeat_age_seconds)
    return {
        "ok": not stale,
        "last_attempt_at": last_attempt or None,
        "age_seconds": age,
        "max_age_seconds": float(max_heartbeat_age_seconds),
        "stale": stale,
    }


def _ledger_health(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"ok": False, "path": str(path), "alert": "paper_ledger_missing"}
    try:
        ledger = load_paper_ledger(path)
    except PaperLedgerError as exc:
        return {"ok": False, "path": str(path), "alert": "paper_ledger_load_failed", "error": str(exc)}
    return {"ok": True, "path": str(path), "summary": paper_ledger_summary(ledger)}


def _archive_health(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"ok": False, "path": str(path), "alert": "cycle_archive_missing", "cycle_count": 0, "action_counts": {}}
    action_counts: Counter[str] = Counter()
    malformed = 0
    cycle_count = 0
    last_cycle: dict[str, Any] = {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    malformed += 1
                    continue
                if not isinstance(payload, dict):
                    malformed += 1
                    continue
                cycle_count += 1
                action_counts[str(payload.get("action") or "UNKNOWN")] += 1
                last_cycle = payload
    except OSError as exc:
        return {"ok": False, "path": str(path), "alert": "cycle_archive_load_failed", "error": str(exc), "cycle_count": cycle_count, "action_counts": dict(action_counts)}
    return {
        "ok": malformed == 0,
        "path": str(path),
        "cycle_count": cycle_count,
        "action_counts": dict(action_counts),
        "malformed_lines": malformed,
        "last_action": last_cycle.get("action"),
        "alert": "cycle_archive_malformed" if malformed else None,
    }


def _closed_positions_for_date(ledger: dict[str, Any], report_date: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for position in ledger.get("closed_positions") or []:
        if not isinstance(position, dict):
            continue
        closed_at = str(position.get("closed_at") or "")
        if report_date and closed_at and not closed_at.startswith(report_date):
            continue
        rows.append(
            {
                "position_id": position.get("position_id"),
                "symbol": position.get("symbol"),
                "side": position.get("side"),
                "opened_at": position.get("opened_at"),
                "closed_at": position.get("closed_at"),
                "entry_price": position.get("entry_price"),
                "exit_price": position.get("exit_price"),
                "quantity": position.get("quantity"),
                "net_pnl_usdt": position.get("net_pnl_usdt"),
                "close_reason": position.get("close_reason"),
                "real_order": False,
            }
        )
    return rows


def _fills_for_date(ledger: dict[str, Any], report_date: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fill in ledger.get("fills") or []:
        if not isinstance(fill, dict):
            continue
        created_at = str(fill.get("created_at") or "")
        if report_date and created_at and not created_at.startswith(report_date):
            continue
        item = dict(fill)
        item["real_order"] = False
        rows.append(item)
    return rows


def _daily_alert_text(report: dict[str, Any]) -> str:
    raw_summary = report.get("ledger_summary")
    summary: dict[str, Any] = raw_summary if isinstance(raw_summary, dict) else {}
    raw_cycle_counts = report.get("cycle_counts")
    cycle_counts: dict[str, Any] = raw_cycle_counts if isinstance(raw_cycle_counts, dict) else {}
    return (
        "TradeCat paper daily "
        f"{report.get('date')}: ok={bool(report.get('ok'))}, "
        f"equity={summary.get('equity_usdt')}, realized={summary.get('realized_pnl_usdt')}, "
        f"open={summary.get('open_positions_count')}, closed={summary.get('closed_positions_count')}, "
        f"cycles={report.get('cycle_count')}, processed={cycle_counts.get('PROCESSED', 0)}, "
        "boundary=public-readonly paper/watch; real_orders=false"
    )


def _health_alert_text(report: dict[str, Any]) -> str:
    raw_heartbeat = report.get("heartbeat")
    heartbeat: dict[str, Any] = raw_heartbeat if isinstance(raw_heartbeat, dict) else {}
    alerts = [str(item) for item in (report.get("alerts") or [])]
    return (
        f"TradeCat paper health: status={report.get('status')}, ok={bool(report.get('ok'))}, "
        f"heartbeat_age={heartbeat.get('age_seconds')}, alerts={','.join(alerts) or 'none'}, "
        "real_orders=false"
    )


def _age_seconds(then_iso: str, now_iso: str) -> float | None:
    then = _parse_iso(then_iso)
    now = _parse_iso(now_iso)
    if then is None or now is None:
        return None
    return max(0.0, (now - then).total_seconds())


def _parse_iso(text: str) -> datetime | None:
    clean = str(text or "").strip()
    if not clean:
        return None
    try:
        parsed = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _today_iso() -> str:
    return date.today().isoformat()


def _safety_boundary() -> dict[str, bool]:
    return {
        "public_readonly_market_data": True,
        "public_readonly": True,
        "paper_or_watch_only": True,
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "binance_account_state": False,
    }
