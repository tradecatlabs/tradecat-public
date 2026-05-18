from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections import OrderedDict
from pathlib import Path
from typing import Any

from tradecat_auto.binance_market import normalize_to_usdt_perp_symbol


def _default_tradecat_public_root() -> Path:
    explicit = os.environ.get("TRADECAT_PUBLIC_ROOT")
    if explicit:
        return Path(explicit).expanduser()
    # Source layout inside tradecat-public:
    # project/src/tradecat_auto/tradecat_source.py -> tradecat-public root.
    return Path(__file__).resolve().parents[3]


DEFAULT_TRADECAT_PUBLIC = _default_tradecat_public_root()


def event_id_for(source_time_bj: str, content: str) -> str:
    material = f"{str(source_time_bj).strip()}\n{str(content).strip()}".encode()
    return hashlib.sha256(material).hexdigest()


def anomaly_event_id_for(anomaly_symbol: dict[str, Any]) -> str:
    source_values = anomaly_symbol.get("source_values") if isinstance(anomaly_symbol.get("source_values"), dict) else {}
    material = {
        "source_dataset_key": str(anomaly_symbol.get("source_dataset_key") or "anomaly_panel"),
        "normalized_symbol": str(anomaly_symbol.get("normalized_symbol") or "").upper().strip(),
        "raw_symbol": str(anomaly_symbol.get("raw_symbol") or "").upper().strip(),
        "row_index": anomaly_symbol.get("first_row_index") or anomaly_symbol.get("row_index"),
        "source_values": source_values,
    }
    return hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def signal_flow_event_id_for(row: dict[str, Any], *, row_index: int = 0, normalized_symbol: str = "") -> str:
    material = _signal_flow_event_key_material(row, normalized_symbol=normalized_symbol)
    return hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def anomaly_signal_event_for(anomaly_symbol: dict[str, Any]) -> dict[str, Any]:
    source_values = anomaly_symbol.get("source_values") if isinstance(anomaly_symbol.get("source_values"), dict) else {}
    symbol = str(anomaly_symbol.get("normalized_symbol") or anomaly_symbol.get("raw_symbol") or "").upper().strip()
    row_index = anomaly_symbol.get("first_row_index") or anomaly_symbol.get("row_index")
    return {
        "schema": "tradecat_auto.anomaly_signal_event.v1",
        "schema_version": "1.0.0",
        "event_id": anomaly_event_id_for(anomaly_symbol),
        "source_dataset_key": str(anomaly_symbol.get("source_dataset_key") or "anomaly_panel"),
        "row_index": row_index,
        "source_time_bj": _source_time_from_row(source_values),
        "symbol": symbol,
        "raw_symbol": str(anomaly_symbol.get("raw_symbol") or "").upper().strip(),
        "content": _anomaly_content(symbol, source_values),
        "source_values": source_values,
    }


def signal_flow_event_for(row: dict[str, Any], *, row_index: int = 0, normalized_symbol: str = "") -> dict[str, Any]:
    raw_symbol = _raw_symbol_from_row(row)
    symbol = str(normalized_symbol or raw_symbol).upper().strip()
    return {
        "schema": "tradecat_auto.signal_flow_event.v1",
        "schema_version": "1.0.0",
        "event_id": signal_flow_event_id_for(row, row_index=row_index, normalized_symbol=symbol),
        "source_dataset_key": "signal_flow",
        "source_dataset_keys": ["signal_flow"],
        "row_index": row_index,
        "source_time_bj": _source_time_from_row(row),
        "symbol": symbol,
        "raw_symbol": raw_symbol,
        "period": str(row.get("周期") or "").strip(),
        "signal_type": str(row.get("类型") or "").strip(),
        "content": _signal_flow_content(symbol, row),
        "source_values": row,
    }


