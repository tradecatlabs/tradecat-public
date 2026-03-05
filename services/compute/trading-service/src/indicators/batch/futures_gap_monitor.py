"""期货情绪缺口监控 - 检测5m情绪数据缺口"""
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, TypedDict
import threading

import pandas as pd

from ...db.reader import inc_pg_query, shared_pg_conn
from ..base import Indicator, IndicatorMeta, register

# ==================== 数据契约 ====================

class GapInfo(TypedDict):
    """期货情绪缺口监控输出契约"""
    已加载根数: int
    最新时间: Optional[str]
    缺失根数: Optional[int]
    首缺口起: Optional[str]
    首缺口止: Optional[str]

# 期货时间序列缓存（按周期、按币种）
_TIMES_CACHE: Dict[str, Dict[str, List[datetime]]] = {}
_CACHE_TS: Dict[str, float] = {}
_CACHE_SYMBOLS: Dict[str, set] = {}
_CACHE_TTL_SECONDS = 60
_CACHE_LOCK = threading.Lock()
_LAST_FETCH_ERROR: Dict[str, str] = {}
_LAST_FETCH_ERROR_TS: Dict[str, float] = {}

LOG = logging.getLogger(__name__)

def _fetch_metrics_times_batch(symbols: List[str], limit: int, interval: str = "5m") -> Dict[str, List[datetime]]:
    """批量读取期货时间序列"""
    if not symbols:
        return {}

    # 根据周期选择表和列名
    if interval == "5m":
        table = "binance_futures_metrics_5m"
        time_col = "create_time"
    else:
        table = f"binance_futures_metrics_{interval}_last"
        time_col = "bucket"

    sql = f"""
        WITH ranked AS (
            SELECT
                symbol,
                {time_col},
                ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY {time_col} DESC) as rn
            FROM market_data.{table}
            WHERE symbol = ANY(%s)
              AND {time_col} > (NOW() AT TIME ZONE 'UTC') - INTERVAL '30 days'
        )
        SELECT symbol, {time_col}
        FROM ranked
        WHERE rn <= %s
        ORDER BY symbol, {time_col} ASC
    """

    result: Dict[str, List[datetime]] = {s: [] for s in symbols}
    with shared_pg_conn() as conn:
        with conn.cursor() as cur:
            inc_pg_query()
            cur.execute(sql, (symbols, limit))
            for row in cur.fetchall():
                ts = row[1].replace(tzinfo=timezone.utc) if row[1] else None
                if ts:
                    result[row[0]].append(ts)
    return result


def _ensure_times_cache(symbols: List[str], interval: str, limit: int):
    """确保时间序列缓存可用"""
    import time

    symbols = [s for s in symbols if s]
    if not symbols:
        return

    now = time.time()
    with _CACHE_LOCK:
        stale = (now - _CACHE_TS.get(interval, 0)) >= _CACHE_TTL_SECONDS
        cached_symbols = set(_CACHE_SYMBOLS.get(interval, set()))

    fetch_symbols = symbols if stale else [s for s in symbols if s not in cached_symbols]
    if not fetch_symbols:
        return

    try:
        batch = _fetch_metrics_times_batch(fetch_symbols, limit, interval)
    except Exception:
        LOG.warning("期货情绪缺口监控读库失败 interval=%s", interval, exc_info=True)
        with _CACHE_LOCK:
            _LAST_FETCH_ERROR[interval] = "db_read_failed"
            _LAST_FETCH_ERROR_TS[interval] = now
        return

    with _CACHE_LOCK:
        _LAST_FETCH_ERROR.pop(interval, None)
        _LAST_FETCH_ERROR_TS.pop(interval, None)
        if stale:
            _TIMES_CACHE[interval] = batch
            _CACHE_SYMBOLS[interval] = set(batch.keys())
        else:
            _TIMES_CACHE.setdefault(interval, {}).update(batch)
            _CACHE_SYMBOLS[interval] = cached_symbols.union(batch.keys())
        _CACHE_TS[interval] = now


def get_times_cache(symbols: List[str], interval: str = "5m", limit: int = 240) -> Dict[str, Dict[str, List[datetime]]]:
    """预取时间序列缓存（供引擎使用）"""
    _ensure_times_cache(symbols, interval, limit)
    with _CACHE_LOCK:
        interval_cache = dict(_TIMES_CACHE.get(interval, {}))
    return {interval: {s: interval_cache.get(s, []) for s in symbols}}


