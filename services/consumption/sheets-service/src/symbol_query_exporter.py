# ruff: noqa: UP017
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.repo import find_repo_root, find_telegram_service_src


def _ensure_import_path() -> None:
    start = Path(__file__).resolve()
    repo_root = find_repo_root(start)
    tg_src = find_telegram_service_src(repo_root)

    # 让 `import libs.*` 可用
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    # 让 `import bot.*` / `import cards.*` 可用（telegram-service 的 src 包）
    if str(tg_src) not in sys.path:
        sys.path.insert(0, str(tg_src))


@dataclass(frozen=True)
class SymbolQuerySheet:
    """
    “币种查询”导出（用于写入 Google Sheets 的真表格，而不是伪表格文本）。

    values: 2D 表格（每个元素为单元格值；支持 number 写入以便排序/图表）
    panel_title_rows/panel_header_rows: 1-based 行号，用于 writer 上色
    """

    symbol: str
    values: list[list[Any]]
    panel_title_rows: list[int]
    panel_header_rows: list[int]
    n_rows: int
    n_cols: int
    raw_block_start_col_0: int | None = None
    merge_ranges: list[tuple[int, int, int, int]] | None = None


_NUM_SUFFIX = {
    "K": 1_000.0,
    "M": 1_000_000.0,
    "B": 1_000_000_000.0,
    "T": 1_000_000_000_000.0,
}


def _coerce_number(v: object) -> float | int | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return v

    if not isinstance(v, str):
        return None

    s = v.strip()
    if not s or s == "-":
        return None

    sign = 1.0
    if s[0] == "+":
        s = s[1:].strip()
    elif s[0] == "-":
        sign = -1.0
        s = s[1:].strip()

    is_percent = s.endswith("%")
    if is_percent:
        s = s[:-1].strip()

    mult = 1.0
    if s and s[-1].upper() in _NUM_SUFFIX:
        mult = _NUM_SUFFIX[s[-1].upper()]
        s = s[:-1].strip()

    s = s.replace(",", "")
    try:
        x = float(s)
    except Exception:
        return None

    x = sign * x * mult
    # 百分号按“百分数”保留（例如 "0.15%" -> 0.15），不转小数 0.0015
    if is_percent:
        return int(x) if float(int(x)) == x else x
    return int(x) if float(int(x)) == x else x


def _raw_value(*, val: object, display: object) -> float | int | None:
    x = _coerce_number(val)
    if x is not None:
        return x
    return _coerce_number(display)


