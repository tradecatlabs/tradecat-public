from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tradecat_auto.binance_market import summarize_depth
from tradecat_auto.pipeline import build_paper_pipeline_report

CONTEXT_SCHEMA = "tradecat_auto.agent_market_context.v1"
AUDIT_SCHEMA = "tradecat_auto.agent_market_context_audit.v1"
SCHEMA_VERSION = "1.0.0"
DEFAULT_SOURCE_MANIFEST = "scripts/project/resources/agent_market_context/binance/provenance.manifest.json"

ALLOWED_MODES = {"public_readonly", "paper", "watch"}
ALLOWED_ENDPOINTS_BY_FAMILY: dict[str, set[str]] = {
    "klines": {"/fapi/v1/klines"},
    "order_book_depth": {"/fapi/v1/depth"},
    "book_ticker": {"/fapi/v1/ticker/bookTicker"},
    "24h_ticker": {"/fapi/v1/ticker/24hr"},
    "funding_rate": {"/fapi/v1/fundingRate"},
    "premium_index": {"/fapi/v1/premiumIndex"},
    "open_interest": {"/fapi/v1/openInterest"},
    "open_interest_history": {"/futures/data/openInterestHist"},
    "long_short_ratios": {
        "/futures/data/topLongShortAccountRatio",
        "/futures/data/topLongShortPositionRatio",
        "/futures/data/globalLongShortAccountRatio",
    },
    "taker_buy_sell_volume": {"/futures/data/takerlongshortRatio"},
}
FORBIDDEN_ENDPOINTS = {
    "/fapi/v1/accountConfig",
    "/fapi/v1/adlQuantile",
    "/fapi/v1/algoOrder",
    "/fapi/v1/allAlgoOrders",
    "/fapi/v1/allOpenOrders",
    "/fapi/v1/allOrders",
    "/fapi/v1/apiTradingStatus",
    "/fapi/v1/batchOrders",
    "/fapi/v1/commissionRate",
    "/fapi/v1/countdownCancelAll",
    "/fapi/v1/forceOrders",
    "/fapi/v1/income",
    "/fapi/v1/leverage",
    "/fapi/v1/leverageBracket",
    "/fapi/v1/listenKey",
    "/fapi/v1/marginType",
    "/fapi/v1/multiAssetsMargin",
    "/fapi/v1/openAlgoOrders",
    "/fapi/v1/openOrder",
    "/fapi/v1/openOrders",
    "/fapi/v1/order",
    "/fapi/v1/order/test",
    "/fapi/v1/orderAmendment",
    "/fapi/v1/pmAccountInfo",
    "/fapi/v1/positionMargin",
    "/fapi/v1/positionMargin/history",
    "/fapi/v1/positionSide/dual",
    "/fapi/v1/rateLimit/order",
    "/fapi/v1/symbolConfig",
    "/fapi/v1/userTrades",
    "/fapi/v2/account",
    "/fapi/v2/balance",
    "/fapi/v2/positionRisk",
    "/fapi/v3/account",
    "/fapi/v3/balance",
    "/fapi/v3/positionRisk",
}
FORBIDDEN_ENDPOINT_MARKERS = (
    "/account",
    "/balance",
    "/order",
    "/openorder",
    "/openorders",
    "/allorders",
    "/allopenorders",
    "/batchorders",
    "/algoorder",
    "/algoopenorders",
    "/openalgoorders",
    "/countdowncancelall",
    "/usertrades",
    "/positionrisk",
    "/positionmargin",
    "/positionside/dual",
    "/leverage",
    "/margintype",
    "/multiassetsmargin",
    "/listenkey",
    "/income",
    "/commissionrate",
    "/ratelimit/order",
    "/symbolconfig",
    "/apitradingstatus",
    "/forceorders",
    "/pmaccountinfo",
)
CREDENTIAL_KEY_FRAGMENTS = ("api_key", "secret", "signature", "signed", "listen_key", "private_key")
CREDENTIAL_KEY_COMPACT_FRAGMENTS = tuple(fragment.replace("_", "") for fragment in CREDENTIAL_KEY_FRAGMENTS) + (
    "apikey",
    "secretkey",
)
SIGNED_TIMESTAMP_CONTEXT_KEYS = {"apikey", "recvwindow", "requiressignature", "secretkey", "signature", "signed"}
FORBIDDEN_STATE_KEY_NAMES = {
    "account",
    "account_info",
    "account_state",
    "activate_price",
    "activateprice",
    "all_orders",
    "allorders",
    "avg_price",
    "avgprice",
    "balance",
    "balances",
    "binance_account",
    "binance_order",
    "client_order_id",
    "clientorderid",
    "close_position",
    "closeposition",
    "cum_qty",
    "cum_quote",
    "cumqty",
    "cumquote",
    "cummulative_quote_qty",
    "cummulativequoteqty",
    "exchange_order",
    "exchange_order_id",
    "executed_qty",
    "executedqty",
    "fill",
    "fills",
    "good_till_date",
    "goodtilldate",
    "new_client_order_id",
    "newclientorderid",
    "open_orders",
    "openorders",
    "order_history",
    "order_id",
    "order_list_id",
    "order_status",
    "orderid",
    "orderlistid",
    "orig_client_order_id",
    "orig_qty",
    "origclientorderid",
    "origqty",
    "position",
    "position_amt",
    "position_risk",
    "position_side",
    "positionamt",
    "positionrisk",
    "positions",
    "positionside",
    "price_match",
    "price_protect",
    "price_rate",
    "pricematch",
    "priceprotect",
    "pricerate",
    "real_order",
    "real_orders",
    "reduce_only",
    "reduceonly",
    "self_trade_prevention_mode",
    "selftradepreventionmode",
    "stop_price",
    "stopprice",
    "time_in_force",
    "timeinforce",
    "transact_time",
    "transacttime",
    "update_time",
    "updatetime",
    "user_trades",
    "usertrades",
    "working_type",
    "workingtype",
}


