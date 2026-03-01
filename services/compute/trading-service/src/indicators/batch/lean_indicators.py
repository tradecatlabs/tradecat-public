"""LEAN 技术指标 - NumPy 向量化优化版"""
import numpy as np
import pandas as pd
from ..base import Indicator, IndicatorMeta, register


# ==================== NumPy 向量化工具 ====================
def wilder_smooth(arr: np.ndarray, period: int) -> np.ndarray:
    """Wilder 平滑 - 向量化"""
    result = np.zeros_like(arr, dtype=float)
    result[0] = arr[0]
    alpha = 1.0 / period
    for i in range(1, len(arr)):
        result[i] = result[i-1] * (1 - alpha) + arr[i] * alpha
    return result


def ema_np(arr: np.ndarray, period: int) -> np.ndarray:
    """EMA - 向量化"""
    alpha = 2.0 / (period + 1)
    result = np.zeros_like(arr, dtype=float)
    result[0] = arr[0]
    for i in range(1, len(arr)):
        result[i] = arr[i] * alpha + result[i-1] * (1 - alpha)
    return result


# ==================== SuperTrend ====================
def calc_supertrend(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 10, mult: float = 3.0) -> dict:
    n = len(close)
    if n < period + 1:
        return {}

    # TR 和 ATR
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
    atr = wilder_smooth(tr, period)

    # 上下轨
    hl2 = (high + low) / 2
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr

    # SuperTrend 计算
    final_upper = np.copy(upper)
    final_lower = np.copy(lower)
    supertrend = np.zeros(n)
    direction = np.ones(n, dtype=int)  # 1=下跌, -1=上涨

    for i in range(1, n):
        # 调整上下轨
        if close[i-1] > final_upper[i-1]:
            final_upper[i] = upper[i]
        else:
            final_upper[i] = min(upper[i], final_upper[i-1])

        if close[i-1] < final_lower[i-1]:
            final_lower[i] = lower[i]
        else:
            final_lower[i] = max(lower[i], final_lower[i-1])

        # 方向判断
        if supertrend[i-1] == final_upper[i-1]:
            direction[i] = -1 if close[i] > final_upper[i] else 1
        else:
            direction[i] = 1 if close[i] < final_lower[i] else -1

        supertrend[i] = final_upper[i] if direction[i] == 1 else final_lower[i]

    return {"SuperTrend": supertrend[-1], "方向": "空" if direction[-1] == 1 else "多",
            "上轨": final_upper[-1], "下轨": final_lower[-1]}


@register
class SuperTrendLean(Indicator):
    meta = IndicatorMeta(name="SuperTrend.py", lookback=60, is_incremental=False, min_data=10)

    def compute(self, df: pd.DataFrame, symbol: str, interval: str) -> pd.DataFrame:
        if not self._check_data(df):
            return self._make_insufficient_result(df, symbol, interval, {"SuperTrend": None, "方向": None})
        res = calc_supertrend(df["high"].values, df["low"].values, df["close"].values)
        return self._make_result(df, symbol, interval, res) if res else self._make_insufficient_result(df, symbol, interval, {"SuperTrend": None, "方向": None})


