from __future__ import annotations

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


def evaluate_risk(signal: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    active_policy = dict(default_risk_policy())
    if policy:
        active_policy.update(policy)
    mode = str(active_policy.get("mode") or "paper")
    reasons: list[str] = []
    constraints = ["paper_only", "no_real_orders", "no_api_keys", "deterministic_risk_gate"]

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

    max_consecutive_losses = int(active_policy.get("max_consecutive_losses") or 0)
    consecutive_losses = int(active_policy.get("consecutive_losses") or 0)
    if max_consecutive_losses > 0 and consecutive_losses >= max_consecutive_losses:
        reasons.append("consecutive_loss_limit_reached")

    max_open_positions = int(active_policy.get("max_open_positions") or 0)
    current_open_positions = int(active_policy.get("current_open_positions") or 0)
    if max_open_positions > 0 and current_open_positions >= max_open_positions:
        reasons.append("max_open_positions_reached")

    leverage_raw = _num(active_policy.get("paper_leverage"))
    leverage = leverage_raw if leverage_raw is not None else 0.0
    requested_margin = _num(active_policy.get("requested_margin_usdt"))
    margin_budget = _num(active_policy.get("paper_margin_budget_usdt"))
    if margin_budget is not None and margin_budget > 0 and requested_margin is not None and requested_margin > margin_budget:
        reasons.append("margin_budget_exceeded")
    requested_notional_raw = _num(active_policy.get("requested_notional_usdt"))
    requested_notional = requested_notional_raw if requested_notional_raw is not None else 0.0
    sizing_required = bool(active_policy.get("sizing_required", mode == "paper"))
    if mode == "paper" and sizing_required and (requested_notional_raw is None or requested_notional <= 0 or leverage_raw is None):
        reasons.append("agent_sizing_required")
    if leverage_raw is not None and leverage <= 0:
        reasons.append("invalid_leverage")
    max_leverage = _num(active_policy.get("max_leverage"))
    if leverage > 0 and max_leverage is not None and max_leverage > 0 and leverage > max_leverage:
        reasons.append("max_leverage_exceeded")

    max_total_notional = _num(active_policy.get("max_total_notional_usdt")) or 0.0
    current_total_notional = _num(active_policy.get("current_total_notional_usdt")) or 0.0
    if max_total_notional > 0 and requested_notional > 0 and current_total_notional + requested_notional > max_total_notional:
        reasons.append("max_total_notional_reached")

    forced_reject_reasons = _as_reason_list(active_policy.get("force_reject_reasons"))
    reasons.extend(forced_reject_reasons)

    signal_reasons = signal.get("do_not_trade_reasons") if isinstance(signal.get("do_not_trade_reasons"), list) else []
    if signal_reasons:
        reasons.extend(str(item) for item in signal_reasons)

    reasons = _dedupe(reasons)
    always_reject = {
        "kill_switch_active",
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
            "max_consecutive_losses": active_policy.get("max_consecutive_losses"),
            "consecutive_losses": consecutive_losses,
            "max_total_notional_usdt": active_policy.get("max_total_notional_usdt"),
            "current_total_notional_usdt": current_total_notional,
            "requested_notional_usdt": requested_notional,
            "max_daily_loss_usdt": active_policy.get("max_daily_loss_usdt"),
            "daily_realized_pnl_usdt": active_policy.get("daily_realized_pnl_usdt"),
            "force_reject_reasons": forced_reject_reasons,
            "mainnet_enabled": active_policy.get("mainnet_enabled"),
        },
        "provenance": {
            "source": "tradecat_auto.risk.evaluate_risk",
            "policy_schema": str(active_policy.get("schema") or "tradecat_auto.risk_policy.v1"),
            "signal_schema": str(signal.get("schema") or ""),
        },
        "safety": _safety_boundary(),
        "limitations": ["risk decision permits paper simulation only in this version"],
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