def load_agent_market_context(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "schema": CONTEXT_SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "ok": False,
            "error": {
                "code": "agent_market_context_load_failed",
                "kind": "validation",
                "message": f"failed to load agent market context: {exc}",
                "retryable": False,
            },
        }
    return payload if isinstance(payload, dict) else {"schema": CONTEXT_SCHEMA, "schema_version": SCHEMA_VERSION, "ok": False}


def audit_agent_market_context(context: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not isinstance(context, dict):
        context = {}
        errors.append(_error("invalid_context", "context root must be an object"))

    schema = context.get("schema")
    if schema != CONTEXT_SCHEMA:
        errors.append(_error("invalid_schema", f"schema must be {CONTEXT_SCHEMA}"))
    if context.get("schema_version") != SCHEMA_VERSION:
        errors.append(_error("invalid_schema_version", f"schema_version must be {SCHEMA_VERSION}"))

    mode = str(context.get("mode") or "public_readonly").strip()
    if mode not in ALLOWED_MODES:
        errors.append(_error("forbidden_mode", f"mode {mode!r} is outside public_readonly/paper/watch boundary"))

    symbol = str(context.get("symbol") or "").upper().strip()
    if not symbol:
        errors.append(_error("missing_symbol", "symbol is required"))

    raw_top_provenance = context.get("provenance")
    top_provenance: dict[str, Any] = raw_top_provenance if isinstance(raw_top_provenance, dict) else {}
    if not top_provenance:
        errors.append(_error("missing_provenance", "top-level provenance is required"))
    elif not top_provenance.get("source_manifest"):
        errors.append(_error("missing_source_manifest", "provenance.source_manifest is required for reproducible audits"))

    credential_hits = _credential_key_hits(context)
    for hit in credential_hits:
        errors.append(_error("credential_material_forbidden", f"credential-like key is not allowed: {hit}"))

    signed_timestamp_hits = _signed_timestamp_hits(context)
    for hit in signed_timestamp_hits:
        errors.append(_error("signed_timestamp_forbidden", f"timestamp is not allowed inside a signed/request-signature context: {hit}"))

    forbidden_state_hits = _forbidden_state_key_hits(context)
    for hit in forbidden_state_hits:
        errors.append(
            _error(
                "account_or_order_state_forbidden",
                f"real account/order state key is not allowed in Agent-supplied context: {hit}",
            )
        )

    accepted_families: list[str] = []
    rejected_families: list[str] = []
    accepted_endpoints: list[str] = []
    market_data = context.get("market_data")
    if not isinstance(market_data, list) or not market_data:
        errors.append(_error("missing_market_data", "market_data must be a non-empty array"))
        market_data = []

    for index, item in enumerate(market_data):
        if not isinstance(item, dict):
            errors.append(_error("invalid_market_data_item", "market_data item must be an object", index=index))
            continue
        family = str(item.get("family") or "").strip()
        endpoint = _normalize_endpoint(str(item.get("endpoint") or ""))
        method = str(item.get("method") or "GET").upper().strip()
        item_provenance = item.get("provenance") if isinstance(item.get("provenance"), dict) else {}

        if family not in ALLOWED_ENDPOINTS_BY_FAMILY:
            rejected_families.append(family)
            errors.append(_error("unsupported_family", f"market_data[{index}].family is not allowlisted: {family!r}", index=index))
            continue
        if method != "GET":
            errors.append(_error("forbidden_method", f"market_data[{index}].method must be GET", index=index))
        forbidden_endpoint_reason = _forbidden_endpoint_reason(endpoint)
        if forbidden_endpoint_reason:
            errors.append(
                _error(
                    "forbidden_endpoint",
                    f"market_data[{index}].endpoint is forbidden: {endpoint} ({forbidden_endpoint_reason})",
                    index=index,
                )
            )
        elif endpoint not in ALLOWED_ENDPOINTS_BY_FAMILY[family]:
            errors.append(_error("endpoint_not_allowlisted", f"endpoint {endpoint!r} is not allowed for family {family!r}", index=index))
        if item.get("requires_signature") is True or item.get("signed") is True:
            errors.append(_error("signed_request_forbidden", f"market_data[{index}] is marked as signed/requires_signature", index=index))
        if not item_provenance:
            errors.append(_error("missing_item_provenance", f"market_data[{index}].provenance is required", index=index))
        if item.get("ok") is False:
            warnings.append(_warning("market_data_item_not_ok", f"market_data[{index}] was supplied as ok=false", index=index))

        if not any(error.get("index") == index for error in errors):
            accepted_families.append(family)
            accepted_endpoints.append(endpoint)

    ok = not errors
    return {
        "schema": AUDIT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ok": ok,
        "symbol": symbol,
        "mode": mode,
        "accepted_families": _dedupe(accepted_families),
        "rejected_families": _dedupe([item for item in rejected_families if item]),
        "accepted_endpoints": _dedupe(accepted_endpoints),
        "errors": errors,
        "warnings": warnings,
        "provenance": copy.deepcopy(top_provenance),
        "source_manifest": top_provenance.get("source_manifest") or DEFAULT_SOURCE_MANIFEST,
        "safety_boundary_enforced": True,
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "allowed_modes": sorted(ALLOWED_MODES),
        "allowed_market_context_families": sorted(ALLOWED_ENDPOINTS_BY_FAMILY),
        "generated_at": _now_iso(),
    }


def agent_market_context_to_market_bundle(context: dict[str, Any]) -> dict[str, Any]:
    audit = audit_agent_market_context(context)
    symbol = str(context.get("symbol") or audit.get("symbol") or "").upper().strip()
    bundle: dict[str, Any] = {
        "schema": "tradecat_auto.public_market_bundle.v1",
        "schema_version": SCHEMA_VERSION,
        "ok": bool(audit.get("ok")),
        "symbol": symbol,
        "source": "agent_supplied_market_context",
        "agent_market_context_audit": audit,
        "errors": {},
    }
    if not audit.get("ok"):
        bundle["errors"]["agent_market_context"] = audit.get("errors", [])
        return bundle

    for item in context.get("market_data") or []:
        if not isinstance(item, dict) or item.get("ok") is False:
            continue
        family = str(item.get("family") or "")
        endpoint = _normalize_endpoint(str(item.get("endpoint") or ""))
        data = copy.deepcopy(item.get("data"))
        if family == "24h_ticker":
            bundle["ticker24hr"] = data
        elif family == "book_ticker":
            bundle["bookTicker"] = data
        elif family == "order_book_depth":
            bundle["depth"] = data
            if isinstance(data, dict):
                bundle["depth_summary"] = summarize_depth(data)
        elif family == "klines":
            bundle["klines"] = data
        elif family == "open_interest":
            bundle["openInterest"] = data
        elif family == "open_interest_history":
            bundle["openInterestHist"] = _ensure_list(data)
        elif family == "funding_rate":
            bundle["fundingRate"] = _ensure_list(data)
        elif family == "premium_index":
            bundle["premiumIndex"] = data
        elif family == "long_short_ratios":
            _map_long_short_ratio(bundle, endpoint, data)
        elif family == "taker_buy_sell_volume":
            bundle["takerlongshortRatio"] = _ensure_list(data)
    return bundle


def build_paper_report_from_agent_market_context(
    context: dict[str, Any],
    *,
    mode: str = "paper",
    requested_notional_usdt: float | None = None,
    requested_margin_usdt: float | None = None,
    paper_leverage: float | None = None,
    margin_budget_usdt: float | None = None,
    risk_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    audit = audit_agent_market_context(context)
    if not audit.get("ok"):
        return {
            "schema": "tradecat_auto.run_once_report.v1",
            "schema_version": SCHEMA_VERSION,
            "ok": False,
            "real_orders": False,
            "signed_requests": False,
            "reads_api_keys": False,
            "mode": mode,
            "selected_symbol": audit.get("symbol") or str(context.get("symbol") or "").upper().strip(),
            "error": "agent_market_context_audit_failed",
            "agent_market_context_audit": audit,
            "provenance": _top_provenance(context),
            "safety": _safety_boundary(),
            "limitations": [
                "agent-supplied public/read-only market context rejected before paper pipeline",
                "no Binance credentials were read",
                "no real order was placed",
            ],
        }
    selected_symbol = str(context.get("symbol") or audit.get("symbol") or "").upper().strip()
    agent_sizing = _agent_paper_sizing(context)
    resolved_requested_margin = requested_margin_usdt if requested_margin_usdt is not None else agent_sizing.get("requested_margin_usdt")
    resolved_paper_leverage = paper_leverage if paper_leverage is not None else agent_sizing.get("paper_leverage")
    resolved_requested_notional = requested_notional_usdt if requested_notional_usdt is not None else agent_sizing.get("requested_notional_usdt")
    sizing_source = str(agent_sizing.get("source") or "agent_market_context_missing_sizing")
    if requested_margin_usdt is not None or requested_notional_usdt is not None or paper_leverage is not None:
        sizing_source = "explicit_cli_override"
    anomaly_item = context.get("anomaly_symbol") if isinstance(context.get("anomaly_symbol"), dict) else {}
    if not anomaly_item:
        anomaly_item = {"raw_symbol": selected_symbol, "normalized_symbol": selected_symbol, "source_values": {}}
    anomaly_item = copy.deepcopy(anomaly_item)
    anomaly_item["normalized_symbol"] = selected_symbol
    event = context.get("source_event") if isinstance(context.get("source_event"), dict) else {}
    report = build_paper_pipeline_report(
        selected_symbol=selected_symbol,
        anomaly_symbols={"ok": True, "symbols": [anomaly_item], "rejected": []},
        market_bundle=agent_market_context_to_market_bundle(context),
        events={"ok": True, "events": [copy.deepcopy(event)] if event else []},
        mode=mode,
        requested_notional_usdt=resolved_requested_notional,
        requested_margin_usdt=resolved_requested_margin,
        paper_leverage=resolved_paper_leverage,
        margin_budget_usdt=margin_budget_usdt,
        sizing_source=sizing_source,
        agent_trade_thesis=context.get("agent_trade_thesis") if isinstance(context.get("agent_trade_thesis"), dict) else None,
        risk_policy=risk_policy,
    )
    report["schema_version"] = SCHEMA_VERSION
    report["agent_market_context_audit"] = audit
    report["agent_paper_sizing_input"] = agent_sizing
    report["market_context_provenance"] = copy.deepcopy(context.get("provenance") if isinstance(context.get("provenance"), dict) else {})
    report["provenance"] = {
        **(report.get("provenance") if isinstance(report.get("provenance"), dict) else {}),
        "agent_market_context": _top_provenance(context),
    }
    report.setdefault("limitations", [])
    if "agent-supplied public/read-only market context" not in report["limitations"]:
        report["limitations"].append("agent-supplied public/read-only market context")
    return report


def _agent_paper_sizing(context: dict[str, Any]) -> dict[str, Any]:
    paper_intent = _paper_intent_from_context(context)
    if not paper_intent:
        return {
            "schema": "tradecat_auto.agent_paper_sizing_input.v1",
            "schema_version": "1.0.0",
            "ok": False,
            "source": "agent_market_context_missing_sizing",
            "requested_margin_usdt": None,
            "paper_leverage": None,
            "requested_notional_usdt": None,
            "error_code": "agent_sizing_required",
        }
    requested_margin = _positive_number(paper_intent.get("requested_margin_usdt"))
    leverage = _positive_number(
        paper_intent.get("requested_leverage")
        if paper_intent.get("requested_leverage") is not None
        else paper_intent.get("paper_leverage", paper_intent.get("leverage"))
    )
    requested_notional = _positive_number(paper_intent.get("requested_notional_usdt"))
    ok = (requested_margin is not None and leverage is not None) or (requested_notional is not None and leverage is not None)
    return {
        "schema": "tradecat_auto.agent_paper_sizing_input.v1",
        "schema_version": "1.0.0",
        "ok": ok,
        "source": "agent_trade_thesis.paper_intent",
        "requested_margin_usdt": requested_margin,
        "paper_leverage": leverage,
        "requested_notional_usdt": requested_notional,
        "error_code": None if ok else "agent_sizing_required",
    }


def _paper_intent_from_context(context: dict[str, Any]) -> dict[str, Any]:
    thesis = context.get("agent_trade_thesis") if isinstance(context.get("agent_trade_thesis"), dict) else {}
    if isinstance(thesis.get("paper_intent"), dict):
        return thesis["paper_intent"]
    if isinstance(context.get("paper_intent"), dict):
        return context["paper_intent"]
    return {}


def _positive_number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric > 0 else None


def _map_long_short_ratio(bundle: dict[str, Any], endpoint: str, data: Any) -> None:
    rows = _ensure_list(data)
    if endpoint.endswith("topLongShortAccountRatio"):
        bundle["topLongShortAccountRatio"] = rows
    elif endpoint.endswith("topLongShortPositionRatio"):
        bundle["topLongShortPositionRatio"] = rows
    elif endpoint.endswith("globalLongShortAccountRatio"):
        bundle["globalLongShortAccountRatio"] = rows
    else:
        bundle.setdefault("longShortRatios", []).extend(rows)


def _ensure_list(data: Any) -> list[Any]:
    if isinstance(data, list):
        return copy.deepcopy(data)
    if data is None:
        return []
    return [copy.deepcopy(data)]


def _normalize_endpoint(endpoint: str) -> str:
    clean = endpoint.strip()
    if not clean:
        return clean
    if clean.startswith("http://") or clean.startswith("https://"):
        # Keep only path for allowlist matching.
        try:
            from urllib.parse import urlparse

            parsed = urlparse(clean)
            clean = parsed.path or clean
        except Exception:
            pass
    return clean if clean.startswith("/") else f"/{clean}"


def _forbidden_endpoint_reason(endpoint: str) -> str | None:
    normalized = _normalize_endpoint(endpoint).lower()
    explicit = {item.lower() for item in FORBIDDEN_ENDPOINTS}
    if normalized in explicit:
        return "hard forbidden account/order endpoint"
    for marker in FORBIDDEN_ENDPOINT_MARKERS:
        if marker in normalized:
            return f"hard forbidden endpoint marker {marker}"
    return None


def _forbidden_state_key_hits(value: Any, *, prefix: str = "") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            normalized = key_text.lower().replace("-", "_")
            compact = _compact_key(key_text)
            forbidden_compact = {item.replace("_", "") for item in FORBIDDEN_STATE_KEY_NAMES}
            if normalized in FORBIDDEN_STATE_KEY_NAMES or compact in forbidden_compact:
                if compact in {"realorder", "realorders"} and child is False:
                    pass
                else:
                    hits.append(path)
            hits.extend(_forbidden_state_key_hits(child, prefix=path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(_forbidden_state_key_hits(child, prefix=f"{prefix}[{index}]" if prefix else f"[{index}]"))
    return hits


def _signed_timestamp_hits(value: Any, *, prefix: str = "", signed_context: bool = False) -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        compact_keys = {_compact_key(key): key for key in value}
        current_signed_context = signed_context or any(
            compact in SIGNED_TIMESTAMP_CONTEXT_KEYS and value.get(original) is not False
            for compact, original in compact_keys.items()
        )
        for key, child in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if _compact_key(key_text) == "timestamp" and current_signed_context:
                hits.append(path)
            hits.extend(_signed_timestamp_hits(child, prefix=path, signed_context=current_signed_context))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(_signed_timestamp_hits(child, prefix=f"{prefix}[{index}]" if prefix else f"[{index}]", signed_context=signed_context))
    return hits


def _credential_key_hits(value: Any, *, prefix: str = "") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            normalized = key_text.lower().replace("-", "_")
            compact = _compact_key(key_text)
            if any(fragment in normalized for fragment in CREDENTIAL_KEY_FRAGMENTS) or any(
                fragment in compact for fragment in CREDENTIAL_KEY_COMPACT_FRAGMENTS
            ):
                # Schema/safety flags are allowed only as explicit false.
                if normalized in {"requires_signature", "signed", "signed_requests", "reads_api_keys", "read_api_keys"} and child is False:
                    pass
                else:
                    hits.append(path)
            hits.extend(_credential_key_hits(child, prefix=path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(_credential_key_hits(child, prefix=f"{prefix}[{index}]" if prefix else f"[{index}]"))
    return hits


def _compact_key(key: Any) -> str:
    return str(key).lower().replace("-", "_").replace("_", "")


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(item) for item in values if str(item)))


def _error(code: str, message: str, *, index: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "kind": "validation", "message": message, "retryable": False}
    if index is not None:
        payload["index"] = index
    return payload


def _warning(code: str, message: str, *, index: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if index is not None:
        payload["index"] = index
    return payload


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _top_provenance(context: dict[str, Any]) -> dict[str, Any]:
    raw_provenance = context.get("provenance") if isinstance(context, dict) else None
    provenance = copy.deepcopy(raw_provenance) if isinstance(raw_provenance, dict) else {}
    provenance.setdefault("source_manifest", DEFAULT_SOURCE_MANIFEST)
    return provenance


def _safety_boundary() -> dict[str, bool]:
    return {
        "public_readonly_market_data": True,
        "paper_or_watch_only": True,
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "binance_account_state": False,
    }
