from __future__ import annotations

"""TG 卡片数据契约（单一真相源）。

注意：本模块允许包含“内部表名/内部列名”的映射，因为这些属于实现细节；
真正对外输出由 api-service 的 /api/v1/cards 等端点做脱敏与整形。
"""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class CardContract:
    """卡片契约定义（只读）"""

    card_id: str
    title: str
    description: str

    # 指标库表名（tg_cards schema）。为空表示该卡片当前为占位/下线，或由别的链路提供。
    indicator_table: str | None

    # 兼容历史调用：卡片内部曾使用的“表别名/键名”（如 “ATR波幅榜单”）。
    legacy_table_key: str | None = None

    # 是否需要合并基础数据（价格/成交额/振幅/成交笔数/主动买卖比 等）
    merge_base: bool = True

    # 默认支持周期（用于 capabilities）
    intervals: tuple[str, ...] = ("5m", "15m", "1h", "4h", "1d", "1w")


# ==================== 指标表别名（历史兼容） ====================

# 说明：历史上 telegram-service 使用 “表别名/榜单名” -> “实际表名(.py)” 的映射。
# 该映射在契约层收敛，作为单一真相源，避免 api/telegram 两边各维护一套漂移。

LEGACY_TABLE_KEY_TO_TABLE: Final[dict[str, str]] = {
    # 基础
    "基础数据": "基础数据同步器.py",
    "基础数据同步器": "基础数据同步器.py",
    # 指标
    "ATR波幅榜单": "ATR波幅扫描器.py",
    "BB榜单": "布林带扫描器.py",
    "布林带榜单": "布林带扫描器.py",
    "CVD榜单": "CVD信号排行榜.py",
    "KDJ随机指标榜单": "KDJ随机指标扫描器.py",
    "K线形态榜单": "K线形态扫描器.py",
    "MACD柱状榜单": "MACD柱状扫描器.py",
    "MFI资金流量榜单": "MFI资金流量扫描器.py",
    "OBV能量潮榜单": "OBV能量潮扫描器.py",
    "VPVR榜单": "VPVR排行生成器.py",
    "VWAP榜单": "VWAP离线信号扫描.py",
    "主动买卖比榜单": "主动买卖比扫描器.py",
    "成交量比率榜单": "成交量比率扫描器.py",
    "支撑阻力榜单": "全量支撑阻力扫描器.py",
    "收敛发散榜单": "G，C点扫描器.py",
    "流动性榜单": "流动性扫描器.py",
    "谐波信号榜单": "谐波信号扫描器.py",
    "趋势线榜单": "趋势线榜单.py",
    "期货情绪聚合榜单": "期货情绪聚合表.py",
}


