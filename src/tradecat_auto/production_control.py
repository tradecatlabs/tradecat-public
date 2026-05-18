from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from tradecat_auto.audit_journal import journal_summary
from tradecat_auto.paper_ledger import PaperLedgerError, load_paper_ledger, paper_ledger_summary

SCHEMA_VERSION = "1.0.0"
BENIGN_LAST_ERROR_CODES = {
    "agent_sizing_required",
    "agent_exit_plan_required",
    "no_events_available",
    "no_anomaly_signal_available",
    "signal_not_tradable",
    "position_already_open_for_symbol",
    "max_concurrent_positions_per_symbol_reached",
}
DEFAULT_AUTO_PAPER_RUNTIME_DIR = Path(".runtime/auto-paper")
DEFAULT_AUTO_PAPER_STATE_PATH = DEFAULT_AUTO_PAPER_RUNTIME_DIR / "service_state.json"
DEFAULT_AUTO_PAPER_LEDGER_PATH = DEFAULT_AUTO_PAPER_RUNTIME_DIR / "paper_ledger.json"
DEFAULT_AUTO_PAPER_ARCHIVE_PATH = DEFAULT_AUTO_PAPER_RUNTIME_DIR / "cycles.jsonl"
DEFAULT_AUTO_PAPER_JOURNAL_PATH = DEFAULT_AUTO_PAPER_RUNTIME_DIR / "paper_audit.sqlite3"


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
    if _last_error_is_alertable(last_error):
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
            "last_full_cycle_at": state.get("last_full_cycle_at"),
            "last_input_changed_at": state.get("last_input_changed_at"),
            "last_trigger_reason": state.get("last_trigger_reason"),
            "last_processed_event_id": state.get("last_processed_event_id"),
            "last_selected_symbol": state.get("last_selected_symbol"),
            "last_error": state.get("last_error"),
            "last_error_code": _last_error_code(state.get("last_error")),
        },
        "ledger": ledger,
        "archive": archive,
        "audit_journal": audit,
        "alerts": alerts,
        "safety": _safety_boundary(),
    }


def build_latest_cycle_report(*, archive_path: Path | str) -> dict[str, Any]:
    cycle = _read_latest_jsonl(Path(archive_path))
    ok = bool(cycle)
    return {
        "schema": "tradecat_auto.latest_cycle_report.v1",
        "schema_version": SCHEMA_VERSION,
        "ok": ok,
        "error_code": None if ok else "latest_cycle_unavailable",
        "archive_path": str(archive_path),
        "cycle": cycle,
        "summary": _cycle_summary(cycle),
        "provenance": {"source": "local_tradecat_cycle_archive", "archive_path": str(archive_path)},
        "safety": _safety_boundary(),
    }


