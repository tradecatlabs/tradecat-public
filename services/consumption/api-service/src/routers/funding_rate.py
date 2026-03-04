"""Funding Rate 路由 (对齐 CoinGlass /api/futures/funding-rate/history)

重要说明：
- 当前未接入真实 funding rate 数据源（禁止用其它列冒充资金费率）。
- 在数据源补齐前，统一返回 not_supported，避免“看起来正确的错误数据”污染消费链路。
"""

from fastapi import APIRouter, Query

from src.utils.errors import ErrorCode, error_response
from src.utils.symbol import normalize_symbol

router = APIRouter(tags=["futures"])

VALID_INTERVALS = ["5m", "15m", "1h", "4h", "1d", "1w"]

TABLE_BY_INTERVAL = {
    "5m": "market_data.binance_futures_metrics_5m",
    "15m": "market_data.binance_futures_metrics_15m_last",
    "1h": "market_data.binance_futures_metrics_1h_last",
    "4h": "market_data.binance_futures_metrics_4h_last",
    "1d": "market_data.binance_futures_metrics_1d_last",
    "1w": "market_data.binance_futures_metrics_1w_last",
}


def _normalize_exchange(exchange: str) -> str:
    """标准化交易所标识"""
    ex = (exchange or "").strip().lower()
    if ex in {"binance", "binance_futures", "binance_usdm", "binanceusdm", "binance_futures_um"}:
        return "binance_futures_um"
    return ex or "binance_futures_um"


@router.get("/funding-rate/history")
async def get_funding_rate_history(
    symbol: str = Query(..., description="交易对 (BTC 或 BTCUSDT)"),
    exchange: str = Query(default="Binance", description="交易所"),
    interval: str = Query(default="1h", description="周期"),
    limit: int = Query(default=100, ge=1, le=1000, description="返回数量"),
    startTime: int | None = Query(default=None, description="开始时间 (毫秒)"),
    endTime: int | None = Query(default=None, description="结束时间 (毫秒)"),
) -> dict:
    """获取 Funding Rate 历史数据"""
    symbol = normalize_symbol(symbol)

    # NOTE: 真实 funding rate 数据源未接入前，禁止返回“其它列冒充资金费率”的伪数据。
    return error_response(ErrorCode.TABLE_NOT_FOUND, "funding_rate_not_supported")
