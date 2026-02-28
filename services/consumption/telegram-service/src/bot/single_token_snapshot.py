"""单币种快照表格渲染

目标：最小新增代码、最大复用现有数据提供层，支持：
- 基础/合约/高级三面板
- 周期列可开关，表头固定（字段\周期 5m 15m 1h 4h 1d 1w）
- 等宽对齐：首列左对齐，其余右对齐（沿用 docs/数据对齐.md 算法）

注意：本文件只负责数据聚合与文本渲染，不修改消息路由。
数据源：PostgreSQL 指标库（`DATABASE_URL` → `tg_cards.*`）。
"""

from __future__ import annotations

import math
import os
import unicodedata
from typing import Dict, List, Literal, Sequence, Tuple
try:
    from wcwidth import wcswidth  # 更精确的终端宽度计算（兼容 emoji/组合字符）
except ImportError:  # 可选依赖，缺失时回退原逻辑
    wcswidth = None

from cards.data_provider import format_symbol, get_ranking_provider
from cards.i18n import gettext as _t, resolve_lang, translate_field, translate_value

# ==================== 配置 ====================

# 周期集合；合约面板强制忽略 1m
ALL_PERIODS: Tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h", "1d", "1w")
FUTURES_PERIODS: Tuple[str, ...] = ("5m", "15m", "1h", "4h", "1d", "1w")

# 面板类型
PanelType = Literal["basic", "futures", "advanced"]

# 数据源白名单：表名 -> 候选数值字段（按优先顺序选第一个可用）
# 字段名严格对齐各卡片的 col_id，避免错名导致空值。
# 注意：期货面板已精简，避免同一表的字段重复显示
TABLE_FIELDS: Dict[PanelType, Dict[str, Sequence[Tuple[str, str]]]] = {
    "basic": {
        # 布林带
        "布林带排行卡片": (
            ("bandwidth", "带宽"),
            ("百分比b", "百分比"),
            ("中轨斜率", "中轨斜率"),
            ("中轨价格", "中轨价格"),
            ("上轨价格", "上轨价格"),
            ("下轨价格", "下轨价格"),
        ),
        # 成交量比率
        "成交量比率排行卡片": (("量比", "量比"), ("信号概述", "信号概述")),
        # 支撑阻力
        "支撑阻力排行卡片": (
            ("支撑位", "支撑位"),
            ("阻力位", "阻力位"),
            ("ATR", "ATR"),
            ("距支撑百分比", "距支撑%"),
            ("距阻力百分比", "距阻力%"),
            ("距关键位百分比", "距关键位%"),
        ),
        # 主动买卖比
        "主动买卖比排行卡片": (
            ("主动买量", "主动买量"),
            ("主动卖量", "主动卖量"),
            ("主动买卖比", "主动买卖比"),
        ),
        # KDJ
        "KDJ排行卡片": (("J值", "J"), ("K值", "K"), ("D值", "D"), ("信号概述", "方向")),
        # MACD
        "MACD柱状排行卡片": (
            ("MACD", "MACD"),
            ("DIF", "DIF"),
            ("DEA", "DEA"),
            ("MACD柱状图", "柱状图"),
            ("信号概述", "信号"),
        ),
        # OBV
        "OBV排行卡片": (("OBV值", "OBV值"), ("OBV变化率", "OBV变化率")),
        # RSI谐波
        "RSI谐波排行卡片": (("谐波值", "谐波值"),),
    },
    "futures": {
        # 期货面板：所有字段来自期货情绪聚合表，按逻辑分组展示（无重复）
        # 持仓数据
        "持仓数据": (
            ("持仓金额", "持仓金额"),
            ("持仓张数", "持仓张数"),
            ("持仓变动%", "持仓变动%"),
            ("持仓变动", "持仓变动"),
            ("持仓斜率", "持仓斜率"),
            ("持仓Z分数", "Z分数"),
            ("OI连续根数", "OI连续根数"),
        ),
        # 大户情绪
        "大户情绪": (
            ("大户多空比", "大户多空比"),
            ("大户偏离", "大户偏离"),
            ("大户情绪动量", "大户动量"),
            ("大户波动", "大户波动"),
        ),
        # 全市场情绪
        "全市场情绪": (
            ("全体多空比", "全体多空比"),
            ("全体偏离", "全体偏离"),
            ("全体波动", "全体波动"),
        ),
        # 主动成交
        "主动成交": (
            ("主动成交多空比", "主动多空比"),
            ("主动偏离", "主动偏离"),
            ("主动情绪动量", "主动动量"),
            ("主动跳变幅度", "主动跳变"),
            ("主动连续根数", "主动连续"),
        ),
        # 情绪综合
        "情绪综合": (
            ("情绪差值", "情绪差值"),
            ("情绪翻转信号", "翻转信号"),
            ("波动率", "波动率"),
            ("风险分", "风险分"),
            ("市场占比", "市场占比"),
        ),
    },
    "advanced": {
        "EMA排行卡片": (
            ("EMA7", "EMA7"),
            ("EMA25", "EMA25"),
            ("EMA99", "EMA99"),
            ("带宽评分", "带宽评分"),
            ("趋势方向", "趋势方向"),
            ("价格", "价格"),
        ),
        # K线形态已移至独立按钮界面，不在表格中显示
        "VPVR排行卡片": (
            ("VPVR价格", "VPVR价"),
            ("价值区下沿", "价值区下沿"),
            ("价值区上沿", "价值区上沿"),
            ("价值区宽度百分比", "价值区宽度%"),
            ("价值区覆盖率", "价值区覆盖率"),
            ("价值区位置", "价值区位置"),
        ),
        "VWAP排行卡片": (
            ("偏离度", "偏离度"),
            ("偏离百分比", "偏离%"),
            ("成交量加权", "加权成交额"),
            ("VWAP带宽百分比", "带宽%"),
            ("VWAP上轨", "上轨"),
            ("VWAP下轨", "下轨"),
            ("VWAP价格", "VWAP价格"),
            ("当前价格", "当前价格"),
        ),
        "趋势线排行卡片": (("趋势方向", "趋势方向"), ("距离趋势线%", "距离%")),
        "ATR排行卡片": (("ATR百分比", "ATR%"), ("波动分类", "波动"), ("上轨", "上轨"), ("中轨", "中轨"), ("下轨", "下轨"), ("当前价格", "价格")),
        "CVD排行卡片": (("CVD值", "CVD值"), ("变化率", "变化率")),
        "超级精准趋势排行卡片": (
            ("趋势强度", "趋势强度"),
            ("趋势持续根数", "持续根数"),
            ("趋势方向", "方向"),
            ("量能偏向", "量能偏向"),
            ("趋势带", "趋势带"),
            ("最近翻转时间", "最近翻转时间"),
        ),
        "MFI排行卡片": (("MFI值", "MFI"),),
        "流动性排行卡片": (
            ("流动性得分", "流动性得分"),
            ("流动性等级", "流动性等级"),
            ("Amihud得分", "Amihud得分"),
            ("Kyle得分", "Kyle得分"),
            ("波动率得分", "波动率得分"),
            ("成交量得分", "成交量得分"),
            ("Amihud原值", "Amihud原值"),
            ("Kyle原值", "Kyle原值"),
        ),
    },
}