def anomaly_signal_events_payload(anomaly_symbols: dict[str, Any], *, selected_symbol: str = "") -> dict[str, Any]:
    source_rows = anomaly_symbols.get("symbols") if isinstance(anomaly_symbols, dict) else []
    rows = source_rows if isinstance(source_rows, list) else []
    selected = str(selected_symbol or "").upper().strip()
    events = [
        anomaly_signal_event_for(item)
        for item in rows
        if isinstance(item, dict)
        and (not selected or str(item.get("normalized_symbol") or "").upper().strip() == selected)
    ]
    if selected and not events:
        events = [
            anomaly_signal_event_for(item)
            for item in rows[:1]
            if isinstance(item, dict)
        ]
    return {
        "schema": "tradecat_auto.anomaly_signal_events.v1",
        "schema_version": "1.0.0",
        "ok": bool(events),
        "source_schema": anomaly_symbols.get("schema") if isinstance(anomaly_symbols, dict) else None,
        "source_dataset_key": anomaly_symbols.get("source_dataset_key", "anomaly_panel") if isinstance(anomaly_symbols, dict) else "anomaly_panel",
        "events": events,
        "error_code": None if events else _source_error_code(anomaly_symbols) or "no_anomaly_signal_available",
        "error": anomaly_symbols.get("error") if isinstance(anomaly_symbols, dict) else None,
    }


def parse_signal_flow_payload(
    payload: dict[str, Any],
    *,
    tradable_symbols: set[str] | list[str] | tuple[str, ...],
) -> dict[str, Any]:
    if payload.get("ok") is False:
        result = _dataset_error_payload(
            payload,
            dataset_key="signal_flow",
            schema="tradecat_auto.signal_flow_events.v1",
            events_key="events",
        )
        result["rejected"] = []
        result["duplicates"] = []
        result["duplicate_count"] = 0
        return result
    rows = payload.get("rows") if isinstance(payload, dict) else []
    events_by_id: OrderedDict[str, dict[str, Any]] = OrderedDict()
    rejected: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    if isinstance(rows, list):
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            raw_symbol = _raw_symbol_from_row(row)
            if not raw_symbol:
                continue
            normalized = _normalize_signal_symbol(raw_symbol, tradable_symbols)
            if not normalized:
                rejected.append(
                    {
                        "row_index": index,
                        "raw_symbol": raw_symbol,
                        "reason": "not_in_tradable_usdt_perp_universe",
                    }
                )
                continue
            event = signal_flow_event_for(row, row_index=index, normalized_symbol=normalized)
            event_id = str(event.get("event_id") or "")
            if event_id in events_by_id:
                duplicates.append(
                    {
                        "row_index": index,
                        "first_row_index": events_by_id[event_id].get("row_index"),
                        "event_id": event_id,
                        "raw_symbol": raw_symbol,
                        "normalized_symbol": normalized,
                        "reason": "duplicate_signal_flow_event",
                    }
                )
                continue
            events_by_id[event_id] = event
    events = list(events_by_id.values())
    return {
        "schema": "tradecat_auto.signal_flow_events.v1",
        "schema_version": "1.0.0",
        "ok": bool(events),
        "source_schema": payload.get("schema"),
        "source_dataset_key": payload.get("dataset_key", "signal_flow"),
        "events": events,
        "rejected": rejected,
        "duplicates": duplicates,
        "duplicate_count": len(duplicates),
        "error_code": None if events else _source_error_code(payload) or "no_signal_flow_available",
        "error": payload.get("error") if isinstance(payload, dict) else None,
    }


