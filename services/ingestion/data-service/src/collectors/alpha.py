"""Alpha 代币列表采集"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).parent.parent))
from adapters.rate_limiter import acquire, parse_ban, release, set_ban
from config import settings

logger = logging.getLogger(__name__)

BINANCE_ALPHA_URL = settings.binance_alpha_url
CACHE_TTL = timedelta(hours=6)


def _normalize_symbol(symbol: str | None) -> str | None:
    if not symbol:
        return None
    return symbol.replace("/", "").replace("-", "").replace("_", "").upper() or None


class AlphaTokenFetcher:
    """Alpha 代币列表"""

    def __init__(self):
        self._cache_path = settings.data_dir / "alpha_tokens.json"
        self._proxy = settings.http_proxy

    async def refresh(self, force: bool = False) -> dict[str, dict[str, str]]:
        """刷新 Alpha 代币缓存"""
        if not force and self._cache_path.exists():
            try:
                cache = json.loads(self._cache_path.read_text())
                fetched_at = datetime.fromisoformat(cache.get("fetched_at", ""))
                if datetime.now(UTC) - fetched_at.replace(tzinfo=UTC) < CACHE_TTL:
                    logger.info("使用缓存: %d 个 Alpha 代币", len(cache.get("tokens", [])))
                    return self._parse_tokens(cache.get("tokens", []))
            except Exception:
                pass

        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            acquire(1)
            try:
                async with session.get(BINANCE_ALPHA_URL, proxy=self._proxy) as resp:
                    if resp.status in (418, 429):
                        body = await resp.text()
                        ban_time = parse_ban(body)
                        set_ban(ban_time if ban_time > time.time() else time.time() + 60)
                        return self._load_cache()
                    if resp.status != 200:
                        logger.warning("获取 Alpha 列表失败: %s", resp.status)
                        return self._load_cache()
                    data = await resp.json()
            except Exception as e:
                logger.warning("请求 Alpha 列表异常: %s", e)
                return self._load_cache()
            finally:
                release()

        tokens = data.get("data", []) if isinstance(data, dict) else []
        if not tokens:
            return self._load_cache()

        cache = {"fetched_at": datetime.now(UTC).isoformat(), "tokens": tokens}
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
        logger.info("Alpha 代币缓存已更新: %d 个", len(tokens))

        return self._parse_tokens(tokens)

    def _load_cache(self) -> dict[str, dict[str, str]]:
        if not self._cache_path.exists():
            return {}
        try:
            cache = json.loads(self._cache_path.read_text())
            return self._parse_tokens(cache.get("tokens", []))
        except Exception:
            return {}

    def _parse_tokens(self, tokens: list) -> dict[str, dict[str, str]]:
        mapping = {}
        for item in tokens:
            symbol = item.get("symbol") or item.get("cexCoinName")
            alpha_id = item.get("alphaId") or item.get("alpha_id")
            name = item.get("name")
            if not symbol and alpha_id:
                symbol = alpha_id.replace("ALPHA_", "")
            normalized = _normalize_symbol(symbol)
            if normalized:
                mapping[normalized] = {
                    "note": alpha_id or name or "Binance Alpha",
                    "alpha_id": alpha_id or "",
                    "name": name or "",
                    "source": "binance",
                }
        return mapping

    def is_alpha(self, symbol: str) -> tuple[bool, str | None]:
        """判断是否为 Alpha 代币"""
        alpha_map = self._load_cache()
        normalized = _normalize_symbol(symbol)
        if normalized and normalized in alpha_map:
            return True, alpha_map[normalized].get("note")
        return False, None


async def refresh_alpha_tokens(force: bool = False) -> dict[str, dict[str, str]]:
    """刷新 Alpha 代币列表"""
    return await AlphaTokenFetcher().refresh(force)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    async def run():
        tokens = await refresh_alpha_tokens(force=True)
        print(f"\nAlpha 代币: {len(tokens)} 个")
        for sym in list(tokens.keys())[:10]:
            print(f"  {sym}: {tokens[sym]['name']}")

    asyncio.run(run())


if __name__ == "__main__":
    main()
