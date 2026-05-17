from __future__ import annotations

import re
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tradecat_terminal.contracts import make_error
from tradecat_terminal.dataset_contract import dataset_consumption_contract_summary, load_dataset_consumption_contract
from tradecat_terminal.view_model import build_dataset_view

ANALYSIS_DATASETS = ("event_stream", "anomaly_panel", "market_stats")
DEFAULT_CANDIDATE_LIMIT = 20
_WINDOW_PATTERN = re.compile(r"^(latest|[1-9][0-9]*[hdw])$")


def build_analysis_report(
    cache_dir: Path,
    *,
    analysis_window: str = "24h",
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> dict[str, Any]:
    """生成本地只读分析报告。

    analysis_report.v1 只做确定性的观察归纳，不做交易评分、回测或自动执行。
    """
    window = _normalize_window(analysis_window)
    if candidate_limit < 1:
        raise ValueError("--limit 必须大于 0")

    contracts = load_dataset_consumption_contract()
    dataset_contracts = contracts.get("datasets") if isinstance(contracts.get("datasets"), dict) else {}
    views = {dataset_key: build_dataset_view(cache_dir, dataset_key) for dataset_key in ANALYSIS_DATASETS}
    freshness = [
        _dataset_freshness(dataset_key, views[dataset_key], _contract_for(dataset_contracts, dataset_key))
        for dataset_key in ANALYSIS_DATASETS
    ]
    ready_views = {dataset_key: view for dataset_key, view in views.items() if _rows(view)}
    generated_at = _now_iso()
    base = {
        "generated_at": generated_at,
        "analysis_window": {
            "requested": window,
            "mode": "latest_cached",
            "dataset_keys": list(ANALYSIS_DATASETS),
            "note": "analysis_report.v1 reads only the latest local cache projections; it does not fetch network data.",
        },
        "dataset_freshness": freshness,
        "observations": [],
        "candidate_symbols": [],
        "evidence": [],
        "risk_flags": _base_risk_flags(),
        "limitations": _base_limitations(),
    }

    if not ready_views:
        return {
            **base,
            "ok": False,
            "error": make_error(
                "本地缓存没有可分析的数据集。",
                code="empty_analysis_cache",
                kind="local_state",
                hint="先运行 bash scripts/run-tradecat.sh doctor --sync --timeout 10 或 sync-all --json 预热本地缓存。",
                retryable=True,
            ),
        }

    evidence: list[dict[str, Any]] = []
    observations = _build_observations(ready_views, dataset_contracts, evidence)
    candidates = _build_candidate_symbols(ready_views, dataset_contracts, evidence, limit=candidate_limit)
    risk_flags = [*base["risk_flags"], *_cache_risk_flags(freshness, candidates)]

    return {
        **base,
        "ok": True,
        "observations": observations,
        "candidate_symbols": candidates,
        "evidence": evidence,
        "risk_flags": risk_flags,
    }


def _normalize_window(value: str) -> str:
    text = str(value or "").strip().lower()
    if not _WINDOW_PATTERN.fullmatch(text):
        raise ValueError("--window 必须是 latest 或形如 24h、7d、4w 的窗口")
    return text


def _build_observations(
    views: dict[str, dict[str, Any]],
    dataset_contracts: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    if "event_stream" in views:
        observations.append(_event_stream_observation(views["event_stream"], dataset_contracts, evidence))
    if "anomaly_panel" in views:
        observations.append(_anomaly_panel_observation(views["anomaly_panel"], dataset_contracts, evidence))
    if "market_stats" in views:
        observations.append(_market_stats_observation(views["market_stats"], dataset_contracts, evidence))
    return observations


def _event_stream_observation(
    view: dict[str, Any],
    dataset_contracts: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = _rows(view)
    contract = _contract_for(dataset_contracts, "event_stream")
    time_column = str((contract.get("time_semantics") or {}).get("event_time_column") or "")
    non_empty_times = [_value(row, [time_column]) for row in rows if time_column and _value(row, [time_column])]
    row_evidence = [_row_evidence("event_stream", row, contract, view, kind="event") for row in rows[:5]]
    evidence.extend(row_evidence)
    return {
        "id": "event_stream.activity",
        "dataset_key": "event_stream",
        "kind": "stream_activity",
        "severity": "info",
        "summary": f"event_stream 本地缓存包含 {len(rows)} 条事件观察。",
        "metrics": {
            "row_count": len(rows),
            "sampled_evidence_count": len(row_evidence),
        },
        "time_bounds": {
            "first_observed_event_time": non_empty_times[0] if non_empty_times else "",
            "last_observed_event_time": non_empty_times[-1] if non_empty_times else "",
        },
        "evidence_ids": [item["id"] for item in row_evidence],
    }


def _anomaly_panel_observation(
    view: dict[str, Any],
    dataset_contracts: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = _rows(view)
    contract = _contract_for(dataset_contracts, "anomaly_panel")
    symbols = OrderedDict[str, None]()
    for row in rows:
        symbol = _symbol_from_row(row, contract)
        if symbol:
            symbols.setdefault(symbol, None)
    row_evidence = [_row_evidence("anomaly_panel", row, contract, view, kind="anomaly") for row in rows[:10]]
    evidence.extend(row_evidence)
    return {
        "id": "anomaly_panel.candidates",
        "dataset_key": "anomaly_panel",
        "kind": "anomaly_presence",
        "severity": "info",
        "summary": f"anomaly_panel 本地缓存暴露 {len(symbols)} 个去重候选标的。",
        "metrics": {
            "row_count": len(rows),
            "candidate_symbol_count": len(symbols),
            "sampled_evidence_count": len(row_evidence),
        },
        "evidence_ids": [item["id"] for item in row_evidence],
    }


def _market_stats_observation(
    view: dict[str, Any],
    dataset_contracts: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = _rows(view)
    contract = _contract_for(dataset_contracts, "market_stats")
    windows = [_value(row, ["窗口"]) for row in rows if _value(row, ["窗口"])]
    row_evidence = [_row_evidence("market_stats", row, contract, view, kind="market_context") for row in rows[:5]]
    evidence.extend(row_evidence)
    return {
        "id": "market_stats.context",
        "dataset_key": "market_stats",
        "kind": "market_context",
        "severity": "info",
        "summary": f"market_stats 本地缓存包含 {len(rows)} 条市场上下文汇总。",
        "metrics": {
            "row_count": len(rows),
            "window_count": len(windows),
            "sampled_evidence_count": len(row_evidence),
        },
        "windows": windows[:20],
        "evidence_ids": [item["id"] for item in row_evidence],
    }


def _build_candidate_symbols(
    views: dict[str, dict[str, Any]],
    dataset_contracts: dict[str, Any],
    evidence: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    if "anomaly_panel" not in views:
        return []
    contract = _contract_for(dataset_contracts, "anomaly_panel")
    evidence_by_id = {item["id"]: item for item in evidence}
    candidates: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for row in _rows(views["anomaly_panel"]):
        symbol = _symbol_from_row(row, contract)
        if not symbol:
            continue
        evidence_id = _evidence_id("anomaly_panel", row)
        if evidence_id not in evidence_by_id:
            item = _row_evidence("anomaly_panel", row, contract, views["anomaly_panel"], kind="anomaly")
            evidence.append(item)
            evidence_by_id[item["id"]] = item
        candidate = candidates.setdefault(
            symbol,
            {
                "symbol": symbol,
                "rank": len(candidates) + 1,
                "source_dataset_keys": ["anomaly_panel"],
                "reasons": ["present_in_anomaly_panel"],
                "confidence": "observed",
                "evidence_ids": [],
                "notes": ["候选仅表示在异动面板中被观察到，不代表交易方向或建议。"],
            },
        )
        if evidence_id not in candidate["evidence_ids"]:
            candidate["evidence_ids"].append(evidence_id)
        if len(candidates) >= limit:
            break
    return list(candidates.values())


def _dataset_freshness(dataset_key: str, view: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    rows = _rows(view)
    return {
        "dataset_key": dataset_key,
        "ok": bool(rows),
        "cache_state": "ready" if rows else "empty",
        "row_count": len(rows),
        "fetched_at": str(view.get("fetched_at") or ""),
        "content_hash": str(view.get("content_hash") or ""),
        "data_mode": str(view.get("data_mode") or contract.get("data_mode") or ""),
        "quality_tier": str(contract.get("quality_tier") or ""),
        "time_grain": str(contract.get("time_grain") or ""),
    }


def _row_evidence(
    dataset_key: str,
    row: dict[str, Any],
    contract: dict[str, Any],
    view: dict[str, Any],
    *,
    kind: str,
) -> dict[str, Any]:
    return {
        "id": _evidence_id(dataset_key, row),
        "dataset_key": dataset_key,
        "row_index": int(row.get("row_index") or 0),
        "kind": kind,
        "summary": _evidence_summary(dataset_key, row, contract),
        "values": _contract_values(row, contract),
        "source_columns": _contract_source_columns(contract),
        "fetched_at": str(view.get("fetched_at") or ""),
    }


def _evidence_summary(dataset_key: str, row: dict[str, Any], contract: dict[str, Any]) -> str:
    symbol = _symbol_from_row(row, contract)
    if symbol:
        return f"{dataset_key} row for {symbol}"
    values = row.get("raw_values") if isinstance(row.get("raw_values"), dict) else {}
    first_value = next((str(value).strip() for value in values.values() if str(value).strip()), "")
    return f"{dataset_key} row {int(row.get('row_index') or 0)}" + (f": {first_value[:80]}" if first_value else "")


def _contract_values(row: dict[str, Any], contract: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for field in contract.get("fields") or []:
        if not isinstance(field, dict):
            continue
        name = str(field.get("canonical_name") or "")
        value = _value(row, [str(item) for item in field.get("source_columns") or []])
        if name and value:
            result[name] = value
    return result


def _contract_source_columns(contract: dict[str, Any]) -> list[str]:
    columns: list[str] = []
    for field in contract.get("fields") or []:
        if isinstance(field, dict):
            columns.extend(str(item) for item in field.get("source_columns") or [])
    return _dedupe(columns)


def _symbol_from_row(row: dict[str, Any], contract: dict[str, Any]) -> str:
    columns: list[str] = []
    for field in contract.get("fields") or []:
        if isinstance(field, dict) and field.get("role") == "entity_key":
            columns.extend(str(item) for item in field.get("source_columns") or [])
    value = _value(row, columns)
    return _normalize_symbol(value)


def _value(row: dict[str, Any], columns: list[str]) -> str:
    raw_values = row.get("raw_values") if isinstance(row.get("raw_values"), dict) else {}
    for column in columns:
        value = str(raw_values.get(column) or "").strip()
        if value:
            return value
    return ""


def _rows(view: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in view.get("rows") or [] if isinstance(row, dict) and not _is_header_like_row(row)]


def _is_header_like_row(row: dict[str, Any]) -> bool:
    raw_values = row.get("raw_values") if isinstance(row.get("raw_values"), dict) else {}
    non_empty = {str(key).strip(): str(value).strip() for key, value in raw_values.items() if str(value).strip()}
    return bool(non_empty) and all(key == value for key, value in non_empty.items())


def _contract_for(dataset_contracts: dict[str, Any], dataset_key: str) -> dict[str, Any]:
    contract = dataset_contracts.get(dataset_key)
    if isinstance(contract, dict):
        return contract
    return dataset_consumption_contract_summary(dataset_key)


def _evidence_id(dataset_key: str, row: dict[str, Any]) -> str:
    return f"{dataset_key}:row:{int(row.get('row_index') or 0)}"


def _normalize_symbol(value: str) -> str:
    return value.strip().upper().replace(" ", "")


def _dedupe(values: list[str]) -> list[str]:
    return list(OrderedDict((value, None) for value in values if value))


def _base_risk_flags() -> list[dict[str, str]]:
    return [
        {
            "code": "public_sheet_best_effort",
            "severity": "info",
            "message": "输入数据来自公开 Google Sheets best-effort 缓存，适合研究和摘要，不适合执行级交易自动化。",
        },
        {
            "code": "analysis_not_trading_advice",
            "severity": "warning",
            "message": "analysis_report.v1 只输出观察和证据，不输出买卖建议、仓位建议或自动交易指令。",
        },
    ]


def _cache_risk_flags(freshness: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    missing = [item["dataset_key"] for item in freshness if not item.get("ok")]
    if missing:
        flags.append(
            {
                "code": "partial_analysis_cache",
                "severity": "warning",
                "message": f"以下分析输入缺少本地缓存: {', '.join(missing)}。",
            }
        )
    if not candidates:
        flags.append(
            {
                "code": "no_candidate_symbols",
                "severity": "info",
                "message": "本次本地缓存未暴露可结构化提取的候选标的。",
            }
        )
    return flags


def _base_limitations() -> list[str]:
    return [
        "只读取本地最新缓存，不联网同步；如需新数据，先显式执行 sync 或 doctor --sync。",
        "第一版只归纳 event_stream、anomaly_panel、market_stats 三个数据集。",
        "候选标的来自显式字段语义，不从自由文本中猜测交易对。",
        "报告不包含策略评分、回测、收益预测、买卖建议或自动交易执行语义。",
    ]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