def signal_events_payload(
    signal_flow_events: dict[str, Any],
    anomaly_symbols: dict[str, Any],
    *,
    selected_symbol: str = "",
) -> dict[str, Any]:
    selected = str(selected_symbol or "").upper().strip()
    source_events = signal_flow_events.get("events") if isinstance(signal_flow_events, dict) else []
    signal_events = [
        _attach_related_anomaly_panel(item, anomaly_symbols)
        for item in source_events
        if isinstance(item, dict)
        and (not selected or str(item.get("symbol") or "").upper().strip() == selected)
    ] if isinstance(source_events, list) else []
    if signal_events:
        return {
            "schema": "tradecat_auto.signal_events.v1",
            "schema_version": "1.0.0",
            "ok": True,
            "source_schema": signal_flow_events.get("schema") if isinstance(signal_flow_events, dict) else None,
            "source_dataset_key": "signal_flow",
            "source_dataset_keys": _dedupe(
                [source for event in signal_events for source in _string_list(event.get("source_dataset_keys"))]
            ),
            "events": signal_events,
            "input_sources": {
                "signal_flow": {
                    "ok": bool(signal_flow_events.get("ok")) if isinstance(signal_flow_events, dict) else False,
                    "count": len(source_events) if isinstance(source_events, list) else 0,
                    "rejected_count": len(signal_flow_events.get("rejected") or []) if isinstance(signal_flow_events, dict) else 0,
                    "duplicate_count": _duplicate_count(signal_flow_events) if isinstance(signal_flow_events, dict) else 0,
                },
                "anomaly_panel": {
                    "ok": bool(anomaly_symbols.get("ok")) if isinstance(anomaly_symbols, dict) else False,
                    "count": len(anomaly_symbols.get("symbols") or []) if isinstance(anomaly_symbols, dict) else 0,
                    "rejected_count": len(anomaly_symbols.get("rejected") or []) if isinstance(anomaly_symbols, dict) else 0,
                },
            },
            "error_code": None,
            "error": None,
        }
    return anomaly_signal_events_payload(anomaly_symbols, selected_symbol=selected_symbol)


def parse_event_stream_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("ok") is False:
        return _dataset_error_payload(payload, dataset_key="event_stream", schema="tradecat_auto.sheet_events.v1", events_key="events")
    rows = payload.get("rows") if isinstance(payload, dict) else []
    events: list[dict[str, Any]] = []
    if isinstance(rows, list):
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            source_time = str(row.get("时间(北京)") or row.get("time") or row.get("source_time_bj") or "").strip()
            content = str(row.get("内容") or row.get("content") or "").strip()
            if not source_time or not content:
                continue
            events.append(
                {
                    "schema": "tradecat_auto.sheet_event.v1",
                    "schema_version": "1.0.0",
                    "event_id": event_id_for(source_time, content),
                    "source_dataset_key": str(payload.get("dataset_key") or "event_stream"),
                    "row_index": index,
                    "source_time_bj": source_time,
                    "content": content,
                }
            )
    return {
        "schema": "tradecat_auto.sheet_events.v1",
        "schema_version": "1.0.0",
        "ok": bool(events),
        "source_schema": payload.get("schema"),
        "source_dataset_key": payload.get("dataset_key", "event_stream"),
        "events": events,
    }


def parse_anomaly_symbols(payload: dict[str, Any], *, tradable_symbols: set[str] | list[str] | tuple[str, ...]) -> dict[str, Any]:
    if payload.get("ok") is False:
        result = _dataset_error_payload(
            payload,
            dataset_key="anomaly_panel",
            schema="tradecat_auto.anomaly_symbols.v1",
            events_key="symbols",
        )
        result["rejected"] = []
        return result
    rows = payload.get("rows") if isinstance(payload, dict) else []
    symbols: OrderedDict[str, dict[str, Any]] = OrderedDict()
    symbol_rows: list[dict[str, Any]] = []
    section_counts: OrderedDict[str, int] = OrderedDict()
    rejected: list[dict[str, Any]] = []
    if isinstance(rows, list):
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            raw_symbol = _raw_symbol_from_row(row)
            if not raw_symbol:
                continue
            row_index = _source_row_index(row, fallback=index)
            section = _anomaly_section(row)
            normalized = normalize_to_usdt_perp_symbol(raw_symbol, tradable_symbols)
            if not normalized:
                rejected.append(
                    {
                        "row_index": row_index,
                        "raw_symbol": raw_symbol,
                        "section": section,
                        "reason": "not_in_tradable_usdt_perp_universe",
                    }
                )
                continue
            item = {
                "raw_symbol": raw_symbol,
                "normalized_symbol": normalized,
                "first_row_index": row_index,
                "row_index": row_index,
                "section": section,
                "source_dataset_key": str(payload.get("dataset_key") or "anomaly_panel"),
                "source_values": row,
            }
            symbol_rows.append(item)
            section_counts[section or ""] = int(section_counts.get(section or "") or 0) + 1
            symbols.setdefault(normalized, item)
    return {
        "schema": "tradecat_auto.anomaly_symbols.v1",
        "schema_version": "1.0.0",
        "ok": bool(symbols),
        "source_schema": payload.get("schema"),
        "source_dataset_key": payload.get("dataset_key", "anomaly_panel"),
        "symbols": list(symbols.values()),
        "rows": symbol_rows,
        "sections": [{"name": name, "row_count": count} for name, count in section_counts.items() if name],
        "rejected": rejected,
    }


