"""Cryptofeed WebSocket 适配器"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, List, Optional

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class CandleEvent:
    """K线事件"""
    symbol: str
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: Optional[Decimal] = None
    taker_buy_volume: Optional[Decimal] = None
    taker_buy_quote_volume: Optional[Decimal] = None
    trade_count: Optional[int] = None


class BinanceWSAdapter:
    """Binance WebSocket 适配器"""

    def __init__(self, http_proxy: Optional[str] = None):
        self._proxy = http_proxy
        self._handler = None
        self._callback: Optional[Callable[[CandleEvent], None]] = None
        self._symbols: List[str] = []

    def subscribe(self, symbols: List[str], callback: Callable[[CandleEvent], None]) -> None:
        self._symbols = symbols
        self._callback = callback

    async def _on_candle(self, candle, receipt_ts: float) -> None:
        if not candle.closed or not self._callback:
            return
        raw = getattr(candle, "raw", {}) or {}
        k = raw.get("k", {})
        self._callback(CandleEvent(
            symbol=candle.symbol, timestamp=candle.start,
            open=candle.open, high=candle.high, low=candle.low, close=candle.close, volume=candle.volume,
            quote_volume=Decimal(k.get("q", "0")), taker_buy_volume=Decimal(k.get("V", "0")),
            taker_buy_quote_volume=Decimal(k.get("Q", "0")), trade_count=candle.trades,
        ))

    def run(self) -> None:
        from cryptofeed import FeedHandler
        from cryptofeed.defines import CANDLES
        from cryptofeed.exchanges import BinanceFutures

        log_file = settings.log_dir / "cryptofeed.log"
        self._handler = FeedHandler(config={"uvloop": False, "log": {"filename": str(log_file), "level": "INFO"}})
        # 重要：cryptofeed 的 http_proxy 仅对 HTTP GET 生效；WebSocket 代理需要走 websockets.connect(proxy=...)
        # 这里在 WebsocketEndpoint.options 注入 proxy，确保 wss 在受限网络环境下也能稳定收流。
        if self._proxy:
            for ep in getattr(BinanceFutures, "websocket_endpoints", []) or []:
                opts = dict(getattr(ep, "options", {}) or {})
                opts.setdefault("proxy", self._proxy)
                ep.options = opts

        kw = {"symbols": self._symbols, "channels": [CANDLES], "callbacks": {CANDLES: self._on_candle}, "candle_interval": "1m", "candle_closed_only": True, "timeout": 60, "http_proxy": self._proxy}
        if self._proxy:
            logger.info("WebSocket/HTTP 代理已启用: %s", self._proxy)
        self._handler.add_feed(BinanceFutures(**kw))
        logger.info("启动 Binance WSS: 符号=%d", len(self._symbols))
        self._handler.run()

    def stop(self) -> None:
        if self._handler:
            self._handler.stop()


def preload_symbols(symbols: List[str]) -> None:
    try:
        from cryptofeed.defines import BINANCE_FUTURES, PERPETUAL
        from cryptofeed.exchanges import BinanceFutures
        from cryptofeed.symbols import Symbol, Symbols
        mapping = {Symbol(s[:-4], "USDT", type=PERPETUAL).normalized: s for s in symbols if s.upper().endswith("USDT")}
        if mapping:
            Symbols.set(BINANCE_FUTURES, mapping, {"symbols": list(mapping.keys()), "channels": {"rest": [], "websocket": list(BinanceFutures.websocket_channels.keys())}})
            logger.info("预置 cryptofeed 映射 %d 个", len(mapping))
    except Exception as e:
        logger.warning("预置映射失败: %s", e)
