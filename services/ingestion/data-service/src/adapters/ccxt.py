"""CCXT 适配器 - 使用全局限流器"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import ccxt

from adapters.rate_limiter import acquire, parse_ban, release, set_ban

logger = logging.getLogger(__name__)

_clients: Dict[str, ccxt.Exchange] = {}
_symbols: Dict[str, List[str]] = {}
DEFAULT_PROXY = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")

def _maybe_set_ban_from_error(err_str: str) -> bool:
    """从异常文本中识别 418/429/ban，并写入全局 ban。

    背景：部分 ccxt 版本/适配层会把 Binance 的 418/ban 归类为 NetworkError，
    若只在 RateLimitExceeded 分支处理，会导致 ban 冷却机制失效。
    """
    s = str(err_str)
    now = time.time()

    # 418: Way too much request weight used; IP banned until ...
    # 有些异常文本可能不包含 418，但包含 banned until / IP banned
    if ("418" in s) or ("banned until" in s) or ("IP banned" in s):
        ban_time = parse_ban(s)
        set_ban(ban_time if ban_time > now else now + 120)
        return True

    # 429: too many requests
    if ("429" in s) or ("Too many requests" in s):
        set_ban(now + 60)
        return True

    return False


def _parse_list(raw: str) -> List[str]:
    """将逗号分隔的币种字符串解析为大写列表，过滤空项。"""
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def get_client(exchange: str = "binance") -> ccxt.Exchange:
    if exchange not in _clients:
        cls = getattr(ccxt, exchange, None)
        if not cls:
            raise ValueError(f"不支持: {exchange}")
        _clients[exchange] = cls({
            "enableRateLimit": True,  # 保留内置限流作为双重保护
            "timeout": 30000,
            "proxies": {"http": DEFAULT_PROXY, "https": DEFAULT_PROXY} if DEFAULT_PROXY else None,
            "options": {"defaultType": "swap"},
        })
    return _clients[exchange]


# ========== 币种管理配置 ==========
# 使用共享模块（assets/common/symbols.py）
import sys

from config import PROJECT_ROOT

_repo_root = str(PROJECT_ROOT)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
from assets.common.symbols import get_configured_symbols


def load_symbols(exchange: str = "binance") -> List[str]:
    key = f"{exchange}_usdt"
    if key not in _symbols:
        # 先检查是否有配置的币种
        configured = get_configured_symbols()
        if configured:
            _symbols[key] = configured
            logger.info("使用配置币种 %d 个", len(_symbols[key]))
        else:
            # 从交易所获取全部
            acquire(5)
            try:
                client = get_client(exchange)
                client.load_markets()
                all_symbols = sorted({
                    f"{m['base']}USDT" for m in client.markets.values()
                    if m.get("swap") and m.get("settle") == "USDT" and m.get("linear")
                })
                # 应用排除
                exclude = set(_parse_list(os.getenv("SYMBOLS_EXCLUDE", "")))
                extra = _parse_list(os.getenv("SYMBOLS_EXTRA", ""))
                _symbols[key] = [s for s in all_symbols if s not in exclude]
                _symbols[key] = sorted(set(_symbols[key]) | set(extra))
                logger.info("加载 %s USDT永续 %d 个", exchange, len(_symbols[key]))
            finally:
                release()
    return _symbols[key]


def fetch_ohlcv(exchange: str, symbol: str, interval: str = "1m",
               since_ms: Optional[int] = None, limit: int = 1000) -> List[List]:
    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        return []

    ccxt_sym = f"{symbol[:-4]}/USDT:USDT"

    # ==================== 优先尝试 Binance 原生 Kline（含 quote/taker 字段） ====================
    if exchange in {"binance", "binanceusdm", "binance_usdm", "binance_futures", "binance_futures_um"}:
        for attempt in range(3):
            acquire(2)
            try:
                client = get_client(exchange)
                method = getattr(client, "fapiPublicGetKlines", None)
                if method:
                    params = {"symbol": symbol, "interval": interval, "limit": limit}
                    if since_ms is not None:
                        params["startTime"] = since_ms
                    raw = method(params)
                    if raw:
                        return raw
            except Exception as e:
                if attempt == 2:
                    logger.warning("binance 原生 klines 失败: %s", e)
            finally:
                release()

    for attempt in range(3):
        acquire(2)
        try:
            return get_client(exchange).fetch_ohlcv(ccxt_sym, interval, since=since_ms, limit=limit)
        except ccxt.RateLimitExceeded as e:
            # ccxt 可能抛出 429/418；一旦触发应立即进入全局冷却，避免继续消耗权重
            _maybe_set_ban_from_error(str(e))
            if attempt == 2:
                logger.warning("fetch_ohlcv 限流: %s", e)
            return []
        except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as e:
            # 某些情况下 418/ban 会被归类为 NetworkError：必须同样进入全局冷却
            if _maybe_set_ban_from_error(str(e)):
                return []
            if attempt == 2:
                logger.warning("fetch_ohlcv 网络错误: %s", e)
                return []
            time.sleep(1 * (2 ** attempt))
        finally:
            release()


def to_rows(exchange: str, symbol: str, candles: List[List], source: str = "ccxt") -> List[dict]:
    rows = []
    for c in candles:
        if len(c) < 6:
            continue
        try:
            open_time_ms = int(c[0])
        except (TypeError, ValueError):
            # 兼容 ccxt / Binance 原生返回里时间戳为 str/None 的情况
            continue
        # Binance 原生 klines: [openTime, open, high, low, close, volume, closeTime, quoteVolume, trades, takerBuyVol, takerBuyQuote, ...]
        quote_volume = None
        trade_count = None
        taker_buy_volume = None
        taker_buy_quote_volume = None
        if len(c) >= 11:
            quote_volume = float(c[7]) if c[7] not in (None, "") else None
            trade_count = int(c[8]) if c[8] not in (None, "") else None
            taker_buy_volume = float(c[9]) if c[9] not in (None, "") else None
            taker_buy_quote_volume = float(c[10]) if c[10] not in (None, "") else None
        rows.append({
            "exchange": exchange, "symbol": symbol.upper(),
            "bucket_ts": datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc),
            "open": float(c[1]), "high": float(c[2]), "low": float(c[3]),
            "close": float(c[4]), "volume": float(c[5]),
            "quote_volume": quote_volume, "trade_count": trade_count, "is_closed": True, "source": source,
            "taker_buy_volume": taker_buy_volume, "taker_buy_quote_volume": taker_buy_quote_volume,
        })
    return rows


def normalize_symbol(symbol: str) -> Optional[str]:
    s = symbol.upper().replace("/", "").replace(":", "").replace("-", "")
    return s if s.endswith("USDT") else None


# 兼容旧代码
class _CompatLimiter:
    def acquire(self, w=1): acquire(w)
_limiter = _CompatLimiter()
def _check_and_wait_ban():
    return None
_parse_ban_time = parse_ban
_ban_until = 0
_ban_lock = None

async def async_acquire(weight: int = 1):
    await asyncio.to_thread(acquire, weight)

async def async_check_and_wait_ban():
    pass
