from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tradecat_auto.audit_journal import journal_summary
from tradecat_auto.paper_ledger import PaperLedgerError, load_paper_ledger, load_paper_ledger_from_object
from tradecat_auto.safety_boundary import paper_watch_safety_boundary

SCHEMA_VERSION = "1.0.0"


def build_replay_report(
    *,
    archive_path: Path | str,
    ledger_path: Path | str | None = None,
    journal_path: Path | str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    report_time = generated_at or _now_iso()
    archive = Path(archive_path)
    cycles, errors = _load_jsonl(archive)
    ledger: dict[str, Any] | None = None
    ledger_error = None
    if ledger_path is not None:
        try:
            ledger = load_paper_ledger(Path(ledger_path))
        except (PaperLedgerError, OSError) as exc:
            ledger_error = f"{type(exc).__name__}: {exc}"

    archive_sha256 = _sha256_file(archive) if archive.exists() else ""
    archive_summary = _summarize_cycles(cycles)
    archive_summary["path"] = str(archive)
    archive_summary["sha256"] = archive_sha256
    archive_summary["load_errors"] = errors

    paper_backtest = (
        build_paper_backtest_report(ledger, generated_at=report_time)
        if ledger is not None
        else {
            "schema": "tradecat_auto.paper_backtest_report.v1",
            "schema_version": SCHEMA_VERSION,
            "ok": False,
            "error": {
                "code": "paper_ledger_missing" if ledger_error is None else "paper_ledger_load_failed",
                "kind": "local_state",
                "message": ledger_error or "ledger_path was not provided",
                "retryable": False,
            },
            "metrics": _empty_metrics(),
        }
    )

    decision_trace = _build_decision_trace_report_from_cycles(
        archive_path=archive,
        cycles=cycles,
        errors=errors,
        journal_path=journal_path,
        generated_at=report_time,
        archive_sha256=archive_sha256,
    )
    decision_quality = build_decision_quality_report_from_reports(
        decision_trace, paper_backtest, generated_at=report_time
    )
    ok = not errors and bool(cycles) and paper_backtest.get("ok") is True
    return {
        "schema": "tradecat_auto.replay_report.v1",
        "schema_version": SCHEMA_VERSION,
        "ok": ok,
        "generated_at": report_time,
        "archive": archive_summary,
        "decision_trace": decision_trace,
        "decision_quality": decision_quality,
        "paper_backtest": paper_backtest,
        "safety": {
            **_replay_safety(),
            "write_paths": [str(archive), str(ledger_path) if ledger_path is not None else ""],
        },
        "limitations": [
            "replay uses local service-cycle JSONL and optional paper ledger only",
            "no Binance credentials were read",
            "no real order was placed",
        ],
    }


def build_decision_quality_report(
    *,
    archive_path: Path | str,
    ledger_path: Path | str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    report_time = generated_at or _now_iso()
    decision_trace = build_decision_trace_report(archive_path=archive_path, generated_at=report_time)
    ledger: dict[str, Any] | None = None
    if ledger_path is not None:
        try:
            ledger = load_paper_ledger(Path(ledger_path))
        except (PaperLedgerError, OSError):
            ledger = None
    paper_backtest = (
        build_paper_backtest_report(ledger, generated_at=report_time)
        if ledger is not None
        else {
            "schema": "tradecat_auto.paper_backtest_report.v1",
            "schema_version": SCHEMA_VERSION,
            "ok": False,
            "metrics": _empty_metrics(),
            "closed_positions_count": 0,
        }
    )
    return build_decision_quality_report_from_reports(decision_trace, paper_backtest, generated_at=report_time)


def build_decision_quality_report_from_reports(
    decision_trace: dict[str, Any],
    paper_backtest: dict[str, Any],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    traces = [item for item in decision_trace.get("traces") or [] if isinstance(item, dict)]
    error_counts = {str(key): int(value) for key, value in (decision_trace.get("error_code_counts") or {}).items()}
    decision_counts = {str(key): int(value) for key, value in (decision_trace.get("decision_counts") or {}).items()}
    metrics = paper_backtest.get("metrics") if isinstance(paper_backtest.get("metrics"), dict) else _empty_metrics()
    risk_reject_count = sum(1 for trace in traces if trace.get("risk_decision") == "REJECT")
    return {
        "schema": "tradecat_auto.decision_quality_report.v1",
        "schema_version": SCHEMA_VERSION,
        "ok": bool(decision_trace.get("ok")) and bool(paper_backtest.get("ok", True)),
        "generated_at": generated_at or _now_iso(),
        "trace_count": int(decision_trace.get("trace_count") or len(traces)),
        "decision_counts": decision_counts,
        "error_code_counts": error_counts,
        "agent_input_completeness": {
            "missing_sizing_count": error_counts.get("agent_sizing_required", 0),
            "missing_exit_plan_count": error_counts.get("agent_exit_plan_required", 0),
            "context_audit_reject_count": _context_audit_reject_count(error_counts),
            "risk_reject_count": risk_reject_count,
        },
        "paper_outcomes": {
            "opened_count": decision_counts.get("OPENED", 0),
            "rejected_count": decision_counts.get("REJECTED", 0),
            "closed_positions_count": int(paper_backtest.get("closed_positions_count") or 0),
            "open_positions_count": int(metrics.get("open_positions_count") or 0),
            "net_pnl_usdt": float(metrics.get("net_pnl_usdt") or 0.0),
            "win_rate": float(metrics.get("win_rate") or 0.0),
            "max_drawdown_usdt": float(metrics.get("max_drawdown_usdt") or 0.0),
        },
        "quality_notes": [
            "paper/watch engineering review only",
            "not investment advice",
            "use error_code_counts to improve Agent context/thesis completeness",
        ],
        "provenance": {"source": "tradecat_auto.replay.build_decision_quality_report_from_reports"},
        "safety": {**_replay_safety(), "not_investment_advice": True},
    }


def build_decision_trace_report(
    *,
    archive_path: Path | str,
    journal_path: Path | str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    archive = Path(archive_path)
    cycles, errors = _load_jsonl(archive)
    return _build_decision_trace_report_from_cycles(
        archive_path=archive,
        cycles=cycles,
        errors=errors,
        journal_path=journal_path,
        generated_at=generated_at,
        archive_sha256=_sha256_file(archive) if archive.exists() else "",
    )


def _build_decision_trace_report_from_cycles(
    *,
    archive_path: Path,
    cycles: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    journal_path: Path | str | None = None,
    generated_at: str | None = None,
    archive_sha256: str = "",
) -> dict[str, Any]:
    archive = Path(archive_path)
    traces = [_decision_trace_from_cycle(cycle, index) for index, cycle in enumerate(cycles)]
    decision_counts: dict[str, int] = {}
    error_code_counts: dict[str, int] = {}
    for trace in traces:
        decision = str(trace.get("decision") or "NO_EXECUTION")
        decision_counts[decision] = decision_counts.get(decision, 0) + 1
        for code in trace.get("error_codes") or []:
            error_code_counts[str(code)] = error_code_counts.get(str(code), 0) + 1
    source_paths = {
        "archive_path": str(archive),
        "journal_path": str(journal_path) if journal_path is not None else "",
        "archive_sha256": archive_sha256,
    }
    payload = {
        "schema": "tradecat_auto.decision_trace_report.v1",
        "schema_version": SCHEMA_VERSION,
        "ok": not errors and bool(traces),
        "generated_at": generated_at or _now_iso(),
        "trace_count": len(traces),
        "opened_count": decision_counts.get("OPENED", 0),
        "rejected_count": decision_counts.get("REJECTED", 0),
        "decision_counts": decision_counts,
        "error_code_counts": error_code_counts,
        "source_paths": source_paths,
        "traces": traces,
        "load_errors": errors,
        "provenance": {"source": "tradecat_auto.replay.build_decision_trace_report"},
        "safety": _replay_safety(),
    }
    if journal_path is not None and str(journal_path):
        payload["audit_journal"] = journal_summary(Path(journal_path))
    return payload


def build_paper_backtest_report(ledger: dict[str, Any], *, generated_at: str | None = None) -> dict[str, Any]:
    normalized = load_paper_ledger_from_object(ledger if isinstance(ledger, dict) else {})
    closed_positions = [item for item in normalized.get("closed_positions") or [] if isinstance(item, dict)]
    fills = [item for item in normalized.get("fills") or [] if isinstance(item, dict)]
    equity_curve = [item for item in normalized.get("equity_curve") or [] if isinstance(item, dict)]
    pnl_values = [_num(item.get("net_pnl_usdt")) or _fallback_position_pnl(item) for item in closed_positions]
    metrics = _metrics_from_series(
        pnl_values=pnl_values,
        equity_values=[_num(item.get("equity_usdt")) for item in equity_curve],
        initial_balance=_num(normalized.get("initial_balance_usdt")) or 0.0,
        fills_count=len(fills),
        open_positions_count=len(normalized.get("open_positions") or {}),
    )
    return {
        "schema": "tradecat_auto.paper_backtest_report.v1",
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "generated_at": generated_at or _now_iso(),
        "metrics": metrics,
        "closed_positions_count": len(closed_positions),
        "fills_count": len(fills),
        "equity_curve_points": len(equity_curve),
        "safety": {**_replay_safety(), "paper_only": True},
    }


def _decision_trace_from_cycle(cycle: dict[str, Any], index: int) -> dict[str, Any]:
    pipeline = cycle.get("pipeline_report") if isinstance(cycle.get("pipeline_report"), dict) else {}
    execution = pipeline.get("paper_execution") if isinstance(pipeline.get("paper_execution"), dict) else {}
    risk = pipeline.get("risk_decision") if isinstance(pipeline.get("risk_decision"), dict) else {}
    signal = pipeline.get("signal") if isinstance(pipeline.get("signal"), dict) else {}
    ledger = cycle.get("paper_ledger") if isinstance(cycle.get("paper_ledger"), dict) else {}
    service_action = str(cycle.get("action") or "UNKNOWN")
    execution_status = str(execution.get("status") or "")
    risk_decision = str(risk.get("decision") or "")
    error_codes = _trace_error_codes(cycle, pipeline, execution, risk)
    decision = _trace_decision(service_action, execution_status, risk_decision, error_codes)
    run_id = _trace_run_id(cycle, pipeline, execution)
    event_id = _trace_event_id(cycle)
    trace_id = _trace_id(run_id, event_id, index, service_action, pipeline, execution)
    return {
        "schema": "tradecat_auto.decision_trace.v1",
        "schema_version": SCHEMA_VERSION,
        "ok": decision not in {"ERROR"} and not bool(error_codes),
        "trace_id": trace_id,
        "cycle_index": index,
        "run_id": run_id,
        "event_id": event_id,
        "research_cycle_run_id": _trace_research_cycle_run_id(pipeline, execution, ledger),
        "service_action": service_action,
        "selected_symbol": str(
            pipeline.get("selected_symbol") or execution.get("symbol") or signal.get("symbol") or ""
        ).upper(),
        "decision": decision,
        "error_code": error_codes[0] if error_codes else None,
        "error_codes": error_codes,
        "risk_decision": risk_decision,
        "risk_reasons": [str(item) for item in risk.get("reasons") or [] if str(item)],
        "paper_execution_status": execution_status,
        "paper_execution_id": str(execution.get("paper_execution_id") or ""),
        "paper_fill_count": len(ledger.get("recent_fills") or ledger.get("fills") or []),
        "provenance": {"source": "tradecat_auto.replay._decision_trace_from_cycle"},
        "safety": _replay_safety(),
    }


def _load_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cycles: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if not path.exists():
        return cycles, [{"code": "archive_missing", "message": f"archive does not exist: {path}"}]
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append({"code": "invalid_jsonl", "line": line_number, "message": str(exc)})
                    continue
                if isinstance(payload, dict):
                    cycles.append(payload)
                else:
                    errors.append(
                        {
                            "code": "invalid_cycle_payload",
                            "line": line_number,
                            "message": "cycle root is not an object",
                        }
                    )
    except OSError as exc:
        return cycles, [{"code": "archive_read_failed", "message": str(exc)}]
    return cycles, errors


def _summarize_cycles(cycles: list[dict[str, Any]]) -> dict[str, Any]:
    processed_count = 0
    opened_count = 0
    rejected_count = 0
    risk_reject_count = 0
    symbols: list[str] = []
    actions: dict[str, int] = {}
    for cycle in cycles:
        action = str(cycle.get("action") or "UNKNOWN")
        actions[action] = actions.get(action, 0) + 1
        raw_pipeline = cycle.get("pipeline_report")
        pipeline: dict[str, Any] = raw_pipeline if isinstance(raw_pipeline, dict) else {}
        if action == "PROCESSED":
            processed_count += 1
        symbol = str(pipeline.get("selected_symbol") or "").upper().strip()
        if symbol:
            symbols.append(symbol)
        raw_execution = pipeline.get("paper_execution")
        execution: dict[str, Any] = raw_execution if isinstance(raw_execution, dict) else {}
        status = execution.get("status")
        if status == "OPENED" and _cycle_open_countable(cycle, pipeline):
            opened_count += 1
        elif status == "REJECTED":
            rejected_count += 1
        raw_risk = pipeline.get("risk_decision")
        risk: dict[str, Any] = raw_risk if isinstance(raw_risk, dict) else {}
        if risk.get("decision") == "REJECT":
            risk_reject_count += 1
    return {
        "schema": "tradecat_auto.replay_archive_summary.v1",
        "schema_version": SCHEMA_VERSION,
        "cycle_count": len(cycles),
        "processed_count": processed_count,
        "opened_count": opened_count,
        "rejected_count": rejected_count,
        "risk_reject_count": risk_reject_count,
        "actions": actions,
        "symbols": list(dict.fromkeys(symbols)),
    }


def _trace_decision(service_action: str, execution_status: str, risk_decision: str, error_codes: list[str]) -> str:
    if service_action.startswith("SKIPPED"):
        return "SKIPPED"
    if service_action == "ERROR":
        return "ERROR"
    if execution_status == "OPENED" and error_codes:
        return "ERROR"
    if execution_status == "OPENED":
        return "OPENED"
    if execution_status == "REJECTED" or risk_decision == "REJECT":
        return "REJECTED"
    if risk_decision == "WATCH_ONLY":
        return "WATCH_ONLY"
    if error_codes:
        return "ERROR"
    return "NO_EXECUTION"


def _cycle_open_countable(cycle: dict[str, Any], pipeline: dict[str, Any]) -> bool:
    return (
        cycle.get("ok") is not False
        and pipeline.get("ok") is not False
        and not (cycle.get("error_code") or pipeline.get("error_code"))
    )


def _context_audit_reject_count(error_counts: dict[str, int]) -> int:
    return sum(
        count
        for code, count in error_counts.items()
        if code.startswith("agent_market_context_")
        or code
        in {
            "context_audit_failed",
            "signed_request_rejected",
            "credential_material_rejected",
            "forbidden_endpoint_rejected",
        }
    )


def _trace_error_codes(
    cycle: dict[str, Any],
    pipeline: dict[str, Any],
    execution: dict[str, Any],
    risk: dict[str, Any],
) -> list[str]:
    codes: list[str] = []
    for value in (
        cycle.get("error_code"),
        pipeline.get("error_code"),
        execution.get("error_code"),
    ):
        if value:
            codes.append(str(value))
    for reason in execution.get("reasons") or []:
        if reason:
            codes.append(str(reason))
    for reason in risk.get("reasons") or []:
        if reason and risk.get("decision") == "REJECT":
            codes.append(str(reason))
    if cycle.get("action") == "SKIPPED_DUPLICATE_EVENT":
        codes.append("event_id_already_seen")
    if cycle.get("action") == "SKIPPED_NO_EVENT":
        codes.append(str(cycle.get("reason") or "no_events_available"))
    return list(dict.fromkeys(code for code in codes if code and code != "None"))


def _trace_run_id(cycle: dict[str, Any], pipeline: dict[str, Any], execution: dict[str, Any]) -> str:
    for value in (
        cycle.get("run_id"),
        cycle.get("audit_journal", {}).get("run_id") if isinstance(cycle.get("audit_journal"), dict) else "",
        pipeline.get("run_id"),
        execution.get("paper_execution_id"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _trace_event_id(cycle: dict[str, Any]) -> str:
    latest_event = cycle.get("latest_event") if isinstance(cycle.get("latest_event"), dict) else {}
    return str(cycle.get("event_id") or latest_event.get("event_id") or "").strip()


def _trace_research_cycle_run_id(pipeline: dict[str, Any], execution: dict[str, Any], ledger: dict[str, Any]) -> str:
    for value in (
        pipeline.get("research_cycle_run_id"),
        execution.get("research_cycle_run_id"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    for fill in ledger.get("recent_fills") or ledger.get("fills") or []:
        if isinstance(fill, dict) and fill.get("research_cycle_run_id"):
            return str(fill["research_cycle_run_id"])
    return ""


def _trace_id(
    run_id: str,
    event_id: str,
    index: int,
    service_action: str,
    pipeline: dict[str, Any],
    execution: dict[str, Any],
) -> str:
    material = json.dumps(
        {
            "run_id": run_id,
            "event_id": event_id,
            "index": index,
            "service_action": service_action,
            "selected_symbol": pipeline.get("selected_symbol"),
            "paper_execution_id": execution.get("paper_execution_id"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _replay_safety() -> dict[str, bool]:
    return paper_watch_safety_boundary()


def _metrics_from_series(
    *,
    pnl_values: list[float],
    equity_values: list[float | None],
    initial_balance: float,
    fills_count: int,
    open_positions_count: int,
) -> dict[str, Any]:
    trade_count = len(pnl_values)
    wins = [value for value in pnl_values if value > 0]
    losses = [value for value in pnl_values if value < 0]
    breakeven = [value for value in pnl_values if value == 0]
    gross_profit = sum(wins)
    gross_loss = sum(losses)
    net_pnl = sum(pnl_values)
    profit_factor = (gross_profit / abs(gross_loss)) if gross_loss < 0 else None
    equity_clean = [float(value) for value in equity_values if value is not None]
    max_drawdown = _max_drawdown(equity_clean)
    return {
        "trade_count": trade_count,
        "fills_count": fills_count,
        "open_positions_count": open_positions_count,
        "win_count": len(wins),
        "loss_count": len(losses),
        "breakeven_count": len(breakeven),
        "win_rate": len(wins) / trade_count if trade_count else 0.0,
        "loss_rate": len(losses) / trade_count if trade_count else 0.0,
        "gross_profit_usdt": gross_profit,
        "gross_loss_usdt": gross_loss,
        "net_pnl_usdt": net_pnl,
        "profit_factor": profit_factor,
        "avg_trade_pnl_usdt": net_pnl / trade_count if trade_count else 0.0,
        "max_drawdown_usdt": max_drawdown,
        "net_return_pct": (net_pnl / initial_balance * 100) if initial_balance else 0.0,
        "ending_equity_usdt": equity_clean[-1] if equity_clean else initial_balance + net_pnl,
    }


def _max_drawdown(equity_values: list[float]) -> float:
    if not equity_values:
        return 0.0
    peak = equity_values[0]
    max_drawdown = 0.0
    for value in equity_values:
        if value > peak:
            peak = value
        drawdown = peak - value
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    return max_drawdown


def _fallback_position_pnl(position: dict[str, Any]) -> float:
    value = _num(position.get("pnl_usdt"))
    if value is not None:
        return value
    entry = _num(position.get("entry_price")) or 0.0
    exit_price = _num(position.get("exit_price")) or entry
    quantity = _num(position.get("quantity")) or 0.0
    side = str(position.get("side") or "LONG").upper()
    if side == "SHORT":
        return (entry - exit_price) * quantity
    return (exit_price - entry) * quantity


def _empty_metrics() -> dict[str, Any]:
    return _metrics_from_series(
        pnl_values=[], equity_values=[], initial_balance=0.0, fills_count=0, open_positions_count=0
    )


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
