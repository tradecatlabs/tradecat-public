from __future__ import annotations

import os
from decimal import Decimal
from functools import lru_cache
from typing import Any, Iterable

from psycopg import sql
from psycopg.rows import dict_row

from src.query.datasources import INDICATORS, get_pool
from src.query.filters import drop_placeholder_rows
from src.query.time import parse_ts_any
from src.utils.symbol import normalize_symbol


def _indicator_schema() -> str:
    return (os.environ.get("INDICATOR_PG_SCHEMA") or "tg_cards").strip() or "tg_cards"


def _normalize_period_value(period: str) -> str:
    p = (period or "").strip().lower()
    if p in ("24h", "1day"):
        return "1d"
    return p


def _period_candidates(period: str) -> list[str]:
    target = _normalize_period_value(period)
    return list({target, target.upper(), period, period.lower(), period.upper()})


def _normalize_table_name(name: str) -> str:
    n = (name or "").strip()
    if not n:
        raise ValueError("empty_table")
    if n in ("基础数据", "基础数据同步器"):
        return "基础数据同步器.py"
    if not n.endswith(".py"):
        return f"{n}.py"
    return n


@lru_cache(maxsize=512)
def _table_columns(schema: str, table: str) -> list[str]:
    table = _normalize_table_name(table)
    pool = get_pool(INDICATORS)
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema=%s AND table_name=%s
                ORDER BY ordinal_position
                """,
                (schema, table),
            )
            return [str(r[0]) for r in (cur.fetchall() or [])]


def _pick_ts_col(cols: Iterable[str]) -> str | None:
    for c in ("数据时间", "时间", "timestamp"):
        if c in cols:
            return c
    return None


def _pick_symbol_col(cols: Iterable[str]) -> str | None:
    for c in ("交易对", "币种", "symbol"):
        if c in cols:
            return c
    return None


def _period_cols(cols: Iterable[str]) -> list[str]:
    out: list[str] = []
    for c in cols:
        if str(c).lower() in ("周期", "period", "interval"):
            out.append(str(c))
    return out


def _build_period_where(period_cols: list[str], period: str, params: list[object]) -> sql.Composed | None:
    if not period_cols:
        return None
    vals = _period_candidates(period)
    sub: list[sql.Composed] = []
    for c in period_cols:
        sub.append(sql.SQL("{} = ANY(%s)").format(sql.Identifier(c)))
        params.append(vals)
    return sql.SQL("(") + sql.SQL(" OR ").join(sub) + sql.SQL(")")


def _build_symbols_where(sym_col: str | None, symbols: list[str] | None, params: list[object]) -> sql.Composed | None:
    if not sym_col or not symbols:
        return None
    vals = sorted({s.strip().upper() for s in symbols if s and s.strip()})
    if not vals:
        return None
    params.append(vals)
    return sql.SQL("upper({}) = ANY(%s)").format(sql.Identifier(sym_col))


def _build_symbol_where(cols: list[str], symbol: str, params: list[object]) -> sql.Composed | None:
    if not symbol:
        return None
    raw = (symbol or "").strip().upper()
    if not raw:
        return None
    sym_full = raw if raw.endswith("USDT") else raw + "USDT"
    sym_base = raw.replace("USDT", "")

    sub: list[sql.Composed] = []
    if "交易对" in cols:
        sub.append(
            sql.SQL("(upper({})=%s OR replace(upper({}),'USDT','')=%s)").format(
                sql.Identifier("交易对"),
                sql.Identifier("交易对"),
            )
        )
        params.extend([sym_full, sym_base])
    if "币种" in cols:
        sub.append(sql.SQL("upper({})=%s").format(sql.Identifier("币种")))
        params.append(sym_base)
    if "symbol" in cols:
        sub.append(sql.SQL("upper({})=%s").format(sql.Identifier("symbol")))
        params.append(sym_base)
    if not sub:
        return None
    return sql.SQL("(") + sql.SQL(" OR ").join(sub) + sql.SQL(")")


def _build_field_nonempty_where(cols: list[str], field: str | None) -> sql.Composed | None:
    f = (field or "").strip()
    if not f:
        return None
    if f not in cols:
        return None
    return sql.SQL("{} IS NOT NULL AND {} != ''").format(sql.Identifier(f), sql.Identifier(f))


def _compose_where(clauses: list[sql.Composed]) -> sql.SQL:
    if not clauses:
        return sql.SQL("")
    return sql.SQL(" WHERE ") + sql.SQL(" AND ").join(clauses)


def fetch_indicator_rows(
    *,
    table: str,
    interval: str | None,
    mode: str,
    symbol: str | None = None,
    symbols: list[str] | None = None,
    field_nonempty: str | None = None,
    limit: int = 1000,
) -> tuple[list[dict[str, Any]], Any]:
    """从指标库（tg_cards.*）读取数据，返回 (rows, latest_ts_value)。"""
    schema = _indicator_schema()
    table = _normalize_table_name(table)
    cols = _table_columns(schema, table)
    if not cols:
        return [], None

    ts_col = _pick_ts_col(cols)
    if not ts_col:
        return [], None
    sym_col = _pick_symbol_col(cols)
    period_cols = _period_cols(cols)

    params: list[object] = []
    clauses: list[sql.Composed] = []

    if interval:
        p = _normalize_period_value(interval)
        if w := _build_period_where(period_cols, p, params):
            clauses.append(w)

    # symbols filter（批量）
    if w := _build_symbols_where(sym_col, symbols, params):
        clauses.append(w)

    # symbol filter（单币种）
    if symbol:
        if w := _build_symbol_where(cols, normalize_symbol(symbol), params):
            clauses.append(w)

    if w := _build_field_nonempty_where(cols, field_nonempty):
        clauses.append(w)

    where_sql = _compose_where(clauses)

    pool = get_pool(INDICATORS)
    tbl = sql.Identifier(schema, table)
    ts_ident = sql.Identifier(ts_col)

    def _normalize_value(v: Any) -> Any:
        if isinstance(v, Decimal):
            return float(v)
        return v

    def _normalize_row(r: dict[str, Any]) -> dict[str, Any]:
        return {k: _normalize_value(v) for k, v in r.items()}

    rows: list[dict[str, Any]] = []
    latest_ts_val: Any = None

    with pool.connection() as conn:
        if mode == "latest_at_max_ts":
            with conn.cursor() as cur:
                cur.execute(sql.SQL("SELECT MAX({}) AS max_ts FROM {}{}").format(ts_ident, tbl, where_sql), params)
                latest_ts_val = (cur.fetchone() or [None])[0]
            if not latest_ts_val:
                return [], None
            where2 = where_sql + (sql.SQL(" AND {}=%s").format(ts_ident) if where_sql.as_string(conn) else sql.SQL(" WHERE {}=%s").format(ts_ident))
            params2 = list(params) + [latest_ts_val]
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql.SQL("SELECT * FROM {}{}").format(tbl, where2), params2)
                rows = [_normalize_row(dict(r)) for r in (cur.fetchall() or [])]

        elif mode == "single_latest":
            if not symbol:
                return [], None
            order_sql = sql.SQL(" ORDER BY {} DESC, ctid DESC LIMIT 1").format(ts_ident)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql.SQL("SELECT * FROM {}{}{}").format(tbl, where_sql, order_sql), params)
                one = cur.fetchone()
                rows = [_normalize_row(dict(one))] if one else []

        elif mode == "raw":
            lim = max(1, min(int(limit), 5000))
            order_sql = sql.SQL(" ORDER BY {} DESC LIMIT %s").format(ts_ident)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql.SQL("SELECT * FROM {}{}{}").format(tbl, where_sql, order_sql), list(params) + [lim])
                rows = [_normalize_row(dict(r)) for r in (cur.fetchall() or [])]

        else:  # latest_per_symbol default
            if not sym_col:
                return [], None
            sym_ident = sql.Identifier(sym_col)
            query = sql.SQL(
                "SELECT DISTINCT ON ({sym}) * FROM {tbl}{where} ORDER BY {sym}, {ts} DESC"
            ).format(sym=sym_ident, tbl=tbl, where=where_sql, ts=ts_ident)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, params)
                rows = [_normalize_row(dict(r)) for r in (cur.fetchall() or [])]

    # 过滤占位行
    key_cols: list[str] = []
    if sym_col:
        key_cols.append(sym_col)
    if period_cols:
        # 优先使用“周期”
        key_cols.append("周期" if "周期" in period_cols else period_cols[0])
    key_cols.append(ts_col)
    rows = drop_placeholder_rows(rows, key_cols=tuple(dict.fromkeys(key_cols)))

    # 计算 latest ts（用于消费端更新时间展示）
    latest_dt = None
    for r in rows:
        dt = parse_ts_any(r.get(ts_col))
        if dt is None:
            continue
        if latest_dt is None or dt > latest_dt:
            latest_dt = dt
    return rows, latest_dt
