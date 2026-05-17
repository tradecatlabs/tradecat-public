from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LEDGER_SCHEMA = "tradecat_auto.paper_ledger.v1"
PAPER_ACCOUNT_STATE_SCHEMA = "tradecat_auto.paper_account_state.v1"
DEFAULT_INITIAL_BALANCE_USDT = 1000.0
DEFAULT_FEE_BPS = 2.0
DEFAULT_SLIPPAGE_BPS = 0.0


class PaperLedgerError(ValueError):
    """Raised when an existing paper ledger cannot be trusted."""


def default_paper_ledger(*, initial_balance_usdt: float = DEFAULT_INITIAL_BALANCE_USDT) -> dict[str, Any]:
    balance = _non_negative(initial_balance_usdt, "initial_balance_usdt")
    return {
        "schema": LEDGER_SCHEMA,
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
    }


def load_paper_ledger(path: Path | str, *, initial_balance_usdt: float = DEFAULT_INITIAL_BALANCE_USDT) -> dict[str, Any]:
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
    ledger["schema"] = LEDGER_SCHEMA
    ledger["open_positions"] = dict(ledger.get("open_positions") or {})
    ledger["closed_positions"] = list(ledger.get("closed_positions") or [])
    ledger["paper_orders"] = list(ledger.get("paper_orders") or [])
    ledger["fills"] = list(ledger.get("fills") or [])
    ledger["applied_execution_ids"] = _dedupe(ledger.get("applied_execution_ids") or [])
    ledger["ignored_execution_ids"] = _dedupe(ledger.get("ignored_execution_ids") or [])
    ledger["equity_curve"] = list(ledger.get("equity_curve") or [])
    return _recalculate_equity(ledger)


