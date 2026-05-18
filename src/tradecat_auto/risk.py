from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def default_risk_policy(*, mode: str = "paper") -> dict[str, Any]:
    return {
        "schema": "tradecat_auto.risk_policy.v1",
        "schema_version": "1.0.0",
        "mode": mode,
        "allowed_market": "usds_m_futures",
        "allowed_quote_asset": "USDT",
        "allowed_contract_type": "PERPETUAL",
        "mainnet_enabled": False,
        "min_score": 0,
        "max_symbol_notional_usdt": None,
        "max_total_notional_usdt": None,
        "max_spread_bps": None,
        "max_leverage": None,
        "paper_margin_budget_usdt": None,
        "paper_leverage": None,
        "sizing_required": mode == "paper",
        "sizing_source": "agent_supplied_or_explicit",
        "max_open_positions": None,
        "current_open_positions": 0,
        "max_consecutive_losses": 0,
        "consecutive_losses": 0,
        "max_daily_loss_usdt": 0.0,
        "daily_realized_pnl_usdt": 0.0,
        "current_total_notional_usdt": 0.0,
        "requested_margin_usdt": None,
        "requested_notional_usdt": None,
        "force_reject_reasons": [],
        "kill_switch_file": "",
    }


def load_portfolio_risk_policy(path: Path | str | None) -> dict[str, Any] | None:
    text = str(path or "").strip()
    if not text:
        return None
    policy_path = Path(text)
    if not policy_path.exists():
        raise ValueError(f"portfolio_risk_policy_load_failed: missing file: {policy_path}")
    try:
        payload = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"portfolio_risk_policy_load_failed: {policy_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("portfolio_risk_policy_load_failed: policy root must be an object")
    if payload.get("schema") not in (None, "", "tradecat_auto.portfolio_risk_policy.v1"):
        raise ValueError("portfolio_risk_policy_load_failed: invalid schema")
    if payload.get("schema_version") not in (None, "", "1.0.0"):
        raise ValueError("portfolio_risk_policy_load_failed: invalid schema_version")
    for forbidden in (
        "requested_margin_usdt",
        "requested_notional_usdt",
        "paper_leverage",
        "stop_loss_price",
        "take_profit_price",
        "max_holding_minutes",
    ):
        if forbidden in payload:
            raise ValueError(f"portfolio_risk_policy_load_failed: forbidden trade parameter {forbidden}")
    return payload