def _dataset_error_payload(payload: dict[str, Any], *, dataset_key: str, schema: str, events_key: str) -> dict[str, Any]:
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    code = str(error.get("code") or payload.get("error_code") or "source_unavailable")
    return {
        "schema": schema,
        "schema_version": "1.0.0",
        "ok": False,
        "source_schema": payload.get("schema"),
        "source_dataset_key": payload.get("dataset_key", dataset_key),
        "error_code": code,
        "error": error or payload.get("error") or "source_unavailable",
        events_key: [],
    }


def _raw_symbol_from_row(row: dict[str, Any]) -> str:
    for key in ("交易对", "合约代码", "币种符号", "symbol", "Symbol", "SYMBOL"):
        value = str(row.get(key) or "").strip()
        if value:
            return value.upper()
    return ""


def _source_row_index(row: dict[str, Any], *, fallback: int) -> int:
    for key in ("源行号", "row_index", "行号"):
        try:
            value = int(float(str(row.get(key) or "").strip()))
        except ValueError:
            continue
        if value > 0:
            return value
    return fallback


def _signal_flow_event_key_material(row: dict[str, Any], *, normalized_symbol: str = "") -> dict[str, Any]:
    return {
        "source_dataset_key": "signal_flow",
        "normalized_symbol": str(normalized_symbol or _raw_symbol_from_row(row)).upper().strip(),
        "source_time_bj": _source_time_from_row(row),
        "period": _row_text(row, "周期", "period", "timeframe", "interval"),
        "signal_type": _row_text(row, "类型", "type", "signal_type"),
        "content": _row_text(row, "内容", "content", "message", "text"),
    }


