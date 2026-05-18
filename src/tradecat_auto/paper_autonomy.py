from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tradecat_auto.market_enrichment import parse_float

PAPER_AUTONOMY_PROFILE_SCHEMA = "tradecat_auto.paper_autonomy_profile.v1"
AGENT_TRADE_THESIS_SCHEMA = "tradecat_auto.agent_trade_thesis.v1"
SCHEMA_VERSION = "1.0.0"
FORBIDDEN_TRUE_KEYS = {
    "real_order",
    "real_orders",
    "signed",
    "signed_requests",
    "requires_signature",
    "reads_api_keys",
    "binance_account_state",
}
CREDENTIAL_KEY_MARKERS = ("api_key", "apikey", "secret", "signature", "listen_key", "private_key")


def load_paper_autonomy_profile(path: Path | str | None, *, mode: str = "paper") -> dict[str, Any] | None:
    if str(mode or "paper").strip().lower() not in {"paper", "watch"}:
        return None
    text = str(path or "").strip()
    if not text:
        return None
    profile_path = Path(text)
    if not profile_path.exists():
        raise ValueError(f"paper_autonomy_profile_load_failed: missing file: {profile_path}")
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"paper_autonomy_profile_load_failed: {profile_path}: {exc}") from exc
    return normalize_paper_autonomy_profile(data)