def export_symbol_query_sheet(*, symbol: str, lang: str = "zh_CN") -> SymbolQuerySheet:
    _ensure_import_path()

    # 复用 telegram-service 的数据口径（同一 provider / 同一字段配置 / 同一翻译逻辑）
    from bot.single_token_txt import (  # type: ignore
        ALL_PERIODS,
        PANEL_CONFIG,
        SingleTokenTxtExporter,
    )
    from cards.data_provider import format_symbol  # type: ignore
    from cards.i18n import gettext as _t  # type: ignore
    from cards.i18n import translate_value  # type: ignore

    sym = format_symbol(symbol)
    if not sym:
        # 保底：返回一个最小表格（避免 writer 写空导致残留）
        values = [["币种", (symbol or "").strip().upper() or "-", "错误", "未知币种", "", "", "", "", ""]]
        return SymbolQuerySheet(
            symbol=(symbol or "").strip().upper() or "UNKNOWN",
            values=values,
            panel_title_rows=[],
            panel_header_rows=[],
            n_rows=len(values),
            n_cols=len(values[0]),
        )

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    periods_all = tuple(ALL_PERIODS)
    exporter = SingleTokenTxtExporter()
    exporter.lang = lang

    values: list[list[Any]] = []
    panel_title_rows: list[int] = []
    panel_header_rows: list[int] = []
    merge_ranges: list[tuple[int, int, int, int]] = []

    def pad_row(row: list[Any], n_cols: int) -> list[Any]:
        if len(row) >= n_cols:
            return row[:n_cols]
        return row + [""] * (n_cols - len(row))

    # 统一结构：复用主看板（方案5）的“左侧层级列 + 右侧周期列”思路
    # - 左侧 3 列：面板 / 指标组 / 指标
    # - 右侧周期列：7 周期
    # - 为了支持表内排序/阈值/图表，追加一个“raw 镜像区”（默认隐藏）：[分隔列] + raw(7周期)
    n_display = len(periods_all)
    # raw 镜像区（用于排序/图表的数值镜像）默认关闭：
    # - 否则会额外生成 1 列分隔 + N 列 raw（你看到的 J..P 等多余列），信息密度变差
    # - 如确需 raw：设置 `SHEETS_SYMBOL_QUERY_RAW_MODE=hidden|show`
    raw_mode = (os.environ.get("SHEETS_SYMBOL_QUERY_RAW_MODE", "off") or "off").strip().lower()
    if raw_mode not in {"hidden", "show", "off"}:
        raw_mode = "hidden"

    include_raw = raw_mode != "off"
    raw_block_start_col_0 = (3 + n_display) if include_raw else None  # 分隔列起始（0-based）
    n_cols = (3 + n_display + 1 + n_display) if include_raw else (3 + n_display)

    # -------------------- 顶部信息块（压缩为 1 行；单单元格） --------------------
    # 需求：币种查询子表只保留 1 行元信息（包含目录占位），用中文逗号分隔。
    # - 目录的具体条目与跳转链接由 writer 在同一单元格内补齐（RichText links）。
    # 顶部单行尽量不放 emoji：避免富文本链接的索引/渲染在不同客户端下出现偏差
    # NOTE:
    # - 目录标题与跳转链接由 writer 在同一单元格内补齐（RichText links），这里不要写入“目录（点击跳转）”
    # - 避免出现 “……，目录（点击跳转），，基础指标……” 这种重复分隔符
    meta_text = f"币种，{sym}，导出时间(UTC)，{now}，语言，{lang}，说明，结构化表格（非文本伪表格）"
    values.append(pad_row([meta_text], n_cols))

    # 全局表头（只写一次，不在每个面板重复写）
    if include_raw:
        values.append(pad_row(["面板", "指标组", "指标", *periods_all, "原始值", *periods_all], n_cols))
    else:
        values.append(pad_row(["面板", "指标组", "指标", *periods_all], n_cols))

    # -------------------- 4 个面板（写入同一张大表，面板列由 writer 做纵向 merge） --------------------
    for panel_name in ["basic", "futures", "advanced", "pattern"]:
        config = PANEL_CONFIG.get(panel_name) or {}
        title_key = str(config.get("title_key") or "").strip()
        panel_title = _t(title_key, lang=lang) if title_key else panel_name
        panel_written = False

        if panel_name == "pattern":
            # 形态面板：也做成“字段纵向 + 周期横向”，与主看板一致（更紧凑、可筛选）
            table_name = "K线形态扫描器"
            fields = [
                ("形态类型", "形态类型", str),
                ("检测数量", "检测数量", str),
                ("强度", "强度", str),
            ]
            group_row_start_0 = len(values)
            for field_id, display_key, formatter in fields:
                display_name = _t(display_key, lang=lang)
                display_row: list[Any] = [panel_title if not panel_written else "", str(table_name), str(display_name)]
                raw_row: list[Any] = []
                for p in periods_all:
                    data = exporter._get_data(str(table_name), sym, str(p))  # noqa: SLF001
                    if not data:
                        display_row.append("-")
                        if include_raw:
                            raw_row.append("")
                        continue

                    val = data.get(field_id)
                    if formatter is str and isinstance(val, str):
                        val = translate_value(val, lang=lang)

                    disp = "-" if val is None or val == "" else str(val)
                    display_row.append(disp)
                    if include_raw:
                        raw = _raw_value(val=val, display=disp)
                        raw_row.append("" if raw is None else raw)

                if include_raw:
                    values.append(pad_row([*display_row, "", *raw_row], n_cols))
                else:
                    values.append(pad_row(display_row, n_cols))
                panel_written = True

            group_row_end_0_excl = len(values)
            if (group_row_end_0_excl - group_row_start_0) > 1:
                # 指标组列（B 列）纵向合并
                merge_ranges.append((group_row_start_0, group_row_end_0_excl, 1, 2))
            continue

        # panel periods（期货面板没有 1m）
        cfg_periods = tuple(config.get("periods") or periods_all)
        cfg_periods_set = set(cfg_periods)
        tables: dict[str, list[tuple[str, str, object]]] = config.get("tables") or {}

        for table_name, fields in tables.items():
            group_row_start_0 = len(values)  # 0-based, inclusive
            for field_id, display_key, formatter in fields:
                display_name = _t(display_key, lang=lang)
                display_row: list[Any] = [panel_title if not panel_written else "", str(table_name), str(display_name)]
                raw_row: list[Any] = []
                for p in periods_all:
                    if str(p) not in cfg_periods_set:
                        display_row.append("-")
                        if include_raw:
                            raw_row.append("")
                        continue
                    data = exporter._get_data(str(table_name), sym, str(p))  # noqa: SLF001
                    if not data:
                        display_row.append("-")
                        if include_raw:
                            raw_row.append("")
                        continue
                    val = data.get(field_id)
                    if formatter is str and isinstance(val, str):
                        val = translate_value(val, lang=lang)
                    try:
                        disp = "-" if val is None else formatter(val)
                        if formatter is str and isinstance(disp, str):
                            disp = translate_value(disp, lang=lang)
                        display_row.append("-" if disp is None else str(disp))
                        if include_raw:
                            if val is None:
                                raw_row.append("")
                            else:
                                raw = _raw_value(val=val, display=disp)
                                raw_row.append("" if raw is None else raw)
                    except Exception:
                        display_row.append("-" if val is None else str(val))
                        if include_raw:
                            if val is None:
                                raw_row.append("")
                            else:
                                raw = _raw_value(val=val, display=val)
                                raw_row.append("" if raw is None else raw)
                if include_raw:
                    values.append(pad_row([*display_row, "", *raw_row], n_cols))
                else:
                    values.append(pad_row(display_row, n_cols))
                panel_written = True
            group_row_end_0_excl = len(values)
            # 合并“指标组”列（A 列）：仅对多行组生效
            if (group_row_end_0_excl - group_row_start_0) > 1:
                merge_ranges.append((group_row_start_0, group_row_end_0_excl, 1, 2))

    return SymbolQuerySheet(
        symbol=sym,
        values=values,
        panel_title_rows=panel_title_rows,
        panel_header_rows=panel_header_rows,
        n_rows=len(values),
        n_cols=n_cols,
        raw_block_start_col_0=raw_block_start_col_0,
        merge_ranges=merge_ranges,
    )


def export_symbol_full_txt(*, symbol: str, lang: str = "zh_CN") -> str:
    """
    导出“币种查询功能”的完整 TXT（与 TG 侧一致口径）。
    - symbol: 允许 BTC / BTCUSDT
    - 返回：多行文本（psql 风格）
    """
    _ensure_import_path()
    from bot.single_token_txt import export_single_token_txt  # type: ignore

    sym = (symbol or "").strip()
    if not sym:
        return ""
    return export_single_token_txt(sym, lang=lang)


def normalize_symbol_tab_title(*, symbol: str, prefix: str) -> str:
    sym = (symbol or "").strip().upper()
    if not sym:
        return (prefix or "币种查询_").strip() + "UNKNOWN"
    return f"{(prefix or '币种查询_').strip()}{sym}"
