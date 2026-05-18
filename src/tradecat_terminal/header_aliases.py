from __future__ import annotations

import re

from tradecat_terminal.i18n import resolve_lang

HEADER_ALIASES: dict[str, dict[str, str]] = {
    "时间(北京)": {"en": "Time (UTC+8)", "ko": "시간(UTC+8)"},
    "时间": {"en": "Time", "ko": "시간"},
    "内容": {"en": "Content", "ko": "내용"},
    "排名": {"en": "Rank", "ko": "순위"},
    "序号": {"en": "No.", "ko": "번호"},
    "交易对": {"en": "Symbol", "ko": "거래쌍"},
    "合约代码": {"en": "Symbol", "ko": "거래쌍"},
    "币种符号": {"en": "Symbol", "ko": "거래쌍"},
    "综合分": {"en": "Score", "ko": "점수"},
    "结构标签": {"en": "Structure", "ko": "구조"},
    "数据新鲜度分": {"en": "Freshness", "ko": "신선도"},
    "当前持仓量": {"en": "Open Interest", "ko": "미결제약정"},
    "当前持仓额": {"en": "OI Value", "ko": "미결제약정 금액"},
    "当前份额(%)": {"en": "Share (%)", "ko": "점유율(%)"},
    "当前份额变化(%)": {"en": "Share Change (%)", "ko": "점유율 변화(%)"},
    "窗口": {"en": "Window", "ko": "기간"},
    "覆盖合约数": {"en": "Contracts", "ko": "계약 수"},
    "合约数": {"en": "Contracts", "ko": "계약 수"},
    "交易对口径": {"en": "Symbol Scope", "ko": "거래쌍 기준"},
    "数据源": {"en": "Data Source", "ko": "데이터 소스"},
    "导出时间(UTC+8)": {"en": "Export Time (UTC+8)", "ko": "내보낸 시간(UTC+8)"},
    "刷新间隔(s)": {"en": "Refresh (s)", "ko": "새로고침(s)"},
    "条数": {"en": "Rows", "ko": "행 수"},
    "语言": {"en": "Language", "ko": "언어"},
    "模式": {"en": "Mode", "ko": "모드"},
    "标题": {"en": "Title", "ko": "제목"},
    "金额单位": {"en": "Unit", "ko": "단위"},
    "快照时间(ms)": {"en": "Snapshot Time (ms)", "ko": "스냅샷 시간(ms)"},
}

TOKEN_ALIASES: dict[str, dict[str, str]] = {
    "5m": {"en": "5m", "ko": "5분"},
    "15m": {"en": "15m", "ko": "15분"},
    "1h": {"en": "1h", "ko": "1시간"},
    "4h": {"en": "4h", "ko": "4시간"},
    "1d": {"en": "1d", "ko": "1일"},
    "1w": {"en": "1w", "ko": "1주"},
    "量变": {"en": "Volume Change", "ko": "거래량 변화"},
    "额变": {"en": "Value Change", "ko": "금액 변화"},
    "量": {"en": "Volume", "ko": "거래량"},
    "额": {"en": "Value", "ko": "금액"},
    "变化率": {"en": "Change Rate", "ko": "변화율"},
    "变化": {"en": "Change", "ko": "변화"},
    "占比": {"en": "Share", "ko": "비중"},
    "市场份额": {"en": "Market Share", "ko": "시장 점유율"},
    "当前": {"en": "Current", "ko": "현재"},
    "最新": {"en": "Latest", "ko": "최신"},
    "主动买卖": {"en": "Active Buy/Sell", "ko": "능동 매수/매도"},
    "主动买": {"en": "Active Buy", "ko": "능동 매수"},
    "主动卖": {"en": "Active Sell", "ko": "능동 매도"},
    "滞后根数": {"en": "Lag Bars", "ko": "지연 봉 수"},
    "连续根数": {"en": "Streak Bars", "ko": "연속 봉 수"},
    "异常强度": {"en": "Anomaly Strength", "ko": "이상 강도"},
    "排名": {"en": "Rank", "ko": "순위"},
    "榜": {"en": "Board", "ko": "보드"},
}


def alias_header(raw_name: str, lang: str | None = None) -> str:
    resolved = resolve_lang(lang)
    name = str(raw_name)
    if resolved == "zh":
        return name
    exact = HEADER_ALIASES.get(name, {}).get(resolved)
    if exact:
        return exact
    return _token_alias(name, resolved)


def alias_headers(raw_names: list[str], lang: str | None = None) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for raw_name in raw_names:
        display = alias_header(raw_name, lang)
        count = seen.get(display, 0) + 1
        seen[display] = count
        result.append(display if count == 1 else f"{display}_{count}")
    return result


def _token_alias(name: str, lang: str) -> str:
    text = name
    changed = False
    for token in sorted(TOKEN_ALIASES, key=len, reverse=True):
        replacement = TOKEN_ALIASES[token].get(lang)
        if replacement and token in text:
            text = text.replace(token, replacement)
            changed = True
    if not changed:
        return name
    if lang == "en":
        text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
        text = text.replace("(%)", " (%)")
        text = re.sub(r"\s+", " ", text).strip()
    return text
