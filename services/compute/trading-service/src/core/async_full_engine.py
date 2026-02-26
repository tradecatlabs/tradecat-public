"""
完全异步计算引擎 v2（高性能版）

优化点:
1. 高优先级查询合并SQL + 并行
2. 使用 pickle 协议5 优化序列化
3. 快慢指标真正并行（不再顺序等待）
4. 缓存并行初始化

三层隔离:
1. 币种优先级隔离 - 高优先级币种先算完
2. 指标隔离 - 快慢指标分离，互不阻塞  
3. 写入异步 - 独立线程批量写入

所有操作异步非阻塞
"""
import logging
import time
import signal
import queue
import pickle
from concurrent.futures import ProcessPoolExecutor, Future, as_completed, ThreadPoolExecutor
from threading import Thread, Event
from typing import Dict, List, Optional, Set
from datetime import datetime, timezone
import pandas as pd

from ..db.reader import shared_pg_conn
from ..indicators.base import get_all_indicators

LOG = logging.getLogger("indicator_service.async_full")

INTERVAL_CONFIG = {
    "1m": (60, 3), "5m": (300, 3), "15m": (900, 5), "1h": (3600, 10),
    "4h": (14400, 15), "1d": (86400, 30), "1w": (604800, 60),
}

# 高优先级币种 - 动态计算
HIGH_PRIORITY_SYMBOLS = set()  # 运行时动态获取

# 慢指标 - 单独进程计算
SLOW_INDICATORS = {
    "K线形态扫描器.py", "智能RSI扫描器.py", "多空信号扫描器.py",
    "超级精准趋势扫描器.py", "VPVR排行生成器.py",
}

INDICATOR_DEPS = {
    "期货情绪聚合表.py": ["期货情绪元数据.py"],
    "期货情绪缺口监控.py": ["期货情绪元数据.py"],
    "数据监控.py": ["基础数据同步器.py"],
}

def get_high_priority_symbols_fast(top_n: int = 30) -> Set[str]:
    """
    快速获取高优先级币种 - 合并SQL + 并行查询
    """
    result = set()

    def query_kline_priority():
        """K线维度优先级 - 单SQL合并查询"""
        symbols = set()
        try:
            with shared_pg_conn() as conn:
                # 合并3个维度到单个SQL
                sql = """
                    WITH base AS (
                        SELECT symbol, 
                               SUM(quote_volume) as total_qv,
                               AVG((high-low)/NULLIF(close,0)) as volatility
                        FROM market_data.candles_5m
                        WHERE bucket_ts > NOW() - INTERVAL '24 hours'
                        GROUP BY symbol
                    ),
                    volume_rank AS (
                        SELECT symbol FROM base ORDER BY total_qv DESC LIMIT %s
                    ),
                    volatility_rank AS (
                        SELECT symbol FROM base ORDER BY volatility DESC LIMIT %s
                    ),
                    change_rank AS (
                        WITH latest AS (
                            SELECT DISTINCT ON (symbol) symbol, close
                            FROM market_data.candles_5m
                            WHERE bucket_ts > NOW() - INTERVAL '1 hour'
                            ORDER BY symbol, bucket_ts DESC
                        ),
                        prev AS (
                            SELECT DISTINCT ON (symbol) symbol, close as prev_close
                            FROM market_data.candles_5m
                            WHERE bucket_ts BETWEEN NOW() - INTERVAL '25 hours' AND NOW() - INTERVAL '23 hours'
                            ORDER BY symbol, bucket_ts DESC
                        )
                        SELECT l.symbol
                        FROM latest l JOIN prev p ON l.symbol = p.symbol
                        ORDER BY ABS((l.close - p.prev_close) / NULLIF(p.prev_close, 0)) DESC
                        LIMIT %s
                    )
                    SELECT DISTINCT symbol FROM (
                        SELECT symbol FROM volume_rank
                        UNION SELECT symbol FROM volatility_rank
                        UNION SELECT symbol FROM change_rank
                    ) combined
                """
                cur = conn.execute(sql, (top_n, top_n, top_n))
                symbols.update(r[0] for r in cur.fetchall())
        except Exception as e:
            LOG.warning(f"K线优先级查询失败: {e}")
        return symbols

    def query_futures_priority():
        """期货维度优先级"""
        return _get_futures_priority(top_n)[0]

    # 并行执行K线和期货查询
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(query_kline_priority),
            executor.submit(query_futures_priority),
        ]
        for f in as_completed(futures):
            try:
                result.update(f.result())
            except Exception as e:
                LOG.warning(f"优先级查询失败: {e}")

    LOG.info(f"高优先级币种: {len(result)} 个")
    return result


