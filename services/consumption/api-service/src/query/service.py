from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.query.dao import fetch_indicator_rows
from src.query.time import format_ts_bundle, parse_ts_any


def health_payload(*, sources: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc)
    ts = format_ts_bundle(now)
    return {
        "ts_utc": ts.ts_utc,
        "ts_ms": ts.ts_ms,
        "ts_shanghai": ts.ts_shanghai,
        "sources": sources or [],
    }


def dashboard_payload(*, intervals: list[str], symbols: list[str] | None, shape: str) -> dict[str, Any]:
    """MVP：先返回基础数据（按周期的 latest_at_max_ts）。"""
    now = datetime.now(tz=timezone.utc)
    ts = format_ts_bundle(now)

    base_by_interval: dict[str, list[dict[str, Any]]] = {}
    latest_dt = None
    for itv in intervals:
        rows, dt = fetch_indicator_rows(
            table="基础数据同步器.py",
            interval=itv,
            mode="latest_at_max_ts",
            symbols=symbols,
            limit=5000,
        )
        base_by_interval[itv] = rows
        if dt and (latest_dt is None or dt > latest_dt):
            latest_dt = dt

    data: dict[str, Any] = {
        "ts_utc": ts.ts_utc,
        "ts_ms": ts.ts_ms,
        "ts_shanghai": ts.ts_shanghai,
        "table": "基础数据同步器.py",
        "intervals": intervals,
        "shape": shape,
    }

    if latest_dt:
        latest_ts = format_ts_bundle(latest_dt)
        data["latest_ts_utc"] = latest_ts.ts_utc
        data["latest_ts_ms"] = latest_ts.ts_ms
        data["latest_ts_shanghai"] = latest_ts.ts_shanghai

    if shape == "wide":
        # wide：symbol -> interval -> row
        wide: dict[str, dict[str, dict[str, Any]]] = {}
        for itv, rows in base_by_interval.items():
            for r in rows:
                sym = str(r.get("交易对") or r.get("币种") or r.get("symbol") or "").upper()
                if not sym:
                    continue
                wide.setdefault(sym, {})[itv] = r
        data["rows"] = wide
    else:
        long_rows: list[dict[str, Any]] = []
        for itv, rows in base_by_interval.items():
            for r in rows:
                rr = dict(r)
                rr["interval"] = itv
                long_rows.append(rr)
        data["rows"] = long_rows

    return data


def _merge_with_base(row: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    merged = dict(row)
    merged["price"] = float(base.get("当前价格", row.get("当前价格", 0)) or 0)
    merged["quote_volume"] = float(base.get("成交额", row.get("成交额", 0)) or 0)
    merged["change_percent"] = float(base.get("变化率", 0) or 0)
    merged["updated_at"] = base.get("数据时间") or row.get("数据时间")
    for k in ["振幅", "交易次数", "成交笔数", "主动买入量", "主动卖出量", "主动买额", "主动卖额", "主动买卖比"]:
        if k in base:
            merged[k] = base.get(k)
    return merged


def symbol_snapshot_payload(
    *,
    symbol: str,
    panels: list[str],
    intervals: list[str],
    include_base: bool,
    include_pattern: bool,
    table_fields: dict[str, dict[str, tuple[tuple[str, str], ...]]],
    table_alias: dict[str, dict[str, str]],
) -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc)
    ts = format_ts_bundle(now)
    raw_symbol = (symbol or "").strip().upper()
    base_symbol = raw_symbol.replace("USDT", "")

    snapshot: dict[str, Any] = {
        "ts_utc": ts.ts_utc,
        "ts_ms": ts.ts_ms,
        "ts_shanghai": ts.ts_shanghai,
        "symbol": raw_symbol,
        "base_symbol": base_symbol,
        "panels": {},
    }

    # base rows per interval（用于 merge）
    base_rows: dict[str, dict[str, Any]] = {}
    for itv in intervals:
        rows, _dt = fetch_indicator_rows(
            table="基础数据同步器.py",
            interval=itv,
            mode="single_latest",
            symbol=raw_symbol,
            limit=1,
        )
        base_rows[itv] = rows[0] if rows else {}

    # panels
    for panel in panels:
        tables = table_fields.get(panel, {})
        panel_payload: dict[str, Any] = {"intervals": intervals, "tables": {}}

        for table_display in tables.keys():
            base_table = table_alias.get(panel, {}).get(table_display, table_display)
            table_payload: dict[str, Any] = {
                "table": base_table,
                "fields": [{"id": col_id, "label": label} for col_id, label in tables.get(table_display, ())],
                "intervals": {},
            }
            for itv in intervals:
                rows, _dt = fetch_indicator_rows(
                    table=base_table,
                    interval=itv,
                    mode="single_latest",
                    symbol=raw_symbol,
                    limit=1,
                )
                row0 = rows[0] if rows else {}
                if row0 and base_rows.get(itv):
                    row0 = _merge_with_base(row0, base_rows[itv])
                table_payload["intervals"][itv] = row0
            panel_payload["tables"][table_display] = table_payload

        snapshot["panels"][panel] = panel_payload

    if include_base:
        snapshot["base"] = {"table": "基础数据同步器.py", "intervals": base_rows}

    if include_pattern:
        pattern_rows: dict[str, dict[str, Any]] = {}
        for itv in intervals:
            rows, _dt = fetch_indicator_rows(
                table="K线形态扫描器.py",
                interval=itv,
                mode="single_latest",
                symbol=raw_symbol,
                limit=1,
            )
            row0 = rows[0] if rows else {}
            if row0 and base_rows.get(itv):
                row0 = _merge_with_base(row0, base_rows[itv])
            pattern_rows[itv] = row0
        snapshot["pattern"] = {"table": "K线形态扫描器.py", "intervals": pattern_rows}

    # latest（取 base 的 updated_at 或各 interval 最大）
    latest_dt = None
    for itv, r in base_rows.items():
        dt = parse_ts_any(r.get("数据时间")) if r else None
        if dt and (latest_dt is None or dt > latest_dt):
            latest_dt = dt
    if latest_dt:
        lt = format_ts_bundle(latest_dt)
        snapshot["latest_ts_utc"] = lt.ts_utc
        snapshot["latest_ts_ms"] = lt.ts_ms
        snapshot["latest_ts_shanghai"] = lt.ts_shanghai

    return snapshot

