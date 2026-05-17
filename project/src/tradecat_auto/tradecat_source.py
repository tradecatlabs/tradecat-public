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


def parse_event_stream_payload(payload: dict[str, Any]) -> dict[str, Any]:
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
    rows = payload.get("rows") if isinstance(payload, dict) else []
    symbols: OrderedDict[str, dict[str, Any]] = OrderedDict()
    rejected: list[dict[str, Any]] = []
    if isinstance(rows, list):
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            raw_symbol = _raw_symbol_from_row(row)
            if not raw_symbol:
                continue
            normalized = normalize_to_usdt_perp_symbol(raw_symbol, tradable_symbols)
            if not normalized:
                rejected.append(
                    {
                        "row_index": index,
                        "raw_symbol": raw_symbol,
                        "reason": "not_in_tradable_usdt_perp_universe",
                    }
                )
                continue
            symbols.setdefault(
                normalized,
                {
                    "raw_symbol": raw_symbol,
                    "normalized_symbol": normalized,
                    "first_row_index": index,
                    "source_dataset_key": str(payload.get("dataset_key") or "anomaly_panel"),
                    "source_values": row,
                },
            )
    return {
        "schema": "tradecat_auto.anomaly_symbols.v1",
        "schema_version": "1.0.0",
        "ok": bool(symbols),
        "source_schema": payload.get("schema"),
        "source_dataset_key": payload.get("dataset_key", "anomaly_panel"),
        "symbols": list(symbols.values()),
        "rejected": rejected,
    }


def _raw_symbol_from_row(row: dict[str, Any]) -> str:
    for key in ("交易对", "合约代码", "币种符号", "symbol", "Symbol", "SYMBOL"):
        value = str(row.get(key) or "").strip()
        if value:
            return value.upper()
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

    def fetch_anomaly_symbols(self, *, tradable_symbols: set[str], limit: int = 20) -> dict[str, Any]:
        return parse_anomaly_symbols(self.request_dataset("anomaly_panel", limit=limit), tradable_symbols=tradable_symbols)
