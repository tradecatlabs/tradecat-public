from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tradecat_auto.agent_market_context import (
    ALLOWED_ENDPOINTS_BY_FAMILY,
    DEFAULT_SOURCE_MANIFEST,
    audit_agent_market_context,
)

RESEARCH_CYCLE_SCHEMA = "tradecat_auto.agent_research_cycle.v1"
RESEARCH_CYCLE_AUDIT_SCHEMA = "tradecat_auto.agent_research_cycle_audit.v1"
TOOL_ORCHESTRATION_SCHEMA = "tradecat_auto.agent_tool_orchestration.v1"
SCHEMA_VERSION = "1.0.0"
ALLOWED_MODES = {"observe_only", "paper", "watch"}
PAPER_ACTIONS = {"run_context_paper"}
PUBLIC_SAFETY_FLAGS = {
    "public_readonly_market_data": True,
    "paper_or_watch_only": True,
    "real_orders": False,
    "signed_requests": False,
    "reads_api_keys": False,
    "binance_account_state": False,
}
FORBIDDEN_ENDPOINT_MARKERS = (
    "account",
    "balance",
    "order",
    "openorder",
    "allorders",
    "batchorders",
    "algoorder",
    "usertrades",
    "positionrisk",
    "positionmargin",
    "positionside",
    "leverage",
    "margintype",
    "listenkey",
    "income",
    "commissionrate",
    "signature",
    "apikey",
    "secret",
)
CREDENTIAL_KEY_MARKERS = ("api_key", "apikey", "secret", "signature", "listen_key", "private_key")


def load_agent_research_cycle(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "schema": RESEARCH_CYCLE_SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "ok": False,
            "error_code": "agent_research_cycle_load_failed",
            "error": {
                "code": "agent_research_cycle_load_failed",
                "kind": "input_validation",
                "message": str(exc),
                "retryable": False,
            },
            "provenance": {"source": "tradecat_auto.agent_research_cycle.load_agent_research_cycle", "path": str(p)},
            "safety": _safety_boundary(),
        }
    return data if isinstance(data, dict) else {
        "schema": RESEARCH_CYCLE_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "error_code": "agent_research_cycle_load_failed",
        "error": {
            "code": "agent_research_cycle_load_failed",
            "kind": "input_validation",
            "message": "agent research cycle root must be a JSON object",
            "retryable": False,
        },
        "provenance": {"source": "tradecat_auto.agent_research_cycle.load_agent_research_cycle", "path": str(p)},
        "safety": _safety_boundary(),
    }


