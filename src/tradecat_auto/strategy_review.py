from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tradecat_auto.paper_ledger import PaperLedgerError, load_paper_ledger

SCHEMA_VERSION = "1.0.0"
STRATEGY_REVIEW_SCHEMA = "tradecat_auto.strategy_review_report.v1"
STRATEGY_STATE_SCHEMA = "tradecat_auto.strategy_state.v1"


def build_strategy_review_report(
    *,
    ledger_path: Path | str,
    archive_path: Path | str | None = None,
    min_closed_positions: int = 50,
    min_symbol_trades: int = 5,
    symbol_loss_usdt: float = 0.75,
    symbol_win_rate_below: float = 0.35,
    min_signal_type_trades: int = 20,
    signal_type_loss_usdt: float = 2.0,
    signal_type_win_rate_below: float = 0.38,
    min_side_trades: int = 100,
    side_loss_usdt: float = 10.0,
    side_win_rate_below: float = 0.38,
    max_open_positions: int = 50,
    max_positions_per_symbol: int = 3,
    generated_at: str | None = None,
) -> dict[str, Any]:
    report_time = generated_at or _now_iso()
    try:
        ledger = load_paper_ledger(ledger_path)
    except (PaperLedgerError, OSError) as exc:
        return _review_error(ledger_path, archive_path, exc, report_time)

    closed_positions = [item for item in ledger.get("closed_positions") or [] if isinstance(item, dict)]
    open_positions = [item for item in (ledger.get("open_positions") or {}).values() if isinstance(item, dict)]
    cycles, archive_errors = _load_cycles(archive_path)
    execution_context = _execution_context_by_id(cycles)
    symbol_metrics = _group_metrics(closed_positions, key_func=lambda item: _text(item.get("symbol")))
    side_metrics = _group_metrics(closed_positions, key_func=lambda item: _text(item.get("side")))
    signal_type_metrics = _group_metrics(
        closed_positions,
        key_func=lambda item: _signal_type_for_position(item, execution_context),
    )
    blocked_symbols = _blocked_keys(
        symbol_metrics,
        min_trades=min_symbol_trades,
        max_loss_usdt=symbol_loss_usdt,
        max_win_rate=symbol_win_rate_below,
    )
    blocked_signal_types = _blocked_keys(
        signal_type_metrics,
        min_trades=min_signal_type_trades,
        max_loss_usdt=signal_type_loss_usdt,
        max_win_rate=signal_type_win_rate_below,
        exclude={"-", "UNKNOWN"},
    )
    blocked_sides = _blocked_keys(
        side_metrics,
        min_trades=min_side_trades,
        max_loss_usdt=side_loss_usdt,
        max_win_rate=side_win_rate_below,
        allowed={"LONG", "SHORT"},
    )
    thresholds = {
        "min_closed_positions": min_closed_positions,
        "min_symbol_trades": min_symbol_trades,
        "symbol_loss_usdt": symbol_loss_usdt,
        "symbol_win_rate_below": symbol_win_rate_below,
        "min_signal_type_trades": min_signal_type_trades,
        "signal_type_loss_usdt": signal_type_loss_usdt,
        "signal_type_win_rate_below": signal_type_win_rate_below,
        "min_side_trades": min_side_trades,
        "side_loss_usdt": side_loss_usdt,
        "side_win_rate_below": side_win_rate_below,
        "max_open_positions": max_open_positions,
        "max_positions_per_symbol": max_positions_per_symbol,
    }
    strategy_state = build_strategy_state(
        closed_positions_count=len(closed_positions),
        open_positions_count=len(open_positions),
        thresholds=thresholds,
        blocked_symbols=blocked_symbols,
        blocked_signal_types=blocked_signal_types,
        blocked_sides=blocked_sides,
        generated_at=report_time,
    )
    if len(closed_positions) < min_closed_positions:
        strategy_state["enabled"] = False
        strategy_state["status"] = "insufficient_closed_positions"
        strategy_state["policy"]["new_entries_enabled"] = True
        strategy_state["policy"]["blocked_symbols"] = []
        strategy_state["policy"]["blocked_signal_types"] = []
        strategy_state["policy"]["blocked_sides"] = []

    return {
        "schema": STRATEGY_REVIEW_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "error_code": None,
        "generated_at": report_time,
        "ledger_path": str(ledger_path),
        "archive_path": str(archive_path or ""),
        "closed_positions_count": len(closed_positions),
        "open_positions_count": len(open_positions),
        "review_status": strategy_state["status"],
        "thresholds": thresholds,
        "metrics": {
            "overall": _metric_summary(closed_positions),
            "by_symbol": symbol_metrics,
            "by_side": side_metrics,
            "by_signal_type": signal_type_metrics,
            "open_symbols": dict(Counter(_text(item.get("symbol")) for item in open_positions)),
        },
        "recommendations": {
            "blocked_symbols": blocked_symbols,
            "blocked_signal_types": blocked_signal_types,
            "blocked_sides": blocked_sides,
            "max_open_positions": max_open_positions,
            "max_positions_per_symbol": max_positions_per_symbol,
        },
        "strategy_state": strategy_state,
        "archive_errors": archive_errors,
        "provenance": {
            "source": "tradecat_auto.strategy_review.build_strategy_review_report",
            "ledger_schema": str(ledger.get("schema") or ""),
        },
        "safety": _safety_boundary(),
        "limitations": [
            "paper/watch outcome review only",
            "does not read Binance credentials",
            "does not place real orders",
            "strategy state is a local runtime paper filter, not investment advice",
        ],
    }