def _as_table_name(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip()
    if not v:
        return None
    # 允许直接传入 *.py 或历史别名
    if v.endswith(".py"):
        return v
    return LEGACY_TABLE_KEY_TO_TABLE.get(v) or (v + ".py")


# ==================== card_id 契约列表 ====================

ALL_CARD_CONTRACTS: Final[tuple[CardContract, ...]] = (
    # basic
    CardContract(card_id="sr_ranking", title="🧱 支撑阻力", description="支撑阻力突破/反弹信号榜", indicator_table=_as_table_name("支撑阻力榜单"), legacy_table_key="支撑阻力榜单"),
    CardContract(card_id="volume_ranking", title="📊 成交量", description="按成交量排序的榜单", indicator_table=_as_table_name("基础数据同步器.py"), legacy_table_key="基础数据", merge_base=False),
    CardContract(card_id="money_flow", title="🚰 资金流向", description="资金净流量榜（Smart Money Flow）", indicator_table=_as_table_name("CVD榜单"), legacy_table_key="CVD榜单"),
    CardContract(card_id="macd_ranking", title="🧲 MACD柱", description="MACD 柱状强度榜", indicator_table=_as_table_name("MACD柱状榜单"), legacy_table_key="MACD柱状榜单"),
    CardContract(card_id="bb_ranking", title="🎗️ 布林带", description="布林带带宽/百分比 榜单", indicator_table=_as_table_name("BB榜单"), legacy_table_key="BB榜单"),
    CardContract(card_id="obv_ranking", title="📡 OBV", description="OBV 能量潮斜率/方向榜", indicator_table=_as_table_name("OBV能量潮榜单"), legacy_table_key="OBV能量潮榜单"),
    CardContract(card_id="volume_ratio_ranking", title="📦 成交量比率", description="成交量比率(当前/均量)排行榜", indicator_table=_as_table_name("成交量比率榜单"), legacy_table_key="成交量比率榜单"),
    CardContract(card_id="rsi_harmonic_ranking", title="🔔 RSI谐波", description="RSI 全谐波信号榜", indicator_table=_as_table_name("谐波信号榜单"), legacy_table_key="谐波信号榜单"),
    CardContract(card_id="kdj_ranking", title="🎯 KDJ", description="KDJ 随机指标排行榜", indicator_table=_as_table_name("KDJ随机指标榜单"), legacy_table_key="KDJ随机指标榜单"),

    # advanced
    CardContract(card_id="liquidity_ranking", title="💧 流动性", description="流动性危机指数榜 (Amihud/Kyle 综合)", indicator_table=_as_table_name("流动性榜单"), legacy_table_key="流动性榜单"),
    CardContract(card_id="mfi_ranking", title="💰 MFI", description="MFI 资金流量强度榜", indicator_table=_as_table_name("MFI资金流量榜单"), legacy_table_key="MFI资金流量榜单"),
    CardContract(card_id="vwap_ranking", title="📏 VWAP", description="按VWAP偏离强度排序的榜单", indicator_table=_as_table_name("VWAP榜单"), legacy_table_key="VWAP榜单"),
    CardContract(card_id="vpvr_ranking", title="🏛️ VPVR", description="成交量分布偏离价值区榜单（宽度用百分比）", indicator_table=_as_table_name("VPVR榜单"), legacy_table_key="VPVR榜单"),
    CardContract(card_id="atr_ranking", title="🧭 波动率", description="波幅强度榜（ATR%）", indicator_table=_as_table_name("ATR波幅榜单"), legacy_table_key="ATR波幅榜单"),
    CardContract(card_id="ema_ranking", title="🧮 EMA", description="EMA 区间收敛/发散强度榜", indicator_table=_as_table_name("G，C点扫描器.py"), legacy_table_key="收敛发散榜单"),
    CardContract(card_id="trendline_ranking", title="📈 趋势线", description="多/空趋势线距离榜（Pine 趋势线 1:1 复刻）", indicator_table=_as_table_name("趋势线榜单.py"), legacy_table_key="趋势线榜单"),
    CardContract(card_id="cvd_ranking", title="🌊 CVD", description="按净流强度排序的 CVD 榜单", indicator_table=_as_table_name("CVD榜单"), legacy_table_key="CVD榜单"),
    CardContract(card_id="super_trend_ranking", title="📐 超级趋势", description="零延迟趋势信号：方向/持续/强度", indicator_table=_as_table_name("超级精准趋势扫描器.py"), legacy_table_key="超级精准趋势扫描器.py"),
    CardContract(card_id="candle_pattern_ranking", title="🕯️ 形态", description="K线形态强度榜（价格形态+蜡烛形态，全中文）", indicator_table=_as_table_name("K线形态榜单"), legacy_table_key="K线形态榜单"),

    # futures（独立指标表）
    CardContract(card_id="buy_sell_ratio_ranking", title="🧾 主动买卖比", description="按主动买成交额占比排序，洞察买盘强弱", indicator_table=_as_table_name("主动买卖比榜单"), legacy_table_key="主动买卖比榜单"),

    # futures (基于同一张聚合表)
    CardContract(card_id="futures_oi_streak", title="📈 OI连续", description="OI 连涨/连跌根数排行榜，基于期货情绪聚合表", indicator_table=_as_table_name("期货情绪聚合表.py"), legacy_table_key="期货情绪聚合榜单"),
    CardContract(card_id="futures_oi_z_alert", title="🚩 OI极值", description="持仓Z分数极值告警榜，基于期货情绪聚合表", indicator_table=_as_table_name("期货情绪聚合表.py"), legacy_table_key="期货情绪聚合榜单"),
    CardContract(card_id="futures_oi_change_ranking", title="⚡ 持仓增减速", description="持仓变动速度排行榜，基于期货情绪聚合表", indicator_table=_as_table_name("期货情绪聚合表.py"), legacy_table_key="期货情绪聚合榜单"),
    CardContract(card_id="futures_flip_radar", title="🛰️ 翻转雷达", description="情绪翻转信号榜，基于期货情绪聚合表", indicator_table=_as_table_name("期货情绪聚合表.py"), legacy_table_key="期货情绪聚合榜单"),
    CardContract(card_id="futures_oi_ranking", title="🐋 持仓聚合", description="期货合约持仓量/变动排行榜，基于期货情绪聚合表", indicator_table=_as_table_name("期货情绪聚合表.py"), legacy_table_key="期货情绪聚合榜单"),
    CardContract(card_id="futures_crowd_sentiment", title="🌐 全体情绪", description="全市场多空情绪与偏离排行榜，基于期货情绪聚合表", indicator_table=_as_table_name("期货情绪聚合表.py"), legacy_table_key="期货情绪聚合榜单"),
    CardContract(card_id="futures_top_sentiment", title="🐳 大户情绪", description="大户多空情绪与动量排行榜，基于期货情绪聚合表", indicator_table=_as_table_name("期货情绪聚合表.py"), legacy_table_key="期货情绪聚合榜单"),
    CardContract(card_id="futures_taker_jump", title="⚡ 主动跳变", description="主动成交跳变幅度榜，基于期货情绪聚合表", indicator_table=_as_table_name("期货情绪聚合表.py"), legacy_table_key="期货情绪聚合榜单"),
    CardContract(card_id="futures_risk_crowding", title="🚨 风险拥挤", description="风险分与市场占比排行榜，基于期货情绪聚合表", indicator_table=_as_table_name("期货情绪聚合表.py"), legacy_table_key="期货情绪聚合榜单"),
    CardContract(card_id="futures_volatility", title="🌊 波动度", description="OI/情绪稳定度与波动率排行榜，基于期货情绪聚合表", indicator_table=_as_table_name("期货情绪聚合表.py"), legacy_table_key="期货情绪聚合榜单"),
    CardContract(card_id="futures_oi_trend", title="📐 OI趋势", description="持仓斜率与Z分数趋势榜，基于期货情绪聚合表", indicator_table=_as_table_name("期货情绪聚合表.py"), legacy_table_key="期货情绪聚合榜单"),
    CardContract(card_id="futures_divergence", title="⚖️ 情绪分歧", description="大户与全体情绪差值排行榜，基于期货情绪聚合表", indicator_table=_as_table_name("期货情绪聚合表.py"), legacy_table_key="期货情绪聚合榜单"),
    CardContract(card_id="position_ranking", title="🐋 持仓量", description="持仓量排行榜，追踪主力动向", indicator_table=_as_table_name("期货情绪聚合表.py"), legacy_table_key="期货情绪聚合榜单"),
    CardContract(card_id="futures_sentiment_momentum", title="🚀 情绪动量", description="大户/主动情绪动量排行榜，基于期货情绪聚合表", indicator_table=_as_table_name("期货情绪聚合表.py"), legacy_table_key="期货情绪聚合榜单"),
    CardContract(card_id="futures_taker_sentiment", title="🚦 主动方向", description="主动成交多空比与偏离排行榜，基于期货情绪聚合表", indicator_table=_as_table_name("期货情绪聚合表.py"), legacy_table_key="期货情绪聚合榜单"),
    CardContract(card_id="futures_taker_streak", title="↕️ 主动连续", description="主动成交连多/连空根数排行榜，基于期货情绪聚合表", indicator_table=_as_table_name("期货情绪聚合表.py"), legacy_table_key="期货情绪聚合榜单"),

    # offline / disabled cards（indicator_table=None）
    CardContract(card_id="funding_rate", title="💱 资金费率", description="资金费率排行榜（当前下线占位）", indicator_table=None, merge_base=False),
    CardContract(card_id="market_depth", title="🧊 市场深度", description="市场深度排行榜（当前下线占位）", indicator_table=None, merge_base=False),
    CardContract(card_id="__disabled_liquidation__", title="💥 爆仓", description="爆仓排行榜（禁用占位）", indicator_table=None, merge_base=False),
)


CARD_ID_TO_CONTRACT: Final[dict[str, CardContract]] = {c.card_id: c for c in ALL_CARD_CONTRACTS}


# 兼容：历史 key/表名 -> card_id（用于 telegram-service provider 的最小改动迁移）
_LEGACY_KEY_TO_CARD_ID: Final[dict[str, str]] = {
    # basic
    "支撑阻力榜单": "sr_ranking",
    "MACD柱状榜单": "macd_ranking",
    "BB榜单": "bb_ranking",
    "布林带榜单": "bb_ranking",
    "OBV能量潮榜单": "obv_ranking",
    "成交量比率榜单": "volume_ratio_ranking",
    "主动买卖比榜单": "buy_sell_ratio_ranking",
    "谐波信号榜单": "rsi_harmonic_ranking",
    "KDJ随机指标榜单": "kdj_ranking",
    # advanced
    "ATR波幅榜单": "atr_ranking",
    "CVD榜单": "cvd_ranking",
    "MFI资金流量榜单": "mfi_ranking",
    "VPVR榜单": "vpvr_ranking",
    "VWAP榜单": "vwap_ranking",
    "流动性榜单": "liquidity_ranking",
    "收敛发散榜单": "ema_ranking",
    "G，C点扫描器.py": "ema_ranking",
    "趋势线榜单.py": "trendline_ranking",
    "超级精准趋势扫描器.py": "super_trend_ranking",
    "K线形态榜单": "candle_pattern_ranking",
    # futures
    "期货情绪聚合表.py": "position_ranking",  # 注意：该表被多卡片复用，建议显式传 card_id
    "期货情绪聚合榜单": "position_ranking",
    # base
    "基础数据": "volume_ranking",
    "基础数据同步器.py": "volume_ranking",
}


def resolve_card_id(raw: str) -> str | None:
    """把历史别名/表名/卡片ID 解析为 card_id。"""
    v = (raw or "").strip()
    if not v:
        return None
    if v in CARD_ID_TO_CONTRACT:
        return v
    return _LEGACY_KEY_TO_CARD_ID.get(v)


__all__ = [
    "CardContract",
    "ALL_CARD_CONTRACTS",
    "CARD_ID_TO_CONTRACT",
    "LEGACY_TABLE_KEY_TO_TABLE",
    "resolve_card_id",
]
