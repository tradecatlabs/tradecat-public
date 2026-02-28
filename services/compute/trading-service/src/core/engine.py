"""
计算引擎（高性能版）

核心优化：
1. 多周期并行读取数据
2. 多进程并行计算（按周期+币种分片）
3. 使用 pickle 协议5 优化序列化
4. 进程池复用
5. 一次性写入所有结果
6. 可观测性：日志、指标、Tracing、告警
"""
import time
import pickle
from multiprocessing import cpu_count
from typing import List
from ..config import config
from ..indicators.base import get_all_indicators, get_batch_indicators, get_incremental_indicators
from ..utils.precision import trim_dataframe
from ..observability import get_logger, metrics, trace, alert, AlertLevel

LOG = get_logger("indicator_service")

# 指标定义
_compute_total = metrics.counter("indicator_compute_total", "指标计算总次数")
_compute_errors = metrics.counter("indicator_compute_errors", "指标计算错误次数")
_compute_duration = metrics.histogram("indicator_compute_duration_seconds", "指标计算耗时", (0.5, 1, 2, 5, 10, 30, 60))
_db_read_duration = metrics.histogram("db_read_duration_seconds", "数据库读取耗时", (0.5, 1, 2, 5, 10, 30))
_db_write_duration = metrics.histogram("db_write_duration_seconds", "数据库写入耗时", (0.1, 0.5, 1, 2, 5))
_active_symbols = metrics.gauge("active_symbols", "活跃交易对数量")
_last_compute_ts = metrics.gauge("last_compute_timestamp", "最后计算时间戳")

# 全局进程池（复用）
class Engine:
    """指标计算引擎（高性能版）"""

    def __init__(
        self,
        symbols: List[str] = None,
        intervals: List[str] = None,
        indicators: List[str] = None,
        lookback: int = None,
        max_workers: int = None,
        compute_backend: str = None,
    ):
        self.symbols = symbols
        self.intervals = intervals or config.intervals
        self.indicator_names = indicators
        self.lookback = lookback or config.default_lookback
        self.max_workers = max_workers or min(cpu_count(), 8)
        self.compute_backend = (compute_backend or config.compute_backend or "thread").lower()

    def run(self, mode: str = "all"):
        """运行计算 - 使用缓存，只读取一次"""
        from ..db.reader import get_db_counters
        from .io import load_klines, preload_futures_cache
        from .compute import compute_all
        from .storage import write_results
        with trace("engine.run", mode=mode) as span:
            start = time.time()
            db_counters_start = get_db_counters()

            # 使用传入的币种，或自动获取高优先级
            if self.symbols:
                symbols = self.symbols
            else:
                from .async_full_engine import get_high_priority_symbols_fast
                t_priority = time.time()
                high_symbols = get_high_priority_symbols_fast(top_n=15)
                if not high_symbols:
                    LOG.warning("无高优先级币种")
                    alert(AlertLevel.WARNING, "无高优先级币种", "获取高优先级币种失败，计算终止")
                    return
                symbols = list(high_symbols)
                LOG.info(f"高优先级币种: {len(symbols)} 个, 耗时 {time.time()-t_priority:.1f}s")

            _active_symbols.set(len(symbols))
            span.set_tag("symbols_count", len(symbols))

            if mode == "batch":
                indicators = get_batch_indicators()
            elif mode == "incremental":
                indicators = get_incremental_indicators()
            else:
                indicators = get_all_indicators()

            if self.indicator_names:
                indicators = {k: v for k, v in indicators.items() if k in self.indicator_names}

            if not indicators:
                LOG.warning("无指标需要计算")
                return

            max_lookback = max(ind.meta.lookback for ind in indicators.values())
            span.set_tag("indicators_count", len(indicators))

            LOG.info(f"开始计算: {len(symbols)} 币种, {len(self.intervals)} 周期, {len(indicators)} 指标, {self.max_workers} 进程")

            # 使用缓存 - 检查是否需要初始化或更新
            with trace("db.read") as read_span:
                t0 = time.time()
                all_klines = load_klines(symbols, self.intervals, max_lookback)

                t_read = time.time() - t0
                _db_read_duration.observe(t_read)
                read_span.set_tag("klines_count", len(all_klines))

            LOG.info(f"数据读取完成: {len(all_klines)} 组, 耗时 {t_read:.1f}s")

            if not all_klines:
                LOG.warning("无K线数据")
                alert(AlertLevel.WARNING, "无K线数据", "数据库中无可用K线数据")
                return

            # 准备计算任务 - 线程模式直接传 DataFrame，进程模式使用 pickle
            use_pickle = self.compute_backend == "process"
            task_list = [
                (sym, iv, pickle.dumps(df, protocol=5) if use_pickle else df)
                for (sym, iv), df in all_klines.items()
            ]

            # 预加载期货缓存
            futures_cache = preload_futures_cache(symbols, self.intervals, indicators)

            # 分片并行计算
            with trace("compute") as compute_span:
                t1 = time.time()
                indicator_names = list(indicators.keys())
                all_results = compute_all(
                    task_list,
                    indicator_names,
                    indicators,
                    futures_cache,
                    backend=self.compute_backend,
                    max_workers=self.max_workers,
                    max_io_workers=config.max_io_workers,
                    max_cpu_workers=config.max_cpu_workers,
                    compute_errors=_compute_errors,
                    logger=LOG,
                )

                t_compute = time.time() - t1
                _compute_duration.observe(t_compute)
                compute_span.set_tag("duration_s", round(t_compute, 2))

            # 写入数据库
            with trace("db.write") as write_span:
                t2 = time.time()
                # 写入 PG tg_cards（每个指标一张表，全量覆盖）
                write_results(all_results)
                t_write = time.time() - t2
                _db_write_duration.observe(t_write)
                write_span.set_tag("duration_s", round(t_write, 2))

            db_counters_end = get_db_counters()
            pg_queries = db_counters_end["pg_query_total"] - db_counters_start["pg_query_total"]
            LOG.info("DB压力: pg_queries=%s", pg_queries)

            total_rows = sum(len(recs) for recs_list in all_results.values() for recs in recs_list)
            total_time = time.time() - start

            # 更新指标
            _compute_total.inc(total_rows)
            _last_compute_ts.set(time.time())

            span.set_tag("total_rows", total_rows)
            span.set_tag("total_time_s", round(total_time, 2))

            LOG.info(f"计算完成: 读取={t_read:.1f}s, 计算={t_compute:.1f}s, 写入={t_write:.2f}s, {total_rows}行, 总耗时 {total_time:.2f}s")

            # 慢计算告警
            if total_time > 120:
                alert(AlertLevel.WARNING, "计算耗时过长", f"总耗时 {total_time:.1f}s 超过阈值", symbols=len(symbols), rows=total_rows)

    def run_single(self, symbol: str, interval: str, indicator_name: str):
        """单次增量计算 - 走缓存"""
        from ..db.cache import get_cache
        from .storage import write_indicator_result

        ind_cls = get_all_indicators().get(indicator_name)
        if not ind_cls:
            return

        indicator = ind_cls()
        cache = get_cache()
        klines = cache.get_klines(interval, symbol)
        if symbol not in klines:
            return

        result = indicator.compute(klines[symbol], symbol, interval)
        if result is not None and not result.empty:
            result = trim_dataframe(result)
            write_indicator_result(indicator.meta.name, result, interval)
