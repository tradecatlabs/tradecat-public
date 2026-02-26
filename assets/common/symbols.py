"""币种管理模块

统一的币种过滤逻辑，供所有服务使用。
读取环境变量：SYMBOLS_GROUPS, SYMBOLS_GROUP_*, SYMBOLS_EXTRA, SYMBOLS_EXCLUDE
"""
import json
import logging
import os
import time
import urllib.request
from typing import List, Optional, Set

logger = logging.getLogger(__name__)

_ALL_SYMBOLS_CACHE: List[str] = []
_ALL_SYMBOLS_TS: float = 0.0


def _now_ts() -> float:
    return time.time()


def _proxy_handler():
    proxy = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")
    if not proxy:
        return None
    return urllib.request.ProxyHandler({"http": proxy, "https": proxy})


def _fetch_all_symbols_ccxt() -> List[str]:
    """优先使用 ccxt 获取 Binance USDT 永续符号。"""
    try:
        import ccxt  # type: ignore
    except Exception as exc:  # pragma: no cover - 环境可能未安装 ccxt
        raise RuntimeError(f"ccxt 不可用: {exc}") from exc

    proxy = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")
    client = ccxt.binance({
        "enableRateLimit": True,
        "timeout": 30000,
        "proxies": {"http": proxy, "https": proxy} if proxy else None,
        "options": {"defaultType": "swap"},
    })
    client.load_markets()
    symbols = sorted({
        f"{m['base']}USDT" for m in client.markets.values()
        if m.get("swap") and m.get("settle") == "USDT" and m.get("linear")
    })
    if not symbols:
        raise RuntimeError("ccxt 返回空符号列表")
    return symbols


def _fetch_all_symbols_rest() -> List[str]:
    """使用 Binance REST 获取 USDT 永续符号。"""
    url = os.getenv("SYMBOLS_ALL_URL")
    if not url:
        base = (os.getenv("BINANCE_FAPI_BASE") or os.getenv("BINANCE_REST_BASE_MAINNET") or "").rstrip("/")
        if base:
            url = f"{base}/fapi/v1/exchangeInfo"
    if not url:
        raise RuntimeError("未配置 SYMBOLS_ALL_URL 或 BINANCE_FAPI_BASE/BINANCE_REST_BASE_MAINNET")
    handler = _proxy_handler()
    opener = urllib.request.build_opener(handler) if handler else urllib.request.build_opener()
    retries = int(os.getenv("SYMBOLS_ALL_RETRIES", "3"))
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            with opener.open(url, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(1 + attempt)
                continue
            raise
    symbols = []
    for item in data.get("symbols", []):
        if item.get("contractType") != "PERPETUAL":
            continue
        if item.get("quoteAsset") != "USDT":
            continue
        if item.get("status") != "TRADING":
            continue
        sym = item.get("symbol")
        if sym and sym.endswith("USDT"):
            symbols.append(sym)
    if not symbols:
        raise RuntimeError("REST 返回空符号列表") from last_exc
    return sorted(set(symbols))


def _get_all_symbols_cached() -> List[str]:
    """获取全量符号（带缓存），失败时返回空列表。"""
    global _ALL_SYMBOLS_CACHE, _ALL_SYMBOLS_TS
    ttl = int(os.getenv("SYMBOLS_ALL_TTL", "3600"))
    now = _now_ts()
    if _ALL_SYMBOLS_CACHE and (now - _ALL_SYMBOLS_TS) < ttl:
        return list(_ALL_SYMBOLS_CACHE)

    source = os.getenv("SYMBOLS_ALL_SOURCE", "rest").lower()
    errors = []
    symbols: List[str] = []

    if source in ("auto", "ccxt"):
        try:
            symbols = _fetch_all_symbols_ccxt()
        except Exception as exc:
            errors.append(f"ccxt: {exc}")
            if source == "ccxt":
                raise

    if not symbols:
        try:
            symbols = _fetch_all_symbols_rest()
        except Exception as exc:
            errors.append(f"rest: {exc}")

    if symbols:
        _ALL_SYMBOLS_CACHE = symbols
        _ALL_SYMBOLS_TS = now
        return list(symbols)

    if errors:
        logger.warning("获取全量币种失败: %s", "; ".join(errors))
    return list(_ALL_SYMBOLS_CACHE)


def _parse_list(val: str) -> List[str]:
    """解析逗号分隔的列表"""
    return [s.strip().upper() for s in val.split(",") if s.strip()]


def _load_symbol_groups() -> dict:
    """从环境变量加载所有分组"""
    groups = {}
    for key, val in os.environ.items():
        if key.startswith("SYMBOLS_GROUP_") and val:
            name = key[14:].lower()
            groups[name] = _parse_list(val)
    return groups


def get_configured_symbols() -> Optional[List[str]]:
    """
    根据环境变量获取币种列表
    
    Returns:
        List[str]: 配置的币种列表
        None: 使用 auto/all 模式，由调用方决定具体币种
    """
    groups_str = os.environ.get("SYMBOLS_GROUPS", "auto")
    extra = _parse_list(os.environ.get("SYMBOLS_EXTRA", ""))
    exclude = set(_parse_list(os.environ.get("SYMBOLS_EXCLUDE", "")))
    
    selected_groups = [g.strip().lower() for g in groups_str.split(",") if g.strip()]
    
    # auto 返回 None，由调用方决定
    if "auto" in selected_groups:
        return None

    # all 返回全量列表（带缓存）
    if "all" in selected_groups:
        symbols = _get_all_symbols_cached()
        if not symbols:
            return None
        symbols = set(symbols)
        symbols.update(extra)
        symbols -= exclude
        return sorted(symbols) if symbols else None
    
    # 加载分组
    all_groups = _load_symbol_groups()
    symbols = set()
    for g in selected_groups:
        if g in all_groups:
            symbols.update(all_groups[g])
    
    symbols.update(extra)
    symbols -= exclude
    
    return sorted(symbols) if symbols else None


def get_configured_symbols_set() -> Optional[Set[str]]:
    """
    根据环境变量获取币种集合（用于过滤）
    
    Returns:
        Set[str]: 配置的币种集合
        None: 使用 auto/all 模式，不过滤
    """
    result = get_configured_symbols()
    return set(result) if result else None


def reload_symbols():
    """
    强制重新加载币种配置（用于热更新）
    
    注意：此函数本身不缓存，每次调用 get_configured_symbols() 都会重新读取环境变量。
    此函数主要用于通知依赖模块（如 data_provider）刷新其缓存。
    """
    # symbols.py 本身每次都从 os.environ 读取，无需清理
    # 但需要通知其他模块刷新缓存
    pass