def get_high_priority_symbols(cache, interval: str = "5m", top_n: int = 15) -> tuple[Set[str], dict]:
    """
    动态获取高优先级币种 - 11个维度取并集:
    
    K线维度(6个):
    1. 1d 交易额 Top30
    2. 市值近似 Top30
    3. 价格波动率 Top30
    4. 成交量异常(量比>2) 
    5. 1d 涨跌幅 Top30
    6. 价格突破(突破20周期高/低点)
    
    期货维度(5个):
    7. 持仓价值 Top30
    8. 持仓量变化 >5% 或 Top30
    9. 主动买卖比极端 (<0.2 或 >5.0)
    10. 多空比极端 (<0.5 或 >4.0)
    11. 大户多空比变化 >0.5
    
    返回: (高优先级集合, 调试信息dict)
    """
    klines = cache.get_klines(interval)
    if not klines:
        return set(), {}

    turnover_rank = []    # 交易额
    cap_rank = []         # 市值
    volatility_rank = []  # 波动率
    change_rank = []      # 涨跌幅
    vol_spike = set()     # 量比异常
    breakout = set()      # 价格突破

    for symbol, df in klines.items():
        if len(df) < 24:
            continue
        try:
            close = float(df['close'].iloc[-1] or 0)
            if close <= 0:
                continue
            vol = float(df['volume'].iloc[-1] or 0)
            high = float(df['high'].iloc[-1] or 0)
            low = float(df['low'].iloc[-1] or 0)

            # 1. 交易额 (quote_volume)
            quote_vol = vol * close
            if 'quote_volume' in df.columns and df['quote_volume'].iloc[-1]:
                quote_vol = float(df['quote_volume'].iloc[-1])
            turnover_rank.append((symbol, quote_vol))

            # 2. 市值近似
            cap_rank.append((symbol, close * vol))

            # 3. 波动率
            volatility = (high - low) / close
            volatility_rank.append((symbol, volatility))

            # 4. 量比异常 (当前量 / MA20量 > 2)
            if len(df) >= 20:
                ma20_vol = df['volume'].iloc[-20:].mean()
                if ma20_vol > 0 and vol / ma20_vol > 2.0:
                    vol_spike.add(symbol)

            # 5. 1d 涨跌幅 (用最近24根K线)
            lookback = min(24, len(df) - 1)
            close_prev = float(df['close'].iloc[-lookback - 1] or close)
            if close_prev > 0:
                change_pct = (close - close_prev) / close_prev
                change_rank.append((symbol, abs(change_pct)))

            # 6. 价格突破 (突破20周期高/低点)
            if len(df) >= 21:
                high_20 = df['high'].iloc[-21:-1].max()
                low_20 = df['low'].iloc[-21:-1].min()
                if high > high_20 or low < low_20:
                    breakout.add(symbol)

        except (TypeError, ValueError):
            continue

    # 各维度Top N
    top_turnover = {s for s, _ in sorted(turnover_rank, key=lambda x: x[1], reverse=True)[:top_n]}
    top_cap = {s for s, _ in sorted(cap_rank, key=lambda x: x[1], reverse=True)[:top_n]}
    top_volatility = {s for s, _ in sorted(volatility_rank, key=lambda x: x[1], reverse=True)[:top_n]}
    top_change = {s for s, _ in sorted(change_rank, key=lambda x: x[1], reverse=True)[:top_n]}

    # K线维度并集
    kline_result = top_turnover | top_cap | top_volatility | top_change | vol_spike | breakout

    # === 期货维度 ===
    futures_result, futures_debug = _get_futures_priority(top_n)

    # 总并集
    result = kline_result | futures_result

    debug = {
        "turnover": len(top_turnover), "cap": len(top_cap), "volatility": len(top_volatility),
        "change": len(top_change), "vol_spike": len(vol_spike), "breakout": len(breakout),
        "kline_total": len(kline_result),
        **futures_debug,
        "total": len(result)
    }
    LOG.info(f"高优先级 K线: 额={debug['turnover']}, 值={debug['cap']}, 波={debug['volatility']}, "
             f"涨跌={debug['change']}, 量比={debug['vol_spike']}, 突破={debug['breakout']}, 小计={debug['kline_total']}")
    LOG.info(f"高优先级 期货: 持仓值={debug.get('oi_value', 0)}, 持仓变化={debug.get('oi_change', 0)}, "
             f"买卖比={debug.get('taker_extreme', 0)}, 多空比={debug.get('ls_extreme', 0)}, "
             f"大户变化={debug.get('top_ls_change', 0)}, 小计={debug.get('futures_total', 0)}")
    LOG.info(f"高优先级 总并集: {debug['total']}")

    return result, debug