def build_latest_decision_report(*, archive_path: Path | str) -> dict[str, Any]:
    cycle = _read_latest_jsonl(Path(archive_path), predicate=lambda item: isinstance(item.get("pipeline_report"), dict))
    pipeline = cycle.get("pipeline_report") if isinstance(cycle.get("pipeline_report"), dict) else {}
    if not pipeline:
        return {
            "schema": "tradecat_auto.latest_decision_report.v1",
            "schema_version": SCHEMA_VERSION,
            "ok": False,
            "error_code": "latest_decision_unavailable",
            "archive_path": str(archive_path),
            "text": "当前还没有可展示的 Agent/TradeCat 决策产物；等待 auto-paper 写入包含 pipeline_report 的 cycle。",
            "cycle": {},
            "provenance": {"source": "local_tradecat_cycle_archive", "archive_path": str(archive_path)},
            "safety": _safety_boundary(),
            "limitations": ["auditable decision summary only; not hidden model chain-of-thought"],
        }
    event = _as_dict(cycle.get("latest_event") or pipeline.get("latest_event"))
    thesis = _as_dict(pipeline.get("agent_trade_thesis"))
    signal = _as_dict(pipeline.get("signal"))
    strategy = _as_dict(pipeline.get("strategy_intent"))
    risk = _as_dict(pipeline.get("risk_decision"))
    execution = _as_dict(pipeline.get("paper_execution"))
    sizing = _as_dict(pipeline.get("paper_sizing"))
    sections = [
        _text_section(
            "输入信号",
            [
                ("来源", event.get("source_dataset_key")),
                ("时间", event.get("source_time_bj") or pipeline.get("generated_at")),
                ("事件 ID", event.get("event_id")),
                ("币种", event.get("symbol") or pipeline.get("selected_symbol")),
                ("类型", event.get("signal_type")),
                ("内容", event.get("content")),
            ],
        ),
        _text_section(
            "Agent thesis",
            [
                ("来源", _decision_thesis_source(thesis)),
                ("方向", thesis.get("direction") or strategy.get("direction") or signal.get("direction")),
                ("信心", thesis.get("confidence")),
                ("理由", thesis.get("rationale")),
                ("风险备注", _join_text_list(thesis.get("risk_notes"))),
            ],
        ),
        _text_section(
            "策略与退出计划",
            [
                ("动作", strategy.get("action")),
                ("入场价", strategy.get("entry_price")),
                ("止损/失效价", strategy.get("invalidation_price")),
                ("止盈价", strategy.get("take_profit_price")),
                ("最长持仓分钟", strategy.get("max_holding_minutes")),
                ("退出来源", strategy.get("exit_plan_source")),
            ],
        ),
        _text_section(
            "风控与 sizing",
            [
                ("决定", risk.get("decision")),
                ("原因", _join_text_list(risk.get("reasons"))),
                ("sizing 来源", sizing.get("source")),
                ("请求保证金 USDT", sizing.get("requested_margin_usdt")),
                ("纸面杠杆", sizing.get("paper_leverage")),
                ("有效名义金额 USDT", sizing.get("effective_notional_usdt")),
            ],
        ),
        _text_section(
            "纸面执行",
            [
                ("状态", execution.get("status")),
                ("方向", execution.get("side")),
                ("名义金额 USDT", execution.get("notional_usdt")),
                ("保证金 USDT", execution.get("margin_usdt")),
                ("数量", execution.get("quantity")),
                ("拒绝原因", _join_text_list(execution.get("reasons"))),
            ],
        ),
    ]
    text = "\n\n".join(section["text"] for section in sections if section["text"])
    return {
        "schema": "tradecat_auto.latest_decision_report.v1",
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "error_code": None,
        "archive_path": str(archive_path),
        "symbol": thesis.get("symbol") or pipeline.get("selected_symbol") or signal.get("symbol"),
        "direction": thesis.get("direction") or strategy.get("direction") or signal.get("direction"),
        "risk_decision": risk.get("decision"),
        "paper_execution_status": execution.get("status"),
        "text": text,
        "sections": sections,
        "cycle_summary": _cycle_summary(cycle),
        "provenance": {
            "source": "local_tradecat_cycle_archive",
            "archive_path": str(archive_path),
            "cycle_schema": str(cycle.get("schema") or ""),
            "pipeline_schema": str(pipeline.get("schema") or ""),
            "event_id": str(event.get("event_id") or ""),
        },
        "safety": {**_safety_boundary(), **_as_dict(pipeline.get("safety"))},
        "limitations": ["auditable decision summary only; not hidden model chain-of-thought"],
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
        "alerts": []
        if ledger_health.get("ok") and archive.get("ok")
        else [item for item in [ledger_health.get("alert"), archive.get("alert")] if item],
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
    status = "missing" if age is None else "stale" if stale else "fresh"
    return {
        "ok": not stale,
        "status": status,
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
        return {
            "ok": False,
            "path": str(path),
            "alert": "cycle_archive_load_failed",
            "error": str(exc),
            "cycle_count": cycle_count,
            "action_counts": dict(action_counts),
        }
    return {
        "ok": malformed == 0,
        "path": str(path),
        "cycle_count": cycle_count,
        "action_counts": dict(action_counts),
        "malformed_lines": malformed,
        "last_action": last_cycle.get("action"),
        "alert": "cycle_archive_malformed" if malformed else None,
    }


def _read_latest_jsonl(path: Path, *, predicate: Callable[[dict[str, Any]], bool] | None = None) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 1048576), 0)
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return {}
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and (predicate is None or predicate(payload)):
            return payload
    return {}


def _cycle_summary(cycle: dict[str, Any]) -> dict[str, Any]:
    pipeline = cycle.get("pipeline_report") if isinstance(cycle.get("pipeline_report"), dict) else {}
    execution = pipeline.get("paper_execution") if isinstance(pipeline.get("paper_execution"), dict) else {}
    event = cycle.get("latest_event") if isinstance(cycle.get("latest_event"), dict) else {}
    return {
        "action": cycle.get("action"),
        "ok": cycle.get("ok"),
        "error_code": cycle.get("error_code") or pipeline.get("error_code"),
        "reason": cycle.get("reason"),
        "selected_symbol": pipeline.get("selected_symbol") or event.get("symbol"),
        "event_id": event.get("event_id"),
        "source_dataset_key": event.get("source_dataset_key"),
        "source_time_bj": event.get("source_time_bj"),
        "risk_decision": _as_dict(pipeline.get("risk_decision")).get("decision"),
        "paper_execution_status": execution.get("status"),
    }


def _last_error_code(value: Any) -> str | None:
    if isinstance(value, dict):
        return str(value.get("code") or value.get("error_code") or "").strip() or None
    text = str(value or "").strip()
    return text or None


def _last_error_is_alertable(value: Any) -> bool:
    code = _last_error_code(value)
    if not code:
        return False
    if code in BENIGN_LAST_ERROR_CODES:
        return False
    if isinstance(value, dict) and str(value.get("kind") or "") == "risk_reject" and not value.get("retryable"):
        return False
    return True


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _join_text_list(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if str(item))
    return str(value) if value not in (None, "") else ""


def _decision_thesis_source(thesis: dict[str, Any]) -> str:
    provenance = _as_dict(thesis.get("provenance"))
    if provenance.get("paper_autonomy_profile"):
        return "paper_autonomy_profile 合成的 paper-only Agent thesis"
    if thesis:
        return "外部 Agent/Hermes thesis"
    return "未提供 thesis"


def _text_section(title: str, pairs: list[tuple[str, Any]]) -> dict[str, str]:
    lines = [f"{label}: {value}" for label, value in pairs if value not in (None, "", [])]
    return {"title": title, "text": "\n".join(lines)}


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