# ==================== ADX ====================
def calc_adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> dict:
    n = len(close)
    if n < period * 2:
        return {}

    # TR, +DM, -DM
    tr = np.zeros(n)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)

    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
        up = high[i] - high[i-1]
        down = low[i-1] - low[i]
        plus_dm[i] = up if up > down and up > 0 else 0
        minus_dm[i] = down if down > up and down > 0 else 0

    # Wilder 平滑
    smooth_tr = wilder_smooth(tr, period)
    smooth_plus = wilder_smooth(plus_dm, period)
    smooth_minus = wilder_smooth(minus_dm, period)

    # DI
    # NOTE: np.where(cond, A/B, 0) 仍可能先计算 A/B 再筛选，导致除零 RuntimeWarning；
    # 用 np.divide + where 才能真正避免除零分支被评估。
    plus_di = np.zeros_like(smooth_tr, dtype=float)
    minus_di = np.zeros_like(smooth_tr, dtype=float)
    np.divide(100 * smooth_plus, smooth_tr, out=plus_di, where=smooth_tr > 0)
    np.divide(100 * smooth_minus, smooth_tr, out=minus_di, where=smooth_tr > 0)

    # DX 和 ADX
    di_sum = plus_di + minus_di
    dx = np.zeros_like(di_sum, dtype=float)
    np.divide(100 * np.abs(plus_di - minus_di), di_sum, out=dx, where=di_sum > 0)
    adx = wilder_smooth(dx, period)

    return {"ADX": adx[-1], "正向DI": plus_di[-1], "负向DI": minus_di[-1]}


@register
class ADXIndicator(Indicator):
    meta = IndicatorMeta(name="ADX.py", lookback=70, is_incremental=False, min_data=28)

    def compute(self, df: pd.DataFrame, symbol: str, interval: str) -> pd.DataFrame:
        if not self._check_data(df):
            return self._make_insufficient_result(df, symbol, interval, {"ADX": None, "正向DI": None, "负向DI": None})
        res = calc_adx(df["high"].values, df["low"].values, df["close"].values)
        return self._make_result(df, symbol, interval, res) if res else self._make_insufficient_result(df, symbol, interval, {"ADX": None})


# ==================== CCI ====================
def calc_cci(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 20) -> dict:
    n = len(close)
    if n < period:
        return {}

    tp = (high + low + close) / 3
    sma = np.convolve(tp, np.ones(period)/period, mode='valid')

    # MAD
    mad = np.zeros(len(sma))
    for i in range(len(sma)):
        mad[i] = np.mean(np.abs(tp[i:i+period] - sma[i]))

    cci = (tp[period-1:] - sma) / (0.015 * mad + 1e-10)
    return {"CCI": cci[-1]}


@register
class CCIIndicator(Indicator):
    meta = IndicatorMeta(name="CCI.py", lookback=60, is_incremental=False, min_data=20)

    def compute(self, df: pd.DataFrame, symbol: str, interval: str) -> pd.DataFrame:
        if not self._check_data(df):
            return self._make_insufficient_result(df, symbol, interval, {"CCI": None})
        res = calc_cci(df["high"].values, df["low"].values, df["close"].values)
        return self._make_result(df, symbol, interval, res) if res else self._make_insufficient_result(df, symbol, interval, {"CCI": None})


