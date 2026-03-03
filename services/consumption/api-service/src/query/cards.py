from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Final

from assets.common.contracts.cards_contract import CARD_ID_TO_CONTRACT

from src.query.dao import fetch_indicator_rows
from src.query.time import format_ts_bundle, parse_ts_any


BASE_TABLE: Final[str] = "基础数据同步器.py"

# 不对外暴露的内部列名（会被整形为稳定字段：symbol/interval/updated_at 等）
_BANNED_COLS: Final[set[str]] = {
    "交易对",
    "币种",
    "symbol",
    "周期",
    "period",
    "interval",
    "数据时间",
    "时间",
    "timestamp",
}


def _to_symbol_variants(raw: str) -> tuple[str, str]:
    s = (raw or "").strip().upper()
    if not s:
        return "", ""
    if s.endswith("USDT"):
        return s, s[: -4] or s
    # 兼容：部分表只存 base symbol（BTC）
    return s + "USDT", s


def _pick_symbol(row: dict[str, Any]) -> tuple[str, str]:
    for key in ("交易对", "币种", "symbol"):
        v = row.get(key)
        if v:
            return _to_symbol_variants(str(v))
    return "", ""


def _build_base_map(interval: str, symbols: list[str] | None) -> tuple[dict[str, dict[str, Any]], datetime | None]:
    rows, latest_dt = fetch_indicator_rows(
        table=BASE_TABLE,
        interval=interval,
        mode="latest_at_max_ts",
        symbols=symbols,
        limit=5000,
    )
    m: dict[str, dict[str, Any]] = {}
    for r in rows:
        sym_full, sym_base = _pick_symbol(r)
        if sym_full:
            m[sym_full] = dict(r)
        if sym_base:
            m[sym_base] = dict(r)
    return m, latest_dt


def _merge_base_fields(*, metric_row: dict[str, Any], base_row: dict[str, Any]) -> dict[str, Any]:
    # 与 telegram-service 的 merge 口径保持一致：优先 base，其次 metric
    fields: dict[str, Any] = {}
    fields["price"] = float(base_row.get("当前价格", metric_row.get("当前价格", 0)) or 0)
    fields["quote_volume"] = float(base_row.get("成交额", metric_row.get("成交额", 0)) or 0)
    fields["change_percent"] = float(base_row.get("变化率", 0) or 0)
    fields["updated_at"] = base_row.get("数据时间") or metric_row.get("数据时间")

    # 常见公共字段（如存在则补齐）
    for k in ("振幅", "交易次数", "成交笔数", "主动买入量", "主动卖出量", "主动买额", "主动卖额", "主动买卖比", "成交量"):
        if k in base_row:
            fields[k] = base_row.get(k)
    return fields


def build_card_payload(
    *,
    card_id: str,
    interval: str,
    symbols: list[str] | None,
    limit: int,
) -> dict[str, Any]:
    """按 card_id 读取卡片数据，并输出稳定结构（不泄露内部表名/关键列名）。"""
    contract = CARD_ID_TO_CONTRACT.get(card_id)
    if contract is None:
        raise ValueError("card_not_found")
    if not contract.indicator_table:
        raise ValueError("card_offline")

    now = datetime.now(tz=timezone.utc)
    ts = format_ts_bundle(now)

    # metrics
    table = contract.indicator_table
    mode = "latest_at_max_ts" if table == BASE_TABLE else "latest_per_symbol"
    metric_rows, metric_latest_dt = fetch_indicator_rows(
        table=table,
        interval=interval,
        mode=mode,
        symbols=symbols,
        limit=5000,
    )

    base_map: dict[str, dict[str, Any]] = {}
    base_latest_dt = None
    if contract.merge_base:
        base_map, base_latest_dt = _build_base_map(interval, symbols)

    latest_dt = metric_latest_dt
    if base_latest_dt and (latest_dt is None or base_latest_dt > latest_dt):
        latest_dt = base_latest_dt

    out_rows: list[dict[str, Any]] = []
    for r in metric_rows:
        sym_full, sym_base = _pick_symbol(r)
        if not sym_full and not sym_base:
            continue

        base_row = base_map.get(sym_full) or base_map.get(sym_base) or {}

        fields: dict[str, Any] = {}
        if contract.merge_base:
            fields.update(_merge_base_fields(metric_row=r, base_row=base_row))
        else:
            # base 表自身：也输出稳定的基础字段（减少消费端分支）
            fields.update(_merge_base_fields(metric_row=r, base_row=r))

        # 把指标表的业务字段带上（去掉内部 key）
        for k, v in r.items():
            if k in _BANNED_COLS:
                continue
            if k == "排名":
                continue
            fields[k] = v

        rank_val = r.get("排名")
        try:
            rank = int(rank_val) if rank_val not in (None, "", "-") else None
        except Exception:
            rank = None

        # 为了稳定：symbol 使用 full 形式；同时提供 base_symbol
        out_rows.append(
            {
                "symbol": sym_full or (sym_base + "USDT" if sym_base else ""),
                "base_symbol": sym_base,
                "rank": rank,
                "fields": fields,
            }
        )

    # 排序：优先按 rank（如存在）
    if any(r.get("rank") is not None for r in out_rows):
        out_rows.sort(key=lambda x: (x.get("rank") is None, x.get("rank") or 0))

    # limit
    limit = max(1, min(int(limit), 5000))
    out_rows = out_rows[:limit]

    payload: dict[str, Any] = {
        "ts_utc": ts.ts_utc,
        "ts_ms": ts.ts_ms,
        "ts_shanghai": ts.ts_shanghai,
        "card_id": contract.card_id,
        "title": contract.title,
        "description": contract.description,
        "interval": interval,
        "rows": out_rows,
    }

    if latest_dt:
        lt = format_ts_bundle(latest_dt)
        payload["latest_ts_utc"] = lt.ts_utc
        payload["latest_ts_ms"] = lt.ts_ms
        payload["latest_ts_shanghai"] = lt.ts_shanghai

    # data_freshness：以 updated_at 推导（可能为空）
    freshest = None
    for rr in out_rows:
        dt = parse_ts_any((rr.get("fields") or {}).get("updated_at"))
        if dt and (freshest is None or dt > freshest):
            freshest = dt
    if freshest:
        ft = format_ts_bundle(freshest)
        payload["data_freshness_utc"] = ft.ts_utc

    return payload


__all__ = ["BASE_TABLE", "build_card_payload"]

