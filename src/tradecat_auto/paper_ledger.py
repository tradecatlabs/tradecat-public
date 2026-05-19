from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tradecat_auto.safety_boundary import (
    forbidden_private_or_real_trade_hits,
    paper_watch_hard_boundaries,
    paper_watch_safety_boundary,
)

try:  # pragma: no cover - non-POSIX fallback
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

LEDGER_SCHEMA = "tradecat_auto.paper_ledger.v1"
PAPER_ACCOUNT_STATE_SCHEMA = "tradecat_auto.paper_account_state.v1"
POSITION_MANAGEMENT_ACTION_REPORT_SCHEMA = "tradecat_auto.position_management_action_report.v1"
SCHEMA_VERSION = "1.0.0"
DEFAULT_INITIAL_BALANCE_USDT = 1000.0
DEFAULT_FEE_BPS = 4.0
DEFAULT_SLIPPAGE_BPS = 0.0


class PaperLedgerError(ValueError):
    """Raised when an existing paper ledger cannot be trusted."""


def default_paper_ledger(*, initial_balance_usdt: float = DEFAULT_INITIAL_BALANCE_USDT) -> dict[str, Any]:
    balance = _non_negative(initial_balance_usdt, "initial_balance_usdt")
    return {
        "schema": LEDGER_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "cash_balance_usdt": balance,
        "equity_usdt": balance,
        "initial_balance_usdt": balance,
        "realized_pnl_usdt": 0.0,
        "unrealized_pnl_usdt": 0.0,
        "open_positions": {},
        "closed_positions": [],
        "paper_orders": [],
        "fills": [],
        "applied_execution_ids": [],
        "ignored_execution_ids": [],
        "equity_curve": [],
        "last_updated_at": None,
        "provenance": {"source": "local_tradecat_paper_ledger"},
        "safety": _safety_boundary(),
    }


