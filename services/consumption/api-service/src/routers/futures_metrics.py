"""期货综合指标路由"""

import psycopg
from psycopg import sql

from fastapi import APIRouter, Query
from fastapi.concurrency import run_in_threadpool

from src.query import market_dao
from src.utils.errors import ErrorCode, api_response, error_response
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


@router.get("/metrics")
async def get_futures_metrics(
    symbol: str = Query(..., description="交易对 (BTC 或 BTCUSDT)"),
    exchange: str = Query(default="Binance", description="交易所"),
    interval: str = Query(default="5m", description="周期"),
    limit: int = Query(default=100, ge=1, le=1000, description="返回数量"),
) -> dict:
    """获取期货综合指标数据"""
    symbol = normalize_symbol(symbol)

    if interval not in VALID_INTERVALS:
        return error_response(ErrorCode.INVALID_INTERVAL, f"无效的 interval: {interval}")
    table = TABLE_BY_INTERVAL.get(interval)
    if not table:
        return error_response(ErrorCode.TABLE_NOT_FOUND, f"未配置 interval: {interval}")

    def _fetch_rows():
        time_col = "create_time" if interval == "5m" else "bucket"
        schema, table_name = market_dao.split_qualified_table(table)
        if not market_dao.table_exists(schema, table_name):
            return ("table_missing", [])

        pool = market_dao.get_market_pool()
        tbl = sql.Identifier(schema, table_name)
        time_ident = sql.Identifier(time_col)

        with pool.connection() as conn:
            with conn.cursor() as cursor:
                exchange_code = _normalize_exchange(exchange)
                if interval == "5m":
                    query = sql.SQL(
                        """
                        SELECT symbol, {time_col}, sum_open_interest_value,
                               sum_toptrader_long_short_ratio, sum_taker_long_short_vol_ratio
                        FROM {tbl}
                        WHERE symbol = %s AND exchange = %s
                        ORDER BY {time_col} DESC
                        LIMIT %s
                        """
                    ).format(time_col=time_ident, tbl=tbl)
                    cursor.execute(query, (symbol, exchange_code, limit))
                else:
                    query = sql.SQL(
                        """
                        SELECT symbol, {time_col}, sum_open_interest_value,
                               sum_toptrader_long_short_ratio, sum_taker_long_short_vol_ratio
                        FROM {tbl}
                        WHERE symbol = %s
                        ORDER BY {time_col} DESC
                        LIMIT %s
                        """
                    ).format(time_col=time_ident, tbl=tbl)
                    cursor.execute(query, (symbol, limit))
                return ("ok", cursor.fetchall())

    try:
        status, rows = await run_in_threadpool(_fetch_rows)
        if status == "table_missing":
            return error_response(ErrorCode.TABLE_NOT_FOUND, f"表不存在: {table}")
        data = []
        for row in reversed(rows):
            oi = row[2] if row[2] is not None else None
            ls = row[3] if row[3] is not None else None
            tl = row[4] if row[4] is not None else None
            data.append(
                {
                    "time": int(row[1].timestamp() * 1000),
                    "symbol": row[0],
                    "openInterest": str(oi) if oi is not None else None,
                    "longShortRatio": str(ls) if ls is not None else None,
                    "takerLongShortRatio": str(tl) if tl is not None else None,
                }
            )
        return api_response(data)
    except psycopg.OperationalError as e:
        return error_response(ErrorCode.SERVICE_UNAVAILABLE, f"数据库连接失败: {e}")
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, f"查询失败: {e}")
