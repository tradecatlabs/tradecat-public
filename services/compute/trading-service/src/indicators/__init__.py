"""
指标模块

- incremental/: 真正增量计算（EMA/累加/单行读取）
- batch/: 需要历史窗口（rolling/全量计算）

计算结果统一写入 PostgreSQL（tg_cards schema）。
"""
from .base import (
    Indicator,
    IndicatorMeta,
    register,
    get_indicator,
    get_all_indicators,
    get_batch_indicators,
    get_incremental_indicators,
)

# === 增量指标（可递推/单行）===
# 导入用于注册，非直接使用
from .incremental import macd  # noqa: F401
from .incremental import kdj  # noqa: F401
from .incremental import atr  # noqa: F401
from .incremental import ema_gc  # noqa: F401
from .incremental import obv  # noqa: F401
from .incremental import cvd  # noqa: F401
from .incremental import base_data  # noqa: F401
from .incremental import buy_sell_ratio  # noqa: F401
from .incremental import futures_sentiment  # noqa: F401

# === 批量指标（需要窗口）===
from .batch import k_pattern  # noqa: F401
from .batch import trend_line  # noqa: F401
from .batch import support_resistance  # noqa: F401
from .batch import vpvr  # noqa: F401
from .batch import super_trend  # noqa: F401
from .batch import bollinger  # noqa: F401
from .batch import vwap  # noqa: F401
from .batch import volume_ratio  # noqa: F401
from .batch import mfi  # noqa: F401
from .batch import liquidity  # noqa: F401
from .batch import tv_rsi  # noqa: F401
from .batch import tv_trend_cloud  # noqa: F401
from .batch import tv_big_money  # noqa: F401
from .batch import tv_fib_sniper  # noqa: F401
from .batch import tv_zero_lag  # noqa: F401
from .batch import tv_volume_signal  # noqa: F401
from .batch import tv_long_short  # noqa: F401
from .batch import scalping  # noqa: F401
from .batch import harmonic  # noqa: F401
from .batch import futures_aggregate  # noqa: F401
from .batch import lean_indicators  # noqa: F401
from .batch import data_monitor  # noqa: F401
from .batch import futures_gap_monitor  # noqa: F401

__all__ = [
    "Indicator",
    "IndicatorMeta",
    "register",
    "get_indicator",
    "get_all_indicators",
    "get_batch_indicators",
    "get_incremental_indicators",
]