# 表名别名映射：卡片名 -> 实际数据表名
TABLE_ALIAS: Dict[PanelType, Dict[str, str]] = {
    "basic": {
        "布林带排行卡片": "布林带扫描器",
        "成交量比率排行卡片": "成交量比率扫描器",
        "支撑阻力排行卡片": "全量支撑阻力扫描器",
        "主动买卖比排行卡片": "主动买卖比扫描器",
        "KDJ排行卡片": "KDJ随机指标扫描器",
        "MACD柱状排行卡片": "MACD柱状扫描器",
        "OBV排行卡片": "OBV能量潮扫描器",
        "RSI谐波排行卡片": "谐波信号扫描器",
    },
    "futures": {
        # 期货面板：所有分组都映射到期货情绪聚合表
        "持仓数据": "期货情绪聚合表",
        "大户情绪": "期货情绪聚合表",
        "全市场情绪": "期货情绪聚合表",
        "主动成交": "期货情绪聚合表",
        "情绪综合": "期货情绪聚合表",
    },
    "advanced": {
        "ATR排行卡片": "ATR波幅扫描器",
        "CVD排行卡片": "CVD信号排行榜",
        "EMA排行卡片": "G，C点扫描器",
        "K线形态排行卡片": "K线形态扫描器",
        "MFI排行卡片": "MFI资金流量扫描器",
        "VPVR排行卡片": "VPVR排行生成器",
        "VWAP排行卡片": "VWAP离线信号扫描",
        "流动性排行卡片": "流动性扫描器",
        "超级精准趋势排行卡片": "超级精准趋势扫描器",
        "趋势线排行卡片": "趋势线榜单",
    },
}

# 百分比字段关键字（小写匹配）
PERCENT_FIELD_KEYWORDS = ["ratio", "percent", "%", "rate", "资金费率", "比", "百分", "率", "偏离"]

