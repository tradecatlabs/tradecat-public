"""期货指标采集器 - 高性能版"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from adapters.ccxt import load_symbols
from adapters.metrics import Timer, metrics
from adapters.rate_limiter import acquire, parse_ban, release, set_ban
from adapters.timescale import TimescaleAdapter
from config import settings

logger = logging.getLogger(__name__)

FAPI = settings.binance_fapi_base


# 配置连接池
_adapter = requests.adapters.HTTPAdapter(pool_connections=30, pool_maxsize=30)
_session = requests.Session()
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


class MetricsCollector:
    """Binance 期货指标采集（5m 粒度）- 并发版"""

    def __init__(self, workers: int = 8):
        self._ts = TimescaleAdapter()
        self._workers = workers
        self._proxies = {"http": settings.http_proxy, "https": settings.http_proxy} if settings.http_proxy else {}

    def _get(self, url: str, params: dict) -> list | None:
        """REST 请求 - 使用全局限流"""
        acquire(1)
        metrics.inc("requests_total")
        try:
            r = _session.get(url, params=params, proxies=self._proxies, timeout=10)
            if r.status_code == 429:
                # 429: 警告，立即停止，解析 Retry-After
                retry_after = int(r.headers.get("Retry-After", 60))
                set_ban(time.time() + retry_after)
                logger.warning("429 限流警告，等待 %ds", retry_after)
                metrics.inc("requests_failed")
                return None
            if r.status_code == 418:
                # 418: 已被 ban，解析 ban 结束时间
                retry_after = int(r.headers.get("Retry-After", 0))
                ban_time = parse_ban(r.text) if not retry_after else time.time() + retry_after
                set_ban(ban_time if ban_time > time.time() else time.time() + 120)
                logger.warning("418 IP 被 ban")
                metrics.inc("requests_failed")
                return None
            r.raise_for_status()
            return r.json()
        except Exception as e:
            metrics.inc("requests_failed")
            logger.debug("请求失败 %s: %s", params.get("symbol", ""), e)
            return None
        finally:
            release()

    def _collect_one(self, sym: str) -> dict | None:
        """采集单个符号 - 串行请求避免并发放大"""
        sym = sym.upper()
        apis = [
            ("oi", f"{FAPI}/futures/data/openInterestHist", {"symbol": sym, "period": "5m", "limit": 1}),
            ("pos", f"{FAPI}/futures/data/topLongShortPositionRatio", {"symbol": sym, "period": "5m", "limit": 1}),
            ("acc", f"{FAPI}/futures/data/topLongShortAccountRatio", {"symbol": sym, "period": "5m", "limit": 1}),
            ("glb", f"{FAPI}/futures/data/globalLongShortAccountRatio", {"symbol": sym, "period": "5m", "limit": 1}),
            ("taker", f"{FAPI}/futures/data/takerlongshortRatio", {"symbol": sym, "period": "5m", "limit": 1}),
        ]

        results = {}
        for key, url, params in apis:
            results[key] = self._get(url, params)

        oi, pos, acc, glb, taker = (
            results.get("oi"),
            results.get("pos"),
            results.get("acc"),
            results.get("glb"),
            results.get("taker"),
        )

        # 至少要有 oi 数据才有意义
        if not oi or not isinstance(oi, list) or not oi:
            return None

        ts = int(oi[0].get("timestamp", 0))
        ts = (ts // 300000) * 300000

        return {
            "create_time": datetime.fromtimestamp(ts / 1000, tz=UTC).replace(tzinfo=None),
            "symbol": sym,
            "exchange": settings.db_exchange,
            "sum_open_interest": _to_decimal(oi[0].get("sumOpenInterest")) if oi else None,
            "sum_open_interest_value": _to_decimal(oi[0].get("sumOpenInterestValue")) if oi else None,
            "count_toptrader_long_short_ratio": _to_decimal(acc[0].get("longShortRatio")) if acc else None,
            "sum_toptrader_long_short_ratio": _to_decimal(pos[0].get("longShortRatio")) if pos else None,
            "count_long_short_ratio": _to_decimal(glb[0].get("longShortRatio")) if glb else None,
            "sum_taker_long_short_vol_ratio": _to_decimal(taker[0].get("buySellRatio")) if taker else None,
            "source": "binance_api",
            "is_closed": True,
        }

    def collect(self, symbols: Sequence[str]) -> list[dict]:
        """并发采集"""
        rows = []
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            futures = {pool.submit(self._collect_one, sym): sym for sym in symbols}
            for future in as_completed(futures):
                try:
                    row = future.result()
                    if row:
                        rows.append(row)
                except Exception as e:
                    logger.debug("采集异常 %s: %s", futures[future], e)
        return rows

    def save(self, rows: list[dict]) -> int:
        """批量保存 - 使用 COPY 高性能写入"""
        if not rows:
            return 0
        n = self._ts.upsert_metrics(rows)
        metrics.inc("rows_written", n)
        return n

    def run_once(self, symbols: Sequence[str] | None = None) -> int:
        symbols = symbols or load_symbols(settings.ccxt_exchange)
        logger.info("采集 %d 个符号 (并发=%d)", len(symbols), self._workers)
        with Timer("last_collect_duration"):
            rows = self.collect(symbols)
            n = self.save(rows)
        logger.info("保存 %d 条 | %s", n, metrics)
        return n

    def close(self) -> None:
        self._ts.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    c = MetricsCollector()
    try:
        c.run_once()
    finally:
        c.close()


if __name__ == "__main__":
    main()
