"""Open Interest 路由 (对齐 CoinGlass /api/futures/open-interest/history)"""

import logging
import psycopg
from psycopg import sql

from fastapi import APIRouter, Query
from fastapi.concurrency import run_in_threadpool

from src.query import market_dao
from src.query.time import normalize_utc
from src.utils.errors import ErrorCode, api_response, error_response
from src.utils.symbol import normalize_symbol

router = APIRouter(tags=["futures"])

LOG = logging.getLogger("tradecat.api.open_interest")

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


@router.get("/open-interest/history")
async def get_open_interest_history(
    symbol: str = Query(..., description="交易对 (BTC 或 BTCUSDT)"),
    exchange: str = Query(default="Binance", description="交易所"),
    interval: str = Query(default="1h", description="周期"),
    limit: int = Query(default=100, ge=1, le=1000, description="返回数量"),
    startTime: int | None = Query(default=None, description="开始时间 (毫秒)"),
    endTime: int | None = Query(default=None, description="结束时间 (毫秒)"),
) -> dict:
    """获取 Open Interest 历史数据"""
    symbol = normalize_symbol(symbol)

    if interval not in VALID_INTERVALS:
        return error_response(ErrorCode.INVALID_INTERVAL, f"无效的 interval: {interval}")
    table = TABLE_BY_INTERVAL.get(interval)
    if not table:
        return error_response(ErrorCode.TABLE_NOT_FOUND, f"未配置 interval: {interval}")

    time_col = "create_time" if interval == "5m" else "bucket"
    schema, table_name = market_dao.split_qualified_table(table)

    def _fetch_rows():
        if not market_dao.table_exists(schema, table_name):
            return ("table_missing", [])

        pool = market_dao.get_market_pool()
        tbl = sql.Identifier(schema, table_name)
        time_ident = sql.Identifier(time_col)

        with pool.connection() as conn:
            with conn.cursor() as cursor:
                exchange_code = _normalize_exchange(exchange)

                query = sql.SQL(
                    """
                    SELECT symbol, {time_col}, sum_open_interest_value
                    FROM {tbl}
                    WHERE symbol = %s
                    """
                ).format(time_col=time_ident, tbl=tbl)
                params: list[object] = [symbol]

                if interval == "5m":
                    query += sql.SQL(" AND exchange = %s")
                    params.append(exchange_code)

                if startTime is not None:
                    query += sql.SQL(" AND {time_col} >= (to_timestamp(%s / 1000.0) AT TIME ZONE 'UTC')").format(
                        time_col=time_ident
                    )
                    params.append(startTime)
                if endTime is not None:
                    query += sql.SQL(" AND {time_col} <= (to_timestamp(%s / 1000.0) AT TIME ZONE 'UTC')").format(
                        time_col=time_ident
                    )
                    params.append(endTime)

                query += sql.SQL(" ORDER BY {time_col} DESC LIMIT %s").format(time_col=time_ident)
                params.append(limit)

                cursor.execute(query, params)
                return ("ok", cursor.fetchall())

    try:
        status, rows = await run_in_threadpool(_fetch_rows)
        if status == "table_missing":
            return error_response(
                ErrorCode.TABLE_NOT_FOUND,
                f"表不存在: {table}",
                extra={"missing_table": {"schema": schema, "table": table_name}},
            )
        # CoinGlass OI 格式 (OHLC style)
        data = []
        for row in reversed(rows):
            oi_value = float(row[2]) if row[2] is not None else None
            dt = normalize_utc(row[1])
            data.append(
                {
                    "time": int((dt.timestamp() if dt else 0) * 1000),
                    "open": str(oi_value) if oi_value is not None else None,
                    "high": str(oi_value) if oi_value is not None else None,
                    "low": str(oi_value) if oi_value is not None else None,
                    "close": str(oi_value) if oi_value is not None else None,
                }
            )
        return api_response(data)
    except psycopg.OperationalError:
        LOG.warning("持仓数据库连接失败", exc_info=True)
        return error_response(ErrorCode.SERVICE_UNAVAILABLE, "数据库连接失败")
    except Exception:
        LOG.warning("查询持仓失败 symbol=%s exchange=%s interval=%s", symbol, exchange, interval, exc_info=True)
        return error_response(ErrorCode.INTERNAL_ERROR, "查询失败")