def evaluate_risk(signal: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    active_policy = dict(default_risk_policy())
    if policy:
        active_policy.update(policy)
    portfolio_policy = _portfolio_policy(active_policy)
    if portfolio_policy:
        _apply_portfolio_policy(active_policy, portfolio_policy)
    mode = str(active_policy.get("mode") or "paper")
    reasons: list[str] = []
    constraints = ["paper_only", "no_real_orders", "no_api_keys", "deterministic_risk_gate"]

    if active_policy.get("portfolio_kill_switch_active") is True:
        reasons.append("portfolio_kill_switch_active")
    if active_policy.get("new_entries_enabled") is False:
        reasons.append("new_entries_disabled")
    if active_policy.get("cooldown_active") is True:
        reasons.append("cooldown_active")

    kill_switch_file = str(active_policy.get("kill_switch_file") or "").strip()
    if kill_switch_file and Path(kill_switch_file).exists():
        reasons.append("kill_switch_active")

    if mode == "mainnet":
        reasons.append("mainnet_execution_not_implemented")
    elif mode not in {"paper", "watch"}:
        reasons.append("unsupported_mode")

    if not signal.get("tradable_candidate") or signal.get("direction") not in {"LONG", "SHORT"}:
        reasons.append("signal_not_tradable")

    score = _num(signal.get("score")) or 0
    min_score = _num(active_policy.get("min_score"))
    if min_score is None:
        min_score = 0.0
    if min_score > 0 and score < min_score:
        reasons.append("score_below_policy_minimum")

    max_daily_loss = float(active_policy.get("max_daily_loss_usdt") or 0.0)
    daily_realized = _num(active_policy.get("daily_realized_pnl_usdt")) or 0.0
    if max_daily_loss > 0 and daily_realized <= -max_daily_loss:
        reasons.append("daily_loss_limit_reached")

    max_drawdown = _num(active_policy.get("max_drawdown_usdt")) or 0.0
    current_drawdown = _num(active_policy.get("current_drawdown_usdt")) or 0.0
    if max_drawdown > 0 and current_drawdown >= max_drawdown:
        reasons.append("drawdown_limit_reached")

    max_consecutive_losses = int(active_policy.get("max_consecutive_losses") or 0)
    consecutive_losses = int(active_policy.get("consecutive_losses") or 0)
    if max_consecutive_losses > 0 and consecutive_losses >= max_consecutive_losses:
        reasons.append("consecutive_loss_limit_reached")

    max_open_positions = int(active_policy.get("max_open_positions") or 0)
    current_open_positions = int(active_policy.get("current_open_positions") or 0)
    if max_open_positions > 0 and current_open_positions >= max_open_positions:
        reasons.append("max_open_positions_reached")

    max_positions_per_symbol = int(active_policy.get("max_positions_per_symbol") or 0)
    current_symbol_open_positions = int(active_policy.get("current_symbol_open_positions") or 0)
    if max_positions_per_symbol > 0 and current_symbol_open_positions >= max_positions_per_symbol:
        reasons.append("max_positions_per_symbol_reached")

    leverage_raw = _num(active_policy.get("paper_leverage"))
    leverage = leverage_raw if leverage_raw is not None else 0.0
    requested_margin = _num(active_policy.get("requested_margin_usdt"))
    margin_budget = _num(active_policy.get("paper_margin_budget_usdt"))
    if (
        margin_budget is not None
        and margin_budget > 0
        and requested_margin is not None
        and requested_margin > margin_budget
    ):
        reasons.append("margin_budget_exceeded")
    requested_notional_raw = _num(active_policy.get("requested_notional_usdt"))
    requested_notional = requested_notional_raw if requested_notional_raw is not None else 0.0
    sizing_required = bool(active_policy.get("sizing_required", mode == "paper"))
    if (
        mode == "paper"
        and sizing_required
        and (requested_notional_raw is None or requested_notional <= 0 or leverage_raw is None)
    ):
        reasons.append("agent_sizing_required")
    if leverage_raw is not None and leverage <= 0:
        reasons.append("invalid_leverage")
    max_leverage = _num(active_policy.get("max_leverage"))
    if leverage > 0 and max_leverage is not None and max_leverage > 0 and leverage > max_leverage:
        reasons.append("max_leverage_exceeded")

    min_agent_confidence = _num(active_policy.get("min_agent_confidence"))
    agent_confidence = _num(active_policy.get("agent_confidence"))
    if min_agent_confidence is not None and min_agent_confidence > 0:
        if agent_confidence is None:
            reasons.append("agent_confidence_required")
        elif agent_confidence < min_agent_confidence:
            reasons.append("agent_confidence_below_minimum")

    abnormal_move_halt = _num(active_policy.get("abnormal_move_halt_bps")) or 0.0
    current_move_bps = abs(_num(active_policy.get("current_abnormal_move_bps")) or 0.0)
    if abnormal_move_halt > 0 and current_move_bps >= abnormal_move_halt:
        reasons.append("abnormal_move_halt_active")

    max_symbol_notional = _num(active_policy.get("max_symbol_notional_usdt")) or 0.0
    if max_symbol_notional > 0 and requested_notional > 0 and requested_notional > max_symbol_notional:
        reasons.append("max_symbol_notional_reached")

    max_symbol_risk = _num(active_policy.get("max_symbol_risk_usdt")) or 0.0
    requested_symbol_risk = _num(active_policy.get("requested_symbol_risk_usdt"))
    if max_symbol_risk > 0:
        if requested_symbol_risk is None:
            reasons.append("agent_symbol_risk_required")
        elif requested_symbol_risk > max_symbol_risk:
            reasons.append("max_symbol_risk_reached")

    max_symbol_risk_pct = _num(active_policy.get("max_symbol_risk_pct")) or 0.0
    account_equity = _num(active_policy.get("account_equity_usdt")) or 0.0
    if max_symbol_risk_pct > 0:
        if requested_symbol_risk is None or account_equity <= 0:
            reasons.append("agent_symbol_risk_pct_required")
        elif requested_symbol_risk / account_equity > max_symbol_risk_pct:
            reasons.append("max_symbol_risk_pct_reached")

    max_total_notional = _num(active_policy.get("max_total_notional_usdt")) or 0.0
    current_total_notional = _num(active_policy.get("current_total_notional_usdt")) or 0.0
    if (
        max_total_notional > 0
        and requested_notional > 0
        and current_total_notional + requested_notional > max_total_notional
    ):
        reasons.append("max_total_notional_reached")

    forced_reject_reasons = _as_reason_list(active_policy.get("force_reject_reasons"))
    reasons.extend(forced_reject_reasons)

    signal_reasons = signal.get("do_not_trade_reasons") if isinstance(signal.get("do_not_trade_reasons"), list) else []
    if signal_reasons:
        reasons.extend(str(item) for item in signal_reasons)

    reasons = _dedupe(reasons)
    always_reject = {
        "kill_switch_active",
        "portfolio_kill_switch_active",
        "new_entries_disabled",
        "cooldown_active",
        "abnormal_move_halt_active",
        "mainnet_execution_not_implemented",
        "unsupported_mode",
        *forced_reject_reasons,
    }
    if any(reason in always_reject for reason in reasons):
        decision = "REJECT"
    elif "signal_not_tradable" in reasons:
        decision = "WATCH_ONLY"
    elif "agent_sizing_required" in reasons and mode == "paper":
        decision = "REJECT"
    elif reasons:
        decision = "REJECT"
    else:
        decision = "ALLOW"

    return {
        "schema": "tradecat_auto.risk_decision.v1",
        "schema_version": "1.0.0",
        "ok": True,
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "decision": decision,
        "mode": mode,
        "symbol": str(signal.get("symbol") or ""),
        "direction": signal.get("direction", "WATCH_ONLY"),
        "score": score,
        "paper_leverage": leverage_raw,
        "max_notional_usdt": _positive_cap(active_policy.get("max_symbol_notional_usdt")),
        "constraints": constraints,
        "reasons": reasons,
        "policy": {
            "min_score": active_policy.get("min_score"),
            "max_symbol_notional_usdt": active_policy.get("max_symbol_notional_usdt"),
            "max_leverage": active_policy.get("max_leverage"),
            "paper_margin_budget_usdt": margin_budget,
            "paper_leverage": leverage_raw,
            "sizing_required": sizing_required,
            "sizing_source": active_policy.get("sizing_source"),
            "requested_margin_usdt": requested_margin,
            "max_open_positions": active_policy.get("max_open_positions"),
            "current_open_positions": active_policy.get("current_open_positions"),
            "max_positions_per_symbol": active_policy.get("max_positions_per_symbol"),
            "current_symbol_open_positions": active_policy.get("current_symbol_open_positions"),
            "max_consecutive_losses": active_policy.get("max_consecutive_losses"),
            "consecutive_losses": consecutive_losses,
            "max_total_notional_usdt": active_policy.get("max_total_notional_usdt"),
            "current_total_notional_usdt": current_total_notional,
            "max_drawdown_usdt": active_policy.get("max_drawdown_usdt"),
            "current_drawdown_usdt": current_drawdown,
            "max_symbol_risk_usdt": active_policy.get("max_symbol_risk_usdt"),
            "requested_symbol_risk_usdt": requested_symbol_risk,
            "max_symbol_risk_pct": active_policy.get("max_symbol_risk_pct"),
            "account_equity_usdt": active_policy.get("account_equity_usdt"),
            "min_agent_confidence": active_policy.get("min_agent_confidence"),
            "agent_confidence": agent_confidence,
            "abnormal_move_halt_bps": active_policy.get("abnormal_move_halt_bps"),
            "current_abnormal_move_bps": active_policy.get("current_abnormal_move_bps"),
            "cooldown_active": active_policy.get("cooldown_active"),
            "requested_notional_usdt": requested_notional,
            "max_daily_loss_usdt": active_policy.get("max_daily_loss_usdt"),
            "daily_realized_pnl_usdt": active_policy.get("daily_realized_pnl_usdt"),
            "force_reject_reasons": forced_reject_reasons,
            "mainnet_enabled": active_policy.get("mainnet_enabled"),
            "portfolio_risk_policy": active_policy.get("portfolio_risk_policy_snapshot"),
        },
        "provenance": {
            "source": "tradecat_auto.risk.evaluate_risk",
            "policy_schema": str(active_policy.get("schema") or "tradecat_auto.risk_policy.v1"),
            "signal_schema": str(signal.get("schema") or ""),
        },
        "safety": _safety_boundary(),
        "limitations": ["risk decision permits paper simulation only in this version"],
    }


def _portfolio_policy(active_policy: dict[str, Any]) -> dict[str, Any]:
    raw = active_policy.get("portfolio_risk_policy")
    if isinstance(raw, dict):
        return dict(raw)
    if active_policy.get("schema") == "tradecat_auto.portfolio_risk_policy.v1":
        return dict(active_policy)
    return {}


def _apply_portfolio_policy(active_policy: dict[str, Any], portfolio_policy: dict[str, Any]) -> None:
    if portfolio_policy.get("enabled") is False:
        active_policy["portfolio_risk_policy_snapshot"] = _portfolio_policy_snapshot(portfolio_policy)
        return
    limits = portfolio_policy.get("limits") if isinstance(portfolio_policy.get("limits"), dict) else {}
    field_map = {
        "max_daily_loss_usdt": "max_daily_loss_usdt",
        "max_drawdown_usdt": "max_drawdown_usdt",
        "max_open_positions": "max_open_positions",
        "max_positions_per_symbol": "max_positions_per_symbol",
        "max_symbol_notional_usdt": "max_symbol_notional_usdt",
        "max_total_notional_usdt": "max_total_notional_usdt",
        "max_symbol_risk_usdt": "max_symbol_risk_usdt",
        "max_symbol_risk_pct": "max_symbol_risk_pct",
        "max_leverage": "max_leverage",
        "min_agent_confidence": "min_agent_confidence",
        "cooldown_minutes_after_reject": "cooldown_minutes_after_reject",
        "cooldown_minutes_after_close": "cooldown_minutes_after_close",
        "abnormal_move_halt_bps": "abnormal_move_halt_bps",
        "max_consecutive_losses": "max_consecutive_losses",
    }
    for source_key, target_key in field_map.items():
        value = limits.get(source_key)
        if value is not None:
            active_policy[target_key] = value
    if "new_entries_enabled" in portfolio_policy:
        active_policy["new_entries_enabled"] = bool(portfolio_policy.get("new_entries_enabled"))
    kill_switch = portfolio_policy.get("kill_switch") if isinstance(portfolio_policy.get("kill_switch"), dict) else {}
    if kill_switch.get("active") is True:
        active_policy["portfolio_kill_switch_active"] = True
        active_policy["portfolio_kill_switch_reason"] = str(kill_switch.get("reason") or "")
    active_policy["portfolio_risk_policy_snapshot"] = _portfolio_policy_snapshot(portfolio_policy)


def _portfolio_policy_snapshot(portfolio_policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": str(portfolio_policy.get("schema") or "tradecat_auto.portfolio_risk_policy.v1"),
        "schema_version": str(portfolio_policy.get("schema_version") or "1.0.0"),
        "mode": str(portfolio_policy.get("mode") or ""),
        "enabled": bool(portfolio_policy.get("enabled", True)),
        "new_entries_enabled": portfolio_policy.get("new_entries_enabled"),
        "limits": dict(portfolio_policy.get("limits") if isinstance(portfolio_policy.get("limits"), dict) else {}),
        "kill_switch": dict(
            portfolio_policy.get("kill_switch") if isinstance(portfolio_policy.get("kill_switch"), dict) else {}
        ),
        "provenance": dict(
            portfolio_policy.get("provenance") if isinstance(portfolio_policy.get("provenance"), dict) else {}
        ),
    }


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_cap(value: Any) -> float | None:
    numeric = _num(value)
    return numeric if numeric is not None and numeric > 0 else None


def _as_reason_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    text = str(value or "").strip()
    return [text] if text else []


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _safety_boundary() -> dict[str, bool]:
    return {
        "public_readonly_market_data": True,
        "paper_or_watch_only": True,
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "binance_account_state": False,
    }
