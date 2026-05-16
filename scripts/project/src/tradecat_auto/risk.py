from __future__ import annotations

from pathlib import Path
from typing import Any


def default_risk_policy(*, mode: str = "paper") -> dict[str, Any]:
    return {
        "schema": "tradecat_auto.risk_policy.v1",
        "mode": mode,
        "allowed_market": "usds_m_futures",
        "allowed_quote_asset": "USDT",
        "allowed_contract_type": "PERPETUAL",
        "mainnet_enabled": False,
        "min_score": 60,
        "max_symbol_notional_usdt": 20.0,
        "max_total_notional_usdt": 50.0,
        "max_spread_bps": 10.0,
        "max_leverage": 3,
        "max_open_positions": 3,
        "current_open_positions": 0,
        "max_consecutive_losses": 3,
        "consecutive_losses": 0,
        "max_daily_loss_usdt": 20.0,
        "daily_realized_pnl_usdt": 0.0,
        "current_total_notional_usdt": 0.0,
        "requested_notional_usdt": 0.0,
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
    if score < float(active_policy.get("min_score") or 60):
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

    max_total_notional = float(active_policy.get("max_total_notional_usdt") or 0.0)
    current_total_notional = _num(active_policy.get("current_total_notional_usdt")) or 0.0
    requested_notional = _num(active_policy.get("requested_notional_usdt")) or 0.0
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
    elif reasons:
        decision = "REJECT"
    else:
        decision = "ALLOW"

    return {
        "schema": "tradecat_auto.risk_decision.v1",
        "ok": True,
        "decision": decision,
        "mode": mode,
        "symbol": str(signal.get("symbol") or ""),
        "direction": signal.get("direction", "WATCH_ONLY"),
        "score": score,
        "max_notional_usdt": float(active_policy.get("max_symbol_notional_usdt") or 0),
        "constraints": constraints,
        "reasons": reasons,
        "policy": {
            "min_score": active_policy.get("min_score"),
            "max_symbol_notional_usdt": active_policy.get("max_symbol_notional_usdt"),
            "max_leverage": active_policy.get("max_leverage"),
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
        "limitations": ["risk decision permits paper simulation only in this version"],
    }


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_reason_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    text = str(value or "").strip()
    return [text] if text else []


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