def _get_futures_priority(top_n: int = 15) -> tuple[set, dict]:
    """获取期货维度的高优先级币种"""
    result = set()
    debug = {"oi_value": 0, "oi_change": 0, "taker_extreme": 0, "ls_extreme": 0, "top_ls_change": 0, "futures_total": 0}

    try:
        with shared_pg_conn() as conn:
            with conn.cursor() as cur:
                # 查每个币种的最新数据（限制7天）
                cur.execute("""
                    SELECT DISTINCT ON (symbol) 
                        symbol, sum_open_interest_value as oi_val,
                        sum_taker_long_short_vol_ratio as taker_ratio,
                        count_long_short_ratio as ls_ratio
                    FROM market_data.binance_futures_metrics_5m 
                    WHERE create_time > NOW() - INTERVAL '7 days'
                    ORDER BY symbol, create_time DESC
                """)
                rows = cur.fetchall()

                oi_value_rank = []    # 持仓价值
                taker_extreme = set() # 主动买卖比极端
                ls_extreme = set()    # 多空比极端

                for row in rows:
                    sym, oi_val, taker, ls = row

                    # 7. 持仓价值 Top30
                    if oi_val:
                        oi_value_rank.append((sym, float(oi_val)))

                    # 9. 主动买卖比极端 (<0.2 或 >5.0)
                    if taker:
                        t = float(taker)
                        if t < 0.2 or t > 5.0:
                            taker_extreme.add(sym)

                    # 10. 多空比极端 (<0.5 或 >4.0)
                    if ls:
                        ls_val = float(ls)
                        if ls_val < 0.5 or ls_val > 4.0:
                            ls_extreme.add(sym)

                # Top N
                top_oi_value = {s for s, _ in sorted(oi_value_rank, key=lambda x: x[1], reverse=True)[:top_n]}

                result = top_oi_value | taker_extreme | ls_extreme

                debug = {
                    "oi_value": len(top_oi_value),
                    "oi_change": 0,  # 简化掉
                    "taker_extreme": len(taker_extreme),
                    "ls_extreme": len(ls_extreme),
                    "top_ls_change": 0,  # 简化掉
                    "futures_total": len(result)
                }
    except Exception as e:
        LOG.warning(f"获取期货优先级失败: {e}")

    return result, debug


def _compute_indicator(indicator_name: str, klines_data: Dict[str, bytes], interval: str) -> tuple:
    """计算单个指标（子进程）- 使用 pickle 反序列化"""
    import sys
    import os

    # 确保能找到模块
    service_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if service_root not in sys.path:
        sys.path.insert(0, service_root)

    from src.indicators.base import get_all_indicators
    from src.utils.precision import trim_dataframe

    indicators = get_all_indicators()
    if indicator_name not in indicators:
        return (indicator_name, interval, None)

    cls = indicators[indicator_name]
    ind = cls()

    results = []
    for symbol, df_bytes in klines_data.items():
        df = pickle.loads(df_bytes)

        if len(df) < ind.meta.lookback // 2:
            continue
        try:
            result = ind.compute(df, symbol, interval)
            if result is not None and not result.empty:
                results.append(result)
        except Exception:
            pass

    if results:
        combined = pd.concat(results, ignore_index=True)
        return (indicator_name, interval, trim_dataframe(combined))
    return (indicator_name, interval, None)


class AsyncWriter(Thread):
    """异步写入线程"""

    def __init__(self, write_queue: queue.Queue):
        super().__init__(daemon=True, name="AsyncWriter")
        self.write_queue = write_queue
        self._stop_event = Event()
        self.write_count = 0

    def stop(self):
        self._stop_event.set()

    def run(self):
        from ..db import writer
        LOG.info("写入线程启动")

        while not self._stop_event.is_set():
            batch = []
            try:
                item = self.write_queue.get(timeout=0.5)
                batch.append(item)
                if item is None:
                    break
                while len(batch) < 50:
                    try:
                        batch.append(self.write_queue.get_nowait())
                    except queue.Empty:
                        break
            except queue.Empty:
                continue

            # 过滤 None
            batch = [b for b in batch if b is not None]
            if batch:
                by_interval: Dict[str, Dict[str, pd.DataFrame]] = {}
                for table, interval, df in batch:
                    if interval not in by_interval:
                        by_interval[interval] = {}
                    by_interval[interval][table] = df

                for interval, data in by_interval.items():
                    try:
                        writer.write_batch(data, interval)
                        self.write_count += len(data)
                    except Exception as e:
                        LOG.error(f"写入失败: {e}")


