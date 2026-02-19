# ruff: noqa: UP017
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

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

    values: 2D 表格（每个元素为单元格值，统一用字符串口径写入）
    panel_title_rows/panel_header_rows: 1-based 行号，用于 writer 上色
    """

    symbol: str
    values: list[list[str]]
    panel_title_rows: list[int]
    panel_header_rows: list[int]
    n_rows: int
    n_cols: int


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

    values: list[list[str]] = []
    panel_title_rows: list[int] = []
    panel_header_rows: list[int] = []

    def pad_row(row: list[str], n_cols: int) -> list[str]:
        if len(row) >= n_cols:
            return row[:n_cols]
        return row + [""] * (n_cols - len(row))

    # 统一列宽：2 个维度列 + 7 个周期列
    n_cols = 2 + len(periods_all)

    # -------------------- 顶部信息块 --------------------
    values.append(
        pad_row(
            [
                "币种",
                sym,
                "导出时间(UTC)",
                now,
                "语言",
                lang,
            ],
            n_cols,
        )
    )
    values.append(pad_row(["说明", "结构化表格（非文本伪表格）"], n_cols))
    values.append([""] * n_cols)

    # -------------------- 4 个面板 --------------------
    for panel_name in ["basic", "futures", "advanced", "pattern"]:
        config = PANEL_CONFIG.get(panel_name) or {}
        title_key = str(config.get("title_key") or "").strip()
        panel_title = _t(title_key, lang=lang) if title_key else panel_name

        # title row
        panel_title_rows.append(len(values) + 1)
        values.append(pad_row([panel_title], n_cols))

        if panel_name == "pattern":
            # 形态面板：竖表（周期为行）
            panel_header_rows.append(len(values) + 1)
            values.append(pad_row(["周期", "形态类型", "检测数量", "强度"], n_cols))
            for p in periods_all:
                data = exporter._get_data("K线形态扫描器", sym, p)  # noqa: SLF001
                if data:
                    pat = data.get("形态类型")
                    if isinstance(pat, str):
                        pat = translate_value(pat, lang=lang)
                    cnt = data.get("检测数量")
                    stg = data.get("强度")
                    values.append(
                        pad_row(
                            [
                                str(p),
                                "-" if pat is None or pat == "" else str(pat),
                                "-" if cnt is None or cnt == "" else str(cnt),
                                "-" if stg is None or stg == "" else str(stg),
                            ],
                            n_cols,
                        )
                    )
                else:
                    values.append(pad_row([str(p), "-", "-", "-"], n_cols))
            values.append([""] * n_cols)
            continue

        # 横表：指标组/指标 + 周期列
        panel_header_rows.append(len(values) + 1)
        values.append(pad_row(["指标组", "指标", *periods_all], n_cols))

        # panel periods（期货面板没有 1m）
        cfg_periods = tuple(config.get("periods") or periods_all)
        cfg_periods_set = set(cfg_periods)
        tables: dict[str, list[tuple[str, str, object]]] = config.get("tables") or {}

        for table_name, fields in tables.items():
            for field_id, display_key, formatter in fields:
                display_name = _t(display_key, lang=lang)
                row: list[str] = [str(table_name), str(display_name)]
                for p in periods_all:
                    if str(p) not in cfg_periods_set:
                        row.append("-")
                        continue
                    data = exporter._get_data(str(table_name), sym, str(p))  # noqa: SLF001
                    if not data:
                        row.append("-")
                        continue
                    val = data.get(field_id)
                    if formatter is str and isinstance(val, str):
                        val = translate_value(val, lang=lang)
                    try:
                        row.append("-" if val is None else str(formatter(val)))
                    except Exception:
                        row.append("-" if val is None else str(val))
                values.append(pad_row(row, n_cols))
            # table 分隔空行
            values.append([""] * n_cols)

    return SymbolQuerySheet(
        symbol=sym,
        values=values,
        panel_title_rows=panel_title_rows,
        panel_header_rows=panel_header_rows,
        n_rows=len(values),
        n_cols=n_cols,
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