# 自动探测时忽略的字段
IGNORE_FIELDS = {
    "symbol", "交易对", "币种", "数据时间", "周期", "price", "quote_volume", "change_percent",
    "updated_at", "timestamp", "bucket_ts", "market", "interval"
}

# 从环境变量读取屏蔽字段（逗号分隔）
def _get_hidden_fields() -> set:
    """获取需要屏蔽的字段（从 SNAPSHOT_HIDDEN_FIELDS 环境变量）"""
    hidden = os.environ.get("SNAPSHOT_HIDDEN_FIELDS", "")
    if not hidden:
        return set()
    return {f.strip() for f in hidden.split(",") if f.strip()}


def _disp_width(text: str) -> int:
    """字符串显示宽度（ASCII=1，宽字符=2），优先使用 wcwidth 精确计算。"""
    if text is None:
        return 0
    s = str(text)
    if wcswidth:
        w = wcswidth(s)
        if w >= 0:
            return w
    # 回退：东亚宽度估算
    w = 0
    for ch in s:
        w += 2 if unicodedata.east_asian_width(ch) in {"F", "W"} else 1
    return w


def align_rows(rows: List[List[str]], left_cols: int = 0) -> List[str]:
    """等宽对齐表格。rows 是二维字符串数组，返回每行字符串。"""
    if not rows:
        return []
    # 计算每列宽度
    col_w: List[int] = []
    for row in rows:
        for i, cell in enumerate(row):
            disp = _disp_width(cell)
            if i >= len(col_w):
                col_w.append(disp)
            else:
                col_w[i] = max(col_w[i], disp)

    # 组装
    aligned: List[str] = []
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            w = col_w[i]
            pad = w - _disp_width(cell)
            if i < left_cols:
                cells.append(cell + " " * pad)
            else:
                cells.append(" " * pad + cell)
        aligned.append(" ".join(cells))
    return aligned


def abbreviate_number(val: float) -> str:
    """金额类缩写，便于表格紧凑。"""
    if val is None or math.isnan(val):
        return ""
    abs_v = abs(val)
    suffixes = [(1e9, "B"), (1e6, "M"), (1e3, "K")]
    for base, suf in suffixes:
        if abs_v >= base:
            return f"{val/base:.2f}{suf}".rstrip("0").rstrip(".")
    return format_float(val)


def format_value(val: object) -> str:
    """数字 → 字符串；None → —；百分比自动%。"""
    if val is None:
        return ""
    if isinstance(val, (int, float)):
        if abs(val) < 1e-6:
            return "0"
        return f"{val:.4f}%"
    return str(val)


# ==================== 主渲染类 ====================


