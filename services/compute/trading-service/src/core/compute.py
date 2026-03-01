"""
计算模块：指标计算与并行调度
"""
import pickle
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from multiprocessing import cpu_count
from typing import Dict, List, Tuple, Optional


# ==================== 进程池复用 ====================

_executor: ProcessPoolExecutor = None


def _get_executor(max_workers: int) -> ProcessPoolExecutor:
    """获取或创建进程池"""
    global _executor
    if _executor is None:
        _executor = ProcessPoolExecutor(max_workers=max_workers)
    return _executor


# ==================== 计算核心 ====================

def compute_batch(args: Tuple) -> Dict[str, List[dict]]:
    """计算一批 (symbol, interval, df_bytes) 的所有指标"""
    import sys
    import os

    # 确保能找到模块
    service_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if service_root not in sys.path:
        sys.path.insert(0, service_root)

    from src.indicators.base import get_all_indicators

    batch, indicator_names, futures_cache = args

    # 设置期货缓存
    if futures_cache:
        try:
            from src.indicators.incremental.futures_sentiment import set_metrics_cache
            latest_cache = futures_cache.get("latest_metrics") if isinstance(futures_cache, dict) else futures_cache
            if latest_cache:
                set_metrics_cache(latest_cache)
        except ImportError:
            pass
        try:
            from src.indicators.batch.futures_aggregate import set_history_cache
            history_cache = futures_cache.get("history") if isinstance(futures_cache, dict) else None
            if history_cache:
                set_history_cache(history_cache)
        except ImportError:
            pass
        try:
            from src.indicators.batch.futures_gap_monitor import set_times_cache
            times_cache = futures_cache.get("times") if isinstance(futures_cache, dict) else None
            if times_cache:
                set_times_cache(times_cache)
        except ImportError:
            pass

    indicators = get_all_indicators()
    if indicator_names:
        indicators = {k: v for k, v in indicators.items() if k in indicator_names}

    results = {name: [] for name in indicators}
    indicator_instances = {name: cls() for name, cls in indicators.items()}

    for symbol, interval, df_bytes in batch:
        # 反序列化 DataFrame（兼容已序列化和未序列化）
        df = pickle.loads(df_bytes) if isinstance(df_bytes, bytes) else df_bytes
        last_ts = df.index[-1].isoformat() if len(df) > 0 and hasattr(df.index[-1], "isoformat") else None

        for name, ind in indicator_instances.items():
            allow_placeholder = getattr(ind.meta, "allow_placeholder", True)
            placeholder = (
                [{"交易对": symbol, "周期": interval, "数据时间": last_ts, "指标": None}]
                if (allow_placeholder and last_ts)
                else None
            )

            if len(df) < ind.meta.lookback // 2:
                if placeholder:
                    results[name].append(placeholder)
                continue
            try:
                result = ind.compute(df, symbol, interval)
                if result is not None and not result.empty:
                    results[name].append(result.to_dict("records"))
                elif placeholder:
                    results[name].append(placeholder)
            except Exception:
                if placeholder:
                    results[name].append(placeholder)

    return results


def compute_parallel(
    task_list: list,
    indicator_names: list,
    indicators: dict,
    futures_cache: dict = None,
    backend: str = "thread",
    max_workers: Optional[int] = None,
    max_io_workers: Optional[int] = None,
    max_cpu_workers: Optional[int] = None,
    compute_errors=None,
    logger=None,
) -> Dict[str, list]:
    """并行计算"""
    worker_count = max_workers or max(1, min(cpu_count(), 8))
    batch_size = max(1, len(task_list) // worker_count)
    batches = []
    for i in range(0, len(task_list), batch_size):
        batch = task_list[i:i + batch_size]
        batches.append((batch, indicator_names, futures_cache))

    all_results = {name: [] for name in indicators}

    if backend == "thread":
        with ThreadPoolExecutor(max_workers=max_io_workers) as executor:
            futures = [executor.submit(compute_batch, batch) for batch in batches]
            for future in as_completed(futures):
                try:
                    batch_results = future.result()
                    for name, records_list in batch_results.items():
                        all_results[name].extend(records_list)
                except Exception as exc:
                    if compute_errors:
                        compute_errors.inc(1, backend="thread")
                    if logger:
                        logger.error("计算失败: %s", exc)
    elif backend == "process":
        executor = _get_executor(max_cpu_workers)
        futures = [executor.submit(compute_batch, batch) for batch in batches]
        for future in as_completed(futures):
            try:
                batch_results = future.result()
                for name, records_list in batch_results.items():
                    all_results[name].extend(records_list)
            except Exception as exc:
                if compute_errors:
                    compute_errors.inc(1, backend="process")
                if logger:
                    logger.error("计算失败: %s", exc)
    else:
        # hybrid: 小批量用线程，大批量用进程
        if len(task_list) <= 50:
            return compute_parallel(
                task_list,
                indicator_names,
                indicators,
                futures_cache,
                backend="thread",
                max_workers=worker_count,
                max_io_workers=max_io_workers,
                max_cpu_workers=max_cpu_workers,
                compute_errors=compute_errors,
                logger=logger,
            )
        return compute_parallel(
            task_list,
            indicator_names,
            indicators,
            futures_cache,
            backend="process",
            max_workers=worker_count,
            max_io_workers=max_io_workers,
            max_cpu_workers=max_cpu_workers,
            compute_errors=compute_errors,
            logger=logger,
        )

    return all_results


def compute_all(
    task_list: list,
    indicator_names: list,
    indicators: dict,
    futures_cache: dict = None,
    backend: str = "thread",
    max_workers: Optional[int] = None,
    max_io_workers: Optional[int] = None,
    max_cpu_workers: Optional[int] = None,
    compute_errors=None,
    logger=None,
) -> Dict[str, list]:
    """按任务规模选择单批或并行计算"""
    if len(task_list) <= 20:
        return compute_batch((task_list, indicator_names, futures_cache))
    return compute_parallel(
        task_list,
        indicator_names,
        indicators,
        futures_cache,
        backend=backend,
        max_workers=max_workers,
        max_io_workers=max_io_workers,
        max_cpu_workers=max_cpu_workers,
        compute_errors=compute_errors,
        logger=logger,
    )
