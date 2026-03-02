"""API 路由模块"""

from .health import router as health_router
from .coins import router as coins_router
from .ohlc import router as ohlc_router
from .open_interest import router as open_interest_router
from .funding_rate import router as funding_rate_router
from .futures_metrics import router as futures_metrics_router
from .base_data import router as base_data_router
from .indicator import router as indicator_router
from .signal import router as signal_router
from .query_v1 import router as query_v1_router

__all__ = [
    "health_router",
    "coins_router",
    "ohlc_router",
    "open_interest_router",
    "funding_rate_router",
    "futures_metrics_router",
    "base_data_router",
    "indicator_router",
    "signal_router",
    "query_v1_router",
]