def _row_text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _anomaly_section(row: dict[str, Any]) -> str:
    for key in ("榜单", "榜单名", "section", "board"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _source_time_from_row(row: dict[str, Any]) -> str:
    for key in ("时间(北京)", "更新时间", "时间", "time", "source_time_bj", "updated_at", "timestamp"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _normalize_signal_symbol(raw_symbol: str, tradable_symbols: set[str] | list[str] | tuple[str, ...]) -> str | None:
    tradable = {str(item).upper().strip() for item in tradable_symbols if str(item).strip()}
    if tradable:
        return normalize_to_usdt_perp_symbol(raw_symbol, tradable)
    text = str(raw_symbol or "").upper().strip()
    if not text:
        return None
    return text if text.endswith("USDT") else f"{text}USDT"


def _anomaly_content(symbol: str, row: dict[str, Any]) -> str:
    detail = _format_source_values(row) if row else json.dumps(row, ensure_ascii=False, sort_keys=True)
    return f"{symbol} 异动面板信号: {detail}".strip()


def _signal_flow_content(symbol: str, row: dict[str, Any]) -> str:
    detail = _format_source_values(row)
    return f"{symbol} 信号流: {detail}".strip()


def _attach_related_anomaly_panel(event: dict[str, Any], anomaly_symbols: dict[str, Any]) -> dict[str, Any]:
    symbol = str(event.get("symbol") or "").upper().strip()
    related = _find_anomaly_symbol(anomaly_symbols, symbol)
    if not related:
        return event
    source_values = related.get("source_values") if isinstance(related.get("source_values"), dict) else {}
    updated = dict(event)
    source_keys = _string_list(updated.get("source_dataset_keys"))
    source_keys.append(str(related.get("source_dataset_key") or "anomaly_panel"))
    updated["source_dataset_keys"] = _dedupe(source_keys)
    updated["related_anomaly_panel"] = {
        "source_dataset_key": str(related.get("source_dataset_key") or "anomaly_panel"),
        "row_index": related.get("first_row_index") or related.get("row_index"),
        "raw_symbol": str(related.get("raw_symbol") or "").upper().strip(),
        "normalized_symbol": symbol,
        "source_values": source_values,
        "content": _anomaly_content(symbol, source_values),
    }
    updated["content"] = f"{str(event.get('content') or '').strip()} | 关联异动面板: {_format_source_values(source_values)}"
    return updated


def _find_anomaly_symbol(anomaly_symbols: dict[str, Any], symbol: str) -> dict[str, Any] | None:
    rows = anomaly_symbols.get("symbols") if isinstance(anomaly_symbols, dict) else []
    selected = str(symbol or "").upper().strip()
    if isinstance(rows, list):
        for item in rows:
            if isinstance(item, dict) and str(item.get("normalized_symbol") or "").upper().strip() == selected:
                return item
    return None


def _format_source_values(values: dict[str, Any]) -> str:
    pairs = [f"{key}={value}" for key, value in values.items() if str(value or "").strip()]
    return "; ".join(pairs)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [str(value)] if str(value or "") else []


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _duplicate_count(payload: dict[str, Any]) -> int:
    try:
        return int(payload.get("duplicate_count") or 0)
    except (TypeError, ValueError):
        duplicates = payload.get("duplicates") if isinstance(payload.get("duplicates"), list) else []
        return len(duplicates)


def _source_error_code(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    error_code = str(payload.get("error_code") or "").strip()
    if error_code:
        return error_code
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("code") or "").strip()
    return ""


class TradeCatPublicSource:
    def __init__(self, root: Path | str = DEFAULT_TRADECAT_PUBLIC, *, timeout: float = 20.0) -> None:
        self.root = Path(root)
        self.timeout = timeout

    def request_dataset(self, dataset_key: str, *, limit: int = 20) -> dict[str, Any]:
        script = self.root / "project/scripts/request.py"
        command = ["python3", str(script), dataset_key, "--format", "json", "--limit", str(limit)]
        proc = subprocess.run(
            command,
            cwd=self.root,
            text=True,
            capture_output=True,
            timeout=self.timeout,
            check=False,
        )
        if proc.returncode != 0:
            parsed_error = _json_object_from_text(proc.stdout)
            if parsed_error is not None:
                parsed_error.setdefault("returncode", proc.returncode)
                return parsed_error
            return {
                "schema": "tradecat_auto.source_error.v1",
                "schema_version": "1.0.0",
                "ok": False,
                "dataset_key": dataset_key,
                "returncode": proc.returncode,
                "stderr": proc.stderr.strip(),
                "stdout": proc.stdout.strip()[:500],
            }
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            return {
                "schema": "tradecat_auto.source_error.v1",
                "schema_version": "1.0.0",
                "ok": False,
                "dataset_key": dataset_key,
                "returncode": proc.returncode,
                "stderr": f"invalid JSON: {exc}",
                "stdout": proc.stdout.strip()[:500],
            }
        if isinstance(payload, dict):
            return payload
        return {
            "schema": "tradecat_auto.source_error.v1",
            "schema_version": "1.0.0",
            "ok": False,
            "dataset_key": dataset_key,
            "stderr": "request.py returned non-object JSON",
            "stdout": proc.stdout.strip()[:500],
        }

    def fetch_events(self, *, limit: int = 20) -> dict[str, Any]:
        return parse_event_stream_payload(self.request_dataset("event_stream", limit=limit))

    def fetch_signal_flow_events(self, *, tradable_symbols: set[str], limit: int = 20) -> dict[str, Any]:
        return parse_signal_flow_payload(
            self.request_dataset("signal_flow", limit=limit),
            tradable_symbols=tradable_symbols,
        )

    def fetch_anomaly_symbols(self, *, tradable_symbols: set[str], limit: int = 20) -> dict[str, Any]:
        del limit
        return parse_anomaly_symbols(self.request_dataset("anomaly_panel", limit=0), tradable_symbols=tradable_symbols)


def _json_object_from_text(text: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
