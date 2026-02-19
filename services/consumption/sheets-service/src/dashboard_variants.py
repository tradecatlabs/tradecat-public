# ruff: noqa: UP017
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PERIODS_DEFAULT = ("1m", "5m", "15m", "1h", "4h", "1d", "1w")


def _parse_period_suffix(col: str) -> str:
    s = str(col or "").strip()
    if "@" not in s:
        return ""
    _field, suf = s.rsplit("@", 1)
    return suf.strip()


def _parse_field_group(col: str) -> str:
    s = str(col or "").strip()
    if "@" not in s:
        return s
    field, _suf = s.rsplit("@", 1)
    return field.strip()


def _symbol_col(columns: list[str]) -> str:
    # 约定：多周期表第 1 列一般是“币种”；但仍做兜底。
    if columns:
        c0 = str(columns[0] or "").strip()
        if c0:
            return c0
    return "币种"


def _periods_in_table(columns: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for c in columns:
        p = _parse_period_suffix(c)
        if p and p not in seen:
            seen.add(p)
            out.append(p)

    # 优先用默认顺序；其余周期按出现顺序追加
    ordered: list[str] = [p for p in PERIODS_DEFAULT if p in seen]
    for p in out:
        if p not in ordered:
            ordered.append(p)
    return ordered


@dataclass(frozen=True)
class VariantTable:
    columns: list[str]
    rows: list[dict[str, Any]]


def compact_cell_multiperiod(*, columns: list[str], rows: list[dict[str, Any]]) -> VariantTable:
    """
    方案1：单元格内多周期（0 交互，纯阅读密度最高）。

    输入：columns 形如 `字段@周期`（多周期横向表）
    输出：
    - columns: [币种] + [字段组...]
    - cell: 每字段组一个单元格，内部用换行列出 7 个周期值（带周期标签）
    """
    cols = [str(c or "").strip() for c in (columns or []) if str(c or "").strip()]
    sym_col = _symbol_col(cols)
    periods = _periods_in_table(cols)

    groups: list[str] = []
    for c in cols:
        if c == sym_col:
            continue
        g = _parse_field_group(c)
        if g and g not in groups:
            groups.append(g)

    out_cols = [sym_col, *groups]
    out_rows: list[dict[str, Any]] = []

    for r in rows or []:
        if not isinstance(r, dict):
            continue
        nr: dict[str, Any] = {sym_col: "" if r.get(sym_col) is None else str(r.get(sym_col))}
        for g in groups:
            # 单周期字段（无 @）直接透传
            if g in r and all((f"{g}@{p}") not in r for p in periods):
                nr[g] = "" if r.get(g) is None else str(r.get(g))
                continue

            lines: list[str] = []
            for p in periods:
                key = f"{g}@{p}"
                v = r.get(key, "")
                vv = "" if v is None else str(v)
                if vv == "":
                    vv = "-"
                lines.append(f"{p} {vv}")
            nr[g] = "\n".join(lines)
        out_rows.append(nr)

    return VariantTable(columns=out_cols, rows=out_rows)


def vertical_multiperiod(*, columns: list[str], rows: list[dict[str, Any]]) -> VariantTable:
    """
    方案3：纵向多周期（0 交互，真表格，可排序/筛选；但更长）。

    输出：
    - columns: [币种, 周期] + [字段组...]
    - rows: 每个币种拆成 7 行，每行一个周期的字段值
    """
    cols = [str(c or "").strip() for c in (columns or []) if str(c or "").strip()]
    sym_col = _symbol_col(cols)
    periods = _periods_in_table(cols)

    groups: list[str] = []
    for c in cols:
        if c == sym_col:
            continue
        g = _parse_field_group(c)
        if g and g not in groups:
            groups.append(g)

    out_cols = [sym_col, "周期", *groups]
    out_rows: list[dict[str, Any]] = []

    for r in rows or []:
        if not isinstance(r, dict):
            continue
        sym = "" if r.get(sym_col) is None else str(r.get(sym_col))
        for p in periods:
            nr: dict[str, Any] = {sym_col: sym, "周期": p}
            for g in groups:
                key = f"{g}@{p}"
                v = r.get(key, "")
                nr[g] = "" if v is None else str(v)
            out_rows.append(nr)

    return VariantTable(columns=out_cols, rows=out_rows)


def field_rows_period_columns(*, columns: list[str], rows: list[dict[str, Any]]) -> VariantTable:
    """
    方案5：字段纵向 + 周期横向（宽度稳定，适合冻结）。

    输入：columns 形如 `字段@周期`（多周期横向表）
    输出：
    - columns: [币种, 字段] + [1m,5m,15m,1h,4h,1d,1w]（按表中出现的周期，优先默认顺序）
    - rows: 每个币种按字段拆成多行，每行一个字段，横向给出 7 个周期值

    说明：
    - 如果某字段只有单值（没有任何 `字段@周期`），则该单值会填充到所有周期列（避免丢字段）。
    """
    cols = [str(c or "").strip() for c in (columns or []) if str(c or "").strip()]
    sym_col = _symbol_col(cols)
    periods = _periods_in_table(cols)

    groups: list[str] = []
    for c in cols:
        if c == sym_col:
            continue
        g = _parse_field_group(c)
        if g and g not in groups:
            groups.append(g)

    out_cols = [sym_col, "字段", *periods]
    out_rows: list[dict[str, Any]] = []

    for r in rows or []:
        if not isinstance(r, dict):
            continue
        sym = "" if r.get(sym_col) is None else str(r.get(sym_col))
        for g in groups:
            nr: dict[str, Any] = {sym_col: sym, "字段": g}
            has_any = False
            for p in periods:
                key = f"{g}@{p}"
                v = r.get(key, "")
                if v is not None and str(v) != "":
                    has_any = True
                nr[p] = "" if v is None else str(v)

            if not has_any and g in r:
                base = "" if r.get(g) is None else str(r.get(g))
                for p in periods:
                    nr[p] = base

            out_rows.append(nr)

    return VariantTable(columns=out_cols, rows=out_rows)