class SingleTokenSnapshot:
    """单币种快照：动态扫描数据源并输出表格。"""

    def __init__(self) -> None:
        self.provider = get_ranking_provider()
        # 渲染级缓存：表/周期 → 全表 + 索引
        self._data_cache: dict[tuple[str, str], list[dict]] = {}
        self._index_cache: dict[tuple[str, str], dict[str, dict]] = {}
        self._target_sym: str = ""

    def render_table(
        self,
        symbol: str,
        panel: PanelType,
        enabled_periods: Dict[str, bool] | None = None,
        enabled_cards: Dict[str, bool] | None = None,
        page: int = 0,
        max_lines: int = 40,
        max_chars: int = 4000,
        lang: str | None = None,
    ) -> tuple[str, int]:
        """渲染指定面板的表格文本（含表头 + 代码块对齐内容）。

        返回 (text, total_pages)，用于外层按钮分页。
        """
        self._data_cache.clear()
        self._index_cache.clear()
        self._target_sym = format_symbol(symbol)
        lang = resolve_lang(lang=lang)
        self._lang = lang  # 保存语言设置供 _fetch_table_value 使用
        if not self._target_sym:
            return _t("snapshot.error.no_symbol", lang=lang), 1

        periods = FUTURES_PERIODS if panel == "futures" else ALL_PERIODS
        enabled = enabled_periods or {p: True for p in periods}
        columns = [p for p in periods if enabled.get(p, False)]
        if not columns:
            return _t("snapshot.error.no_period", lang=lang), 1

        enabled_cards = enabled_cards or {}
        header = [_t("snapshot.header.field", lang=lang)] + columns
        rows: List[List[str]] = []
        table_field_map = TABLE_FIELDS.get(panel, {})
        hidden_fields = _get_hidden_fields()

        # 组装数据行：按表 -> 字段 -> 周期
        for table in self._discover_tables(panel):
            if enabled_cards and not enabled_cards.get(table, True):
                continue
            fields = list(table_field_map.get(table, ()))
            sample_row = self._get_row(table, columns[0], panel)
            if not fields:
                fields = self._auto_fields(sample_row)
            if not fields:
                continue

            for field in fields:
                col_id, label = field
                # 跳过屏蔽字段
                if col_id in hidden_fields or label in hidden_fields:
                    continue
                # 翻译字段标签
                translated_label = translate_field(label, lang=lang)
                row = [translated_label]
                for period in columns:
                    row.append(self._fetch_table_value(table, period, (col_id,), panel))
                rows.append(row)

        aligned = align_rows([header] + rows, left_cols=1)
        title = {
            "basic": _t("snapshot.title.basic", lang=lang, symbol=self._target_sym),
            "futures": _t("snapshot.title.futures", lang=lang, symbol=self._target_sym),
            "advanced": _t("snapshot.title.advanced", lang=lang, symbol=self._target_sym),
        }.get(panel, _t("snapshot.title.default", lang=lang, symbol=self._target_sym))
        header_line = _t("snapshot.header.compact", lang=lang, columns="/".join(columns))
        body_lines = aligned[1:]
        if not body_lines:
            body_lines = [_t("data.no_data", lang=lang)]

        # 分页：优先按字符数防止超 4096 长度，再兜底按行数
        if max_lines <= 0:
            max_lines = 40
        if max_chars <= 0:
            max_chars = 3500

        pages_list: List[List[str]] = []
        cur: List[str] = []
        cur_len = 0
        overhead = len(title) + len(header_line) + len("```\n\n```\n") + 200  # 预估 footer 和格式字符

        for line in body_lines:
            line_len = len(line) + 1
            if cur and (cur_len + line_len + overhead > max_chars or len(cur) >= max_lines):
                pages_list.append(cur)
                cur = [line]
                cur_len = line_len
            else:
                cur.append(line)
                cur_len += line_len
        if cur:
            pages_list.append(cur)

        total_pages = max(len(pages_list), 1)
        page = max(0, min(page, total_pages - 1))
        page_body = "\n".join(pages_list[page]) if pages_list else _t("data.no_data", lang=lang)

        footer_parts = [
            _t("snapshot.footer.hint", lang=lang),
            _t("snapshot.footer.page", lang=lang, current=page + 1, total=total_pages),
        ]
        footer = "\n".join(footer_parts)
        return f"{title}\n{header_line}\n```\n{page_body}\n```\n{footer}", total_pages

    # ---------- 内部 ----------
    def _discover_tables(self, panel: PanelType) -> List[str]:
        """返回面板对应的表名列表：仅使用静态映射，避免误匹配导致空行。"""
        return list(TABLE_FIELDS.get(panel, {}).keys())

    def _fetch_table_value(
        self,
        table: str,
        period: str,
        fields: Sequence[str],
        panel: PanelType,
    ) -> str:
        """从 provider 中取一个字段值并格式化."""
        base_table = TABLE_ALIAS.get(panel, {}).get(table, table)
        idx = self._index_cache.get((base_table, period))
        if idx is None:
            self._get_table_data(base_table, period)
            idx = self._index_cache.get((base_table, period), {})

        item = idx.get(self._target_sym)
        if not item:
            return ""

        for field in fields:
            if field in item and item[field] not in (None, "", []):
                val = item[field]
                # 尝试把数字字符串转 float
                if isinstance(val, str):
                    try:
                        val = float(val)
                    except ValueError:
                        # 字符串值需要翻译（如 "缩量"、"金叉" 等）
                        return translate_value(val, lang=self._lang)
                if isinstance(val, (int, float)):
                    field_l = field.lower().replace("%", "")
                    # 排除斜率等非百分比字段
                    is_slope = "斜率" in field
                    is_percent = not is_slope and any(k in field_l for k in (kw.lower() for kw in PERCENT_FIELD_KEYWORDS))
                    # 百分比语义或绝对值<1 都按百分比展示
                    if is_percent or (abs(val) < 1 and not is_slope):
                        pct = val * 100
                        if abs(pct) < 1e-6:
                            return "0"
                        return format_float(pct) + "%"
                    if abs(val) >= 1e3:
                        return abbreviate_number(float(val))
                    return format_float(val)
                return translate_value(str(val), lang=self._lang)
        return ""

    def _get_row(self, table: str, period: str, panel: PanelType) -> Dict:
        """获取指定表/周期/币种的首行，用于字段探测。"""
        base_table = TABLE_ALIAS.get(panel, {}).get(table, table)
        self._get_table_data(base_table, period)
        return self._index_cache.get((base_table, period), {}).get(self._target_sym, {})

    def _get_table_data(self, base_table: str, period: str) -> list[dict]:
        """获取 (表, 周期) 数据并缓存结果+索引。"""
        key = (base_table, period)
        if key not in self._data_cache:
            try:
                data = self.provider.merge_with_base(base_table, period)
            except Exception:
                data = []
            self._data_cache[key] = data or []
            idx = {}
            for item in self._data_cache[key]:
                sym = format_symbol(item.get("symbol") or item.get("交易对") or "")
                if sym:
                    idx[sym] = item
            self._index_cache[key] = idx
        return self._data_cache[key]

    def _auto_fields(self, row: Dict) -> List[str]:
        """自动探测行中的数值字段，过滤公共字段，保持原顺序。"""
        if not row:
            return []
        fields: List[str] = []
        for k, v in row.items():
            if k in IGNORE_FIELDS:
                continue
            if isinstance(v, (int, float)):
                fields.append(k)
        return fields[:8]  # 防止行数过多，最多 8 个字段


