# ruff: noqa: UP017
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


def _parse_group(col: str) -> str:
    s = str(col or "").strip()
    if "@" not in s:
        return s
    g, _p = s.rsplit("@", 1)
    return g.strip()


def _parse_period(col: str) -> str:
    s = str(col or "").strip()
    if "@" not in s:
        return ""
    _g, p = s.rsplit("@", 1)
    return p.strip()


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _env_csv(key: str, default_csv: str) -> list[str]:
    raw = (os.environ.get(key, "") or "").strip()
    if not raw:
        raw = default_csv
    out: list[str] = []
    for it in raw.split(","):
        s = it.strip()
        if s and s not in out:
            out.append(s)
    return out


def inject_base_card_and_dedup(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    目标：
    - 将“每个卡片都重复出现的基础字段”抽到一个新的“基础数据”卡片（置顶）
    - 其它卡片去掉这些基础字段列，减少重复

    说明：
    - 仅对 dashboard 展示面生效（payload dict 级别处理）
    - 不改 card_key（幂等键与事实层无关）
    """
    enabled = (os.environ.get("SHEETS_DEDUP_BASE_FIELDS", "1") or "1").strip() != "0"
    if not enabled:
        return payloads

    base_groups_list = _env_csv(
        "SHEETS_BASE_FIELD_GROUPS",
        # 默认：这些字段在多数排行榜卡片里重复出现（属于“基础行情字段”）
        "成交额,振幅,成交笔数,主动买卖比,价格",
    )
    base_groups = set(base_groups_list)
    if not base_groups_list:
        return payloads

    periods_order = _env_csv("SHEETS_BASE_PERIODS", "1m,5m,15m,1h,4h,1d,1w")
    periods_set = set(periods_order)

    # 过滤出“有表格”的卡片
    tabular = [p for p in payloads if isinstance((p.get("table") or {}).get("columns"), list)]
    if not tabular:
        return payloads

    # symbol column（约定：多周期表第 1 列）
    symbol_col = "币种"
    try:
        cols0 = (tabular[0].get("table") or {}).get("columns") or []
        if cols0:
            symbol_col = str(cols0[0] or "币种").strip() or "币种"
    except Exception:
        symbol_col = "币种"

    # 收集基础字段值：symbol -> col_key -> value
    by_symbol: dict[str, dict[str, str]] = {}
    symbol_order: list[str] = []

    def touch_symbol(sym: str) -> None:
        s = (sym or "").strip()
        if not s:
            return
        if s not in by_symbol:
            by_symbol[s] = {}
        if s not in symbol_order:
            symbol_order.append(s)

    # 先按第一张卡片的行顺序确定 symbol_order（展示更稳定）
    try:
        rows0 = (tabular[0].get("table") or {}).get("rows") or []
        for r in rows0:
            if not isinstance(r, dict):
                continue
            touch_symbol(str(r.get(symbol_col) or r.get("币种") or r.get("symbol") or ""))
    except Exception:
        pass

    # 扫所有卡片，补齐基础字段
    present_cols: set[str] = set()
    for p in tabular:
        cols = ((p.get("table") or {}).get("columns") or []) if isinstance(p.get("table"), dict) else []
        cols = [str(c) for c in cols if c is not None]
        present_cols.update(cols)

        rows = (p.get("table") or {}).get("rows") or []
        for r in rows:
            if not isinstance(r, dict):
                continue
            sym = str(r.get(symbol_col) or r.get("币种") or r.get("symbol") or "").strip()
            if not sym:
                continue
            touch_symbol(sym)
            bucket = by_symbol[sym]
            for c in cols:
                if c == symbol_col:
                    continue
                g = _parse_group(c)
                if g not in base_groups:
                    continue
                period = _parse_period(c)
                if period and periods_set and period not in periods_set:
                    continue
                v = r.get(c)
                if v is None or v == "":
                    continue
                bucket[c] = str(v)

    # 只保留“实际存在”的 base 列
    base_cols: list[str] = [symbol_col]
    for g in base_groups_list:
        # non-multi（无 @）也支持：只出现一次
        if g in present_cols:
            base_cols.append(g)
        for per in periods_order:
            key = f"{g}@{per}"
            if key in present_cols:
                base_cols.append(key)

    # 若工作簿里实际没有任何基础列（比如卡片没启用这些字段），直接返回
    if len(base_cols) <= 1:
        return payloads

    base_rows: list[dict[str, Any]] = []
    for sym in symbol_order:
        row: dict[str, Any] = {symbol_col: sym}
        vals = by_symbol.get(sym) or {}
        for c in base_cols[1:]:
            row[c] = vals.get(c, "")
        base_rows.append(row)

    # 生成“基础数据”卡片（置顶）
    first = tabular[0]
    update_time = str(
        ((first.get("header") or {}) if isinstance(first.get("header"), dict) else {}).get("update_time") or "-"
    )
    last_update = str(
        ((first.get("params") or {}) if isinstance(first.get("params"), dict) else {}).get("last_update") or "-"
    )
    base_payload: dict[str, Any] = {
        "schema_version": 1,
        "card_key": f"cards:base_fields:{_now_utc_iso()}",
        "ts_utc": _now_utc_iso(),
        "source_service": "sheets-service",
        "card_type": "base_fields",
        "header": {
            "title": "🧱 基础数据（去重汇总）",
            "update_time": update_time,
            "sort_desc": "仅展示公共字段",
        },
        "params": {"last_update": last_update},
        "hint": {"text": f"从各排行榜卡片中提取并去重：{','.join(sorted(base_groups))}"},
        "table": {"columns": base_cols, "rows": base_rows},
        "tg": {"url": ""},
        "raw": {"telegram_text_full": "", "payload_json_full": {"note": "synthetic_base_fields"}},
    }

    # 对其它卡片去重：移除 base_groups 的列（保留 symbol_col）
    out: list[dict[str, Any]] = [base_payload]
    for p in payloads:
        table = p.get("table")
        if not isinstance(table, dict):
            out.append(p)
            continue
        cols = table.get("columns")
        rows = table.get("rows")
        if not isinstance(cols, list) or not isinstance(rows, list):
            out.append(p)
            continue

        keep_cols: list[str] = []
        drop_cols: set[str] = set()
        for c0 in cols:
            c = "" if c0 is None else str(c0)
            if c == symbol_col:
                keep_cols.append(c)
                continue
            g = _parse_group(c)
            if g in base_groups:
                drop_cols.add(c)
                continue
            keep_cols.append(c)

        if not drop_cols:
            out.append(p)
            continue

        new_rows: list[dict[str, Any]] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            nr = dict(r)
            for dc in drop_cols:
                nr.pop(dc, None)
            new_rows.append(nr)

        np = dict(p)
        np["table"] = {"columns": keep_cols, "rows": new_rows}
        out.append(np)

    return out