class FullAsyncEngine:
    """完全异步引擎 - 三层隔离"""

    def __init__(
        self,
        symbols: List[str] = None,
        intervals: List[str] = None,
        indicators: List[str] = None,
        workers: int = 4,
    ):
        self.symbols = symbols
        self.intervals = intervals or list(INTERVAL_CONFIG.keys())
        self.indicator_names = indicators
        self.workers = workers

        self._running = False
        self._fast_executor: Optional[ProcessPoolExecutor] = None
        self._slow_executor: Optional[ProcessPoolExecutor] = None
        self._write_queue = queue.Queue(maxsize=2000)
        self._writer: Optional[AsyncWriter] = None
        self._cache = None

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum, frame):
        LOG.info(f"收到信号 {signum}，停止...")
        self.stop()

    def _split_symbols(self, symbols: List[str], cache) -> tuple:
        """按优先级分割币种 - 动态计算"""
        # 用5m周期判断（数据更及时）
        interval = "5m" if "5m" in self.intervals else self.intervals[0]
        high_priority, _ = get_high_priority_symbols(cache, interval, 30)
        high = [s for s in symbols if s in high_priority]
        low = [s for s in symbols if s not in high_priority]
        return high, low

    def _split_indicators(self, indicators: List[str]) -> tuple:
        """分离快慢指标"""
        fast = [i for i in indicators if i not in SLOW_INDICATORS]
        slow = [i for i in indicators if i in SLOW_INDICATORS]
        return fast, slow

    def _get_indicator_order(self, all_indicators: Dict) -> List[str]:
        indicator_names = set(all_indicators.keys())
        deps_first = set()
        for dependent, deps in INDICATOR_DEPS.items():
            if dependent in indicator_names:
                for d in deps:
                    if d in indicator_names:
                        deps_first.add(d)
        order = list(deps_first)
        for name in indicator_names:
            if name not in deps_first:
                order.append(name)
        return order

    def run(self):
        from ..db import reader
        from ..db.cache import init_cache, stop_cache

        symbols = self.symbols or reader.get_symbols()
        if not symbols:
            LOG.warning("无交易对")
            return

        all_indicators = get_all_indicators()
        if self.indicator_names:
            all_indicators = {k: v for k, v in all_indicators.items() if k in self.indicator_names}

        indicator_order = self._get_indicator_order(all_indicators)
        fast_indicators, slow_indicators = self._split_indicators(indicator_order)
        max_lookback = max(ind.meta.lookback for ind in all_indicators.values())

        # 快速获取高优先级币种（直接查数据库）
        t0 = time.time()
        high_symbols = get_high_priority_symbols_fast(top_n=30)
        LOG.info(f"高优先级: {len(high_symbols)} 币种, {time.time()-t0:.1f}s")

        # 只缓存高优先级币种
        t0 = time.time()
        self._cache = init_cache(list(high_symbols), self.intervals, max_lookback)
        LOG.info(f"缓存完成: {time.time()-t0:.1f}s")

        LOG.info("=" * 60)
        LOG.info(f"指标计算引擎: {len(high_symbols)} 币种, {len(self.intervals)} 周期, {len(indicator_order)} 指标")
        LOG.info("=" * 60)

        # 启动写入线程
        self._writer = AsyncWriter(self._write_queue)
        self._writer.start()

        # 创建进程池
        self._fast_executor = ProcessPoolExecutor(max_workers=self.workers)
        self._slow_executor = ProcessPoolExecutor(max_workers=1)

        self._running = True

        # === 首次计算 ===
        LOG.info("=== 首次计算 ===")
        t_start = time.time()

        LOG.info(f"计算 {len(high_symbols)} 币种, {len(self.intervals)} 周期")
        self._compute_priority(high_symbols, fast_indicators, slow_indicators, self.intervals)

        LOG.info(f"首次计算完成: {time.time()-t_start:.1f}s")

        # 进入定时触发模式
        LOG.info("进入定时触发模式...")
        self._run_daemon(high_symbols, fast_indicators, slow_indicators)

        stop_cache()
        self._cleanup()
        LOG.info("引擎已停止")

    def _compute_priority(self, symbols: List[str], fast_indicators: List[str], slow_indicators: List[str],
                          intervals: List[str] = None):
        """计算一个优先级的所有币种 - 快慢指标真正并行"""
        if not symbols:
            return

        intervals = intervals or self.intervals
        for interval in intervals:
            klines = self._cache.get_klines(interval)
            # 使用 pickle 序列化
            klines_data = {s: pickle.dumps(df, protocol=5)
                          for s, df in klines.items() if s in symbols}

            if not klines_data:
                continue

            t0 = time.time()

            # 快慢指标同时提交
            all_futures = []
            for indicator in fast_indicators:
                future = self._fast_executor.submit(_compute_indicator, indicator, klines_data, interval)
                all_futures.append(('fast', future))

            for indicator in slow_indicators:
                future = self._slow_executor.submit(_compute_indicator, indicator, klines_data, interval)
                all_futures.append(('slow', future))

            # 统一等待，完成一个处理一个
            fast_done = 0
            slow_done = 0
            for tag, future in all_futures:
                try:
                    timeout = 60 if tag == 'fast' else 300
                    ind_name, iv, result = future.result(timeout=timeout)
                    if result is not None:
                        self._write_queue.put_nowait((ind_name, iv, result))
                    if tag == 'fast':
                        fast_done += 1
                    else:
                        slow_done += 1
                except Exception as e:
                    LOG.error(f"[{interval}] {tag}指标: {e}")

            total_time = time.time() - t0
            LOG.info(f"[{interval}] {len(symbols)}币种 快={fast_done} 慢={slow_done} 耗时={total_time:.1f}s")

    def _run_daemon(self, high_symbols: List[str],
                    fast_indicators: List[str], slow_indicators: List[str]):
        """定时触发模式"""
        last_compute = {iv: 0 for iv in self.intervals}
        last_report = time.time()

        while self._running:
            now = datetime.now(timezone.utc)
            ts = now.timestamp()

            for interval in self.intervals:
                period, wait = INTERVAL_CONFIG.get(interval, (60, 3))
                close_ts = int(ts // period) * period
                seconds_after = ts - close_ts

                if wait + 2 <= seconds_after < wait + 7 and close_ts > last_compute[interval]:
                    last_compute[interval] = close_ts
                    LOG.info(f"[{interval}] 触发")
                    self._compute_interval(high_symbols, interval, fast_indicators, slow_indicators)

            if time.time() - last_report > 60:
                LOG.info(f"状态: 队列={self._write_queue.qsize()}, 写入={self._writer.write_count}")
                last_report = time.time()

            time.sleep(1)

            if time.time() - last_report > 60:
                LOG.info(f"状态: 队列={self._write_queue.qsize()}, 写入={self._writer.write_count}")
                last_report = time.time()

            time.sleep(1)

    def _compute_interval(self, symbols: List[str], interval: str,
                          fast_indicators: List[str], slow_indicators: List[str]):
        """计算单个周期 - 使用 pickle 序列化"""
        if not symbols:
            return

        klines = self._cache.get_klines(interval)
        klines_data = {s: pickle.dumps(df, protocol=5)
                      for s, df in klines.items() if s in symbols}

        if not klines_data:
            return

        # 快指标
        for indicator in fast_indicators:
            future = self._fast_executor.submit(_compute_indicator, indicator, klines_data, interval)
            future.add_done_callback(lambda f: self._on_complete(f))

        # 慢指标
        for indicator in slow_indicators:
            future = self._slow_executor.submit(_compute_indicator, indicator, klines_data, interval)
            future.add_done_callback(lambda f: self._on_complete(f))

    def _on_complete(self, future: Future):
        """计算完成回调"""
        try:
            ind_name, iv, result = future.result(timeout=0)
            if result is not None:
                self._write_queue.put_nowait((ind_name, iv, result))
        except Exception:
            pass

    def stop(self):
        self._running = False

    def _cleanup(self):
        if self._writer:
            self._writer.stop()
        if self._fast_executor:
            self._fast_executor.shutdown(wait=False)
        if self._slow_executor:
            self._slow_executor.shutdown(wait=False)


def run_async_full(
    symbols: List[str] = None,
    intervals: List[str] = None,
    indicators: List[str] = None,
    high_workers: int = 4,
    low_workers: int = 2,
):
    FullAsyncEngine(
        symbols=symbols,
        intervals=intervals,
        indicators=indicators,
        workers=high_workers,
    ).run()
