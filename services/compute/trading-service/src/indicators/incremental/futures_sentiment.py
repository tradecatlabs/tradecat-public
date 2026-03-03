"""期货情绪指标（从 PostgreSQL 读取）"""
import logging
from datetime import timezone
from typing import Optional, Dict, TypedDict

import pandas as pd

from ...db.reader import inc_pg_query, shared_pg_conn
from ..base import Indicator, IndicatorMeta, register

# ==================== 数据契约 ====================

LOG = logging.getLogger("indicator_service.futures_sentiment")

class FuturesLatestMetrics(TypedDict, total=False):
    """期货情绪最新快照契约（增量指标输入）"""
    datetime: Optional[pd.Timestamp]
    oi: Optional[float]
    oiv: Optional[float]
    ctlsr: Optional[float]
    tlsr: Optional[float]
    lsr: Optional[float]
    tlsvr: Optional[float]

# 缓存 {interval: {symbol: data}}
_METRICS_CACHE: Dict[str, Dict[str, FuturesLatestMetrics]] = {}
_CACHE_TS: Dict[str, float] = {}
_TABLE_EXISTS: Dict[str, bool] = {}
_TABLE_EXISTS_TS: Dict[str, float] = {}
_ERROR_TS: Dict[str, float] = {}
_TABLE_EXISTS_TTL_SECONDS = 600
_ERROR_LOG_TTL_SECONDS = 600

def _table_exists(schema: str, table: str) -> bool:
    import time
    key = f"{schema}.{table}"
    now = time.time()
    if key in _TABLE_EXISTS and (now - _TABLE_EXISTS_TS.get(key, 0)) < _TABLE_EXISTS_TTL_SECONDS:
        return _TABLE_EXISTS[key]
    ok = False
    try:
        with shared_pg_conn() as conn:
            with conn.cursor() as cur:
                inc_pg_query()
                cur.execute("SELECT to_regclass(%s) IS NOT NULL AS ok", (key,))
                row = cur.fetchone()
                ok = bool(row[0]) if row else False
    except Exception:
        ok = False
    _TABLE_EXISTS[key] = ok
    _TABLE_EXISTS_TS[key] = now
    return ok

def _load_all_metrics(interval: str = "5m"):
    """批量加载所有币种的最新期货数据"""
    global _METRICS_CACHE, _CACHE_TS
    import time

    # 缓存 60 秒
    if time.time() - _CACHE_TS.get(interval, 0) < 60 and interval in _METRICS_CACHE:
        return

    # 根据周期选择表和列名
    if interval == "5m":
        table = "binance_futures_metrics_5m"
        time_col = "create_time"
    else:
        table = f"binance_futures_metrics_{interval}_last"
        time_col = "bucket"

    # 若该周期的期货表不存在：直接返回空缓存，避免触发占位行写入与反复异常
    if not _table_exists("market_data", table):
        _METRICS_CACHE[interval] = {}
        _CACHE_TS[interval] = time.time()
        return

    try:
        with shared_pg_conn() as conn:
            with conn.cursor() as cur:
                inc_pg_query()
                cur.execute(f"""
                    SELECT DISTINCT ON (symbol) 
                        symbol, {time_col}, sum_open_interest, sum_open_interest_value,
                        count_toptrader_long_short_ratio, sum_toptrader_long_short_ratio,
                        count_long_short_ratio, sum_taker_long_short_vol_ratio
                    FROM market_data.{table}
                    WHERE {time_col} > (NOW() AT TIME ZONE 'UTC') - INTERVAL '30 days'
                    ORDER BY symbol, {time_col} DESC
                """)
                _METRICS_CACHE[interval] = {}
                for row in cur.fetchall():
                    _METRICS_CACHE[interval][row[0]] = {
                        "datetime": row[1].replace(tzinfo=timezone.utc) if row[1] else None,
                        "oi": row[2], "oiv": row[3], "ctlsr": row[4],
                        "tlsr": row[5], "lsr": row[6], "tlsvr": row[7],
                    }
                _CACHE_TS[interval] = time.time()
    except Exception:
        now = time.time()
        last = _ERROR_TS.get(interval, 0)
        if (now - last) >= _ERROR_LOG_TTL_SECONDS:
            _ERROR_TS[interval] = now
            LOG.warning("加载期货情绪快照失败 interval=%s table=%s", interval, table, exc_info=True)
        _METRICS_CACHE[interval] = {}
        _CACHE_TS[interval] = now


def get_latest_metrics(symbol: str, interval: str = "5m") -> Optional[FuturesLatestMetrics]:
    """获取单个币种的最新期货数据"""
    _load_all_metrics(interval)
    return _METRICS_CACHE.get(interval, {}).get(symbol)


def set_metrics_cache(cache: Dict[str, FuturesLatestMetrics], interval: str = "5m"):
    """设置期货数据缓存（用于跨进程传递）"""
    global _METRICS_CACHE, _CACHE_TS
    import time
    _METRICS_CACHE[interval] = cache
    _CACHE_TS[interval] = time.time()


def get_metrics_cache(interval: str = "5m") -> Dict[str, FuturesLatestMetrics]:
    """获取期货数据缓存"""
    _load_all_metrics(interval)
    return _METRICS_CACHE.get(interval, {}).copy()


@register
class FuturesSentiment(Indicator):
    meta = IndicatorMeta(name="期货情绪元数据.py", lookback=1, is_incremental=True, allow_placeholder=False)

    def compute(self, df: pd.DataFrame, symbol: str, interval: str) -> pd.DataFrame:
        # 期货数据只有 5m/15m/1h/4h/1d/1w，跳过1m
        if interval == "1m":
            return pd.DataFrame()
        metrics = get_latest_metrics(symbol, interval)
        if not metrics:
            return pd.DataFrame()

        def f(v):
            try:
                return float(v) if v is not None else None
            except Exception:
                return None

        ts = metrics.get("datetime")
        # 若期货源无时间戳（或表缺失/异常导致），不要用 K 线 last_ts 伪造“期货进度”
        if ts is None:
            return pd.DataFrame()
        data = {
            "持仓张数": f(metrics.get("oi")),
            "持仓金额": f(metrics.get("oiv")),
            "大户多空比样本": f(metrics.get("ctlsr")),
            "大户多空比总和": f(metrics.get("tlsr")),
            "全体多空比样本": f(metrics.get("lsr")),
            "主动成交多空比总和": f(metrics.get("tlsvr")),
            "大户多空比": f(metrics.get("tlsr")),
            "全体多空比": f(metrics.get("lsr")),
            "主动成交多空比": f(metrics.get("tlsvr")),
        }
        if all(v is None for v in data.values()):
            return pd.DataFrame()
        return self._make_result(df, symbol, interval, {
            **data
        }, timestamp=ts)