def set_times_cache(cache: Dict[str, Dict[str, List[datetime]]]):
    """设置时间序列缓存（用于跨进程传递）"""
    import time
    global _TIMES_CACHE, _CACHE_TS, _CACHE_SYMBOLS
    with _CACHE_LOCK:
        _TIMES_CACHE = cache or {}
        _CACHE_TS = {iv: time.time() for iv in _TIMES_CACHE}
        _CACHE_SYMBOLS = {iv: set(_TIMES_CACHE[iv].keys()) for iv in _TIMES_CACHE}


def get_metrics_times(symbol: str, limit: int = 240, interval: str = "5m") -> List[datetime]:
    """从 PostgreSQL 获取时间戳列表"""
    _ensure_times_cache([symbol], interval, limit)
    with _CACHE_LOCK:
        times = list(_TIMES_CACHE.get(interval, {}).get(symbol, []))
    if limit and len(times) > limit:
        return times[-limit:]
    return times


def get_last_fetch_error(interval: str = "5m") -> Optional[str]:
    with _CACHE_LOCK:
        return _LAST_FETCH_ERROR.get(interval)


def detect_gaps(times: List[datetime], interval_sec: int = 300) -> GapInfo:
    """检测时间序列中的缺口"""
    if not times:
        return {"已加载根数": 0, "最新时间": None, "缺失根数": None, "首缺口起": None, "首缺口止": None}

    times = sorted(set(times))
    missing_segments = []
    for i in range(1, len(times)):
        delta = (times[i] - times[i-1]).total_seconds()
        if delta > interval_sec:
            miss = int(delta // interval_sec) - 1
            gap_start = times[i-1] + timedelta(seconds=interval_sec)
            gap_end = times[i] - timedelta(seconds=interval_sec)
            missing_segments.append((gap_start, gap_end, miss))

    total_missing = sum(seg[2] for seg in missing_segments)
    first_gap = missing_segments[0] if missing_segments else (None, None, 0)

    return {
        "已加载根数": len(times),
        "最新时间": times[-1].isoformat(),
        "缺失根数": total_missing,
        "首缺口起": first_gap[0].isoformat() if first_gap[0] else None,
        "首缺口止": first_gap[1].isoformat() if first_gap[1] else None,
    }


@register
class FuturesGapMonitor(Indicator):
    meta = IndicatorMeta(name="期货情绪缺口监控.py", lookback=1, is_incremental=False, min_data=1)

    def compute(self, df: pd.DataFrame, symbol: str, interval: str) -> pd.DataFrame:
        # 期货缺口监控只对 5m 有意义，但为了避免上层 placeholder 逻辑插入“无键垃圾行”，
        # 这里对所有周期都返回“带三键(交易对/周期/数据时间)”的单行结果。
        if interval != "5m":
            ts = df.index[-1] if not df.empty else None
            ts_str = ts.isoformat() if hasattr(ts, "isoformat") else (str(ts) if ts is not None else None)
            return pd.DataFrame(
                [
                    {
                        "交易对": symbol,
                        "周期": interval,
                        "数据时间": ts_str,
                        "信号": "仅支持5m周期",
                        "已加载根数": None,
                        "最新时间": None,
                        "缺失根数": None,
                        "首缺口起": None,
                        "首缺口止": None,
                    }
                ]
            )

        times = get_metrics_times(symbol, 240, interval)
        if err := get_last_fetch_error(interval):
            ts = df.index[-1] if not df.empty else None
            ts_str = ts.isoformat() if hasattr(ts, "isoformat") else (str(ts) if ts is not None else None)
            return pd.DataFrame(
                [
                    {
                        "交易对": symbol,
                        "周期": interval,
                        "数据时间": ts_str,
                        "信号": err,
                        "已加载根数": None,
                        "最新时间": None,
                        "缺失根数": None,
                        "首缺口起": None,
                        "首缺口止": None,
                    }
                ]
            )
        gap_info = detect_gaps(times, 300)

        latest_ts = gap_info.get("最新时间")
        # gap_info["最新时间"] 可能为空；兜底使用 K线最新时间（保持三键完整）
        if not latest_ts:
            ts = df.index[-1] if not df.empty else None
            latest_ts = ts.isoformat() if hasattr(ts, "isoformat") else (str(ts) if ts is not None else None)

        missing = gap_info.get("缺失根数")
        signal = "有缺口" if isinstance(missing, int) and missing > 0 else "正常"

        row = {
            "交易对": symbol,
            "周期": interval,
            "数据时间": latest_ts,
            "信号": signal,
            **gap_info,
        }
        # 固定列顺序：保证前三列为主键
        cols = ["交易对", "周期", "数据时间"] + [c for c in row.keys() if c not in ("交易对", "周期", "数据时间")]
        return pd.DataFrame([row])[cols]