def audit_agent_research_cycle(cycle: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not isinstance(cycle, dict):
        cycle = {}
        errors.append(_error("invalid_research_cycle", "research cycle root must be an object"))

    if cycle.get("schema") != RESEARCH_CYCLE_SCHEMA:
        errors.append(_error("invalid_schema", f"schema must be {RESEARCH_CYCLE_SCHEMA}"))
    if cycle.get("schema_version") != SCHEMA_VERSION:
        errors.append(_error("invalid_schema_version", f"schema_version must be {SCHEMA_VERSION}"))

    mode = str(cycle.get("mode") or "").strip()
    if mode not in ALLOWED_MODES:
        errors.append(_error("forbidden_mode", f"mode {mode!r} is outside observe_only/paper/watch"))

    provenance = cycle.get("provenance") if isinstance(cycle.get("provenance"), dict) else {}
    if not provenance or not provenance.get("source"):
        errors.append(_error("missing_provenance", "top-level provenance.source is required"))

    signal = cycle.get("source_signal") if isinstance(cycle.get("source_signal"), dict) else {}
    if not signal:
        errors.append(_error("missing_source_signal", "source_signal is required"))
    elif not isinstance(signal.get("provenance"), dict) or not signal.get("provenance"):
        errors.append(_error("missing_signal_provenance", "source_signal.provenance is required"))

    _audit_safety(cycle.get("safety"), errors)
    for hit in _credential_key_hits(cycle):
        errors.append(_error("credential_material_forbidden", f"credential-like key is not allowed: {hit}"))

    accepted_endpoints: list[str] = []
    rejected_endpoints: list[str] = []
    for section in ("requested_market_data", "tool_calls"):
        items = cycle.get(section)
        if items in (None, ""):
            items = []
        if not isinstance(items, list):
            errors.append(_error("invalid_research_cycle", f"{section} must be an array"))
            continue
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(_error("invalid_market_data_item", f"{section}[{index}] must be an object", index=index))
                continue
            family = str(item.get("family") or "").strip()
            endpoint = _normalize_endpoint(item.get("endpoint"))
            method = str(item.get("method") or "GET").upper().strip()
            forbidden_reason = _forbidden_endpoint_reason(endpoint)
            if family not in ALLOWED_ENDPOINTS_BY_FAMILY:
                errors.append(_error("unsupported_family", f"{section}[{index}].family is not allowlisted: {family!r}", index=index))
                rejected_endpoints.append(endpoint)
                continue
            if method != "GET":
                errors.append(_error("forbidden_method", f"{section}[{index}].method must be GET", index=index))
            if forbidden_reason:
                errors.append(_error("forbidden_endpoint", f"{section}[{index}].endpoint is forbidden: {endpoint} ({forbidden_reason})", index=index))
                rejected_endpoints.append(endpoint)
            elif endpoint not in ALLOWED_ENDPOINTS_BY_FAMILY[family]:
                errors.append(_error("endpoint_not_allowlisted", f"endpoint {endpoint!r} is not allowed for family {family!r}", index=index))
                rejected_endpoints.append(endpoint)
            else:
                accepted_endpoints.append(endpoint)
            if item.get("requires_signature") is True or item.get("signed") is True:
                errors.append(_error("signed_request_forbidden", f"{section}[{index}] is marked as signed/requires_signature", index=index))
            if item.get("reads_api_keys") is True or item.get("real_orders") is True:
                errors.append(_error("safety_boundary_violation", f"{section}[{index}] violates public paper/watch safety flags", index=index))
            if section == "tool_calls" and item.get("ok") is False:
                warnings.append(_warning("tool_call_not_ok", f"tool_calls[{index}] returned ok=false", index=index))

    next_action = cycle.get("next_action") if isinstance(cycle.get("next_action"), dict) else {}
    action = str(next_action.get("action") or "").strip()
    if not action:
        errors.append(_error("missing_next_action", "next_action.action is required"))
    if action in PAPER_ACTIONS:
        thesis = cycle.get("agent_trade_thesis") if isinstance(cycle.get("agent_trade_thesis"), dict) else {}
        sizing_error = _paper_sizing_error(thesis)
        if sizing_error:
            errors.append(_error(sizing_error, "run_context_paper requires explicit Agent paper sizing"))
        if not _has_exit_plan(thesis):
            errors.append(_error("agent_exit_plan_required", "run_context_paper requires explicit Agent exit plan"))
        if any(warning.get("code") == "tool_call_not_ok" for warning in warnings):
            errors.append(_error("market_context_incomplete", "run_context_paper requires successful required market context"))

    ok = not errors
    return {
        "schema": RESEARCH_CYCLE_AUDIT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ok": ok,
        "error_code": None if ok else str(errors[0]["code"]),
        "run_id": str(cycle.get("run_id") or ""),
        "mode": mode,
        "next_action": action,
        "accepted_endpoints": _dedupe(accepted_endpoints),
        "rejected_endpoints": _dedupe(rejected_endpoints),
        "errors": errors,
        "warnings": warnings,
        "provenance": provenance,
        "safety": _safety_boundary(),
    }


def build_observe_only_research_cycle(
    *,
    events: dict[str, Any],
    anomaly_symbols: dict[str, Any],
    requested_symbol: str = "auto",
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a read-only Agent research task skeleton without market tool calls."""

    latest_event = _latest_event(events)
    selected_symbol = _select_symbol(requested_symbol, anomaly_symbols)
    if not latest_event:
        error_code = "no_signal_available"
        next_action = {
            "action": "reject",
            "reason": "no source signal is available for autonomous research",
            "required_inputs": ["tradecat_public_signal_flow"],
            "writes_paper_ledger": False,
        }
    elif not selected_symbol:
        error_code = "no_symbol_selected"
        next_action = {
            "action": "reject",
            "reason": "no candidate symbol could be selected from signal input",
            "required_inputs": ["source_signal.symbol or anomaly symbol"],
            "writes_paper_ledger": False,
        }
    else:
        error_code = None
        next_action = {
            "action": "observe_only",
            "reason": "research task created; Agent/Hermes must fetch public-readonly market context before paper execution",
            "required_inputs": ["agent_market_context", "agent_trade_thesis"],
            "writes_paper_ledger": False,
        }

    ok = error_code is None
    run_id = _research_run_id(latest_event, selected_symbol, generated_at)
    return {
        "schema": RESEARCH_CYCLE_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ok": ok,
        "run_id": run_id,
        "generated_at": generated_at or _now_iso(),
        "mode": "observe_only",
        "symbol": selected_symbol,
        "error_code": error_code,
        "source_signal": _source_signal(latest_event, selected_symbol),
        "requested_market_data": _default_requested_market_data(selected_symbol) if selected_symbol else [],
        "tool_calls": [],
        "tool_orchestration_policy": _tool_orchestration_policy(selected_symbol) if selected_symbol else {},
        "risk_notes": [] if ok else [str(next_action["reason"])],
        "next_action": next_action,
        "provenance": {
            "source": "tradecat_auto.agent_research_cycle.build_observe_only_research_cycle",
            "events_schema": str(events.get("schema") or ""),
            "anomaly_symbols_schema": str(anomaly_symbols.get("schema") or ""),
        },
        "safety": _safety_boundary(),
        "limitations": [
            "observe-only research task; no paper ledger write",
            "no Binance credentials are read",
            "no signed requests are made",
            "no real order is placed",
        ],
    }


def build_observe_only_drafts(cycle: dict[str, Any]) -> dict[str, Any]:
    context = build_observe_only_market_context_draft(cycle)
    context_audit = audit_agent_market_context(context)
    thesis = build_observe_only_trade_thesis_draft(cycle, context_audit=context_audit)
    return {
        "schema": "tradecat_auto.observe_only_drafts.v1",
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "error_code": None,
        "run_id": str(cycle.get("run_id") or ""),
        "research_cycle": cycle,
        "agent_market_context": context,
        "agent_market_context_audit": context_audit,
        "agent_trade_thesis": thesis,
        "provenance": {
            "source": "tradecat_auto.agent_research_cycle.build_observe_only_drafts",
            "research_cycle_run_id": str(cycle.get("run_id") or ""),
        },
        "safety": _safety_boundary(),
    }


def build_observe_only_market_context_draft(cycle: dict[str, Any]) -> dict[str, Any]:
    symbol = str(cycle.get("symbol") or "").upper().strip()
    market_data = []
    for item in cycle.get("requested_market_data") or []:
        if not isinstance(item, dict):
            continue
        market_data.append(
            {
                "family": item.get("family"),
                "endpoint": item.get("endpoint"),
                "method": "GET",
                "ok": False,
                "sequence": item.get("sequence"),
                "required": item.get("required"),
                "provenance": {
                    "source": "agent_required_public_tool_call_pending",
                    "research_cycle_run_id": str(cycle.get("run_id") or ""),
                    "reason": str(item.get("reason") or ""),
                },
                "error": {
                    "code": str(item.get("error_code") or "public_market_data_pending"),
                    "kind": "pending_public_readonly_tool_call",
                    "message": "Agent/Hermes must fetch this Binance public/read-only market data before paper execution.",
                    "retryable": True,
                },
            }
        )
    return {
        "schema": "tradecat_auto.agent_market_context.v1",
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "symbol": symbol,
        "generated_at": _now_iso(),
        "mode": "public_readonly",
        "provenance": {
            "source": "tradecat_auto.agent_research_cycle.build_observe_only_market_context_draft",
            "source_manifest": DEFAULT_SOURCE_MANIFEST,
            "research_cycle_run_id": str(cycle.get("run_id") or ""),
        },
        "source_event": cycle.get("source_signal") if isinstance(cycle.get("source_signal"), dict) else {},
        "market_data": market_data,
        "limitations": [
            "draft context only; Agent public/read-only tool calls are still required",
            "no Binance credentials are read",
            "no signed requests are made",
            "no real order is placed",
        ],
    }


def build_observe_only_trade_thesis_draft(cycle: dict[str, Any], *, context_audit: dict[str, Any]) -> dict[str, Any]:
    requested_families = [
        str(item.get("family"))
        for item in cycle.get("requested_market_data") or []
        if isinstance(item, dict) and item.get("family")
    ]
    return {
        "schema": "tradecat_auto.agent_trade_thesis.v1",
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "symbol": str(cycle.get("symbol") or "").upper().strip(),
        "mode": "paper_research",
        "direction": "WATCH_ONLY",
        "confidence": 0.0,
        "holding_horizon": "unknown",
        "rationale": "observe-only draft; Agent must fetch public market context and explicitly provide thesis, sizing, leverage, and exit plan before paper execution.",
        "error_code": "agent_trade_thesis_required",
        "requested_followup_context_families": requested_families,
        "risk_notes": [
            "No paper sizing is supplied in this draft.",
            "No stop loss, take profit, or max holding time is supplied in this draft.",
            f"context_audit_ok={bool(context_audit.get('ok'))}",
        ],
        "provenance": {
            "source": "tradecat_auto.agent_research_cycle.build_observe_only_trade_thesis_draft",
            "research_cycle_run_id": str(cycle.get("run_id") or ""),
        },
        "limitations": [
            "paper/watch only; no Binance credentials; no real order",
            "draft thesis is not a trade instruction",
        ],
    }


def write_observe_only_drafts(cycle: dict[str, Any], output_dir: Path | str) -> dict[str, Any]:
    out_dir = Path(output_dir)
    _reject_forbidden_output_dir(out_dir)
    drafts = build_observe_only_drafts(cycle)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "research_cycle": out_dir / "research_cycle.json",
        "agent_market_context": out_dir / "agent_market_context.json",
        "agent_trade_thesis": out_dir / "agent_trade_thesis.json",
    }
    files["research_cycle"].write_text(json.dumps(cycle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    files["agent_market_context"].write_text(
        json.dumps(drafts["agent_market_context"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    files["agent_trade_thesis"].write_text(
        json.dumps(drafts["agent_trade_thesis"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "schema": "tradecat_auto.observe_only_draft_write.v1",
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "error_code": None,
        "output_dir": str(out_dir),
        "files": {key: str(path) for key, path in files.items()},
        "provenance": {"source": "tradecat_auto.agent_research_cycle.write_observe_only_drafts"},
        "safety": _safety_boundary(),
    }


def _reject_forbidden_output_dir(output_dir: Path) -> None:
    resolved = output_dir.expanduser().resolve()
    parts = resolved.parts
    for index, part in enumerate(parts[:-1]):
        if part == ".runtime" and parts[index + 1] == "auto-paper":
            raise ValueError("observe_only_output_dir_forbidden: do not write observe-only drafts into .runtime/auto-paper")


def _audit_safety(value: Any, errors: list[dict[str, Any]]) -> None:
    safety = value if isinstance(value, dict) else {}
    for key, expected in PUBLIC_SAFETY_FLAGS.items():
        if safety.get(key) is not expected:
            errors.append(_error("safety_boundary_violation", f"safety.{key} must be {expected!r}"))


def _latest_event(events: dict[str, Any]) -> dict[str, Any] | None:
    rows = events.get("events") if isinstance(events, dict) else []
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    return None


def _select_symbol(requested_symbol: str, anomaly_symbols: dict[str, Any]) -> str:
    text = str(requested_symbol or "auto").upper().strip()
    if text and text != "AUTO":
        return text if text.endswith("USDT") else f"{text}USDT"
    rows = anomaly_symbols.get("symbols") if isinstance(anomaly_symbols, dict) else []
    if isinstance(rows, list):
        for item in rows:
            if not isinstance(item, dict):
                continue
            normalized = str(item.get("normalized_symbol") or "").upper().strip()
            if normalized:
                return normalized
            raw = str(item.get("raw_symbol") or "").upper().strip()
            if raw:
                return raw if raw.endswith("USDT") else f"{raw}USDT"
    rejected = anomaly_symbols.get("rejected") if isinstance(anomaly_symbols, dict) else []
    if isinstance(rejected, list):
        for item in rejected:
            if isinstance(item, dict):
                raw = str(item.get("raw_symbol") or "").upper().strip()
                if raw:
                    return raw if raw.endswith("USDT") else f"{raw}USDT"
    return ""


def _source_signal(event: dict[str, Any] | None, symbol: str) -> dict[str, Any]:
    if not event:
        return {"kind": "tradecat_sheet_event", "symbol": symbol, "provenance": {"source": "tradecat_public_sheet"}}
    return {
        "kind": "tradecat_sheet_event",
        "event_id": str(event.get("event_id") or ""),
        "symbol": symbol,
        "raw": event,
        "provenance": {
            "source": str(event.get("source_dataset_key") or "tradecat_public_sheet"),
            "source_time_bj": str(event.get("source_time_bj") or ""),
        },
    }


def _default_requested_market_data(symbol: str) -> list[dict[str, Any]]:
    del symbol
    return [
        {
            "sequence": 1,
            "family": "klines",
            "endpoint": "/fapi/v1/klines",
            "method": "GET",
            "required": True,
            "reason": "confirm post-signal price structure",
            "error_code": "public_klines_unavailable",
            "fallback_next_action": "request_more_context",
        },
        {
            "sequence": 2,
            "family": "24h_ticker",
            "endpoint": "/fapi/v1/ticker/24hr",
            "method": "GET",
            "required": True,
            "reason": "measure current volatility and turnover",
            "error_code": "public_ticker_unavailable",
            "fallback_next_action": "request_more_context",
        },
        {
            "sequence": 3,
            "family": "book_ticker",
            "endpoint": "/fapi/v1/ticker/bookTicker",
            "method": "GET",
            "required": True,
            "reason": "check immediate spread and top-of-book liquidity",
            "error_code": "public_book_ticker_unavailable",
            "fallback_next_action": "request_more_context",
        },
        {
            "sequence": 4,
            "family": "open_interest",
            "endpoint": "/fapi/v1/openInterest",
            "method": "GET",
            "required": True,
            "reason": "check whether futures positioning supports the signal",
            "error_code": "public_open_interest_unavailable",
            "fallback_next_action": "request_more_context",
        },
        {
            "sequence": 5,
            "family": "funding_rate",
            "endpoint": "/fapi/v1/fundingRate",
            "method": "GET",
            "required": False,
            "reason": "identify funding pressure and crowded positioning risk",
            "error_code": "public_funding_rate_unavailable",
            "fallback_next_action": "hold",
        },
    ]


def _tool_orchestration_policy(symbol: str) -> dict[str, Any]:
    return {
        "schema": TOOL_ORCHESTRATION_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "symbol": symbol,
        "execution": "Agent/Hermes performs ordered GET-only public/read-only Binance market tool calls; TradeCat audits supplied context and never fetches private/account data for this cycle.",
        "required_tool_failure": {
            "next_action": "request_more_context",
            "error_code": "market_context_incomplete",
            "writes_paper_ledger": False,
        },
        "optional_tool_failure": {
            "next_action": "hold",
            "error_code": "optional_market_data_unavailable",
            "writes_paper_ledger": False,
        },
        "prohibited": [
            "Binance API keys or secrets",
            "signed requests",
            "account/order/leverage/margin endpoints",
            "real orders",
        ],
    }


def _research_run_id(event: dict[str, Any] | None, symbol: str, generated_at: str | None) -> str:
    event_id = str((event or {}).get("event_id") or "")
    material = f"{event_id}\n{symbol}\n{generated_at or ''}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"research:{digest}"


def _paper_sizing_error(thesis: dict[str, Any]) -> str | None:
    paper_intent = thesis.get("paper_intent") if isinstance(thesis.get("paper_intent"), dict) else {}
    leverage = _positive_float(paper_intent.get("paper_leverage") or paper_intent.get("requested_leverage") or paper_intent.get("leverage"))
    margin = _positive_float(paper_intent.get("requested_margin_usdt"))
    notional = _positive_float(paper_intent.get("requested_notional_usdt"))
    return None if leverage is not None and (margin is not None or notional is not None) else "agent_sizing_required"


def _has_exit_plan(thesis: dict[str, Any]) -> bool:
    return any(
        _positive_float(thesis.get(key)) is not None
        for key in ("invalidation_price", "take_profit_price", "max_holding_minutes")
    )


def _forbidden_endpoint_reason(endpoint: str) -> str | None:
    compact = endpoint.lower().replace("_", "").replace("-", "")
    for marker in FORBIDDEN_ENDPOINT_MARKERS:
        if marker in compact:
            return f"forbidden endpoint marker {marker}"
    return None


def _normalize_endpoint(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("http://") or text.startswith("https://"):
        try:
            from urllib.parse import urlparse

            text = urlparse(text).path or text
        except Exception:
            pass
    return text if text.startswith("/") else f"/{text}"


def _credential_key_hits(value: Any, *, prefix: str = "") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            compact = key_text.lower().replace("-", "_").replace("_", "")
            normalized = key_text.lower().replace("-", "_")
            if any(marker in normalized for marker in CREDENTIAL_KEY_MARKERS) or any(marker in compact for marker in CREDENTIAL_KEY_MARKERS):
                if normalized in {"requires_signature", "signed", "signed_requests", "reads_api_keys"} and child is False:
                    pass
                else:
                    hits.append(path)
            hits.extend(_credential_key_hits(child, prefix=path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(_credential_key_hits(child, prefix=f"{prefix}[{index}]" if prefix else f"[{index}]"))
    return hits


def _positive_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _error(code: str, message: str, *, index: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if index is not None:
        payload["index"] = index
    return payload


def _warning(code: str, message: str, *, index: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if index is not None:
        payload["index"] = index
    return payload


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(item) for item in values if str(item)))


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