# ==================== WilliamsR ====================
def calc_williams_r(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> dict:
    n = len(close)
    if n < period:
        return {}

    # 滚动最高最低
    hh = np.array([high[max(0,i-period+1):i+1].max() for i in range(period-1, n)])
    ll = np.array([low[max(0,i-period+1):i+1].min() for i in range(period-1, n)])

    wr = -100 * (hh - close[period-1:]) / (hh - ll + 1e-10)
    return {"WilliamsR": wr[-1]}


@register
class WilliamsRIndicator(Indicator):
    meta = IndicatorMeta(name="WilliamsR.py", lookback=42, is_incremental=False, min_data=14)

    def compute(self, df: pd.DataFrame, symbol: str, interval: str) -> pd.DataFrame:
        if not self._check_data(df):
            return self._make_insufficient_result(df, symbol, interval, {"WilliamsR": None})
        res = calc_williams_r(df["high"].values, df["low"].values, df["close"].values)
        return self._make_result(df, symbol, interval, res) if res else self._make_insufficient_result(df, symbol, interval, {"WilliamsR": None})


# ==================== Donchian ====================
def calc_donchian(high: np.ndarray, low: np.ndarray, period: int = 20) -> dict:
    if len(high) < period:
        return {}
    upper = high[-period:].max()
    lower = low[-period:].min()
    return {"上轨": upper, "中轨": (upper + lower) / 2, "下轨": lower}


@register
class DonchianIndicator(Indicator):
    meta = IndicatorMeta(name="Donchian.py", lookback=60, is_incremental=False, min_data=20)

    def compute(self, df: pd.DataFrame, symbol: str, interval: str) -> pd.DataFrame:
        if not self._check_data(df):
            return self._make_insufficient_result(df, symbol, interval, {"上轨": None, "中轨": None, "下轨": None})
        res = calc_donchian(df["high"].values, df["low"].values)
        return self._make_result(df, symbol, interval, res) if res else self._make_insufficient_result(df, symbol, interval, {"上轨": None})


# ==================== Keltner ====================
def calc_keltner(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                 ema_period: int = 20, atr_period: int = 10, mult: float = 2.0) -> dict:
    n = len(close)
    if n < max(ema_period, atr_period):
        return {}

    mid = ema_np(close, ema_period)

    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
    atr = wilder_smooth(tr, atr_period)

    return {"上轨": mid[-1] + mult * atr[-1], "中轨": mid[-1], "下轨": mid[-1] - mult * atr[-1], "ATR": atr[-1]}


@register
class KeltnerIndicator(Indicator):
    meta = IndicatorMeta(name="Keltner.py", lookback=60, is_incremental=False, min_data=20)

    def compute(self, df: pd.DataFrame, symbol: str, interval: str) -> pd.DataFrame:
        if not self._check_data(df):
            return self._make_insufficient_result(df, symbol, interval, {"上轨": None, "中轨": None, "下轨": None})
        res = calc_keltner(df["high"].values, df["low"].values, df["close"].values)
        return self._make_result(df, symbol, interval, res) if res else self._make_insufficient_result(df, symbol, interval, {"上轨": None})


# ==================== Ichimoku ====================
def calc_ichimoku(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                  tenkan: int = 9, kijun: int = 26, senkou_b: int = 52) -> dict:
    n = len(close)
    if n < kijun:
        return {}

    def donchian_mid(h, low, period):
        return (h[-period:].max() + low[-period:].min()) / 2

    tenkan_val = donchian_mid(high, low, tenkan)
    kijun_val = donchian_mid(high, low, kijun)
    senkou_a = (tenkan_val + kijun_val) / 2
    senkou_b_val = donchian_mid(high, low, senkou_b) if n >= senkou_b else 0

    price = close[-1]
    cloud_top = max(senkou_a, senkou_b_val)
    cloud_bottom = min(senkou_a, senkou_b_val)

    if price > cloud_top and tenkan_val > kijun_val:
        signal, direction = "BUY", "多"
    elif price < cloud_bottom and tenkan_val < kijun_val:
        signal, direction = "SELL", "空"
    else:
        signal, direction = "NEUTRAL", "震荡"

    if price > cloud_top:
        strength = min(1.0, (price - cloud_top) / (cloud_top - cloud_bottom + 1e-10))
    elif price < cloud_bottom:
        strength = min(1.0, (cloud_bottom - price) / (cloud_top - cloud_bottom + 1e-10))
    else:
        strength = 0.5

    return {"转换线": tenkan_val, "基准线": kijun_val, "先行带A": senkou_a, "先行带B": senkou_b_val,
            "迟行带": price, "当前价格": price, "信号": signal, "方向": direction, "强度": round(strength, 3)}


@register
class IchimokuIndicator(Indicator):
    meta = IndicatorMeta(name="Ichimoku.py", lookback=120, is_incremental=False, min_data=26)

    def compute(self, df: pd.DataFrame, symbol: str, interval: str) -> pd.DataFrame:
        if not self._check_data(df):
            return self._make_insufficient_result(df, symbol, interval, {"信号": None, "方向": None})
        res = calc_ichimoku(df["high"].values, df["low"].values, df["close"].values)
        return self._make_result(df, symbol, interval, res) if res else self._make_insufficient_result(df, symbol, interval, {"信号": None})