def save_paper_ledger(path: Path | str, ledger: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = _recalculate_equity(dict(ledger))
    payload["schema"] = LEDGER_SCHEMA
    tmp = p.with_suffix(f"{p.suffix}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


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
    if symbol in open_positions:
        updated["last_rejected_execution"] = {
            "reason": "position_already_open_for_symbol",
            "symbol": symbol,
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

    fill_price = _slipped_price(entry_price, side, "OPEN", slippage_bps)
    fill_notional = abs(fill_price * quantity)
    fee = fill_notional * float(fee_bps) / 10_000
    margin_usdt = fill_notional / leverage
    sizing_source = str(execution.get("sizing_source") or "").strip() or None
    stop_loss_price = _num(execution.get("stop_loss_price"))
    take_profit_price = _num(execution.get("take_profit_price"))
    max_holding_minutes = _num(execution.get("max_holding_minutes"))
    has_exit_plan = any(value is not None for value in (stop_loss_price, take_profit_price, max_holding_minutes))
    exit_management = str(execution.get("exit_management") or ("agent_supplied" if has_exit_plan else "agent_managed"))
    exit_plan_source = str(execution.get("exit_plan_source") or ("execution_exit_fields" if has_exit_plan else "agent_required_missing"))
    position_id = _position_id(execution_id, symbol)
    position = {
        "position_id": position_id,
        "execution_id": execution_id,
        "symbol": symbol,
        "side": side,
        "status": "OPEN",
        "opened_at": str(execution.get("opened_at") or now_text),
        "entry_price": fill_price,
        "raw_entry_price": entry_price,
        "entry_fee_usdt": fee,
        "quantity": quantity,
        "notional_usdt": fill_notional,
        "requested_notional_usdt": _num(execution.get("requested_notional_usdt")),
        "requested_margin_usdt": _num(execution.get("requested_margin_usdt")),
        "margin_usdt": margin_usdt,
        "leverage": leverage,
        "sizing_source": sizing_source,
        "stop_loss_price": stop_loss_price,
        "take_profit_price": take_profit_price,
        "max_holding_minutes": max_holding_minutes,
        "exit_management": exit_management,
        "exit_plan_source": exit_plan_source,
        "exit_rationale": execution.get("exit_rationale"),
        "last_mark_price": fill_price,
        "unrealized_pnl_usdt": 0.0,
    }
    open_positions[symbol] = position
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
            "order_type": "PAPER_POST_ONLY_MAKER_ASSUMPTION",
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
            "fee_usdt": fee,
            "created_at": now_text,
            "filled_at": now_text,
            "real_order": False,
            "exchange_order_id": None,
            "source": "tradecat_paper_execution",
        }
    )
    updated.setdefault("fills", []).append(
        {
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
            "fee_usdt": fee,
            "created_at": now_text,
        }
    )
    updated["cash_balance_usdt"] = float(updated.get("cash_balance_usdt") or 0.0) - fee
    updated["applied_execution_ids"] = _dedupe([*(updated.get("applied_execution_ids") or []), execution_id])
    updated["last_updated_at"] = now_text
    return _recalculate_equity(updated, now_iso=now_text)


def load_paper_ledger_from_object(value: dict[str, Any]) -> dict[str, Any]:
    ledger = default_paper_ledger(initial_balance_usdt=float(value.get("initial_balance_usdt") or DEFAULT_INITIAL_BALANCE_USDT))
    ledger.update(copy.deepcopy(value))
    ledger["schema"] = LEDGER_SCHEMA
    ledger["open_positions"] = dict(ledger.get("open_positions") or {})
    ledger["closed_positions"] = list(ledger.get("closed_positions") or [])
    ledger["paper_orders"] = list(ledger.get("paper_orders") or [])
    ledger["fills"] = list(ledger.get("fills") or [])
    ledger["applied_execution_ids"] = _dedupe(ledger.get("applied_execution_ids") or [])
    ledger["ignored_execution_ids"] = _dedupe(ledger.get("ignored_execution_ids") or [])
    ledger["equity_curve"] = list(ledger.get("equity_curve") or [])
    return ledger


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
    for symbol, position in list((updated.get("open_positions") or {}).items()):
        mark_price = _num(prices.get(symbol))
        if mark_price is None or mark_price <= 0:
            continue
        position["last_mark_price"] = mark_price
        position["unrealized_pnl_usdt"] = _position_pnl(position, mark_price)
        close_reason = _close_reason(position, mark_price, now_iso=now_text, max_holding_minutes=max_holding_minutes)
        if close_reason:
            _close_position(updated, symbol, mark_price, close_reason, fee_bps=fee_bps, slippage_bps=slippage_bps, now_iso=now_text)
    updated["last_updated_at"] = now_text
    return _recalculate_equity(updated, now_iso=now_text)


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


def paper_account_state(ledger: dict[str, Any]) -> dict[str, Any]:
    """Return prompt-safe paper account state derived only from the local ledger."""

    normalized = _recalculate_equity(load_paper_ledger_from_object(ledger))
    return {
        "schema": PAPER_ACCOUNT_STATE_SCHEMA,
        "schema_version": "1.0.0",
        "mode": "paper",
        "source": "local_tradecat_paper_ledger",
        "cash_balance_usdt": normalized.get("cash_balance_usdt"),
        "equity_usdt": normalized.get("equity_usdt"),
        "initial_balance_usdt": normalized.get("initial_balance_usdt"),
        "realized_pnl_usdt": normalized.get("realized_pnl_usdt"),
        "unrealized_pnl_usdt": normalized.get("unrealized_pnl_usdt"),
        "open_positions": list((normalized.get("open_positions") or {}).values()),
        "recent_paper_orders": list(normalized.get("paper_orders") or [])[-20:],
        "recent_fills": list(normalized.get("fills") or [])[-20:],
        "closed_positions_count": len(normalized.get("closed_positions") or []),
        "last_updated_at": normalized.get("last_updated_at"),
        "hard_boundaries": {
            "real_orders": False,
            "signed_requests": False,
            "reads_api_keys": False,
            "binance_account_state": False,
        },
        "limitations": [
            "derived from local paper ledger only",
            "not Binance account, balance, position, order, or fill state",
            "paper/watch research only; no real exchange order was placed",
        ],
    }


def _close_position(
    ledger: dict[str, Any],
    symbol: str,
    mark_price: float,
    close_reason: str,
    *,
    fee_bps: float,
    slippage_bps: float,
    now_iso: str,
) -> None:
    position = dict((ledger.get("open_positions") or {}).pop(symbol))
    side = str(position.get("side") or "").upper()
    quantity = _num(position.get("quantity")) or 0.0
    exit_price = _slipped_price(mark_price, side, "CLOSE", slippage_bps)
    gross_pnl = _position_pnl(position, exit_price)
    exit_notional = abs(exit_price * quantity)
    entry_fee = _num(position.get("entry_fee_usdt"))
    if entry_fee is None:
        entry_fee = abs((_num(position.get("notional_usdt")) or 0.0) * float(fee_bps) / 10_000)
    fee = exit_notional * float(fee_bps) / 10_000
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
            "net_pnl_usdt": net_pnl,
            "unrealized_pnl_usdt": 0.0,
        }
    )
    ledger.setdefault("closed_positions", []).append(position)
    ledger.setdefault("fills", []).append(
        {
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
    if effective_max_holding is not None and effective_max_holding > 0 and _holding_minutes(position, now_iso) >= effective_max_holding:
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


def _dedupe(values: Any) -> list[str]:
    return list(dict.fromkeys(str(item) for item in values if str(item)))


def _validate_loaded_payload(data: dict[str, Any], path: Path) -> None:
    if data.get("schema") != LEDGER_SCHEMA:
        raise PaperLedgerError(f"paper_ledger_load_failed: {path}: schema is not {LEDGER_SCHEMA}")
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
