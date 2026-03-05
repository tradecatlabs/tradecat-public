from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
import os
import threading
import time
from typing import Any

from src.query.cards import build_card_payload
from src.query.dao import fetch_indicator_rows
from src.query.time import format_ts_bundle, parse_ts_any


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class _CacheEntry:
    expires_at: float
    value: Any


_CACHE_LOCK = threading.Lock()
_INFLIGHT_LOCKS: dict[str, threading.Lock] = {}

_DASHBOARD_CACHE: OrderedDict[str, _CacheEntry] = OrderedDict()
_SNAPSHOT_CACHE: OrderedDict[str, _CacheEntry] = OrderedDict()


def _cache_max_entries() -> int:
    return max(16, min(_env_int("QUERY_CACHE_MAX_ENTRIES", 256), 4096))


def _cache_get(cache: OrderedDict[str, _CacheEntry], key: str) -> Any | None:
    now = time.monotonic()
    with _CACHE_LOCK:
        ent = cache.get(key)
        if not ent:
            return None
        if ent.expires_at <= now:
            cache.pop(key, None)
            return None
        cache.move_to_end(key)
        return ent.value


def _cache_set(cache: OrderedDict[str, _CacheEntry], key: str, value: Any, ttl_sec: float) -> None:
    ttl = max(0.0, float(ttl_sec))
    if ttl <= 0:
        return
    now = time.monotonic()
    with _CACHE_LOCK:
        cache[key] = _CacheEntry(expires_at=now + ttl, value=value)
        cache.move_to_end(key)
        max_entries = _cache_max_entries()
        while len(cache) > max_entries:
            evicted, _ = cache.popitem(last=False)
            _INFLIGHT_LOCKS.pop(evicted, None)
        if len(_INFLIGHT_LOCKS) > max_entries * 2:
            _INFLIGHT_LOCKS.clear()


def _get_inflight_lock(key: str) -> threading.Lock:
    with _CACHE_LOCK:
        lock = _INFLIGHT_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _INFLIGHT_LOCKS[key] = lock
        return lock


def _numeric_mode_key() -> str:
    return (os.environ.get("QUERY_NUMERIC_MODE") or "float").strip().lower() or "float"


def health_payload(*, sources: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc)
    ts = format_ts_bundle(now)
    return {
        "ts_utc": ts.ts_utc,
        "ts_ms": ts.ts_ms,
        "ts_shanghai": ts.ts_shanghai,
        "sources": sources or [],
    }


def dashboard_payload(
    *,
    cards: list[str],
    intervals: list[str],
    symbols: list[str] | None,
    shape: str,
    limit: int,
) -> dict[str, Any]:
    """看板聚合输出（多卡片 × 多周期）。

    shape:
    - wide: symbol -> interval -> row
    - long: rows[] 每条带 interval
    """
    ttl_sec = _env_float("QUERY_DASHBOARD_CACHE_TTL_SEC", 2.0)
    cacheable = symbols is None
    cache_key = ""
    if ttl_sec > 0 and cacheable:
        cache_key = (
            f"dashboard|shape={shape}|limit={limit}|numeric={_numeric_mode_key()}|cards={','.join(cards)}|"
            f"intervals={','.join(intervals)}|symbols=*"
        )
        cached = _cache_get(_DASHBOARD_CACHE, cache_key)
        if cached is not None:
            return cached

        lock = _get_inflight_lock(cache_key)
        with lock:
            cached2 = _cache_get(_DASHBOARD_CACHE, cache_key)
            if cached2 is not None:
                return cached2
            out = _dashboard_payload_uncached(cards=cards, intervals=intervals, symbols=symbols, shape=shape, limit=limit)
            _cache_set(_DASHBOARD_CACHE, cache_key, out, ttl_sec=ttl_sec)
            return out

    return _dashboard_payload_uncached(cards=cards, intervals=intervals, symbols=symbols, shape=shape, limit=limit)


def _dashboard_payload_uncached(
    *,
    cards: list[str],
    intervals: list[str],
    symbols: list[str] | None,
    shape: str,
    limit: int,
) -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc)
    ts = format_ts_bundle(now)

    data: dict[str, Any] = {
        "ts_utc": ts.ts_utc,
        "ts_ms": ts.ts_ms,
        "ts_shanghai": ts.ts_shanghai,
        "cards": cards,
        "intervals": intervals,
        "shape": shape,
    }

    latest_dt = None
    out_cards: dict[str, Any] = {}
    for cid in cards:
        per_interval: dict[str, Any] = {}
        for itv in intervals:
            payload = build_card_payload(card_id=cid, interval=itv, symbols=symbols, limit=limit)
            per_interval[itv] = payload

            dt = parse_ts_any(payload.get("latest_ts_utc"))
            if dt and (latest_dt is None or dt > latest_dt):
                latest_dt = dt

        if shape == "wide":
            wide: dict[str, dict[str, Any]] = {}
            for itv, p in per_interval.items():
                for r in (p.get("rows") or []):
                    sym = str(r.get("symbol") or "").upper()
                    if not sym:
                        continue
                    wide.setdefault(sym, {})[itv] = r
            out_cards[cid] = {"card_id": cid, "intervals": intervals, "rows": wide}
        else:
            long_rows: list[dict[str, Any]] = []
            for itv, p in per_interval.items():
                for r in (p.get("rows") or []):
                    rr = dict(r)
                    rr["interval"] = itv
                    long_rows.append(rr)
            out_cards[cid] = {"card_id": cid, "intervals": intervals, "rows": long_rows}

    data["data"] = out_cards

    if latest_dt:
        latest_ts = format_ts_bundle(latest_dt)
        data["latest_ts_utc"] = latest_ts.ts_utc
        data["latest_ts_ms"] = latest_ts.ts_ms
        data["latest_ts_shanghai"] = latest_ts.ts_shanghai

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
    ttl_sec = _env_float("QUERY_SNAPSHOT_CACHE_TTL_SEC", 2.0)
    cache_key = ""
    if ttl_sec > 0:
        cache_key = (
            f"snapshot|symbol={symbol.upper()}|panels={','.join(panels)}|intervals={','.join(intervals)}|"
            f"include_base={int(include_base)}|include_pattern={int(include_pattern)}|numeric={_numeric_mode_key()}"
        )
        cached = _cache_get(_SNAPSHOT_CACHE, cache_key)
        if cached is not None:
            return cached

        lock = _get_inflight_lock(cache_key)
        with lock:
            cached2 = _cache_get(_SNAPSHOT_CACHE, cache_key)
            if cached2 is not None:
                return cached2
            out = _symbol_snapshot_payload_uncached(
                symbol=symbol,
                panels=panels,
                intervals=intervals,
                include_base=include_base,
                include_pattern=include_pattern,
                table_fields=table_fields,
                table_alias=table_alias,
            )
            _cache_set(_SNAPSHOT_CACHE, cache_key, out, ttl_sec=ttl_sec)
            return out

    return _symbol_snapshot_payload_uncached(
        symbol=symbol,
        panels=panels,
        intervals=intervals,
        include_base=include_base,
        include_pattern=include_pattern,
        table_fields=table_fields,
        table_alias=table_alias,
    )


def _symbol_snapshot_payload_uncached(
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
