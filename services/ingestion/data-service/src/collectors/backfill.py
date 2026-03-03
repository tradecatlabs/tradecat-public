"""数据补齐系统 - K线 + 期货指标

功能：
1. 精确缺口检测 (按条数，非按日期)
2. REST 分页补齐 (CCXT)
3. ZIP 历史补齐 (Binance Vision)
4. 补齐后复检
5. 持续巡检模式
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from adapters.ccxt import fetch_ohlcv, load_symbols, to_rows
from adapters.metrics import Timer, metrics
from adapters.rate_limiter import acquire, parse_ban, release, set_ban
from adapters.timescale import TimescaleAdapter
from config import INTERVAL_TO_MS, settings

logger = logging.getLogger(__name__)

BINANCE_DATA_URL = settings.binance_data_base
EXPECTED_1M_PER_DAY = 1440  # 1分钟 * 1440 = 1天
EXPECTED_5M_PER_DAY = 288   # 5分钟 * 288 = 1天


# ==================== 缺口检测 ====================
@dataclass
class GapInfo:
    """缺口信息"""
    symbol: str
    date: date
    expected: int
    actual: int
    missing: int = field(init=False)

    def __post_init__(self):
        self.missing = self.expected - self.actual


class GapScanner:
    """精确缺口扫描器"""

    def __init__(self, ts: TimescaleAdapter):
        self._ts = ts

    def scan_klines(self, symbols: Sequence[str], start: date, end: date,
                    interval: str = "1m", threshold: float = 0.95) -> Dict[str, List[GapInfo]]:
        """扫描 K 线缺口，返回 {symbol: [GapInfo]}"""
        expected = EXPECTED_1M_PER_DAY if interval == "1m" else int(EXPECTED_1M_PER_DAY / INTERVAL_TO_MS.get(interval, 60000) * 60000)
        min_count = int(expected * threshold)

        table = f"{self._ts.schema}.candles_{interval}"
        sql = f"""
            SELECT symbol, DATE(bucket_ts AT TIME ZONE 'UTC') AS d, COUNT(*) AS c
            FROM {table}
            WHERE exchange = %s AND symbol = ANY(%s)
              AND bucket_ts >= %s AND bucket_ts < %s
            GROUP BY symbol, DATE(bucket_ts AT TIME ZONE 'UTC')
        """
        start_ts = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
        end_ts = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)

        counts: Dict[tuple, int] = {}
        with self._ts.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (settings.db_exchange, list(symbols), start_ts, end_ts))
                for sym, d, c in cur.fetchall():
                    counts[(sym, d)] = c

        gaps: Dict[str, List[GapInfo]] = {}
        for sym in symbols:
            sym_gaps = []
            for i in range((end - start).days + 1):
                d = start + timedelta(days=i)
                actual = counts.get((sym, d), 0)
                if actual < min_count:
                    sym_gaps.append(GapInfo(sym, d, expected, actual))
            if sym_gaps:
                gaps[sym] = sym_gaps
        return gaps

    def scan_metrics(self, symbols: Sequence[str], start: date, end: date,
                     threshold: float = 0.95) -> Dict[str, List[GapInfo]]:
        """扫描期货指标缺口"""
        min_count = int(EXPECTED_5M_PER_DAY * threshold)

        table = f"{self._ts.schema}.binance_futures_metrics_5m"
        sql = f"""
            SELECT symbol, DATE(create_time) AS d, COUNT(*) AS c
            FROM {table}
            WHERE symbol = ANY(%s) AND create_time >= %s AND create_time < %s
            GROUP BY symbol, DATE(create_time)
        """
        start_ts = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
        end_ts = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)

        counts: Dict[tuple, int] = {}
        with self._ts.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (list(symbols), start_ts, end_ts))
                for sym, d, c in cur.fetchall():
                    counts[(sym, d)] = c

        gaps: Dict[str, List[GapInfo]] = {}
        for sym in symbols:
            sym_gaps = []
            for i in range((end - start).days + 1):
                d = start + timedelta(days=i)
                actual = counts.get((sym, d), 0)
                if actual < min_count:
                    sym_gaps.append(GapInfo(sym, d, EXPECTED_5M_PER_DAY, actual))
            if sym_gaps:
                gaps[sym] = sym_gaps
        return gaps


# ==================== REST 分页补齐 ====================
class RestBackfiller:
    """REST API 分页补齐 (用于小缺口) - 并行版"""

    def __init__(self, ts: TimescaleAdapter, workers: Optional[int] = None):
        self._ts = ts
        if workers is None:
            raw = (os.getenv("DATA_SERVICE_REST_BACKFILL_WORKERS") or "").strip()
            if raw:
                try:
                    workers = int(raw)
                except ValueError:
                    workers = 2
            else:
                workers = 2
        self._workers = max(1, min(int(workers), 20))

    def fill_kline_gap(self, symbol: str, gap: GapInfo, interval: str = "1m") -> int:
        """补齐单个 K 线缺口 - 收集后一次性写入"""
        start_ts = datetime.combine(gap.date, datetime.min.time(), tzinfo=timezone.utc)
        end_ts = datetime.combine(gap.date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        since_ms = int(start_ts.timestamp() * 1000)
        target_ms = int(end_ts.timestamp() * 1000)

        all_rows = []  # 收集所有数据
        max_iterations = 100

        for _ in range(max_iterations):
            candles = fetch_ohlcv(settings.ccxt_exchange, symbol, interval, since_ms, 1000)
            if not candles:
                break

            rows = [r for r in to_rows(settings.db_exchange, symbol, candles, "ccxt_gap")
                    if start_ts <= r["bucket_ts"] < end_ts]
            all_rows.extend(rows)

            last_ms = int(candles[-1][0])
            if last_ms == since_ms or last_ms >= target_ms:
                break
            since_ms = last_ms + INTERVAL_TO_MS.get(interval, 60000)

        # 一次性写入
        if all_rows:
            self._ts.upsert_candles(interval, all_rows, update_on_conflict=False)
        return len(all_rows)

    def fill_gaps(self, gaps: Dict[str, List[GapInfo]], interval: str = "1m") -> int:
        """并行批量补齐缺口"""
        tasks = [(sym, gap, interval) for sym, sym_gaps in gaps.items() for gap in sym_gaps]
        if not tasks:
            return 0

        total = 0
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            futures = {pool.submit(self.fill_kline_gap, sym, gap, iv): (sym, gap.date) for sym, gap, iv in tasks}
            for future in as_completed(futures):
                sym, d = futures[future]
                try:
                    n = future.result()
                    if n > 0:
                        logger.info("[%s] %s REST补齐 %d 条", sym, d, n)
                        total += n
                except Exception as e:
                    logger.warning("[%s] %s REST失败: %s", sym, d, e)
        return total


# ==================== Metrics REST 补齐 ====================
class MetricsRestBackfiller:
    """Metrics REST API 补齐 (用于 ZIP 未产出的近日数据)"""

    FAPI = settings.binance_fapi_base

    def __init__(self, ts: TimescaleAdapter, workers: int = 3):
        self._ts = ts
        self._workers = workers
        self._proxies = {"http": settings.http_proxy, "https": settings.http_proxy} if settings.http_proxy else {}
        self._session = requests.Session()

    def _get(self, url: str, params: dict) -> Optional[list]:
        """REST 请求"""
        acquire(1)
        try:
            r = self._session.get(url, params=params, proxies=self._proxies, timeout=15)
            if r.status_code == 429:
                retry_after = int(r.headers.get("Retry-After", 60))
                set_ban(time.time() + retry_after)
                return None
            if r.status_code == 418:
                retry_after = int(r.headers.get("Retry-After", 0))
                ban_time = parse_ban(r.text) if not retry_after else time.time() + retry_after
                set_ban(ban_time if ban_time > time.time() else time.time() + 120)
                return None
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.debug("Metrics REST 请求失败: %s", e)
            return None
        finally:
            release()

    def _fetch_day(self, symbol: str, d: date) -> List[dict]:
        """获取单日 Metrics 数据 (5个API)"""
        start_ms = int(datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc).timestamp() * 1000)
        end_ms = start_ms + 86400000 - 1  # 当天结束

        apis = [
            ("oi", f"{self.FAPI}/futures/data/openInterestHist", {"symbol": symbol, "period": "5m", "startTime": start_ms, "endTime": end_ms, "limit": 500}),
            ("pos", f"{self.FAPI}/futures/data/topLongShortPositionRatio", {"symbol": symbol, "period": "5m", "startTime": start_ms, "endTime": end_ms, "limit": 500}),
            ("acc", f"{self.FAPI}/futures/data/topLongShortAccountRatio", {"symbol": symbol, "period": "5m", "startTime": start_ms, "endTime": end_ms, "limit": 500}),
            ("glb", f"{self.FAPI}/futures/data/globalLongShortAccountRatio", {"symbol": symbol, "period": "5m", "startTime": start_ms, "endTime": end_ms, "limit": 500}),
            ("taker", f"{self.FAPI}/futures/data/takerlongshortRatio", {"symbol": symbol, "period": "5m", "startTime": start_ms, "endTime": end_ms, "limit": 500}),
        ]

        results = {}
        for key, url, params in apis:
            results[key] = self._get(url, params) or []

        # 以 oi 为基准合并
        oi_list = results.get("oi", [])
        if not oi_list:
            return []

        # 构建时间戳索引
        pos_map = {r.get("timestamp"): r for r in results.get("pos", [])}
        acc_map = {r.get("timestamp"): r for r in results.get("acc", [])}
        glb_map = {r.get("timestamp"): r for r in results.get("glb", [])}
        taker_map = {r.get("timestamp"): r for r in results.get("taker", [])}

        rows = []
        for oi in oi_list:
            ts = oi.get("timestamp", 0)
            ts_aligned = (ts // 300000) * 300000
            pos = pos_map.get(ts, {})
            acc = acc_map.get(ts, {})
            glb = glb_map.get(ts, {})
            taker = taker_map.get(ts, {})

            rows.append({
                "create_time": datetime.fromtimestamp(ts_aligned / 1000, tz=timezone.utc).replace(tzinfo=None),
                "symbol": symbol.upper(),
                "exchange": settings.db_exchange,
                "sum_open_interest": Decimal(str(oi.get("sumOpenInterest", 0))) if oi.get("sumOpenInterest") else None,
                "sum_open_interest_value": Decimal(str(oi.get("sumOpenInterestValue", 0))) if oi.get("sumOpenInterestValue") else None,
                "count_toptrader_long_short_ratio": Decimal(str(acc.get("longShortRatio", 0))) if acc.get("longShortRatio") else None,
                "sum_toptrader_long_short_ratio": Decimal(str(pos.get("longShortRatio", 0))) if pos.get("longShortRatio") else None,
                "count_long_short_ratio": Decimal(str(glb.get("longShortRatio", 0))) if glb.get("longShortRatio") else None,
                "sum_taker_long_short_vol_ratio": Decimal(str(taker.get("buySellRatio", 0))) if taker.get("buySellRatio") else None,
                "source": "binance_rest",
                "is_closed": True,
            })
        return rows

    def fill_gap(self, symbol: str, gap: GapInfo) -> int:
        """补齐单个缺口"""
        rows = self._fetch_day(symbol, gap.date)
        if rows:
            self._ts.upsert_metrics(rows)
            return len(rows)
        return 0

    def fill_gaps(self, gaps: Dict[str, List[GapInfo]]) -> int:
        """并行批量补齐"""
        tasks = [(sym, gap) for sym, sym_gaps in gaps.items() for gap in sym_gaps]
        if not tasks:
            return 0

        total = 0
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            futures = {pool.submit(self.fill_gap, sym, gap): (sym, gap.date) for sym, gap in tasks}
            for future in as_completed(futures):
                sym, d = futures[future]
                try:
                    n = future.result()
                    if n > 0:
                        logger.info("[%s] %s Metrics REST补齐 %d 条", sym, d, n)
                        total += n
                except Exception as e:
                    logger.warning("[%s] %s Metrics REST失败: %s", sym, d, e)
        return total


# ==================== ZIP 历史补齐 ====================
class ZipBackfiller:
    """Binance Vision ZIP 补齐 - 智能颗粒度 + 代理重试"""

    MAX_CACHE_DAYS = 7  # ZIP 文件最大缓存天数

    def __init__(self, ts: TimescaleAdapter, workers: int = 8):
        self._ts = ts
        self.workers = workers
        self._kline_dir = settings.data_dir / "downloads" / "klines"
        self._metrics_dir = settings.data_dir / "downloads" / "metrics"
        self._kline_dir.mkdir(parents=True, exist_ok=True)
        self._metrics_dir.mkdir(parents=True, exist_ok=True)
        self._proxies = {"http": settings.http_proxy, "https": settings.http_proxy} if settings.http_proxy else {}
        self._fallback_proxies = self._proxies  # 使用相同代理，不硬编码备用

    def cleanup_old_files(self, max_age_days: int = None) -> int:
        """清理过期的 ZIP 文件"""
        max_age = max_age_days or self.MAX_CACHE_DAYS
        cutoff = time.time() - max_age * 86400
        removed = 0
        for d in [self._kline_dir, self._metrics_dir]:
            for f in d.glob("*.zip"):
                try:
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
                        removed += 1
                except OSError:
                    pass
        if removed:
            logger.info("清理 %d 个过期 ZIP 文件", removed)
        return removed

    def _download_with_retry(self, url: str, path: Path) -> bool:
        """下载文件，失败时自动走代理重试"""
        acquire(1)
        try:
            for attempt, proxies in enumerate([self._proxies, self._fallback_proxies]):
                try:
                    r = requests.get(url, proxies=proxies, timeout=60)
                    if r.status_code == 404:
                        return False
                    if r.status_code == 429:
                        retry_after = int(r.headers.get("Retry-After", 60))
                        set_ban(time.time() + retry_after)
                        return False
                    if r.status_code == 418:
                        retry_after = int(r.headers.get("Retry-After", 0))
                        ban_time = parse_ban(r.text) if not retry_after else time.time() + retry_after
                        set_ban(ban_time if ban_time > time.time() else time.time() + 120)
                        return False
                    r.raise_for_status()
                    path.write_bytes(r.content)
                    metrics.inc("zip_downloads")
                    return True
                except Exception as e:
                    if attempt == 0:
                        logger.debug("直连失败，尝试代理: %s", url)
                    else:
                        logger.debug("代理也失败 %s: %s", url, e)
            return False
        finally:
            release()

    def fill_kline_gaps(self, gaps: Dict[str, List[GapInfo]], interval: str = "1m") -> int:
        """批量补齐 K 线缺口 - 按月分组避免重复下载"""
        if not gaps:
            return 0

        # 按 (symbol, month) 分组，避免重复下载月度 ZIP
        month_groups: Dict[tuple, List[date]] = {}
        for sym, sym_gaps in gaps.items():
            for gap in sym_gaps:
                key = (sym, gap.date.strftime("%Y-%m"))
                month_groups.setdefault(key, []).append(gap.date)

        # 任务：每个 (symbol, month) 只下载一次，但导入多个日期
        tasks = [(sym, month, dates, interval) for (sym, month), dates in month_groups.items()]
        logger.info("K线 ZIP 补齐: %d 个月度任务 (原 %d 个日任务)", len(tasks), sum(len(g) for g in gaps.values()))

        total = 0
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(self._download_kline_month, sym, month, dates, iv): (sym, month) for sym, month, dates, iv in tasks}
            for future in as_completed(futures):
                sym, month = futures[future]
                try:
                    n = future.result()
                    if n > 0:
                        logger.info("[%s] %s ZIP导入 %d 条", sym, month, n)
                        total += n
                except Exception as e:
                    logger.warning("[%s] %s 失败: %s", sym, month, e)

        return total

    def _download_kline_month(self, symbol: str, month: str, dates: List[date], interval: str) -> int:
        """下载并导入一个月的 K 线数据"""
        sym = symbol.upper()
        total = 0
        current_month = date.today().strftime("%Y-%m")

        # 当月数据直接用日度ZIP（月度ZIP还没生成）
        if month == current_month:
            for d in dates:
                day_str = d.strftime("%Y-%m-%d")
                day_fname = f"{sym}-{interval}-{day_str}.zip"
                day_path = self._kline_dir / day_fname
                if not day_path.exists():
                    day_url = f"{BINANCE_DATA_URL}/data/futures/um/daily/klines/{sym}/{interval}/{day_fname}"
                    if not self._download_with_retry(day_url, day_path):
                        continue
                total += self._import_kline_zip(day_path, symbol, interval)
            return total

        # 1. 历史月份尝试月度 ZIP
        month_fname = f"{sym}-{interval}-{month}.zip"
        month_path = self._kline_dir / month_fname
        if not month_path.exists():
            month_url = f"{BINANCE_DATA_URL}/data/futures/um/monthly/klines/{sym}/{interval}/{month_fname}"
            self._download_with_retry(month_url, month_path)

        if month_path.exists():
            # 月度 ZIP 存在，导入所有需要的日期
            for d in dates:
                n = self._import_kline_zip(month_path, symbol, interval, d)
                total += n
            return total

        # 2. 月度不存在，降级到日度
        for d in dates:
            day_str = d.strftime("%Y-%m-%d")
            day_fname = f"{sym}-{interval}-{day_str}.zip"
            day_path = self._kline_dir / day_fname
            if not day_path.exists():
                day_url = f"{BINANCE_DATA_URL}/data/futures/um/daily/klines/{sym}/{interval}/{day_fname}"
                if not self._download_with_retry(day_url, day_path):
                    continue
            total += self._import_kline_zip(day_path, symbol, interval)

        return total

    def fill_metrics_gaps(self, gaps: Dict[str, List[GapInfo]]) -> int:
        """批量补齐期货指标缺口 - 按月分组避免重复下载"""
        if not gaps:
            return 0

        # 按 (symbol, month) 分组
        month_groups: Dict[tuple, List[date]] = {}
        for sym, sym_gaps in gaps.items():
            for gap in sym_gaps:
                key = (sym, gap.date.strftime("%Y-%m"))
                month_groups.setdefault(key, []).append(gap.date)

        tasks = [(sym, month, dates) for (sym, month), dates in month_groups.items()]
        logger.info("Metrics ZIP 补齐: %d 个月度任务 (原 %d 个日任务)", len(tasks), sum(len(g) for g in gaps.values()))

        total = 0
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(self._download_metrics_month, sym, month, dates): (sym, month) for sym, month, dates in tasks}
            for future in as_completed(futures):
                sym, month = futures[future]
                try:
                    n = future.result()
                    if n > 0:
                        logger.info("[%s] %s Metrics导入 %d 条", sym, month, n)
                        total += n
                except Exception as e:
                    logger.warning("[%s] %s 失败: %s", sym, month, e)

        return total

    def _download_metrics_month(self, symbol: str, month: str, dates: List[date]) -> int:
        """下载并导入一个月的 Metrics 数据"""
        sym = symbol.upper()
        total = 0
        current_month = date.today().strftime("%Y-%m")

        # 当月数据直接用日度ZIP
        if month == current_month:
            for d in dates:
                day_str = d.strftime("%Y-%m-%d")
                day_fname = f"{sym}-metrics-{day_str}.zip"
                day_path = self._metrics_dir / day_fname
                if not day_path.exists():
                    day_url = f"{BINANCE_DATA_URL}/data/futures/um/daily/metrics/{sym}/{day_fname}"
                    if not self._download_with_retry(day_url, day_path):
                        continue
                total += self._import_metrics_zip(day_path, symbol)
            return total

        # 1. 历史月份尝试月度 ZIP
        month_fname = f"{sym}-metrics-{month}.zip"
        month_path = self._metrics_dir / month_fname
        if not month_path.exists():
            month_url = f"{BINANCE_DATA_URL}/data/futures/um/monthly/metrics/{sym}/{month_fname}"
            self._download_with_retry(month_url, month_path)

        if month_path.exists():
            for d in dates:
                n = self._import_metrics_zip(month_path, symbol, d)
                total += n
            return total

        # 2. 降级到日度
        for d in dates:
            day_str = d.strftime("%Y-%m-%d")
            day_fname = f"{sym}-metrics-{day_str}.zip"
            day_path = self._metrics_dir / day_fname
            if not day_path.exists():
                day_url = f"{BINANCE_DATA_URL}/data/futures/um/daily/metrics/{sym}/{day_fname}"
                if not self._download_with_retry(day_url, day_path):
                    continue
            total += self._import_metrics_zip(day_path, symbol)

        return total

    def _import_kline_zip(self, path: Path, symbol: str, interval: str, filter_date: date = None) -> int:
        """导入 K 线 ZIP，可选按日期过滤"""
        rows = []
        try:
            with zipfile.ZipFile(path) as zf:
                for name in zf.namelist():
                    if not name.endswith(".csv"):
                        continue
                    with zf.open(name) as f:
                        for row in csv.reader(line.decode() for line in f):
                            if len(row) < 6:
                                continue
                            try:
                                ts = datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc)
                                # 月度ZIP时只导入指定日期
                                if filter_date and ts.date() != filter_date:
                                    continue
                                rows.append({
                                    "exchange": settings.db_exchange,
                                    "symbol": symbol.upper(),
                                    "bucket_ts": ts,
                                    "open": float(row[1]), "high": float(row[2]),
                                    "low": float(row[3]), "close": float(row[4]),
                                    "volume": float(row[5]),
                                    "quote_volume": float(row[7]) if len(row) > 7 and row[7] else None,
                                    "trade_count": int(row[8]) if len(row) > 8 and row[8] else None,
                                    "is_closed": True,
                                    "source": "binance_zip",
                                    "taker_buy_volume": float(row[9]) if len(row) > 9 and row[9] else None,
                                    "taker_buy_quote_volume": float(row[10]) if len(row) > 10 and row[10] else None,
                                })
                            except (ValueError, IndexError):
                                pass
        except Exception as e:
            logger.error("解析失败 %s: %s", path, e)
            return 0

        if rows:
            return self._ts.upsert_candles(interval, rows, update_on_conflict=False)
        return 0

    def _import_metrics_zip(self, path: Path, symbol: str, filter_date: date = None) -> int:
        """导入 metrics ZIP，可选按日期过滤"""
        rows = []
        try:
            with zipfile.ZipFile(path) as zf:
                for name in zf.namelist():
                    if not name.endswith(".csv"):
                        continue
                    with zf.open(name) as f:
                        for row in csv.reader(line.decode() for line in f):
                            if len(row) < 4:
                                continue
                            try:
                                ts_val = row[0]
                                if ts_val.isdigit():
                                    ts = int(ts_val)
                                else:
                                    ts = int(datetime.fromisoformat(ts_val.replace("Z", "+00:00")).timestamp() * 1000)

                                # 对齐到 5 分钟边界
                                ts = (ts // 300000) * 300000
                                dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
                                if filter_date and dt.date() != filter_date:
                                    continue

                                rows.append({
                                    "create_time": dt.replace(tzinfo=None),
                                    "symbol": symbol.upper(),
                                    "exchange": settings.db_exchange,
                                    "sum_open_interest": Decimal(row[2]) if len(row) > 2 and row[2] else None,
                                    "sum_open_interest_value": Decimal(row[3]) if len(row) > 3 and row[3] else None,
                                    "count_toptrader_long_short_ratio": Decimal(row[5]) if len(row) > 5 and row[5] else None,
                                    "sum_toptrader_long_short_ratio": Decimal(row[4]) if len(row) > 4 and row[4] else None,
                                    "count_long_short_ratio": Decimal(row[6]) if len(row) > 6 and row[6] else None,
                                    "sum_taker_long_short_vol_ratio": Decimal(row[7]) if len(row) > 7 and row[7] else None,
                                    "source": "binance_zip",
                                    "is_closed": True,
                                })
                            except (ValueError, IndexError):
                                pass
        except Exception as e:
            logger.error("解析失败 %s: %s", path, e)
            return 0

        if rows:
            return self._upsert_metrics(rows)
        return 0

    def _upsert_metrics(self, rows: List[dict]) -> int:
        """批量 upsert metrics - 使用 COPY 高性能写入"""
        if not rows:
            return 0
        n = self._ts.upsert_metrics(rows)
        metrics.inc("rows_written", n)
        return n


# ==================== 统一补齐器 ====================
class DataBackfiller:
    """统一数据补齐器"""

    def __init__(self, lookback_days: int = 10, workers: int = 8, threshold: float = 0.95):
        self.lookback_days = lookback_days
        self.workers = workers
        self.threshold = threshold
        self._ts = TimescaleAdapter()
        self._scanner = GapScanner(self._ts)
        self._rest = RestBackfiller(self._ts)
        self._zip = ZipBackfiller(self._ts, workers)

    def run_klines(self, symbols: Optional[Sequence[str]] = None, interval: str = "1m") -> Dict[str, int]:
        """补齐 K 线"""
        with Timer("last_backfill_duration"):
            symbols = symbols or load_symbols(settings.ccxt_exchange)
            end = date.today() - timedelta(days=1)
            start = end - timedelta(days=self.lookback_days)

            # 1. 扫描缺口
            logger.info("扫描 K 线缺口: %d 个符号, %s ~ %s", len(symbols), start, end)
            gaps = self._scanner.scan_klines(symbols, start, end, interval, self.threshold)

            if not gaps:
                logger.info("K 线无缺口")
                return {"scanned": len(symbols), "gaps": 0, "filled": 0}

            total_gaps = sum(len(g) for g in gaps.values())
            metrics.inc("gaps_found", total_gaps)
            logger.info("发现 %d 个符号共 %d 个缺口", len(gaps), total_gaps)

            # 2. ZIP 补齐 (优先)
            filled = self._zip.fill_kline_gaps(gaps, interval)

            # 3. 复检 + REST 补齐剩余
            remaining = self._scanner.scan_klines(list(gaps.keys()), start, end, interval, self.threshold)
            if remaining:
                logger.info("复检: 仍有 %d 个缺口，尝试 REST 补齐", sum(len(g) for g in remaining.values()))
                filled += self._rest.fill_gaps(remaining, interval)

            # 4. 最终复检
            final = self._scanner.scan_klines(list(gaps.keys()), start, end, interval, self.threshold)
            final_gaps = sum(len(g) for g in final.values()) if final else 0

            metrics.inc("gaps_filled", filled)
            logger.info("K 线补齐完成: 填充 %d 条, 剩余缺口 %d | %s", filled, final_gaps, metrics)
            return {"scanned": len(symbols), "gaps": total_gaps, "filled": filled, "remaining": final_gaps}

    def run_metrics(self, symbols: Optional[Sequence[str]] = None) -> Dict[str, int]:
        """补齐期货指标"""
        symbols = symbols or load_symbols(settings.ccxt_exchange)
        end = date.today() - timedelta(days=1)
        start = end - timedelta(days=self.lookback_days)

        # 1. 扫描缺口
        logger.info("扫描 Metrics 缺口: %d 个符号, %s ~ %s", len(symbols), start, end)
        gaps = self._scanner.scan_metrics(symbols, start, end, self.threshold)

        if not gaps:
            logger.info("Metrics 无缺口")
            return {"scanned": len(symbols), "gaps": 0, "filled": 0}

        total_gaps = sum(len(g) for g in gaps.values())
        logger.info("发现 %d 个符号共 %d 个缺口", len(gaps), total_gaps)

        # 2. ZIP 补齐
        filled = self._zip.fill_metrics_gaps(gaps)

        # 3. 复检 + REST 补齐剩余
        remaining = self._scanner.scan_metrics(list(gaps.keys()), start, end, self.threshold)
        if remaining:
            remaining_count = sum(len(g) for g in remaining.values())
            logger.info("ZIP 后仍有 %d 个缺口，尝试 REST 补齐", remaining_count)
            rest_filler = MetricsRestBackfiller(self._ts, workers=self.workers)
            filled += rest_filler.fill_gaps(remaining)

        # 4. 最终复检
        final = self._scanner.scan_metrics(list(gaps.keys()), start, end, self.threshold)
        final_gaps = sum(len(g) for g in final.values()) if final else 0

        logger.info("Metrics 补齐完成: 填充 %d 条, 剩余缺口 %d", filled, final_gaps)
        return {"scanned": len(symbols), "gaps": total_gaps, "filled": filled, "remaining": final_gaps}

    def run_all(self, symbols: Optional[Sequence[str]] = None) -> Dict[str, Dict[str, int]]:
        """并行补齐 K线 + Metrics"""
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_klines = pool.submit(self.run_klines, symbols)
            f_metrics = pool.submit(self.run_metrics, symbols)
            return {
                "klines": f_klines.result(),
                "metrics": f_metrics.result(),
            }

    def close(self) -> None:
        self._ts.close()


# ==================== 兼容旧接口 ====================
class GapFiller:
    """K线缺口补齐 (兼容旧接口)"""
    def __init__(self, ts: TimescaleAdapter):
        self._ts = ts
        self._lookback = settings.ws_gap_lookback
        self._rest = RestBackfiller(ts)
        self._scanner = GapScanner(ts)

    def set_lookback(self, minutes: int) -> None:
        self._lookback = max(1, minutes)

    def ensure_continuity(self, symbols: Sequence[str]) -> None:
        end = date.today()
        # lookback 是分钟，转换为天数 (向上取整)
        lookback_days = max(1, (self._lookback + 1439) // 1440)
        start = end - timedelta(days=lookback_days)
        gaps = self._scanner.scan_klines(symbols, start, end, "1m", 0.95)
        if gaps:
            logger.info("检测到 %d 个符号有缺口", len(gaps))
            self._rest.fill_gaps(gaps, "1m")


# ==================== 主入口 ====================
def get_backfill_config():
    """从环境变量获取补齐配置"""
    import os

    mode_raw = os.environ.get("BACKFILL_MODE", "days").lower()
    # 兼容历史写法 full → all
    mode = "all" if mode_raw == "full" else mode_raw

    try:
        days = int(os.environ.get("BACKFILL_DAYS", "30"))
    except ValueError:
        days = 30

    start_date = None
    start_date_raw = os.environ.get("BACKFILL_START_DATE")
    if start_date_raw:
        try:
            start_date = datetime.fromisoformat(start_date_raw).date()
        except ValueError:
            logger.warning("无效的 BACKFILL_START_DATE: %s", start_date_raw)

    on_start = os.environ.get("BACKFILL_ON_START", "false").lower() in ("true", "1", "yes")
    return mode, days, on_start, start_date


def compute_lookback(mode: str, days: int, start_date: Optional[date] = None) -> int:
    """根据模式与起始日计算回溯天数"""
    mode = (mode or "days").lower()

    if mode == "none":
        return 0

    if mode == "all":
        if start_date:
            delta = (date.today() - start_date).days
            return max(delta, 1)
        return 3650  # 默认 10 年

    # 默认 days 模式
    return max(days, 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="数据补齐系统")
    parser.add_argument("--lookback", type=int, help="回溯天数（覆盖env配置）")
    parser.add_argument("--symbols", type=str, help="交易对列表(逗号分隔)")
    parser.add_argument("--workers", type=int, default=2, help="下载线程数")
    parser.add_argument("--threshold", type=float, default=0.95, help="完整度阈值")
    parser.add_argument("--klines", action="store_true", help="补齐K线")
    parser.add_argument("--metrics", action="store_true", help="补齐期货指标")
    parser.add_argument("--all", action="store_true", help="补齐全部")
    parser.add_argument("--scan-only", action="store_true", help="仅扫描不补齐")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    # 从环境变量获取配置
    mode, env_days, _, start_date = get_backfill_config()

    # 确定回溯天数
    if args.lookback:
        lookback = args.lookback
    else:
        lookback = compute_lookback(mode, env_days, start_date)

    if lookback <= 0:
        logger.info("BACKFILL_MODE=none，跳过补齐")
        return

    logger.info("补齐模式: %s, 回溯: %d 天", mode, lookback)

    symbols = args.symbols.split(",") if args.symbols else None
    bf = DataBackfiller(lookback, args.workers, args.threshold)

    try:
        if args.scan_only:
            # 仅扫描
            symbols = symbols or load_symbols(settings.ccxt_exchange)
            end = date.today() - timedelta(days=1)
            start = end - timedelta(days=lookback)

            if args.klines or args.all or not args.metrics:
                gaps = bf._scanner.scan_klines(symbols, start, end)
                print(f"\nK线缺口: {sum(len(g) for g in gaps.values())} 个")
                for sym, sym_gaps in list(gaps.items())[:5]:
                    print(f"  {sym}: {[str(g.date) for g in sym_gaps[:3]]}")

            if args.metrics or args.all:
                gaps = bf._scanner.scan_metrics(symbols, start, end)
                print(f"\nMetrics缺口: {sum(len(g) for g in gaps.values())} 个")
                for sym, sym_gaps in list(gaps.items())[:5]:
                    print(f"  {sym}: {[str(g.date) for g in sym_gaps[:3]]}")
        else:
            # 补齐
            if args.all:
                result = bf.run_all(symbols)
                print(f"\n结果: {result}")
            elif args.klines:
                result = bf.run_klines(symbols)
                print(f"\nK线结果: {result}")
            elif args.metrics:
                result = bf.run_metrics(symbols)
                print(f"\nMetrics结果: {result}")
            else:
                print("用法: python backfill.py --klines|--metrics|--all [--scan-only]")
    finally:
        bf.close()


if __name__ == "__main__":
    main()