def load_paper_ledger(
    path: Path | str, *, initial_balance_usdt: float = DEFAULT_INITIAL_BALANCE_USDT
) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return default_paper_ledger(initial_balance_usdt=initial_balance_usdt)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PaperLedgerError(f"paper_ledger_load_failed: {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise PaperLedgerError(f"paper_ledger_load_failed: {p}: ledger root is not an object")
    _validate_loaded_payload(data, p)
    ledger = default_paper_ledger(initial_balance_usdt=initial_balance_usdt)
    ledger.update(data)
    return _recalculate_equity(_normalize_ledger_shape(ledger))


@contextmanager
def paper_ledger_lock(path: Path | str):
    """Serialize local read-modify-write updates for one paper ledger file."""

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lock_path = p.with_suffix(f"{p.suffix}.lock") if p.suffix else p.with_name(f"{p.name}.lock")
    with lock_path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def save_paper_ledger(path: Path | str, ledger: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = _recalculate_equity(dict(ledger))
    payload["schema"] = LEDGER_SCHEMA
    payload["schema_version"] = SCHEMA_VERSION
    payload["safety"] = _safety_boundary()
    payload["provenance"] = _provenance(payload.get("provenance"))
    if forbidden_private_or_real_trade_hits(payload):
        raise PaperLedgerError(f"paper_ledger_save_failed: {p}: safety boundary violation")
    write_runtime_json_atomic(p, payload)


def runtime_temp_path(path: Path | str) -> Path:
    p = Path(path)
    nonce = f"{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}"
    return p.with_suffix(f"{p.suffix}.{nonce}.tmp") if p.suffix else p.with_name(f"{p.name}.{nonce}.tmp")


def write_runtime_json_atomic(path: Path | str, payload: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = runtime_temp_path(p)
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(p)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def apply_paper_execution(
    ledger: dict[str, Any],
    execution: dict[str, Any],
    *,
    fee_bps: float = DEFAULT_FEE_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    now_iso: str | None = None,
) -> dict[str, Any]:
    fee_bps = _non_negative(fee_bps, "fee_bps")
    slippage_bps = _non_negative(slippage_bps, "slippage_bps")
    updated = load_paper_ledger_from_object(ledger)
    now_text = now_iso or _now_iso()
    if forbidden_private_or_real_trade_hits(execution):
        execution_id = str(execution.get("paper_execution_id") or _execution_id(execution)).strip()
        updated["last_rejected_execution"] = {
            "reason": "paper_execution_safety_violation",
            "symbol": str(execution.get("symbol") or "").upper().strip(),
            "status": str(execution.get("status") or ""),
        }
        if execution_id:
            updated["ignored_execution_ids"] = _dedupe([*(updated.get("ignored_execution_ids") or []), execution_id])
        updated["last_updated_at"] = now_text
        return _recalculate_equity(updated, now_iso=now_text)
    if execution.get("status") != "OPENED" or not execution.get("ok"):
        updated["last_rejected_execution"] = copy.deepcopy(execution)
        updated["last_updated_at"] = now_text
        return _recalculate_equity(updated, now_iso=now_text)

    execution_id = str(execution.get("paper_execution_id") or _execution_id(execution)).strip()
    if execution_id in set(updated.get("applied_execution_ids") or []):
        ignored = _dedupe([*(updated.get("ignored_execution_ids") or []), execution_id])
        updated["ignored_execution_ids"] = ignored
        updated["last_updated_at"] = now_text
        return _recalculate_equity(updated, now_iso=now_text)

    symbol = str(execution.get("symbol") or "").upper().strip()
    side = str(execution.get("side") or "").upper().strip()
    entry_price = _num(execution.get("entry_price")) or 0.0
    quantity = _num(execution.get("quantity")) or 0.0
    notional = _num(execution.get("notional_usdt")) or abs(entry_price * quantity)
    if not symbol or side not in {"LONG", "SHORT"} or entry_price <= 0 or quantity <= 0 or notional <= 0:
        updated["last_rejected_execution"] = {"reason": "invalid_open_execution", "execution": copy.deepcopy(execution)}
        updated["last_updated_at"] = now_text
        return _recalculate_equity(updated, now_iso=now_text)

    open_positions = updated.setdefault("open_positions", {})
    max_concurrent = _positive_int(execution.get("max_concurrent_positions_per_symbol"))
    allow_multiple = bool(
        execution.get("allow_multiple_open_positions_per_symbol") is True
        or (max_concurrent is not None and max_concurrent > 1)
    )
    same_symbol_count = _open_position_count_for_symbol(open_positions, symbol)
    if same_symbol_count and not allow_multiple:
        updated["last_rejected_execution"] = {
            "reason": "position_already_open_for_symbol",
            "symbol": symbol,
            "execution": copy.deepcopy(execution),
        }
        updated["ignored_execution_ids"] = _dedupe([*(updated.get("ignored_execution_ids") or []), execution_id])
        updated["last_updated_at"] = now_text
        return _recalculate_equity(updated, now_iso=now_text)
    if max_concurrent is not None and same_symbol_count >= max_concurrent:
        updated["last_rejected_execution"] = {
            "reason": "max_concurrent_positions_per_symbol_reached",
            "symbol": symbol,
            "current_open_positions_for_symbol": same_symbol_count,
            "max_concurrent_positions_per_symbol": max_concurrent,
            "execution": copy.deepcopy(execution),
        }
        updated["ignored_execution_ids"] = _dedupe([*(updated.get("ignored_execution_ids") or []), execution_id])
        updated["last_updated_at"] = now_text
        return _recalculate_equity(updated, now_iso=now_text)

    leverage = _num(execution.get("leverage"))
    requested_margin = _num(execution.get("requested_margin_usdt"))
    requested_notional = _num(execution.get("requested_notional_usdt"))
    if leverage is None or leverage <= 0 or (requested_margin is None and requested_notional is None):
        updated["last_rejected_execution"] = {
            "reason": "agent_sizing_required",
            "execution": copy.deepcopy(execution),
        }
        updated["ignored_execution_ids"] = _dedupe([*(updated.get("ignored_execution_ids") or []), execution_id])
        updated["last_updated_at"] = now_text
        return _recalculate_equity(updated, now_iso=now_text)

    effective_fee_bps = _execution_fee_bps(execution, fee_bps)
    fill_price = (
        entry_price
        if _entry_price_includes_slippage(execution)
        else _slipped_price(entry_price, side, "OPEN", slippage_bps)
    )
    fill_notional = abs(fill_price * quantity)
    fee = fill_notional * float(effective_fee_bps) / 10_000
    margin_usdt = fill_notional / leverage
    sizing_source = str(execution.get("sizing_source") or "").strip() or None
    research_cycle_run_id = str(execution.get("research_cycle_run_id") or "").strip() or None
    stop_loss_price = _num(execution.get("stop_loss_price"))
    take_profit_price = _num(execution.get("take_profit_price"))
    max_holding_minutes = _num(execution.get("max_holding_minutes"))
    has_exit_plan = any(value is not None for value in (stop_loss_price, take_profit_price, max_holding_minutes))
    exit_management = str(execution.get("exit_management") or ("agent_supplied" if has_exit_plan else "agent_managed"))
    exit_plan_source = str(
        execution.get("exit_plan_source") or ("execution_exit_fields" if has_exit_plan else "agent_required_missing")
    )
    position_id = _position_id(execution_id, symbol)
    position_key = position_id if allow_multiple else symbol
    position = {
        "position_id": position_id,
        "execution_id": execution_id,
        "symbol": symbol,
        "side": side,
        "status": "OPEN",
        "opened_at": str(execution.get("opened_at") or now_text),
        "entry_price": fill_price,
        "raw_entry_price": _num(execution.get("raw_entry_price")) or entry_price,
        "entry_fee_usdt": fee,
        "fee_bps": effective_fee_bps,
        "paper_fee_model": execution.get("paper_fee_model"),
        "liquidity_role": execution.get("liquidity_role"),
        "execution_cost_model": _execution_cost_model(execution),
        "quantity": quantity,
        "notional_usdt": fill_notional,
        "requested_notional_usdt": _num(execution.get("requested_notional_usdt")),
        "requested_margin_usdt": _num(execution.get("requested_margin_usdt")),
        "margin_usdt": margin_usdt,
        "leverage": leverage,
        "sizing_source": sizing_source,
        "research_cycle_run_id": research_cycle_run_id,
        "stop_loss_price": stop_loss_price,
        "take_profit_price": take_profit_price,
        "max_holding_minutes": max_holding_minutes,
        "exit_management": exit_management,
        "exit_plan_source": exit_plan_source,
        "exit_rationale": execution.get("exit_rationale"),
        "allow_multiple_open_positions_per_symbol": allow_multiple,
        "max_concurrent_positions_per_symbol": max_concurrent,
        "last_mark_price": fill_price,
        "unrealized_pnl_usdt": 0.0,
    }
    open_positions[position_key] = position
    updated.setdefault("paper_orders", []).append(
        {
            "schema": "tradecat_auto.paper_order.v1",
            "schema_version": "1.0.0",
            "order_id": execution_id,
            "execution_id": execution_id,
            "position_id": position_id,
            "symbol": symbol,
            "side": "BUY" if side == "LONG" else "SELL",
            "position_side": side,
            "order_type": "PAPER_TAKER_PUBLIC_DEPTH_ESTIMATE",
            "status": "FILLED",
            "requested_price": entry_price,
            "filled_price": fill_price,
            "quantity": quantity,
            "notional_usdt": fill_notional,
            "requested_notional_usdt": position.get("requested_notional_usdt"),
            "requested_margin_usdt": position.get("requested_margin_usdt"),
            "margin_usdt": position.get("margin_usdt"),
            "leverage": position.get("leverage"),
            "sizing_source": sizing_source,
            "research_cycle_run_id": research_cycle_run_id,
            "fee_usdt": fee,
            "fee_bps": effective_fee_bps,
            "paper_fee_model": execution.get("paper_fee_model"),
            "liquidity_role": execution.get("liquidity_role"),
            "execution_cost_model": _execution_cost_model(execution),
            "created_at": now_text,
            "filled_at": now_text,
            "real_order": False,
            "exchange_order_id": None,
            "source": "tradecat_paper_execution",
        }
    )
    updated.setdefault("fills", []).append(
        {
            "schema": "tradecat_auto.paper_fill.v1",
            "schema_version": SCHEMA_VERSION,
            "fill_id": _fill_id(execution_id, "OPEN"),
            "execution_id": execution_id,
            "position_id": position_id,
            "symbol": symbol,
            "side": "BUY" if side == "LONG" else "SELL",
            "action": "OPEN",
            "price": fill_price,
            "quantity": quantity,
            "notional_usdt": fill_notional,
            "requested_notional_usdt": position.get("requested_notional_usdt"),
            "requested_margin_usdt": position.get("requested_margin_usdt"),
            "margin_usdt": position.get("margin_usdt"),
            "leverage": position.get("leverage"),
            "sizing_source": sizing_source,
            "research_cycle_run_id": research_cycle_run_id,
            "fee_usdt": fee,
            "fee_bps": effective_fee_bps,
            "paper_fee_model": execution.get("paper_fee_model"),
            "liquidity_role": execution.get("liquidity_role"),
            "execution_cost_model": _execution_cost_model(execution),
            "created_at": now_text,
        }
    )
    updated["cash_balance_usdt"] = float(updated.get("cash_balance_usdt") or 0.0) - fee
    updated["applied_execution_ids"] = _dedupe([*(updated.get("applied_execution_ids") or []), execution_id])
    updated["last_updated_at"] = now_text
    return _recalculate_equity(updated, now_iso=now_text)


def load_paper_ledger_from_object(value: dict[str, Any]) -> dict[str, Any]:
    if forbidden_private_or_real_trade_hits(value):
        raise PaperLedgerError("paper_ledger_load_failed: in-memory safety boundary violation")
    ledger = default_paper_ledger(
        initial_balance_usdt=float(value.get("initial_balance_usdt") or DEFAULT_INITIAL_BALANCE_USDT)
    )
    ledger.update(copy.deepcopy(value))
    return _normalize_ledger_shape(ledger)


def mark_to_market(
    ledger: dict[str, Any],
    prices: dict[str, float],
    *,
    fee_bps: float = DEFAULT_FEE_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    now_iso: str | None = None,
    max_holding_minutes: float | None = None,
) -> dict[str, Any]:
    fee_bps = _non_negative(fee_bps, "fee_bps")
    slippage_bps = _non_negative(slippage_bps, "slippage_bps")
    updated = load_paper_ledger_from_object(ledger)
    now_text = now_iso or _now_iso()
    for position_key, position in list((updated.get("open_positions") or {}).items()):
        symbol = _position_symbol(position, fallback=position_key)
        mark_price = _num(prices.get(symbol))
        if mark_price is None or mark_price <= 0:
            continue
        position["last_mark_price"] = mark_price
        position["unrealized_pnl_usdt"] = _position_pnl(position, mark_price)
        close_reason = _close_reason(position, mark_price, now_iso=now_text, max_holding_minutes=max_holding_minutes)
        if close_reason:
            _close_position(
                updated,
                position_key,
                mark_price,
                close_reason,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                now_iso=now_text,
            )
    updated["last_updated_at"] = now_text
    return _recalculate_equity(updated, now_iso=now_text)


def apply_position_management_thesis(
    ledger: dict[str, Any],
    thesis: dict[str, Any],
    *,
    fee_bps: float = DEFAULT_FEE_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    now_iso: str | None = None,
) -> dict[str, Any]:
    """Apply an explicit Agent position-management thesis to the local paper ledger.

    The function returns a machine-readable action report and keeps the updated
    ledger in the private ``_ledger`` field for callers that are allowed to save
    local paper runtime state. It never talks to Binance and never creates real
    orders.
    """

    fee_bps = _non_negative(fee_bps, "fee_bps")
    slippage_bps = _non_negative(slippage_bps, "slippage_bps")
    updated = load_paper_ledger_from_object(ledger)
    now_text = now_iso or _now_iso()
    payload = thesis if isinstance(thesis, dict) else {}
    action = str(payload.get("action") or "").strip().lower()
    if action == "":
        action = "hold"
    mode = str(payload.get("mode") or "paper").strip().lower()
    reason = str(payload.get("reason") or "").strip()
    action_id = _position_management_action_id(payload)
    base = {
        "schema": POSITION_MANAGEMENT_ACTION_REPORT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "mode": mode if mode in {"paper", "watch"} else "paper",
        "action": action if action in {"hold", "noop", "close", "adjust_exit", "add", "reduce"} else "hold",
        "status": "REJECTED",
        "error_code": "position_management_rejected",
        "reason": reason,
        "symbol": _position_management_symbol(payload),
        "position_id": "",
        "position_ref": payload.get("position_ref") if isinstance(payload.get("position_ref"), dict) else {},
        "ledger_mutated": False,
        "action_id": action_id,
        "updated_fields": [],
        "provenance": _position_management_provenance(payload),
        "safety": _safety_boundary(),
        "_ledger": updated,
    }

    safety_error = _position_management_safety_error(payload)
    if safety_error:
        return {**base, "error_code": safety_error, "reason": reason or safety_error}
    if mode not in {"paper", "watch"}:
        return {
            **base,
            "error_code": "position_management_mode_rejected",
            "reason": reason or "mode must be paper or watch",
        }
    if action in {"hold", "noop"}:
        return {
            **base,
            "ok": True,
            "status": "HELD" if action == "hold" else "NOOP",
            "error_code": None,
            "reason": reason or "no explicit paper position change requested",
        }
    if action not in {"close", "adjust_exit", "add", "reduce"}:
        return {
            **base,
            "error_code": "position_management_action_unknown",
            "reason": reason or "unknown position management action",
        }
    if not reason:
        return {**base, "error_code": "position_management_reason_required", "reason": "Agent reason is required"}
    if action in {"add", "reduce"}:
        return {
            **base,
            "status": "UNSUPPORTED",
            "error_code": "position_management_action_not_supported",
            "reason": "add/reduce requires a future paper execution or partial-fill contract; no ledger mutation was applied",
        }

    position_match = _find_open_position(updated.get("open_positions") or {}, payload.get("position_ref"))
    if position_match.get("error_code"):
        return {**base, "error_code": position_match["error_code"], "reason": position_match["reason"]}
    position_key = str(position_match["position_key"])
    position = position_match["position"]
    position_id = str(position.get("position_id") or position_key)
    symbol = _position_symbol(position, fallback=position_key)

    if action == "adjust_exit":
        exit_update = payload.get("exit_update") if isinstance(payload.get("exit_update"), dict) else {}
        updated_fields = _apply_exit_update(position, exit_update, now_text, reason, base["provenance"])
        if not updated_fields:
            return {
                **base,
                "symbol": symbol,
                "position_id": position_id,
                "error_code": "position_exit_update_required",
                "reason": "Agent exit_update must contain stop_loss_price, take_profit_price, or max_holding_minutes",
            }
        open_positions = updated.setdefault("open_positions", {})
        open_positions[position_key] = position
        report = {
            **base,
            "ok": True,
            "status": "APPLIED",
            "error_code": None,
            "symbol": symbol,
            "position_id": position_id,
            "ledger_mutated": True,
            "updated_fields": updated_fields,
        }
        _record_position_management_action(updated, report, now_text)
        return {**report, "_ledger": _recalculate_equity(updated, now_iso=now_text)}

    close_intent = payload.get("close_intent") if isinstance(payload.get("close_intent"), dict) else {}
    close_fraction = _num(close_intent.get("close_fraction"))
    if close_fraction != 1:
        return {
            **base,
            "symbol": symbol,
            "position_id": position_id,
            "error_code": "full_close_fraction_required",
            "reason": "close action currently requires close_fraction=1; partial reduce stays fail-closed",
        }
    mark_price = _num(close_intent.get("mark_price"))
    if mark_price is None or mark_price <= 0:
        return {
            **base,
            "symbol": symbol,
            "position_id": position_id,
            "error_code": "agent_mark_price_required",
            "reason": "close action requires an explicit positive Agent mark_price",
        }
    _close_position(
        updated,
        position_key,
        mark_price,
        "agent_position_management_close",
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        now_iso=now_text,
    )
    _annotate_last_position_management_close(updated, action_id, reason, base["provenance"])
    report = {
        **base,
        "ok": True,
        "status": "APPLIED",
        "error_code": None,
        "symbol": symbol,
        "position_id": position_id,
        "ledger_mutated": True,
        "updated_fields": ["status", "closed_at", "exit_price", "close_reason", "fills"],
    }
    _record_position_management_action(updated, report, now_text)
    return {**report, "_ledger": _recalculate_equity(updated, now_iso=now_text)}


def paper_ledger_summary(ledger: dict[str, Any]) -> dict[str, Any]:
    normalized = _recalculate_equity(load_paper_ledger_from_object(ledger))
    return {
        "schema": "tradecat_auto.paper_ledger_summary.v1",
        "schema_version": "1.0.0",
        "cash_balance_usdt": normalized.get("cash_balance_usdt"),
        "equity_usdt": normalized.get("equity_usdt"),
        "realized_pnl_usdt": normalized.get("realized_pnl_usdt"),
        "unrealized_pnl_usdt": normalized.get("unrealized_pnl_usdt"),
        "open_positions_count": len(normalized.get("open_positions") or {}),
        "closed_positions_count": len(normalized.get("closed_positions") or []),
        "paper_orders_count": len(normalized.get("paper_orders") or []),
        "fills_count": len(normalized.get("fills") or []),
        "last_updated_at": normalized.get("last_updated_at"),
    }


def paper_account_state(ledger: dict[str, Any], *, open_positions_limit: int | None = None) -> dict[str, Any]:
    """Return prompt-safe paper account state derived only from the local ledger."""

    normalized = _recalculate_equity(load_paper_ledger_from_object(ledger))
    open_positions = list((normalized.get("open_positions") or {}).values())
    if open_positions_limit is not None and open_positions_limit > 0:
        open_positions = open_positions[-open_positions_limit:]
    return {
        "schema": PAPER_ACCOUNT_STATE_SCHEMA,
        "schema_version": "1.0.0",
        "mode": "paper",
        "source": "local_tradecat_paper_ledger",
        "provenance": {
            "source": "local_tradecat_paper_ledger",
            "ledger_schema": str(normalized.get("schema") or LEDGER_SCHEMA),
        },
        "safety": _safety_boundary(),
        "cash_balance_usdt": normalized.get("cash_balance_usdt"),
        "equity_usdt": normalized.get("equity_usdt"),
        "initial_balance_usdt": normalized.get("initial_balance_usdt"),
        "realized_pnl_usdt": normalized.get("realized_pnl_usdt"),
        "unrealized_pnl_usdt": normalized.get("unrealized_pnl_usdt"),
        "open_positions": open_positions,
        "recent_paper_orders": list(normalized.get("paper_orders") or [])[-20:],
        "recent_fills": list(normalized.get("fills") or [])[-20:],
        "closed_positions_count": len(normalized.get("closed_positions") or []),
        "last_updated_at": normalized.get("last_updated_at"),
        "hard_boundaries": paper_watch_hard_boundaries(),
        "limitations": [
            "derived from local paper ledger only",
            "not Binance account, balance, position, order, or fill state",
            "paper/watch research only; no real exchange order was placed",
        ],
    }


def _close_position(
    ledger: dict[str, Any],
    position_key: str,
    mark_price: float,
    close_reason: str,
    *,
    fee_bps: float,
    slippage_bps: float,
    now_iso: str,
) -> None:
    position = dict((ledger.get("open_positions") or {}).pop(position_key))
    symbol = _position_symbol(position, fallback=position_key)
    side = str(position.get("side") or "").upper()
    quantity = _num(position.get("quantity")) or 0.0
    exit_price = _slipped_price(mark_price, side, "CLOSE", slippage_bps)
    gross_pnl = _position_pnl(position, exit_price)
    exit_notional = abs(exit_price * quantity)
    entry_fee = _num(position.get("entry_fee_usdt"))
    if entry_fee is None:
        entry_fee = abs((_num(position.get("notional_usdt")) or 0.0) * float(fee_bps) / 10_000)
    effective_fee_bps = _position_fee_bps(position, fee_bps)
    fee = exit_notional * float(effective_fee_bps) / 10_000
    net_pnl = gross_pnl - entry_fee - fee
    close_cash_delta = gross_pnl - fee
    position.update(
        {
            "status": "CLOSED",
            "closed_at": now_iso,
            "exit_price": exit_price,
            "close_reason": close_reason,
            "entry_fee_usdt": entry_fee,
            "gross_pnl_usdt": gross_pnl,
            "exit_fee_usdt": fee,
            "fee_bps": effective_fee_bps,
            "net_pnl_usdt": net_pnl,
            "unrealized_pnl_usdt": 0.0,
        }
    )
    ledger.setdefault("closed_positions", []).append(position)
    ledger.setdefault("fills", []).append(
        {
            "schema": "tradecat_auto.paper_fill.v1",
            "schema_version": SCHEMA_VERSION,
            "fill_id": _fill_id(str(position.get("execution_id") or position.get("position_id")), "CLOSE"),
            "execution_id": position.get("execution_id"),
            "position_id": position.get("position_id"),
            "symbol": symbol,
            "side": "SELL" if side == "LONG" else "BUY",
            "action": "CLOSE",
            "price": exit_price,
            "quantity": quantity,
            "notional_usdt": exit_notional,
            "margin_usdt": position.get("margin_usdt"),
            "leverage": position.get("leverage"),
            "fee_usdt": fee,
            "fee_bps": effective_fee_bps,
            "paper_fee_model": position.get("paper_fee_model"),
            "liquidity_role": position.get("liquidity_role"),
            "gross_pnl_usdt": gross_pnl,
            "net_pnl_usdt": net_pnl,
            "close_reason": close_reason,
            "created_at": now_iso,
        }
    )
    ledger["cash_balance_usdt"] = float(ledger.get("cash_balance_usdt") or 0.0) + close_cash_delta
    ledger["realized_pnl_usdt"] = float(ledger.get("realized_pnl_usdt") or 0.0) + net_pnl


def _recalculate_equity(ledger: dict[str, Any], *, now_iso: str | None = None) -> dict[str, Any]:
    unrealized = 0.0
    for position in (ledger.get("open_positions") or {}).values():
        if not isinstance(position, dict):
            continue
        mark = _num(position.get("last_mark_price")) or _num(position.get("entry_price")) or 0.0
        pnl = _position_pnl(position, mark)
        position["unrealized_pnl_usdt"] = pnl
        unrealized += pnl
    ledger["unrealized_pnl_usdt"] = unrealized
    ledger["equity_usdt"] = float(ledger.get("cash_balance_usdt") or 0.0) + unrealized
    if now_iso:
        ledger.setdefault("equity_curve", []).append(
            {
                "time": now_iso,
                "equity_usdt": ledger["equity_usdt"],
                "cash_balance_usdt": ledger.get("cash_balance_usdt"),
                "realized_pnl_usdt": ledger.get("realized_pnl_usdt"),
                "unrealized_pnl_usdt": unrealized,
                "open_positions_count": len(ledger.get("open_positions") or {}),
            }
        )
    return ledger


def _position_pnl(position: dict[str, Any], price: float) -> float:
    entry = _num(position.get("entry_price")) or 0.0
    quantity = _num(position.get("quantity")) or 0.0
    side = str(position.get("side") or "").upper()
    if side == "LONG":
        return (price - entry) * quantity
    if side == "SHORT":
        return (entry - price) * quantity
    return 0.0


def _close_reason(
    position: dict[str, Any],
    mark_price: float,
    *,
    now_iso: str | None = None,
    max_holding_minutes: float | None = None,
) -> str | None:
    side = str(position.get("side") or "").upper()
    stop_loss = _num(position.get("stop_loss_price"))
    take_profit = _num(position.get("take_profit_price"))
    if side == "LONG":
        if stop_loss is not None and mark_price <= stop_loss:
            return "stop_loss"
        if take_profit is not None and mark_price >= take_profit:
            return "take_profit"
    if side == "SHORT":
        if stop_loss is not None and mark_price >= stop_loss:
            return "stop_loss"
        if take_profit is not None and mark_price <= take_profit:
            return "take_profit"
    # Time stops are strategy/Agent intent, not a wrapper-level fixed default.
    # Keep the function parameter for backward-compatible callers, but only a
    # position-level max_holding_minutes persisted from strategy_intent can close.
    effective_max_holding = _num(position.get("max_holding_minutes"))
    if (
        effective_max_holding is not None
        and effective_max_holding > 0
        and _holding_minutes(position, now_iso) >= effective_max_holding
    ):
        return "time_stop"
    return None


def _holding_minutes(position: dict[str, Any], now_iso: str | None) -> float:
    opened_at = _parse_iso_datetime(str(position.get("opened_at") or ""))
    now = _parse_iso_datetime(str(now_iso or ""))
    if opened_at is None or now is None:
        return 0.0
    return max(0.0, (now - opened_at).total_seconds() / 60.0)


def _parse_iso_datetime(text: str) -> datetime | None:
    value = str(text or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _slipped_price(price: float, side: str, action: str, slippage_bps: float) -> float:
    slip = float(slippage_bps or 0.0) / 10_000
    if slip <= 0:
        return price
    side = side.upper()
    action = action.upper()
    buying = (action == "OPEN" and side == "LONG") or (action == "CLOSE" and side == "SHORT")
    return price * (1 + slip if buying else 1 - slip)


def _execution_cost_model(execution: dict[str, Any]) -> dict[str, Any]:
    model = execution.get("execution_cost_model")
    return copy.deepcopy(model) if isinstance(model, dict) else {}


def _entry_price_includes_slippage(execution: dict[str, Any]) -> bool:
    model = execution.get("execution_cost_model")
    return bool(
        execution.get("entry_price_includes_slippage")
        or (isinstance(model, dict) and model.get("fill_price_includes_slippage"))
    )


def _execution_fee_bps(execution: dict[str, Any], default_fee_bps: float) -> float:
    model = execution.get("execution_cost_model")
    if isinstance(model, dict):
        parsed = _num(model.get("fee_bps"))
        if parsed is not None and parsed >= 0:
            return parsed
    parsed = _num(execution.get("paper_fee_bps"))
    if parsed is not None and parsed >= 0:
        return parsed
    return float(default_fee_bps)


def _position_fee_bps(position: dict[str, Any], default_fee_bps: float) -> float:
    parsed = _num(position.get("fee_bps"))
    if parsed is not None and parsed >= 0:
        return parsed
    return float(default_fee_bps)


def _execution_id(execution: dict[str, Any]) -> str:
    material = json.dumps(
        {
            "symbol": execution.get("symbol"),
            "side": execution.get("side"),
            "opened_at": execution.get("opened_at"),
            "entry_price": execution.get("entry_price"),
            "quantity": execution.get("quantity"),
            "notional_usdt": execution.get("notional_usdt"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _position_id(execution_id: str, symbol: str) -> str:
    return hashlib.sha256(f"{execution_id}\n{symbol}".encode()).hexdigest()[:24]


def _fill_id(execution_id: str, action: str) -> str:
    return hashlib.sha256(f"{execution_id}\n{action}".encode()).hexdigest()[:24]


def _position_symbol(position: Any, *, fallback: Any = "") -> str:
    if isinstance(position, dict):
        symbol = str(position.get("symbol") or "").upper().strip()
        if symbol:
            return symbol
    return str(fallback or "").upper().strip()


def _open_position_count_for_symbol(open_positions: dict[str, Any], symbol: str) -> int:
    normalized = str(symbol or "").upper().strip()
    return sum(1 for key, position in open_positions.items() if _position_symbol(position, fallback=key) == normalized)


def _find_open_position(open_positions: dict[str, Any], position_ref: Any) -> dict[str, Any]:
    ref = position_ref if isinstance(position_ref, dict) else {}
    if not ref:
        return {"error_code": "position_ref_required", "reason": "position_ref is required for this action"}
    wanted_position_id = str(ref.get("position_id") or "").strip()
    wanted_execution_id = str(ref.get("execution_id") or "").strip()
    wanted_symbol = str(ref.get("symbol") or "").upper().strip()
    matches: list[tuple[str, dict[str, Any]]] = []
    for key, raw_position in open_positions.items():
        if not isinstance(raw_position, dict):
            continue
        position = raw_position
        symbol = _position_symbol(position, fallback=key)
        if wanted_position_id or wanted_execution_id:
            if wanted_position_id and str(position.get("position_id") or "") == wanted_position_id:
                matches.append((str(key), position))
            elif wanted_execution_id and str(position.get("execution_id") or "") == wanted_execution_id:
                matches.append((str(key), position))
            continue
        if wanted_symbol and symbol == wanted_symbol:
            matches.append((str(key), position))
    if not matches:
        return {"error_code": "position_not_found", "reason": "no matching open paper position found"}
    unique = {(key, str(position.get("position_id") or "")): (key, position) for key, position in matches}
    if len(unique) > 1 and not (wanted_position_id or wanted_execution_id):
        return {
            "error_code": "position_ref_ambiguous",
            "reason": "symbol-only position_ref matched multiple open paper positions",
        }
    position_key, position = next(iter(unique.values()))
    return {"position_key": position_key, "position": dict(position)}


def _apply_exit_update(
    position: dict[str, Any],
    exit_update: dict[str, Any],
    now_iso: str,
    reason: str,
    provenance: dict[str, Any],
) -> list[str]:
    updated_fields: list[str] = []
    for source_key, target_key in (
        ("stop_loss_price", "stop_loss_price"),
        ("take_profit_price", "take_profit_price"),
        ("max_holding_minutes", "max_holding_minutes"),
    ):
        if source_key not in exit_update:
            continue
        value = _num(exit_update.get(source_key))
        if value is None or value <= 0:
            continue
        position[target_key] = value
        updated_fields.append(target_key)
    if not updated_fields:
        return []
    if isinstance(exit_update.get("exit_rationale"), str) and exit_update.get("exit_rationale"):
        position["exit_rationale"] = str(exit_update["exit_rationale"])
        updated_fields.append("exit_rationale")
    position["exit_management"] = "agent_supplied"
    position["exit_plan_source"] = "position_management_thesis"
    position["position_management_updated_at"] = now_iso
    position["position_management_reason"] = reason
    position["position_management_provenance"] = provenance
    updated_fields.extend(["exit_management", "exit_plan_source"])
    return _dedupe(updated_fields)


def _record_position_management_action(ledger: dict[str, Any], report: dict[str, Any], now_iso: str) -> None:
    clean = {key: value for key, value in report.items() if key != "_ledger"}
    clean["created_at"] = now_iso
    ledger.setdefault("position_management_actions", []).append(clean)
    ledger["last_position_management_action"] = clean
    ledger["last_updated_at"] = now_iso


def _annotate_last_position_management_close(
    ledger: dict[str, Any],
    action_id: str,
    reason: str,
    provenance: dict[str, Any],
) -> None:
    for position in reversed(ledger.get("closed_positions") or []):
        if isinstance(position, dict):
            position["position_management_action_id"] = action_id
            position["position_management_reason"] = reason
            position["position_management_provenance"] = provenance
            break
    for fill in reversed(ledger.get("fills") or []):
        if isinstance(fill, dict) and fill.get("action") == "CLOSE":
            fill["position_management_action_id"] = action_id
            fill["position_management_reason"] = reason
            research_cycle_run_id = str(provenance.get("research_cycle_run_id") or "").strip()
            if research_cycle_run_id:
                fill["research_cycle_run_id"] = research_cycle_run_id
            break


def _position_management_safety_error(value: Any) -> str | None:
    if not isinstance(value, dict):
        return "position_management_thesis_required"
    if value.get("schema") not in (None, "", "tradecat_auto.position_management_thesis.v1"):
        return "position_management_schema_rejected"
    if value.get("schema_version") not in (None, "", SCHEMA_VERSION):
        return "position_management_schema_version_rejected"
    if forbidden_private_or_real_trade_hits(value):
        return "position_management_safety_violation"
    return None


def _position_management_symbol(value: dict[str, Any]) -> str:
    symbol = str(value.get("symbol") or "").upper().strip()
    if symbol:
        return symbol
    ref = value.get("position_ref")
    if isinstance(ref, dict):
        return str(ref.get("symbol") or "").upper().strip()
    return ""


def _position_management_provenance(value: dict[str, Any]) -> dict[str, Any]:
    provenance = value.get("provenance") if isinstance(value.get("provenance"), dict) else {}
    result = dict(provenance)
    result.setdefault("source", "tradecat_auto.paper_ledger.apply_position_management_thesis")
    return result


def _position_management_action_id(value: dict[str, Any]) -> str:
    material = json.dumps(value if isinstance(value, dict) else {}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _positive_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        numeric = int(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric > 0 else None


def _dedupe(values: Any) -> list[str]:
    return list(dict.fromkeys(str(item) for item in values if str(item)))


def _normalize_ledger_shape(ledger: dict[str, Any]) -> dict[str, Any]:
    ledger["schema"] = LEDGER_SCHEMA
    ledger["schema_version"] = SCHEMA_VERSION
    ledger["safety"] = _safety_boundary()
    ledger["provenance"] = _provenance(ledger.get("provenance"))
    ledger["open_positions"] = dict(ledger.get("open_positions") or {})
    ledger["closed_positions"] = list(ledger.get("closed_positions") or [])
    ledger["paper_orders"] = list(ledger.get("paper_orders") or [])
    ledger["fills"] = list(ledger.get("fills") or [])
    ledger["applied_execution_ids"] = _dedupe(ledger.get("applied_execution_ids") or [])
    ledger["ignored_execution_ids"] = _dedupe(ledger.get("ignored_execution_ids") or [])
    ledger["equity_curve"] = list(ledger.get("equity_curve") or [])
    return ledger


def _validate_loaded_payload(data: dict[str, Any], path: Path) -> None:
    if data.get("schema") != LEDGER_SCHEMA:
        raise PaperLedgerError(f"paper_ledger_load_failed: {path}: schema is not {LEDGER_SCHEMA}")
    if forbidden_private_or_real_trade_hits(data):
        raise PaperLedgerError(f"paper_ledger_load_failed: {path}: safety boundary violation")
    numeric_fields = (
        "cash_balance_usdt",
        "equity_usdt",
        "initial_balance_usdt",
        "realized_pnl_usdt",
        "unrealized_pnl_usdt",
    )
    for key in numeric_fields:
        if key not in data or _num(data.get(key)) is None:
            raise PaperLedgerError(f"paper_ledger_load_failed: {path}: {key} is missing or non-numeric")
    typed_fields: tuple[tuple[str, type], ...] = (
        ("open_positions", dict),
        ("closed_positions", list),
        ("fills", list),
        ("applied_execution_ids", list),
        ("ignored_execution_ids", list),
        ("equity_curve", list),
    )
    for key, expected_type in typed_fields:
        if not isinstance(data.get(key), expected_type):
            raise PaperLedgerError(f"paper_ledger_load_failed: {path}: {key} has invalid type")
    if "paper_orders" in data and not isinstance(data.get("paper_orders"), list):
        raise PaperLedgerError(f"paper_ledger_load_failed: {path}: paper_orders has invalid type")
    for symbol, position in data.get("open_positions", {}).items():
        if not str(symbol).strip() or not isinstance(position, dict):
            raise PaperLedgerError(f"paper_ledger_load_failed: {path}: open_positions has invalid entry")


def _non_negative(value: Any, name: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a non-negative number") from exc
    if numeric < 0:
        raise ValueError(f"{name} must be non-negative")
    return numeric


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safety_boundary() -> dict[str, bool]:
    return paper_watch_safety_boundary()


def _provenance(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {"source": "local_tradecat_paper_ledger"}