def format_float(val: float) -> str:
    """动态小数保留：
    - |x| >= 0.01    -> 2 位小数
    - 1e-6 <= |x| <0.01 -> 5 位小数
    - |x| < 1e-6    -> 科学计数法，2 位有效数字
    最后去尾零和多余点。
    """
    if val is None or math.isnan(val):
        return ""
    a = abs(val)
    if a >= 0.01:
        s = f"{val:.2f}"
    elif a >= 1e-6:
        s = f"{val:.5f}"
    else:
        s = f"{val:.2e}"
    return s.rstrip("0").rstrip(".")


# ==================== K线形态独立界面 ====================

def render_pattern_panel(symbol: str, enabled_periods: Dict[str, bool] | None = None, lang: str = None) -> str:
    """渲染单币种 K线形态面板（独立界面）"""
    lang = resolve_lang(lang=lang)
    provider = get_ranking_provider()
    sym = format_symbol(symbol)
    if not sym:
        return _t("snapshot.error.no_symbol", lang=lang)

    sym_full = sym + "USDT" if not sym.endswith("USDT") else sym

    # 默认周期开关：15m/1h/4h 开启，其他关闭
    if enabled_periods is None:
        enabled_periods = {"1m": False, "5m": False, "15m": True, "1h": True, "4h": True, "1d": False, "1w": False}

    periods = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]
    lines = [_t("pattern.title", lang=lang, symbol=sym)]

    for p in periods:
        if not enabled_periods.get(p, False):
            continue
        row = provider._fetch_single_row("K线形态扫描器", p, sym_full)
        if not row:
            continue
        patterns = row.get("形态类型", "")
        count = row.get("检测数量", 0)
        if not patterns:
            continue

        # 分类形态
        bullish = []  # 看涨
        bearish = []  # 看跌
        neutral = []  # 中性

        bullish_kw = ["锤子", "晨星", "吞没", "孕线", "头肩底", "双底", "三底", "上升", "看涨"]
        bearish_kw = ["上吊", "黄昏", "乌鸦", "头肩顶", "双顶", "三顶", "下降", "看跌", "墓碑"]

        for pat in patterns.split(","):
            pat = pat.strip()
            if not pat:
                continue
            # 翻译形态名称
            pat = translate_value(pat, lang=lang)
            if any(k in pat for k in bullish_kw):
                bullish.append(pat)
            elif any(k in pat for k in bearish_kw):
                bearish.append(pat)
            else:
                neutral.append(pat)

        lines.append(_t("pattern.period_count", lang=lang, period=p, count=count))
        lines.append("```")
        if bullish:
            lines.append(f"🟢 {', '.join(bullish)}")
        if bearish:
            lines.append(f"🔴 {', '.join(bearish)}")
        if neutral:
            lines.append(f"⚪ {', '.join(neutral)}")
        lines.append("```")

    if len(lines) == 1:  # 只有标题
        return f"{_t('pattern.title', lang=lang, symbol=sym)}\n```\n{_t('pattern.no_data', lang=lang)}\n```"

    return "\n".join(lines)


# ==================== 简单自测入口（非必须） ====================

if __name__ == "__main__":
    demo = SingleTokenSnapshot()
    print(demo.render_table("BTC", "futures", {"1m": False, "5m": True, "15m": True, "1h": True, "4h": True, "1d": True, "1w": True}))