def build_strategy_state(
    *,
    closed_positions_count: int,
    open_positions_count: int,
    thresholds: dict[str, Any],
    blocked_symbols: list[str],
    blocked_signal_types: list[str],
    blocked_sides: list[str],
    generated_at: str | None = None,
) -> dict[str, Any]:
    return {
        "schema": STRATEGY_STATE_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "enabled": True,
        "status": "active",
        "generated_at": generated_at or _now_iso(),
        "closed_positions_count": int(closed_positions_count),
        "open_positions_count": int(open_positions_count),
        "policy": {
            "new_entries_enabled": True,
            "max_open_positions": _positive_int(thresholds.get("max_open_positions")),
            "max_positions_per_symbol": _positive_int(thresholds.get("max_positions_per_symbol")),
            "blocked_symbols": blocked_symbols,
            "blocked_signal_types": blocked_signal_types,
            "blocked_sides": blocked_sides,
        },
        "thresholds": dict(thresholds),
        "provenance": {"source": "tradecat_auto.strategy_review.build_strategy_state"},
        "safety": _safety_boundary(),
        "limitations": ["local runtime paper/watch filter only", "not a real order instruction"],
    }


def save_strategy_state(path: Path | str, state: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_strategy_state(path: Path | str | None) -> dict[str, Any] | None:
    text = str(path or "").strip()
    if not text:
        return None
    p = Path(text)
    if not p.exists():
        return None
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"strategy_state_load_failed: {p}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("strategy_state_load_failed: state root must be an object")
    if payload.get("schema") != STRATEGY_STATE_SCHEMA:
        raise ValueError(f"strategy_state_load_failed: schema must be {STRATEGY_STATE_SCHEMA}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"strategy_state_load_failed: schema_version must be {SCHEMA_VERSION}")
    _validate_safety(payload.get("safety"))
    return payload


def strategy_state_policy(
    strategy_state: dict[str, Any] | None,
    *,
    selected_symbol: str = "",
    latest_event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(strategy_state, dict) or strategy_state.get("enabled") is False:
        return {}
    policy = strategy_state.get("policy") if isinstance(strategy_state.get("policy"), dict) else {}
    signal_type = _signal_type_from_event(latest_event or {})
    return {
        "strategy_state": _strategy_state_snapshot(strategy_state),
        "strategy_state_enabled": True,
        "strategy_state_generated_at": str(strategy_state.get("generated_at") or ""),
        "current_signal_type": signal_type,
        "current_strategy_symbol": str(selected_symbol or "").upper().strip(),
        "new_entries_enabled": policy.get("new_entries_enabled", True),
        "max_open_positions": _positive_int(policy.get("max_open_positions")),
        "max_positions_per_symbol": _positive_int(policy.get("max_positions_per_symbol")),
        "blocked_symbols": _string_list(policy.get("blocked_symbols"), uppercase=True),
        "blocked_signal_types": _string_list(policy.get("blocked_signal_types")),
        "blocked_sides": _string_list(policy.get("blocked_sides"), uppercase=True),
    }


def _review_error(
    ledger_path: Path | str, archive_path: Path | str | None, exc: Exception, generated_at: str
) -> dict[str, Any]:
    return {
        "schema": STRATEGY_REVIEW_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "error_code": "strategy_review_ledger_load_failed",
        "generated_at": generated_at,
        "ledger_path": str(ledger_path),
        "archive_path": str(archive_path or ""),
        "error": {
            "code": "strategy_review_ledger_load_failed",
            "kind": "local_runtime_state",
            "message": f"{type(exc).__name__}: {exc}",
            "retryable": False,
        },
        "strategy_state": build_strategy_state(
            closed_positions_count=0,
            open_positions_count=0,
            thresholds={},
            blocked_symbols=[],
            blocked_signal_types=[],
            blocked_sides=[],
            generated_at=generated_at,
        ),
        "provenance": {"source": "tradecat_auto.strategy_review.build_strategy_review_report"},
        "safety": _safety_boundary(),
    }


def _load_cycles(path: Path | str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    text = str(path or "").strip()
    if not text:
        return [], []
    archive = Path(text)
    if not archive.exists():
        return [], []
    cycles: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for line_number, line in enumerate(archive.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append({"line": line_number, "error": str(exc)})
            continue
        if isinstance(payload, dict):
            cycles.append(payload)
    return cycles, errors


def _execution_context_by_id(cycles: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for cycle in cycles:
        pipeline = cycle.get("pipeline_report") if isinstance(cycle.get("pipeline_report"), dict) else {}
        execution = pipeline.get("paper_execution") if isinstance(pipeline.get("paper_execution"), dict) else {}
        execution_id = _text(execution.get("paper_execution_id") or execution.get("execution_id"))
        if not execution_id:
            continue
        event = cycle.get("latest_event") if isinstance(cycle.get("latest_event"), dict) else {}
        if not event:
            event = pipeline.get("latest_event") if isinstance(pipeline.get("latest_event"), dict) else {}
        result[execution_id] = {
            "signal_type": _signal_type_from_event(event),
            "event_id": _text(event.get("event_id")),
            "source_dataset_key": _text(event.get("source_dataset_key")),
        }
    return result


def _group_metrics(positions: list[dict[str, Any]], *, key_func: Any) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for position in positions:
        key = key_func(position) or "-"
        groups.setdefault(str(key), []).append(position)
    return {key: _metric_summary(items) for key, items in sorted(groups.items())}


def _metric_summary(positions: list[dict[str, Any]]) -> dict[str, Any]:
    pnls = [_num(item.get("net_pnl_usdt")) or 0.0 for item in positions]
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    fees = sum(
        (_num(item.get("entry_fee_usdt")) or 0.0) + (_num(item.get("exit_fee_usdt")) or 0.0) for item in positions
    )
    gross = sum((_num(item.get("gross_pnl_usdt")) or 0.0) for item in positions)
    exit_reasons = Counter(str(item.get("close_reason") or "-") for item in positions)
    return {
        "trades": len(positions),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(positions) if positions else 0.0,
        "net_pnl_usdt": sum(pnls),
        "gross_pnl_usdt": gross,
        "fees_usdt": fees,
        "avg_win_usdt": sum(wins) / len(wins) if wins else 0.0,
        "avg_loss_usdt": sum(losses) / len(losses) if losses else 0.0,
        "exit_reasons": dict(exit_reasons),
    }


def _blocked_keys(
    metrics: dict[str, dict[str, Any]],
    *,
    min_trades: int,
    max_loss_usdt: float,
    max_win_rate: float,
    exclude: set[str] | None = None,
    allowed: set[str] | None = None,
) -> list[str]:
    excluded = exclude or set()
    result: list[str] = []
    for key, item in metrics.items():
        if key in excluded:
            continue
        if allowed is not None and key not in allowed:
            continue
        trades = int(item.get("trades") or 0)
        net_pnl = _num(item.get("net_pnl_usdt")) or 0.0
        win_rate = _num(item.get("win_rate")) or 0.0
        if trades >= min_trades and net_pnl <= -abs(max_loss_usdt) and win_rate <= max_win_rate:
            result.append(key)
    return result


def _signal_type_for_position(position: dict[str, Any], execution_context: dict[str, dict[str, str]]) -> str:
    execution_id = _text(position.get("execution_id") or position.get("paper_execution_id"))
    context = execution_context.get(execution_id) if execution_id else None
    if context:
        return context.get("signal_type") or "-"
    return "-"


def _signal_type_from_event(event: dict[str, Any]) -> str:
    if not isinstance(event, dict):
        return ""
    values = event.get("source_values") if isinstance(event.get("source_values"), dict) else {}
    return _text(event.get("signal_type") or event.get("type") or values.get("类型"))


def _strategy_state_snapshot(strategy_state: dict[str, Any]) -> dict[str, Any]:
    policy = strategy_state.get("policy") if isinstance(strategy_state.get("policy"), dict) else {}
    return {
        "schema": STRATEGY_STATE_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "enabled": bool(strategy_state.get("enabled", True)),
        "status": str(strategy_state.get("status") or ""),
        "generated_at": str(strategy_state.get("generated_at") or ""),
        "closed_positions_count": int(strategy_state.get("closed_positions_count") or 0),
        "open_positions_count": int(strategy_state.get("open_positions_count") or 0),
        "policy": {
            "new_entries_enabled": policy.get("new_entries_enabled"),
            "max_open_positions": policy.get("max_open_positions"),
            "max_positions_per_symbol": policy.get("max_positions_per_symbol"),
            "blocked_symbols_count": len(_string_list(policy.get("blocked_symbols"))),
            "blocked_signal_types_count": len(_string_list(policy.get("blocked_signal_types"))),
            "blocked_sides": _string_list(policy.get("blocked_sides"), uppercase=True),
        },
    }


def _validate_safety(value: Any) -> None:
    safety = value if isinstance(value, dict) else {}
    expected = {
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "binance_account_state": False,
    }
    for key, expected_value in expected.items():
        if safety.get(key) is not expected_value:
            raise ValueError(f"strategy_state_load_failed: safety.{key} must be {expected_value!r}")


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _string_list(value: Any, *, uppercase: bool = False) -> list[str]:
    if not isinstance(value, list):
        return []
    result = [str(item or "").strip() for item in value if str(item or "").strip()]
    if uppercase:
        result = [item.upper() for item in result]
    return list(dict.fromkeys(result))


def _text(value: Any) -> str:
    return str(value or "").strip()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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
