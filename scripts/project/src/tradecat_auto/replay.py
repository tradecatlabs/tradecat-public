from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tradecat_auto.paper_ledger import PaperLedgerError, load_paper_ledger, load_paper_ledger_from_object

SCHEMA_VERSION = "1.0.0"


def build_replay_report(*, archive_path: Path | str, ledger_path: Path | str | None = None) -> dict[str, Any]:
    archive = Path(archive_path)
    cycles, errors = _load_jsonl(archive)
    ledger: dict[str, Any] | None = None
    ledger_error = None
    if ledger_path is not None:
        try:
            ledger = load_paper_ledger(Path(ledger_path))
        except (PaperLedgerError, OSError) as exc:
            ledger_error = f"{type(exc).__name__}: {exc}"

    archive_summary = _summarize_cycles(cycles)
    archive_summary["path"] = str(archive)
    archive_summary["sha256"] = _sha256_file(archive) if archive.exists() else ""
    archive_summary["load_errors"] = errors

    paper_backtest = build_paper_backtest_report(ledger) if ledger is not None else {
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

    ok = not errors and bool(cycles) and paper_backtest.get("ok") is True
    return {
        "schema": "tradecat_auto.replay_report.v1",
        "schema_version": SCHEMA_VERSION,
        "ok": ok,
        "generated_at": _now_iso(),
        "archive": archive_summary,
        "paper_backtest": paper_backtest,
        "safety": {
            "public_readonly": True,
            "paper_or_watch_only": True,
            "real_orders": False,
            "signed_requests": False,
            "reads_api_keys": False,
            "write_paths": [str(archive), str(ledger_path) if ledger_path is not None else ""],
        },
        "limitations": [
            "replay uses local service-cycle JSONL and optional paper ledger only",
            "no Binance credentials were read",
            "no real order was placed",
        ],
    }


def build_paper_backtest_report(ledger: dict[str, Any]) -> dict[str, Any]:
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
        "generated_at": _now_iso(),
        "metrics": metrics,
        "closed_positions_count": len(closed_positions),
        "fills_count": len(fills),
        "equity_curve_points": len(equity_curve),
        "safety": {
            "paper_only": True,
            "real_orders": False,
            "signed_requests": False,
            "reads_api_keys": False,
        },
    }


def _load_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cycles: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if not path.exists():
        return cycles, [{"code": "archive_missing", "message": f"archive does not exist: {path}"}]
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return cycles, [{"code": "archive_read_failed", "message": str(exc)}]
    for line_number, line in enumerate(lines, start=1):
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
            errors.append({"code": "invalid_cycle_payload", "line": line_number, "message": "cycle root is not an object"})
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
        if status == "OPENED":
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
    return _metrics_from_series(pnl_values=[], equity_values=[], initial_balance=0.0, fills_count=0, open_positions_count=0)


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
