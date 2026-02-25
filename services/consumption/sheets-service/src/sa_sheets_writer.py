# ruff: noqa: UP017
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.dashboard_variants import (
    PERIODS_DEFAULT,
    VariantTable,
    compact_cell_multiperiod,
    field_rows_period_columns,
    vertical_multiperiod,
)


def _col_to_index(col: str) -> int:
    s = (col or "").strip().upper()
    if not s or not s.isalpha():
        raise ValueError(f"invalid_column:{col}")
    idx = 0
    for ch in s:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx


def _index_to_col(idx: int) -> str:
    n = int(idx)
    if n <= 0:
        raise ValueError(f"invalid_col_index:{idx}")
    out = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(ord("A") + rem) + out
    return out


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _now_utc8_iso() -> str:
    tz8 = timezone(timedelta(hours=8))
    return datetime.now(timezone.utc).astimezone(tz8).replace(microsecond=0).isoformat()


def _utf16_len(text: str) -> int:
    """
    Google Sheets RichText 的 TextFormatRun.startIndex 以 UTF-16 code units 计数：
    - ASCII/中文：1 个字符=1
    - emoji/部分扩展字符：1 个“可见字符”可能是 2（代理对）
    """
    return len(str(text or "").encode("utf-16-le")) // 2


_NUM_SUFFIX = {
    "K": 1_000.0,
    "M": 1_000_000.0,
    "B": 1_000_000_000.0,
    "T": 1_000_000_000_000.0,
}


def _coerce_number(v: object) -> float | int | None:
    """
    将展示字符串尽可能解析为 number，用于图表/排序。
    - 支持：+/- 前缀、百分号、K/M/B/T 后缀、逗号分隔
    - 百分号按“百分数”保留（例如 "0.15%" -> 0.15），不转小数 0.0015
    """
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
    if is_percent:
        return int(x) if float(int(x)) == x else x
    return int(x) if float(int(x)) == x else x


def _rgb(r: float, g: float, b: float) -> dict[str, float]:
    return {"red": float(r), "green": float(g), "blue": float(b)}


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


def _env_text(key: str, default: str) -> str:
    v = (os.environ.get(key, "") or "").strip()
    return v or default


def _env_int_list(key: str) -> list[int]:
    """
    读取环境变量里的整数列表。
    - 支持：逗号 `,` / 中文逗号 `，` 分隔
    - 支持：JSON 列表（例如 `[80,120,60]`）
    - 空/解析失败：返回空 list
    """
    raw = (os.environ.get(key, "") or "").strip()
    if not raw:
        return []

    try:
        if raw.startswith("[") and raw.endswith("]"):
            v = json.loads(raw)
            if isinstance(v, list):
                out: list[int] = []
                for x in v:
                    try:
                        out.append(int(x))
                    except Exception:
                        continue
                return out
    except Exception:
        # fallthrough to split parsing
        pass

    raw = raw.replace("，", ",")
    out2: list[int] = []
    for part in raw.split(","):
        s = (part or "").strip()
        if not s:
            continue
        try:
            out2.append(int(s))
        except Exception:
            continue
    return out2


def _hidden_periods() -> set[str]:
    """
    需要在 Google Sheets 里“移除（删除列）”的周期列（仅展示层，不影响数据生成）。

    - env: `SHEETS_HIDE_PERIODS`，逗号分隔；默认移除 `1m`（避免主表/币种表过宽、写入量过大）
    - 禁用：`SHEETS_HIDE_PERIODS=0|off|none`
    """
    raw = (os.environ.get("SHEETS_HIDE_PERIODS", "1m") or "1m").strip()
    if raw.lower() in {"0", "off", "none"}:
        return set()
    return {s.strip() for s in raw.split(",") if s.strip()}


def _classify_bull_bear(v: Any) -> int:
    """
    将“方向/信号”类离散值归一为 bull/bear/neutral：
    - 返回：1=bull(偏多)、-1=bear(偏空)、0=neutral/unknown

    说明：
    - 该函数只用于“明确是方向/信号”的字段行（由 (card_type, field_name) 精确限定），
      避免把其它字段（例如 成交额/振幅/百分比）误判上色。
    """
    if v is None:
        return 0

    s = str(v).strip()
    if not s or s == "-":
        return 0
    if s.lower() in {"n/a", "na"}:
        return 0

    # 1) 数值方向：仅允许离散 -1/0/+1，避免把“成交额/净流/涨跌幅”等连续数值误判上色
    #    （即便调用方误把这类字段纳入了 direction_targets，也不要给出红/绿）
    n = _coerce_number(s)
    if isinstance(n, (int, float)):
        if n in {1, 1.0}:
            return 1
        if n in {-1, -1.0}:
            return -1
        return 0

    s2 = re.sub(r"\s+", "", s)

    # 2) 先处理会同时包含“多/空”的短语，避免互相覆盖
    if "空转多" in s2:
        return 1
    if "多转空" in s2:
        return -1

    # 3) 明确词
    if s2 in {"多", "偏多", "看多"}:
        return 1
    if s2 in {"空", "偏空", "看空"}:
        return -1

    if "金叉" in s2:
        return 1
    if "死叉" in s2:
        return -1

    if "多头排列" in s2:
        return 1
    if "空头排列" in s2:
        return -1

    if "支撑" in s2 or "突破" in s2 or "上破" in s2:
        return 1
    if "阻力" in s2 or "跌破" in s2 or "下破" in s2:
        return -1

    # 成交量“方向”常用词：放量/缩量
    if "缩量" in s2:
        return -1
    if "放量" in s2:
        return 1

    # 兜底：包含“偏多/多头”视为 bull；包含“偏空/空头”视为 bear
    if "偏多" in s2 or "多头" in s2:
        return 1
    if "偏空" in s2 or "空头" in s2:
        return -1

    return 0


def _empty_placeholder_mode() -> str:
    """
    空行/无数据单元格的占位渲染模式。

    - `sparkline`（默认，纯函数绘制）：用 `SPARKLINE` 画对角线（反斜线：左上→右下）
    - `char`：写入字符占位（默认字符见 `SHEETS_EMPTY_PLACEHOLDER`）
    - `off`：不做占位

    env: `SHEETS_EMPTY_PLACEHOLDER_MODE`
    """
    raw = (os.environ.get("SHEETS_EMPTY_PLACEHOLDER_MODE", "sparkline") or "sparkline").strip().lower()
    if raw in {"0", "off", "none"}:
        return "off"
    if raw in {"sparkline", "formula", "diag", "diagonal", "line"}:
        return "sparkline"
    return "char"


def _empty_placeholder_char() -> str:
    """
    `char` 模式下用于占位的字符。

    env: `SHEETS_EMPTY_PLACEHOLDER`
    - 默认：`／`（全角斜线）
    - 禁用：`0|off|none`
    """
    raw = (os.environ.get("SHEETS_EMPTY_PLACEHOLDER", "／") or "／").strip()
    if raw.lower() in {"0", "off", "none"}:
        return ""
    return raw or "／"


_SEMICOLON_LOCALE_LANGS = {
    # 经验集合：这些语言在 Sheets 中常用 `;` 作为函数参数分隔符，数组列分隔符用 `\`
    "de",
    "fr",
    "es",
    "it",
    "pt",
    "ru",
    "nl",
    "pl",
    "tr",
    "da",
    "sv",
    "no",
    "fi",
    "cs",
    "sk",
    "hu",
    "ro",
    "bg",
    "el",
    "uk",
    "sr",
    "hr",
    "sl",
    "lt",
    "lv",
    "et",
}


def _sparkline_backslash_formula(*, locale: str | None) -> str:
    """
    纯函数绘制“反斜线”对角线（左上→右下）。

    约束：
    - Sheets 没有“单元格对角线边框”，只能用 SPARKLINE 画线，视觉上近似。
    - 公式分隔符依赖 spreadsheet locale；这里按 locale 做最常见的两套语法。
    """
    # 允许强制覆盖（用于排障）：`comma` / `semicolon`
    force = (os.environ.get("SHEETS_FORMULA_SEPARATORS", "") or "").strip().lower()
    if force in {"comma", ","}:
        arg_sep, col_sep = ",", ","
    elif force in {"semicolon", ";"}:
        arg_sep, col_sep = ";", "\\"
    else:
        lang = str(locale or "").split("_", 1)[0].strip().lower()
        if lang in _SEMICOLON_LOCALE_LANGS:
            arg_sep, col_sep = ";", "\\"
        else:
            arg_sep, col_sep = ",", ","

    data = "{1" + col_sep + "0}"
    opts = (
        "{"
        + "\"charttype\""
        + col_sep
        + "\"line\""
        + ";"
        + "\"color\""
        + col_sep
        + "\"#C8C8C8\""
        + ";"
        + "\"linewidth\""
        + col_sep
        + "2"
        + ";"
        + "\"ymin\""
        + col_sep
        + "0"
        + ";"
        + "\"ymax\""
        + col_sep
        + "1"
        + "}"
    )
    return "=SPARKLINE(" + data + arg_sep + opts + ")"


def _is_no_data_cell(v: Any) -> bool:
    if _is_blank_cell(v):
        return True
    if isinstance(v, str):
        s = v.strip().lower()
        return s in {"n/a", "na"}
    return False


def _dashboard_v5_frozen_cols() -> int:
    # v5 主表列：卡片/币种/字段/周期...；默认冻结前三列（卡片+币种+字段）
    try:
        v = int((os.environ.get("SHEETS_DASHBOARD_FROZEN_COLS", "3") or "3").strip() or "3")
    except Exception:
        v = 3
    return max(v, 0)


def _dashboard_v5_col_widths_px() -> tuple[int, int, int, int]:
    """
    v5 主看板列宽（像素）：
    - A: 卡片
    - B: 币种
    - C: 字段
    - 周期列：5m..1w（已按 SHEETS_HIDE_PERIODS 删除 1m）
    """
    try:
        w_card = int((os.environ.get("SHEETS_DASHBOARD_COL_WIDTH_CARD", "120") or "120").strip() or "120")
    except Exception:
        w_card = 120
    try:
        w_symbol = int((os.environ.get("SHEETS_DASHBOARD_COL_WIDTH_SYMBOL", "64") or "64").strip() or "64")
    except Exception:
        w_symbol = 64
    try:
        w_field = int((os.environ.get("SHEETS_DASHBOARD_COL_WIDTH_FIELD", "110") or "110").strip() or "110")
    except Exception:
        w_field = 110
    try:
        w_period = int((os.environ.get("SHEETS_DASHBOARD_COL_WIDTH_PERIOD", "86") or "86").strip() or "86")
    except Exception:
        w_period = 86

    return max(w_card, 80), max(w_symbol, 50), max(w_field, 80), max(w_period, 60)


def _format_dashboard_banner_text(raw: str) -> tuple[str, int]:
    """
    将看板 banner 文案规范化为“单单元格多行文本”。

    支持：
    - 显式换行：环境变量里可用 `\\n` 表示换行（会转为 `\\n` 实际换行）
      - 说明：systemd 的 EnvironmentFile 不便直接写多行值，因此用转义序列更稳
    - 兼容旧格式：`广告位（交易猫CA：...，币安40%...；https://...）` 会被拆成 3 行：
      - 广告位
      - 交易猫CA：...
      - 币安40%...；https://...
    """

    def norm_line(s: str) -> str:
        return re.sub(r"\s+", " ", str(s or "").strip()).strip()

    s = str(raw or "").strip()
    if not s:
        return "", 0

    # 允许用 `\n` 作为“换行占位符”
    s = s.replace("\\n", "\n")
    s = s.replace("\r\n", "\n").replace("\r", "\n")

    if "\n" in s:
        lines = [norm_line(x) for x in s.split("\n")]
        lines = [x for x in lines if x]
        text = "\n".join(lines)
        return text, len(lines) if text else 0

    # 兼容旧的“单行括号格式”：标题（line2，line3）
    m = re.match(r"^(?P<title>[^（(]+)[（(](?P<body>.+)[）)]$", s)
    if m:
        title = norm_line(m.group("title"))
        body = str(m.group("body") or "")
        parts = re.split(r"[，,]\s*", body, maxsplit=1)
        if len(parts) == 2:
            line2 = norm_line(parts[0])
            line3 = norm_line(parts[1])
            lines2 = [x for x in [title, line2, line3] if x]
            text2 = "\n".join(lines2)
            return text2, len(lines2) if text2 else 0

    text = norm_line(s)
    return text, 1 if text else 0


def _read_top_banner_raw(*, prefer_dashboard: bool) -> str:
    """
    读取“全表首行广告位”文案。

    约定：
    - `SHEETS_TOP_BANNER_TEXT`：推荐的全局 banner 文案（对所有 tab 生效）
    - `SHEETS_DASHBOARD_BANNER_TEXT`：历史变量（原先仅看板）；作为兼容兜底
    """
    if prefer_dashboard:
        raw = (os.environ.get("SHEETS_DASHBOARD_BANNER_TEXT", "") or "").strip()
        if raw:
            return raw
        return (os.environ.get("SHEETS_TOP_BANNER_TEXT", "") or "").strip()

    raw = (os.environ.get("SHEETS_TOP_BANNER_TEXT", "") or "").strip()
    if raw:
        return raw
    return (os.environ.get("SHEETS_DASHBOARD_BANNER_TEXT", "") or "").strip()


def _normalize_fixed_widths(widths: list[int], *, n_cols: int) -> list[int]:
    """
    将“固定列宽列表”规范化到指定列数：
    - 丢弃无效值（<=0 / 非 int）
    - 每个宽度最小 20px（允许比默认 clamp 更窄，例如 36px）
    - 不足列数：用最后一个宽度补齐
    - 超出列数：截断
    """
    if int(n_cols) <= 0:
        return []
    out: list[int] = []
    for x in widths:
        try:
            v = int(x)
        except Exception:
            continue
        if v <= 0:
            continue
        out.append(max(int(v), 20))
    if not out:
        return []
    if len(out) < int(n_cols):
        out.extend([int(out[-1])] * (int(n_cols) - len(out)))
    if len(out) > int(n_cols):
        out = out[: int(n_cols)]
    return out


def _symbol_query_frozen_cols() -> int:
    # 币种查询列：面板/指标组/指标/周期...；默认冻结前三列
    try:
        v = int((os.environ.get("SHEETS_SYMBOL_QUERY_FROZEN_COLS", "3") or "3").strip() or "3")
    except Exception:
        v = 3
    return max(v, 0)


def _symbol_query_col_widths_px() -> tuple[int, int, int, int]:
    """
    币种查询表列宽（像素）：
    - A: 面板
    - B: 指标组
    - C: 指标
    - 周期列：5m..1w
    """
    try:
        w_panel = int((os.environ.get("SHEETS_SYMBOL_QUERY_COL_WIDTH_PANEL", "90") or "90").strip() or "90")
    except Exception:
        w_panel = 90
    try:
        w_group = int((os.environ.get("SHEETS_SYMBOL_QUERY_COL_WIDTH_GROUP", "150") or "150").strip() or "150")
    except Exception:
        w_group = 150
    try:
        w_metric = int((os.environ.get("SHEETS_SYMBOL_QUERY_COL_WIDTH_METRIC", "170") or "170").strip() or "170")
    except Exception:
        w_metric = 170
    try:
        w_period = int((os.environ.get("SHEETS_SYMBOL_QUERY_COL_WIDTH_PERIOD", "78") or "78").strip() or "78")
    except Exception:
        w_period = 78

    return max(w_panel, 40), max(w_group, 60), max(w_metric, 60), max(w_period, 50)


def _polymarket_col_widths_px(*, n_cols: int) -> list[int]:
    """
    Polymarket 统计子表列宽（像素）。
    默认更紧凑，避免 1 列超宽导致整体信息密度过低。
    """
    try:
        w_first = int((os.environ.get("SHEETS_POLYMARKET_COL_WIDTH_FIRST", "360") or "360").strip() or "360")
    except Exception:
        w_first = 360
    try:
        w_other = int((os.environ.get("SHEETS_POLYMARKET_COL_WIDTH_OTHER", "120") or "120").strip() or "120")
    except Exception:
        w_other = 120
    try:
        w_min = int((os.environ.get("SHEETS_POLYMARKET_COL_WIDTH_MIN", "80") or "80").strip() or "80")
    except Exception:
        w_min = 80
    w_first = max(int(w_first), 200)
    w_other = max(int(w_other), int(w_min))

    if int(n_cols) <= 0:
        return [w_first]
    out = [w_first]
    for _ in range(1, int(n_cols)):
        out.append(w_other)
    return out


def _polymarket_frozen_cols() -> int:
    """
    Polymarket 统计子表“冻结列”数量（默认冻结第 1 列：面板列）。
    - env: `SHEETS_POLYMARKET_FROZEN_COLS`
    """
    try:
        v = int((os.environ.get("SHEETS_POLYMARKET_FROZEN_COLS", "2") or "2").strip() or "2")
    except Exception:
        v = 2
    return max(int(v), 0)


def _polymarket_frozen_rows(*, anchors: list[tuple[str, int, int]]) -> int:
    """
    Polymarket 统计子表“冻结行”数量。

    默认策略（无 env 显式覆盖时）：
    - 冻结：元信息行 + 目录行 + 首个分段的全部表头行
      - 这样滚动时“字段含义”不会立刻丢失

    - env: `SHEETS_POLYMARKET_FROZEN_ROWS`（显式指定冻结行数，优先级最高）
    """
    raw = (os.environ.get("SHEETS_POLYMARKET_FROZEN_ROWS", "") or "").strip()
    if raw:
        try:
            return max(int(raw), 0)
        except Exception:
            pass

    # meta(1) + dir(1) = 2 行；再加上首个分段 header 行数
    if anchors:
        try:
            _title, header_row_1, header_rows_n = anchors[0]
            header_row_1 = int(header_row_1)
            header_rows_n = int(header_rows_n)
            if header_row_1 > 0 and header_rows_n > 0:
                last_header_row_1 = header_row_1 + header_rows_n - 1
                return max(int(last_header_row_1), 2)
        except Exception:
            pass

    return 2


def _value_type(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    return "object"


def _is_blank_cell(x: Any) -> bool:
    if x is None:
        return True
    if isinstance(x, str):
        s = x.strip()
        return (not s) or (s == "-")
    return False


def _drop_fully_empty_columns(headers: list[list[Any]], rows: list[list[Any]]) -> tuple[list[list[Any]], list[list[Any]]]:
    """
    去掉“整列都是空”的分隔列（常见于 exporter 为了视觉分组插入的空列）。
    - 仅当：所有 header 行该列为空，且所有数据行该列为空，才会删除该列
    """
    if not headers:
        return headers, rows
    n_cols0 = max((len(h) for h in headers), default=0)
    n_cols0 = max(int(n_cols0), max((len(r) for r in rows), default=0))
    if n_cols0 <= 0:
        return headers, rows

    keep: list[int] = []
    for ci in range(0, int(n_cols0)):
        hdr_blank = True
        for h in headers:
            v = h[ci] if ci < len(h) else ""
            if not _is_blank_cell(v):
                hdr_blank = False
                break
        if not hdr_blank:
            keep.append(int(ci))
            continue

        data_blank = True
        for r in rows:
            v = r[ci] if ci < len(r) else ""
            if not _is_blank_cell(v):
                data_blank = False
                break
        if not data_blank:
            keep.append(int(ci))

    if len(keep) == int(n_cols0):
        return headers, rows

    headers2 = [[(h[ci] if ci < len(h) else "") for ci in keep] for h in headers]
    rows2 = [[(r[ci] if ci < len(r) else "") for ci in keep] for r in rows]
    return headers2, rows2


def _polymarket_drop_columns_by_header(
    headers: list[list[Any]],
    rows: list[list[Any]],
    *,
    drop_names: set[str],
) -> tuple[list[list[Any]], list[list[Any]]]:
    """
    删除指定表头名对应的整列（用于“布局收敛”，不改数据源）。

    规则：
    - 只要任意一行表头该列命中 drop_names（去空格后完全匹配），就删除该列
    - drop_names 为空则不处理
    """
    if not drop_names:
        return headers, rows
    if not headers:
        return headers, rows

    n_cols0 = max((len(h) for h in headers), default=0)
    n_cols0 = max(int(n_cols0), max((len(r) for r in rows), default=0))
    if n_cols0 <= 0:
        return headers, rows

    drop_cols: set[int] = set()
    for ci in range(0, int(n_cols0)):
        for h in headers:
            v = h[ci] if ci < len(h) else ""
            name = str(v or "").strip()
            if name and name in drop_names:
                drop_cols.add(int(ci))
                break
    if not drop_cols:
        return headers, rows

    keep = [ci for ci in range(0, int(n_cols0)) if int(ci) not in drop_cols]
    if not keep:
        return headers, rows

    headers2 = [[(h[ci] if ci < len(h) else "") for ci in keep] for h in headers]
    rows2 = [[(r[ci] if ci < len(r) else "") for ci in keep] for r in rows]
    return headers2, rows2


def _flatten_eav(prefix: str, val: Any) -> Iterable[tuple[str, str, str]]:
    """
    返回 (field_path, value_type, value_text) 的序列。
    - 对 object/array：先写容器节点，再递归子节点
    - 对 scalar：写标量节点
    """
    t = _value_type(val)
    path = prefix or "_"
    if t in {"null", "bool", "number", "string"}:
        yield (path, t, "" if val is None else str(val))
        return

    if t == "array":
        yield (path, t, "")
        for i, item in enumerate(val):
            yield from _flatten_eav(f"{path}[{i}]", item)
        return

    # object
    yield (path, t, "")
    if isinstance(val, dict):
        for k, v in val.items():
            child = f"{k}" if path == "_" else f"{path}.{k}"
            yield from _flatten_eav(child, v)


@dataclass(frozen=True)
class BootstrapResult:
    spreadsheet_id: str
    spreadsheet_url: str


class _WriteRateLimiter:
    def __init__(self, limit_per_minute: int) -> None:
        self._limit = max(int(limit_per_minute), 0)
        self._window_seconds = 60.0
        self._ts: deque[float] = deque()

    def acquire(self) -> None:
        if self._limit <= 0:
            return

        while True:
            now = time.monotonic()
            while self._ts and (now - self._ts[0]) >= self._window_seconds:
                self._ts.popleft()

            if len(self._ts) < self._limit:
                self._ts.append(now)
                return

            sleep_for = self._window_seconds - (now - self._ts[0]) + 0.05
            time.sleep(max(sleep_for, 0.05))


class SaSheetsWriter:
    """
    Service Account + Google Sheets API 写入实现（全 CLI）。
    - 支持：创建工作簿、建 tab/表头、写事实表、渲染 dashboard（含合并单元格）
    - 可选：Drive 权限（公开只读/分享给 email）、以及超长 raw 字段落 Drive blob
    """

    def __init__(
        self,
        *,
        spreadsheet_id: str,
        credentials_path: str,
        dashboard_col_l: str,
        dashboard_col_r: str,
        dashboard_mode: str = "replace",
        dashboard_slot_height: int = 260,
        facts_mode: str = "append",
        share_email: str,
        public_read: bool,
        drive_folder_id: str,
        blob_threshold_chars: int,
        timeout_seconds: int = 15,
        schema_mode: str = "full",
        local_meta_path: Path | None = None,
    ) -> None:
        try:
            import google_auth_httplib2  # type: ignore
            import httplib2  # type: ignore
            from google.oauth2.service_account import Credentials  # type: ignore
            from googleapiclient.discovery import build  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "缺少 Google API 依赖：请在 sheets-service 安装 google-api-python-client/google-auth"
            ) from exc

        if not credentials_path:
            raise RuntimeError("缺少 SA 凭证路径：设置 GOOGLE_APPLICATION_CREDENTIALS 或 SHEETS_SA_CREDENTIALS_PATH")

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)

        # 关键：在部分网络环境下必须走代理（例如 WSL/公司网络）
        # httplib2 默认不读环境变量；这里显式从环境构造 proxy_info。
        proxy_info = httplib2.proxy_info_from_environment()
        base_http = httplib2.Http(proxy_info=proxy_info, timeout=timeout_seconds)
        authed_http = google_auth_httplib2.AuthorizedHttp(creds, http=base_http)

        self._sheets = build("sheets", "v4", http=authed_http, cache_discovery=False)
        self._drive = build("drive", "v3", http=authed_http, cache_discovery=False)

        self._spreadsheet_id = spreadsheet_id
        self._dashboard_col_l = dashboard_col_l
        self._dashboard_col_r = dashboard_col_r
        self._dashboard_mode = (dashboard_mode or "replace").strip().lower()
        self._dashboard_slot_height = max(int(dashboard_slot_height), 1)
        self._facts_mode = (facts_mode or "append").strip().lower()
        self._share_email = share_email
        self._public_read = public_read
        self._drive_folder_id = drive_folder_id
        self._blob_threshold_chars = int(blob_threshold_chars)
        self._timeout_seconds = timeout_seconds
        self._schema_mode = (schema_mode or "full").strip().lower()
        if self._schema_mode not in {"full", "minimal"}:
            self._schema_mode = "full"
        self._local_meta_path = local_meta_path

        # Sheet tabs（要求：全部中文命名；如需定制可用 env 覆盖）
        self._tab_dashboard = _env_text("SHEETS_TAB_DASHBOARD", "看板")
        self._tab_dashboard_data = _env_text("SHEETS_TAB_DASHBOARD_DATA", "看板_数据")
        self._tab_dashboard_history = _env_text("SHEETS_TAB_DASHBOARD_HISTORY", "看板_历史")
        self._tab_dashboard_meta = _env_text("SHEETS_TAB_DASHBOARD_META", "看板_元信息")
        self._tab_cards_index = _env_text("SHEETS_TAB_CARDS_INDEX", "卡片索引")
        self._tab_card_fields_eav = _env_text("SHEETS_TAB_CARD_FIELDS_EAV", "卡片字段EAV")
        self._tab_card_rows = _env_text("SHEETS_TAB_CARD_ROWS", "卡片明细行")
        self._tab_row_fields_eav = _env_text("SHEETS_TAB_ROW_FIELDS_EAV", "明细字段EAV")
        self._tab_blobs_index = _env_text("SHEETS_TAB_BLOBS_INDEX", "大字段索引")
        self._tab_meta = _env_text("SHEETS_TAB_META", "元数据")
        self._tab_polymarket_stats = _env_text("SHEETS_TAB_POLYMARKET_STATS", "Polymarket统计")
        self._tab_polymarket_events = _env_text("SHEETS_TAB_POLYMARKET_EVENTS", "Polymarket事件")

        self._ensured_schema = False
        self._sheet_id_by_title: dict[str, int] = {}
        self._grid_by_title: dict[str, tuple[int, int]] = {}
        self._append_cursor_y = 1

        # Google Sheets 默认配额很低（常见为 60 write req/min/user），不做节流会稳定触发 429。
        write_rpm = int((os.environ.get("SHEETS_SA_WRITE_RPM", "55") or "55").strip())
        self._write_limiter = _WriteRateLimiter(write_rpm)

        # Spreadsheet locale（用于生成 locale-sensitive 的公式文本，例如 SPARKLINE 的分隔符）
        self._spreadsheet_locale: str | None = None
        try:
            ss = self._exec(
                self._sheets.spreadsheets().get(
                    spreadsheetId=self._spreadsheet_id,
                    fields="properties.locale",
                ),
                is_write=False,
            )
            self._spreadsheet_locale = str(((ss.get("properties") or {}) or {}).get("locale") or "").strip() or None
        except Exception:
            self._spreadsheet_locale = None

    def _exec(self, req: Any, *, is_write: bool) -> Any:
        if is_write:
            self._write_limiter.acquire()
            # 429 是明确的“未执行”限流错误，重试不会造成重复写入风险（包括 append）。
            try:
                max_retries = int((os.environ.get("SHEETS_SA_429_RETRIES", "8") or "8").strip())
            except Exception:
                max_retries = 8
            max_retries = max(max_retries, 0)

            attempt = 0
            while True:
                try:
                    return req.execute()
                except Exception as exc:
                    status = int(getattr(getattr(exc, "resp", None), "status", 0) or 0)
                    if status != 429 or attempt >= max_retries:
                        raise
                    # 指数退避：2s,4s,8s...（上限 60s），给配额窗口留时间
                    delay = min(2.0 * (2**attempt), 60.0)
                    time.sleep(delay)
                    attempt += 1

        # 读请求也可能在弱网/代理环境下超时；读是幂等的，可以安全重试。
        try:
            read_retries = int((os.environ.get("SHEETS_SA_READ_RETRIES", "3") or "3").strip())
        except Exception:
            read_retries = 3
        read_retries = max(read_retries, 0)

        attempt = 0
        while True:
            try:
                return req.execute()
            except TimeoutError:
                if attempt >= read_retries:
                    raise
                # 简单指数退避：1s,2s,4s...（上限 8s），避免瞬时抖动导致整轮失败
                delay = min(1.0 * (2**attempt), 8.0)
                time.sleep(delay)
                attempt += 1

    # ==================== runtime overrides（用于 CLI/运维） ====================
    def set_dashboard_mode(self, mode: str) -> None:
        self._dashboard_mode = (mode or "").strip().lower() or self._dashboard_mode

    def compute_col_r(self, *, col_l: str, needed_cols: int, min_col_r: str) -> str:
        """
        计算 dashboard 的 col_r：
        - 从 col_l 起，需要容纳 needed_cols 列
        - 同时不小于 min_col_r（避免把用户显式配置的右边界“缩回去”）
        """
        left = _col_to_index(col_l)
        need = max(int(needed_cols), 1)
        want_r = left + need - 1
        try:
            min_r = _col_to_index(min_col_r)
        except Exception:
            min_r = want_r
        return _index_to_col(max(want_r, min_r))

    # ==================== bootstrap ====================
    def bootstrap(self, *, title: str) -> BootstrapResult:
        if not self._spreadsheet_id:
            quota = self._exec(self._drive.about().get(fields="storageQuota"), is_write=False).get("storageQuota", {})
            limit = int(quota.get("limit") or "0")
            usage = int(quota.get("usage") or "0")
            if limit <= 0 or usage >= limit:
                raise RuntimeError(
                    "Service Account 的 Google Drive 存储配额为 0（或已用尽），无法创建新工作簿。"
                    "解决方案：用你的个人账号先创建一个空 Google Sheet（网页端），把它分享给该 SA 邮箱为编辑，"
                    "然后设置 SHEETS_SPREADSHEET_ID 走写入（无需再 bootstrap 创建）。"
                )
            created = self._exec(
                self._sheets.spreadsheets().create(body={"properties": {"title": title}}), is_write=True
            )
            self._spreadsheet_id = created["spreadsheetId"]

        self.ensure_schema()

        if self._drive_folder_id:
            self._move_to_folder(self._drive_folder_id)

        if self._public_read:
            self._set_public_read()

        if self._share_email:
            self._share_to_email(self._share_email, role="writer")

        url = f"https://docs.google.com/spreadsheets/d/{self._spreadsheet_id}"
        return BootstrapResult(spreadsheet_id=self._spreadsheet_id, spreadsheet_url=url)

    def _move_to_folder(self, folder_id: str) -> None:
        file_id = self._spreadsheet_id
        meta = self._exec(self._drive.files().get(fileId=file_id, fields="parents"), is_write=False)
        parents = ",".join(meta.get("parents", []))
        self._exec(
            self._drive.files().update(
                fileId=file_id,
                addParents=folder_id,
                removeParents=parents or None,
                fields="id, parents",
            ),
            is_write=True,
        )

    def _set_public_read(self) -> None:
        self._exec(
            self._drive.permissions().create(
                fileId=self._spreadsheet_id,
                body={"type": "anyone", "role": "reader"},
                fields="id",
            ),
            is_write=True,
        )

    def _share_to_email(self, email: str, *, role: str) -> None:
        self._exec(
            self._drive.permissions().create(
                fileId=self._spreadsheet_id,
                body={"type": "user", "role": role, "emailAddress": email},
                fields="id",
                sendNotificationEmail=False,
            ),
            is_write=True,
        )

    # ==================== schema ====================
    def ensure_schema(self) -> None:
        if self._ensured_schema:
            return

        # minimal schema：只保留“看板 + 币种查询子表”，不创建事实/元数据等 tab。
        if self._schema_mode == "minimal":
            self._refresh_sheet_map()
            if self._tab_dashboard not in self._sheet_id_by_title:
                self._exec(
                    self._sheets.spreadsheets().batchUpdate(
                        spreadsheetId=self._spreadsheet_id,
                        body={"requests": [{"addSheet": {"properties": {"title": self._tab_dashboard}}}]},
                    ),
                    is_write=True,
                )
                self._refresh_sheet_map()
            # 进程启动后尽量恢复 append cursor（避免 append 模式重启后从 1 覆盖）
            try:
                meta = self._local_meta_get()
                self._append_cursor_y = int(str(meta.get("dashboard_next_row") or "1").strip() or "1")
            except Exception:
                self._append_cursor_y = 1
            self._ensured_schema = True
            return

        wanted = [
            self._tab_dashboard,
            self._tab_dashboard_data,
            self._tab_dashboard_history,
            self._tab_dashboard_meta,
            self._tab_cards_index,
            self._tab_card_fields_eav,
            self._tab_card_rows,
            self._tab_row_fields_eav,
            self._tab_blobs_index,
            self._tab_meta,
        ]
        self._refresh_sheet_map()

        # 兼容：旧工作簿若使用英文 tab 名，自动迁移为中文（保证“全部子表中文命名”）
        self._migrate_legacy_tabs()
        self._refresh_sheet_map()

        missing = [n for n in wanted if n not in self._sheet_id_by_title]
        if missing:
            reqs = [{"addSheet": {"properties": {"title": name}}} for name in missing]
            self._exec(
                self._sheets.spreadsheets().batchUpdate(
                    spreadsheetId=self._spreadsheet_id,
                    body={"requests": reqs},
                ),
                is_write=True,
            )
            self._refresh_sheet_map()

        # 数据层/历史层默认隐藏（不影响阅读 tab）
        try:
            self._set_sheet_hidden(self._tab_dashboard_data, hidden=True)
        except Exception:
            pass
        try:
            self._set_sheet_hidden(self._tab_dashboard_history, hidden=True)
        except Exception:
            pass
        # 元信息层默认隐藏（可自行取消隐藏查看）
        try:
            self._set_sheet_hidden(self._tab_dashboard_meta, hidden=True)
        except Exception:
            pass

        # headers（dashboard 不需要，但保留一致性）
        self._ensure_header_row(
            self._tab_dashboard_data,
            [
                "export_ts_utc",
                "card_key",
                "ts_utc",
                "source_service",
                "card_type",
                "title",
                "update_time",
                "sort_desc",
                "last_update",
                "symbol",
                "field",
                "period",
                "value_display",
                "value_num",
            ],
        )
        self._ensure_header_row(
            self._tab_dashboard_history,
            [
                "export_ts_utc",
                "card_type",
                "title",
                "update_time",
                "symbol",
                "field",
                "period",
                "value_num",
                "value_display",
            ],
        )
        self._ensure_header_row(
            self._tab_dashboard_meta,
            [
                "title",
                "update_time",
                "sort_desc",
                "hint",
                "last_update",
            ],
        )
        self._ensure_header_row(
            self._tab_cards_index,
            [
                "card_key",
                "ts_utc",
                "source_service",
                "card_type",
                "title",
                "update_time",
                "sort_desc",
                "last_update",
                "tg_url",
                "dash_sheet",
                "dash_col_l",
                "dash_col_r",
                "dash_row_y",
                "dash_height",
            ],
        )
        self._ensure_header_row(self._tab_card_fields_eav, ["card_key", "field_path", "value_text", "value_type"])
        self._ensure_header_row(self._tab_card_rows, ["card_key", "row_index", "row_key", "row_json"])
        self._ensure_header_row(
            self._tab_row_fields_eav, ["card_key", "row_index", "field_path", "value_text", "value_type"]
        )
        self._ensure_header_row(
            self._tab_blobs_index, ["card_key", "blob_key", "sha256", "mime", "url", "size_chars", "created_at"]
        )
        self._ensure_header_row(self._tab_meta, ["key", "value"])

        # meta defaults
        meta = self._meta_get()
        defaults = {
            "schema_version": "1",
            "dashboard_next_row": str(meta.get("dashboard_next_row") or "1"),
            "dashboard_col_l": meta.get("dashboard_col_l") or self._dashboard_col_l,
            "dashboard_col_r": meta.get("dashboard_col_r") or self._dashboard_col_r,
            "dashboard_mode": meta.get("dashboard_mode") or self._dashboard_mode,
            "dashboard_slot_height": str(meta.get("dashboard_slot_height") or str(self._dashboard_slot_height)),
        }
        self._meta_set(defaults)

        self._ensured_schema = True

    # ==================== symbol tabs（币种查询子表） ====================
    def ensure_symbol_tab(self, *, title: str) -> None:
        self.ensure_schema()
        self._refresh_sheet_map()
        if title in self._sheet_id_by_title:
            return
        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
            ),
            is_write=True,
        )
        self._refresh_sheet_map()

    # ==================== generic sheet ops（用于变体看板） ====================
    def ensure_sheet(self, *, title: str) -> None:
        self.ensure_schema()
        self._refresh_sheet_map()
        if title in self._sheet_id_by_title:
            return
        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
            ),
            is_write=True,
        )
        self._refresh_sheet_map()

    def ensure_hidden_sheet(self, *, title: str) -> None:
        """
        确保 sheet 存在且处于隐藏状态（用于“数据层/历史层”等非阅读面板）。
        """
        self.ensure_sheet(title=title)
        try:
            self._set_sheet_hidden(title, hidden=True)
        except Exception:
            # 隐藏失败不影响写入；最多是 tab 可见
            pass

    def reset_sheet_display(
        self,
        *,
        title: str,
        col_l: str,
        col_r: str,
        compact: bool = True,
        frozen_row_count: int = 0,
        frozen_column_count: int = 0,
    ) -> dict[str, Any]:
        """
        清理指定 sheet 的展示面（用于“看板变体 tab”）：
        - clear values
        - unmerge all
        - clear formats（避免残留背景色/边框）
        - 可选：压缩 grid（仅影响该 sheet）
        """
        self.ensure_sheet(title=title)
        col_l_u = str(col_l).strip().upper()
        col_r_u = str(col_r).strip().upper()
        frozen_row_count = max(int(frozen_row_count or 0), 0)
        frozen_column_count = max(int(frozen_column_count or 0), 0)

        # 1) clear values
        self._exec(
            self._sheets.spreadsheets()
            .values()
            .clear(
                spreadsheetId=self._spreadsheet_id,
                range=f"{title}!A:ZZ",
            ),
            is_write=True,
        )

        sh_id = self._sheet_id_by_title.get(title)
        if sh_id is None:
            self._refresh_sheet_map()
            sh_id = self._sheet_id_by_title[title]

        # 2) unmerge all
        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": [{"unmergeCells": {"range": {"sheetId": int(sh_id)}}}]},
            ),
            is_write=True,
        )

        # 3) clear formats
        try:
            target_cols = max(_col_to_index(col_r_u), 1)
        except Exception:
            target_cols = 26
        cur_rows, cur_cols = self._grid_by_title.get(title, (1000, 26))
        clear_rows = max(int(cur_rows or 0), 1)
        clear_cols = max(int(cur_cols or 0), int(target_cols), 1)
        self._ensure_grid_size(title, min_rows=int(clear_rows), min_cols=int(clear_cols))
        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={
                    "requests": [
                        {
                            "repeatCell": {
                                "range": {
                                    "sheetId": int(sh_id),
                                    "startRowIndex": 0,
                                    "endRowIndex": int(clear_rows),
                                    "startColumnIndex": 0,
                                    "endColumnIndex": int(clear_cols),
                                },
                                "cell": {"userEnteredFormat": {}},
                                "fields": "userEnteredFormat",
                            }
                        }
                    ]
                },
            ),
            is_write=True,
        )

        if compact:
            target_rows = max(int(frozen_row_count) + 1, 2)
            target_cols = max(int(_col_to_index(col_r_u)), int(frozen_column_count), 1)
            self._exec(
                self._sheets.spreadsheets().batchUpdate(
                    spreadsheetId=self._spreadsheet_id,
                    body={
                        "requests": [
                            {
                                "updateSheetProperties": {
                                    "properties": {
                                        "sheetId": int(sh_id),
                                        "gridProperties": {
                                            "rowCount": int(target_rows),
                                            "columnCount": int(target_cols),
                                            "frozenRowCount": int(frozen_row_count),
                                            "frozenColumnCount": int(frozen_column_count),
                                            "hideGridlines": False,
                                        },
                                    },
                                    "fields": "gridProperties.rowCount,gridProperties.columnCount,gridProperties.frozenRowCount,gridProperties.frozenColumnCount,gridProperties.hideGridlines",
                                }
                            }
                        ]
                    },
                ),
                is_write=True,
            )
            self._refresh_sheet_map()

        return {"ok": True, "sheet": title, "col_l": col_l_u, "col_r": col_r_u}

    def write_symbol_query_tab(self, *, tab_title: str, sheet: Any) -> dict[str, Any]:
        """
        覆盖写“币种查询”子表（真表格）：
        - 每个值一个单元格（非“| 分隔符伪表格”）
        - 不做 append，避免 cells 无限增长
        - 通过 meta 记录上次 rows/cols，仅清理尾部差量，避免整表 clear 带来的闪烁
        - 支持样式版本升级（自动清除旧 conditional formatting，避免历史残留）
        """
        self.ensure_symbol_tab(title=tab_title)

        sh_id = self._sheet_id_by_title.get(tab_title)
        if sh_id is None:
            self._refresh_sheet_map()
            sh_id = self._sheet_id_by_title.get(tab_title)
        if sh_id is None:
            raise RuntimeError(f"missing_sheet:{tab_title}")

        # 先 unmerge，避免旧版合并残留导致 values.update 报错或结构错乱
        try:
            self._exec(
                self._sheets.spreadsheets().batchUpdate(
                    spreadsheetId=self._spreadsheet_id,
                    body={"requests": [{"unmergeCells": {"range": {"sheetId": int(sh_id)}}}]},
                ),
                is_write=True,
            )
        except Exception:
            pass

        values = getattr(sheet, "values", None) or []
        n_rows = int(getattr(sheet, "n_rows", 0) or len(values))
        n_cols = int(getattr(sheet, "n_cols", 0) or (len(values[0]) if values else 0))
        panel_title_rows = list(getattr(sheet, "panel_title_rows", []) or [])
        panel_header_rows = list(getattr(sheet, "panel_header_rows", []) or [])
        merge_ranges = list(getattr(sheet, "merge_ranges", []) or [])

        if not values or n_rows <= 0 or n_cols <= 0:
            values = [["-", "-", "-", "-", "-", "-", "-", "-", "-"]]
            n_rows, n_cols = 1, len(values[0])

        # -------------------- top banner（全表首行广告位） --------------------
        # 要求：每个表都“强制”有一个首行广告位（单单元格多行文本）。
        # - 这里不依赖 exporter；由 writer 统一注入，确保后续结构升级不会漏掉
        # - 注：冻结列开启时不做真 merge；用“遮蔽内竖线”实现视觉合并（见样式段）
        banner_raw = _read_top_banner_raw(prefer_dashboard=False)
        banner_text, banner_line_count = _format_dashboard_banner_text(str(banner_raw or ""))
        banner_rows = 1 if banner_text else 0
        if banner_rows > 0:
            try:
                max_cols0 = max((len(r) for r in values if isinstance(r, list)), default=int(n_cols or 1))
            except Exception:
                max_cols0 = int(n_cols or 1)
            max_cols0 = max(int(max_cols0), int(n_cols or 1), 1)
            values = [[banner_text] + [""] * (int(max_cols0) - 1)] + list(values)

            # shift exporter-provided row indices / merge ranges（整表下移 1 行）
            try:
                panel_title_rows = [int(r) + 1 for r in panel_title_rows]
            except Exception:
                panel_title_rows = []
            try:
                panel_header_rows = [int(r) + 1 for r in panel_header_rows]
            except Exception:
                panel_header_rows = []
            merge_ranges2: list[tuple[int, int, int, int]] = []
            for rg in merge_ranges:
                try:
                    r0, r1, c0, c1 = rg
                except Exception:
                    continue
                try:
                    merge_ranges2.append((int(r0) + 1, int(r1) + 1, int(c0), int(c1)))
                except Exception:
                    continue
            merge_ranges = merge_ranges2

            n_rows = int(len(values))
            n_cols = int(max(int(n_cols), int(max_cols0)))

        # -------------------- detect header/panels (v7) --------------------
        # 结构（默认）：
        # - Row1: banner（可选，全表首行广告位）
        # - Row2: meta + directory（单单元格，writer 补 RichText links）
        # - Row3: 全局表头：面板 | 指标组 | 指标 | 1m..1w | (原始值) | 1m..1w
        header_row_0 = None
        directory_row_0 = int(banner_rows)  # meta+directory 行（0-based）
        for ri, row in enumerate(values):
            if not isinstance(row, list) or len(row) < 3:
                continue
            c0 = str(row[0]).strip()
            c1 = str(row[1]).strip()
            c2 = str(row[2]).strip()
            if c0 == "面板" and c1 == "指标组" and c2 == "指标":
                header_row_0 = int(ri)
                break
        if header_row_0 is None:
            header_row_0 = 3  # 向后兼容旧数据时的保底

        # -------------------- drop period columns（删除列，不折叠隐藏） --------------------
        # 需求：直接删除 1m（以及其它配置的周期列），不使用 hiddenByUser 折叠。
        # 做法：直接修改 values 矩阵，从源头“删列”，保证：
        # - 表头与数据区不再出现该周期；
        # - raw 镜像区（若存在）同步删除对应列；
        # - compact grid 会随 n_cols 收缩，右侧不再残留多余空列。
        drop_periods = _hidden_periods()
        if drop_periods:
            try:
                header_row = values[int(header_row_0)] if 0 <= int(header_row_0) < len(values) else []
                raw_sep: int | None = None
                if isinstance(header_row, list):
                    for ci, cell in enumerate(header_row):
                        if str(cell).strip() == "原始值":
                            raw_sep = int(ci)
                            break

                display_end = int(raw_sep) if raw_sep is not None else (len(header_row) if isinstance(header_row, list) else 0)
                display_period_cols: list[tuple[int, str]] = []
                if isinstance(header_row, list):
                    for ci in range(3, int(display_end)):
                        name = str(header_row[ci]).strip()
                        if not name:
                            continue
                        display_period_cols.append((int(ci), name))

                drop_positions = [pos for pos, (_ci, name) in enumerate(display_period_cols) if name in drop_periods]
                if drop_positions:
                    cols_to_remove: set[int] = set()
                    for pos in drop_positions:
                        cols_to_remove.add(int(display_period_cols[int(pos)][0]))
                        if raw_sep is not None:
                            cols_to_remove.add(int(raw_sep) + 1 + int(pos))

                    for ci in sorted(cols_to_remove, reverse=True):
                        for row in values:
                            if isinstance(row, list) and 0 <= int(ci) < len(row):
                                row.pop(int(ci))

                    # 规整成矩形矩阵，避免 merge/style 计算时行长度不一致
                    n_cols2 = max((len(r) for r in values if isinstance(r, list)), default=0)
                    for row in values:
                        if isinstance(row, list) and len(row) < int(n_cols2):
                            row.extend([""] * (int(n_cols2) - len(row)))

                    # raw_sep 位置变化：同步回写到 sheet 对象（供后续样式/列宽/隐藏 raw 区使用）
                    header_row2 = values[int(header_row_0)] if 0 <= int(header_row_0) < len(values) else []
                    raw_sep2: int | None = None
                    if isinstance(header_row2, list):
                        for ci, cell in enumerate(header_row2):
                            if str(cell).strip() == "原始值":
                                raw_sep2 = int(ci)
                                break
                    try:
                        sheet.raw_block_start_col_0 = raw_sep2  # type: ignore[attr-defined]
                    except Exception:
                        pass

                    n_rows = int(len(values))
                    n_cols = int(n_cols2)
            except Exception:
                pass

        panel_starts: list[tuple[int, str]] = []
        for ri in range(int(header_row_0) + 1, int(n_rows)):
            row = values[ri]
            if not isinstance(row, list) or not row:
                continue
            title = str(row[0]).strip()
            if not title:
                continue
            # 避免误识别表头/目录
            if title in {"面板", "币种", "说明"} or title.startswith("📌"):
                continue
            panel_starts.append((int(ri), title))

        # 面板列（A）纵向合并：每个面板块从 start 到下一个 start（或结尾）
        panel_blocks: list[tuple[int, int, str]] = []
        for idx, (start_0, title) in enumerate(panel_starts):
            end_0_excl = int(panel_starts[idx + 1][0]) if (idx + 1) < len(panel_starts) else int(n_rows)
            if end_0_excl > start_0:
                panel_blocks.append((int(start_0), int(end_0_excl), str(title)))

        # -------------------- empty placeholder（斜线占位） --------------------
        # 仅对“数据区”的周期列生效：避免污染面板标题行/表头/元信息行。
        # - 目的：把空值/无数据“画成对角线占位”（纯函数 SPARKLINE）或写入字符占位。
        placeholder_mode = _empty_placeholder_mode()
        placeholder_char = _empty_placeholder_char() if placeholder_mode == "char" else ""
        sparkline_cells: list[tuple[int, int]] = []  # (row_1, col_1)
        if placeholder_mode != "off":
            try:
                header_row = values[int(header_row_0)] if 0 <= int(header_row_0) < len(values) else []
                period_set = set(PERIODS_DEFAULT)
                period_cols: list[int] = []
                if isinstance(header_row, list):
                    for ci, cell in enumerate(header_row):
                        if str(cell).strip() in period_set:
                            period_cols.append(int(ci))

                skip_rows = {int(directory_row_0), int(header_row_0)}
                skip_rows.update(int(r) for r in (panel_title_rows or []))
                skip_rows.update(int(r) for r in (panel_header_rows or []))

                data_r0 = int(header_row_0) + 1
                for ri in range(int(data_r0), int(n_rows)):
                    if int(ri) in skip_rows:
                        continue
                    row = values[int(ri)]
                    if not isinstance(row, list):
                        continue
                    for ci in period_cols:
                        if not (0 <= int(ci) < len(row)):
                            continue
                        v = row[int(ci)]
                        if _is_no_data_cell(v):
                            if placeholder_mode == "sparkline":
                                row[int(ci)] = ""
                                sparkline_cells.append((int(ri) + 1, int(ci) + 1))
                            elif placeholder_char:
                                row[int(ci)] = placeholder_char
            except Exception:
                pass

        # -------------------- 离散信号（多/空）上色：仅标记范围，不在此处写样式 --------------------
        # 目标：把“方向/信号/翻转信号”等离散字段，在周期列内按 bull/bear 上色（红/绿），并且每轮刷新可恢复底色。
        # 注意：绝不能对数值字段（例如 成交额/净流/涨跌幅）做“正负号上色”，否则会产生误导。
        direction_metrics = {"方向", "信号", "翻转信号"}
        direction_marks: list[tuple[int, list[tuple[int, int, Any]]]] = []  # (row0, [(col0, pi, value)])
        period_cols: list[tuple[str, int]] = []  # (period_name, col0)
        try:
            header_row = values[int(header_row_0)] if 0 <= int(header_row_0) < len(values) else []
            if isinstance(header_row, list) and len(header_row) >= 4:
                for pi, cell in enumerate(header_row[3:]):
                    s = str(cell).strip()
                    if not s or s == "原始值":
                        break
                    period_cols.append((s, 3 + int(pi)))
        except Exception:
            period_cols = []
        if period_cols:
            for ri in range(int(header_row_0) + 1, int(n_rows)):
                row = values[int(ri)]
                if not isinstance(row, list) or len(row) < 4:
                    continue
                metric = str(row[2]).strip()
                if metric not in direction_metrics:
                    continue
                cells: list[tuple[int, int, Any]] = []
                for pi, (_p, ci) in enumerate(period_cols):
                    if 0 <= int(ci) < len(row):
                        cells.append((int(ci), int(pi), row[int(ci)]))
                if cells:
                    direction_marks.append((int(ri), cells))

        # 顶部一行（元信息+目录）：
        # - 若开启冻结列，Google Sheets 不允许“冻结分割线切开 merged cell”，否则 updateSheetProperties 会 400，
        #   导致 frozenColumnCount 无法生效（用户看到“没有冻结条”）。
        # - 因此：冻结列开启时不做整行横向 merge，靠文本溢出显示即可。
        frozen_cols = _symbol_query_frozen_cols()
        if int(n_cols) >= 2 and int(frozen_cols) <= 0:
            # banner 行（可选）+ 元信息行：整行横向合并（不冻结列时允许）
            if int(banner_rows) > 0:
                merge_ranges.append((0, 1, 0, int(n_cols)))
            merge_ranges.append((int(directory_row_0), int(directory_row_0) + 1, 0, int(n_cols)))

        # 将“面板合并”加入 merge_ranges（与指标组合并共用一套 batch merge）
        for start_0, end_0_excl, _title in panel_blocks:
            if (end_0_excl - start_0) > 1:
                merge_ranges.append((int(start_0), int(end_0_excl), 0, 1))

        # NOTE: 我们会在本函数末尾做“compact grid”（压缩列数/行数），以实现“右侧无单元格”的效果。
        # 因此这里先确保 grid 足够大，避免 values.update 超出当前网格范围而报错。
        self._ensure_grid_size(tab_title, min_rows=n_rows, min_cols=n_cols)

        col_r = _index_to_col(n_cols)
        self._exec(
            self._sheets.spreadsheets()
            .values()
            .update(
                spreadsheetId=self._spreadsheet_id,
                range=f"{tab_title}!A1:{col_r}{n_rows}",
                valueInputOption="RAW",
                body={"values": values},
            ),
            is_write=True,
        )

        # -------------------- sparkline placeholders（纯函数绘制对角线） --------------------
        # 必须在 values.update(RAW) 之后执行：RAW 会把公式当文本写入。
        if placeholder_mode == "sparkline" and sparkline_cells:
            try:
                formula = _sparkline_backslash_formula(locale=getattr(self, "_spreadsheet_locale", None))
                self._apply_cell_formulas(sheet_title=tab_title, cells=sparkline_cells, formula=formula)
            except Exception:
                pass

        # -------------------- directory (single cell, rich links) --------------------
        # 需求：币种查询子表只保留 1 行元信息；目录条目追加到同一单元格内，用中文逗号分隔并保留跳转。
        dir_text: str | None = None
        dir_runs: list[dict[str, Any]] | None = None
        if 0 <= int(directory_row_0) < int(n_rows) and panel_blocks:
            try:
                def idx_len(s: str) -> int:
                    # Sheets API startIndex 使用 UTF-16 code units（emoji 会占 2）
                    return _utf16_len(str(s))

                # 读取 exporter 写入的“元信息基底”，把目录条目拼到后面
                base = ""
                try:
                    base = str((values[int(directory_row_0)][0] if values and values[int(directory_row_0)] else "") or "")
                except Exception:
                    base = ""
                base = str(base).strip()
                if base and (not base.endswith("，")):
                    base = base + "，"

                label = "目录（点击跳转）"
                prefix = base
                if label not in prefix:
                    prefix = prefix + label
                parts: list[str] = [prefix]
                runs: list[dict[str, Any]] = [{"startIndex": 0, "format": {}}]
                pos = idx_len(parts[0])
                item_count = 1
                for start_0, _end_0_excl, title in panel_blocks:
                    # 冻结列开启时，不做整行 merge；目录保持单行溢出显示，不插入换行
                    sep = "，"
                    parts.append(sep)
                    pos += idx_len(sep)

                    # 顶部目录单元格：去掉前缀图标/emoji，避免 RichText startIndex 在不同客户端下错位
                    t = re.sub(r"^[^0-9A-Za-z\u4e00-\u9fff]+\s*", "", str(title or "")).strip() or "-"
                    start = int(pos)
                    parts.append(t)
                    pos += idx_len(t)
                    end = int(pos)

                    url = (
                        f"https://docs.google.com/spreadsheets/d/{self._spreadsheet_id}/edit"
                        f"#gid={int(sh_id)}&range=A{int(start_0) + 1}"
                    )
                    runs.append(
                        {
                            "startIndex": int(start),
                            "format": {
                                "link": {"uri": str(url)},
                                "foregroundColor": _rgb(0.1, 0.4, 0.8),
                                "underline": True,
                            },
                        }
                    )
                    runs.append({"startIndex": int(end), "format": {}})
                    item_count += 1

                parts_s = "".join(parts)
                dir_text = parts_s + ("，" if not parts_s.endswith("，") else "")
                # Sheets API: TextFormatRun.startIndex 必须 < 字符串长度。
                # 我们会在每个条目后追加一个“重置格式”的 run；最后一个条目在字符串末尾时会产生 startIndex==len(text)。
                # 这里统一裁剪掉末尾无效的 run，避免 400。
                text_len = idx_len(dir_text)
                while runs and int(runs[-1].get("startIndex", 0) or 0) >= int(text_len):
                    runs.pop()
                dir_runs = runs
            except Exception:
                dir_text, dir_runs = None, None

        meta = self._meta_get()
        key_rows = f"symtab.{tab_title}.rows"
        key_cols = f"symtab.{tab_title}.cols"
        try:
            r_old = int(str(meta.get(key_rows) or "0").strip() or "0")
        except Exception:
            r_old = 0
        try:
            c_old = int(str(meta.get(key_cols) or "0").strip() or "0")
        except Exception:
            c_old = 0

        # 清理尾部差量：避免旧版残留（比如历史 raw 镜像区、旧结构多余列）。
        # 注意：
        # - 该表默认启用 compact grid（把网格裁剪到 n_rows/n_cols），因此“超出网格的 clear”会直接 400。
        # - 当网格已被裁剪时，超出部分本来就不存在，无需 clear。
        try:
            cur_rows, cur_cols = self._grid_by_title.get(tab_title, (0, 0))
            cur_rows = int(cur_rows or 0)
            cur_cols = int(cur_cols or 0)
        except Exception:
            cur_rows, cur_cols = 0, 0
        if cur_rows <= 0:
            cur_rows = int(n_rows)
        if cur_cols <= 0:
            cur_cols = int(n_cols)

        # 1) 清除“多余行”（仅在当前网格确实大于 n_rows 时执行）
        if int(r_old) > int(n_rows) and int(cur_rows) > int(n_rows):
            end_row = min(int(r_old), int(cur_rows))
            end_col = min(int(max(c_old, n_cols)), int(cur_cols))
            if end_row >= int(n_rows) + 1 and end_col >= 1:
                self._exec(
                    self._sheets.spreadsheets()
                    .values()
                    .clear(
                        spreadsheetId=self._spreadsheet_id,
                        range=f"{tab_title}!A{int(n_rows) + 1}:{_index_to_col(int(end_col))}{int(end_row)}",
                    ),
                    is_write=True,
                )

        # 2) 清除“多余列”（仅在当前网格确实大于 n_cols 时执行）
        if int(c_old) > int(n_cols) and int(cur_cols) > int(n_cols):
            end_col = min(int(c_old), int(cur_cols))
            end_row = min(int(max(r_old, n_rows)), int(cur_rows))
            if end_col >= int(n_cols) + 1 and end_row >= 1:
                self._exec(
                    self._sheets.spreadsheets()
                    .values()
                    .clear(
                        spreadsheetId=self._spreadsheet_id,
                        range=(
                            f"{tab_title}!{_index_to_col(int(n_cols) + 1)}1:{_index_to_col(int(end_col))}{int(end_row)}"
                        ),
                    ),
                    is_write=True,
                )

        # -------------------- style --------------------
        # layout 变更需要 bump style_version，确保冻结行数/表头行/目录行样式能“全量刷新”到新结构
        style_version = "symbol_table_v13"
        key_style_version = f"symtab.{tab_title}.style_version"
        key_style_rows = f"symtab.{tab_title}.style_rows"
        key_style_cols = f"symtab.{tab_title}.style_cols"
        key_style_placeholder = f"symtab.{tab_title}.style_placeholder"
        placeholder_mode = _empty_placeholder_mode()
        placeholder_style = (
            f"char:{_empty_placeholder_char()}"
            if placeholder_mode == "char"
            else ("sparkline" if placeholder_mode == "sparkline" else "off")
        )
        try:
            styled_rows = int(str(meta.get(key_style_rows) or "0").strip() or "0")
        except Exception:
            styled_rows = 0
        try:
            styled_cols = int(str(meta.get(key_style_cols) or "0").strip() or "0")
        except Exception:
            styled_cols = 0

        # 样式覆盖范围：只保证不小于“当前数据行列”与“历史样式范围”，不再强制扩到 800 行。
        # 底部/右侧空白会在 compact grid 阶段被裁剪掉。
        target_rows = int(max(n_rows, styled_rows, 1))
        target_cols = int(max(n_cols, styled_cols, 6))
        need_style = (
            (meta.get(key_style_version) or "") != style_version
            or (meta.get(key_style_placeholder) or "") != placeholder_style
            or target_rows > styled_rows
            or target_cols != styled_cols
        )
        if need_style:
            self._ensure_grid_size(tab_title, min_rows=target_rows, min_cols=target_cols)

            # 清除旧 conditional formatting（避免历史规则残留）
            try:
                ss = self._exec(
                    self._sheets.spreadsheets().get(
                        spreadsheetId=self._spreadsheet_id,
                        fields="sheets(properties(sheetId,title),conditionalFormats)",
                    ),
                    is_write=False,
                )
                cond_cnt = 0
                for sh in ss.get("sheets", []):
                    props = sh.get("properties") or {}
                    if int(props.get("sheetId") or 0) != int(sh_id):
                        continue
                    cond = sh.get("conditionalFormats") or []
                    cond_cnt = len(cond)
                    break
                if cond_cnt > 0:
                    reqs = [
                        {"deleteConditionalFormatRule": {"sheetId": int(sh_id), "index": 0}} for _ in range(cond_cnt)
                    ]
                    self._exec(
                        self._sheets.spreadsheets().batchUpdate(
                            spreadsheetId=self._spreadsheet_id,
                            body={"requests": reqs},
                        ),
                        is_write=True,
                    )
            except Exception:
                pass

            reqs: list[dict[str, Any]] = []

            reqs.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": int(sh_id),
                            "startRowIndex": 0,
                            "endRowIndex": int(target_rows),
                            "startColumnIndex": 0,
                            "endColumnIndex": int(target_cols),
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": _rgb(1.0, 1.0, 1.0),
                                "textFormat": {
                                    "fontFamily": "Arial",
                                    "fontSize": 10,
                                },
                                "horizontalAlignment": "LEFT",
                                "verticalAlignment": "MIDDLE",
                                "wrapStrategy": "CLIP",
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,wrapStrategy)",
                    }
                }
            )

            # widths：更紧凑（提升信息密度）
            fixed_widths = _normalize_fixed_widths(
                _env_int_list("SHEETS_SYMBOL_QUERY_FIXED_COL_WIDTHS"),
                n_cols=int(target_cols),
            )
            if fixed_widths:
                for ci, px in enumerate(fixed_widths):
                    reqs.append(
                        {
                            "updateDimensionProperties": {
                                "range": {
                                    "sheetId": int(sh_id),
                                    "dimension": "COLUMNS",
                                    "startIndex": int(ci),
                                    "endIndex": int(ci + 1),
                                },
                                "properties": {"pixelSize": int(px)},
                                "fields": "pixelSize",
                            }
                        }
                    )
            else:
                w_panel, w_group, w_metric, w_period = _symbol_query_col_widths_px()
                reqs.append(
                    {
                        "updateDimensionProperties": {
                            "range": {"sheetId": int(sh_id), "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                            "properties": {"pixelSize": int(w_panel)},
                            "fields": "pixelSize",
                        }
                    }
                )
                reqs.append(
                    {
                        "updateDimensionProperties": {
                            "range": {"sheetId": int(sh_id), "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2},
                            "properties": {"pixelSize": int(w_group)},
                            "fields": "pixelSize",
                        }
                    }
                )
                reqs.append(
                    {
                        "updateDimensionProperties": {
                            "range": {"sheetId": int(sh_id), "dimension": "COLUMNS", "startIndex": 2, "endIndex": 3},
                            "properties": {"pixelSize": int(w_metric)},
                            "fields": "pixelSize",
                        }
                    }
                )

            raw_block_start_col_0 = getattr(sheet, "raw_block_start_col_0", None)
            try:
                raw_block_start_col_0 = int(raw_block_start_col_0) if raw_block_start_col_0 is not None else None
            except Exception:
                raw_block_start_col_0 = None

            if not fixed_widths:
                # columns >= C：周期列更窄；若存在 raw 镜像区，则 display/raw 区域分别设置宽度并可隐藏
                for ci in range(3, int(target_cols)):
                    px = int(w_period)
                    if raw_block_start_col_0 is not None and 0 <= raw_block_start_col_0 < int(n_cols):
                        if ci == int(raw_block_start_col_0):
                            px = 26  # 分隔列
                        elif int(raw_block_start_col_0) < ci < int(n_cols):
                            px = max(int(w_period) - 6, 60)  # raw 周期列更窄
                    reqs.append(
                        {
                            "updateDimensionProperties": {
                                "range": {
                                    "sheetId": int(sh_id),
                                    "dimension": "COLUMNS",
                                    "startIndex": ci,
                                    "endIndex": ci + 1,
                                },
                                "properties": {"pixelSize": int(px)},
                                "fields": "pixelSize",
                            }
                        }
                    )

            # 周期列右对齐
            if target_cols > 3:
                reqs.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": 0,
                                "endRowIndex": int(target_rows),
                                "startColumnIndex": 3,
                                "endColumnIndex": int(target_cols),
                            },
                            "cell": {"userEnteredFormat": {"horizontalAlignment": "RIGHT", "wrapStrategy": "CLIP"}},
                            "fields": "userEnteredFormat(horizontalAlignment,wrapStrategy)",
                        }
                    }
                )

            # display 周期列灰白交替（对齐主看板视觉习惯）
            try:
                header_row = values[int(header_row_0)] if 0 <= int(header_row_0) < len(values) else []
                periods: list[str] = []
                if isinstance(header_row, list) and len(header_row) >= 4:
                    for cell in header_row[3:]:
                        s = str(cell).strip()
                        if not s or s == "原始值":
                            break
                        periods.append(s)
                for pi, _p in enumerate(periods):
                    if (pi % 2) == 1:  # 给“奇数周期列”上淡灰底
                        ci = 3 + int(pi)
                        reqs.append(
                            {
                                "repeatCell": {
                                    "range": {
                                        "sheetId": int(sh_id),
                                        "startRowIndex": 0,
                                        "endRowIndex": int(target_rows),
                                        "startColumnIndex": int(ci),
                                        "endColumnIndex": int(ci + 1),
                                    },
                                    "cell": {"userEnteredFormat": {"backgroundColor": _rgb(0.975, 0.98, 0.99)}},
                                    "fields": "userEnteredFormat(backgroundColor)",
                                }
                            }
                        )
            except Exception:
                pass

            # raw 镜像区：浅灰底 + 可隐藏（默认隐藏）
            if raw_block_start_col_0 is not None and 0 <= raw_block_start_col_0 < int(n_cols):
                raw_sep = int(raw_block_start_col_0)
                raw_end = int(n_cols)

                # separator column subtle bg
                reqs.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": 0,
                                "endRowIndex": int(target_rows),
                                "startColumnIndex": raw_sep,
                                "endColumnIndex": raw_sep + 1,
                            },
                            "cell": {"userEnteredFormat": {"backgroundColor": _rgb(0.97, 0.97, 0.97)}},
                            "fields": "userEnteredFormat(backgroundColor)",
                        }
                    }
                )

                # raw columns bg
                if raw_end > raw_sep + 1:
                    reqs.append(
                        {
                            "repeatCell": {
                                "range": {
                                    "sheetId": int(sh_id),
                                    "startRowIndex": 0,
                                    "endRowIndex": int(target_rows),
                                    "startColumnIndex": raw_sep + 1,
                                    "endColumnIndex": raw_end,
                                },
                                "cell": {"userEnteredFormat": {"backgroundColor": _rgb(0.985, 0.985, 0.99)}},
                                "fields": "userEnteredFormat(backgroundColor)",
                            }
                        }
                    )

                raw_mode = (os.environ.get("SHEETS_SYMBOL_QUERY_RAW_MODE", "off") or "off").strip().lower()
                if raw_mode not in {"hidden", "show", "off"}:
                    raw_mode = "off"
                if raw_mode != "off":
                    reqs.append(
                        {
                            "updateDimensionProperties": {
                                "range": {
                                    "sheetId": int(sh_id),
                                    "dimension": "COLUMNS",
                                    "startIndex": raw_sep,
                                    "endIndex": raw_end,
                                },
                                "properties": {"hiddenByUser": raw_mode == "hidden"},
                                "fields": "hiddenByUser",
                            }
                        }
                    )

            # freeze top info rows
            reqs.append(
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": int(sh_id),
                            "gridProperties": {
                                "frozenRowCount": int(int(header_row_0) + 1),
                                "frozenColumnCount": int(_symbol_query_frozen_cols()),
                            },
                        },
                        "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
                    }
                }
            )

            # banner 行（可选）：全表首行广告位
            if int(banner_rows) > 0:
                try:
                    banner_lines = int(banner_line_count or 1)
                except Exception:
                    banner_lines = 1
                banner_lines = max(1, min(int(banner_lines), 6))
                banner_row_px = int(21 * int(banner_lines))

                reqs.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": 0,
                                "endRowIndex": 1,
                                "startColumnIndex": 0,
                                "endColumnIndex": int(target_cols),
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": _rgb(1.0, 0.97, 0.86),
                                    "textFormat": {"bold": True},
                                    "horizontalAlignment": "LEFT",
                                    "verticalAlignment": "MIDDLE",
                                    "wrapStrategy": "OVERFLOW_CELL",
                                }
                            },
                            "fields": "userEnteredFormat(backgroundColor,textFormat.bold,horizontalAlignment,verticalAlignment,wrapStrategy)",
                        }
                    }
                )
                reqs.append(
                    {
                        "updateDimensionProperties": {
                            "range": {"sheetId": int(sh_id), "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
                            "properties": {"pixelSize": int(banner_row_px)},
                            "fields": "pixelSize",
                        }
                    }
                )
                # 视觉合并：遮蔽 banner 行内部竖线（冻结列开启时无法真 merge）
                reqs.append(
                    {
                        "updateBorders": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": 0,
                                "endRowIndex": 1,
                                "startColumnIndex": 0,
                                "endColumnIndex": int(target_cols),
                            },
                            "innerVertical": {"style": "SOLID", "width": 1, "color": _rgb(1.0, 0.97, 0.86)},
                        }
                    }
                )

            # meta+directory 行强调（始终 1 行；目录追加到同一单元格）
            meta_r0 = int(directory_row_0)
            reqs.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": int(sh_id),
                            "startRowIndex": int(meta_r0),
                            "endRowIndex": int(meta_r0) + 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": int(target_cols),
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": _rgb(0.96, 0.97, 0.98),
                                "textFormat": {"bold": True},
                                "horizontalAlignment": "LEFT",
                                "verticalAlignment": "MIDDLE",
                                "wrapStrategy": "OVERFLOW_CELL",
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat.bold,horizontalAlignment,verticalAlignment,wrapStrategy)",
                    }
                }
            )
            # meta 行行高：固定默认，避免被 banner 多行撑高后“连带影响”
            reqs.append(
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": int(sh_id),
                            "dimension": "ROWS",
                            "startIndex": int(meta_r0),
                            "endIndex": int(meta_r0) + 1,
                        },
                        "properties": {"pixelSize": 21},
                        "fields": "pixelSize",
                    }
                }
            )

            # global header row emphasis
            rrh = max(int(header_row_0), 0)
            reqs.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": int(sh_id),
                            "startRowIndex": int(rrh),
                            "endRowIndex": int(rrh + 1),
                            "startColumnIndex": 0,
                            "endColumnIndex": int(target_cols),
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": _rgb(0.93, 0.94, 0.96),
                                "textFormat": {"bold": True},
                                "horizontalAlignment": "CENTER",
                                "verticalAlignment": "MIDDLE",
                                "wrapStrategy": "CLIP",
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat.bold,horizontalAlignment,verticalAlignment,wrapStrategy)",
                    }
                }
            )

            # panel blocks (A列) 背景交替 + 居中加粗
            panel_colors = [
                _rgb(0.90, 0.95, 0.98),
                _rgb(0.94, 0.92, 0.98),
            ]
            for bi, (start_0, end_0_excl, _title) in enumerate(panel_blocks):
                if end_0_excl <= start_0:
                    continue
                bg = panel_colors[int(bi) % len(panel_colors)]
                reqs.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": int(start_0),
                                "endRowIndex": int(end_0_excl),
                                "startColumnIndex": 0,
                                "endColumnIndex": 1,
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": bg,
                                    "textFormat": {"bold": True},
                                    "horizontalAlignment": "CENTER",
                                    "verticalAlignment": "MIDDLE",
                                    "wrapStrategy": "CLIP",
                                }
                            },
                            "fields": "userEnteredFormat(backgroundColor,textFormat.bold,horizontalAlignment,verticalAlignment,wrapStrategy)",
                        }
                    }
                )

            # panel title rows
            for r in panel_title_rows:
                rr0 = max(int(r) - 1, 0)
                reqs.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": rr0,
                                "endRowIndex": rr0 + 1,
                                "startColumnIndex": 0,
                                "endColumnIndex": int(target_cols),
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": _rgb(0.86, 0.90, 0.96),
                                    "textFormat": {"bold": True},
                                }
                            },
                            "fields": "userEnteredFormat(backgroundColor,textFormat)",
                        }
                    }
                )

            # panel header rows
            for r in panel_header_rows:
                rr0 = max(int(r) - 1, 0)
                reqs.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": rr0,
                                "endRowIndex": rr0 + 1,
                                "startColumnIndex": 0,
                                "endColumnIndex": int(target_cols),
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": _rgb(0.93, 0.94, 0.96),
                                    "textFormat": {"bold": True},
                                }
                            },
                            "fields": "userEnteredFormat(backgroundColor,textFormat.bold)",
                        }
                    }
                )

            self._exec(
                self._sheets.spreadsheets().batchUpdate(
                    spreadsheetId=self._spreadsheet_id,
                    body={"requests": reqs},
                ),
                is_write=True,
            )
            self._meta_set(
                {
                    key_style_version: style_version,
                    key_style_rows: str(target_rows),
                    key_style_cols: str(target_cols),
                    key_style_placeholder: placeholder_style,
                }
            )

        # -------------------- freeze + top-row overflow（每次都对齐） --------------------
        # frozenColumnCount 变更不会触发 need_style，但会影响“冻结条”是否出现。
        # 如果仅在 need_style 时设置冻结列，用户会看到“环境变量已改但冻结没生效”。
        try:
            self._set_sheet_grid_properties(
                tab_title,
                frozen_row_count=int(int(header_row_0) + 1),
                frozen_column_count=_symbol_query_frozen_cols(),
            )
        except Exception:
            pass

        # 列宽：每次都对齐，避免“不同币种 tab 的列宽漂移”（手动拖拽/旧版样式遗留会导致不一致）
        try:
            col_end = int(max(n_cols, 4))
            reqs_w: list[dict[str, Any]] = []
            fixed_widths = _normalize_fixed_widths(
                _env_int_list("SHEETS_SYMBOL_QUERY_FIXED_COL_WIDTHS"),
                n_cols=int(col_end),
            )
            if fixed_widths:
                for ci, px in enumerate(fixed_widths):
                    reqs_w.append(
                        {
                            "updateDimensionProperties": {
                                "range": {
                                    "sheetId": int(sh_id),
                                    "dimension": "COLUMNS",
                                    "startIndex": int(ci),
                                    "endIndex": int(ci + 1),
                                },
                                "properties": {"pixelSize": int(px)},
                                "fields": "pixelSize",
                            }
                        }
                    )
            else:
                w_panel, w_group, w_metric, w_period = _symbol_query_col_widths_px()
                raw_block_start_col_0 = getattr(sheet, "raw_block_start_col_0", None)
                try:
                    raw_block_start_col_0 = int(raw_block_start_col_0) if raw_block_start_col_0 is not None else None
                except Exception:
                    raw_block_start_col_0 = None

                # A/B/C 固定宽度（层级列）
                reqs_w.append(
                    {
                        "updateDimensionProperties": {
                            "range": {"sheetId": int(sh_id), "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                            "properties": {"pixelSize": int(w_panel)},
                            "fields": "pixelSize",
                        }
                    }
                )
                reqs_w.append(
                    {
                        "updateDimensionProperties": {
                            "range": {"sheetId": int(sh_id), "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2},
                            "properties": {"pixelSize": int(w_group)},
                            "fields": "pixelSize",
                        }
                    }
                )
                reqs_w.append(
                    {
                        "updateDimensionProperties": {
                            "range": {"sheetId": int(sh_id), "dimension": "COLUMNS", "startIndex": 2, "endIndex": 3},
                            "properties": {"pixelSize": int(w_metric)},
                            "fields": "pixelSize",
                        }
                    }
                )

                # 其余列统一宽度（按 raw 镜像区分段）
                if raw_block_start_col_0 is not None and 0 <= int(raw_block_start_col_0) < int(col_end):
                    raw_sep = int(raw_block_start_col_0)
                    # display 周期列
                    if raw_sep > 3:
                        reqs_w.append(
                            {
                                "updateDimensionProperties": {
                                    "range": {
                                        "sheetId": int(sh_id),
                                        "dimension": "COLUMNS",
                                        "startIndex": 3,
                                        "endIndex": int(raw_sep),
                                    },
                                    "properties": {"pixelSize": int(w_period)},
                                    "fields": "pixelSize",
                                }
                            }
                        )
                    # 分隔列
                    reqs_w.append(
                        {
                            "updateDimensionProperties": {
                                "range": {
                                    "sheetId": int(sh_id),
                                    "dimension": "COLUMNS",
                                    "startIndex": int(raw_sep),
                                    "endIndex": int(min(raw_sep + 1, col_end)),
                                },
                                "properties": {"pixelSize": 26},
                                "fields": "pixelSize",
                            }
                        }
                    )
                    # raw 周期列
                    if col_end > raw_sep + 1:
                        raw_w = max(int(w_period) - 8, 60)
                        reqs_w.append(
                            {
                                "updateDimensionProperties": {
                                    "range": {
                                        "sheetId": int(sh_id),
                                        "dimension": "COLUMNS",
                                        "startIndex": int(raw_sep + 1),
                                        "endIndex": int(col_end),
                                    },
                                    "properties": {"pixelSize": int(raw_w)},
                                    "fields": "pixelSize",
                                }
                            }
                        )
                else:
                    # 无 raw 区：周期列统一 w_period
                    if col_end > 3:
                        reqs_w.append(
                            {
                                "updateDimensionProperties": {
                                    "range": {
                                        "sheetId": int(sh_id),
                                        "dimension": "COLUMNS",
                                        "startIndex": 3,
                                        "endIndex": int(col_end),
                                    },
                                    "properties": {"pixelSize": int(w_period)},
                                    "fields": "pixelSize",
                                }
                            }
                        )

            self._exec(
                self._sheets.spreadsheets().batchUpdate(
                    spreadsheetId=self._spreadsheet_id,
                    body={"requests": reqs_w},
                ),
                is_write=True,
            )
        except Exception:
            pass
        try:
            reqs_align: list[dict[str, Any]] = []

            # 全部展开：解除此前手工隐藏的列（例如之前隐藏过 1m）
            reqs_align.append(
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": int(sh_id),
                            "dimension": "COLUMNS",
                            "startIndex": 0,
                            "endIndex": int(target_cols),
                        },
                        "properties": {"hiddenByUser": False},
                        "fields": "hiddenByUser",
                    }
                }
            )

            # Row1（元信息+目录）保持“单行溢出显示”，避免自动换行挤压信息密度
            reqs_align.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": int(sh_id),
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": int(target_cols),
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "horizontalAlignment": "LEFT",
                                "verticalAlignment": "MIDDLE",
                                "wrapStrategy": "OVERFLOW_CELL",
                            }
                        },
                        "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment,wrapStrategy)",
                    }
                }
            )

            # 需求：币种查询表的“列头/表头类型字段”必须上下左右居中 + 加粗（每次都强制，防手工样式漂移）
            # 注意：这里只覆盖 对齐+加粗，不覆盖背景色/换行策略，避免影响“数据区”既有样式。
            rrh = max(int(header_row_0), 0)
            reqs_align.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": int(sh_id),
                            "startRowIndex": int(rrh),
                            "endRowIndex": int(rrh + 1),
                            "startColumnIndex": 0,
                            "endColumnIndex": int(target_cols),
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "textFormat": {"bold": True},
                                "horizontalAlignment": "CENTER",
                                "verticalAlignment": "MIDDLE",
                            }
                        },
                        "fields": "userEnteredFormat(textFormat.bold,horizontalAlignment,verticalAlignment)",
                    }
                }
            )
            # 需求：行表头/列表头也要规范（面板/指标组/指标 这三列）
            # - 从全局表头行开始，强制 A..C 上下左右居中 + 加粗
            # - 不影响周期列的数据格式（数值/右对齐等）
            reqs_align.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": int(sh_id),
                            "startRowIndex": int(rrh),
                            "endRowIndex": int(n_rows),
                            "startColumnIndex": 0,
                            "endColumnIndex": 3,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "textFormat": {"bold": True},
                                "horizontalAlignment": "CENTER",
                                "verticalAlignment": "MIDDLE",
                                "wrapStrategy": "CLIP",
                            }
                        },
                        "fields": "userEnteredFormat(textFormat.bold,horizontalAlignment,verticalAlignment,wrapStrategy)",
                    }
                }
            )
            for r in (panel_title_rows or []):
                rr0 = max(int(r) - 1, 0)
                reqs_align.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": int(rr0),
                                "endRowIndex": int(rr0 + 1),
                                "startColumnIndex": 0,
                                "endColumnIndex": int(target_cols),
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "textFormat": {"bold": True},
                                    "horizontalAlignment": "CENTER",
                                    "verticalAlignment": "MIDDLE",
                                }
                            },
                            "fields": "userEnteredFormat(textFormat.bold,horizontalAlignment,verticalAlignment)",
                        }
                    }
                )
            for r in (panel_header_rows or []):
                rr0 = max(int(r) - 1, 0)
                reqs_align.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": int(rr0),
                                "endRowIndex": int(rr0 + 1),
                                "startColumnIndex": 0,
                                "endColumnIndex": int(target_cols),
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "textFormat": {"bold": True},
                                    "horizontalAlignment": "CENTER",
                                    "verticalAlignment": "MIDDLE",
                                }
                            },
                            "fields": "userEnteredFormat(textFormat.bold,horizontalAlignment,verticalAlignment)",
                    }
                }
            )

            # raw 镜像区：按 raw_mode 控制显示/隐藏（默认 off）；放在“全展开”之后以覆盖其效果
            try:
                raw_block_start_col_0 = getattr(sheet, "raw_block_start_col_0", None)
                raw_block_start_col_0 = int(raw_block_start_col_0) if raw_block_start_col_0 is not None else None
            except Exception:
                raw_block_start_col_0 = None
            if raw_block_start_col_0 is not None and 0 <= int(raw_block_start_col_0) < int(n_cols):
                raw_sep = int(raw_block_start_col_0)
                raw_end = int(n_cols)
                raw_mode = (os.environ.get("SHEETS_SYMBOL_QUERY_RAW_MODE", "off") or "off").strip().lower()
                if raw_mode not in {"hidden", "show", "off"}:
                    raw_mode = "off"
                if raw_mode != "off":
                    reqs_align.append(
                        {
                            "updateDimensionProperties": {
                                "range": {
                                    "sheetId": int(sh_id),
                                    "dimension": "COLUMNS",
                                    "startIndex": int(raw_sep),
                                    "endIndex": int(raw_end),
                                },
                                "properties": {"hiddenByUser": raw_mode == "hidden"},
                                "fields": "hiddenByUser",
                            }
                        }
                    )

            # 周期列灰白底色（每轮覆盖，避免历史残留红/绿/手工样式漂移）
            # 注意：
            # - bull/bear（红/绿）只会覆盖“方向/信号/翻转信号”行
            # - 因此必须先把周期列统一刷回灰白底色，保证其它数值行（如 量比/MACD柱/带宽评分）不会残留颜色
            if period_cols:
                bg_period_even = _rgb(1.0, 1.0, 1.0)
                bg_period_odd = _rgb(0.975, 0.98, 0.99)  # 与币种查询表默认灰白交替一致
                body_r0 = int(header_row_0) + 1
                body_r1 = int(n_rows)
                if body_r1 > body_r0:
                    for pi, (_p, ci) in enumerate(period_cols):
                        bg = bg_period_odd if (int(pi) % 2 == 1) else bg_period_even
                        reqs_align.append(
                            {
                                "repeatCell": {
                                    "range": {
                                        "sheetId": int(sh_id),
                                        "startRowIndex": int(body_r0),
                                        "endRowIndex": int(body_r1),
                                        "startColumnIndex": int(ci),
                                        "endColumnIndex": int(ci) + 1,
                                    },
                                    "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                                    "fields": "userEnteredFormat.backgroundColor",
                                }
                            }
                        )

            # 离散信号上色：多/空 -> 绿/红（每轮覆盖，避免残留）
            if direction_marks and period_cols:
                bg_period_even = _rgb(1.0, 1.0, 1.0)
                bg_period_odd = _rgb(0.975, 0.98, 0.99)  # 对齐“周期列灰白交替”底色
                bg_bull = _rgb(0.776, 0.937, 0.808)  # light green (#C6EFCE)
                bg_bear = _rgb(1.0, 0.780, 0.808)  # light red (#FFC7CE)

                for row0, cells in direction_marks:
                    if int(row0) < 0 or int(row0) >= int(n_rows):
                        continue
                    if not cells:
                        continue

                    # 按列排序，便于合并同色连续区间
                    cells_sorted = sorted(cells, key=lambda t: int(t[0]))

                    seg_c0: int | None = None
                    seg_bg: dict[str, float] | None = None
                    prev_c0: int | None = None

                    def flush_seg() -> None:
                        nonlocal seg_c0, seg_bg, prev_c0
                        if seg_c0 is None or seg_bg is None or prev_c0 is None:
                            return
                        reqs_align.append(
                            {
                                "repeatCell": {
                                    "range": {
                                        "sheetId": int(sh_id),
                                        "startRowIndex": int(row0),
                                        "endRowIndex": int(row0) + 1,
                                        "startColumnIndex": int(seg_c0),
                                        "endColumnIndex": int(prev_c0) + 1,
                                    },
                                    "cell": {"userEnteredFormat": {"backgroundColor": seg_bg}},
                                    "fields": "userEnteredFormat.backgroundColor",
                                }
                            }
                        )
                        seg_c0 = None
                        seg_bg = None
                        prev_c0 = None

                    for c0, pi, v in cells_sorted:
                        base_bg = bg_period_odd if (int(pi) % 2 == 1) else bg_period_even
                        cls = _classify_bull_bear(v)
                        if cls > 0:
                            bg = bg_bull
                        elif cls < 0:
                            bg = bg_bear
                        else:
                            bg = base_bg

                        if seg_c0 is None:
                            seg_c0 = int(c0)
                            seg_bg = bg
                            prev_c0 = int(c0)
                            continue
                        if prev_c0 is not None and int(c0) == int(prev_c0) + 1 and bg == seg_bg:
                            prev_c0 = int(c0)
                            continue
                        flush_seg()
                        seg_c0 = int(c0)
                        seg_bg = bg
                        prev_c0 = int(c0)

                    flush_seg()

            self._exec(
                self._sheets.spreadsheets().batchUpdate(
                    spreadsheetId=self._spreadsheet_id,
                    body={"requests": reqs_align},
                ),
                is_write=True,
            )
        except Exception:
            pass

        # -------------------- compact grid（只显示“有用的列”） --------------------
        # 解释：Google Sheets 的“网格”不是按数据自动生成的，默认每个 sheet 有固定 row/col 数。
        # 通过 updateSheetProperties.gridProperties.columnCount/rowCount 可以让列/行在 UI 中“消失”，
        # 从而达到你看到的“只有有限几列，其它区域是纯空白背景、无单元格”的效果。
        compact_grid = (os.environ.get("SHEETS_SYMBOL_QUERY_COMPACT_GRID", "1") or "1").strip() != "0"
        if compact_grid:
            try:
                cur_rows, cur_cols = self._grid_by_title.get(tab_title, (0, 0))
            except Exception:
                cur_rows, cur_cols = 0, 0

            # 收缩列数 + 行数：币种查询子表是“完全托管展示面”，允许把底部/右侧空白网格彻底裁剪掉。
            want_rows = int(n_rows)
            want_cols = int(n_cols)
            if int(cur_cols or 0) != int(want_cols) or int(cur_rows or 0) != int(want_rows):
                self._set_sheet_grid_properties(
                    tab_title,
                    row_count=want_rows,
                    col_count=want_cols,
                    frozen_row_count=int(int(header_row_0) + 1),
                    frozen_column_count=_symbol_query_frozen_cols(),
                )

        # -------------------- merges（指标组列合并） --------------------
        if merge_ranges:
            reqs: list[dict[str, Any]] = []
            for rg in merge_ranges:
                try:
                    r0, r1, c0, c1 = rg  # 0-based, end exclusive
                except Exception:
                    continue
                try:
                    r0 = int(r0)
                    r1 = int(r1)
                    c0 = int(c0)
                    c1 = int(c1)
                except Exception:
                    continue
                if r0 < 0 or r1 <= r0:
                    continue
                if c0 < 0 or c1 <= c0:
                    continue
                if r0 >= n_rows:
                    continue
                if r1 > n_rows:
                    r1 = n_rows
                if c0 >= n_cols:
                    continue
                if c1 > n_cols:
                    c1 = n_cols
                # mergeCells 允许“单列纵向合并”或“单行横向合并”，
                # 只要范围内的单元格数量 > 1 就应该执行。
                if (r1 - r0) <= 1 and (c1 - c0) <= 1:
                    continue
                reqs.append(
                    {
                        "mergeCells": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": int(r0),
                                "endRowIndex": int(r1),
                                "startColumnIndex": int(c0),
                                "endColumnIndex": int(c1),
                            },
                            "mergeType": "MERGE_ALL",
                        }
                    }
                )
            if reqs:
                try:
                    self._exec(
                        self._sheets.spreadsheets().batchUpdate(
                            spreadsheetId=self._spreadsheet_id,
                            body={"requests": reqs},
                        ),
                        is_write=True,
                    )
                except Exception as exc:
                    # 不吞错：合并失败会直接导致“面板列空白/指标组重复”，属于高可见问题
                    print(f"⚠️ symtab.merge_failed tab={tab_title} merges={len(reqs)} {type(exc).__name__}: {exc}")

        # -------------------- directory richtext links (after merges) --------------------
        if dir_text and dir_runs:
            try:
                self._exec(
                    self._sheets.spreadsheets().batchUpdate(
                        spreadsheetId=self._spreadsheet_id,
                        body={
                            "requests": [
                                {
                                    "updateCells": {
                                        "range": {
                                            "sheetId": int(sh_id),
                                            "startRowIndex": int(directory_row_0),
                                            "endRowIndex": int(directory_row_0) + 1,
                                            "startColumnIndex": 0,
                                            "endColumnIndex": 1,
                                        },
                                        "rows": [
                                            {
                                                "values": [
                                                    {
                                                        "userEnteredValue": {"stringValue": str(dir_text)},
                                                        "textFormatRuns": dir_runs,
                                                    }
                                                ]
                                            }
                                        ],
                                        "fields": "userEnteredValue,textFormatRuns",
                                    }
                                }
                            ]
                        },
                    ),
                    is_write=True,
                )
            except Exception as exc:
                print(f"⚠️ symtab.dir_links_failed tab={tab_title} {type(exc).__name__}: {exc}")

        # 周期列不再使用 hiddenByUser 折叠：已在 values 阶段直接删除列（见上方 drop_periods）。

        self._meta_set({key_rows: str(n_rows), key_cols: str(n_cols)})
        return {"ok": True, "tab": tab_title, "rows": n_rows, "cols": n_cols}

    # ==================== polymarket stats tab ====================
    def write_polymarket_stats_tab(self, *, tab_title: str, sheet: Any) -> dict[str, Any]:
        """
        覆盖写 Polymarket 统计子表（真表格，分段 CSV）：
        - 第 1 行：元信息（单单元格，中文逗号分隔）
        - 第 2 行：目录（单单元格，中文逗号分隔，带跳转超链接）
        - 多个分段：标题行（整行合并）+ 表头行 + 数据行
        - 通过 meta 记录上次 rows/cols，仅清理尾部差量，避免整表 clear 带来的闪烁
        """
        self.ensure_sheet(title=tab_title)
        self._refresh_sheet_map()

        sh_id = self._sheet_id_by_title.get(tab_title)
        if sh_id is None:
            self._refresh_sheet_map()
            sh_id = self._sheet_id_by_title.get(tab_title)
        if sh_id is None:
            raise RuntimeError(f"missing_sheet:{tab_title}")

        # 先 unmerge，避免旧版合并残留导致 values.update 报错或结构错乱
        try:
            self._exec(
                self._sheets.spreadsheets().batchUpdate(
                    spreadsheetId=self._spreadsheet_id,
                    body={"requests": [{"unmergeCells": {"range": {"sheetId": int(sh_id)}}}]},
                ),
                is_write=True,
            )
        except Exception:
            pass

        values = getattr(sheet, "values", None) or []
        n_rows = int(getattr(sheet, "n_rows", 0) or len(values))
        n_cols = int(getattr(sheet, "n_cols", 0) or (len(values[0]) if values else 0))
        panel_title_rows = list(getattr(sheet, "panel_title_rows", []) or [])
        panel_header_rows = list(getattr(sheet, "panel_header_rows", []) or [])
        merge_ranges = list(getattr(sheet, "merge_ranges", []) or [])

        if not values or n_rows <= 0 or n_cols <= 0:
            values = [["Polymarket统计，错误，导出为空"]]
            n_rows, n_cols = 1, 1

        # 统一补齐行长度，避免 merge/style 计算时行长度不一致
        n_cols2 = max((len(r) for r in values if isinstance(r, list)), default=n_cols or 1)
        n_cols = int(max(int(n_cols2), 1))
        for row in values:
            if isinstance(row, list) and len(row) < int(n_cols):
                row.extend([""] * (int(n_cols) - len(row)))

        # -------------------- layout: report partitions / grid cards --------------------
        # 默认仅对 Polymarket统计 生效；避免影响 Polymarket事件 等“单表明细”子表。
        # - report：纵向报表分区（推荐，信息密度高、观感更像 BI）
        # - grid/masonry：卡片网格（历史方案）
        layout = (os.environ.get("SHEETS_POLYMARKET_STATS_LAYOUT", "report") or "report").strip().lower()
        want_report = (
            tab_title == self._tab_polymarket_stats
            and layout in {"report", "report_v2", "partition", "sections"}
            and bool(panel_title_rows)
            and bool(panel_header_rows)
        )
        want_grid = (
            tab_title == self._tab_polymarket_stats
            and layout in {"grid", "masonry"}
            and bool(panel_title_rows)
            and bool(panel_header_rows)
        )
        if want_report:
            split_enabled = (os.environ.get("SHEETS_POLYMARKET_STATS_SPLIT", "1") or "1").strip() != "0"
            if split_enabled:
                return self._write_polymarket_stats_tabs_split_report(
                    tab_title=tab_title,
                    values=values,
                    panel_title_rows=panel_title_rows,
                    panel_header_rows=panel_header_rows,
                )
            return self._write_polymarket_stats_tab_report(
                tab_title=tab_title,
                sh_id=int(sh_id),
                values=values,
                panel_title_rows=panel_title_rows,
                panel_header_rows=panel_header_rows,
            )
        if want_grid:
            return self._write_polymarket_stats_tab_grid(
                tab_title=tab_title,
                sh_id=int(sh_id),
                values=values,
                panel_title_rows=panel_title_rows,
                panel_header_rows=panel_header_rows,
            )

        # -------------------- top banner（全表首行广告位） --------------------
        banner_raw = _read_top_banner_raw(prefer_dashboard=False)
        banner_text, banner_line_count = _format_dashboard_banner_text(str(banner_raw or ""))
        banner_rows = 1 if banner_text else 0
        if int(banner_rows) > 0:
            # 注入到第 1 行：整表下移 1 行（row index / merge ranges 同步 shift）
            values.insert(0, [banner_text] + [""] * (int(n_cols) - 1))
            panel_title_rows = [int(r) + 1 for r in panel_title_rows]
            panel_header_rows = [int(r) + 1 for r in panel_header_rows]
            merge_ranges2: list[tuple[int, int, int, int]] = []
            for rg in merge_ranges:
                try:
                    r0, r1, c0, c1 = rg
                except Exception:
                    continue
                try:
                    merge_ranges2.append((int(r0) + 1, int(r1) + 1, int(c0), int(c1)))
                except Exception:
                    continue
            merge_ranges = merge_ranges2
            n_rows = int(len(values))

        # directory 行（0-based；会在写入前插入该行）
        directory_row_0 = int(banner_rows) + 1

        # -------------------- directory row (row2) --------------------
        # 需求：目录单独占 1 行，冻结在顶部，避免塞进 A1 导致过长/易混乱。
        dir_text: str | None = None
        dir_runs: list[dict[str, Any]] | None = None
        if panel_title_rows and values and isinstance(values[0], list) and values[0]:
            try:
                def idx_len(s: str) -> int:
                    return _utf16_len(str(s))

                def strip_leading_emoji(s: str) -> str:
                    return re.sub(r"^[^0-9A-Za-z\u4e00-\u9fff]+\s*", "", str(s or "")).strip()

                label = "目录（点击跳转）"
                prefix = label

                parts: list[str] = [prefix]
                runs: list[dict[str, Any]] = [{"startIndex": 0, "format": {}}]
                pos = int(idx_len(prefix))
                titles = sorted({int(r) for r in panel_title_rows if int(r) >= 2 and int(r) <= int(n_rows)})
                for r1 in titles:
                    r0 = int(r1) - 1
                    title = ""
                    try:
                        title = str(values[int(r0)][0] or "")
                    except Exception:
                        title = ""
                    title = strip_leading_emoji(title) or "-"

                    sep = "，"
                    parts.append(sep)
                    pos += idx_len(sep)

                    start = int(pos)
                    parts.append(title)
                    pos += idx_len(title)
                    end = int(pos)

                    # NOTE: 我们会在写入 values 前插入目录行，所以跳转行号需要 +1。
                    url = (
                        f"https://docs.google.com/spreadsheets/d/{self._spreadsheet_id}/edit"
                        f"#gid={int(sh_id)}&range=A{int(r1 + 1)}"
                    )
                    runs.append(
                        {
                            "startIndex": int(start),
                            "format": {
                                "link": {"uri": str(url)},
                                "foregroundColor": _rgb(0.1, 0.4, 0.8),
                                "underline": True,
                            },
                        }
                    )
                    runs.append({"startIndex": int(end), "format": {}})

                dir_text = "".join(parts)
                text_len = idx_len(dir_text)
                while runs and int(runs[-1].get("startIndex", 0) or 0) >= int(text_len):
                    runs.pop()
                dir_runs = runs
            except Exception:
                dir_text, dir_runs = None, None

        # 插入目录行到 meta 行之后（并同步 shift 行号相关结构）
        values.insert(int(directory_row_0), [str(dir_text or "")] + [""] * (int(n_cols) - 1))
        panel_title_rows = [int(r) + 1 for r in panel_title_rows]
        panel_header_rows = [int(r) + 1 for r in panel_header_rows]
        merge_ranges2: list[tuple[int, int, int, int]] = []
        for rg in merge_ranges:
            try:
                r0, r1, c0, c1 = rg
            except Exception:
                continue
            try:
                r0 = int(r0)
                r1 = int(r1)
                c0 = int(c0)
                c1 = int(c1)
            except Exception:
                continue
            if r0 >= int(directory_row_0):
                r0 += 1
                r1 += 1
            merge_ranges2.append((int(r0), int(r1), int(c0), int(c1)))
        merge_ranges = merge_ranges2

        n_rows = int(len(values))

        # 保底：若 exporter 未给 merge_ranges，这里将“第一行元信息”合并
        if not merge_ranges and int(n_cols) > 1:
            if int(banner_rows) > 0:
                merge_ranges.append((0, 1, 0, int(n_cols)))  # banner
            merge_ranges.append((int(banner_rows), int(banner_rows) + 1, 0, int(n_cols)))  # meta
        # 目录行整行合并
        if int(n_cols) > 1:
            merge_ranges.append((int(directory_row_0), int(directory_row_0) + 1, 0, int(n_cols)))

        # NOTE: 先确保 grid 足够大，避免 values.update 超出当前网格范围而报错。
        self._ensure_grid_size(tab_title, min_rows=n_rows, min_cols=n_cols)

        col_r = _index_to_col(n_cols)
        self._exec(
            self._sheets.spreadsheets()
            .values()
            .update(
                spreadsheetId=self._spreadsheet_id,
                range=f"{tab_title}!A1:{col_r}{n_rows}",
                valueInputOption="RAW",
                body={"values": values},
            ),
            is_write=True,
        )

        # tail clear（避免历史残留）
        # 注意：当开启 compact grid（默认）时，我们会把 gridProperties 的 rowCount/columnCount
        # 收敛到 n_rows/n_cols，超出区域会“物理消失”，不需要再 values.clear。
        compact_grid = (os.environ.get("SHEETS_POLYMARKET_COMPACT_GRID", "1") or "1").strip() != "0"
        meta = self._meta_get()
        key_rows = f"pmtab.{tab_title}.rows"
        key_cols = f"pmtab.{tab_title}.cols"
        try:
            r_old = int(str(meta.get(key_rows) or "0").strip() or "0")
        except Exception:
            r_old = 0
        try:
            c_old = int(str(meta.get(key_cols) or "0").strip() or "0")
        except Exception:
            c_old = 0

        if r_old > n_rows:
            self._exec(
                self._sheets.spreadsheets()
                .values()
                .clear(
                    spreadsheetId=self._spreadsheet_id,
                    range=f"{tab_title}!A{n_rows + 1}:{_index_to_col(max(c_old, n_cols))}{r_old}",
                ),
                is_write=True,
            )
        if c_old > n_cols:
            self._exec(
                self._sheets.spreadsheets()
                .values()
                .clear(
                    spreadsheetId=self._spreadsheet_id,
                    range=f"{tab_title}!{_index_to_col(n_cols + 1)}1:{_index_to_col(c_old)}{max(r_old, n_rows)}",
                ),
                is_write=True,
            )

        # -------------------- style --------------------
        style_version = "polymarket_table_v3"
        key_style_version = f"pmtab.{tab_title}.style_version"
        key_style_rows = f"pmtab.{tab_title}.style_rows"
        key_style_cols = f"pmtab.{tab_title}.style_cols"
        try:
            styled_rows = int(str(meta.get(key_style_rows) or "0").strip() or "0")
        except Exception:
            styled_rows = 0
        try:
            styled_cols = int(str(meta.get(key_style_cols) or "0").strip() or "0")
        except Exception:
            styled_cols = 0

        # NOTE: 不强制扩到 800 行；否则 UI 会出现大量空白网格，影响阅读。
        target_rows = int(max(n_rows, styled_rows, 1))
        target_cols = int(max(n_cols, 6))
        need_style = (
            (meta.get(key_style_version) or "") != style_version
            or target_rows > styled_rows
            or target_cols != styled_cols
        )
        if need_style:
            self._ensure_grid_size(tab_title, min_rows=target_rows, min_cols=target_cols)

            # 清除旧 conditional formatting（避免历史规则残留）
            try:
                ss = self._exec(
                    self._sheets.spreadsheets().get(
                        spreadsheetId=self._spreadsheet_id,
                        fields="sheets(properties(sheetId,title),conditionalFormats)",
                    ),
                    is_write=False,
                )
                cond_cnt = 0
                for sh in ss.get("sheets", []):
                    props = sh.get("properties") or {}
                    if int(props.get("sheetId") or 0) != int(sh_id):
                        continue
                    cond = sh.get("conditionalFormats") or []
                    cond_cnt = len(cond)
                    break
                if cond_cnt > 0:
                    reqs_del = [
                        {"deleteConditionalFormatRule": {"sheetId": int(sh_id), "index": 0}} for _ in range(cond_cnt)
                    ]
                    self._exec(
                        self._sheets.spreadsheets().batchUpdate(
                            spreadsheetId=self._spreadsheet_id,
                            body={"requests": reqs_del},
                        ),
                        is_write=True,
                    )
            except Exception:
                pass

            reqs: list[dict[str, Any]] = []

            # base style
            reqs.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": int(sh_id),
                            "startRowIndex": 0,
                            "endRowIndex": int(target_rows),
                            "startColumnIndex": 0,
                            "endColumnIndex": int(target_cols),
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": _rgb(1.0, 1.0, 1.0),
                                "textFormat": {"fontFamily": "Arial", "fontSize": 10},
                                "horizontalAlignment": "LEFT",
                                "verticalAlignment": "MIDDLE",
                                "wrapStrategy": "CLIP",
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,wrapStrategy)",
                    }
                }
            )

            # column widths（更紧凑）
            widths = _polymarket_col_widths_px(n_cols=int(target_cols))
            for ci in range(0, int(target_cols)):
                px = int(widths[int(ci)]) if int(ci) < len(widths) else int(widths[-1])
                reqs.append(
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": int(sh_id),
                                "dimension": "COLUMNS",
                                "startIndex": int(ci),
                                "endIndex": int(ci + 1),
                            },
                            "properties": {"pixelSize": int(px)},
                            "fields": "pixelSize",
                        }
                    }
                )

            # freeze meta row + directory row
            reqs.append(
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": int(sh_id),
                            "gridProperties": {"frozenRowCount": int(2 + int(banner_rows)), "frozenColumnCount": 0},
                        },
                        "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
                    }
                }
            )

            # banner 行（可选）
            if int(banner_rows) > 0:
                try:
                    banner_lines = int(banner_line_count or 1)
                except Exception:
                    banner_lines = 1
                banner_lines = max(1, min(int(banner_lines), 6))
                banner_row_px = int(21 * int(banner_lines))

                reqs.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": 0,
                                "endRowIndex": 1,
                                "startColumnIndex": 0,
                                "endColumnIndex": int(target_cols),
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": _rgb(1.0, 0.97, 0.86),
                                    "textFormat": {"bold": True},
                                    "horizontalAlignment": "LEFT",
                                    "verticalAlignment": "MIDDLE",
                                    "wrapStrategy": "OVERFLOW_CELL",
                                }
                            },
                            "fields": "userEnteredFormat(backgroundColor,textFormat.bold,horizontalAlignment,verticalAlignment,wrapStrategy)",
                        }
                    }
                )
                reqs.append(
                    {
                        "updateDimensionProperties": {
                            "range": {"sheetId": int(sh_id), "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
                            "properties": {"pixelSize": int(banner_row_px)},
                            "fields": "pixelSize",
                        }
                    }
                )
                reqs.append(
                    {
                        "updateBorders": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": 0,
                                "endRowIndex": 1,
                                "startColumnIndex": 0,
                                "endColumnIndex": int(target_cols),
                            },
                            "innerVertical": {"style": "SOLID", "width": 1, "color": _rgb(1.0, 0.97, 0.86)},
                        }
                    }
                )

            # meta row emphasis（始终 1 行）
            reqs.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": int(sh_id),
                            "startRowIndex": int(banner_rows),
                            "endRowIndex": int(banner_rows) + 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": int(target_cols),
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": _rgb(0.96, 0.97, 0.98),
                                "textFormat": {"bold": True},
                                "horizontalAlignment": "LEFT",
                                "verticalAlignment": "MIDDLE",
                                "wrapStrategy": "OVERFLOW_CELL",
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat.bold,horizontalAlignment,verticalAlignment,wrapStrategy)",
                    }
                }
            )

            # directory row（单单元格溢出，不换行）
            reqs.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": int(sh_id),
                            "startRowIndex": int(directory_row_0),
                            "endRowIndex": int(directory_row_0) + 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": int(target_cols),
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": _rgb(0.97, 0.98, 1.0),
                                "textFormat": {"bold": True},
                                "horizontalAlignment": "LEFT",
                                "verticalAlignment": "MIDDLE",
                                "wrapStrategy": "CLIP",
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat.bold,horizontalAlignment,verticalAlignment,wrapStrategy)",
                    }
                }
            )

            # title rows emphasis
            for r in (panel_title_rows or []):
                rr0 = max(int(r) - 1, 0)
                reqs.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": int(rr0),
                                "endRowIndex": int(rr0 + 1),
                                "startColumnIndex": 0,
                                "endColumnIndex": int(target_cols),
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": _rgb(0.90, 0.95, 0.98),
                                    "textFormat": {"bold": True},
                                    "horizontalAlignment": "CENTER",
                                    "verticalAlignment": "MIDDLE",
                                    "wrapStrategy": "CLIP",
                                }
                            },
                            "fields": "userEnteredFormat(backgroundColor,textFormat.bold,horizontalAlignment,verticalAlignment,wrapStrategy)",
                        }
                    }
                )

            # header rows emphasis
            for r in (panel_header_rows or []):
                rr0 = max(int(r) - 1, 0)
                reqs.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": int(rr0),
                                "endRowIndex": int(rr0 + 1),
                                "startColumnIndex": 0,
                                "endColumnIndex": int(target_cols),
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": _rgb(0.93, 0.94, 0.96),
                                    "textFormat": {"bold": True},
                                    "horizontalAlignment": "CENTER",
                                    "verticalAlignment": "MIDDLE",
                                    "wrapStrategy": "CLIP",
                                }
                            },
                            "fields": "userEnteredFormat(backgroundColor,textFormat.bold,horizontalAlignment,verticalAlignment,wrapStrategy)",
                        }
                    }
                )

            # section body stripes（按分段重置奇偶；提升可读性）
            stripe = (os.environ.get("SHEETS_POLYMARKET_ROW_STRIPE", "1") or "1").strip() != "0"
            if stripe and panel_title_rows:
                try:
                    titles = sorted({int(r) for r in panel_title_rows if int(r) >= 2 and int(r) <= int(n_rows)})
                    # 末尾哨兵：便于计算每段结束
                    titles2 = list(titles) + [int(n_rows) + 1]
                    header_set = {int(r) for r in (panel_header_rows or []) if int(r) >= 2 and int(r) <= int(n_rows)}
                    for i in range(len(titles2) - 1):
                        t1 = int(titles2[i])
                        end_excl_1 = int(titles2[i + 1])
                        # header 行通常是 title+1；但以 exporter 标记为准
                        h1 = t1 + 1 if (t1 + 1) in header_set else None
                        if h1 is None:
                            # fallback：找该段内第一个 header 标记
                            for r in sorted(header_set):
                                if int(r) > int(t1) and int(r) < int(end_excl_1):
                                    h1 = int(r)
                                    break
                        if h1 is None:
                            continue
                        data_start0 = int(h1)  # 0-based: header row is h1-1, so data starts at h1
                        data_end0 = int(end_excl_1) - 1  # 0-based end exclusive
                        if data_end0 <= data_start0:
                            continue
                        for rr0 in range(int(data_start0), int(data_end0)):
                            if ((rr0 - int(data_start0)) % 2) == 1:
                                reqs.append(
                                    {
                                        "repeatCell": {
                                            "range": {
                                                "sheetId": int(sh_id),
                                                "startRowIndex": int(rr0),
                                                "endRowIndex": int(rr0 + 1),
                                                "startColumnIndex": 0,
                                                "endColumnIndex": int(target_cols),
                                            },
                                            "cell": {"userEnteredFormat": {"backgroundColor": _rgb(0.985, 0.987, 0.99)}},
                                            "fields": "userEnteredFormat(backgroundColor)",
                                        }
                                    }
                                )
                except Exception:
                    pass

            self._exec(
                self._sheets.spreadsheets().batchUpdate(
                    spreadsheetId=self._spreadsheet_id,
                    body={"requests": reqs},
                ),
                is_write=True,
            )

        # compact grid：让“无数据区域”在 UI 中消失
        compact_grid = (os.environ.get("SHEETS_POLYMARKET_COMPACT_GRID", "1") or "1").strip() != "0"
        if compact_grid:
            # NOTE: 允许收缩 rowCount/colCount（等价 UI 删除多余行/列），以实现“只看到有用网格”。
            self._set_sheet_grid_properties(
                tab_title,
                row_count=int(target_rows),
                col_count=int(target_cols),
                frozen_row_count=int(2 + int(banner_rows)),
                frozen_column_count=0,
            )

        # merges（标题行整行合并）
        if merge_ranges:
            reqs_merge: list[dict[str, Any]] = []
            for rg in merge_ranges:
                try:
                    r0, r1, c0, c1 = rg
                except Exception:
                    continue
                try:
                    r0 = int(r0)
                    r1 = int(r1)
                    c0 = int(c0)
                    c1 = int(c1)
                except Exception:
                    continue
                if r0 < 0 or r1 <= r0:
                    continue
                if c0 < 0 or c1 <= c0:
                    continue
                if r0 >= n_rows:
                    continue
                if r1 > n_rows:
                    r1 = n_rows
                if c0 >= n_cols:
                    continue
                if c1 > n_cols:
                    c1 = n_cols
                if (r1 - r0) <= 1 and (c1 - c0) <= 1:
                    continue
                reqs_merge.append(
                    {
                        "mergeCells": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": int(r0),
                                "endRowIndex": int(r1),
                                "startColumnIndex": int(c0),
                                "endColumnIndex": int(c1),
                            },
                            "mergeType": "MERGE_ALL",
                        }
                    }
                )
            if reqs_merge:
                try:
                    self._exec(
                        self._sheets.spreadsheets().batchUpdate(
                            spreadsheetId=self._spreadsheet_id,
                            body={"requests": reqs_merge},
                        ),
                        is_write=True,
                    )
                except Exception:
                    pass

        # directory links（after merges）：写入目录行（并替换 textFormatRuns）
        if dir_text and dir_runs:
            try:
                self._exec(
                    self._sheets.spreadsheets().batchUpdate(
                        spreadsheetId=self._spreadsheet_id,
                        body={
                            "requests": [
                                {
                                    "updateCells": {
                                        "range": {
                                            "sheetId": int(sh_id),
                                            "startRowIndex": int(directory_row_0),
                                            "endRowIndex": int(directory_row_0) + 1,
                                            "startColumnIndex": 0,
                                            "endColumnIndex": 1,
                                        },
                                        "rows": [
                                            {
                                                "values": [
                                                    {
                                                        "userEnteredValue": {"stringValue": str(dir_text)},
                                                        "textFormatRuns": dir_runs,
                                                    }
                                                ]
                                            }
                                        ],
                                        "fields": "userEnteredValue,textFormatRuns",
                                    }
                                }
                            ]
                        },
                    ),
                    is_write=True,
                )
            except Exception as exc:
                print(f"⚠️ pmtab.dir_links_failed tab={tab_title} {type(exc).__name__}: {exc}")

        # meta bump（记录 rows/cols/style）
        self._meta_set(
            {
                key_rows: str(n_rows),
                key_cols: str(n_cols),
                key_style_version: style_version,
                key_style_rows: str(target_rows),
                key_style_cols: str(target_cols),
            }
        )

        return {"ok": True, "tab": tab_title, "rows": n_rows, "cols": n_cols}

    def _write_polymarket_stats_tab_grid(
        self,
        *,
        tab_title: str,
        sh_id: int,
        values: list[list[Any]],
        panel_title_rows: list[int],
        panel_header_rows: list[int],
    ) -> dict[str, Any]:
        """
        方案A：Polymarket统计「卡片网格」布局（masonry）：
        - A1 元信息（整行合并，冻结）
        - A2 目录（整行合并，冻结，富文本超链接）
        - 正文：每个分段变成一张卡片，按 2~3 列网格自动排布，最大化信息密度
        """
        # -------------------- parse sections from exporter output --------------------
        def strip_leading_emoji(s: str) -> str:
            return re.sub(r"^[^0-9A-Za-z\u4e00-\u9fff]+\s*", "", str(s or "")).strip()

        def trim_row(r: list[Any]) -> list[Any]:
            rr = list(r)
            while rr and (rr[-1] == "" or rr[-1] is None):
                rr.pop()
            return rr

        def _is_blank_cell(x: Any) -> bool:
            if x is None:
                return True
            if isinstance(x, str):
                s = x.strip()
                return (not s) or (s == "-")
            return False

        def _drop_fully_empty_columns(headers: list[list[Any]], rows: list[list[Any]]) -> tuple[list[list[Any]], list[list[Any]]]:
            """
            去掉“整列都是空”的分隔列（常见于 exporter 为了视觉分组插入的空列）。
            - 仅当：所有 header 行该列为空，且所有数据行该列为空，才会删除该列
            """
            if not headers:
                return headers, rows
            n_cols0 = max((len(h) for h in headers), default=0)
            n_cols0 = max(int(n_cols0), max((len(r) for r in rows), default=0))
            if n_cols0 <= 0:
                return headers, rows

            keep: list[int] = []
            for ci in range(0, int(n_cols0)):
                hdr_blank = True
                for h in headers:
                    v = h[ci] if ci < len(h) else ""
                    if not _is_blank_cell(v):
                        hdr_blank = False
                        break
                if not hdr_blank:
                    keep.append(int(ci))
                    continue

                data_blank = True
                for r in rows:
                    v = r[ci] if ci < len(r) else ""
                    if not _is_blank_cell(v):
                        data_blank = False
                        break
                if not data_blank:
                    keep.append(int(ci))

            if len(keep) == int(n_cols0):
                return headers, rows

            headers2 = [[(h[ci] if ci < len(h) else "") for ci in keep] for h in headers]
            rows2 = [[(r[ci] if ci < len(r) else "") for ci in keep] for r in rows]
            return headers2, rows2

        title_idx = sorted({int(r) - 1 for r in panel_title_rows if int(r) >= 2})
        header_idx_set = {int(r) - 1 for r in panel_header_rows if int(r) >= 2}
        drop_cols_raw = (os.environ.get("SHEETS_POLYMARKET_DROP_COLUMNS", "买卖比例,聪明钱操作类型") or "").strip()
        drop_names = {s.strip() for s in re.split(r"[,，]", drop_cols_raw) if s.strip()}

        meta_text = ""
        try:
            meta_text = str((values[0] or [""])[0] or "").strip()
        except Exception:
            meta_text = ""
        # 统计口径去重：csv-report.js 固定滚动 24h，这里提升到全局元信息一次表达
        if meta_text and ("窗口" not in meta_text) and ("24h" not in meta_text.lower()):
            meta_text = f"{meta_text}，窗口，滚动24h"

        # -------------------- top banner（全表首行广告位） --------------------
        banner_raw = _read_top_banner_raw(prefer_dashboard=False)
        banner_text, banner_line_count = _format_dashboard_banner_text(str(banner_raw or ""))
        banner_rows = 1 if banner_text else 0
        meta_row_0 = int(banner_rows)
        dir_row_0 = int(banner_rows) + 1

        def normalize_title(s: str) -> str:
            x = str(s or "").strip()
            for suf in [" (本地时间)", "（本地时间）"]:
                if x.endswith(suf):
                    x = x[: -len(suf)].rstrip()
            return x

        sections: list[dict[str, Any]] = []
        for i, t0 in enumerate(title_idx):
            t0 = int(t0)
            t1 = int(title_idx[i + 1]) if i + 1 < len(title_idx) else int(len(values))
            if t0 < 1 or t0 >= len(values):
                continue
            # header：优先 exporter 标记；否则 title+1
            h0 = None
            for cand in sorted(header_idx_set):
                if int(cand) > int(t0) and int(cand) < int(t1):
                    h0 = int(cand)
                    break
            if h0 is None:
                cand = t0 + 1
                if cand < len(values):
                    h0 = cand
            if h0 is None or h0 >= len(values):
                continue

            title = ""
            try:
                title = str((values[t0] or [""])[0] or "").strip()
            except Exception:
                title = ""
            title = normalize_title(title)
            header = trim_row([str(x) for x in (values[h0] or [])])
            rows = []
            for rr in values[h0 + 1 : t1]:
                if not isinstance(rr, list):
                    continue
                row_trim = trim_row(list(rr))
                if not row_trim:
                    continue
                rows.append(row_trim)

            # 先做列裁剪（空列/指定列删除），再生成超链接坐标（避免删列后坐标错位）
            n_sec_cols0 = max(len(header), max((len(r) for r in rows), default=0), 1)
            headers2 = [header[:n_sec_cols0] + [""] * max(0, int(n_sec_cols0) - len(header))]
            rows2 = [r[:n_sec_cols0] + [""] * max(0, int(n_sec_cols0) - len(r)) for r in rows]
            headers2, rows2 = _drop_fully_empty_columns(headers2, rows2)
            headers2, rows2 = _polymarket_drop_columns_by_header(headers2, rows2, drop_names=drop_names)
            header = list((headers2[-1] if headers2 else []) or [])
            rows = rows2

            # 将“链接”融入“市场名称”单元格超链接（不破坏原表结构；避免链接缺失时丢信息）
            # 注意：超链接公式在写入后用 USER_ENTERED 差量写入，避免整表 USER_ENTERED 触发时间/数值误解析。
            # 一个 section 可能包含多个“市场名称/链接”对（例如横向拼接多张 Top15 表），这里全部识别并写入。
            link_indices: list[int] = []
            name_indices: list[int] = []
            for j, c in enumerate(header):
                cj = str(c or "").strip()
                if cj in {"链接", "link", "url", "URL"} or ("链接" in cj):
                    link_indices.append(int(j))
                if cj in {"市场名称", "市场", "market", "question", "名称"}:
                    name_indices.append(int(j))

            # pair: each link column binds to its nearest "name" column on the left (stable for repeated groups)
            pairs: list[tuple[int, int]] = []
            used_names: set[int] = set()
            for li in sorted(set(link_indices)):
                cand = [ni for ni in name_indices if int(ni) < int(li) and int(ni) not in used_names]
                if not cand:
                    continue
                ni = max(cand)
                used_names.add(int(ni))
                pairs.append((int(ni), int(li)))

            hyperlinks: list[tuple[int, int, str, str]] = []
            for ri, r in enumerate(rows):
                for ni, li in pairs:
                    url = ""
                    try:
                        url = str(r[int(li)] or "").strip()
                    except Exception:
                        url = ""
                    name = ""
                    try:
                        name = str(r[int(ni)] or "").strip()
                    except Exception:
                        name = ""
                    if url and (url.startswith("http://") or url.startswith("https://")) and name:
                        hyperlinks.append((int(ri), int(ni), str(url), str(name)))

            n_sec_cols = max(len(header), max((len(r) for r in rows), default=0), 1)
            sections.append(
                {
                    "title": title or "未命名分段",
                    "title_plain": strip_leading_emoji(title or "未命名分段") or "未命名分段",
                    "header": header[:n_sec_cols] + [""] * max(0, n_sec_cols - len(header)),
                    "rows": [r[:n_sec_cols] + [""] * max(0, n_sec_cols - len(r)) for r in rows],
                    "n_cols": int(n_sec_cols),
                    "hyperlinks": hyperlinks,
                }
            )

        # -------------------- lift polymarket exporter logs into meta --------------------
        # exporter 的 stdout 会带若干“生成 CSV 报告/跳过 API 排行”等日志行，
        # 这些行被 parser 误识别为一个“Polymarket统计”分段，导致多出一张无意义卡片与多行噪音。
        # 这里把有效信息提取进 meta_text，然后删除该分段。
        if sections:
            idx_noise = None
            for idx, sec in enumerate(sections):
                if str(sec.get("title_plain") or "").strip() == "Polymarket统计":
                    idx_noise = int(idx)
                    break
            if idx_noise is not None:
                sec0 = sections[int(idx_noise)]
                first = ""
                try:
                    first = str((sec0.get("header") or [""])[0] or "").strip()
                except Exception:
                    first = ""
                if "生成 CSV 报告" in first and "滚动24小时" in first:
                    # 解析窗口起止（不强行标时区，避免误导；原样写入 meta）
                    m = re.search(r"滚动24小时:\s*([0-9\-:\s]{10,})~\s*([0-9\-:\s]{10,})", first)
                    if m:
                        s0 = str(m.group(1)).strip()
                        s1 = str(m.group(2)).strip()
                        if s0 and s1:
                            meta_text = f"{meta_text}，窗口起止，{s0}~{s1}" if meta_text else f"窗口起止，{s0}~{s1}"
                    # API 排行开关状态
                    for rr in (sec0.get("rows") or []):
                        t = ""
                        try:
                            t = str((rr or [""])[0] or "").strip()
                        except Exception:
                            t = ""
                        if "已跳过" in t and "API" in t:
                            meta_text = f"{meta_text}，API排行，关闭" if meta_text else "API排行，关闭"
                            break
                    sections.pop(int(idx_noise))

        # -------------------- bundle: combine related sections into compact composite tables --------------------
        def _find_section_idx(title_plain: str) -> int | None:
            want = str(title_plain or "").strip()
            if not want:
                return None
            for idx, sec in enumerate(sections):
                if str(sec.get("title_plain") or "").strip() == want:
                    return int(idx)
            return None

        def _as_table(sec: dict[str, Any]) -> tuple[list[str], list[list[Any]]]:
            return list(sec.get("header") or []), list(sec.get("rows") or [])

        def _row_map_by_key(rows: list[list[Any]], *, key_idx: int) -> dict[str, list[Any]]:
            out: dict[str, list[Any]] = {}
            for r in rows:
                if not r or int(key_idx) >= len(r):
                    continue
                k = str(r[int(key_idx)] or "").strip()
                if not k:
                    continue
                out[k] = r
            return out

        def _hour_sort_key(h: str) -> tuple[int, str]:
            s = str(h or "").strip()
            m = re.match(r"^(\d{2}):(\d{2})$", s)
            if not m:
                return (10**9, s)
            return (int(m.group(1)) * 60 + int(m.group(2)), s)

        # 1) 时段类三张表：合并为 1 张“小时”主键表（无损压缩：只去掉重复 key 列与空白分隔列）
        idx_trend = _find_section_idx("信号频率趋势 (环比)")
        idx_type = _find_section_idx("时段-类型分布")
        idx_active = _find_section_idx("活跃时段分布")
        if idx_trend is not None and idx_type is not None and idx_active is not None:
            trend = sections[int(idx_trend)]
            typ = sections[int(idx_type)]
            act = sections[int(idx_active)]

            h_trend, r_trend = _as_table(trend)
            h_type, r_type = _as_table(typ)
            h_act, r_act = _as_table(act)

            # locate hour col and metric cols
            def col_idx(cols: list[str], name: str) -> int | None:
                for j, c in enumerate(cols):
                    if str(c or "").strip() == name:
                        return int(j)
                return None

            k0 = col_idx(h_trend, "小时") or 0
            k1 = col_idx(h_type, "小时") or 0
            k2 = col_idx(h_act, "小时") or 0

            m_trend_1 = col_idx(h_trend, "信号数")
            m_trend_2 = col_idx(h_trend, "环比变化%")
            if m_trend_1 is None:
                m_trend_1 = col_idx(h_trend, "信号数量")
            m_act_1 = col_idx(h_act, "信号数量")
            m_act_2 = col_idx(h_act, "占比%")

            m_type = {
                "套利": col_idx(h_type, "套利"),
                "大额交易": col_idx(h_type, "大额交易"),
                "订单簿": col_idx(h_type, "订单簿"),
                "聪明钱": col_idx(h_type, "聪明钱"),
            }

            map_trend = _row_map_by_key(r_trend, key_idx=int(k0))
            map_type = _row_map_by_key(r_type, key_idx=int(k1))
            map_act = _row_map_by_key(r_act, key_idx=int(k2))

            hours = sorted({*map_trend.keys(), *map_type.keys(), *map_act.keys()}, key=_hour_sort_key)
            new_header = ["小时", "信号数", "环比变化%", "套利", "大额交易", "订单簿", "聪明钱", "信号数量", "占比%"]
            new_rows: list[list[Any]] = []
            for h in hours:
                rt = map_trend.get(h) or []
                ry = map_type.get(h) or []
                ra = map_act.get(h) or []

                def pick(row: list[Any], idx: int | None) -> Any:
                    if idx is None:
                        return ""
                    if int(idx) < 0 or int(idx) >= len(row):
                        return ""
                    return row[int(idx)]

                new_rows.append(
                    [
                        h,
                        pick(rt, m_trend_1),
                        pick(rt, m_trend_2),
                        pick(ry, m_type["套利"]),
                        pick(ry, m_type["大额交易"]),
                        pick(ry, m_type["订单簿"]),
                        pick(ry, m_type["聪明钱"]),
                        pick(ra, m_act_1),
                        pick(ra, m_act_2),
                    ]
                )

            group_header = ["信号频率趋势 (环比)", "", "", "时段-类型分布", "", "", "", "活跃时段分布", ""]
            composite = {
                "title": "时段分布汇总",
                "title_plain": "时段分布汇总",
                "group_header": group_header,
                "header": new_header,
                "rows": new_rows,
                "n_cols": int(len(new_header)),
                "hyperlinks": [],
            }

            insert_at = int(min(idx_trend, idx_type, idx_active))
            for rm in sorted([idx_trend, idx_type, idx_active], reverse=True):
                sections.pop(int(rm))
            sections.insert(insert_at, composite)

        # 2) Top 15 四表：横向拼接为 1 张复合表（保持每表字段不丢）
        idx_big = _find_section_idx("大额交易 Top 15")
        idx_new = _find_section_idx("新市场 Top 15")
        idx_hot = _find_section_idx("综合热门市场 Top 15")
        idx_smart = _find_section_idx("聪明钱 Top 15")
        if idx_big is not None and idx_new is not None and idx_hot is not None and idx_smart is not None:
            sec_big = sections[int(idx_big)]
            sec_new = sections[int(idx_new)]
            sec_hot = sections[int(idx_hot)]
            sec_smart = sections[int(idx_smart)]

            hb, rb = _as_table(sec_big)
            hn, rn = _as_table(sec_new)
            hh, rh = _as_table(sec_hot)
            hs, rs = _as_table(sec_smart)

            nrb = int(len(rb))
            nrn = int(len(rn))
            nrh = int(len(rh))
            nrs = int(len(rs))
            max_r = max(nrb, nrn, nrh, nrs, 0)

            def pad_row(row: list[Any], width: int) -> list[Any]:
                rr = list(row or [])
                if len(rr) < int(width):
                    rr.extend([""] * (int(width) - len(rr)))
                return rr[: int(width)]

            new_header = list(hb) + list(hn) + list(hh) + list(hs)
            group_header = (
                ["大额交易 Top 15"] + [""] * (len(hb) - 1)
                + ["新市场 Top 15"] + [""] * (len(hn) - 1)
                + ["综合热门市场 Top 15"] + [""] * (len(hh) - 1)
                + ["聪明钱 Top 15"] + [""] * (len(hs) - 1)
            )
            new_rows: list[list[Any]] = []
            for i in range(0, int(max_r)):
                new_rows.append(
                    pad_row(rb[i] if i < nrb else [], len(hb))
                    + pad_row(rn[i] if i < nrn else [], len(hn))
                    + pad_row(rh[i] if i < nrh else [], len(hh))
                    + pad_row(rs[i] if i < nrs else [], len(hs))
                )

            composite = {
                "title": "Top 15 汇总",
                "title_plain": "Top 15 汇总",
                "group_header": group_header,
                "header": new_header,
                "rows": new_rows,
                "n_cols": int(len(new_header)),
                # hyperlinks: 复用 writer 的 header 扫描逻辑（后续会重新计算）
                "hyperlinks": [],
            }

            insert_at = int(min(idx_big, idx_new, idx_hot, idx_smart))
            for rm in sorted([idx_big, idx_new, idx_hot, idx_smart], reverse=True):
                sections.pop(int(rm))
            sections.insert(insert_at, composite)

        # 3) 类别分布二表：合并为 1 张“类别”主键表
        idx_cat = _find_section_idx("市场类别分布")
        idx_pref = _find_section_idx("聪明钱偏好类别")
        if idx_cat is not None and idx_pref is not None:
            sec_cat = sections[int(idx_cat)]
            sec_pref = sections[int(idx_pref)]
            hc, rc = _as_table(sec_cat)
            hp, rp = _as_table(sec_pref)

            kc = 0
            kp = 0
            map_c = _row_map_by_key(rc, key_idx=kc)
            map_p = _row_map_by_key(rp, key_idx=kp)
            cats = sorted({*map_c.keys(), *map_p.keys()})

            def idx(cols: list[str], name: str) -> int | None:
                for j, c in enumerate(cols):
                    if str(c or "").strip() == name:
                        return int(j)
                return None

            c_n = idx(hc, "信号数量")
            c_p = idx(hc, "占比%")
            p_n = idx(hp, "信号数量")
            p_p = idx(hp, "占比%")

            new_header = ["类别", "信号数量", "占比%", "信号数量", "占比%"]
            group_header = ["市场类别分布", "", "", "聪明钱偏好类别", ""]
            new_rows: list[list[Any]] = []
            for cat in cats:
                rc0 = map_c.get(cat) or []
                rp0 = map_p.get(cat) or []
                new_rows.append(
                    [
                        cat,
                        rc0[int(c_n)] if c_n is not None and int(c_n) < len(rc0) else "",
                        rc0[int(c_p)] if c_p is not None and int(c_p) < len(rc0) else "",
                        rp0[int(p_n)] if p_n is not None and int(p_n) < len(rp0) else "",
                        rp0[int(p_p)] if p_p is not None and int(p_p) < len(rp0) else "",
                    ]
                )

            composite = {
                "title": "类别偏好汇总",
                "title_plain": "类别偏好汇总",
                "group_header": group_header,
                "header": new_header,
                "rows": new_rows,
                "n_cols": int(len(new_header)),
                "hyperlinks": [],
            }

            insert_at = int(min(idx_cat, idx_pref))
            for rm in sorted([idx_cat, idx_pref], reverse=True):
                sections.pop(int(rm))
            sections.insert(insert_at, composite)

        if not sections:
            # fallback：退回为原始表（不做网格）
            sheet = type("Tmp", (), {})()
            sheet.values = values
            sheet.n_rows = len(values)
            sheet.n_cols = max((len(r) for r in values if isinstance(r, list)), default=1)
            # 关键：避免再次触发 grid 分支（防止递归）
            sheet.panel_title_rows = []
            sheet.panel_header_rows = []
            sheet.merge_ranges = [(0, 1, 0, max(int(sheet.n_cols), 1))]
            return self.write_polymarket_stats_tab(tab_title=tab_title, sheet=sheet)

        # -------------------- drop known-bad/low-value standalone sections --------------------
        # 用户反馈：这些分段会引入“标题行+表头行”的视觉噪音（对应固定行号问题），且不属于当前看板目标。
        # 这里直接删除整张卡片（不是合并/隐藏），避免残留空洞与错乱样式。
        drop_enabled = (os.environ.get("SHEETS_POLYMARKET_DROP_STANDALONE_SECTIONS", "1") or "1").strip() != "0"
        if drop_enabled:
            drop_set = {
                "套利信号 Top 15",
                "订单簿失衡 Top 15",
                "套利利润分布",
                "高频套利市场 (10次以上)",
                "高频套利市场（10次以上）",
                "信号密集时段 (5分钟内20+信号)",
                "信号密集时段（5分钟内20+信号）",
                "市场重复出现率 (跨信号类型)",
                "市场重复出现率（跨信号类型）",
            }
            sections = [s for s in sections if str(s.get("title_plain") or "").strip() not in drop_set]

        # bundling 后需要重新计算每个 section 的列宽/超链接（尤其是“Top 15 汇总”等复合表）
        def _compute_hyperlinks_for_section(_header: list[Any], _rows: list[list[Any]]) -> list[tuple[int, int, str, str]]:
            header2 = [str(x or "").strip() for x in (_header or [])]
            link_indices: list[int] = []
            name_indices: list[int] = []
            for j, c in enumerate(header2):
                if c in {"链接", "link", "url", "URL"} or ("链接" in c):
                    link_indices.append(int(j))
                if c in {"市场名称", "市场", "market", "question", "名称"}:
                    name_indices.append(int(j))

            pairs: list[tuple[int, int]] = []
            used_names: set[int] = set()
            for li in sorted(set(link_indices)):
                cand = [ni for ni in name_indices if int(ni) < int(li) and int(ni) not in used_names]
                if not cand:
                    continue
                ni = max(cand)
                used_names.add(int(ni))
                pairs.append((int(ni), int(li)))

            hyperlinks2: list[tuple[int, int, str, str]] = []
            for ri, r in enumerate(_rows or []):
                for ni, li in pairs:
                    url = ""
                    try:
                        url = str(r[int(li)] or "").strip()
                    except Exception:
                        url = ""
                    name = ""
                    try:
                        name = str(r[int(ni)] or "").strip()
                    except Exception:
                        name = ""
                    if url and (url.startswith("http://") or url.startswith("https://")) and name:
                        hyperlinks2.append((int(ri), int(ni), str(url), str(name)))
            return hyperlinks2

        for sec in sections:
            header = list(sec.get("header") or [])
            rows = list(sec.get("rows") or [])
            group_header = list(sec.get("group_header") or [])

            n_sec_cols = max(len(header), max((len(r) for r in rows), default=0), len(group_header), 1)
            sec["n_cols"] = int(n_sec_cols)
            sec["header"] = header[:n_sec_cols] + [""] * max(0, n_sec_cols - len(header))
            if group_header:
                sec["group_header"] = group_header[:n_sec_cols] + [""] * max(0, n_sec_cols - len(group_header))
            sec["rows"] = [r[:n_sec_cols] + [""] * max(0, n_sec_cols - len(r)) for r in rows]
            sec["hyperlinks"] = _compute_hyperlinks_for_section(sec["header"], sec["rows"])

        # -------------------- layout config --------------------
        def env_int(key: str, default: int) -> int:
            try:
                return int((os.environ.get(key, str(default)) or str(default)).strip() or str(default))
            except Exception:
                return int(default)

        # ultimate defaults: 3 columns + minimal gaps（信息密度最大化）
        grid_cols = max(env_int("SHEETS_POLYMARKET_GRID_COLS", 3), 1)
        gap_cols = max(env_int("SHEETS_POLYMARKET_CARD_GAP_COLS", 1), 0)
        gap_rows = max(env_int("SHEETS_POLYMARKET_CARD_GAP_ROWS", 0), 0)

        max_sec_cols = max((int(s["n_cols"]) for s in sections), default=5)
        # 当存在“超宽复合表”（例如 Top15 汇总）时，3 列 masonry 会导致大片空列视觉噪音。
        # 这里做自适应：超过阈值则强制单列纵向布局（卡片仍保留边框/标题/目录跳转）。
        wide_threshold = max(env_int("SHEETS_POLYMARKET_WIDE_CARD_THRESHOLD_COLS", 18), 1)
        force_single = (os.environ.get("SHEETS_POLYMARKET_FORCE_SINGLE_COLUMN", "0") or "0").strip() == "1"
        if force_single or int(max_sec_cols) >= int(wide_threshold):
            grid_cols = 1
            gap_cols = 0

        card_min_cols = max(env_int("SHEETS_POLYMARKET_CARD_MIN_COLS", 5), 3)
        # 单列纵向布局不需要“最小宽度缓冲”：否则会凭空制造空列。
        card_w = int(max_sec_cols) if int(grid_cols) == 1 else int(max(int(card_min_cols), int(max_sec_cols)))
        col_span = int(card_w + gap_cols)
        target_cols = int(grid_cols * card_w + max(grid_cols - 1, 0) * gap_cols)
        target_cols = max(target_cols, card_w)

        # -------------------- masonry placement --------------------
        def x_start(col_i: int) -> int:
            return int(col_i) * int(col_span)

        # 0-based row indices
        cards_y0 = int(dir_row_0) + 1  # after (optional banner) + meta + dir
        cursors = [int(cards_y0) for _ in range(int(grid_cols))]
        placements: list[dict[str, Any]] = []

        max_end_row = int(cards_y0)
        # masonry：按卡片高度降序放置（减少底部空洞）。
        # 单列模式：保持原始顺序（更符合“表格/报表”阅读习惯）。
        if int(grid_cols) == 1:
            sections_sorted = list(sections)
        else:
            sections_sorted = sorted(
                sections,
                key=lambda s: (
                    -(1 + (2 if s.get("group_header") else 1) + len(s.get("rows") or [])),
                    str(s.get("title_plain") or ""),
                ),
            )
        for sec in sections_sorted:
            # 选择最短列
            col_i = min(range(len(cursors)), key=lambda j: cursors[j])
            y0 = int(cursors[col_i])
            x0 = int(x_start(col_i))

            title = str(sec["title"])
            group_header = list(sec.get("group_header") or [])
            header = list(sec["header"])
            rows = list(sec["rows"])
            n_rows = len(rows)
            header_rows = 2 if group_header else 1
            body_offset = 1 + int(header_rows)  # title + header rows
            h = 1 + int(header_rows) + int(n_rows)  # title + header rows + data
            max_end_row = max(max_end_row, y0 + h)

            # 单列布局：每张卡片宽度收敛到“自身列宽”，避免右侧大片空列被边框框出来。
            sec_w = int(sec.get("n_cols") or len(header) or 1)
            w = int(sec_w) if int(grid_cols) == 1 else int(card_w)

            placements.append(
                {
                    "title": title,
                    "title_plain": str(sec["title_plain"]),
                    "hyperlinks": list(sec.get("hyperlinks") or []),
                    "x0": 0 if int(grid_cols) == 1 else x0,
                    "y0": y0,
                    "w": int(w),
                    "h": int(h),
                    "header_rows": int(header_rows),
                    "body_offset": int(body_offset),
                    "group_header": group_header,
                    "header": header,
                    "rows": rows,
                }
            )
            cursors[col_i] = y0 + h + int(gap_rows)

        target_rows = int(max_end_row)

        # -------------------- build grid values (rect) --------------------
        grid: list[list[Any]] = [[""] * int(target_cols) for _ in range(int(target_rows))]

        # banner/meta/dir rows
        if int(banner_rows) > 0 and banner_text:
            grid[0][0] = banner_text
        if meta_text and 0 <= int(meta_row_0) < len(grid):
            grid[int(meta_row_0)][0] = meta_text
        # directory placeholder; will be overwritten by updateCells with rich text
        if 0 <= int(dir_row_0) < len(grid):
            grid[int(dir_row_0)][0] = "目录（点击跳转）"

        for p in placements:
            x0 = int(p["x0"])
            y0 = int(p["y0"])
            w = int(p["w"])
            h = int(p["h"])
            header_rows = int(p.get("header_rows") or 1)
            body_offset = int(p.get("body_offset") or (1 + header_rows))
            group_header = list(p.get("group_header") or [])
            header = list(p["header"])
            rows = list(p["rows"])

            if 0 <= y0 < len(grid) and 0 <= x0 < int(target_cols):
                grid[y0][x0] = str(p["title"])
            # group header row (optional)
            if group_header and (y0 + 1) < len(grid):
                for j in range(0, int(w)):
                    v = group_header[j] if j < len(group_header) else ""
                    if x0 + j < int(target_cols):
                        grid[y0 + 1][x0 + j] = v
            # header row
            hdr_y = int(y0 + 1 + (1 if group_header else 0))
            if hdr_y < len(grid):
                for j in range(0, int(w)):
                    v = header[j] if j < len(header) else ""
                    if x0 + j < int(target_cols):
                        grid[hdr_y][x0 + j] = v
            # body
            for i, rr in enumerate(rows):
                yy = y0 + int(body_offset) + i
                if yy >= len(grid):
                    break
                for j in range(0, int(w)):
                    v = rr[j] if j < len(rr) else ""
                    if x0 + j < int(target_cols):
                        grid[yy][x0 + j] = v

        # -------------------- write values --------------------
        self._ensure_grid_size(tab_title, min_rows=int(target_rows), min_cols=int(target_cols))
        col_r = _index_to_col(int(target_cols))
        self._exec(
            self._sheets.spreadsheets()
            .values()
            .update(
                spreadsheetId=self._spreadsheet_id,
                range=f"{tab_title}!A1:{col_r}{int(target_rows)}",
                valueInputOption="RAW",
                body={"values": grid},
            ),
            is_write=True,
        )

        # tail clear（避免历史残留）
        compact_grid = (os.environ.get("SHEETS_POLYMARKET_COMPACT_GRID", "1") or "1").strip() != "0"
        meta = self._meta_get()
        key_rows = f"pmtab.{tab_title}.rows"
        key_cols = f"pmtab.{tab_title}.cols"
        try:
            r_old = int(str(meta.get(key_rows) or "0").strip() or "0")
        except Exception:
            r_old = 0
        try:
            c_old = int(str(meta.get(key_cols) or "0").strip() or "0")
        except Exception:
            c_old = 0

        if int(r_old) > int(target_rows):
            self._exec(
                self._sheets.spreadsheets()
                .values()
                .clear(
                    spreadsheetId=self._spreadsheet_id,
                    range=f"{tab_title}!A{int(target_rows) + 1}:{_index_to_col(max(int(c_old), int(target_cols)))}{int(r_old)}",
                ),
                is_write=True,
            )
        if int(c_old) > int(target_cols):
            self._exec(
                self._sheets.spreadsheets()
                .values()
                .clear(
                    spreadsheetId=self._spreadsheet_id,
                    range=f"{tab_title}!{_index_to_col(int(target_cols) + 1)}1:{_index_to_col(int(c_old))}{max(int(r_old), int(target_rows))}",
                ),
                is_write=True,
            )

        # -------------------- merges --------------------
        merge_ranges: list[tuple[int, int, int, int]] = []
        if int(target_cols) > 1:
            # banner（可选）+ meta + directory：整行合并
            if int(banner_rows) > 0:
                merge_ranges.append((0, 1, 0, int(target_cols)))  # banner
            merge_ranges.append((int(meta_row_0), int(meta_row_0) + 1, 0, int(target_cols)))  # meta
            merge_ranges.append((int(dir_row_0), int(dir_row_0) + 1, 0, int(target_cols)))  # directory
        for p in placements:
            y0 = int(p["y0"])
            x0 = int(p["x0"])
            w = int(p["w"])
            merge_ranges.append((int(y0), int(y0 + 1), int(x0), int(min(x0 + w, int(target_cols)))))

        if merge_ranges:
            reqs_merge: list[dict[str, Any]] = []
            # 先清空旧 merge（否则会与新布局冲突，导致 mergeCells 400）
            reqs_merge.append({"unmergeCells": {"range": {"sheetId": int(sh_id)}}})
            for r0, r1, c0, c1 in merge_ranges:
                if r0 < 0 or r1 <= r0:
                    continue
                if c0 < 0 or c1 <= c0:
                    continue
                reqs_merge.append(
                    {
                        "mergeCells": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": int(r0),
                                "endRowIndex": int(r1),
                                "startColumnIndex": int(c0),
                                "endColumnIndex": int(c1),
                            },
                            "mergeType": "MERGE_ALL",
                        }
                    }
                )
            if reqs_merge:
                try:
                    self._exec(
                        self._sheets.spreadsheets().batchUpdate(
                            spreadsheetId=self._spreadsheet_id,
                            body={"requests": reqs_merge},
                        ),
                        is_write=True,
                    )
                except Exception:
                    pass

        # -------------------- styles --------------------
        style_version = "polymarket_grid_v8"
        key_style_version = f"pmtab.{tab_title}.style_version"
        key_style_rows = f"pmtab.{tab_title}.style_rows"
        key_style_cols = f"pmtab.{tab_title}.style_cols"
        try:
            styled_rows = int(str(meta.get(key_style_rows) or "0").strip() or "0")
        except Exception:
            styled_rows = 0
        try:
            styled_cols = int(str(meta.get(key_style_cols) or "0").strip() or "0")
        except Exception:
            styled_cols = 0

        need_style = (
            (meta.get(key_style_version) or "") != style_version
            or styled_rows != int(target_rows)
            or styled_cols != int(target_cols)
        )
        if need_style:
            # column widths
            # - 多列 masonry：按“卡片内列位”设置（稳定、紧凑）
            # - 单列纵向：按“整列内容”自适应（避免排行榜各列同宽导致可读性差）
            def _clamp(v: int, lo: int, hi: int) -> int:
                return max(int(lo), min(int(v), int(hi)))

            def _approx_px_from_text_len(n: int) -> int:
                # 经验值：10pt Arial 约 7px/字符 + padding
                return int(20 + int(n) * 7)

            def _is_url(s: str) -> bool:
                x = (s or "").strip().lower()
                return x.startswith("http://") or x.startswith("https://")

            widths_by_col: list[int] = []
            if int(grid_cols) == 1:
                min_px = int((os.environ.get("SHEETS_POLYMARKET_COL_WIDTH_MIN", "56") or "56").strip() or "56")
                max_px = int((os.environ.get("SHEETS_POLYMARKET_COL_WIDTH_MAX", "420") or "420").strip() or "420")

                # 采样整列最大可见文本长度（忽略 URL），得到更合理的列宽
                for ci in range(0, int(target_cols)):
                    max_len = 0
                    has_link_header = False
                    has_name_header = False
                    has_rank_header = False
                    has_hour_header = False

                    for ri in range(0, int(target_rows)):
                        row = grid[ri] if 0 <= ri < len(grid) else []
                        if not row or ci >= len(row):
                            continue
                        v = row[ci]
                        if v is None or v == "":
                            continue
                        s = str(v).strip()
                        if not s:
                            continue
                        if s in {"链接", "link", "url", "URL"} or ("链接" in s):
                            has_link_header = True
                        if s in {"市场名称", "市场", "market", "question", "名称"}:
                            has_name_header = True
                        if s == "排名":
                            has_rank_header = True
                        if s in {"小时", "hour", "Hour"}:
                            has_hour_header = True

                        # URL 列永远不按 URL 本体撑宽（主展示是“市场名称”的超链接）
                        if _is_url(s):
                            continue
                        # 过长文本只取前缀估计，避免异常撑爆
                        max_len = max(max_len, min(len(s), 60))

                    if has_link_header:
                        px = int((os.environ.get("SHEETS_POLYMARKET_COL_WIDTH_LINK", "40") or "40").strip() or "40")
                    elif has_rank_header or has_hour_header:
                        px = int((os.environ.get("SHEETS_POLYMARKET_COL_WIDTH_KEY", "72") or "72").strip() or "72")
                    elif has_name_header:
                        px = _approx_px_from_text_len(max(max_len, 18))
                    else:
                        px = _approx_px_from_text_len(max(max_len, 6))

                    widths_by_col.append(_clamp(int(px), int(min_px), int(max_px)))

                def col_px(ci: int) -> int:
                    if 0 <= int(ci) < len(widths_by_col):
                        return int(widths_by_col[int(ci)])
                    return int(min_px)

            else:
                # 多列 masonry：按“卡片内列位”设置；gap 列更窄
                def col_px(ci: int) -> int:
                    if gap_cols > 0 and (ci % int(col_span)) >= int(card_w):
                        return 24
                    idx = ci % int(col_span)
                    if idx == 0:
                        return int((os.environ.get("SHEETS_POLYMARKET_CARD_COL_W0", "250") or "250").strip() or "250")
                    if idx == int(card_w) - 1:
                        return int(
                            (os.environ.get("SHEETS_POLYMARKET_CARD_COL_W_LAST", "140") or "140").strip() or "140"
                        )
                    return int((os.environ.get("SHEETS_POLYMARKET_CARD_COL_W", "98") or "98").strip() or "98")

            reqs: list[dict[str, Any]] = []
            reqs.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": int(sh_id),
                            "startRowIndex": 0,
                            "endRowIndex": int(target_rows),
                            "startColumnIndex": 0,
                            "endColumnIndex": int(target_cols),
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": _rgb(1.0, 1.0, 1.0),
                                "textFormat": {"fontFamily": "Arial", "fontSize": 10},
                                "horizontalAlignment": "LEFT",
                                "verticalAlignment": "MIDDLE",
                                "wrapStrategy": "CLIP",
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,wrapStrategy)",
                    }
                }
            )

            for ci in range(0, int(target_cols)):
                reqs.append(
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": int(sh_id),
                                "dimension": "COLUMNS",
                                "startIndex": int(ci),
                                "endIndex": int(ci + 1),
                            },
                            "properties": {"pixelSize": int(max(col_px(int(ci)), 50))},
                            "fields": "pixelSize",
                        }
                    }
                )

            # freeze 2 rows
            reqs.append(
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": int(sh_id),
                            "gridProperties": {"frozenRowCount": 2, "frozenColumnCount": 0},
                        },
                        "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
                    }
                }
            )

            # gridlines：默认不隐藏（保持 Google Sheets 默认网格线展示）
            reqs.append(
                {
                    "updateSheetProperties": {
                        "properties": {"sheetId": int(sh_id), "gridProperties": {"hideGridlines": False}},
                        "fields": "gridProperties.hideGridlines",
                    }
                }
            )

            # banner 行（可选）
            if int(banner_rows) > 0:
                try:
                    banner_lines = int(banner_line_count or 1)
                except Exception:
                    banner_lines = 1
                banner_lines = max(1, min(int(banner_lines), 6))
                banner_row_px = int(21 * int(banner_lines))

                reqs.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": 0,
                                "endRowIndex": 1,
                                "startColumnIndex": 0,
                                "endColumnIndex": int(target_cols),
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": _rgb(1.0, 0.97, 0.86),
                                    "textFormat": {"bold": True},
                                    "horizontalAlignment": "LEFT",
                                    "verticalAlignment": "MIDDLE",
                                    "wrapStrategy": "OVERFLOW_CELL",
                                }
                            },
                            "fields": "userEnteredFormat(backgroundColor,textFormat.bold,horizontalAlignment,verticalAlignment,wrapStrategy)",
                        }
                    }
                )
                reqs.append(
                    {
                        "updateDimensionProperties": {
                            "range": {"sheetId": int(sh_id), "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
                            "properties": {"pixelSize": int(banner_row_px)},
                            "fields": "pixelSize",
                        }
                    }
                )
                reqs.append(
                    {
                        "updateBorders": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": 0,
                                "endRowIndex": 1,
                                "startColumnIndex": 0,
                                "endColumnIndex": int(target_cols),
                            },
                            "innerVertical": {"style": "SOLID", "width": 1, "color": _rgb(1.0, 0.97, 0.86)},
                        }
                    }
                )

            # meta row
            reqs.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": int(sh_id),
                            "startRowIndex": int(meta_row_0),
                            "endRowIndex": int(meta_row_0) + 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": int(target_cols),
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": _rgb(0.93, 0.94, 0.96),
                                "textFormat": {"bold": True},
                                "horizontalAlignment": "LEFT",
                                "verticalAlignment": "MIDDLE",
                                "wrapStrategy": "OVERFLOW_CELL",
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat.bold,horizontalAlignment,verticalAlignment,wrapStrategy)",
                    }
                }
            )
            # directory row
            reqs.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": int(sh_id),
                            "startRowIndex": int(dir_row_0),
                            "endRowIndex": int(dir_row_0) + 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": int(target_cols),
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": _rgb(0.97, 0.98, 1.0),
                                "textFormat": {"bold": True},
                                "horizontalAlignment": "LEFT",
                                "verticalAlignment": "MIDDLE",
                                "wrapStrategy": "OVERFLOW_CELL",
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat.bold,horizontalAlignment,verticalAlignment,wrapStrategy)",
                    }
                }
            )

            # cards style + borders
            title_bg = _rgb(0.12, 0.16, 0.23)
            title_fg = _rgb(1.0, 1.0, 1.0)
            group_bg = _rgb(0.86, 0.90, 0.96)
            header_bg = _rgb(0.93, 0.94, 0.96)
            border = {"style": "SOLID", "width": 1, "color": _rgb(0.80, 0.82, 0.86)}

            for p in placements:
                x0 = int(p["x0"])
                y0 = int(p["y0"])
                w = int(p["w"])
                h = int(p["h"])
                header_rows = int(p.get("header_rows") or 1)
                body_offset = int(p.get("body_offset") or (1 + header_rows))
                has_group = bool(p.get("group_header"))
                x1 = int(min(x0 + w, int(target_cols)))
                y1 = int(min(y0 + h, int(target_rows)))

                # title row
                reqs.append(
                    {
                        "repeatCell": {
                            "range": {"sheetId": int(sh_id), "startRowIndex": int(y0), "endRowIndex": int(y0 + 1), "startColumnIndex": int(x0), "endColumnIndex": int(x1)},
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": title_bg,
                                    "textFormat": {"bold": True, "foregroundColor": title_fg},
                                    "horizontalAlignment": "CENTER",
                                    "verticalAlignment": "MIDDLE",
                                    "wrapStrategy": "CLIP",
                                }
                            },
                            "fields": "userEnteredFormat(backgroundColor,textFormat.bold,textFormat.foregroundColor,horizontalAlignment,verticalAlignment,wrapStrategy)",
                        }
                    }
                )
                # 关键：标题行横向合并（否则标题文字只在第 1 列居中，看起来像“没对齐/有 bug”）
                if (x1 - x0) >= 2:
                    reqs.append(
                        {
                            "mergeCells": {
                                "range": {
                                    "sheetId": int(sh_id),
                                    "startRowIndex": int(y0),
                                    "endRowIndex": int(y0 + 1),
                                    "startColumnIndex": int(x0),
                                    "endColumnIndex": int(x1),
                                },
                                "mergeType": "MERGE_ALL",
                            }
                        }
                    )
                # group header row (optional)
                if has_group:
                    reqs.append(
                        {
                            "repeatCell": {
                                "range": {
                                    "sheetId": int(sh_id),
                                    "startRowIndex": int(y0 + 1),
                                    "endRowIndex": int(y0 + 2),
                                    "startColumnIndex": int(x0),
                                    "endColumnIndex": int(x1),
                                },
                                "cell": {
                                    "userEnteredFormat": {
                                        "backgroundColor": group_bg,
                                        "textFormat": {"bold": True},
                                        "horizontalAlignment": "CENTER",
                                        "verticalAlignment": "MIDDLE",
                                        "wrapStrategy": "CLIP",
                                    }
                                },
                                "fields": "userEnteredFormat(backgroundColor,textFormat.bold,horizontalAlignment,verticalAlignment,wrapStrategy)",
                            }
                        }
                    )
                    # merge contiguous spans in group header row
                    gh = list(p.get("group_header") or [])
                    start = 0
                    while start < int(w):
                        val = str(gh[start] or "").strip() if start < len(gh) else ""
                        if not val:
                            start += 1
                            continue
                        end = start + 1
                        while end < int(w):
                            nxt = str(gh[end] or "").strip() if end < len(gh) else ""
                            if nxt:
                                break
                            end += 1
                        # clamp to card boundary
                        c0 = int(x0 + start)
                        c1 = int(min(x0 + end, x1))
                        if c1 - c0 >= 2:
                            reqs.append(
                                {
                                    "mergeCells": {
                                        "range": {
                                            "sheetId": int(sh_id),
                                            "startRowIndex": int(y0 + 1),
                                            "endRowIndex": int(y0 + 2),
                                            "startColumnIndex": int(c0),
                                            "endColumnIndex": int(c1),
                                        },
                                        "mergeType": "MERGE_ALL",
                                    }
                                }
                            )
                        start = end

                # header row
                hdr_y0 = int(y0 + 1 + (1 if has_group else 0))
                reqs.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": int(hdr_y0),
                                "endRowIndex": int(hdr_y0 + 1),
                                "startColumnIndex": int(x0),
                                "endColumnIndex": int(x1),
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": header_bg,
                                    "textFormat": {"bold": True},
                                    "horizontalAlignment": "CENTER",
                                    "verticalAlignment": "MIDDLE",
                                    "wrapStrategy": "CLIP",
                                }
                            },
                            "fields": "userEnteredFormat(backgroundColor,textFormat.bold,horizontalAlignment,verticalAlignment,wrapStrategy)",
                        }
                    }
                )

                # body alignment（信息密度 + 可读性）
                # - col0：居中
                # - col1：左对齐
                # - col2+：右对齐（数字为主）
                if y1 > (y0 + int(body_offset)):
                    # col0
                    reqs.append(
                        {
                            "repeatCell": {
                                "range": {
                                    "sheetId": int(sh_id),
                                    "startRowIndex": int(y0 + int(body_offset)),
                                    "endRowIndex": int(y1),
                                    "startColumnIndex": int(x0),
                                    "endColumnIndex": int(min(x0 + 1, x1)),
                                },
                                "cell": {
                                    "userEnteredFormat": {
                                        "horizontalAlignment": "CENTER",
                                        "verticalAlignment": "MIDDLE",
                                        "wrapStrategy": "CLIP",
                                    }
                                },
                                "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment,wrapStrategy)",
                            }
                        }
                    )
                    # col1
                    if (x0 + 2) <= x1:
                        reqs.append(
                            {
                                "repeatCell": {
                                    "range": {
                                        "sheetId": int(sh_id),
                                        "startRowIndex": int(y0 + int(body_offset)),
                                        "endRowIndex": int(y1),
                                        "startColumnIndex": int(x0 + 1),
                                        "endColumnIndex": int(min(x0 + 2, x1)),
                                    },
                                    "cell": {
                                        "userEnteredFormat": {
                                            "horizontalAlignment": "LEFT",
                                            "verticalAlignment": "MIDDLE",
                                            "wrapStrategy": "CLIP",
                                        }
                                    },
                                    "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment,wrapStrategy)",
                                }
                            }
                        )
                    # col2+
                    if (x0 + 2) < x1:
                        reqs.append(
                            {
                                "repeatCell": {
                                    "range": {
                                        "sheetId": int(sh_id),
                                        "startRowIndex": int(y0 + int(body_offset)),
                                        "endRowIndex": int(y1),
                                        "startColumnIndex": int(x0 + 2),
                                        "endColumnIndex": int(x1),
                                    },
                                    "cell": {
                                        "userEnteredFormat": {
                                            "horizontalAlignment": "RIGHT",
                                            "verticalAlignment": "MIDDLE",
                                            "wrapStrategy": "CLIP",
                                        }
                                    },
                                    "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment,wrapStrategy)",
                                }
                            }
                        )

                # border around card
                reqs.append(
                    {
                        "updateBorders": {
                            "range": {"sheetId": int(sh_id), "startRowIndex": int(y0), "endRowIndex": int(y1), "startColumnIndex": int(x0), "endColumnIndex": int(x1)},
                            "top": border,
                            "bottom": border,
                            "left": border,
                            "right": border,
                            "innerHorizontal": border,
                            "innerVertical": border,
                        }
                    }
                )

            self._exec(
                self._sheets.spreadsheets().batchUpdate(
                    spreadsheetId=self._spreadsheet_id,
                    body={"requests": reqs},
                ),
                is_write=True,
            )

        # compact grid：让“无数据区域”在 UI 中消失
        compact_grid = (os.environ.get("SHEETS_POLYMARKET_COMPACT_GRID", "1") or "1").strip() != "0"
        if compact_grid:
            self._set_sheet_grid_properties(
                tab_title,
                row_count=int(target_rows),
                col_count=int(target_cols),
                frozen_row_count=int(2 + int(banner_rows)),
                frozen_column_count=0,
            )

        # -------------------- directory richtext links (A2) --------------------
        try:
            def idx_len(s: str) -> int:
                return _utf16_len(str(s))

            label = "目录（点击跳转）"
            parts = [label]
            runs: list[dict[str, Any]] = [{"startIndex": 0, "format": {}}]
            pos = int(idx_len(label))
            # 目录按“原始分段顺序”输出，但跳转坐标按 placements（masonry 排布）生成。
            pos_by_title: dict[str, tuple[int, int]] = {}
            for p in placements:
                t = str(p.get("title_plain") or "").strip() or "-"
                pos_by_title[t] = (int(p["x0"]), int(p["y0"]))

            for sec in sections:
                sep = "，"
                parts.append(sep)
                pos += idx_len(sep)
                start = int(pos)
                title_plain = str(sec.get("title_plain") or "").strip() or "-"
                parts.append(title_plain)
                pos += idx_len(title_plain)
                end = int(pos)
                xy = pos_by_title.get(title_plain) or (0, int(cards_y0))
                col = _index_to_col(int(xy[0] + 1))
                row1 = int(xy[1] + 1)
                url = f"https://docs.google.com/spreadsheets/d/{self._spreadsheet_id}/edit#gid={int(sh_id)}&range={col}{row1}"
                runs.append(
                    {
                        "startIndex": int(start),
                        "format": {"link": {"uri": str(url)}, "foregroundColor": _rgb(0.1, 0.4, 0.8), "underline": True},
                    }
                )
                runs.append({"startIndex": int(end), "format": {}})

            dir_text = "".join(parts)
            text_len = idx_len(dir_text)
            while runs and int(runs[-1].get("startIndex", 0) or 0) >= int(text_len):
                runs.pop()

            self._exec(
                self._sheets.spreadsheets().batchUpdate(
                    spreadsheetId=self._spreadsheet_id,
                    body={
                        "requests": [
                            {
                                "updateCells": {
                                    "range": {
                                        "sheetId": int(sh_id),
                                        "startRowIndex": int(dir_row_0),
                                        "endRowIndex": int(dir_row_0) + 1,
                                        "startColumnIndex": 0,
                                        "endColumnIndex": 1,
                                    },
                                    "rows": [{"values": [{"userEnteredValue": {"stringValue": str(dir_text)}, "textFormatRuns": runs}]}],
                                    "fields": "userEnteredValue,textFormatRuns",
                                }
                            }
                        ]
                    },
                ),
                is_write=True,
            )
        except Exception:
            pass

        # -------------------- hyperlinks: apply formulas (diff) --------------------
        # 用 USER_ENTERED 只写入需要超链接的单元格，避免 RAW 导致公式不生效，
        # 也避免整表 USER_ENTERED 触发 “01:00” 等被解析为时间值。
        def _escape_formula_str(s: str) -> str:
            return str(s or "").replace('"', '""').replace("\n", " ").replace("\r", " ")

        def _escape_sheet_title_a1(title: str) -> str:
            # A1 notation: quote sheet title with single quotes; escape inner single quotes by doubling.
            return "'" + str(title or "").replace("'", "''") + "'"

        data_updates: list[dict[str, Any]] = []
        for p in placements:
            x0 = int(p["x0"])
            y0 = int(p["y0"])
            body_offset = int(p.get("body_offset") or 2)
            links = list(p.get("hyperlinks") or [])
            for ri, ci, url, name in links:
                rr0 = int(y0 + int(body_offset) + int(ri))  # 0-based
                cc0 = int(x0 + int(ci))      # 0-based
                if rr0 < 0 or rr0 >= int(target_rows):
                    continue
                if cc0 < 0 or cc0 >= int(target_cols):
                    continue
                sheet_a1 = _escape_sheet_title_a1(tab_title)
                cell = f"{sheet_a1}!{_index_to_col(int(cc0 + 1))}{int(rr0 + 1)}"
                formula = f'=HYPERLINK("{_escape_formula_str(url)}","{_escape_formula_str(name)}")'
                data_updates.append({"range": cell, "values": [[formula]]})

        if data_updates:
            ex = data_updates[0].get("range", "")
            print(f"[DEBUG] pmtab.hyperlinks_prepare tab={tab_title} count={len(data_updates)} example={ex}")
            try:
                self._exec(
                    self._sheets.spreadsheets()
                    .values()
                    .batchUpdate(
                        spreadsheetId=self._spreadsheet_id,
                        body={"valueInputOption": "USER_ENTERED", "data": data_updates},
                    ),
                    is_write=True,
                )
                print(f"[DEBUG] pmtab.hyperlinks_applied tab={tab_title} count={len(data_updates)}")
            except Exception as exc:
                print(f"⚠️ pmtab.hyperlinks_failed tab={tab_title} {type(exc).__name__}: {exc}")

        # meta bump（记录 rows/cols/style）
        self._meta_set(
            {
                key_rows: str(int(target_rows)),
                key_cols: str(int(target_cols)),
                key_style_version: style_version,
                key_style_rows: str(int(target_rows)),
                key_style_cols: str(int(target_cols)),
            }
        )

        return {"ok": True, "tab": tab_title, "rows": int(target_rows), "cols": int(target_cols)}

    def _write_polymarket_stats_tab_report(
        self,
        *,
        tab_title: str,
        sh_id: int,
        values: list[list[Any]],
        panel_title_rows: list[int],
        panel_header_rows: list[int],
    ) -> dict[str, Any]:
        """
        方案B：Polymarket统计「纵向报表分区」布局：
        - A1 元信息（整行合并，冻结，不换行）
        - A2 目录（整行合并，冻结，富文本超链接，不换行）
        - 正文：各分段依次纵向排列：分区标题（整行合并）+ 表头 + 数据
          - Top 15：合并为“长表”（类型列 + 指标列），避免超宽表
          - 时段分布/类别偏好：使用现有无损合并逻辑（保持字段）
        """
        # -------------------- parse sections from exporter output --------------------
        def strip_leading_emoji(s: str) -> str:
            return re.sub(r"^[^0-9A-Za-z\u4e00-\u9fff]+\s*", "", str(s or "")).strip()

        def trim_row(r: list[Any]) -> list[Any]:
            rr = list(r)
            while rr and (rr[-1] == "" or rr[-1] is None):
                rr.pop()
            return rr

        title_idx = sorted({int(r) - 1 for r in panel_title_rows if int(r) >= 2})
        header_idx_set = {int(r) - 1 for r in panel_header_rows if int(r) >= 2}
        drop_cols_raw = (os.environ.get("SHEETS_POLYMARKET_DROP_COLUMNS", "买卖比例,聪明钱操作类型") or "").strip()
        drop_names = {s.strip() for s in re.split(r"[,，]", drop_cols_raw) if s.strip()}

        meta_text = ""
        try:
            meta_text = str((values[0] or [""])[0] or "").strip()
        except Exception:
            meta_text = ""
        if meta_text and ("窗口" not in meta_text) and ("24h" not in meta_text.lower()):
            meta_text = f"{meta_text}，窗口，滚动24h"

        # -------------------- top banner（全表首行广告位） --------------------
        banner_raw = _read_top_banner_raw(prefer_dashboard=False)
        banner_text, banner_line_count = _format_dashboard_banner_text(str(banner_raw or ""))
        banner_rows = 1 if banner_text else 0
        meta_row_0 = int(banner_rows)
        dir_row_0 = int(banner_rows) + 1

        def normalize_title(s: str) -> str:
            x = str(s or "").strip()
            for suf in [" (本地时间)", "（本地时间）"]:
                if x.endswith(suf):
                    x = x[: -len(suf)].rstrip()
            return x

        sections: list[dict[str, Any]] = []
        for i, t0 in enumerate(title_idx):
            t0 = int(t0)
            t1 = int(title_idx[i + 1]) if i + 1 < len(title_idx) else int(len(values))
            if t0 < 1 or t0 >= len(values):
                continue
            # header：优先 exporter 标记；否则 title+1
            h0 = None
            for cand in sorted(header_idx_set):
                if int(cand) > int(t0) and int(cand) < int(t1):
                    h0 = int(cand)
                    break
            if h0 is None:
                cand = t0 + 1
                if cand < len(values):
                    h0 = cand
            if h0 is None or h0 >= len(values):
                continue

            # 允许“多行表头”（例如：分组表头 + 列名表头），只取连续的 header 行
            header_rows_idx = [int(h0)]
            if int(h0) in header_idx_set:
                cur = int(h0) + 1
                while int(cur) < int(t1) and int(cur) in header_idx_set:
                    header_rows_idx.append(int(cur))
                    cur += 1
            data_start = int(header_rows_idx[-1]) + 1

            title = ""
            try:
                title = str((values[t0] or [""])[0] or "").strip()
            except Exception:
                title = ""
            title = normalize_title(title)

            headers_raw: list[list[Any]] = []
            for hi in header_rows_idx:
                headers_raw.append(trim_row([str(x) for x in (values[int(hi)] or [])]))
            rows: list[list[Any]] = []
            for rr in values[int(data_start) : t1]:
                if not isinstance(rr, list):
                    continue
                row_trim = trim_row(list(rr))
                if not row_trim:
                    continue
                rows.append(row_trim)

            n_sec_cols = max(max((len(h) for h in headers_raw), default=0), max((len(r) for r in rows), default=0), 1)
            headers2 = [h[:n_sec_cols] + [""] * max(0, int(n_sec_cols) - len(h)) for h in headers_raw]
            rows2 = [r[:n_sec_cols] + [""] * max(0, int(n_sec_cols) - len(r)) for r in rows]

            # 去掉“整列空白”的分隔列（减少空列/间隙，不影响数据字段）
            headers2, rows2 = _drop_fully_empty_columns(headers2, rows2)
            # 删除用户明确不想展示的列（例如：买卖比例/聪明钱操作类型）
            headers2, rows2 = _polymarket_drop_columns_by_header(headers2, rows2, drop_names=drop_names)
            header_last = list(headers2[-1] if headers2 else [])

            sections.append(
                {
                    "title_plain": strip_leading_emoji(title or "未命名分段") or "未命名分段",
                    "headers": headers2,
                    "header": header_last,
                    "rows": rows2,
                    "n_cols": int(max(len(header_last), max((len(r) for r in rows2), default=0), 1)),
                }
            )

        # -------------------- lift exporter logs into meta --------------------
        if sections:
            idx_noise = None
            for idx, sec in enumerate(sections):
                if str(sec.get("title_plain") or "").strip() == "Polymarket统计":
                    idx_noise = int(idx)
                    break
            if idx_noise is not None:
                sec0 = sections[int(idx_noise)]
                first = ""
                try:
                    first = str((sec0.get("header") or [""])[0] or "").strip()
                except Exception:
                    first = ""
                if "生成 CSV 报告" in first and "滚动24小时" in first:
                    m = re.search(r"滚动24小时:\s*([0-9\-:\s]{10,})~\s*([0-9\-:\s]{10,})", first)
                    if m:
                        s0 = str(m.group(1)).strip()
                        s1 = str(m.group(2)).strip()
                        if s0 and s1:
                            meta_text = f"{meta_text}，窗口起止，{s0}~{s1}" if meta_text else f"窗口起止，{s0}~{s1}"
                    for rr in (sec0.get("rows") or []):
                        t = ""
                        try:
                            t = str((rr or [""])[0] or "").strip()
                        except Exception:
                            t = ""
                        if "已跳过" in t and "API" in t:
                            meta_text = f"{meta_text}，API排行，关闭" if meta_text else "API排行，关闭"
                            break
                    sections.pop(int(idx_noise))

        # -------------------- drop noisy/low-value sections --------------------
        drop_enabled = (os.environ.get("SHEETS_POLYMARKET_DROP_STANDALONE_SECTIONS", "1") or "1").strip() != "0"
        if drop_enabled:
            drop_set = {
                "套利信号 Top 15",
                "订单簿失衡 Top 15",
                "套利利润分布",
                "高频套利市场 (10次以上)",
                "高频套利市场（10次以上）",
                "信号密集时段 (5分钟内20+信号)",
                "信号密集时段（5分钟内20+信号）",
                "市场重复出现率 (跨信号类型)",
                "市场重复出现率（跨信号类型）",
            }
            sections = [s for s in sections if str(s.get("title_plain") or "").strip() not in drop_set]

        if not sections:
            err_rows: list[list[Any]] = []
            if int(banner_rows) > 0 and banner_text:
                err_rows.append([banner_text])
            err_rows.append([meta_text or "Polymarket统计，错误，导出为空"])
            n_err = max(int(len(err_rows)), 1)

            self._ensure_grid_size(tab_title, min_rows=int(n_err), min_cols=1)
            self._exec(
                self._sheets.spreadsheets()
                .values()
                .update(
                    spreadsheetId=self._spreadsheet_id,
                    range=f"{tab_title}!A1:A{int(n_err)}",
                    valueInputOption="RAW",
                    body={"values": err_rows},
                ),
                is_write=True,
            )
            return {"ok": True, "tab": tab_title, "rows": int(n_err), "cols": 1}

        # -------------------- helpers --------------------
        def _col_idx(cols: list[str], name: str) -> int | None:
            for j, c in enumerate(cols or []):
                if str(c or "").strip() == name:
                    return int(j)
            return None

        def _find_idx(title_plain: str) -> int | None:
            for idx, sec in enumerate(sections):
                if str(sec.get("title_plain") or "").strip() == title_plain:
                    return int(idx)
            return None

        def _row_map_by_key(rows: list[list[Any]], *, key_idx: int) -> dict[str, list[Any]]:
            out: dict[str, list[Any]] = {}
            for r in rows:
                if not r or int(key_idx) >= len(r):
                    continue
                k = str(r[int(key_idx)] or "").strip()
                if not k:
                    continue
                out[k] = r
            return out

        def _hour_sort_key(h: str) -> tuple[int, str]:
            s = str(h or "").strip()
            m = re.match(r"^(\d{2}):(\d{2})$", s)
            if not m:
                return (10**9, s)
            return (int(m.group(1)) * 60 + int(m.group(2)), s)

        # -------------------- bundle: timeslot composite --------------------
        idx_trend = _find_idx("信号频率趋势 (环比)")
        idx_type = _find_idx("时段-类型分布")
        idx_active = _find_idx("活跃时段分布")
        if idx_trend is not None and idx_type is not None and idx_active is not None:
            trend = sections[int(idx_trend)]
            typ = sections[int(idx_type)]
            act = sections[int(idx_active)]

            h_trend = [str(x or "").strip() for x in (trend.get("header") or [])]
            h_type = [str(x or "").strip() for x in (typ.get("header") or [])]
            h_act = [str(x or "").strip() for x in (act.get("header") or [])]
            r_trend = list(trend.get("rows") or [])
            r_type = list(typ.get("rows") or [])
            r_act = list(act.get("rows") or [])

            def col_idx(cols: list[str], name: str) -> int | None:
                for j, c in enumerate(cols):
                    if str(c or "").strip() == name:
                        return int(j)
                return None

            k0 = col_idx(h_trend, "小时") or 0
            k1 = col_idx(h_type, "小时") or 0
            k2 = col_idx(h_act, "小时") or 0

            m_trend_1 = col_idx(h_trend, "信号数")
            m_trend_2 = col_idx(h_trend, "环比变化%")
            if m_trend_1 is None:
                m_trend_1 = col_idx(h_trend, "信号数量")
            m_act_1 = col_idx(h_act, "信号数量")
            m_act_2 = col_idx(h_act, "占比%")
            m_type = {
                "套利": col_idx(h_type, "套利"),
                "大额交易": col_idx(h_type, "大额交易"),
                "订单簿": col_idx(h_type, "订单簿"),
                "聪明钱": col_idx(h_type, "聪明钱"),
            }

            map_trend = _row_map_by_key(r_trend, key_idx=int(k0))
            map_type = _row_map_by_key(r_type, key_idx=int(k1))
            map_act = _row_map_by_key(r_act, key_idx=int(k2))
            hours = sorted({*map_trend.keys(), *map_type.keys(), *map_act.keys()}, key=_hour_sort_key)

            new_header = ["小时", "信号数", "环比变化%", "套利", "大额交易", "订单簿", "聪明钱", "信号数量", "占比%"]
            new_rows: list[list[Any]] = []
            for h in hours:
                rt = map_trend.get(h) or []
                rty = map_type.get(h) or []
                ra = map_act.get(h) or []
                new_rows.append(
                    [
                        h,
                        rt[int(m_trend_1)] if m_trend_1 is not None and int(m_trend_1) < len(rt) else "",
                        rt[int(m_trend_2)] if m_trend_2 is not None and int(m_trend_2) < len(rt) else "",
                        rty[int(m_type["套利"])] if m_type["套利"] is not None and int(m_type["套利"]) < len(rty) else "",
                        rty[int(m_type["大额交易"])] if m_type["大额交易"] is not None and int(m_type["大额交易"]) < len(rty) else "",
                        rty[int(m_type["订单簿"])] if m_type["订单簿"] is not None and int(m_type["订单簿"]) < len(rty) else "",
                        rty[int(m_type["聪明钱"])] if m_type["聪明钱"] is not None and int(m_type["聪明钱"]) < len(rty) else "",
                        ra[int(m_act_1)] if m_act_1 is not None and int(m_act_1) < len(ra) else "",
                        ra[int(m_act_2)] if m_act_2 is not None and int(m_act_2) < len(ra) else "",
                    ]
                )

            composite = {"title_plain": "时段分布汇总", "header": new_header, "rows": new_rows, "n_cols": len(new_header)}
            for rm in sorted([idx_trend, idx_type, idx_active], reverse=True):
                sections.pop(int(rm))
            sections.insert(min(int(idx_trend), int(idx_type), int(idx_active)), composite)

        # -------------------- bundle: category composite --------------------
        idx_cat = _find_idx("市场类别分布")
        idx_pref = _find_idx("聪明钱偏好类别")
        if idx_cat is not None and idx_pref is not None:
            cat = sections[int(idx_cat)]
            pref = sections[int(idx_pref)]
            hc = [str(x or "").strip() for x in (cat.get("header") or [])]
            hp = [str(x or "").strip() for x in (pref.get("header") or [])]
            rc = list(cat.get("rows") or [])
            rp = list(pref.get("rows") or [])

            def idx(cols: list[str], name: str) -> int | None:
                for j, c in enumerate(cols):
                    if str(c or "").strip() == name:
                        return int(j)
                return None

            c_cat = idx(hc, "类别") or 0
            p_cat = idx(hp, "类别") or 0
            map_c = _row_map_by_key(rc, key_idx=int(c_cat))
            map_p = _row_map_by_key(rp, key_idx=int(p_cat))
            cats = sorted({*map_c.keys(), *map_p.keys()})

            c_n = idx(hc, "信号数量")
            c_p = idx(hc, "占比%")
            p_n = idx(hp, "信号数量")
            p_p = idx(hp, "占比%")

            new_header = ["类别", "信号数量", "占比%", "聪明钱信号数量", "聪明钱占比%"]
            new_rows: list[list[Any]] = []
            for c0 in cats:
                rc0 = map_c.get(c0) or []
                rp0 = map_p.get(c0) or []
                new_rows.append(
                    [
                        c0,
                        rc0[int(c_n)] if c_n is not None and int(c_n) < len(rc0) else "",
                        rc0[int(c_p)] if c_p is not None and int(c_p) < len(rc0) else "",
                        rp0[int(p_n)] if p_n is not None and int(p_n) < len(rp0) else "",
                        rp0[int(p_p)] if p_p is not None and int(p_p) < len(rp0) else "",
                    ]
                )

            composite = {"title_plain": "类别偏好汇总", "header": new_header, "rows": new_rows, "n_cols": len(new_header)}
            for rm in sorted([idx_cat, idx_pref], reverse=True):
                sections.pop(int(rm))
            sections.insert(min(int(idx_cat), int(idx_pref)), composite)

        # -------------------- enforce: Top15 hot-only (child tab) --------------------
        # 用户要求：PolymarketTop15 子表只保留“综合热门市场 Top 15”。
        # 注意：即使上游 split 已过滤，这里仍做一次兜底，避免“Top 15 长表”在报表整形阶段被重建。
        tab_top15 = _env_text("SHEETS_TAB_POLYMARKET_TOP15", "PolymarketTop15")
        top15_hot_only = (os.environ.get("SHEETS_POLYMARKET_TOP15_HOT_ONLY", "1") or "1").strip() != "0"
        if top15_hot_only and str(tab_title).strip() == tab_top15:
            keep_titles = {"综合热门市场 Top 15"}
            sections = [s for s in sections if str(s.get("title_plain") or "").strip() in keep_titles]

        # -------------------- bundle: Top15 -> long table --------------------
        # 说明：综合热门市场 Top 15 自带多指标（套利/大额/订单簿/聪明钱/总计），如果强行“长表化”
        # 会造成同一市场重复出现 5 次，阅读上被认为“重复”。因此这里只把“单指标 Top 15”转为长表，
        # 综合热门保持原表形态（但会被提到更靠前的位置）。
        top15_long_names = ["大额交易 Top 15", "新市场 Top 15", "聪明钱 Top 15"]
        top15_hot_name = "综合热门市场 Top 15"

        top15_long_secs = [s for s in sections if str(s.get("title_plain") or "").strip() in set(top15_long_names)]
        if top15_long_secs:
            # remove originals (keep order from `top15_long_names`)
            wanted = {n: i for i, n in enumerate(top15_long_names)}
            top15_long_secs.sort(key=lambda s: wanted.get(str(s.get("title_plain") or "").strip(), 10**9))
            sections = [s for s in sections if str(s.get("title_plain") or "").strip() not in set(top15_long_names)]

            # 长表只保留“单指标 Top 15”，结构固定为：类型/排名/市场名称/指标/数值
            # 这样避免出现“次数”和“数值”重复两列导致的视觉冗余。
            long_header = ["类型", "排名", "市场名称", "指标", "数值"]
            long_rows: list[list[Any]] = []
            long_links: list[tuple[int, int, str, str]] = []
            for sec in top15_long_secs:
                tname = str(sec.get("title_plain") or "").strip()
                hdr = [str(x or "").strip() for x in (sec.get("header") or [])]
                rows = list(sec.get("rows") or [])
                c_rank = _col_idx(hdr, "排名") or 0
                c_name = _col_idx(hdr, "市场名称")
                if c_name is None:
                    c_name = _col_idx(hdr, "市场") or 1
                c_link = _col_idx(hdr, "链接")

                metric_cols: list[tuple[str, int]] = []
                for mn in ["交易次数", "出现次数", "信号次数", "信号数量"]:
                    ci = _col_idx(hdr, mn)
                    if ci is not None:
                        metric_cols = [(mn, int(ci))]
                        break

                for r in rows:
                    rank = r[int(c_rank)] if int(c_rank) < len(r) else ""
                    name = r[int(c_name)] if int(c_name) < len(r) else ""
                    url = r[int(c_link)] if (c_link is not None and int(c_link) < len(r)) else ""
                    if not metric_cols:
                        metric_cols = [("次数", -1)]
                    for metric_name, ci in metric_cols:
                        val = r[int(ci)] if (int(ci) >= 0 and int(ci) < len(r)) else ""
                        long_rows.append([tname, rank, name, metric_name, val])
                        if url and isinstance(url, str) and url.startswith("http") and name:
                            long_links.append((len(long_rows) - 1, 2, str(url), str(name)))

            sections.insert(
                0,
                {
                    "title_plain": "Top 15",
                    "header": long_header,
                    "rows": long_rows,
                    "n_cols": len(long_header),
                    "hyperlinks": long_links,
                },
            )

            # 把“综合热门市场 Top 15”提到更靠前（紧跟长表后面），保持原表结构不重复。
            idx_hot = None
            for idx, sec in enumerate(sections):
                if str(sec.get("title_plain") or "").strip() == top15_hot_name:
                    idx_hot = int(idx)
                    break
            if idx_hot is not None:
                hot_sec = sections.pop(int(idx_hot))
                sections.insert(1, hot_sec)

        # -------------------- build report rows --------------------
        out: list[list[Any]] = []
        if int(banner_rows) > 0 and banner_text:
            out.append([banner_text])
        out.append([meta_text])
        out.append(["目录（点击跳转）"])

        panel_col_name = "面板"
        anchors: list[tuple[str, int, int]] = []  # (panel_title, header_row1-based, header_rows_count)
        hyperlink_cells: list[tuple[int, int, str, str]] = []  # (abs_row0, abs_col0, url, label)
        extra_merge_ranges: list[tuple[int, int, int, int]] = []  # (r0,r1,c0,c1) end exclusive
        panel_value_ranges: list[tuple[int, int]] = []  # (r0,r1) for column A data blocks (end exclusive)
        data_value_ranges: list[tuple[int, int]] = []  # (r0,r1) for full-row data blocks (end exclusive)

        # 某些“附加统计小表”不需要重复表头（会造成视觉噪声与行号浪费）。
        # 用户要求：Polymarket类别偏好 删除第 10、14 行（对应：买卖比例/聪明钱操作类型 的表头行）。
        # 这里通过“跳过该两段的分段表头”实现：保留数据行，但不再插入额外表头行。
        tab_category = _env_text("SHEETS_TAB_POLYMARKET_CATEGORY", "Polymarket类别偏好")
        drop_section_headers = set()
        if str(tab_title).strip() == str(tab_category).strip():
            drop_section_headers = {"买卖比例", "聪明钱操作类型"}

        for sec in sections:
            title_plain = str(sec.get("title_plain") or "").strip() or "-"
            headers = sec.get("headers")
            if not isinstance(headers, list) or not headers:
                headers = [list(sec.get("header") or [])]
            emit_headers = title_plain not in drop_section_headers

            # anchor：目录跳转目标
            anchor_row0 = len(out)
            hdr_n = int(len(headers)) if emit_headers else 0
            anchors.append((title_plain, int(anchor_row0 + 1), int(hdr_n)))

            # 分段表头（可选）：新增第一列“面板”
            if emit_headers:
                for hi, hr in enumerate(headers):
                    prefix = panel_col_name if hi == int(len(headers)) - 1 else ""
                    out.append([prefix] + [str(x) for x in (hr or [])])

            data_start_row0 = len(out)
            sec_rows = list(sec.get("rows") or [])
            for r in sec_rows:
                # 数据行：第一列填入“面板”值（原来整行分区标题）
                out.append([title_plain] + list(r))
            if sec_rows:
                data_value_ranges.append((int(data_start_row0), int(data_start_row0 + len(sec_rows))))
            if len(sec_rows) >= 2:
                # “面板”列纵向合并：同一分段的数据行块合并，提升可读性
                # - 不影响数据字段；仅展示优化
                panel_value_ranges.append((int(data_start_row0), int(data_start_row0 + len(sec_rows))))
                extra_merge_ranges.append((int(data_start_row0), int(data_start_row0 + len(sec_rows)), 0, 1))
            # hyperlinks: relative to data rows
            for li in (sec.get("hyperlinks") or []):
                try:
                    ri, ci, url, label = li
                except Exception:
                    continue
                # 由于新增了“面板”列，超链接列索引整体右移 +1
                hyperlink_cells.append((int(data_start_row0 + int(ri)), int(ci) + 1, str(url), str(label)))

            # Top 15：合并“类型”列的连续块（提升可读性；不影响数据内容/超链接）
            merge_type_col = (
                (os.environ.get("SHEETS_POLYMARKET_REPORT_MERGE_TYPE_COL", "1") or "1").strip() != "0"
            )
            if merge_type_col and title_plain == "Top 15" and sec_rows:
                cur = None
                cur_s = 0
                for i, r in enumerate(sec_rows):
                    v = ""
                    try:
                        v = str((r[0] if r else "") or "").strip()
                    except Exception:
                        v = ""
                    if cur is None:
                        cur = v
                        cur_s = int(i)
                        continue
                    if v != cur:
                        if int(i) - int(cur_s) >= 2:
                            r0 = int(data_start_row0 + int(cur_s))
                            r1 = int(data_start_row0 + int(i))
                            # 新增了“面板”列，因此“类型”列变为第 2 列（B）
                            extra_merge_ranges.append((int(r0), int(r1), 1, 2))
                        cur = v
                        cur_s = int(i)
                if cur is not None and int(len(sec_rows)) - int(cur_s) >= 2:
                    r0 = int(data_start_row0 + int(cur_s))
                    r1 = int(data_start_row0 + int(len(sec_rows)))
                    extra_merge_ranges.append((int(r0), int(r1), 1, 2))

        frozen_cols = _polymarket_frozen_cols()
        frozen_rows = _polymarket_frozen_rows(anchors=anchors)
        if int(banner_rows) > 0:
            frozen_rows = max(int(frozen_rows), 2 + int(banner_rows))

        # normalize to rect
        n_rows = len(out)
        n_cols = max((len(r) for r in out if isinstance(r, list)), default=1)
        n_cols = max(int(n_cols), 1)
        for r in out:
            if len(r) < n_cols:
                r.extend([""] * (n_cols - len(r)))

        # -------------------- empty placeholders（纯函数绘制对角线） --------------------
        # 需求：对“分段数据行”末尾无数据列（例如 Polymarket类别偏好 E11:F16）用反斜线占位。
        # - 仅填充每行的“尾部空白列”，避免破坏面板列的纵向合并（A 列空白属于合并块，不应写入）
        # - 只对数据区生效（data_value_ranges），不影响 banner/meta/目录/表头
        placeholder_mode = _empty_placeholder_mode()
        placeholder_char = _empty_placeholder_char() if placeholder_mode == "char" else ""
        sparkline_cells: list[tuple[int, int]] = []  # (row_1, col_1)
        if placeholder_mode in {"sparkline", "char"} and data_value_ranges:
            for r0, r1 in data_value_ranges:
                rr0 = max(int(r0), 0)
                rr1 = min(int(r1), int(n_rows))
                for ri in range(int(rr0), int(rr1)):
                    row = out[int(ri)] if 0 <= int(ri) < len(out) else []
                    last_nonblank = -1
                    for ci in range(int(n_cols) - 1, -1, -1):
                        v = row[int(ci)] if int(ci) < len(row) else ""
                        if not _is_blank_cell(v):
                            last_nonblank = int(ci)
                            break
                    for ci in range(int(last_nonblank) + 1, int(n_cols)):
                        if placeholder_mode == "char":
                            if int(ci) < len(row):
                                row[int(ci)] = placeholder_char
                        else:
                            sparkline_cells.append((int(ri) + 1, int(ci) + 1))

        # -------------------- write values --------------------
        self._ensure_grid_size(tab_title, min_rows=int(n_rows), min_cols=int(n_cols))
        col_r = _index_to_col(int(n_cols))
        self._exec(
            self._sheets.spreadsheets()
            .values()
            .update(
                spreadsheetId=self._spreadsheet_id,
                range=f"{tab_title}!A1:{col_r}{int(n_rows)}",
                valueInputOption="RAW",
                body={"values": out},
            ),
            is_write=True,
        )

        # SPARKLINE 占位必须在 values.update(RAW) 之后执行：RAW 会把公式当文本写入。
        if placeholder_mode == "sparkline" and sparkline_cells:
            try:
                formula = _sparkline_backslash_formula(locale=getattr(self, "_spreadsheet_locale", None))
                self._apply_cell_formulas(sheet_title=tab_title, cells=sparkline_cells, formula=formula)
            except Exception:
                pass

        # tail clear（避免历史残留）
        compact_grid = (os.environ.get("SHEETS_POLYMARKET_COMPACT_GRID", "1") or "1").strip() != "0"
        meta = self._meta_get()
        key_rows = f"pmtab.{tab_title}.rows"
        key_cols = f"pmtab.{tab_title}.cols"
        try:
            r_old = int(str(meta.get(key_rows) or "0").strip() or "0")
        except Exception:
            r_old = 0
        try:
            c_old = int(str(meta.get(key_cols) or "0").strip() or "0")
        except Exception:
            c_old = 0
        if not compact_grid:
            if int(r_old) > int(n_rows):
                try:
                    self._exec(
                        self._sheets.spreadsheets()
                        .values()
                        .clear(
                            spreadsheetId=self._spreadsheet_id,
                            range=f"{tab_title}!A{int(n_rows) + 1}:{_index_to_col(max(int(c_old), int(n_cols)))}{int(r_old)}",
                        ),
                        is_write=True,
                    )
                except Exception as exc:
                    print(f"⚠️ pmtab.report_tail_clear_rows_failed tab={tab_title} {type(exc).__name__}: {exc}")
            if int(c_old) > int(n_cols):
                try:
                    self._exec(
                        self._sheets.spreadsheets()
                        .values()
                        .clear(
                            spreadsheetId=self._spreadsheet_id,
                            range=f"{tab_title}!{_index_to_col(int(n_cols) + 1)}1:{_index_to_col(int(c_old))}{max(int(r_old), int(n_rows))}",
                        ),
                        is_write=True,
                    )
                except Exception as exc:
                    print(f"⚠️ pmtab.report_tail_clear_cols_failed tab={tab_title} {type(exc).__name__}: {exc}")

        # -------------------- merges --------------------
        merge_ranges: list[tuple[int, int, int, int]] = []
        # 注意：Google Sheets 不允许跨“冻结列分割线”做横向 merge。
        # - 当启用冻结列时（默认冻结面板列），这里禁用 A1/A2 的整行合并，改为单单元格溢出显示。
        if int(n_cols) > 1 and int(frozen_cols) <= 0:
            # banner（可选）+ meta + directory：整行横向合并（不冻结列时允许）
            if int(banner_rows) > 0:
                merge_ranges.append((0, 1, 0, int(n_cols)))  # banner
            merge_ranges.append((int(meta_row_0), int(meta_row_0) + 1, 0, int(n_cols)))  # meta
            merge_ranges.append((int(dir_row_0), int(dir_row_0) + 1, 0, int(n_cols)))  # directory
        # 结构调整：不再存在“分区标题行整行合并”，改为新增第一列“面板”承载分区名。
        # 因此 anchors 行是“表头行”，严禁整行 merge（否则表头只剩第一个单元格可见）。
        merge_ranges.extend(extra_merge_ranges)

        if merge_ranges:
            reqs_merge: list[dict[str, Any]] = [{"unmergeCells": {"range": {"sheetId": int(sh_id)}}}]
            for r0, r1, c0, c1 in merge_ranges:
                if r0 < 0 or r1 <= r0 or c0 < 0 or c1 <= c0:
                    continue
                reqs_merge.append(
                    {
                        "mergeCells": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": int(r0),
                                "endRowIndex": int(r1),
                                "startColumnIndex": int(c0),
                                "endColumnIndex": int(c1),
                            },
                            "mergeType": "MERGE_ALL",
                        }
                    }
                )
            try:
                self._exec(
                    self._sheets.spreadsheets().batchUpdate(spreadsheetId=self._spreadsheet_id, body={"requests": reqs_merge}),
                    is_write=True,
                )
            except Exception:
                pass

        # -------------------- styles --------------------
        # 版式版本号：用于强制重刷样式（避免历史残留/手工拖拽后的漂移）。
        # v8：B 列（行标题/索引列）强制居中+加粗（覆盖数据区右对齐）。
        style_version = "polymarket_report_v8"
        key_style_version = f"pmtab.{tab_title}.style_version"
        key_style_rows = f"pmtab.{tab_title}.style_rows"
        key_style_cols = f"pmtab.{tab_title}.style_cols"
        try:
            styled_rows = int(str(meta.get(key_style_rows) or "0").strip() or "0")
        except Exception:
            styled_rows = 0
        try:
            styled_cols = int(str(meta.get(key_style_cols) or "0").strip() or "0")
        except Exception:
            styled_cols = 0
        need_style = (meta.get(key_style_version) or "") != style_version or styled_rows != int(n_rows) or styled_cols != int(n_cols)
        if need_style:
            def _clamp(v: int, lo: int, hi: int) -> int:
                return max(int(lo), min(int(v), int(hi)))

            def _approx_px_from_text_len(n: int) -> int:
                return int(20 + int(n) * 7)

            min_px = int((os.environ.get("SHEETS_POLYMARKET_COL_WIDTH_MIN", "56") or "56").strip() or "56")
            max_px = int((os.environ.get("SHEETS_POLYMARKET_COL_WIDTH_MAX", "420") or "420").strip() or "420")
            widths_by_col: list[int] = []
            for ci in range(0, int(n_cols)):
                max_len = 0
                for ri in range(0, min(int(n_rows), 600)):
                    s = ""
                    try:
                        s = str(out[ri][ci] if ci < len(out[ri]) else "")
                    except Exception:
                        s = ""
                    if not s or s.startswith("http"):
                        continue
                    max_len = max(max_len, len(s))
                widths_by_col.append(_clamp(_approx_px_from_text_len(max_len), min_px, max_px))

            reqs: list[dict[str, Any]] = []
            reqs.append(
                {
                    "repeatCell": {
                        "range": {"sheetId": int(sh_id), "startRowIndex": 0, "endRowIndex": int(n_rows), "startColumnIndex": 0, "endColumnIndex": int(n_cols)},
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": _rgb(1.0, 1.0, 1.0),
                                "textFormat": {"fontFamily": "Arial", "fontSize": 10},
                                "horizontalAlignment": "LEFT",
                                "verticalAlignment": "MIDDLE",
                                "wrapStrategy": "CLIP",
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,wrapStrategy)",
                    }
                }
            )
            for ci, px in enumerate(widths_by_col):
                reqs.append(
                    {
                        "updateDimensionProperties": {
                            "range": {"sheetId": int(sh_id), "dimension": "COLUMNS", "startIndex": int(ci), "endIndex": int(ci + 1)},
                            "properties": {"pixelSize": int(px)},
                            "fields": "pixelSize",
                        }
                    }
                )
            reqs.append(
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": int(sh_id),
                            "gridProperties": {
                                "frozenRowCount": int(frozen_rows),
                                "frozenColumnCount": int(frozen_cols),
                                "hideGridlines": False,
                            },
                        },
                        "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount,gridProperties.hideGridlines",
                    }
                }
            )

            # banner 行（可选）：全表首行广告位
            if int(banner_rows) > 0:
                try:
                    banner_lines = int(banner_line_count or 1)
                except Exception:
                    banner_lines = 1
                banner_lines = max(1, min(int(banner_lines), 6))
                banner_row_px = int(21 * int(banner_lines))

                reqs.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": 0,
                                "endRowIndex": 1,
                                "startColumnIndex": 0,
                                "endColumnIndex": int(n_cols),
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": _rgb(1.0, 0.97, 0.86),
                                    "textFormat": {"bold": True},
                                    "horizontalAlignment": "LEFT",
                                    "verticalAlignment": "MIDDLE",
                                    "wrapStrategy": "OVERFLOW_CELL",
                                }
                            },
                            "fields": "userEnteredFormat(backgroundColor,textFormat.bold,horizontalAlignment,verticalAlignment,wrapStrategy)",
                        }
                    }
                )
                reqs.append(
                    {
                        "updateDimensionProperties": {
                            "range": {"sheetId": int(sh_id), "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
                            "properties": {"pixelSize": int(banner_row_px)},
                            "fields": "pixelSize",
                        }
                    }
                )
                # 视觉合并：遮蔽 banner 行内部竖线（冻结列开启时无法真 merge）
                reqs.append(
                    {
                        "updateBorders": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": 0,
                                "endRowIndex": 1,
                                "startColumnIndex": 0,
                                "endColumnIndex": int(n_cols),
                            },
                            "innerVertical": {"style": "SOLID", "width": 1, "color": _rgb(1.0, 0.97, 0.86)},
                        }
                    }
                )

            # meta 行（单单元格溢出，不换行）
            reqs.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": int(sh_id),
                            "startRowIndex": int(meta_row_0),
                            "endRowIndex": int(meta_row_0) + 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": int(n_cols),
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": _rgb(0.93, 0.94, 0.96),
                                "textFormat": {"bold": True},
                                "horizontalAlignment": "LEFT",
                                "wrapStrategy": "OVERFLOW_CELL",
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat.bold,horizontalAlignment,wrapStrategy)",
                    }
                }
            )

            # directory 行（富文本超链接）
            reqs.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": int(sh_id),
                            "startRowIndex": int(dir_row_0),
                            "endRowIndex": int(dir_row_0) + 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": int(n_cols),
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": _rgb(0.97, 0.98, 1.0),
                                "textFormat": {"bold": True},
                                "horizontalAlignment": "LEFT",
                                "wrapStrategy": "OVERFLOW_CELL",
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat.bold,horizontalAlignment,wrapStrategy)",
                    }
                }
            )

            header_bg = _rgb(0.93, 0.94, 0.96)
            for _t, r1, hn in anchors:
                r0 = int(r1) - 1
                hn = int(hn)
                if hn > 0:
                    reqs.append(
                        {
                            "repeatCell": {
                                # 结构调整：不再写“分区标题行”，改为新增第一列“面板”承载分区名。
                                # 因此 anchor 行本身就是表头起始行，直接对 hn 行表头做样式。
                                "range": {
                                    "sheetId": int(sh_id),
                                    "startRowIndex": int(r0),
                                    "endRowIndex": int(r0 + hn),
                                    "startColumnIndex": 0,
                                    "endColumnIndex": int(n_cols),
                                },
                                "cell": {
                                    "userEnteredFormat": {
                                        "backgroundColor": header_bg,
                                        "textFormat": {"bold": True},
                                        "horizontalAlignment": "CENTER",
                                        "wrapStrategy": "CLIP",
                                    }
                                },
                                "fields": "userEnteredFormat(backgroundColor,textFormat.bold,horizontalAlignment,wrapStrategy)",
                            }
                        }
                    )

            # 面板列（A）：同一面板的合并块加粗（对齐“数据区全右对齐”的需求，不再强制居中）
            for r0, r1 in panel_value_ranges:
                if int(r1) <= int(r0):
                    continue
                reqs.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": int(r0),
                                "endRowIndex": int(r1),
                                "startColumnIndex": 0,
                                "endColumnIndex": 1,
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "verticalAlignment": "MIDDLE",
                                    "horizontalAlignment": "CENTER",
                                    "textFormat": {"bold": True},
                                    "wrapStrategy": "CLIP",
                                }
                            },
                            "fields": "userEnteredFormat(verticalAlignment,horizontalAlignment,textFormat.bold,wrapStrategy)",
                        }
                    }
                )

            # 用户要求：这 3 个 Polymarket 表的数据全部右对齐（不影响元信息/目录/表头行）
            # - 仅对数据块范围生效，避免把“表头行”改成右对齐
            # - 同时：A 列“面板”属于列表头/分段标签，应居中；因此右对齐从 B 列开始。
            pm_has_panel_col = False
            try:
                for ri in range(0, min(int(n_rows), 16)):
                    row = out[ri] if 0 <= ri < len(out) else []
                    if row and str(row[0] or "").strip() == "面板":
                        pm_has_panel_col = True
                        break
            except Exception:
                pm_has_panel_col = False
            data_c0 = 1 if pm_has_panel_col else 0
            for r0, r1 in data_value_ranges:
                if int(r1) <= int(r0):
                    continue
                reqs.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": int(r0),
                                "endRowIndex": int(r1),
                                "startColumnIndex": int(data_c0),
                                "endColumnIndex": int(n_cols),
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "horizontalAlignment": "RIGHT",
                                    "verticalAlignment": "MIDDLE",
                                    "wrapStrategy": "CLIP",
                                }
                            },
                            "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment,wrapStrategy)",
                        }
                    }
                )

            # 行标题列/索引列（B）：强制居中 + 加粗（覆盖上面的“全右对齐”）。
            # - Top15: 排名
            # - 时段分布: 小时
            # - 类别偏好: 类别/子类目
            if pm_has_panel_col and int(n_cols) >= 2:
                for r0, r1 in data_value_ranges:
                    if int(r1) <= int(r0):
                        continue
                    reqs.append(
                        {
                            "repeatCell": {
                                "range": {
                                    "sheetId": int(sh_id),
                                    "startRowIndex": int(r0),
                                    "endRowIndex": int(r1),
                                    "startColumnIndex": 1,
                                    "endColumnIndex": 2,
                                },
                                "cell": {
                                    "userEnteredFormat": {
                                        "horizontalAlignment": "CENTER",
                                        "verticalAlignment": "MIDDLE",
                                        "textFormat": {"bold": True},
                                        "wrapStrategy": "CLIP",
                                    }
                                },
                                "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment,textFormat.bold,wrapStrategy)",
                            }
                        }
                    )

            self._exec(self._sheets.spreadsheets().batchUpdate(spreadsheetId=self._spreadsheet_id, body={"requests": reqs}), is_write=True)
            self._meta_set({key_style_version: style_version, key_style_rows: str(n_rows), key_style_cols: str(n_cols)})

        # 列宽：每次都对齐（用户可能手工拖拽导致漂移；这里按内容采样恢复合理宽度）
        try:
            def _clamp(v: int, lo: int, hi: int) -> int:
                return max(int(lo), min(int(v), int(hi)))

            def _approx_px_from_text_len(n: int) -> int:
                return int(20 + int(n) * 7)

            def _is_url(s: str) -> bool:
                x = (s or "").strip().lower()
                return x.startswith("http://") or x.startswith("https://")

            min_px = int((os.environ.get("SHEETS_POLYMARKET_COL_WIDTH_MIN", "56") or "56").strip() or "56")
            max_px = int((os.environ.get("SHEETS_POLYMARKET_COL_WIDTH_MAX", "420") or "420").strip() or "420")
            w_link = int((os.environ.get("SHEETS_POLYMARKET_COL_WIDTH_LINK", "40") or "40").strip() or "40")
            w_key = int((os.environ.get("SHEETS_POLYMARKET_COL_WIDTH_KEY", "72") or "72").strip() or "72")
            # 新增“面板”列后，A 列应按“面板值长度”自适应（而不是被第 1/2 行超长元信息撑爆）。
            # - 仍保留 env 可覆盖上下限，避免极端面板名导致列宽失控
            try:
                panel_min_px = int(
                    (os.environ.get("SHEETS_POLYMARKET_COL_WIDTH_PANEL_MIN", "40") or "40").strip() or "40"
                )
            except Exception:
                panel_min_px = 40
            try:
                panel_max_px = int(
                    (os.environ.get("SHEETS_POLYMARKET_COL_WIDTH_PANEL_MAX", "160") or "160").strip() or "160"
                )
            except Exception:
                panel_max_px = 160

            # 固化列宽（优先级最高）：用于“你手工在表格里调好列宽后，希望后续刷新不再覆盖”。
            # - 仅对 3 个 Polymarket 拆分报表生效
            tab_top15 = _env_text("SHEETS_TAB_POLYMARKET_TOP15", "PolymarketTop15")
            tab_timeslot = _env_text("SHEETS_TAB_POLYMARKET_TIMESLOT", "Polymarket时段分布")
            tab_category = _env_text("SHEETS_TAB_POLYMARKET_CATEGORY", "Polymarket类别偏好")
            fixed_key = ""
            if tab_title == tab_top15:
                fixed_key = "SHEETS_POLYMARKET_FIXED_COL_WIDTHS_TOP15"
            elif tab_title == tab_timeslot:
                fixed_key = "SHEETS_POLYMARKET_FIXED_COL_WIDTHS_TIMESLOT"
            elif tab_title == tab_category:
                fixed_key = "SHEETS_POLYMARKET_FIXED_COL_WIDTHS_CATEGORY"

            fixed_widths = _env_int_list(fixed_key) if fixed_key else []
            widths: list[int] = []
            if fixed_widths:
                for x in fixed_widths:
                    try:
                        v = int(x)
                    except Exception:
                        continue
                    if v <= 0:
                        continue
                    widths.append(max(v, 20))
                if widths and len(widths) < int(n_cols):
                    widths.extend([int(widths[-1])] * (int(n_cols) - len(widths)))
                if widths and len(widths) > int(n_cols):
                    widths = widths[: int(n_cols)]

            scan_rows = min(int(n_rows), 600)
            # 跳过前两行（元信息/目录）：它们通常是超长文本，会把 A 列撑到 max_px，导致数据区难读。
            scan_r0 = 2 if int(scan_rows) > 2 else 0

            # 判断是否存在“面板”列（避免对其他 Polymarket tab 误判）
            has_panel_col = False
            try:
                for ri in range(2, min(int(scan_rows), 12)):
                    row = out[ri] if 0 <= ri < len(out) else []
                    if row and str(row[0] or "").strip() == "面板":
                        has_panel_col = True
                        break
            except Exception:
                has_panel_col = False

            if not widths:
                panel_px = None
                if has_panel_col:
                    # 仅看“面板列”真实值（跳过表头），估计一个合理列宽
                    panel_max_len = 0
                    for ri in range(int(scan_r0), int(scan_rows)):
                        row = out[ri] if 0 <= ri < len(out) else []
                        if not row:
                            continue
                        s = str(row[0] or "").strip()
                        if not s or s == "面板":
                            continue
                        # 合并后的“空白占位”也跳过（有些行可能在后续 merge 后显示为空）
                        if s in {"-", "—"}:
                            continue
                        panel_max_len = max(int(panel_max_len), min(len(s), 48))
                    if int(panel_max_len) > 0:
                        # 关键：只看“面板列字段值”的最长长度。
                        # 面板列通常是短标签：用更激进的压缩系数（6px/字符）提升信息密度。
                        px = int(16 + int(panel_max_len) * 6)
                        panel_px = _clamp(int(px), int(panel_min_px), int(panel_max_px))
                for ci in range(0, int(n_cols)):
                    max_len = 0
                    has_link_header = False
                    has_name_header = False
                    has_rank_header = False
                    has_hour_header = False
                    for ri in range(int(scan_r0), int(scan_rows)):
                        s = ""
                        try:
                            s = str(out[ri][ci] if ci < len(out[ri]) else "")
                        except Exception:
                            s = ""
                        s = str(s or "").strip()
                        if not s:
                            continue
                        if s in {"链接", "link", "url", "URL"} or ("链接" in s):
                            has_link_header = True
                        if s in {"市场名称", "市场", "market", "question", "名称"}:
                            has_name_header = True
                        if s == "排名":
                            has_rank_header = True
                        if s in {"小时", "hour", "Hour"}:
                            has_hour_header = True
                        if _is_url(s):
                            continue
                        max_len = max(max_len, min(len(s), 60))

                    if has_panel_col and int(ci) == 0:
                        px = (
                            int(panel_px)
                            if panel_px is not None
                            else _clamp(_approx_px_from_text_len(8), int(panel_min_px), int(panel_max_px))
                        )
                    elif has_link_header:
                        px = int(w_link)
                    elif has_rank_header or has_hour_header:
                        px = int(w_key)
                    elif has_name_header:
                        px = _approx_px_from_text_len(max(max_len, 18))
                    else:
                        px = _approx_px_from_text_len(max(max_len, 6))
                    widths.append(_clamp(int(px), int(min_px), int(max_px)))

            if widths:
                reqs_w = []
                for ci, px in enumerate(widths):
                    reqs_w.append(
                        {
                            "updateDimensionProperties": {
                                "range": {"sheetId": int(sh_id), "dimension": "COLUMNS", "startIndex": int(ci), "endIndex": int(ci + 1)},
                                "properties": {"pixelSize": int(px)},
                                "fields": "pixelSize",
                            }
                        }
                    )
                self._exec(
                    self._sheets.spreadsheets().batchUpdate(spreadsheetId=self._spreadsheet_id, body={"requests": reqs_w}),
                    is_write=True,
                )
        except Exception:
            pass

        # compact grid：让“无数据区域”在 UI 中消失
        if compact_grid:
            self._set_sheet_grid_properties(
                tab_title,
                row_count=int(n_rows),
                col_count=int(n_cols),
                frozen_row_count=int(frozen_rows),
                frozen_column_count=int(frozen_cols),
            )

        # gridlines：强制不隐藏（历史版本可能设置为隐藏；这里确保后续写入不会“又变成纯底色”）
        try:
            self._exec(
                self._sheets.spreadsheets().batchUpdate(
                    spreadsheetId=self._spreadsheet_id,
                    body={
                        "requests": [
                            {
                                "updateSheetProperties": {
                                    "properties": {"sheetId": int(sh_id), "gridProperties": {"hideGridlines": False}},
                                    "fields": "gridProperties.hideGridlines",
                                }
                            }
                        ]
                    },
                ),
                is_write=True,
            )
        except Exception:
            pass

        # directory richtext links（目录行）
        try:
            def idx_len(s: str) -> int:
                return _utf16_len(str(s))

            label = "目录（点击跳转）"
            parts = [label]
            runs: list[dict[str, Any]] = [{"startIndex": 0, "format": {}}]
            pos = int(idx_len(label))
            for title_plain, r1, _hn in anchors:
                sep = "，"
                parts.append(sep)
                pos += int(idx_len(sep))
                start = int(pos)
                parts.append(title_plain)
                pos += int(idx_len(title_plain))
                end = int(pos)
                url = f"https://docs.google.com/spreadsheets/d/{self._spreadsheet_id}/edit#gid={int(sh_id)}&range=A{int(r1)}"
                runs.append({"startIndex": int(start), "format": {"link": {"uri": str(url)}, "foregroundColor": _rgb(0.1, 0.4, 0.8), "underline": True}})
                runs.append({"startIndex": int(end), "format": {}})
            dir_text = "".join(parts)
            text_len = int(idx_len(dir_text))
            while runs and int(runs[-1].get("startIndex", 0) or 0) >= int(text_len):
                runs.pop()
            self._exec(
                self._sheets.spreadsheets().batchUpdate(
                    spreadsheetId=self._spreadsheet_id,
                    body={
                        "requests": [
                            {
                                "updateCells": {
                                    "range": {"sheetId": int(sh_id), "startRowIndex": int(dir_row_0), "endRowIndex": int(dir_row_0) + 1, "startColumnIndex": 0, "endColumnIndex": 1},
                                    "rows": [{"values": [{"userEnteredValue": {"stringValue": str(dir_text)}, "textFormatRuns": runs}]}],
                                    "fields": "userEnteredValue,textFormatRuns",
                                }
                            }
                        ]
                    },
                ),
                is_write=True,
            )
        except Exception as exc:
            print(f"⚠️ pmtab.report_dir_links_failed tab={tab_title} {type(exc).__name__}: {exc}")

        # hyperlinks: apply formulas (diff)
        def _escape_formula_str(s: str) -> str:
            return str(s or "").replace('"', '""').replace("\n", " ").replace("\r", " ")

        data_updates: list[dict[str, Any]] = []
        for rr0, cc0, url, label in hyperlink_cells:
            if not url or not str(url).startswith("http"):
                continue
            cell = f"{tab_title}!{_index_to_col(int(cc0) + 1)}{int(rr0 + 1)}"
            formula = f'=HYPERLINK("{_escape_formula_str(url)}","{_escape_formula_str(label)}")'
            data_updates.append({"range": cell, "values": [[formula]]})
        if data_updates:
            try:
                print(f"[DEBUG] pmtab.report_hyperlinks_prepare tab={tab_title} count={len(data_updates)}")
                self._exec(
                    self._sheets.spreadsheets()
                    .values()
                    .batchUpdate(
                        spreadsheetId=self._spreadsheet_id,
                        body={"valueInputOption": "USER_ENTERED", "data": data_updates},
                    ),
                    is_write=True,
                )
            except Exception:
                pass

        self._meta_set({key_rows: str(n_rows), key_cols: str(n_cols)})
        return {"ok": True, "tab": tab_title, "rows": int(n_rows), "cols": int(n_cols)}

    def _write_polymarket_stats_tabs_split_report(
        self,
        *,
        tab_title: str,
        values: list[list[Any]],
        panel_title_rows: list[int],
        panel_header_rows: list[int],
    ) -> dict[str, Any]:
        """
        Polymarket统计 拆分为 3 个表（阅读更聚焦，减少“单页过长+定位困难”）：
        - Polymarket时段分布：时段相关分布
        - PolymarketTop15：Top 15（含综合热门）
        - Polymarket类别偏好：类别分布与聪明钱偏好

        注意：
        - 这里只拆“统计报表 tab”，不影响 Polymarket事件（facts）明细表。
        - 原 tab（tab_title，通常为 Polymarket统计）会被隐藏，避免用户看到重复面板。
        """
        def strip_leading_emoji(s: str) -> str:
            return re.sub(r"^[^0-9A-Za-z\u4e00-\u9fff]+\s*", "", str(s or "")).strip()

        def trim_row(r: list[Any]) -> list[Any]:
            rr = list(r)
            while rr and (rr[-1] == "" or rr[-1] is None):
                rr.pop()
            return rr

        title_idx = sorted({int(r) - 1 for r in panel_title_rows if int(r) >= 2})
        header_idx_set = {int(r) - 1 for r in panel_header_rows if int(r) >= 2}
        drop_cols_raw = (os.environ.get("SHEETS_POLYMARKET_DROP_COLUMNS", "买卖比例,聪明钱操作类型") or "").strip()
        drop_names = {s.strip() for s in re.split(r"[,，]", drop_cols_raw) if s.strip()}

        meta_text = ""
        try:
            meta_text = str((values[0] or [""])[0] or "").strip()
        except Exception:
            meta_text = ""
        if meta_text and ("窗口" not in meta_text) and ("24h" not in meta_text.lower()):
            meta_text = f"{meta_text}，窗口，滚动24h"

        def normalize_title(s: str) -> str:
            x = str(s or "").strip()
            for suf in [" (本地时间)", "（本地时间）"]:
                if x.endswith(suf):
                    x = x[: -len(suf)].rstrip()
            return x

        # -------------------- raw section parse (from exporter markers) --------------------
        sections: list[dict[str, Any]] = []
        for i, t0 in enumerate(title_idx):
            t0 = int(t0)
            t1 = int(title_idx[i + 1]) if i + 1 < len(title_idx) else int(len(values))
            if t0 < 1 or t0 >= len(values):
                continue

            h0 = None
            for cand in sorted(header_idx_set):
                if int(cand) > int(t0) and int(cand) < int(t1):
                    h0 = int(cand)
                    break
            if h0 is None:
                cand = t0 + 1
                if cand < len(values):
                    h0 = cand
            if h0 is None or h0 >= len(values):
                continue

            header_rows_idx = [int(h0)]
            if int(h0) in header_idx_set:
                cur = int(h0) + 1
                while int(cur) < int(t1) and int(cur) in header_idx_set:
                    header_rows_idx.append(int(cur))
                    cur += 1
            data_start = int(header_rows_idx[-1]) + 1

            title = ""
            try:
                title = str((values[t0] or [""])[0] or "").strip()
            except Exception:
                title = ""
            title = normalize_title(title)
            title_plain = strip_leading_emoji(title or "未命名分段") or "未命名分段"

            headers_raw: list[list[Any]] = []
            for hi in header_rows_idx:
                headers_raw.append(trim_row([str(x) for x in (values[int(hi)] or [])]))
            rows: list[list[Any]] = []
            for rr in values[int(data_start) : t1]:
                if not isinstance(rr, list):
                    continue
                row_trim = trim_row(list(rr))
                if not row_trim:
                    continue
                rows.append(row_trim)

            n_sec_cols = max(max((len(h) for h in headers_raw), default=0), max((len(r) for r in rows), default=0), 1)
            headers2 = [h[:n_sec_cols] + [""] * max(0, int(n_sec_cols) - len(h)) for h in headers_raw]
            rows2 = [r[:n_sec_cols] + [""] * max(0, int(n_sec_cols) - len(r)) for r in rows]
            headers2, rows2 = _drop_fully_empty_columns(headers2, rows2)
            headers2, rows2 = _polymarket_drop_columns_by_header(headers2, rows2, drop_names=drop_names)
            header_last = list(headers2[-1] if headers2 else [])

            sections.append(
                {
                    "title_plain": title_plain,
                    "headers": headers2,
                    "header": header_last,
                    "rows": rows2,
                }
            )

        # -------------------- lift exporter logs into meta --------------------
        if sections:
            idx_noise = None
            for idx, sec in enumerate(sections):
                if str(sec.get("title_plain") or "").strip() == "Polymarket统计":
                    idx_noise = int(idx)
                    break
            if idx_noise is not None:
                sec0 = sections[int(idx_noise)]
                first = ""
                try:
                    first = str((sec0.get("header") or [""])[0] or "").strip()
                except Exception:
                    first = ""
                if "生成 CSV 报告" in first and "滚动24小时" in first:
                    m = re.search(r"滚动24小时:\s*([0-9\-:\s]{10,})~\s*([0-9\-:\s]{10,})", first)
                    if m:
                        s0 = str(m.group(1)).strip()
                        s1 = str(m.group(2)).strip()
                        if s0 and s1:
                            meta_text = f"{meta_text}，窗口起止，{s0}~{s1}" if meta_text else f"窗口起止，{s0}~{s1}"
                    for rr in (sec0.get("rows") or []):
                        t = ""
                        try:
                            t = str((rr or [""])[0] or "").strip()
                        except Exception:
                            t = ""
                        if "已跳过" in t and "API" in t:
                            meta_text = f"{meta_text}，API排行，关闭" if meta_text else "API排行，关闭"
                            break
                    sections.pop(int(idx_noise))

        # -------------------- drop noisy/low-value sections --------------------
        drop_enabled = (os.environ.get("SHEETS_POLYMARKET_DROP_STANDALONE_SECTIONS", "1") or "1").strip() != "0"
        if drop_enabled:
            drop_set = {
                "套利信号 Top 15",
                "订单簿失衡 Top 15",
                "套利利润分布",
                "高频套利市场 (10次以上)",
                "高频套利市场（10次以上）",
                "信号密集时段 (5分钟内20+信号)",
                "信号密集时段（5分钟内20+信号）",
                "市场重复出现率 (跨信号类型)",
                "市场重复出现率（跨信号类型）",
            }
            sections = [s for s in sections if str(s.get("title_plain") or "").strip() not in drop_set]

        # -------------------- partition to 3 tabs --------------------
        # 用户交互口径：Top15 子表默认只保留“综合热门市场 Top 15”，其余 3 组（大额/新市场/聪明钱）
        # 会占用大量空间且阅读价值低（可通过 env 反向开启全量）。
        top15_hot_name = "综合热门市场 Top 15"
        top15_other_names = {"大额交易 Top 15", "新市场 Top 15", "聪明钱 Top 15"}
        top15_hot_only = (os.environ.get("SHEETS_POLYMARKET_TOP15_HOT_ONLY", "1") or "1").strip() != "0"
        if top15_hot_only:
            # 彻底删除 3 组：不在 Top15 表展示，也不回收进其他子表（避免“删了又跑到别处”）。
            sections = [s for s in sections if str(s.get("title_plain") or "").strip() not in top15_other_names]
            top15_set = {top15_hot_name}
        else:
            top15_set = {top15_hot_name} | set(top15_other_names)
        timeslot_set = {"信号频率趋势 (环比)", "时段-类型分布", "活跃时段分布"}
        category_set = {"市场类别分布", "聪明钱偏好类别"}

        sec_top15 = [s for s in sections if str(s.get("title_plain") or "").strip() in top15_set]
        sec_timeslot = [s for s in sections if str(s.get("title_plain") or "").strip() in timeslot_set]
        sec_category = [s for s in sections if str(s.get("title_plain") or "").strip() in category_set]

        used = top15_set | timeslot_set | category_set
        sec_other = [s for s in sections if str(s.get("title_plain") or "").strip() not in used]
        # 其他分段不丢：默认并入“类别偏好”子表尾部（更像“其他统计”）
        sec_category_all = sec_category + sec_other

        tab_top15 = _env_text("SHEETS_TAB_POLYMARKET_TOP15", "PolymarketTop15")
        tab_timeslot = _env_text("SHEETS_TAB_POLYMARKET_TIMESLOT", "Polymarket时段分布")
        tab_category = _env_text("SHEETS_TAB_POLYMARKET_CATEGORY", "Polymarket类别偏好")

        def build_values(secs: list[dict[str, Any]], *, tag: str) -> tuple[list[list[Any]], list[int], list[int]]:
            out: list[list[Any]] = [[f"{meta_text}，子表，{tag}" if meta_text else f"子表，{tag}"]]
            title_rows: list[int] = []
            header_rows: list[int] = []
            r1 = 2  # 1-based
            for sec in secs:
                title_plain = str(sec.get("title_plain") or "").strip() or "-"
                title_rows.append(int(r1))
                out.append([title_plain])
                r1 += 1
                headers = sec.get("headers")
                if not isinstance(headers, list) or not headers:
                    headers = [list(sec.get("header") or [])]
                for hr in headers:
                    header_rows.append(int(r1))
                    out.append(list(hr or []))
                    r1 += 1
                for rr in (sec.get("rows") or []):
                    out.append(list(rr or []))
                    r1 += 1
            n_cols = max((len(r) for r in out if isinstance(r, list)), default=1)
            n_cols = max(int(n_cols), 1)
            for r in out:
                if len(r) < int(n_cols):
                    r.extend([""] * (int(n_cols) - len(r)))
            return out, title_rows, header_rows

        def write_one(*, title: str, secs: list[dict[str, Any]], tag: str) -> dict[str, Any]:
            self.ensure_sheet(title=title)
            self._refresh_sheet_map()
            sh_id = self._sheet_id_by_title.get(title)
            if sh_id is None:
                self._refresh_sheet_map()
                sh_id = self._sheet_id_by_title.get(title)
            if sh_id is None:
                raise RuntimeError(f"missing_sheet:{title}")
            try:
                self._exec(
                    self._sheets.spreadsheets().batchUpdate(
                        spreadsheetId=self._spreadsheet_id,
                        body={"requests": [{"unmergeCells": {"range": {"sheetId": int(sh_id)}}}]},
                    ),
                    is_write=True,
                )
            except Exception:
                pass
            vals, trows, hrows = build_values(secs, tag=tag)
            if not secs:
                vals = [[f"{meta_text}，子表，{tag}，无数据" if meta_text else f"子表，{tag}，无数据"]]
                trows, hrows = [], []
            return self._write_polymarket_stats_tab_report(
                tab_title=title,
                sh_id=int(sh_id),
                values=vals,
                panel_title_rows=trows,
                panel_header_rows=hrows,
            )

        res = {
            "top15": write_one(title=tab_top15, secs=sec_top15, tag="Top15"),
            "timeslot": write_one(title=tab_timeslot, secs=sec_timeslot, tag="时段分布"),
            "category": write_one(title=tab_category, secs=sec_category_all, tag="类别偏好"),
        }

        # 隐藏原 tab（避免用户看到“未拆分的旧面板”）
        try:
            self._set_sheet_hidden(tab_title, hidden=True)
        except Exception:
            pass
        return {"ok": True, "op": "split", "from": tab_title, "tabs": res}

    def write_symbol_txt_tab(self, *, tab_title: str, text: str) -> dict[str, Any]:
        raise RuntimeError("币种查询子表已升级为真表格：请改用 write_symbol_query_tab(tab_title=..., sheet=...)")

    # ==================== dashboard variants ====================
    def _render_dashboard_to_sheet(
        self,
        payload: dict[str, Any],
        *,
        sheet_title: str,
        y: int,
        col_l: str,
        col_r: str,
        merge_info_row: bool = True,
    ) -> None:
        """
        与 `_render_dashboard` 同口径渲染，但写入到指定 sheet（用于“看板变体 tab”）。
        说明：
        - 若 columns 存在 `字段@周期`：渲染 2 行表头（字段组 + 周期），并按“周期列”灰白交替
        - 若 columns 不含 `@`：渲染 1 行表头（单行列名）；若存在“周期”列则按“周期行”灰白交替
        - 源信息行默认整行合并；当 sheet 需要冻结列时必须关闭（Sheets 禁止跨冻结列边界 merge）
        - 该函数只负责渲染，不负责 slot/meta
        """
        col_l_idx = _col_to_index(col_l)
        col_r_idx = _col_to_index(col_r)
        width = col_r_idx - col_l_idx + 1
        if width <= 0:
            raise RuntimeError("invalid_dashboard_col_range")

        header = payload.get("header") or {}
        hint = payload.get("hint") or {}
        params = payload.get("params") or {}
        table = payload.get("table") or {}
        columns = table.get("columns") or []
        rows = table.get("rows") or []
        has_period_suffix = any("@" in str(c) for c in columns if c is not None)
        header_rows = 2 if has_period_suffix else 1

        title = str(header.get("title") or "")
        update_time = str(header.get("update_time") or "-").strip() or "-"
        sort_desc = str(header.get("sort_desc") or "-").strip() or "-"
        hint_text = str(hint.get("text") or "-").strip() or "-"
        last_update = str(params.get("last_update") or "-").strip() or "-"

        info_line = " ".join(
            [
                f"📊 {title or '-'}",
                f"⏰ 更新 {update_time}",
                f"📊 排序 {sort_desc}",
                f"💡 {hint_text}",
                f"⏰ 最后更新 {last_update}",
            ]
        )

        def pad_row(first: str) -> list[str]:
            return [first] + [""] * (width - 1)

        value_rows: list[tuple[str, list[list[str]]]] = []
        value_rows.append((f"{sheet_title}!{col_l}{y}:{col_r}{y}", [pad_row(info_line)]))

        chunks = [columns[i : i + width] for i in range(0, len(columns), width)] if columns else [[]]

        table_y = y + 1
        for chunk_cols in chunks:
            if has_period_suffix:
                group_row = [_parse_field_group(str(c)) for c in chunk_cols]
                period_row = [_parse_period_suffix(str(c)) for c in chunk_cols]
                group_row = group_row + [""] * (width - len(group_row))
                period_row = period_row + [""] * (width - len(period_row))
                value_rows.append((f"{sheet_title}!{col_l}{table_y}:{col_r}{table_y}", [group_row]))
                value_rows.append((f"{sheet_title}!{col_l}{table_y + 1}:{col_r}{table_y + 1}", [period_row]))
                body_y0 = table_y + 2
            else:
                hdr_row = ["" if c is None else str(c) for c in chunk_cols]
                hdr_row = hdr_row + [""] * (width - len(hdr_row))
                value_rows.append((f"{sheet_title}!{col_l}{table_y}:{col_r}{table_y}", [hdr_row]))
                body_y0 = table_y + 1

            if rows:
                body_vals: list[list[str]] = []
                for r in rows:
                    line: list[str] = []
                    for c in chunk_cols:
                        line.append("" if r.get(c) is None else str(r.get(c)))
                    line = line + [""] * (width - len(line))
                    body_vals.append(line)
                y0 = body_y0
                y1 = body_y0 - 1 + len(body_vals)
                value_rows.append((f"{sheet_title}!{col_l}{y0}:{col_r}{y1}", body_vals))

            table_y += header_rows + len(rows)

        data = [{"range": rng, "values": vals} for rng, vals in value_rows]
        self._exec(
            self._sheets.spreadsheets()
            .values()
            .batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"valueInputOption": "RAW", "data": data},
            ),
            is_write=True,
        )

        sh_id = self._sheet_id_by_title.get(sheet_title)
        if sh_id is None:
            self._refresh_sheet_map()
            sh_id = self._sheet_id_by_title[sheet_title]

        col_l0 = col_l_idx - 1
        col_r1 = col_r_idx

        def rrange(*, r0: int, r1: int, c0: int, c1: int) -> dict[str, Any]:
            return {
                "sheetId": int(sh_id),
                "startRowIndex": int(r0),
                "endRowIndex": int(r1),
                "startColumnIndex": int(c0),
                "endColumnIndex": int(c1),
            }

        bg_hdr_info = _rgb(0.93, 0.94, 0.96)
        bg_hdr_group = _rgb(0.86, 0.90, 0.96)
        bg_hdr_period = _rgb(0.93, 0.94, 0.96)
        bg_body_even = _rgb(1.0, 1.0, 1.0)
        bg_body_odd = _rgb(0.97, 0.97, 0.97)

        requests: list[dict[str, Any]] = []

        # 源信息行：背景/字体
        requests.append(
            {
                "repeatCell": {
                    "range": rrange(r0=y - 1, r1=y, c0=col_l0, c1=col_r1),
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": bg_hdr_info,
                            "textFormat": {"bold": True},
                            "wrapStrategy": "WRAP",
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat,wrapStrategy)",
                }
            }
        )

        # 每个 chunk 的 header/body 样式
        table_y = y + 1
        for chunk_cols in chunks:
            hdr_r0 = table_y - 1
            hdr_r1 = table_y - 1 + header_rows

            # header 字体加粗
            requests.append(
                {
                    "repeatCell": {
                        "range": rrange(r0=hdr_r0, r1=hdr_r1, c0=col_l0, c1=col_r1),
                        "cell": {
                            "userEnteredFormat": {
                                "textFormat": {"bold": True},
                                "horizontalAlignment": "CENTER",
                                "verticalAlignment": "MIDDLE",
                                "wrapStrategy": "WRAP",
                            }
                        },
                        "fields": "userEnteredFormat(textFormat.bold,horizontalAlignment,verticalAlignment,wrapStrategy)",
                    }
                }
            )

            if has_period_suffix:
                period_index: dict[str, int] = {}
                period_by_col: list[str] = []
                for c in chunk_cols + [""] * (width - len(chunk_cols)):
                    suf = _parse_period_suffix(str(c))
                    if suf and suf not in period_index:
                        period_index[suf] = len(period_index)
                    period_by_col.append(suf)

                def col_bg(suf: str, *, _period_index: dict[str, int] = period_index) -> dict[str, float]:
                    if not suf:
                        return bg_body_odd
                    idx = int(_period_index.get(suf, 0))
                    return bg_body_even if idx % 2 == 0 else bg_body_odd

                body_bgs = [col_bg(suf) for suf in period_by_col]

                def add_bg_segments(*, row0: int, row1: int, bgs: list[dict[str, float]]) -> None:
                    start = 0
                    while start < width:
                        bg = bgs[start]
                        end = start + 1
                        while end < width and bgs[end] == bg:
                            end += 1
                        requests.append(
                            {
                                "repeatCell": {
                                    "range": rrange(r0=row0, r1=row1, c0=col_l0 + start, c1=col_l0 + end),
                                    "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                                    "fields": "userEnteredFormat.backgroundColor",
                                }
                            }
                        )
                        start = end

                def add_field_group_separators(*, row0: int, row1: int, _cols: list[str] = chunk_cols) -> None:
                    sep_color = _rgb(0.70, 0.70, 0.70)
                    border = {"style": "SOLID_MEDIUM", "width": 2, "color": sep_color}
                    last_group = ""
                    for idx, c in enumerate(list(_cols) + [""] * (width - len(_cols))):
                        g = _parse_field_group(str(c))
                        if not g:
                            continue
                        if last_group and g != last_group:
                            requests.append(
                                {
                                    "updateBorders": {
                                        "range": rrange(r0=row0, r1=row1, c0=col_l0 + idx, c1=col_l0 + idx + 1),
                                        "left": border,
                                    }
                                }
                            )
                        last_group = g

                # header 背景（两行）
                requests.append(
                    {
                        "repeatCell": {
                            "range": rrange(r0=table_y - 1, r1=table_y, c0=col_l0, c1=col_r1),
                            "cell": {"userEnteredFormat": {"backgroundColor": bg_hdr_group}},
                            "fields": "userEnteredFormat.backgroundColor",
                        }
                    }
                )
                requests.append(
                    {
                        "repeatCell": {
                            "range": rrange(r0=table_y, r1=table_y + 1, c0=col_l0, c1=col_r1),
                            "cell": {"userEnteredFormat": {"backgroundColor": bg_hdr_period}},
                            "fields": "userEnteredFormat.backgroundColor",
                        }
                    }
                )
                if rows:
                    body_r0 = table_y + 1
                    body_r1 = table_y + 1 + len(rows)
                    add_bg_segments(row0=body_r0, row1=body_r1, bgs=body_bgs)
                    add_field_group_separators(row0=table_y - 1, row1=body_r1)

                # 字段组表头 merge
                group_names = [_parse_field_group(str(c)) for c in chunk_cols] + [""] * (width - len(chunk_cols))
                start = 0
                while start < width:
                    g = group_names[start]
                    end = start + 1
                    while end < width and group_names[end] == g:
                        end += 1
                    if g and end - start >= 2:
                        requests.append(
                            {
                                "mergeCells": {
                                    "range": rrange(r0=table_y - 1, r1=table_y, c0=col_l0 + start, c1=col_l0 + end),
                                    "mergeType": "MERGE_ALL",
                                }
                            }
                        )
                    start = end
            else:
                # 单行表头：统一用字段组 header 背景
                requests.append(
                    {
                        "repeatCell": {
                            "range": rrange(r0=table_y - 1, r1=table_y, c0=col_l0, c1=col_r1),
                            "cell": {"userEnteredFormat": {"backgroundColor": bg_hdr_group}},
                            "fields": "userEnteredFormat.backgroundColor",
                        }
                    }
                )
                if rows:
                    # (a) 若存在“周期”列：按周期行灰白交替
                    body_r0 = table_y  # 0-based: header(1 row) ends at table_y, body begins at table_y
                    body_r1 = table_y + len(rows)
                    if "周期" in (str(c or "").strip() for c in columns):
                        p_index: dict[str, int] = {p: i for i, p in enumerate(PERIODS_DEFAULT)}
                        for r_idx, r in enumerate(rows):
                            p = "" if r.get("周期") is None else str(r.get("周期")).strip()
                            if p not in p_index:
                                p_index[p] = len(p_index)
                            bg = bg_body_even if int(p_index.get(p, 0)) % 2 == 0 else bg_body_odd
                            # 合并相同背景的连续行，减少请求数
                            if r_idx == 0:
                                seg_bg = bg
                                seg_start = 0
                            elif bg != seg_bg:
                                requests.append(
                                    {
                                        "repeatCell": {
                                            "range": rrange(
                                                r0=body_r0 + seg_start,
                                                r1=body_r0 + r_idx,
                                                c0=col_l0,
                                                c1=col_r1,
                                            ),
                                            "cell": {"userEnteredFormat": {"backgroundColor": seg_bg}},
                                            "fields": "userEnteredFormat.backgroundColor",
                                        }
                                    }
                                )
                                seg_bg = bg
                                seg_start = r_idx
                        # last segment
                        requests.append(
                            {
                                "repeatCell": {
                                    "range": rrange(
                                        r0=body_r0 + seg_start,
                                        r1=body_r0 + len(rows),
                                        c0=col_l0,
                                        c1=col_r1,
                                    ),
                                    "cell": {"userEnteredFormat": {"backgroundColor": seg_bg}},
                                    "fields": "userEnteredFormat.backgroundColor",
                                }
                            }
                        )
                    else:
                        # (b) 若表头包含周期列（1m..1w）：按周期列灰白交替（字段纵向+周期横向）
                        # 只对当前 chunk 里的周期列着色；其它列保持默认背景。
                        period_cols = {p: i for i, p in enumerate(PERIODS_DEFAULT)}
                        for idx, c in enumerate(list(chunk_cols) + [""] * (width - len(chunk_cols))):
                            name = str(c or "").strip()
                            if name not in period_cols:
                                continue
                            bg = bg_body_even if int(period_cols[name]) % 2 == 0 else bg_body_odd
                            requests.append(
                                {
                                    "repeatCell": {
                                        "range": rrange(
                                            r0=body_r0,
                                            r1=body_r1,
                                            c0=col_l0 + idx,
                                            c1=col_l0 + idx + 1,
                                        ),
                                        "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                                        "fields": "userEnteredFormat.backgroundColor",
                                    }
                                }
                            )

            table_y += header_rows + len(rows)

        if merge_info_row:
            # info 行合并（整行）
            requests.append(
                {
                    "mergeCells": {
                        "range": {
                            "sheetId": int(sh_id),
                            "startRowIndex": y - 1,
                            "endRowIndex": y,
                            "startColumnIndex": col_l_idx - 1,
                            "endColumnIndex": col_r_idx,
                        },
                        "mergeType": "MERGE_ALL",
                    }
                }
            )

        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": requests},
            ),
            is_write=True,
        )

    def write_dashboard_variants(self, *, payloads: list[dict[str, Any]], col_l: str, min_col_r: str) -> dict[str, Any]:
        """
        生成“单面板高密度”看板变体（各自独立 tab，便于对比后择优）：
        - 方案1：单元格内多周期（最窄，0 交互）
        - 方案2：紧凑 + 原始展开（同一 tab 内上下两段；原始段浅灰）
        - 方案3：纵向多周期（真表格，可排序/筛选，0 交互但更长）
        - 方案4：纵向多周期 + 合并币种单元格（每个币种 7 行周期，币种列纵向 merge）
        - 方案5：字段纵向 + 周期横向（宽度稳定，适合冻结）
        """
        variants = [
            ("看板_方案1_单元格多周期", "v1"),
            ("看板_方案2_紧凑+详情", "v2"),
            ("看板_方案3_纵向多周期", "v3"),
            ("看板_方案4_纵向合并币种", "v4"),
            ("看板_方案5_字段纵向周期横向", "v5"),
        ]

        # 允许只生成指定方案，避免写入配额爆炸
        # - SHEETS_DASHBOARD_VARIANTS=1,2,4 或 v1,v2,v4
        sel_raw = (os.environ.get("SHEETS_DASHBOARD_VARIANTS", "") or "").strip()
        if sel_raw:
            want: set[str] = set()
            for it in sel_raw.split(","):
                s = it.strip().lower()
                if not s:
                    continue
                if s in {"1", "2", "3", "4", "5"}:
                    want.add(f"v{s}")
                elif s.startswith("v") and s[1:] in {"1", "2", "3", "4", "5"}:
                    want.add(f"v{s[1:]}")
            if want:
                variants = [(t, m) for (t, m) in variants if m in want]

        results: dict[str, Any] = {"ok": True, "variants": []}
        for title, mode in variants:
            # 变体 tab 用更窄的 col_r（按实际列数计算），但不小于 min_col_r
            max_cols = 1
            transformed: list[dict[str, Any]] = []
            for p in payloads:
                table = p.get("table") or {}
                cols = table.get("columns") or []
                rows = table.get("rows") or []
                if not isinstance(cols, list) or not isinstance(rows, list):
                    transformed.append(p)
                    continue

                cols_s = [str(c) for c in cols if c is not None]
                if mode == "v1":
                    vt: VariantTable = compact_cell_multiperiod(columns=cols_s, rows=rows)
                    np = dict(p)
                    np["table"] = {"columns": vt.columns, "rows": vt.rows}
                    transformed.append(np)
                    max_cols = max(max_cols, len(vt.columns))
                elif mode in {"v3", "v4"}:
                    vt = vertical_multiperiod(columns=cols_s, rows=rows)
                    np = dict(p)
                    np["table"] = {"columns": vt.columns, "rows": vt.rows}
                    transformed.append(np)
                    max_cols = max(max_cols, len(vt.columns))
                elif mode == "v5":
                    vt = field_rows_period_columns(columns=cols_s, rows=rows)
                    np = dict(p)
                    np["table"] = {"columns": vt.columns, "rows": vt.rows}
                    transformed.append(np)
                    max_cols = max(max_cols, len(vt.columns))
                else:
                    # v2：保留原始表（第二段），紧凑表（第一段）
                    vt = compact_cell_multiperiod(columns=cols_s, rows=rows)
                    np = dict(p)
                    np["table"] = {"columns": vt.columns, "rows": vt.rows}
                    # 原始表放到 params（只用于本次渲染，不落事实表）
                    prm = dict(np.get("params") or {}) if isinstance(np.get("params"), dict) else {}
                    prm["_variant_raw_table"] = {"columns": cols_s, "rows": rows}
                    np["params"] = prm
                    transformed.append(np)
                    max_cols = max(max_cols, len(vt.columns), len(cols_s))

            col_r = self.compute_col_r(col_l=col_l, needed_cols=max_cols, min_col_r=min_col_r)
            frozen_cols = 2 if mode in {"v3", "v4", "v5"} else 0
            self.reset_sheet_display(
                title=title,
                col_l=col_l,
                col_r=col_r,
                compact=True,
                frozen_row_count=1 if mode == "v5" else 0,
                frozen_column_count=frozen_cols,
            )

            # v5：表头完全一致（币种/字段/7周期），只写一次全局表头并冻结，不在每张卡里重复写表头。
            if mode == "v5":
                self._write_v5_field_rows_period_columns_sheet(
                    payloads=transformed,
                    sheet_title=title,
                    col_l=col_l,
                    col_r=col_r,
                    export_ts_utc=_now_utc8_iso(),
                )
                results["variants"].append({"sheet": title, "mode": mode, "col_r": col_r, "cards": len(transformed)})
                continue

            y = 1
            for p in transformed:
                # v2：先渲染紧凑表，再渲染原始展开表（浅灰标题）
                if mode == "v2":
                    raw_tbl = None
                    prm = p.get("params") or {}
                    if isinstance(prm, dict):
                        raw_tbl = prm.get("_variant_raw_table")
                    height = self._calc_dashboard_height(p, col_l=col_l, col_r=col_r)
                    self._ensure_grid_size(title, min_rows=y + height, min_cols=_col_to_index(col_r))
                    self._render_dashboard_to_sheet(
                        p,
                        sheet_title=title,
                        y=y,
                        col_l=col_l,
                        col_r=col_r,
                        merge_info_row=True,
                    )
                    y += height

                    if isinstance(raw_tbl, dict):
                        # 详情段：复用同一 header，但 title 加前缀，避免误解为另一张卡
                        pp = dict(p)
                        hdr = dict(pp.get("header") or {}) if isinstance(pp.get("header"), dict) else {}
                        hdr["title"] = f"🔎 详情（原始展开） {str(hdr.get('title') or '').replace('📊', '').strip()}"
                        pp["header"] = hdr
                        pp["table"] = {
                            "columns": list(raw_tbl.get("columns") or []),
                            "rows": list(raw_tbl.get("rows") or []),
                        }
                        height2 = self._calc_dashboard_height(pp, col_l=col_l, col_r=col_r)
                        self._ensure_grid_size(title, min_rows=y + height2, min_cols=_col_to_index(col_r))
                        self._render_dashboard_to_sheet(
                            pp,
                            sheet_title=title,
                            y=y,
                            col_l=col_l,
                            col_r=col_r,
                            merge_info_row=True,
                        )
                        y += height2
                    continue

                height = self._calc_dashboard_height(p, col_l=col_l, col_r=col_r)
                self._ensure_grid_size(title, min_rows=y + height, min_cols=_col_to_index(col_r))
                self._render_dashboard_to_sheet(
                    p,
                    sheet_title=title,
                    y=y,
                    col_l=col_l,
                    col_r=col_r,
                    merge_info_row=mode not in {"v3", "v4", "v5"},
                )

                # v4：对“纵向多周期表”的币种列做纵向合并（每个币种通常对应 7 行周期）
                if mode in {"v4", "v5"}:
                    try:
                        table = p.get("table") or {}
                        cols = table.get("columns") or []
                        rows = table.get("rows") or []
                        if isinstance(cols, list) and isinstance(rows, list) and cols:
                            sym_col = str(cols[0] or "").strip() or "币种"
                            header_rows = 2 if any("@" in str(c) for c in cols if c is not None) else 1
                            # body 第 1 行（1-based）：y(info) + header_rows
                            body_start_row_1 = int(y) + 1 + int(header_rows)
                            self._merge_symbol_column_groups_on_sheet(
                                sheet_title=title,
                                col_l=col_l,
                                sym_col=sym_col,
                                body_start_row_1=body_start_row_1,
                                body_rows=rows,
                            )
                    except Exception:
                        pass

                y += height

            results["variants"].append({"sheet": title, "mode": mode, "col_r": col_r, "cards": len(transformed)})

        return results

    def write_dashboard_v5_main(self, *, payloads: list[dict[str, Any]], col_l: str, col_r: str) -> dict[str, Any]:
        """
        将“方案5（字段纵向 + 周期横向）”作为主看板写入到 `SHEETS_TAB_DASHBOARD`（默认：看板）。

        特性：
        - 顶部目录区（多行）：点击跳转到各卡片
        - 全局表头只写 1 次：`卡片 | 币种 | 字段 | 1m..1w`，并冻结（目录 + 表头；冻结列 A..C）
        - 每张卡仅写：1 行源信息 + 明细 rows（不重复表头）
        - 币种列纵向合并（同币种连续行合并）
        - 美化：周期列灰白交替 + 周期列右对齐 + 币种行组双色交替（仅作用于 A/B 列）
        """
        self.ensure_schema()
        hard_reset = (os.environ.get("SHEETS_DASHBOARD_V5_HARD_RESET", "0") or "0").strip() == "1"

        # v5 主表固定列：卡片/币种/字段/7周期
        required_cols = 10
        try:
            col_l_idx = _col_to_index(col_l)
            col_r_idx = _col_to_index(col_r)
            width = int(col_r_idx) - int(col_l_idx) + 1
        except Exception:
            width = 0
        if width > 0 and width < required_cols:
            try:
                col_r = _index_to_col(int(col_l_idx) + int(required_cols) - 1)
            except Exception:
                pass

        # 记录上次使用区域，用于“清尾巴”（避免残留）
        meta = self._meta_get()
        try:
            prev_used_rows = int(str(meta.get("dashboard_v5_used_rows") or "0").strip() or "0")
        except Exception:
            prev_used_rows = 0
        try:
            prev_used_cols = int(str(meta.get("dashboard_v5_used_cols") or "0").strip() or "0")
        except Exception:
            prev_used_cols = 0

        frozen_cols = _dashboard_v5_frozen_cols()
        export_ts = _now_utc8_iso()

        if hard_reset:
            # 破坏性重绘（会闪烁）：用于“样式大改/历史残留严重”场景
            self.reset_sheet_display(
                title=self._tab_dashboard,
                col_l=col_l,
                col_r=col_r,
                compact=True,
                frozen_row_count=1,
                frozen_column_count=frozen_cols,
            )
        else:
            # 无感刷新：不做 values.clear，全程覆盖写 + 清尾巴，避免整页“先消失再出现”
            self._refresh_sheet_map()
            sh_id = self._sheet_id_by_title.get(self._tab_dashboard)
            if sh_id is None:
                self._refresh_sheet_map()
                sh_id = self._sheet_id_by_title.get(self._tab_dashboard)
            if sh_id is None:
                raise RuntimeError("missing_dashboard_sheet")

            cur_rows, cur_cols = self._grid_by_title.get(self._tab_dashboard, (0, 0))
            # v5 主看板是“完全托管展示面”：允许裁剪 row/col。
            # 这里避免每轮扩到 2000 行/BS 列导致空白网格复活；只按“上次使用区域”作为容量基线，
            # 实际写入需要的更大尺寸会在 _write_v5_field_rows_period_columns_sheet 内部按需扩容。
            want_rows = max(int(cur_rows or 0), int(prev_used_rows or 0), 50)
            want_cols = max(int(cur_cols or 0), int(prev_used_cols or 0), int(required_cols))
            unmerge_end_rows = max(int(prev_used_rows or 0), int(want_rows))
            unmerge_end_cols = max(int(cur_cols or 0), int(want_cols))

            self._exec(
                self._sheets.spreadsheets().batchUpdate(
                    spreadsheetId=self._spreadsheet_id,
                    body={
                        "requests": [
                            {
                                "unmergeCells": {
                                    "range": {
                                        "sheetId": int(sh_id),
                                        "startRowIndex": 0,
                                        "endRowIndex": int(unmerge_end_rows),
                                        "startColumnIndex": 0,
                                        "endColumnIndex": int(unmerge_end_cols),
                                    }
                                }
                            },
                            {
                                "updateSheetProperties": {
                                    "properties": {
                                        "sheetId": int(sh_id),
                                    "gridProperties": {
                                        "rowCount": int(want_rows),
                                        "columnCount": int(want_cols),
                                        "frozenRowCount": 1,
                                        "frozenColumnCount": int(frozen_cols),
                                    },
                                },
                                "fields": "gridProperties.rowCount,gridProperties.columnCount,gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
                            }
                            },
                        ]
                    },
                ),
                is_write=True,
            )
            self._refresh_sheet_map()

        used_end_row_1, used_cols = self._write_v5_field_rows_period_columns_sheet(
            payloads=payloads,
            sheet_title=self._tab_dashboard,
            col_l=col_l,
            col_r=col_r,
            export_ts_utc=export_ts,
            clear_tail_rows_to=prev_used_rows,
        )

        # 清尾巴（值）：上一轮比本轮更长时，清掉尾部旧内容
        if prev_used_rows > int(used_end_row_1):
            y0 = int(used_end_row_1) + 1
            y1 = int(prev_used_rows)
            try:
                self._exec(
                    self._sheets.spreadsheets()
                    .values()
                    .clear(
                        spreadsheetId=self._spreadsheet_id,
                        range=f"{self._tab_dashboard}!{col_l}{y0}:{col_r}{y1}",
                    ),
                    is_write=True,
                )
            except Exception:
                pass

        # 记录本轮使用区域（用于下轮“清尾巴”）
        # v5 主看板：裁剪网格到“实际使用区域”，避免底部/右侧残留大量空白网格。
        try:
            banner_raw = (os.environ.get("SHEETS_DASHBOARD_BANNER_TEXT", "") or "").strip()
            if not banner_raw:
                banner_raw = (os.environ.get("SHEETS_TOP_BANNER_TEXT", "") or "").strip()
            banner_rows = 1 if banner_raw else 0
            frozen_rows = int(banner_rows) + 2  # 目录 + 表头 + (可选 banner)
            self._set_sheet_grid_properties(
                self._tab_dashboard,
                row_count=int(used_end_row_1),
                col_count=int(used_cols),
                frozen_row_count=int(frozen_rows),
                frozen_column_count=int(frozen_cols),
            )
        except Exception:
            pass

        try:
            self._meta_set({"dashboard_v5_used_rows": str(int(used_end_row_1)), "dashboard_v5_used_cols": str(int(used_cols))})
        except Exception:
            pass

        data_res: dict[str, Any] | None = None
        hist_res: dict[str, Any] | None = None
        try:
            data_res = self.write_dashboard_v5_data_tab(payloads=payloads)
        except Exception as exc:
            data_res = {"ok": False, "error": f"{type(exc).__name__}:{exc}"}
        try:
            hist_res = self.append_dashboard_v5_history_tab(payloads=payloads)
        except Exception as exc:
            hist_res = {"ok": False, "error": f"{type(exc).__name__}:{exc}"}
        meta_res: dict[str, Any] | None = None
        try:
            meta_res = self.write_dashboard_v5_meta_tab(payloads=payloads)
        except Exception as exc:
            meta_res = {"ok": False, "error": f"{type(exc).__name__}:{exc}"}

        return {
            "ok": True,
            "sheet": self._tab_dashboard,
            "mode": "v5",
            "cards": len(payloads),
            "col_l": col_l,
            "col_r": col_r,
            "used_rows": int(used_end_row_1),
            "hard_reset": bool(hard_reset),
            "data_tab": data_res,
            "history": hist_res,
            "meta_tab": meta_res,
        }

    def write_dashboard_v5_meta_tab(self, *, payloads: list[dict[str, Any]]) -> dict[str, Any]:
        """
        写入“看板元信息层”（可隐藏 tab）：
        - 每张卡一行：title / update_time / sort_desc / hint / last_update
        - 用途：保留完整元信息，但主看板只展示卡片标题（避免噪声）
        """
        enabled = (os.environ.get("SHEETS_DASHBOARD_V5_META_ENABLED", "1") or "1").strip() != "0"
        if not enabled:
            return {"ok": True, "skipped": True, "reason": "disabled"}

        title = self._tab_dashboard_meta
        # 默认隐藏，但无论隐藏与否都允许写入
        self.ensure_hidden_sheet(title=title)

        headers = ["title", "update_time", "sort_desc", "hint", "last_update"]
        values: list[list[Any]] = [headers]

        def one_line(s: str) -> str:
            return re.sub(r"\s+", " ", str(s or "").strip()).strip()

        for p in payloads or []:
            if not isinstance(p, dict):
                continue
            header = p.get("header") or {}
            hint = p.get("hint") or {}
            params = p.get("params") or {}

            raw_title = str((header.get("title") if isinstance(header, dict) else "") or "")
            title_display = one_line(raw_title).replace("（去重汇总）", "").strip() or "-"
            update_time = one_line(str((header.get("update_time") if isinstance(header, dict) else "") or "")) or "-"
            sort_desc = one_line(str((header.get("sort_desc") if isinstance(header, dict) else "") or "")) or "-"
            hint_text = one_line(str((hint.get("text") if isinstance(hint, dict) else "") or "")) or "-"
            last_update = one_line(str((params.get("last_update") if isinstance(params, dict) else "") or "")) or "-"

            values.append([title_display, update_time, sort_desc, hint_text, last_update])

        n_rows = int(len(values))
        n_cols = int(len(headers))
        col_r = _index_to_col(n_cols)
        self._ensure_grid_size(title, min_rows=n_rows, min_cols=n_cols)
        self._exec(
            self._sheets.spreadsheets()
            .values()
            .update(
                spreadsheetId=self._spreadsheet_id,
                range=f"{title}!A1:{col_r}{n_rows}",
                valueInputOption="RAW",
                body={"values": values},
            ),
            is_write=True,
        )
        try:
            self._set_sheet_grid_properties(title, row_count=n_rows, col_count=n_cols, frozen_row_count=1)
        except Exception:
            pass
        # 表头规范：上下左右居中 + 加粗（只作用于 header 行）
        try:
            sh_id = self._sheet_id_by_title.get(title)
            if sh_id is None:
                self._refresh_sheet_map()
                sh_id = self._sheet_id_by_title.get(title)
            if sh_id is not None:
                req = self._sheets.spreadsheets().batchUpdate(
                    spreadsheetId=self._spreadsheet_id,
                    body={
                        "requests": [
                            {
                                "repeatCell": {
                                    "range": {
                                        "sheetId": int(sh_id),
                                        "startRowIndex": 0,
                                        "endRowIndex": 1,
                                        "startColumnIndex": 0,
                                        "endColumnIndex": int(n_cols),
                                    },
                                    "cell": {
                                        "userEnteredFormat": {
                                            "backgroundColor": _rgb(0.93, 0.94, 0.96),
                                            "textFormat": {"bold": True},
                                            "horizontalAlignment": "CENTER",
                                            "verticalAlignment": "MIDDLE",
                                            "wrapStrategy": "CLIP",
                                        }
                                    },
                                    "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,wrapStrategy)",
                                }
                            }
                        ]
                    },
                )
                # repeatCell 是幂等写：允许对 5xx 做小次数重试，避免偶发 502 导致“表头样式不落地”
                for attempt in range(0, 4):
                    try:
                        self._exec(req, is_write=True)
                        break
                    except Exception as exc:
                        status = int(getattr(getattr(exc, "resp", None), "status", 0) or 0)
                        if status and (500 <= status <= 599) and attempt < 3:
                            time.sleep(min(1.0 * (2**attempt), 6.0))
                            continue
                        break
        except Exception:
            pass

        return {"ok": True, "sheet": title, "rows": n_rows - 1}

    def _iter_dashboard_v5_long_rows(
        self, *, payloads: list[dict[str, Any]], export_ts_utc: str, periods: list[str]
    ) -> Iterable[list[Any]]:
        """
        将 v5 看板的“宽表”展开为长表（每行一个 (card,symbol,field,period)）。
        用途：数据层/历史层（图表/透视/统计友好）。
        """
        per = [p for p in (periods or []) if p]
        if not per:
            per = list(PERIODS_DEFAULT)

        for p in payloads or []:
            if not isinstance(p, dict):
                continue
            card_key = str(p.get("card_key") or "").strip()
            ts_utc = str(p.get("ts_utc") or "").strip()
            source_service = str(p.get("source_service") or "").strip()
            card_type = str(p.get("card_type") or "").strip()

            header = p.get("header") or {}
            params = p.get("params") or {}
            title = str((header.get("title") if isinstance(header, dict) else "") or "").strip()
            update_time = str((header.get("update_time") if isinstance(header, dict) else "") or "").strip()
            sort_desc = str((header.get("sort_desc") if isinstance(header, dict) else "") or "").strip()
            last_update = str((params.get("last_update") if isinstance(params, dict) else "") or "").strip()

            table = p.get("table") or {}
            cols = table.get("columns") or []
            rows = table.get("rows") or []
            if not (isinstance(cols, list) and isinstance(rows, list) and len(cols) >= 2):
                continue

            sym_key = str(cols[0] or "").strip() or "币种"
            field_key = str(cols[1] or "").strip() or "字段"

            for r in rows:
                if not isinstance(r, dict):
                    continue
                sym = str(r.get(sym_key) or "").strip()
                field = str(r.get(field_key) or "").strip()
                for period in per:
                    disp_obj = r.get(period)
                    disp = "" if disp_obj is None else str(disp_obj)
                    num = _coerce_number(disp)
                    yield [
                        export_ts_utc,
                        card_key,
                        ts_utc,
                        source_service,
                        card_type,
                        title,
                        update_time,
                        sort_desc,
                        last_update,
                        sym,
                        field,
                        str(period),
                        disp,
                        "" if num is None else num,
                    ]

    def write_dashboard_v5_data_tab(self, *, payloads: list[dict[str, Any]]) -> dict[str, Any]:
        """
        写入“看板数据层”（隐藏 tab）：
        - 结构化长表（强类型 number），用于：图表 / 透视表 / 统计查询
        - 仅覆盖写（snapshot），不保留历史
        - 通过 interval 控制频率，避免写入量翻倍导致 429
        """
        enabled = (os.environ.get("SHEETS_DASHBOARD_V5_DATA_ENABLED", "1") or "1").strip() != "0"
        if not enabled:
            return {"ok": True, "skipped": True, "reason": "disabled"}

        try:
            interval = int((os.environ.get("SHEETS_DASHBOARD_V5_DATA_INTERVAL_SECONDS", "300") or "300").strip() or "300")
        except Exception:
            interval = 300
        interval = max(int(interval), 0)

        meta = self._meta_get()
        try:
            last = int(str(meta.get("dashboard_v5_data_last_epoch") or "0").strip() or "0")
        except Exception:
            last = 0
        now = int(time.time())
        if interval > 0 and (now - last) < interval:
            return {"ok": True, "skipped": True, "reason": "interval", "interval_seconds": interval, "age_seconds": now - last}

        title = self._tab_dashboard_data
        self.ensure_hidden_sheet(title=title)

        export_ts = _now_utc_iso()
        periods = list(PERIODS_DEFAULT)
        headers = [
            "export_ts_utc",
            "card_key",
            "ts_utc",
            "source_service",
            "card_type",
            "title",
            "update_time",
            "sort_desc",
            "last_update",
            "symbol",
            "field",
            "period",
            "value_display",
            "value_num",
        ]

        body = list(self._iter_dashboard_v5_long_rows(payloads=payloads, export_ts_utc=export_ts, periods=periods))
        values: list[list[Any]] = [headers, *body]
        n_rows = int(len(values))
        n_cols = int(len(headers))
        col_r = _index_to_col(n_cols)

        # 确保网格足够大（避免 update 越界），然后覆盖写
        self._ensure_grid_size(title, min_rows=n_rows, min_cols=n_cols)
        self._exec(
            self._sheets.spreadsheets()
            .values()
            .update(
                spreadsheetId=self._spreadsheet_id,
                range=f"{title}!A1:{col_r}{n_rows}",
                valueInputOption="RAW",
                body={"values": values},
            ),
            is_write=True,
        )

        # 清尾巴：上一轮更长时清掉残留
        key_rows = "dashboard_v5_data_rows"
        key_cols = "dashboard_v5_data_cols"
        try:
            r_old = int(str(meta.get(key_rows) or "0").strip() or "0")
        except Exception:
            r_old = 0
        try:
            c_old = int(str(meta.get(key_cols) or "0").strip() or "0")
        except Exception:
            c_old = 0
        if r_old > n_rows:
            try:
                self._exec(
                    self._sheets.spreadsheets()
                    .values()
                    .clear(
                        spreadsheetId=self._spreadsheet_id,
                        range=f"{title}!A{n_rows + 1}:{_index_to_col(max(c_old, n_cols))}{r_old}",
                    ),
                    is_write=True,
                )
            except Exception:
                pass
        if c_old > n_cols:
            try:
                self._exec(
                    self._sheets.spreadsheets()
                    .values()
                    .clear(
                        spreadsheetId=self._spreadsheet_id,
                        range=f"{title}!{_index_to_col(n_cols + 1)}1:{_index_to_col(c_old)}{max(r_old, n_rows)}",
                    ),
                    is_write=True,
                )
            except Exception:
                pass

        # 版式：压缩 grid + 冻结 header
        try:
            self._set_sheet_grid_properties(title, row_count=n_rows, col_count=n_cols, frozen_row_count=1)
        except Exception:
            pass

        # header 样式（一次性即可）
        try:
            sh_id = self._sheet_id_by_title.get(title)
            if sh_id is None:
                self._refresh_sheet_map()
                sh_id = self._sheet_id_by_title.get(title)
            if sh_id is not None:
                self._exec(
                    self._sheets.spreadsheets().batchUpdate(
                        spreadsheetId=self._spreadsheet_id,
                        body={
                            "requests": [
                                {
                                    "repeatCell": {
                                        "range": {
                                            "sheetId": int(sh_id),
                                            "startRowIndex": 0,
                                            "endRowIndex": 1,
                                            "startColumnIndex": 0,
                                            "endColumnIndex": int(n_cols),
                                        },
                                        "cell": {
                                            "userEnteredFormat": {
                                                "backgroundColor": _rgb(0.93, 0.94, 0.96),
                                                "textFormat": {"bold": True},
                                                "horizontalAlignment": "CENTER",
                                                "verticalAlignment": "MIDDLE",
                                                "wrapStrategy": "CLIP",
                                            }
                                        },
                                        "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,wrapStrategy)",
                                    }
                                },
                                # value_num 列右对齐
                                {
                                    "repeatCell": {
                                        "range": {
                                            "sheetId": int(sh_id),
                                            "startRowIndex": 1,
                                            "endRowIndex": int(max(n_rows, 2)),
                                            "startColumnIndex": int(n_cols - 1),
                                            "endColumnIndex": int(n_cols),
                                        },
                                        "cell": {"userEnteredFormat": {"horizontalAlignment": "RIGHT", "wrapStrategy": "CLIP"}},
                                        "fields": "userEnteredFormat(horizontalAlignment,wrapStrategy)",
                                    }
                                },
                            ]
                        },
                    ),
                    is_write=True,
                )
        except Exception:
            pass

        try:
            self._meta_set(
                {
                    "dashboard_v5_data_last_epoch": str(now),
                    key_rows: str(n_rows),
                    key_cols: str(n_cols),
                }
            )
        except Exception:
            pass

        return {"ok": True, "sheet": title, "rows": n_rows, "cols": n_cols, "export_ts_utc": export_ts}

    def append_dashboard_v5_history_tab(self, *, payloads: list[dict[str, Any]]) -> dict[str, Any]:
        """
        写入“看板历史层”（隐藏 tab）：
        - append-only（带 retention，可选）
        - 默认关闭（避免无意写爆配额/行数）
        """
        enabled = (os.environ.get("SHEETS_DASHBOARD_V5_HISTORY_ENABLED", "0") or "0").strip() == "1"
        if not enabled:
            return {"ok": True, "skipped": True, "reason": "disabled"}

        def _split_csv(env_key: str) -> list[str]:
            raw = (os.environ.get(env_key, "") or "").strip()
            if not raw:
                return []
            return [s.strip() for s in raw.split(",") if s.strip()]

        card_types = set(_split_csv("SHEETS_DASHBOARD_V5_HISTORY_CARD_TYPES"))
        fields = set(_split_csv("SHEETS_DASHBOARD_V5_HISTORY_FIELDS"))
        periods = _split_csv("SHEETS_DASHBOARD_V5_HISTORY_PERIODS") or ["15m"]
        periods = [p for p in periods if p]
        if not periods:
            periods = ["15m"]

        try:
            max_append = int((os.environ.get("SHEETS_DASHBOARD_V5_HISTORY_MAX_APPEND_ROWS", "2000") or "2000").strip() or "2000")
        except Exception:
            max_append = 2000
        max_append = max(int(max_append), 0)

        try:
            max_rows = int((os.environ.get("SHEETS_DASHBOARD_V5_HISTORY_MAX_ROWS", "50000") or "50000").strip() or "50000")
        except Exception:
            max_rows = 50000
        max_rows = max(int(max_rows), 0)

        title = self._tab_dashboard_history
        self.ensure_hidden_sheet(title=title)

        headers = [
            "export_ts_utc",
            "card_type",
            "title",
            "update_time",
            "symbol",
            "field",
            "period",
            "value_num",
            "value_display",
        ]
        self._ensure_header_row(title, headers)
        n_cols = len(headers)
        col_r = _index_to_col(n_cols)

        export_ts = _now_utc_iso()
        rows_out: list[list[Any]] = []
        for rec in self._iter_dashboard_v5_long_rows(payloads=payloads, export_ts_utc=export_ts, periods=periods):
            # rec schema: export_ts, card_key, ts_utc, source_service, card_type, title, update_time, sort_desc, last_update, sym, field, period, disp, num
            ctype = str(rec[4] or "").strip()
            ctitle = str(rec[5] or "").strip()
            up = str(rec[6] or "").strip()
            sym = str(rec[9] or "").strip()
            fld = str(rec[10] or "").strip()
            per = str(rec[11] or "").strip()
            disp = "" if rec[12] is None else str(rec[12])
            num = rec[13]
            if num is None or num == "":
                continue
            if card_types and ctype not in card_types:
                continue
            if fields and fld not in fields:
                continue
            rows_out.append([export_ts, ctype, ctitle, up, sym, fld, per, num, disp])
            if max_append > 0 and len(rows_out) >= max_append:
                break

        if not rows_out:
            return {"ok": True, "skipped": True, "reason": "no_rows"}

        meta = self._meta_get()
        key_next = "dashboard_v5_history_next_row"
        try:
            next_row = int(str(meta.get(key_next) or "2").strip() or "2")
        except Exception:
            next_row = 2
        next_row = max(int(next_row), 2)

        # retention：超过 max_rows 时删除最老的数据行（从第 2 行开始）
        if max_rows > 0:
            cur_count = max(int(next_row) - 2, 0)
            new_count = int(cur_count) + int(len(rows_out))
            extra = int(new_count) - int(max_rows)
            if extra > 0:
                sh_id = self._sheet_id_by_title.get(title)
                if sh_id is None:
                    self._refresh_sheet_map()
                    sh_id = self._sheet_id_by_title.get(title)
                if sh_id is not None:
                    self._exec(
                        self._sheets.spreadsheets().batchUpdate(
                            spreadsheetId=self._spreadsheet_id,
                            body={
                                "requests": [
                                    {
                                        "deleteDimension": {
                                            "range": {
                                                "sheetId": int(sh_id),
                                                "dimension": "ROWS",
                                                "startIndex": 1,  # delete from row 2 (0-based)
                                                "endIndex": 1 + int(extra),
                                            }
                                        }
                                    }
                                ]
                            },
                        ),
                        is_write=True,
                    )
                    # rows shift up
                    next_row = max(int(next_row) - int(extra), 2)

        end_row = int(next_row) + int(len(rows_out)) - 1
        self._ensure_grid_size(title, min_rows=end_row, min_cols=n_cols)
        self._exec(
            self._sheets.spreadsheets()
            .values()
            .update(
                spreadsheetId=self._spreadsheet_id,
                range=f"{title}!A{next_row}:{col_r}{end_row}",
                valueInputOption="RAW",
                body={"values": rows_out},
            ),
            is_write=True,
        )
        try:
            self._set_sheet_grid_properties(title, row_count=end_row, col_count=n_cols, frozen_row_count=1)
        except Exception:
            pass

        try:
            self._meta_set({key_next: str(int(end_row) + 1)})
        except Exception:
            pass

        return {"ok": True, "sheet": title, "appended": len(rows_out), "next_row": int(end_row) + 1, "export_ts_utc": export_ts}

    def _write_v5_field_rows_period_columns_sheet(
        self,
        *,
        payloads: list[dict[str, Any]],
        sheet_title: str,
        col_l: str,
        col_r: str,
        export_ts_utc: str,
        clear_tail_rows_to: int = 0,
    ) -> tuple[int, int]:
        """
        v5 专用渲染：
        - 全局表头只写 1 次：`币种 | 字段 | 1m..1w`，并冻结 top header（frozenRowCount=1）
        - 每张卡仅写：1 行源信息 + 明细 rows（不重复表头）
        - 币种列纵向 merge（同币种连续行合并）
        """
        if not payloads:
            return 0

        sh_id = self._sheet_id_by_title.get(sheet_title)
        if sh_id is None:
            self._refresh_sheet_map()
            sh_id = self._sheet_id_by_title.get(sheet_title)
        if sh_id is None:
            return 0

        col_l_idx = _col_to_index(col_l)
        col_r_idx = _col_to_index(col_r)
        width = col_r_idx - col_l_idx + 1
        if width <= 0:
            raise RuntimeError("invalid_dashboard_col_range")

        # 取第一张卡的 columns 作为全局表头口径（v5 应该对齐）
        first_table = (payloads[0].get("table") or {}) if isinstance(payloads[0], dict) else {}
        base_columns = list(first_table.get("columns") or [])
        base_columns = ["" if c is None else str(c) for c in base_columns]
        if not base_columns:
            base_columns = ["币种", "字段", *[p for p in PERIODS_DEFAULT if p not in _hidden_periods()]]

        # 只支持 v5 的“统一表头”：至少包含 币种/字段 两列
        if len(base_columns) < 2:
            base_columns = ["币种", "字段", *[p for p in PERIODS_DEFAULT if p not in _hidden_periods()]]

        # 删除周期列（例如 1m）：只影响展示层，不改变 payload 数据源
        drop_periods = _hidden_periods()
        if drop_periods:
            period_set = set(PERIODS_DEFAULT)
            base_columns = [c for c in base_columns if not (str(c).strip() in period_set and str(c).strip() in drop_periods)]

        card_col = "卡片"
        payload_col0_name = str(base_columns[0] or "币种") if base_columns else "币种"
        payload_col1_name = str(base_columns[1] or "字段") if len(base_columns) >= 2 else "字段"
        has_payload_card_col = bool(base_columns) and base_columns[0] == card_col

        if has_payload_card_col:
            columns = list(base_columns)
            symbol_key = str(base_columns[1] or "币种") if len(base_columns) >= 2 else "币种"
        else:
            columns = [card_col, *base_columns]
            symbol_key = payload_col0_name

        # v5 看板渲染：按实际列数写入并收缩网格，避免“删除 1m 后仍留空列”
        col_r_idx_eff = int(col_l_idx) + int(max(len(columns), 1)) - 1
        col_r_eff = _index_to_col(int(col_r_idx_eff))
        width = int(max(len(columns), 1))

        # 1) values：目录 + 全局表头 + 每张卡 info/body
        def pad_row(vals: list[str]) -> list[str]:
            return (list(vals) + [""] * width)[:width]

        # 目录（单单元格，多行文本）：首格放 label + 逗号分隔条目（更紧凑）
        render_payloads: list[dict[str, Any]] = []
        for p in payloads:
            if not isinstance(p, dict):
                continue
            table = p.get("table") or {}
            if not isinstance(table, dict):
                continue
            cols = table.get("columns") or []
            cols = ["" if c is None else str(c) for c in (cols or [])]
            if cols and (len(cols) < 2 or cols[0] != payload_col0_name or cols[1] != payload_col1_name):
                continue
            render_payloads.append(p)

        # 目录行尽量不放 emoji：降低富文本链接索引/渲染复杂度（不同客户端兼容更稳）
        dir_label = "目录（点击跳转）"
        banner_raw = (os.environ.get("SHEETS_DASHBOARD_BANNER_TEXT", "") or "").strip()
        if not banner_raw:
            banner_raw = (os.environ.get("SHEETS_TOP_BANNER_TEXT", "") or "").strip()
        banner_text, banner_line_count = _format_dashboard_banner_text(str(banner_raw or ""))
        banner_rows = 1 if banner_text else 0
        # 固定为 1 行：目录文本放入单单元格（A1），避免“铺满一行超链接”挤压主表宽度
        dir_rows = 1
        dir_row_1 = int(banner_rows) + 1  # 1-based
        header_row_1 = int(banner_rows) + int(dir_rows) + 1  # 1-based
        body_start_row_1 = int(header_row_1) + 1

        data: list[dict[str, Any]] = []
        if banner_rows > 0:
            data.append(
                {
                    "range": f"{sheet_title}!{col_l}1:{col_r_eff}1",
                    "values": [pad_row([banner_text])],
                }
            )
        header_vals = pad_row(columns)
        data.append({"range": f"{sheet_title}!{col_l}{header_row_1}:{col_r_eff}{header_row_1}", "values": [header_vals]})

        y = int(body_start_row_1)  # 1-based
        merge_tasks: list[tuple[int, list[dict[str, Any]]]] = []  # (body_start_row_1, body_rows)
        max_y_used = 1
        used_end_row_1 = 1
        dir_entries: list[tuple[str, int]] = []  # (title, body_start_row_1)
        placeholder_mode = _empty_placeholder_mode()
        placeholder_char = _empty_placeholder_char() if placeholder_mode == "char" else ""
        sparkline_cells: list[tuple[int, int]] = []  # (row_1, col_1)
        period_set = set(PERIODS_DEFAULT)
        effective_periods = [p for p in PERIODS_DEFAULT if p not in drop_periods]

        # 离散信号（多/空）上色目标：必须用 (card_type, field_name) 精确限定，避免字段名复用误伤。
        direction_targets: set[tuple[str, str]] = {
            ("super_trend_ranking", "方向"),
            ("trendline_ranking", "趋势方向"),
            ("macd_ranking", "方向"),
            ("volume_ratio_ranking", "方向"),
            ("futures_flip_radar", "翻转信号"),
            ("sr_ranking", "信号"),
            ("kdj_ranking", "信号概述"),
            ("kdj_ranking", "信号"),  # 兼容历史/别名
            ("ema_ranking", "趋势"),
        }
        direction_marks: list[dict[str, Any]] = []

        for p in render_payloads:
            card_type = str(p.get("card_type") or "").strip()
            header = p.get("header") or {}
            table = p.get("table") or {}
            rows = table.get("rows") or []
            cols = table.get("columns") or []
            cols = ["" if c is None else str(c) for c in (cols or [])]

            title = str(header.get("title") or "")

            def one_line(s: str) -> str:
                # Google Sheets：值里如果含 '\n' 会强制换行并把整行撑高；这里强制压成单行。
                return re.sub(r"\s+", " ", str(s or "").strip()).strip() or "-"

            title_display = one_line(title).replace("（去重汇总）", "").strip() or "-"

            y_body = y
            dir_entries.append((title_display, int(y_body)))

            body_vals: list[list[str]] = []
            for row_idx, r in enumerate(rows or []):
                if not isinstance(r, dict):
                    continue

                # 记录“方向/信号”行的每周期值：用于后续红/绿离散上色
                try:
                    field_name = str(r.get(payload_col1_name) or "").strip()
                except Exception:
                    field_name = ""
                if card_type and field_name and (card_type, field_name) in direction_targets:
                    pv: dict[str, Any] = {}
                    for per in effective_periods:
                        pv[per] = r.get(per)
                    direction_marks.append({"row_1": int(y_body) + int(row_idx), "period_values": pv})

                line: list[str] = []
                for ci, c in enumerate(columns):
                    if c == card_col:
                        # 元信息：不再使用“分割行”（info row）；改为写入卡片合并单元格的 top-left
                        # - 只在该卡片块的第一行写入，其它行留空（merge 后以 top-left 为准）
                        line.append(title_display if row_idx == 0 else "")
                        continue
                    v = r.get(c)
                    if (str(c).strip() in period_set) and _is_no_data_cell(v):
                        if placeholder_mode == "sparkline":
                            line.append("")
                            # 1-based 坐标：col_l_idx 是 1-based
                            sparkline_cells.append((int(y_body) + int(row_idx), int(col_l_idx) + int(ci)))
                        elif placeholder_char:
                            line.append(placeholder_char)
                        else:
                            line.append("" if v is None else str(v))
                    else:
                        line.append("" if v is None else str(v))
                body_vals.append(pad_row(line))

            if body_vals:
                y1 = y_body + len(body_vals) - 1
                data.append({"range": f"{sheet_title}!{col_l}{y_body}:{col_r_eff}{y1}", "values": body_vals})
                merge_tasks.append((int(y_body), list(rows)))
                max_y_used = max(max_y_used, int(y1))
                y = int(y1) + 1
            else:
                max_y_used = max(max_y_used, int(y))
                y = int(y) + 1
            used_end_row_1 = max(int(used_end_row_1), int(y) - 1)

        used_cols = int(_col_to_index(col_r_eff))
        used_rows = max(int(used_end_row_1), int(header_row_1))
        self._ensure_grid_size(sheet_title, min_rows=int(used_rows), min_cols=int(used_cols))
        self._exec(
            self._sheets.spreadsheets()
            .values()
            .batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"valueInputOption": "RAW", "data": data},
                ),
            is_write=True,
        )

        # 纯函数占位：空值单元格用 SPARKLINE 画“反斜线”对角线
        if placeholder_mode == "sparkline" and sparkline_cells:
            try:
                formula = _sparkline_backslash_formula(locale=getattr(self, "_spreadsheet_locale", None))
                self._apply_cell_formulas(sheet_title=sheet_title, cells=sparkline_cells, formula=formula)
            except Exception:
                pass

        # 目录：写入“逗号分隔”的单单元格文本（A1）
        # - 保留“点击跳转”：通过 RichText 的 textFormatRuns 为每个条目单独绑定 link
        # - 目录区域无内容时也覆盖写，避免历史残留
        if dir_rows > 0:
            col_l0 = int(col_l_idx) - 1

            def idx_len(s: str) -> int:
                # Sheets API 的 startIndex 使用 UTF-16 code units（emoji 会占 2）。
                return _utf16_len(str(s))

            def strip_leading_emoji(s: str) -> str:
                # 仅用于“目录/元信息”行：去掉前缀图标/emoji（含不可见变体选择符/空白）
                return re.sub(r"^[^0-9A-Za-z\u4e00-\u9fff]+\s*", "", str(s or "")).strip()

            clean_label = strip_leading_emoji(dir_label)
            ts_s = re.sub(r"\s+", " ", str(export_ts_utc or "").strip())
            if not ts_s:
                ts_s = _now_utc8_iso()
            prefix = f"导出时间(UTC+8)，{ts_s}，{clean_label}" if ts_s else clean_label
            text_parts: list[str] = [prefix]
            runs: list[dict[str, Any]] = [{"startIndex": 0, "format": {}}]
            pos = int(idx_len(prefix))
            item_count = 1  # 已写入 label

            for title, row_1 in dir_entries:
                # 冻结列开启时，我们不做“整行横向 merge”（会跨冻结分割线导致 400）。
                # 目录行改为单行文本溢出显示，因此这里不插入换行，避免首行高度被撑大。
                sep = "，"
                text_parts.append(sep)
                pos += idx_len(sep)

                title_s = strip_leading_emoji(str(title or "-").strip() or "-")
                start = int(pos)
                text_parts.append(title_s)
                pos += idx_len(title_s)
                end = int(pos)

                url = (
                    f"https://docs.google.com/spreadsheets/d/{self._spreadsheet_id}/edit"
                    f"#gid={int(sh_id)}&range={col_l}{int(row_1)}"
                )
                runs.append(
                    {
                        "startIndex": int(start),
                        "format": {
                            "link": {"uri": str(url)},
                            "foregroundColor": _rgb(0.1, 0.4, 0.8),
                            "underline": True,
                        },
                    }
                )
                runs.append({"startIndex": int(end), "format": {}})
                item_count += 1

            dir_text = "".join(text_parts)
            # Sheets API: TextFormatRun.startIndex 必须 < 字符串长度；裁剪掉末尾无效的 reset run。
            text_len = idx_len(dir_text)
            while runs and int(runs[-1].get("startIndex", 0) or 0) >= int(text_len):
                runs.pop()

            # 先写入纯文本（RAW），再注入 RichText links（避免公式拼接导致链接丢失）
            grid = [[""] * width for _ in range(int(dir_rows))]
            grid[0][0] = dir_text
            dir_rng = f"{sheet_title}!{col_l}{int(dir_row_1)}:{col_r_eff}{int(dir_row_1) + int(dir_rows) - 1}"
            self._exec(
                self._sheets.spreadsheets()
                .values()
                .update(
                    spreadsheetId=self._spreadsheet_id,
                    range=dir_rng,
                    valueInputOption="RAW",
                    body={"values": grid},
                ),
                is_write=True,
            )

            try:
                self._exec(
                    self._sheets.spreadsheets().batchUpdate(
                        spreadsheetId=self._spreadsheet_id,
                        body={
                            "requests": [
                                {
                                    "updateCells": {
                                        "range": {
                                            "sheetId": int(sh_id),
                                            "startRowIndex": int(dir_row_1) - 1,
                                            "endRowIndex": int(dir_row_1),
                                            "startColumnIndex": int(col_l0),
                                            "endColumnIndex": int(col_l0 + 1),
                                        },
                                        "rows": [
                                            {
                                                "values": [
                                                    {
                                                        "userEnteredValue": {"stringValue": dir_text},
                                                        "textFormatRuns": runs,
                                                    }
                                                ]
                                            }
                                        ],
                                        "fields": "userEnteredValue,textFormatRuns",
                                    }
                                }
                            ]
                        },
                    ),
                    is_write=True,
                )
            except Exception as exc:
                print(f"⚠️ dashboard_v5.dir_links_failed {type(exc).__name__}: {exc}")

        # 2) styles：全局表头 + 周期列灰白交替 + 每张卡 info 行 + merges（合并币种列）
        col_l0 = col_l_idx - 1
        col_r1 = int(col_r_idx_eff)

        def rrange(*, r0: int, r1: int, c0: int, c1: int) -> dict[str, Any]:
            return {
                "sheetId": int(sh_id),
                "startRowIndex": int(r0),
                "endRowIndex": int(r1),
                "startColumnIndex": int(c0),
                "endColumnIndex": int(c1),
            }

        bg_hdr_info = _rgb(0.93, 0.94, 0.96)
        bg_hdr_group = _rgb(0.86, 0.90, 0.96)
        bg_body_even = _rgb(1.0, 1.0, 1.0)
        bg_body_odd = _rgb(0.97, 0.97, 0.97)
        bg_sym_a = _rgb(0.95, 0.97, 1.0)  # 币种行组背景色1（淡蓝）
        bg_sym_b = _rgb(0.98, 0.98, 0.98)  # 币种行组背景色2（淡灰）
        bg_bull = _rgb(0.776, 0.937, 0.808)  # Excel-like light green (#C6EFCE)
        bg_bear = _rgb(1.0, 0.780, 0.808)  # Excel-like light red (#FFC7CE)

        reqs: list[dict[str, Any]] = []
        # -------------------- 差量样式（只扩不重刷） --------------------
        # 目标：避免每轮对大范围做重复 repeatCell（尤其是长表），减少耗时与配额压力。
        meta = self._meta_get()
        style_version = "dashboard_v5_style_v8"
        key_style_version = "dashboard_v5_style_version"
        key_styled_rows = "dashboard_v5_styled_rows"
        key_dir_rows = "dashboard_v5_dir_rows"
        key_banner_rows = "dashboard_v5_banner_rows"
        key_style_placeholder = "dashboard_v5_style_placeholder"
        placeholder_mode2 = _empty_placeholder_mode()
        placeholder_style = (
            f"char:{_empty_placeholder_char()}"
            if placeholder_mode2 == "char"
            else ("sparkline" if placeholder_mode2 == "sparkline" else "off")
        )
        try:
            prev_styled_rows = int(str(meta.get(key_styled_rows) or "0").strip() or "0")
        except Exception:
            prev_styled_rows = 0
        try:
            prev_dir_rows = int(str(meta.get(key_dir_rows) or "0").strip() or "0")
        except Exception:
            prev_dir_rows = 0
        try:
            prev_banner_rows = int(str(meta.get(key_banner_rows) or "0").strip() or "0")
        except Exception:
            prev_banner_rows = 0

        full_style = (
            (meta.get(key_style_version) or "") != style_version
            or (meta.get(key_style_placeholder) or "") != placeholder_style
            or int(prev_dir_rows) != int(dir_rows)
            or int(prev_banner_rows) != int(banner_rows)
            or prev_styled_rows <= 0
        )

        # 清除旧 conditional formatting（避免历史规则残留/占位符变更后不生效）
        if full_style:
            try:
                ss = self._exec(
                    self._sheets.spreadsheets().get(
                        spreadsheetId=self._spreadsheet_id,
                        fields="sheets(properties(sheetId,title),conditionalFormats)",
                    ),
                    is_write=False,
                )
                cond_cnt = 0
                for sh in ss.get("sheets", []):
                    props = sh.get("properties") or {}
                    if int(props.get("sheetId") or 0) != int(sh_id):
                        continue
                    cond = sh.get("conditionalFormats") or []
                    cond_cnt = len(cond)
                    break
                if cond_cnt > 0:
                    reqs_del = [
                        {"deleteConditionalFormatRule": {"sheetId": int(sh_id), "index": 0}} for _ in range(cond_cnt)
                    ]
                    self._exec(
                        self._sheets.spreadsheets().batchUpdate(
                            spreadsheetId=self._spreadsheet_id,
                            body={"requests": reqs_del},
                        ),
                        is_write=True,
                    )
            except Exception:
                pass

        # freeze rows：目录 + 1 行表头；列：A..C（卡片/币种/字段）
        try:
            self._set_sheet_grid_properties(
                sheet_title,
                frozen_row_count=int(banner_rows) + int(dir_rows) + 1,
                frozen_column_count=_dashboard_v5_frozen_cols(),
            )
        except Exception:
            pass

        # 删除周期列后：收缩列数，避免旧列残留（例如旧版 J 列仍残留 1w）
        reqs.append(
            {
                "updateSheetProperties": {
                    "properties": {"sheetId": int(sh_id), "gridProperties": {"columnCount": int(col_r_idx_eff)}},
                    "fields": "gridProperties.columnCount",
                }
            }
        )

        # 全部展开：解除用户此前手工隐藏的列（例如之前隐藏过 1m）
        reqs.append(
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": int(sh_id),
                        "dimension": "COLUMNS",
                        "startIndex": int(col_l0),
                        "endIndex": int(col_r1),
                    },
                    "properties": {"hiddenByUser": False},
                    "fields": "hiddenByUser",
                }
            }
        )

        # 周期列不再用 hiddenByUser 折叠：已在 values 阶段直接删除列（见上方 drop_periods）。

        # 结构变更时：先清掉“受控范围”的旧格式，避免残留（例如旧版 info 行深色背景）
        if full_style and int(used_end_row_1) > 0:
            reqs.append(
                {
                    "repeatCell": {
                        "range": rrange(r0=0, r1=int(used_end_row_1), c0=col_l0, c1=col_r1),
                        "cell": {"userEnteredFormat": {}},
                        "fields": "userEnteredFormat",
                    }
                }
            )

        # banner 栏（可选）：广告位/赞助商信息
        if banner_rows > 0:
            try:
                banner_lines = int(banner_line_count or 1)
            except Exception:
                banner_lines = 1
            banner_lines = max(1, min(int(banner_lines), 6))
            banner_row_px = int(21 * int(banner_lines))

            reqs.append(
                {
                    "repeatCell": {
                        "range": rrange(r0=0, r1=1, c0=col_l0, c1=col_r1),
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": _rgb(1.0, 0.97, 0.86),
                                "textFormat": {"bold": True},
                                "horizontalAlignment": "LEFT",
                                "verticalAlignment": "MIDDLE",
                                "wrapStrategy": "OVERFLOW_CELL",
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,wrapStrategy)",
                    }
                }
            )
            reqs.append(
                {
                    "updateDimensionProperties": {
                        "range": {"sheetId": int(sh_id), "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
                        "properties": {"pixelSize": int(banner_row_px)},
                        "fields": "pixelSize",
                    }
                }
            )
            # banner 行：保持冻结列（A..C）的前提下，Sheets 不允许真 merge A..I。
            # 这里用“内竖线边框涂色”为背景色，视觉上等价于合并单元格（内部网格线消失）。
            reqs.append(
                {
                    "updateBorders": {
                        "range": rrange(r0=0, r1=1, c0=col_l0, c1=col_r1),
                        "innerVertical": {"style": "SOLID", "width": 1, "color": _rgb(1.0, 0.97, 0.86)},
                    }
                }
            )

        # 目录区样式（始终覆盖，避免旧格式残留）
        if int(dir_rows) > 0:
            dir_r0 = int(banner_rows)
            dir_r1 = int(banner_rows) + int(dir_rows)
            reqs.append(
                {
                    "repeatCell": {
                        "range": rrange(r0=int(dir_r0), r1=int(dir_r1), c0=col_l0, c1=col_r1),
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": bg_hdr_info,
                                "textFormat": {"bold": True},
                                "horizontalAlignment": "LEFT",
                                "verticalAlignment": "MIDDLE",
                                "wrapStrategy": "OVERFLOW_CELL",
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,wrapStrategy)",
                    }
                }
            )
            # 目录行行高：保持默认（避免“首行很高”影响信息密度）
            reqs.append(
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": int(sh_id),
                            "dimension": "ROWS",
                            "startIndex": int(dir_r0),
                            "endIndex": int(dir_r0) + 1,
                        },
                        # Google Sheets 默认行高通常为 21px
                        "properties": {"pixelSize": 21},
                        "fields": "pixelSize",
                    }
                }
            )

        # header row style（full_style 时重刷背景等；每轮都强制“居中+加粗”以防手工样式漂移）
        hr0 = int(header_row_1) - 1
        if full_style:
            reqs.append(
                {
                    "repeatCell": {
                        "range": rrange(r0=hr0, r1=hr0 + 1, c0=col_l0, c1=col_r1),
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": bg_hdr_group,
                                "textFormat": {"bold": True},
                                "horizontalAlignment": "CENTER",
                                "verticalAlignment": "MIDDLE",
                                "wrapStrategy": "WRAP",
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat.bold,horizontalAlignment,verticalAlignment,wrapStrategy)",
                    }
                }
            )
        # 需求：全部列头/表头字段必须上下左右居中 + 加粗（不动背景色/换行策略）
        reqs.append(
            {
                "repeatCell": {
                    "range": rrange(r0=hr0, r1=hr0 + 1, c0=col_l0, c1=col_r1),
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {"bold": True},
                            "horizontalAlignment": "CENTER",
                            "verticalAlignment": "MIDDLE",
                        }
                    },
                    "fields": "userEnteredFormat(textFormat.bold,horizontalAlignment,verticalAlignment)",
                }
            }
        )

        # 需求：行表头/列表头也要规范（币种/字段等“索引列”）
        # - 主看板索引列：A=卡片，B=币种，C=字段
        # - 仅覆盖 对齐+加粗，不碰背景色（避免影响卡片/币种交替底色）
        body_r0 = int(header_row_1)  # 0-based: row after header
        body_r1 = int(used_end_row_1)  # 0-based end
        if body_r1 > body_r0:
            reqs.append(
                {
                    "repeatCell": {
                        "range": rrange(r0=body_r0, r1=body_r1, c0=col_l0, c1=int(col_l0 + 3)),
                        "cell": {
                            "userEnteredFormat": {
                                "textFormat": {"bold": True},
                                "horizontalAlignment": "CENTER",
                                "verticalAlignment": "MIDDLE",
                            }
                        },
                        "fields": "userEnteredFormat(textFormat.bold,horizontalAlignment,verticalAlignment)",
                    }
                }
            )

        # period columns shading（每轮覆盖）
        # 关键点：
        # - bull/bear（红/绿）只对“方向/信号”行生效
        # - 但如果历史版本曾误上色/或手工改过背景色，在“差量样式”模式下会残留
        # - 因此周期列的灰白底色必须每轮覆盖一遍，保证像“成交额/净流”这类数值行不会残留红绿
        shade_r0 = int(body_r0)
        shade_r1 = int(used_end_row_1)
        if shade_r1 > shade_r0:
            period_index = {p: i for i, p in enumerate(effective_periods)}
            for idx, c in enumerate(columns):
                name = str(c or "").strip()
                if name not in period_index:
                    continue
                bg = bg_body_even if (int(period_index[name]) % 2 == 0) else bg_body_odd
                reqs.append(
                    {
                        "repeatCell": {
                            "range": rrange(r0=shade_r0, r1=shade_r1, c0=col_l0 + idx, c1=col_l0 + idx + 1),
                            "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                            "fields": "userEnteredFormat.backgroundColor",
                        }
                    }
                )

            # 数值列（周期列）统一右对齐 + CLIP（每轮覆盖，避免样式漂移）
            if (col_l0 + 3) < int(col_r1):
                reqs.append(
                    {
                        "repeatCell": {
                            "range": rrange(
                                r0=shade_r0,
                                r1=shade_r1,
                                c0=int(col_l0 + 3),
                                c1=int(col_r1),
                            ),
                            "cell": {"userEnteredFormat": {"horizontalAlignment": "RIGHT", "wrapStrategy": "CLIP"}},
                            "fields": "userEnteredFormat(horizontalAlignment,wrapStrategy)",
                        }
                    }
                )

        # 离散信号上色：多/空 -> 绿/红（每轮都覆盖，避免残留）
        if direction_marks:
            period_index2 = {p: i for i, p in enumerate(effective_periods)}
            period_col_idx: dict[str, int] = {}
            for idx, c in enumerate(columns):
                name = str(c or "").strip()
                if name in period_index2:
                    period_col_idx[name] = int(idx)

            for item in direction_marks:
                try:
                    row_1 = int(item.get("row_1") or 0)
                except Exception:
                    row_1 = 0
                if row_1 <= 0:
                    continue
                row0 = int(row_1) - 1
                pv2 = item.get("period_values") or {}
                if not isinstance(pv2, dict):
                    pv2 = {}

                # 收集该行各周期单元格的目标底色（含 neutral 的“恢复默认底色”）
                cells: list[tuple[int, dict[str, float]]] = []
                for per in effective_periods:
                    ci = period_col_idx.get(per)
                    if ci is None:
                        continue
                    base_bg = bg_body_even if (int(period_index2.get(per) or 0) % 2 == 0) else bg_body_odd
                    cls = _classify_bull_bear(pv2.get(per))
                    if cls > 0:
                        bg = bg_bull
                    elif cls < 0:
                        bg = bg_bear
                    else:
                        bg = base_bg
                    col0 = int(col_l0) + int(ci)
                    cells.append((int(col0), bg))

                if not cells:
                    continue

                cells.sort(key=lambda t: int(t[0]))
                seg_c0: int | None = None
                seg_bg: dict[str, float] | None = None
                prev_c0: int | None = None

                def flush_seg() -> None:
                    nonlocal seg_c0, seg_bg, prev_c0
                    if seg_c0 is None or seg_bg is None or prev_c0 is None:
                        return
                    reqs.append(
                        {
                            "repeatCell": {
                                "range": rrange(r0=int(row0), r1=int(row0 + 1), c0=int(seg_c0), c1=int(prev_c0 + 1)),
                                "cell": {"userEnteredFormat": {"backgroundColor": seg_bg}},
                                "fields": "userEnteredFormat.backgroundColor",
                            }
                        }
                    )
                    seg_c0 = None
                    seg_bg = None
                    prev_c0 = None

                for c0, bg in cells:
                    if seg_c0 is None:
                        seg_c0 = int(c0)
                        seg_bg = bg
                        prev_c0 = int(c0)
                        continue
                    if prev_c0 is not None and int(c0) == int(prev_c0) + 1 and bg == seg_bg:
                        prev_c0 = int(c0)
                        continue
                    flush_seg()
                    seg_c0 = int(c0)
                    seg_bg = bg
                    prev_c0 = int(c0)

                flush_seg()

        # card merges + symbol merges + row-group shading：按层级合并（卡片 -> 币种），提升阅读性
        for body_start_row_1, body_rows in merge_tasks:
            try:
                # body_start_row_1 是 1-based；rrange 用 0-based
                r0_base = int(body_start_row_1) - 1
                rows_for_card = body_rows
                card_span = len(rows_for_card)

                # 1) merge card column (A) for this card body
                if card_span >= 1:
                    r0 = r0_base
                    r1 = r0_base + card_span
                    if card_span >= 2:
                        reqs.append(
                            {
                                "mergeCells": {
                                    "range": {
                                        "sheetId": int(sh_id),
                                        "startRowIndex": int(r0),
                                        "endRowIndex": int(r1),
                                        "startColumnIndex": int(col_l0 + 0),
                                        "endColumnIndex": int(col_l0 + 1),
                                    },
                                    "mergeType": "MERGE_ALL",
                                }
                            }
                        )
                    reqs.append(
                        {
                            "repeatCell": {
                                "range": rrange(r0=int(r0), r1=int(r1), c0=int(col_l0 + 0), c1=int(col_l0 + 1)),
                                "cell": {
                                    "userEnteredFormat": {
                                        "horizontalAlignment": "CENTER",
                                        "verticalAlignment": "MIDDLE",
                                        "textFormat": {"bold": True},
                                        "backgroundColor": _rgb(0.95, 0.96, 0.98),
                                        "wrapStrategy": "CLIP",
                                    }
                                },
                                "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment,textFormat.bold,backgroundColor,wrapStrategy)",
                            }
                        }
                    )

                # 2) 分组：同一币种的连续行作为一个组（按“币种列”纵向 merge）
                _sym_col_name = symbol_key

                def sym_at(i: int, *, _rows: list[dict[str, Any]] = rows_for_card, _k: str = _sym_col_name) -> str:
                    try:
                        v = (_rows[i] or {}).get(_k)
                        return "" if v is None else str(v).strip()
                    except Exception:
                        return ""

                i = 0
                group_idx = 0
                while i < len(rows_for_card):
                    v0 = sym_at(i)
                    j = i + 1
                    while j < len(rows_for_card) and sym_at(j) == v0:
                        j += 1
                    if v0:
                        # merge symbol column (B) for this group
                        if (j - i) >= 2:
                            r0 = r0_base + i
                            r1 = r0_base + j
                            reqs.append(
                                {
                                    "mergeCells": {
                                        "range": {
                                            "sheetId": int(sh_id),
                                            "startRowIndex": int(r0),
                                            "endRowIndex": int(r1),
                                            "startColumnIndex": int(col_l0 + 1),
                                            "endColumnIndex": int(col_l0 + 2),
                                        },
                                        "mergeType": "MERGE_ALL",
                                    }
                                }
                            )
                            reqs.append(
                                {
                                    "repeatCell": {
                                        "range": rrange(r0=int(r0), r1=int(r1), c0=int(col_l0 + 1), c1=int(col_l0 + 2)),
                                        "cell": {
                                            "userEnteredFormat": {
                                                "horizontalAlignment": "CENTER",
                                                "verticalAlignment": "MIDDLE",
                                                "textFormat": {"bold": True},
                                            }
                                        },
                                        "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment,textFormat.bold)",
                                    }
                                }
                            )
                        bg = bg_sym_a if (group_idx % 2 == 0) else bg_sym_b
                        reqs.append(
                            {
                                "repeatCell": {
                                    "range": rrange(
                                        r0=r0_base + i,
                                        r1=r0_base + j,
                                        c0=col_l0 + 1,
                                        c1=col_l0 + 3,  # B..C
                                    ),
                                    "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                                    "fields": "userEnteredFormat.backgroundColor",
                                }
                            }
                        )
                        group_idx += 1
                    i = j
            except Exception:
                continue

        # 清尾巴（格式）：上一轮比本轮更长时，清掉尾部旧样式，避免残留“灰带/分隔线”
        if int(clear_tail_rows_to) > int(used_end_row_1):
            reqs.append(
                {
                    "repeatCell": {
                        "range": rrange(
                            r0=int(used_end_row_1),
                            r1=int(clear_tail_rows_to),
                            c0=int(col_l0),
                            c1=int(col_r1),
                        ),
                        "cell": {"userEnteredFormat": {}},
                        "fields": "userEnteredFormat",
                    }
                }
            )

        # 列宽（美化）：A=卡片，B=币种，C=字段，D..=周期列
        try:
            fixed_widths = _normalize_fixed_widths(
                _env_int_list("SHEETS_DASHBOARD_FIXED_COL_WIDTHS"),
                n_cols=max(int(col_r1) - int(col_l0), 0),
            )
            if fixed_widths:
                for i, px in enumerate(fixed_widths):
                    reqs.append(
                        {
                            "updateDimensionProperties": {
                                "range": {
                                    "sheetId": int(sh_id),
                                    "dimension": "COLUMNS",
                                    "startIndex": int(col_l0 + i),
                                    "endIndex": int(col_l0 + i + 1),
                                },
                                "properties": {"pixelSize": int(px)},
                                "fields": "pixelSize",
                            }
                        }
                    )
            else:
                w_card, w_symbol, w_field, w_period = _dashboard_v5_col_widths_px()
                reqs.append(
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": int(sh_id),
                                "dimension": "COLUMNS",
                                "startIndex": int(col_l0),
                                "endIndex": int(col_l0 + 1),
                            },
                            "properties": {"pixelSize": int(w_card)},
                            "fields": "pixelSize",
                        }
                    }
                )
                reqs.append(
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": int(sh_id),
                                "dimension": "COLUMNS",
                                "startIndex": int(col_l0 + 1),
                                "endIndex": int(col_l0 + 2),
                            },
                            "properties": {"pixelSize": int(w_symbol)},
                            "fields": "pixelSize",
                        }
                    }
                )
                reqs.append(
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": int(sh_id),
                                "dimension": "COLUMNS",
                                "startIndex": int(col_l0 + 2),
                                "endIndex": int(col_l0 + 3),
                            },
                            "properties": {"pixelSize": int(w_field)},
                            "fields": "pixelSize",
                        }
                    }
                )
                # 周期列统一宽度
                if int(col_r1) > int(col_l0 + 3):
                    reqs.append(
                        {
                            "updateDimensionProperties": {
                                "range": {
                                    "sheetId": int(sh_id),
                                    "dimension": "COLUMNS",
                                    "startIndex": int(col_l0 + 3),
                                    "endIndex": int(col_r1),
                                },
                                "properties": {"pixelSize": int(w_period)},
                                "fields": "pixelSize",
                            }
                        }
                    )
        except Exception:
            pass

        if reqs:
            self._exec(
                self._sheets.spreadsheets().batchUpdate(
                    spreadsheetId=self._spreadsheet_id,
                    body={"requests": reqs},
                ),
                is_write=True,
            )
            try:
                self._meta_set(
                    {
                        key_style_version: style_version,
                        key_style_placeholder: placeholder_style,
                        key_styled_rows: str(int(used_end_row_1)),
                        key_dir_rows: str(int(dir_rows)),
                        key_banner_rows: str(int(banner_rows)),
                    }
                )
            except Exception:
                pass
        # compact grid：主看板/看板变体均为“完全托管展示面”，允许裁剪底部/右侧空白网格。
        try:
            frozen_cols = _dashboard_v5_frozen_cols()
            self._set_sheet_grid_properties(
                sheet_title,
                row_count=int(used_rows),
                col_count=int(used_cols),
                frozen_row_count=int(banner_rows) + int(dir_rows) + 1,
                frozen_column_count=int(frozen_cols),
            )
        except Exception:
            pass

        return int(used_rows), int(used_cols)

    def _merge_symbol_column_groups_on_sheet(
        self,
        *,
        sheet_title: str,
        col_l: str,
        sym_col: str,
        body_start_row_1: int,
        body_rows: list[dict[str, Any]],
    ) -> None:
        """
        将同一币种的连续行在“币种列”纵向合并，提升纵向多周期表的可读性。
        - 只合并 body（不动 header）
        - 只合并连续相同值（不强依赖 7 行/币种的假设）
        """
        if not body_rows:
            return

        sh_id = self._sheet_id_by_title.get(sheet_title)
        if sh_id is None:
            self._refresh_sheet_map()
            sh_id = self._sheet_id_by_title.get(sheet_title)
        if sh_id is None:
            return

        col_l_idx = _col_to_index(col_l)
        sym_col_idx0 = col_l_idx - 1  # 币种列在该变体中固定为第一列（A 起始）

        def val_at(i: int) -> str:
            try:
                r = body_rows[i]
                v = r.get(sym_col)
                return "" if v is None else str(v).strip()
            except Exception:
                return ""

        requests: list[dict[str, Any]] = []
        i = 0
        while i < len(body_rows):
            v0 = val_at(i)
            j = i + 1
            while j < len(body_rows) and val_at(j) == v0:
                j += 1
            span = j - i
            if v0 and span >= 2:
                r0 = (body_start_row_1 + i) - 1
                r1 = (body_start_row_1 + j) - 1
                requests.append(
                    {
                        "mergeCells": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": int(r0),
                                "endRowIndex": int(r1),
                                "startColumnIndex": int(sym_col_idx0),
                                "endColumnIndex": int(sym_col_idx0 + 1),
                            },
                            "mergeType": "MERGE_ALL",
                        }
                    }
                )
                # 合并后居中（更像“分组标题”）
                requests.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": int(r0),
                                "endRowIndex": int(r1),
                                "startColumnIndex": int(sym_col_idx0),
                                "endColumnIndex": int(sym_col_idx0 + 1),
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "horizontalAlignment": "CENTER",
                                    "verticalAlignment": "MIDDLE",
                                    "textFormat": {"bold": True},
                                }
                            },
                            "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment,textFormat.bold)",
                        }
                    }
                )
            i = j

        if not requests:
            return

        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": requests},
            ),
            is_write=True,
        )

    # ==================== ops ====================
    def reset_dashboard(self, *, col_l: str, col_r: str, compact: bool = False) -> dict[str, Any]:
        """
        清理看板展示面（不动事实表）：
        - 清空看板全部单元格
        - 解除全部合并单元格
        - 重置 meta.dashboard_next_row=1，并写入新的 dashboard_col_l/dashboard_col_r
        - 清空 slot.*.y（避免“重置后仍沿用旧卡片 y”造成看起来像堆叠/错位）
        """
        self.ensure_schema()
        col_l_u = str(col_l).strip().upper()
        col_r_u = str(col_r).strip().upper()
        self._dashboard_col_l = col_l_u
        self._dashboard_col_r = col_r_u
        self._append_cursor_y = 1

        # 1) clear values
        self._exec(
            self._sheets.spreadsheets()
            .values()
            .clear(
                spreadsheetId=self._spreadsheet_id,
                range=f"{self._tab_dashboard}!A:ZZ",
            ),
            is_write=True,
        )

        # 2) unmerge all
        sh_id = self._sheet_id_by_title.get(self._tab_dashboard)
        if sh_id is None:
            self._refresh_sheet_map()
            sh_id = self._sheet_id_by_title[self._tab_dashboard]

        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": [{"unmergeCells": {"range": {"sheetId": int(sh_id)}}}]},
            ),
            is_write=True,
        )

        # 2.5) clear formats/borders（避免“残留配色/残留竖线”）
        # values.clear 不会清掉 userEnteredFormat；必须显式重置。
        try:
            target_cols = max(_col_to_index(col_r_u), 1)
        except Exception:
            target_cols = 26
        target_rows = (
            2000 if compact else max(int(self._grid_by_title.get(self._tab_dashboard, (2000, 0))[0] or 2000), 1)
        )
        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={
                    "requests": [
                        {
                            "repeatCell": {
                                "range": {
                                    "sheetId": int(sh_id),
                                    "startRowIndex": 0,
                                    "endRowIndex": int(target_rows),
                                    "startColumnIndex": 0,
                                    "endColumnIndex": int(target_cols),
                                },
                                "cell": {"userEnteredFormat": {}},
                                "fields": "userEnteredFormat",
                            }
                        }
                    ]
                },
            ),
            is_write=True,
        )

        # 3) reset meta
        if self._schema_mode == "minimal":
            # local meta：只清理 dashboard 与 slot，避免无意义增长
            self._local_meta_set(
                {
                    "dashboard_next_row": "1",
                    "dashboard_col_l": col_l_u,
                    "dashboard_col_r": col_r_u,
                    "dashboard_mode": self._dashboard_mode,
                    "dashboard_slot_height": str(self._dashboard_slot_height),
                },
                clear_prefixes=["slot."],
            )
        else:
            meta = self._meta_get()
            slot_clear: dict[str, str] = {}
            for k in meta.keys():
                if k.startswith("slot.") and (k.endswith(".y") or k.endswith(".h")):
                    slot_clear[k] = "0"

            kv = {
                "dashboard_next_row": "1",
                "dashboard_col_l": col_l_u,
                "dashboard_col_r": col_r_u,
                "dashboard_mode": self._dashboard_mode,
                "dashboard_slot_height": str(self._dashboard_slot_height),
                **slot_clear,
            }
            self._meta_set(kv)

        if compact:
            # 只压缩 dashboard 本身（展示面允许破坏性变更），避免历史事实表被误删。
            sh_id = self._sheet_id_by_title.get(self._tab_dashboard)
            if sh_id is None:
                self._refresh_sheet_map()
                sh_id = self._sheet_id_by_title[self._tab_dashboard]

            target_rows = 2
            target_cols = max(_col_to_index(col_r_u), 1)
            self._exec(
                self._sheets.spreadsheets().batchUpdate(
                    spreadsheetId=self._spreadsheet_id,
                    body={
                        "requests": [
                            {
                                "updateSheetProperties": {
                                    "properties": {
                                        "sheetId": int(sh_id),
                                        "gridProperties": {
                                            "rowCount": int(target_rows),
                                            "columnCount": int(target_cols),
                                            # 看板会大量 mergeCells（title/update/sort/hint/last 全行合并）；
                                            # Sheets 禁止跨“冻结列边界”合并，因此这里强制关闭冻结列。
                                            "frozenColumnCount": 0,
                                            "hideGridlines": False,
                                        },
                                    },
                                    "fields": "gridProperties.rowCount,gridProperties.columnCount,gridProperties.frozenColumnCount,gridProperties.hideGridlines",
                                }
                            }
                        ]
                    },
                ),
                is_write=True,
            )
            self._refresh_sheet_map()
        return {"ok": True, "dashboard": {"sheet": self._tab_dashboard, "col_l": col_l, "col_r": col_r, "row_y": 1}}

    def rebuild_dashboard(self, *, max_cards: int = 200) -> dict[str, Any]:
        """
        从事实表重建看板（用于运维：看板可随时重建）。

        读取来源：
        - cards_index：卡片索引（按 append 顺序，取最后 max_cards）
        - card_fields_eav：提取 hint.text / table.columns[*]
        - card_rows：row_json 还原 table.rows
        """
        self.ensure_schema()
        if self._schema_mode == "minimal":
            raise RuntimeError(
                "minimal_schema 下不支持从事实表重建：请先切回 SHEETS_SCHEMA_MODE=full 或关闭 --rebuild-dashboard"
            )

        meta = self._meta_get()
        col_l = (meta.get("dashboard_col_l") or self._dashboard_col_l).strip().upper()
        col_r = (meta.get("dashboard_col_r") or self._dashboard_col_r).strip().upper()
        mode = (self._dashboard_mode or meta.get("dashboard_mode") or "replace").strip().lower()
        if mode not in {"append", "replace"}:
            mode = "replace"

        # 1) 拉取索引
        idx_vals = self._exec(
            self._sheets.spreadsheets()
            .values()
            .get(
                spreadsheetId=self._spreadsheet_id,
                range=f"{self._tab_cards_index}!A:N",
            ),
            is_write=False,
        ).get("values", [])
        if not idx_vals or len(idx_vals) <= 1:
            self.reset_dashboard(col_l=col_l, col_r=col_r)
            return {"ok": True, "cards": 0, "note": "cards_index 为空"}

        rows = idx_vals[1:]

        # 取最后 N 条
        if max_cards > 0:
            rows = rows[-max_cards:]

        # 索引列（按 ensure_schema 的表头）
        # card_key, ts_utc, source_service, card_type, title, update_time, sort_desc, last_update, tg_url, ...
        def g(r: list[str], i: int) -> str:
            return str(r[i]).strip() if i < len(r) and r[i] is not None else ""

        # replace 模式：按 card_type 取“最新一条”，避免重建时把历史卡片按时间堆叠出一长串。
        picked_rows: list[list[str]] = []
        if mode == "replace":
            latest_by_type: dict[str, list[str]] = {}
            for r in rows:
                ck = g(r, 0)
                ct = g(r, 3)
                if not ck or not ct:
                    continue
                latest_by_type[ct] = r
            # 排序口径：优先按 TG 卡片 priority（越大越靠前），其次按 card_type 稳定排序。
            pri = self._load_card_priority_map()
            for ct in sorted(latest_by_type.keys(), key=lambda k: (-int(pri.get(k, 0) or 0), k)):
                picked_rows.append(latest_by_type[ct])
        else:
            picked_rows = rows

        card_items: list[dict[str, str]] = []
        wanted_keys: list[str] = []
        for r in picked_rows:
            ck = g(r, 0)
            if not ck:
                continue
            wanted_keys.append(ck)
            card_items.append(
                {
                    "card_key": ck,
                    "ts_utc": g(r, 1),
                    "source_service": g(r, 2),
                    "card_type": g(r, 3),
                    "title": g(r, 4),
                    "update_time": g(r, 5),
                    "sort_desc": g(r, 6),
                    "last_update": g(r, 7),
                    "tg_url": g(r, 8),
                }
            )

        wanted = set(wanted_keys)
        if not wanted:
            self.reset_dashboard(col_l=col_l, col_r=col_r)
            return {"ok": True, "cards": 0, "note": "no_valid_card_keys"}

        # 2) 拉取 EAV（只解析必要字段）
        eav_vals = self._exec(
            self._sheets.spreadsheets()
            .values()
            .get(
                spreadsheetId=self._spreadsheet_id,
                range=f"{self._tab_card_fields_eav}!A:D",
            ),
            is_write=False,
        ).get("values", [])
        # skip header
        eav_rows = eav_vals[1:] if eav_vals else []

        hint_by_key: dict[str, str] = {}
        cols_by_key: dict[str, dict[int, str]] = {}
        for r in eav_rows:
            if not r or len(r) < 4:
                continue
            ck = str(r[0]).strip()
            if ck not in wanted:
                continue
            path = str(r[1]).strip()
            vtext = "" if r[2] is None else str(r[2])

            if path == "hint.text":
                hint_by_key[ck] = vtext
                continue

            if path.startswith("table.columns[") and path.endswith("]"):
                try:
                    idx = int(path[len("table.columns[") : -1])
                except Exception:
                    continue
                cols_by_key.setdefault(ck, {})[idx] = vtext

        # 3) 拉取明细行
        cr_vals = self._exec(
            self._sheets.spreadsheets()
            .values()
            .get(
                spreadsheetId=self._spreadsheet_id,
                range=f"{self._tab_card_rows}!A:D",
            ),
            is_write=False,
        ).get("values", [])
        cr_rows = cr_vals[1:] if cr_vals else []

        rows_by_key: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        for r in cr_rows:
            if not r or len(r) < 4:
                continue
            ck = str(r[0]).strip()
            if ck not in wanted:
                continue
            try:
                row_index = int(str(r[1]).strip() or "0")
            except Exception:
                row_index = 0
            raw_json = "" if r[3] is None else str(r[3])
            try:
                row_obj = json.loads(raw_json) if raw_json else {}
            except Exception:
                row_obj = {"_raw": raw_json}
            rows_by_key.setdefault(ck, []).append((row_index, row_obj))

        # sort rows by row_index
        sorted_rows_by_key: dict[str, list[dict[str, Any]]] = {}
        for ck, items in rows_by_key.items():
            items_sorted = sorted(items, key=lambda it: int(it[0]))
            sorted_rows_by_key[ck] = [it[1] for it in items_sorted]

        # 4) reset 看板
        self.reset_dashboard(col_l=col_l, col_r=col_r)

        # 5) 重放渲染
        y = 1
        min_slot_height = max(int(self._dashboard_slot_height), 1)
        slot_updates: dict[str, str] = {}
        for item in card_items:
            ck = item["card_key"]
            cols_map = cols_by_key.get(ck, {})
            if cols_map:
                max_i = max(cols_map.keys())
                columns = [cols_map.get(i, "") for i in range(0, max_i + 1)]
            else:
                columns = []

            payload: dict[str, Any] = {
                "card_key": ck,
                "ts_utc": item.get("ts_utc") or "",
                "source_service": item.get("source_service") or "",
                "card_type": item.get("card_type") or "",
                "header": {
                    "title": item.get("title") or "",
                    "update_time": item.get("update_time") or "",
                    "sort_desc": item.get("sort_desc") or "",
                },
                "params": {"last_update": item.get("last_update") or ""},
                "hint": {"text": hint_by_key.get(ck, "")},
                "table": {"columns": columns, "rows": sorted_rows_by_key.get(ck, [])},
                "tg": {"url": item.get("tg_url") or ""},
                "raw": {"telegram_text_full": "", "payload_json_full": {}},
            }

            if mode == "replace":
                ct = (item.get("card_type") or "").strip()
                h = self._calc_dashboard_height(payload, col_l=col_l, col_r=col_r)
                reserved = max(int(h), int(min_slot_height))
                if ct:
                    slot_updates[f"slot.{ct}.y"] = str(y)
                    slot_updates[f"slot.{ct}.h"] = str(reserved)

            self._render_dashboard(payload, y=y, col_l=col_l, col_r=col_r)
            if mode == "replace":
                y += reserved
            else:
                height = self._calc_dashboard_height(payload, col_l=col_l, col_r=col_r)
                y += height

        kv = {"dashboard_next_row": str(y), **slot_updates}
        self._meta_set(kv)
        return {"ok": True, "cards": len(card_items), "dashboard_next_row": y, "dashboard_mode": mode}

    def _load_card_priority_map(self) -> dict[str, int]:
        """
        尝试从 telegram-service 的 cards registry 加载 priority，用于“看板重建排序”。
        - 失败时返回空 dict：自动 fallback 为按 card_type 排序
        """
        try:
            import sys
            from pathlib import Path

            from src.repo import find_repo_root, find_telegram_service_src

            start = Path(__file__).resolve()
            repo_root = find_repo_root(start)
            tg_src = find_telegram_service_src(repo_root)
            if str(repo_root) not in sys.path:
                sys.path.insert(0, str(repo_root))
            if str(tg_src) not in sys.path:
                sys.path.insert(0, str(tg_src))

            from cards.registry import RankingRegistry  # type: ignore

            reg = RankingRegistry()
            reg.load_cards()
            out: dict[str, int] = {}
            for c in reg.iter_cards():
                cid = str(getattr(c, "card_id", "") or "").strip()
                if not cid:
                    continue
                try:
                    pr = int(getattr(c, "priority", 0) or 0)
                except Exception:
                    pr = 0
                out[cid] = pr
            return out
        except Exception:
            return {}

    def _migrate_legacy_tabs(self) -> None:
        """
        将历史英文 tab 名迁移为中文 tab 名。

        - 若新中文名不存在：直接 rename（保留原 sheetId 与历史数据）
        - 若新中文名已存在：把旧英文 tab 重命名为 `旧_<中文名>`，避免数据丢失
        """
        legacy_to_target = {
            "dashboard": self._tab_dashboard,
            "cards_index": self._tab_cards_index,
            "card_fields_eav": self._tab_card_fields_eav,
            "card_rows": self._tab_card_rows,
            "row_fields_eav": self._tab_row_fields_eav,
            "blobs_index": self._tab_blobs_index,
            "meta": self._tab_meta,
        }

        if not self._sheet_id_by_title:
            return

        requests: list[dict[str, Any]] = []
        for legacy, target in legacy_to_target.items():
            if legacy not in self._sheet_id_by_title:
                continue

            sheet_id = int(self._sheet_id_by_title[legacy])
            if target not in self._sheet_id_by_title:
                new_title = target
            else:
                new_title = f"旧_{target}"
                if new_title in self._sheet_id_by_title:
                    new_title = f"旧_{target}_{sheet_id}"

            requests.append(
                {
                    "updateSheetProperties": {
                        "properties": {"sheetId": sheet_id, "title": new_title},
                        "fields": "title",
                    }
                }
            )

        if not requests:
            return

        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": requests},
            ),
            is_write=True,
        )

    def _refresh_sheet_map(self) -> None:
        ss = self._exec(
            self._sheets.spreadsheets().get(
                spreadsheetId=self._spreadsheet_id,
                fields="sheets.properties(sheetId,title,gridProperties(rowCount,columnCount))",
            ),
            is_write=False,
        )
        out: dict[str, int] = {}
        grid: dict[str, tuple[int, int]] = {}
        for sh in ss.get("sheets", []):
            props = sh.get("properties", {})
            title = str(props.get("title"))
            out[title] = int(props.get("sheetId"))
            gp = props.get("gridProperties") or {}
            try:
                rc = int(gp.get("rowCount") or 0)
                cc = int(gp.get("columnCount") or 0)
            except Exception:
                rc, cc = 0, 0
            grid[title] = (rc, cc)
        self._sheet_id_by_title = out
        self._grid_by_title = grid

    def snapshot_column_widths(self, title: str, *, n_cols: int | None = None, max_cols: int = 120) -> list[int]:
        """
        读取指定 tab 的列宽（pixelSize），用于“人工在 UI 调整好后固化为配置”。

        - 只读：不会写入任何数据/样式
        - 默认读取当前 sheet 的 gridProperties.columnCount（若 compact grid 生效，列数会很小）
        """
        self._refresh_sheet_map()
        if title not in self._sheet_id_by_title:
            raise RuntimeError(f"missing_sheet:{title}")

        _rc, cc = self._grid_by_title.get(title, (0, 0))
        if n_cols is None:
            n_cols = int(cc or 0)
        n_cols = max(int(n_cols or 0), 1)
        n_cols = min(int(n_cols), max(int(max_cols), 1))

        col_r = _index_to_col(int(n_cols))
        ss = self._exec(
            self._sheets.spreadsheets().get(
                spreadsheetId=self._spreadsheet_id,
                ranges=[f"{title}!A1:{col_r}1"],
                includeGridData=True,
                fields="sheets(properties(title),data(columnMetadata(pixelSize)))",
            ),
            is_write=False,
        )

        # 可能返回多个 sheet（理论上 ranges 已限定）；这里仍按 title 精确匹配
        target = None
        for sh in ss.get("sheets", []) or []:
            props = sh.get("properties") or {}
            if str(props.get("title") or "").strip() == str(title).strip():
                target = sh
                break
        if target is None and (ss.get("sheets") or []):
            target = (ss.get("sheets") or [])[0]
        if target is None:
            raise RuntimeError(f"missing_sheet_data:{title}")

        md = ((target.get("data") or [{}])[0] or {}).get("columnMetadata") or []
        out: list[int] = []
        for i in range(0, int(n_cols)):
            px = None
            try:
                px = (md[i] or {}).get("pixelSize")
            except Exception:
                px = None
            if px is None:
                out.append(100)
            else:
                try:
                    out.append(int(px))
                except Exception:
                    out.append(100)
        return out

    def _ensure_grid_size(self, title: str, *, min_rows: int, min_cols: int) -> None:
        if min_rows <= 0 and min_cols <= 0:
            return

        sheet_id = self._sheet_id_by_title.get(title)
        if sheet_id is None:
            self._refresh_sheet_map()
            sheet_id = self._sheet_id_by_title.get(title)
        if sheet_id is None:
            raise RuntimeError(f"missing_sheet:{title}")

        row_count, col_count = self._grid_by_title.get(title, (0, 0))
        want_rows = max(int(min_rows), 0)
        want_cols = max(int(min_cols), 0)

        new_row_count = row_count
        new_col_count = col_count
        if want_rows > row_count:
            new_row_count = max(want_rows, row_count + 2000 if row_count > 0 else want_rows)
        if want_cols > col_count:
            new_col_count = max(want_cols, col_count + 10 if col_count > 0 else want_cols)

        if new_row_count == row_count and new_col_count == col_count:
            return

        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={
                    "requests": [
                        {
                            "updateSheetProperties": {
                                "properties": {
                                    "sheetId": int(sheet_id),
                                    "gridProperties": {
                                        "rowCount": int(new_row_count),
                                        "columnCount": int(new_col_count),
                                    },
                                },
                                "fields": "gridProperties.rowCount,gridProperties.columnCount",
                            }
                        }
                    ]
                },
            ),
            is_write=True,
        )
        # refresh cache
        self._refresh_sheet_map()

    def _apply_cell_formulas(self, *, sheet_title: str, cells: list[tuple[int, int]], formula: str) -> None:
        """
        在指定单元格写入同一个公式（USER_ENTERED），用于“纯函数占位”。

        输入：
        - cells: (row_1, col_1) 1-based 坐标

        设计目标：
        - 避免把整块 range 改成 USER_ENTERED（会把 `+2.89M` 之类误当公式导致报错）
        - 只对需要的空单元格写公式，保持其它值 RAW 写入不变
        """
        if not cells or not formula:
            return

        coords: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for r1, c1 in cells:
            try:
                rr = int(r1)
                cc = int(c1)
            except Exception:
                continue
            if rr <= 0 or cc <= 0:
                continue
            key = (rr, cc)
            if key in seen:
                continue
            seen.add(key)
            coords.append(key)

        if not coords:
            return

        coords.sort()

        # 将同一行的连续列合并成一个 range，减少 batchUpdate data entries 数量
        data_entries: list[dict[str, Any]] = []
        i = 0
        while i < len(coords):
            row_1 = int(coords[i][0])
            cols: list[int] = []
            while i < len(coords) and int(coords[i][0]) == int(row_1):
                cols.append(int(coords[i][1]))
                i += 1
            if not cols:
                continue
            cols.sort()

            start = int(cols[0])
            prev = int(cols[0])
            for c in cols[1:] + [-1]:
                if c == (prev + 1):
                    prev = int(c)
                    continue

                col_l = _index_to_col(int(start))
                col_r = _index_to_col(int(prev))
                rng = f"{sheet_title}!{col_l}{int(row_1)}:{col_r}{int(row_1)}"
                width = int(prev) - int(start) + 1
                data_entries.append({"range": rng, "values": [[str(formula)] * int(width)]})

                start = int(c)
                prev = int(c)

        if not data_entries:
            return

        try:
            chunk_size = int((os.environ.get("SHEETS_PLACEHOLDER_FORMULA_RANGES_PER_WRITE", "400") or "400").strip())
        except Exception:
            chunk_size = 400
        chunk_size = max(int(chunk_size), 50)

        for off in range(0, len(data_entries), int(chunk_size)):
            chunk = data_entries[int(off) : int(off) + int(chunk_size)]
            self._exec(
                self._sheets.spreadsheets()
                .values()
                .batchUpdate(
                    spreadsheetId=self._spreadsheet_id,
                    body={
                        "valueInputOption": "USER_ENTERED",
                        "data": chunk,
                    },
                ),
                is_write=True,
            )

    def _set_sheet_grid_properties(
        self,
        title: str,
        *,
        row_count: int | None = None,
        col_count: int | None = None,
        frozen_row_count: int | None = None,
        frozen_column_count: int | None = None,
    ) -> None:
        """
        精确设置 sheet 的网格属性（可收缩），用于“列外无单元格/无网格”的展示效果。

        注意：
        - rowCount/columnCount 收缩会“删除”网格外的单元格（与在 UI 里删除多余行/列等价）。
        - 因此该函数默认只用于“由系统完全托管”的展示型 tab（看板/币种查询）。
        """
        if row_count is None and col_count is None and frozen_row_count is None and frozen_column_count is None:
            return

        sheet_id = self._sheet_id_by_title.get(title)
        if sheet_id is None:
            self._refresh_sheet_map()
            sheet_id = self._sheet_id_by_title.get(title)
        if sheet_id is None:
            raise RuntimeError(f"missing_sheet:{title}")

        gp: dict[str, int] = {}
        fields: list[str] = []

        # 需求硬约束：不隐藏网格线（保持默认网格线可见）。
        # - 这里采用“强制纠偏”策略：凡是调用本函数修改 gridProperties，就顺手把 hideGridlines 置为 False，
        #   以修复历史遗留（旧版写入过 hideGridlines=True）并确保全部托管 tab 观感一致。
        gp["hideGridlines"] = False
        fields.append("gridProperties.hideGridlines")

        if row_count is not None:
            gp["rowCount"] = max(int(row_count), 1)
            fields.append("gridProperties.rowCount")
        if col_count is not None:
            gp["columnCount"] = max(int(col_count), 1)
            fields.append("gridProperties.columnCount")
        if frozen_row_count is not None:
            gp["frozenRowCount"] = max(int(frozen_row_count), 0)
            fields.append("gridProperties.frozenRowCount")
        if frozen_column_count is not None:
            gp["frozenColumnCount"] = max(int(frozen_column_count), 0)
            fields.append("gridProperties.frozenColumnCount")

        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={
                    "requests": [
                        {
                            "updateSheetProperties": {
                                "properties": {"sheetId": int(sheet_id), "gridProperties": gp},
                                "fields": ",".join(fields),
                            }
                        }
                    ]
                },
            ),
            is_write=True,
        )
        self._refresh_sheet_map()

    def _set_sheet_hidden(self, title: str, *, hidden: bool) -> None:
        sheet_id = self._sheet_id_by_title.get(title)
        if sheet_id is None:
            self._refresh_sheet_map()
            sheet_id = self._sheet_id_by_title.get(title)
        if sheet_id is None:
            raise RuntimeError(f"missing_sheet:{title}")

        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={
                    "requests": [
                        {
                            "updateSheetProperties": {
                                "properties": {"sheetId": int(sheet_id), "hidden": bool(hidden)},
                                "fields": "hidden",
                            }
                        }
                    ]
                },
            ),
            is_write=True,
        )

    def _ensure_header_row(self, sheet: str, headers: list[str]) -> None:
        rng = f"{sheet}!1:1"
        got = self._exec(
            self._sheets.spreadsheets()
            .values()
            .get(
                spreadsheetId=self._spreadsheet_id,
                range=rng,
            ),
            is_write=False,
        )
        values = got.get("values", [])
        if values and any(v != "" for v in values[0]):
            return
        self._exec(
            self._sheets.spreadsheets()
            .values()
            .update(
                spreadsheetId=self._spreadsheet_id,
                range=f"{sheet}!A1",
                valueInputOption="RAW",
                body={"values": [headers]},
            ),
            is_write=True,
        )

    # ==================== meta ====================
    def _meta_get(self) -> dict[str, str]:
        if self._schema_mode == "minimal":
            return self._local_meta_get()
        got = self._exec(
            self._sheets.spreadsheets()
            .values()
            .get(
                spreadsheetId=self._spreadsheet_id,
                range=f"{self._tab_meta}!A:B",
            ),
            is_write=False,
        )
        rows = got.get("values", [])
        out: dict[str, str] = {}
        for r in rows[1:]:  # skip header
            if not r:
                continue
            k = str(r[0]).strip() if len(r) >= 1 else ""
            v = str(r[1]) if len(r) >= 2 else ""
            if k:
                out[k] = v
        return out

    def _meta_set(self, kv: dict[str, str]) -> None:
        if self._schema_mode == "minimal":
            self._local_meta_set(kv)
            return
        # 简单 upsert：读出当前 mapping -> 更新/append（低频路径）
        got = self._exec(
            self._sheets.spreadsheets()
            .values()
            .get(
                spreadsheetId=self._spreadsheet_id,
                range=f"{self._tab_meta}!A:B",
            ),
            is_write=False,
        )
        rows = got.get("values", [])
        pos: dict[str, int] = {}
        for idx, r in enumerate(rows[1:], start=2):
            if r and len(r) >= 1 and str(r[0]).strip():
                pos[str(r[0]).strip()] = idx

        updates: list[dict[str, Any]] = []
        appends: list[list[str]] = []
        for k, v in kv.items():
            if k in pos:
                updates.append({"range": f"{self._tab_meta}!B{pos[k]}", "values": [[str(v)]]})
            else:
                appends.append([k, str(v)])

        if updates:
            self._exec(
                self._sheets.spreadsheets()
                .values()
                .batchUpdate(
                    spreadsheetId=self._spreadsheet_id,
                    body={"valueInputOption": "RAW", "data": updates},
                ),
                is_write=True,
            )

        if appends:
            self._exec(
                self._sheets.spreadsheets()
                .values()
                .append(
                    spreadsheetId=self._spreadsheet_id,
                    range=f"{self._tab_meta}!A1",
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": appends},
                ),
                is_write=True,
            )

    # 运维友好：对外暴露 meta（用于节流/周期性任务）
    def meta_get(self) -> dict[str, str]:
        self.ensure_schema()
        return self._meta_get()

    def meta_set(self, kv: dict[str, str]) -> None:
        self.ensure_schema()
        self._meta_set(kv)

    def _local_meta_get(self) -> dict[str, str]:
        p = self._local_meta_path
        if not p:
            return {}
        try:
            if not p.exists():
                return {}
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {}
            out: dict[str, str] = {}
            for k, v in data.items():
                if k is None:
                    continue
                out[str(k)] = "" if v is None else str(v)
            return out
        except Exception:
            return {}

    def _local_meta_set(self, kv: dict[str, str], *, clear_prefixes: list[str] | None = None) -> None:
        p = self._local_meta_path
        if not p:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        cur = self._local_meta_get()
        if clear_prefixes:
            for pref in clear_prefixes:
                for k in list(cur.keys()):
                    if str(k).startswith(pref):
                        cur.pop(k, None)
        for k, v in kv.items():
            cur[str(k)] = "" if v is None else str(v)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(cur, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")
        tmp.replace(p)

    # ==================== write ====================
    def write_card(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.ensure_schema()

        card_key = str(payload.get("card_key") or "").strip()
        if not card_key:
            raise RuntimeError("missing_card_key")

        # 以运行时配置（进程参数/env）为真相源：避免“表内 meta 被写坏/漂移”导致列从 A 飘到 N 等错位。
        col_l = (self._dashboard_col_l or "A").strip().upper()
        col_r = (self._dashboard_col_r or "M").strip().upper()
        # 行为口径：以“运行时配置/构造参数”为准，避免表内 meta 被旧进程写坏导致模式漂移。
        mode = (self._dashboard_mode or "replace").strip().lower()
        min_slot_height = max(int(self._dashboard_slot_height), 1)
        facts_mode = (self._facts_mode or "append").strip().lower()
        if facts_mode not in {"append", "none"}:
            facts_mode = "append"
        # minimal schema：不允许写事实表（tab 会被修剪掉）；强制降级为只写看板。
        if self._schema_mode == "minimal":
            facts_mode = "none"
            self._facts_mode = "none"

        if mode not in {"append", "replace"}:
            mode = "replace"

        card_type = str(payload.get("card_type") or "").strip()
        slot_key = card_type or str(payload.get("card_key") or "").strip()
        height = self._calc_dashboard_height(payload, col_l=col_l, col_r=col_r)

        reserved_height = height
        if mode == "replace":
            slot_y_key = f"slot.{slot_key}.y"
            slot_h_key = f"slot.{slot_key}.h"
            meta = self._meta_get()
            y = int(meta.get(slot_y_key) or "0")
            prev_reserved = int(meta.get(slot_h_key) or "0")

            if y <= 0:
                y = int(meta.get("dashboard_next_row") or "1")
                reserved_height = max(height, min_slot_height)
                self._meta_set(
                    {
                        slot_y_key: str(y),
                        slot_h_key: str(reserved_height),
                        "dashboard_next_row": str(y + reserved_height),
                    }
                )
                meta = self._meta_get()
            else:
                reserved_height = max(prev_reserved, min_slot_height)
                # 如果当前卡片高度超过历史预留高度：需要“扩容”，否则会覆盖下一张卡片。
                if height > reserved_height:
                    delta = int(height - reserved_height)
                    self._dashboard_insert_rows(y=y, reserved_height=reserved_height, delta=delta, meta=meta)
                    reserved_height = height
                    # meta 已在 _dashboard_insert_rows 内更新；重新读取以免漂移
                    meta = self._meta_get()
        else:
            # append：minimal schema 不依赖 sheet meta，使用进程内 cursor；full schema 仍可用 meta
            if self._schema_mode == "minimal":
                y = int(self._append_cursor_y or 1)
            else:
                meta = self._meta_get()
                y = int(meta.get("dashboard_next_row") or "1")

        dash = {
            "sheet": self._tab_dashboard,
            "col_l": col_l,
            "col_r": col_r,
            "row_y": y,
            "height": height,
            "reserved_height": reserved_height if mode == "replace" else height,
        }

        # 1) dashboard（必须优先成功：展示面不能被事实写入失败拖垮）
        self._ensure_grid_size(
            self._tab_dashboard,
            min_rows=y + (reserved_height if mode == "replace" else height),
            min_cols=_col_to_index(col_r),
        )
        if mode == "replace":
            self._clear_dashboard_slot(y=y, slot_height=reserved_height, col_l=col_l, col_r=col_r)
        self._render_dashboard(payload, y=y, col_l=col_l, col_r=col_r)

        # 2) facts（可选：append-only；工作簿达到 1000 万 cells 上限后必须关闭）
        if facts_mode == "append":
            try:
                # blob（可选：超长 raw）——会向“大字段索引”追加一行；在 cells 上限时也会失败
                self._maybe_blob(payload)
                self._append_cards_index(payload, dash)
                self._append_card_fields_eav(payload)
                self._append_rows_eav(payload)
            except Exception as exc:
                # 触发条件：Google Sheets 1000 万 cells 上限
                msg = str(exc)
                if "above the limit of 10000000 cells" in msg:
                    # 事实表写入不可用：降级为“仅看板覆盖写”，避免服务整体卡死在 outbox
                    facts_mode = "none"
                    self._facts_mode = "none"
                else:
                    raise

        # 3) meta bump
        if mode == "append":
            if self._schema_mode == "minimal":
                self._append_cursor_y = int(y + height)
                self._local_meta_set({"dashboard_next_row": str(self._append_cursor_y)})
            else:
                self._meta_set({"dashboard_next_row": str(y + height)})
        elif mode == "replace":
            # 记录最终预留高度（非递减），用于后续清理/扩容判断
            slot_h_key = f"slot.{slot_key}.h"
            try:
                cur = int((meta.get(slot_h_key) or "0").strip() or "0")
            except Exception:
                cur = 0
            if reserved_height > cur:
                self._meta_set({slot_h_key: str(reserved_height)})

        return {"ok": True, "card_key": card_key, "idempotent": False, "dashboard": dash, "facts_mode": facts_mode}

    def prune_tabs(
        self,
        *,
        symbol_tab_prefix: str,
        keep_symbol_tabs: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        删除非必要 tab：只保留：
        - 看板（SHEETS_TAB_DASHBOARD）
        - 交易对子表（默认：title 以 symbol_tab_prefix 开头；可选：仅保留 keep_symbol_tabs）
        """
        # daemon 场景下 prune_tabs 可能每分钟触发一次；如果网络/代理偶发抖动，会导致日志刷屏。
        # 这里加“节流”：minimal schema 下默认每小时最多尝试一次（可通过 env 调整/关闭）。
        # - env: SHEETS_PRUNE_TABS_INTERVAL_SECONDS（默认 3600；<=0 表示每次都尝试）
        # - 记录：写入 local_meta（minimal 模式的单一真相源）
        minimal_throttle = self._schema_mode == "minimal"
        if minimal_throttle:
            try:
                interval = int((os.environ.get("SHEETS_PRUNE_TABS_INTERVAL_SECONDS", "3600") or "3600").strip() or "3600")
            except Exception:
                interval = 3600
            if interval > 0:
                try:
                    meta = self._local_meta_get()
                    last = int(str(meta.get("prune_tabs_last_epoch") or "0").strip() or "0")
                except Exception:
                    last = 0
                now = int(time.time())
                if int(last) > 0 and (now - int(last)) < int(interval):
                    return {"deleted": 0, "kept": [], "skipped": 1, "reason": "throttled"}

        # 先落盘“本次尝试时间”，确保即便后续网络/代理抖动失败，也不会每分钟刷屏
        if minimal_throttle:
            try:
                self._local_meta_set({"prune_tabs_last_epoch": str(int(time.time()))})
            except Exception:
                pass

        try:
            self.ensure_schema()
            self._refresh_sheet_map()
        except Exception as exc:
            if minimal_throttle:
                try:
                    self._local_meta_set({"prune_tabs_last_error": f"{type(exc).__name__}:{exc}"[:2000]})
                except Exception:
                    pass
                return {"deleted": 0, "kept": [], "ok": False, "error": f"{type(exc).__name__}:{exc}"}
            raise
        keep: set[str] = {self._tab_dashboard}

        # v5 数据层/历史层：默认保留（tab 默认隐藏，不影响“最少交互”的阅读体验）
        keep_data = (os.environ.get("SHEETS_PRUNE_KEEP_DASHBOARD_DATA", "1") or "1").strip() != "0"
        keep_history = (os.environ.get("SHEETS_PRUNE_KEEP_DASHBOARD_HISTORY", "1") or "1").strip() != "0"
        keep_meta = (os.environ.get("SHEETS_PRUNE_KEEP_DASHBOARD_META", "1") or "1").strip() != "0"
        if keep_data:
            keep.add(self._tab_dashboard_data)
        if keep_history:
            keep.add(self._tab_dashboard_history)
        if keep_meta:
            keep.add(self._tab_dashboard_meta)

        # 外部数据旁路：Polymarket 统计子表（默认保留）
        keep_polymarket = (os.environ.get("SHEETS_PRUNE_KEEP_POLYMARKET_STATS", "1") or "1").strip() != "0"
        if keep_polymarket:
            keep.add(self._tab_polymarket_stats)
            # Polymarket统计拆分为 3 个阅读表时，也必须保留拆分后的子表，
            # 否则 minimal schema 每轮 prune 会把它们删掉，导致用户“看不到子表”。
            split_enabled = (os.environ.get("SHEETS_POLYMARKET_STATS_SPLIT", "1") or "1").strip() != "0"
            if split_enabled:
                keep.add(_env_text("SHEETS_TAB_POLYMARKET_TOP15", "PolymarketTop15"))
                keep.add(_env_text("SHEETS_TAB_POLYMARKET_TIMESLOT", "Polymarket时段分布"))
                keep.add(_env_text("SHEETS_TAB_POLYMARKET_CATEGORY", "Polymarket类别偏好"))

        # 外部数据旁路：Polymarket facts 事件子表（默认不保留）
        # 说明：该表是高频明细/审计视图，默认不进入“最少交互”的看板集合；需要时显式开启保留。
        keep_polymarket_events = (os.environ.get("SHEETS_PRUNE_KEEP_POLYMARKET_EVENTS", "0") or "0").strip() != "0"
        if keep_polymarket_events:
            keep.add(self._tab_polymarket_events)

        # 可选：保留“看板变体 tab”（用于对比不同高密度布局）
        # 默认不保留：避免用户只想保留最小集合时被额外 tab 污染。
        keep_variants = (os.environ.get("SHEETS_PRUNE_KEEP_DASHBOARD_VARIANTS", "0") or "0").strip() == "1"
        if keep_variants:
            for t in list(self._sheet_id_by_title.keys()):
                if str(t).startswith("看板_方案"):
                    keep.add(str(t))

        if keep_symbol_tabs is not None:
            for t in keep_symbol_tabs:
                if t:
                    keep.add(str(t).strip())
        else:
            pref = (symbol_tab_prefix or "").strip()
            for t in list(self._sheet_id_by_title.keys()):
                if pref and str(t).startswith(pref):
                    keep.add(str(t))

        delete_ids: list[int] = []
        for title, sid in self._sheet_id_by_title.items():
            if title not in keep:
                delete_ids.append(int(sid))

        if not delete_ids:
            if minimal_throttle:
                try:
                    self._local_meta_set({"prune_tabs_last_error": ""})
                except Exception:
                    pass
            return {"deleted": 0, "kept": sorted(keep)}

        reqs = [{"deleteSheet": {"sheetId": int(sid)}} for sid in delete_ids]
        try:
            self._exec(
                self._sheets.spreadsheets().batchUpdate(
                    spreadsheetId=self._spreadsheet_id,
                    body={"requests": reqs},
                ),
                is_write=True,
            )
            self._refresh_sheet_map()
            if minimal_throttle:
                try:
                    self._local_meta_set({"prune_tabs_last_error": ""})
                except Exception:
                    pass
            return {"deleted": len(delete_ids), "kept": sorted(keep)}
        except Exception as exc:
            if minimal_throttle:
                try:
                    self._local_meta_set({"prune_tabs_last_error": f"{type(exc).__name__}:{exc}"[:2000]})
                except Exception:
                    pass
                return {"deleted": 0, "kept": sorted(keep), "ok": False, "error": f"{type(exc).__name__}:{exc}"}
            raise

    def delete_tab_if_exists(self, *, title: str) -> dict[str, Any]:
        """
        精确删除一个 tab（按 title 精确匹配）。

        设计目的：
        - 避免用户只想删一个 tab，却不得不执行 prune_tabs 导致其他 tab 也被删除。
        - 用于运维“即时清理”：例如删除 Polymarket事件（高频明细）后不再重建。
        """
        t = (title or "").strip()
        if not t:
            raise RuntimeError("missing_title")

        # 防呆：禁止误删核心 tab
        if t in {
            self._tab_dashboard,
            self._tab_dashboard_data,
            self._tab_dashboard_history,
            self._tab_dashboard_meta,
        }:
            raise RuntimeError(f"refuse_delete_core_tab:{t}")

        self._refresh_sheet_map()
        sid = self._sheet_id_by_title.get(t)
        if sid is None:
            return {"deleted": 0, "title": t}

        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": [{"deleteSheet": {"sheetId": int(sid)}}]},
            ),
            is_write=True,
        )
        self._refresh_sheet_map()
        return {"deleted": 1, "title": t}

    def _dashboard_insert_rows(self, *, y: int, reserved_height: int, delta: int, meta: dict[str, str]) -> None:
        """
        replace 模式扩容：
        - 在看板 sheet 中插入 delta 行，使得当前 card_type 的槽位可以增长而不覆盖下方卡片
        - 将所有 slot.*.y（在当前卡片下方的）与 dashboard_next_row 同步下移 delta
        """
        if delta <= 0:
            return

        insert_at = int(y) + int(reserved_height)  # 在槽位末尾下一行前插入

        sh_id = self._sheet_id_by_title.get(self._tab_dashboard)
        if sh_id is None:
            self._refresh_sheet_map()
            sh_id = self._sheet_id_by_title[self._tab_dashboard]

        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={
                    "requests": [
                        {
                            "insertDimension": {
                                "range": {
                                    "sheetId": int(sh_id),
                                    "dimension": "ROWS",
                                    "startIndex": int(insert_at) - 1,
                                    "endIndex": int(insert_at) - 1 + int(delta),
                                },
                                "inheritFromBefore": False,
                            }
                        }
                    ]
                },
            ),
            is_write=True,
        )
        # refresh grid cache（rowCount 变化）
        self._refresh_sheet_map()

        # 更新 meta：所有 y > 当前 y 的 slot 下移
        kv: dict[str, str] = {}
        for k, v in meta.items():
            if not (k.startswith("slot.") and k.endswith(".y")):
                continue
            try:
                vy = int(str(v).strip() or "0")
            except Exception:
                continue
            if vy > int(y):
                kv[k] = str(vy + int(delta))

        try:
            dn = int(str(meta.get("dashboard_next_row") or "1").strip() or "1")
        except Exception:
            dn = 1
        kv["dashboard_next_row"] = str(dn + int(delta))
        self._meta_set(kv)

    def _clear_dashboard_slot(self, *, y: int, slot_height: int, col_l: str, col_r: str) -> None:
        """
        看板覆盖写入前的“硬清理”：
        - 清空值（避免上一轮残留）
        - 解除合并（避免 merge 叠加导致 API 报错或版式错乱）
        """
        y0 = int(y)
        h = max(int(slot_height), 1)
        y1 = y0 + h - 1

        self._exec(
            self._sheets.spreadsheets()
            .values()
            .clear(
                spreadsheetId=self._spreadsheet_id,
                range=f"{self._tab_dashboard}!{col_l}{y0}:{col_r}{y1}",
            ),
            is_write=True,
        )

        sh_id = self._sheet_id_by_title.get(self._tab_dashboard)
        if sh_id is None:
            self._refresh_sheet_map()
            sh_id = self._sheet_id_by_title[self._tab_dashboard]

        col_r_idx = _col_to_index(col_r)
        # unmergeCells 必须覆盖“完整 merged range”，否则会 400：
        # - 历史上 dashboard 可能用更宽的 col_r（例如 CU），导致 merge 范围超出当前 col_r
        # - 因此这里对行范围按 slot 精确裁剪，但列范围覆盖整个 sheet 的已分配列数
        _rc, sheet_cols = self._grid_by_title.get(self._tab_dashboard, (0, 0))
        end_col = int(max(sheet_cols or 0, col_r_idx))
        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={
                    "requests": [
                        {
                            "unmergeCells": {
                                "range": {
                                    "sheetId": int(sh_id),
                                    "startRowIndex": y0 - 1,
                                    "endRowIndex": y1,
                                    "startColumnIndex": 0,
                                    "endColumnIndex": end_col,
                                }
                            }
                        }
                    ]
                },
            ),
            is_write=True,
        )

    def _calc_dashboard_height(self, payload: dict[str, Any], *, col_l: str, col_r: str) -> int:
        """
        计算卡片块高度（用于 y 指针推进）。
        - 支持“超宽字段分块”：columns 超出固定宽度时，按列块拆成多段子表
        - height 口径：包含底部 1 行空行分隔
        """
        col_l_idx = _col_to_index(col_l)
        col_r_idx = _col_to_index(col_r)
        width = col_r_idx - col_l_idx + 1
        if width <= 0:
            raise RuntimeError("invalid_dashboard_col_range")

        table = payload.get("table") or {}
        columns = table.get("columns") or []
        rows = table.get("rows") or []
        rows_cnt = len(rows)
        cols_cnt = len(columns)
        has_period_suffix = any("@" in str(c) for c in columns if c is not None)
        header_rows = 2 if has_period_suffix else 1

        # chunks = max(1, ceil(cols_cnt/width))
        chunks = max(1, (cols_cnt + width - 1) // width)
        # 固定源信息1行 + 每块(header_rows + 明细N行)*chunks + blank=1行
        return chunks * (rows_cnt + int(header_rows)) + 2

    # ==================== facts writers ====================
    def _append_cards_index(self, payload: dict[str, Any], dash: dict[str, Any]) -> None:
        header = payload.get("header") or {}
        params = payload.get("params") or {}
        tg = payload.get("tg") or {}

        row = [
            str(payload.get("card_key") or ""),
            str(payload.get("ts_utc") or ""),
            str(payload.get("source_service") or ""),
            str(payload.get("card_type") or ""),
            str(header.get("title") or ""),
            str(header.get("update_time") or ""),
            str(header.get("sort_desc") or ""),
            str(params.get("last_update") or ""),
            str(tg.get("url") or ""),
            str(dash.get("sheet") or ""),
            str(dash.get("col_l") or ""),
            str(dash.get("col_r") or ""),
            str(dash.get("row_y") or ""),
            str(dash.get("height") or ""),
        ]

        self._exec(
            self._sheets.spreadsheets()
            .values()
            .append(
                spreadsheetId=self._spreadsheet_id,
                range=f"{self._tab_cards_index}!A1",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]},
            ),
            is_write=True,
        )

    def _append_card_fields_eav(self, payload: dict[str, Any]) -> None:
        card_key = str(payload.get("card_key") or "")
        rows: list[list[str]] = []
        for path, vtype, vtext in _flatten_eav("", payload):
            rows.append([card_key, path, vtext, vtype])
        self._append_rows(f"{self._tab_card_fields_eav}!A1", rows)

    def _append_rows_eav(self, payload: dict[str, Any]) -> None:
        card_key = str(payload.get("card_key") or "")
        table = payload.get("table") or {}
        rows = table.get("rows") or []
        if not rows:
            return

        card_rows: list[list[str]] = []
        eav_rows: list[list[str]] = []
        for idx, row_obj in enumerate(rows, start=1):
            row_obj = row_obj or {}
            row_key = ""
            for k in ("币种", "symbol", "Symbol"):
                if k in row_obj and row_obj.get(k) is not None:
                    row_key = str(row_obj.get(k))
                    break
            card_rows.append(
                [
                    card_key,
                    str(idx),
                    row_key,
                    json.dumps(row_obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
                ]
            )

            for path, vtype, vtext in _flatten_eav("", row_obj):
                eav_rows.append([card_key, str(idx), path, vtext, vtype])

        self._append_rows(f"{self._tab_card_rows}!A1", card_rows)
        self._append_rows(f"{self._tab_row_fields_eav}!A1", eav_rows)

    def _append_rows(self, range_a1: str, rows: list[list[str]], *, chunk: int = 500) -> None:
        if not rows:
            return
        for i in range(0, len(rows), chunk):
            part = rows[i : i + chunk]
            self._exec(
                self._sheets.spreadsheets()
                .values()
                .append(
                    spreadsheetId=self._spreadsheet_id,
                    range=range_a1,
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": part},
                ),
                is_write=True,
            )

    # ==================== blobs ====================
    def _maybe_blob(self, payload: dict[str, Any]) -> None:
        raw = payload.get("raw") or {}
        if not isinstance(raw, dict):
            return

        if self._blob_threshold_chars <= 0:
            return

        created_at = _now_utc_iso()
        card_key = str(payload.get("card_key") or "")

        def put_text(blob_key: str, text: str, mime: str) -> dict[str, Any]:
            url = self._drive_put_text(
                filename=f"tg_{blob_key.replace(':', '_')}",
                text=text,
                mime=mime,
            )
            sha = _sha256_hex(text)
            self._exec(
                self._sheets.spreadsheets()
                .values()
                .append(
                    spreadsheetId=self._spreadsheet_id,
                    range=f"{self._tab_blobs_index}!A1",
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": [[card_key, blob_key, sha, mime, url, str(len(text)), created_at]]},
                ),
                is_write=True,
            )
            return {"blob_url": url, "sha256": sha, "size_chars": len(text)}

        # telegram_text_full
        v = raw.get("telegram_text_full")
        if v is not None and isinstance(v, str) and len(v) > self._blob_threshold_chars:
            raw["telegram_text_full"] = put_text("raw.telegram_text_full", v, "text/plain")

        # payload_json_full
        j = raw.get("payload_json_full")
        if j is not None:
            s = j if isinstance(j, str) else json.dumps(j, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            if len(s) > self._blob_threshold_chars:
                raw["payload_json_full"] = put_text("raw.payload_json_full", s, "application/json")

        payload["raw"] = raw

    def _drive_put_text(self, *, filename: str, text: str, mime: str) -> str:
        from googleapiclient.http import MediaInMemoryUpload  # type: ignore

        media = MediaInMemoryUpload(text.encode("utf-8"), mimetype=mime, resumable=False)
        meta: dict[str, Any] = {"name": filename}
        if self._drive_folder_id:
            meta["parents"] = [self._drive_folder_id]

        file = self._exec(
            self._drive.files().create(body=meta, media_body=media, fields="id,webViewLink"), is_write=True
        )
        file_id = file["id"]

        # “公共看板”默认策略：知道链接即可读
        self._exec(
            self._drive.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
                fields="id",
            ),
            is_write=True,
        )

        return str(file.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view")

    # ==================== dashboard render ====================
    def _render_dashboard(self, payload: dict[str, Any], *, y: int, col_l: str, col_r: str) -> None:
        col_l_idx = _col_to_index(col_l)
        col_r_idx = _col_to_index(col_r)
        width = col_r_idx - col_l_idx + 1
        if width <= 0:
            raise RuntimeError("invalid_dashboard_col_range")

        header = payload.get("header") or {}
        hint = payload.get("hint") or {}
        params = payload.get("params") or {}
        table = payload.get("table") or {}
        columns = table.get("columns") or []
        rows = table.get("rows") or []

        title = str(header.get("title") or "")
        update_time = str(header.get("update_time") or "-").strip() or "-"
        sort_desc = str(header.get("sort_desc") or "-").strip() or "-"
        hint_text = str(hint.get("text") or "-").strip() or "-"
        last_update = str(params.get("last_update") or "-").strip() or "-"

        # 源信息压缩（用户要求）：固定顺序拼接进同一单元格
        def one_line(s: str) -> str:
            return re.sub(r"\\s+", " ", str(s or "").strip()).strip() or "-"

        info_line = " ".join(
            [
                f"📊 {one_line(title)}",
                f"⏰ 更新 {one_line(update_time)}",
                f"📊 排序 {one_line(sort_desc)}",
                f"💡 {one_line(hint_text)}",
                f"⏰ 最后更新 {one_line(last_update)}",
            ]
        )

        def pad_row(first: str) -> list[str]:
            return [first] + [""] * (width - 1)

        value_rows: list[tuple[str, list[list[str]]]] = []
        value_rows.append((f"{self._tab_dashboard}!{col_l}{y}:{col_r}{y}", [pad_row(info_line)]))

        # 超宽字段：按固定宽度分块渲染（不截断列）
        chunks = [columns[i : i + width] for i in range(0, len(columns), width)] if columns else [[]]

        table_y = y + 1
        for chunk_cols in chunks:
            # header（两行）：字段组行 + 周期行
            group_row = [_parse_field_group(str(c)) for c in chunk_cols]
            period_row = [_parse_period_suffix(str(c)) for c in chunk_cols]
            group_row = group_row + [""] * (width - len(group_row))
            period_row = period_row + [""] * (width - len(period_row))
            value_rows.append((f"{self._tab_dashboard}!{col_l}{table_y}:{col_r}{table_y}", [group_row]))
            value_rows.append((f"{self._tab_dashboard}!{col_l}{table_y + 1}:{col_r}{table_y + 1}", [period_row]))

            # body（从 table_y+2 开始）
            if rows:
                body_vals: list[list[str]] = []
                for r in rows:
                    line: list[str] = []
                    for c in chunk_cols:
                        line.append("" if r.get(c) is None else str(r.get(c)))
                    line = line + [""] * (width - len(line))
                    body_vals.append(line)
                y0 = table_y + 2
                y1 = table_y + 1 + len(body_vals)
                value_rows.append((f"{self._tab_dashboard}!{col_l}{y0}:{col_r}{y1}", body_vals))

            table_y += 2 + len(rows)

        # 兼容：不再渲染独立 hint/last 行（已压缩进 info_line）
        # 保持 table_y 推进逻辑不变；底部空行由 height 预留但不写值。

        # values batchUpdate
        data = [{"range": rng, "values": vals} for rng, vals in value_rows]
        self._exec(
            self._sheets.spreadsheets()
            .values()
            .batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"valueInputOption": "RAW", "data": data},
            ),
            is_write=True,
        )

        # merges + formats
        sh_id = self._sheet_id_by_title.get(self._tab_dashboard)
        if sh_id is None:
            self._refresh_sheet_map()
            sh_id = self._sheet_id_by_title[self._tab_dashboard]

        # ---------- formats ----------
        # 颜色策略：
        # - 表头行：浅灰底 + 加粗（按周期列块做灰白分带，便于阅读）
        # - 表体：按周期列块灰白交替
        # - 源信息行：整行浅底
        bg_title = _rgb(0.93, 0.93, 0.93)
        bg_body_even = _rgb(0.96, 0.96, 0.96)  # 灰
        bg_body_odd = _rgb(1.0, 1.0, 1.0)  # 白
        # 表头统一底色（不随周期变化）；周期分带只作用于表体，避免“表头花里胡哨”影响读字段名
        bg_hdr_group = _rgb(0.88, 0.88, 0.88)  # 字段组行（略深）
        bg_hdr_period = _rgb(0.92, 0.92, 0.92)  # 周期行（略浅）

        def rrange(*, r0: int, r1: int, c0: int, c1: int) -> dict[str, Any]:
            return {
                "sheetId": int(sh_id),
                "startRowIndex": int(r0),
                "endRowIndex": int(r1),
                "startColumnIndex": int(c0),
                "endColumnIndex": int(c1),
            }

        col_l0 = col_l_idx - 1
        col_r1 = col_r_idx

        def repeat_bg(*, row: int, bg: dict[str, float]) -> dict[str, Any]:
            return {
                "repeatCell": {
                    "range": rrange(r0=row - 1, r1=row, c0=col_l0, c1=col_r1),
                    "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                    "fields": "userEnteredFormat.backgroundColor",
                }
            }

        requests: list[dict[str, Any]] = []

        # 源信息行背景 + 加粗
        requests.append(repeat_bg(row=y, bg=bg_title))
        requests.append(
            {
                "repeatCell": {
                    "range": rrange(r0=y - 1, r1=y, c0=col_l0, c1=col_r1),
                    "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                    "fields": "userEnteredFormat.textFormat.bold",
                }
            }
        )

        # 表头/表体：按 chunk 逐段上色（chunk 是纵向堆叠，不影响列下标）
        table_y = y + 1
        for chunk_cols in chunks:
            # header rows style（bold+居中）
            requests.append(
                {
                    "repeatCell": {
                        "range": rrange(r0=table_y - 1, r1=table_y + 1, c0=col_l0, c1=col_r1),
                        "cell": {
                            "userEnteredFormat": {
                                "textFormat": {"bold": True},
                                "horizontalAlignment": "CENTER",
                                "verticalAlignment": "MIDDLE",
                                "wrapStrategy": "WRAP",
                            }
                        },
                        "fields": "userEnteredFormat(textFormat.bold,horizontalAlignment,verticalAlignment,wrapStrategy)",
                    }
                }
            )

            # 计算每列所属周期（出现顺序 -> 交替灰白）
            period_order: list[str] = []
            period_index: dict[str, int] = {}
            period_by_col: list[str] = []
            for c in chunk_cols + [""] * (width - len(chunk_cols)):
                suf = _parse_period_suffix(str(c))
                if suf and suf not in period_index:
                    period_index[suf] = len(period_order)
                    period_order.append(suf)
                period_by_col.append(suf)

            def col_bg(suf: str, *, _period_index: dict[str, int] = period_index) -> dict[str, float]:
                if not suf:
                    return bg_body_odd
                idx = int(_period_index.get(suf, 0))
                if idx % 2 == 0:
                    return bg_body_even
                return bg_body_odd

            body_bgs = [col_bg(suf) for suf in period_by_col]

            def add_bg_segments(*, row0: int, row1: int, bgs: list[dict[str, float]]) -> None:
                start = 0
                while start < width:
                    bg = bgs[start]
                    end = start + 1
                    while end < width and bgs[end] == bg:
                        end += 1
                    requests.append(
                        {
                            "repeatCell": {
                                "range": rrange(r0=row0, r1=row1, c0=col_l0 + start, c1=col_l0 + end),
                                "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                                "fields": "userEnteredFormat.backgroundColor",
                            }
                        }
                    )
                    start = end

            def add_field_group_separators(*, row0: int, row1: int, _cols: list[str] = chunk_cols) -> None:
                # 在“字段组”之间加竖线分隔：对每个新字段组的第一列，加 left border。
                sep_color = _rgb(0.70, 0.70, 0.70)
                border = {"style": "SOLID_MEDIUM", "width": 2, "color": sep_color}
                last_group = ""
                for idx, c in enumerate(list(_cols) + [""] * (width - len(_cols))):
                    g = _parse_field_group(str(c))
                    if not g:
                        continue
                    if last_group and g != last_group:
                        requests.append(
                            {
                                "updateBorders": {
                                    "range": rrange(r0=row0, r1=row1, c0=col_l0 + idx, c1=col_l0 + idx + 1),
                                    "left": border,
                                }
                            }
                        )
                    last_group = g

            # header 背景（两行）
            requests.append(
                {
                    "repeatCell": {
                        "range": rrange(r0=table_y - 1, r1=table_y, c0=col_l0, c1=col_r1),
                        "cell": {"userEnteredFormat": {"backgroundColor": bg_hdr_group}},
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                }
            )
            requests.append(
                {
                    "repeatCell": {
                        "range": rrange(r0=table_y, r1=table_y + 1, c0=col_l0, c1=col_r1),
                        "cell": {"userEnteredFormat": {"backgroundColor": bg_hdr_period}},
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                }
            )
            # body 背景（分段）
            if rows:
                body_r0 = table_y + 1  # = (table_y+2)-1
                body_r1 = table_y + 1 + len(rows)
                add_bg_segments(row0=body_r0, row1=body_r1, bgs=body_bgs)
                # 字段组竖线分隔（覆盖 header+body）
                add_field_group_separators(row0=table_y - 1, row1=body_r1)

            # 字段组表头行：按字段名做 merge（提升可读性）
            group_names = [_parse_field_group(str(c)) for c in chunk_cols] + [""] * (width - len(chunk_cols))
            start = 0
            while start < width:
                g = group_names[start]
                end = start + 1
                while end < width and group_names[end] == g:
                    end += 1
                if g and end - start >= 2:
                    requests.append(
                        {
                            "mergeCells": {
                                "range": rrange(
                                    r0=table_y - 1,
                                    r1=table_y,
                                    c0=col_l0 + start,
                                    c1=col_l0 + end,
                                ),
                                "mergeType": "MERGE_ALL",
                            }
                        }
                    )
                start = end

            table_y += 2 + len(rows)

        # 源信息行合并（整行）
        requests.append(
            {
                "mergeCells": {
                    "range": {
                        "sheetId": sh_id,
                        "startRowIndex": y - 1,
                        "endRowIndex": y,
                        "startColumnIndex": col_l_idx - 1,
                        "endColumnIndex": col_r_idx,
                    },
                    "mergeType": "MERGE_ALL",
                }
            }
        )
        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": requests},
            ),
            is_write=True,
        )