def normalize_paper_autonomy_profile(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        raise ValueError("paper_autonomy_profile_load_failed: profile must be a JSON object")
    schema = value.get("schema")
    if schema not in (None, "", PAPER_AUTONOMY_PROFILE_SCHEMA):
        raise ValueError(f"paper_autonomy_profile_load_failed: schema must be {PAPER_AUTONOMY_PROFILE_SCHEMA}")
    schema_version = value.get("schema_version")
    if schema_version not in (None, "", SCHEMA_VERSION):
        raise ValueError(f"paper_autonomy_profile_load_failed: schema_version must be {SCHEMA_VERSION}")
    if value.get("enabled") is False:
        return None
    hits = _forbidden_hits(value)
    if hits:
        raise ValueError(f"paper_autonomy_profile_load_failed: forbidden private/real-trade fields: {', '.join(hits)}")
    safety = value.get("safety") if isinstance(value.get("safety"), dict) else {}
    for key, expected in _safety_boundary().items():
        if key in safety and safety.get(key) is not expected:
            raise ValueError(f"paper_autonomy_profile_load_failed: safety.{key} must be {expected!r}")
    paper_intent = _paper_intent(value)
    leverage = _positive_float(paper_intent.get("paper_leverage") or paper_intent.get("requested_leverage") or paper_intent.get("leverage"))
    margin = _positive_float(paper_intent.get("requested_margin_usdt"))
    notional = _positive_float(paper_intent.get("requested_notional_usdt"))
    if leverage is None or (margin is None and notional is None):
        raise ValueError("paper_autonomy_profile_load_failed: paper_intent requires paper_leverage plus requested_margin_usdt or requested_notional_usdt")
    exit_plan = value.get("exit_plan") if isinstance(value.get("exit_plan"), dict) else {}
    if not any(_positive_float(exit_plan.get(key)) is not None for key in ("stop_loss_bps", "take_profit_bps", "max_holding_minutes")):
        raise ValueError("paper_autonomy_profile_load_failed: exit_plan requires stop_loss_bps, take_profit_bps, or max_holding_minutes")
    return {
        **value,
        "schema": PAPER_AUTONOMY_PROFILE_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ok": bool(value.get("ok", True)),
        "enabled": True,
        "safety": {**_safety_boundary(), **safety},
    }


def synthesize_agent_trade_thesis(
    *,
    agent_trade_thesis: dict[str, Any] | None,
    paper_autonomy_profile: dict[str, Any] | None,
    signal: dict[str, Any],
    enrichment: dict[str, Any],
    events: dict[str, Any],
) -> dict[str, Any] | None:
    profile = paper_autonomy_profile if isinstance(paper_autonomy_profile, dict) and paper_autonomy_profile.get("enabled") is not False else None
    thesis = dict(agent_trade_thesis) if isinstance(agent_trade_thesis, dict) else {}
    if profile is None:
        return thesis or None

    thesis.setdefault("schema", AGENT_TRADE_THESIS_SCHEMA)
    thesis.setdefault("schema_version", SCHEMA_VERSION)
    thesis.setdefault("ok", True)
    thesis.setdefault("symbol", str(signal.get("symbol") or enrichment.get("symbol") or "").upper().strip())
    thesis.setdefault("mode", "paper_research")
    thesis.setdefault("direction", str(signal.get("direction") or "WATCH_ONLY").upper().strip())
    thesis.setdefault("confidence", _confidence(signal))
    thesis.setdefault("holding_horizon", str(profile.get("holding_horizon") or "intraday"))
    thesis.setdefault("rationale", "operator-delegated paper autonomy profile supplied sizing/exits for Agent paper research.")
    thesis.setdefault("risk_notes", [])
    thesis.setdefault("limitations", ["paper/watch only; no Binance key; no signed requests; no real order"])

    existing_paper_intent = thesis.get("paper_intent") if isinstance(thesis.get("paper_intent"), dict) else {}
    if not _paper_intent_complete(existing_paper_intent):
        thesis["paper_intent"] = _profile_paper_intent({**profile, "paper_intent": {**_profile_paper_intent(profile), **existing_paper_intent}})
    profile_direction = _profile_direction(profile, signal=signal, enrichment=enrichment)
    if profile_direction and str(thesis.get("direction") or "").upper().strip() in {"", "WATCH_ONLY"}:
        thesis["direction"] = profile_direction
        thesis["direction_policy"] = _direction_policy(profile)

    exit_plan = _exit_plan_from_profile(
        profile,
        signal=signal,
        enrichment=enrichment,
        direction_override=str(thesis.get("direction") or ""),
    )
    for key in ("invalidation_price", "take_profit_price", "max_holding_minutes", "exit_rationale"):
        if thesis.get(key) in (None, "") and exit_plan.get(key) not in (None, ""):
            thesis[key] = exit_plan[key]

    provenance = thesis.get("provenance") if isinstance(thesis.get("provenance"), dict) else {}
    latest_event = _latest_event(events)
    thesis["provenance"] = {
        **provenance,
        "source": provenance.get("source") or "tradecat_auto.paper_autonomy.synthesize_agent_trade_thesis",
        "paper_autonomy_profile": True,
        "paper_direction_override": bool(profile_direction),
        "source_event_id": str(latest_event.get("event_id") or "") if latest_event else "",
        "generated_at": _now_iso(),
    }
    return thesis


def _profile_paper_intent(profile: dict[str, Any]) -> dict[str, Any]:
    paper_intent = dict(_paper_intent(profile))
    leverage = paper_intent.get("paper_leverage") or paper_intent.get("requested_leverage") or paper_intent.get("leverage")
    paper_intent["paper_leverage"] = leverage
    paper_intent.setdefault("allow_tradecat_paper_gate_to_decide", True)
    paper_intent["real_order"] = False
    return paper_intent


def _paper_intent_complete(paper_intent: Any) -> bool:
    if not isinstance(paper_intent, dict):
        return False
    leverage = _positive_float(paper_intent.get("paper_leverage") or paper_intent.get("requested_leverage") or paper_intent.get("leverage"))
    margin = _positive_float(paper_intent.get("requested_margin_usdt"))
    notional = _positive_float(paper_intent.get("requested_notional_usdt"))
    return leverage is not None and (margin is not None or notional is not None)


def _profile_direction(profile: dict[str, Any], *, signal: dict[str, Any], enrichment: dict[str, Any]) -> str:
    paper_intent = _paper_intent(profile)
    if paper_intent.get("allow_agent_direction_override") is not True and profile.get("allow_agent_direction_override") is not True:
        return ""
    min_score = _positive_float(paper_intent.get("min_signal_score") or profile.get("min_signal_score"))
    score = _positive_float(signal.get("score")) or 0.0
    if min_score is not None and score < min_score:
        return ""
    explicit = _direction(paper_intent.get("paper_direction") or paper_intent.get("direction") or profile.get("direction"))
    if explicit:
        return explicit
    metrics = enrichment.get("metrics") if isinstance(enrichment.get("metrics"), dict) else {}
    policy = _direction_policy(profile)
    if policy in {"price_momentum", "price_momentum_on_conflict"}:
        price_change = parse_float(metrics.get("price_change_24h_pct"))
        if price_change is not None:
            return "LONG" if price_change >= 0 else "SHORT"
    if policy == "taker_flow":
        taker = parse_float(metrics.get("taker_buy_sell_ratio"))
        if taker is not None and taker >= 1.05:
            return "LONG"
        if taker is not None and taker <= 0.95:
            return "SHORT"
    return ""


def _direction_policy(profile: dict[str, Any]) -> str:
    paper_intent = _paper_intent(profile)
    return str(paper_intent.get("direction_policy") or profile.get("direction_policy") or "").strip().lower()


def _direction(value: Any) -> str:
    text = str(value or "").upper().strip()
    return text if text in {"LONG", "SHORT"} else ""


def _paper_intent(profile: dict[str, Any]) -> dict[str, Any]:
    value = profile.get("paper_intent")
    return dict(value) if isinstance(value, dict) else {}


def _exit_plan_from_profile(
    profile: dict[str, Any],
    *,
    signal: dict[str, Any],
    enrichment: dict[str, Any],
    direction_override: str = "",
) -> dict[str, Any]:
    exit_plan = profile.get("exit_plan") if isinstance(profile.get("exit_plan"), dict) else {}
    metrics = enrichment.get("metrics") if isinstance(enrichment.get("metrics"), dict) else {}
    entry_price = parse_float(metrics.get("last_price"))
    direction = str(direction_override or signal.get("direction") or "").upper().strip()
    stop_bps = _positive_float(exit_plan.get("stop_loss_bps"))
    take_bps = _positive_float(exit_plan.get("take_profit_bps"))
    invalidation = None
    take_profit = None
    if entry_price is not None and entry_price > 0 and direction in {"LONG", "SHORT"}:
        if stop_bps is not None:
            invalidation = entry_price * (1 - stop_bps / 10_000) if direction == "LONG" else entry_price * (1 + stop_bps / 10_000)
        if take_bps is not None:
            take_profit = entry_price * (1 + take_bps / 10_000) if direction == "LONG" else entry_price * (1 - take_bps / 10_000)
    max_holding = _positive_float(exit_plan.get("max_holding_minutes"))
    return {
        "invalidation_price": invalidation,
        "take_profit_price": take_profit,
        "max_holding_minutes": max_holding,
        "exit_rationale": str(exit_plan.get("exit_rationale") or "operator-delegated paper autonomy profile"),
    }


def _forbidden_hits(value: Any, *, prefix: str = "") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            normalized = key_text.lower().replace("-", "_")
            compact = normalized.replace("_", "")
            if child is True and normalized in FORBIDDEN_TRUE_KEYS:
                hits.append(path)
            elif (
                not (path == "safety.reads_api_keys" and child is False)
                and (any(marker in normalized for marker in CREDENTIAL_KEY_MARKERS) or any(marker in compact for marker in CREDENTIAL_KEY_MARKERS))
            ):
                hits.append(path)
            hits.extend(_forbidden_hits(child, prefix=path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(_forbidden_hits(child, prefix=f"{prefix}[{index}]" if prefix else f"[{index}]"))
    return hits


def _confidence(signal: dict[str, Any]) -> float:
    try:
        score = float(signal.get("score") or 0)
    except (TypeError, ValueError):
        score = 0.0
    return max(0.0, min(score / 100.0, 1.0))


def _latest_event(events: dict[str, Any]) -> dict[str, Any] | None:
    rows = events.get("events") if isinstance(events, dict) else []
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    return None


def _positive_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _safety_boundary() -> dict[str, bool]:
    return {
        "public_readonly_market_data": True,
        "paper_or_watch_only": True,
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "binance_account_state": False,
    }


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
