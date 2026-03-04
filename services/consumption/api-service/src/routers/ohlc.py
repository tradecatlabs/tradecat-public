"""K线数据路由 (对齐 CoinGlass /api/futures/ohlc/history)"""

import logging
import psycopg
from psycopg import sql

from fastapi import APIRouter, Query
from fastapi.concurrency import run_in_threadpool

from src.query import market_dao
from src.utils.errors import ErrorCode, api_response, error_response
from src.utils.symbol import normalize_symbol

router = APIRouter(tags=["futures"])

LOG = logging.getLogger("tradecat.api.ohlc")

VALID_INTERVALS = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "1w", "1M"]

TABLE_BY_INTERVAL = {
    "1m": "market_data.candles_1m",
    "3m": "market_data.candles_3m",
    "5m": "market_data.candles_5m",
    "15m": "market_data.candles_15m",
    "30m": "market_data.candles_30m",
    "1h": "market_data.candles_1h",
    "2h": "market_data.candles_2h",
    "4h": "market_data.candles_4h",
    "6h": "market_data.candles_6h",
    "12h": "market_data.candles_12h",
    "1d": "market_data.candles_1d",
    "1w": "market_data.candles_1w",
    "1M": "market_data.candles_1M",
}


def _normalize_exchange(exchange: str) -> str:
    """标准化交易所标识"""
    ex = (exchange or "").strip().lower()
    if ex in {"binance", "binance_futures", "binance_usdm", "binanceusdm", "binance_futures_um"}:
        return "binance_futures_um"
    return ex or "binance_futures_um"


@router.get("/ohlc/history")
async def get_ohlc_history(
    symbol: str = Query(..., description="交易对 (BTC 或 BTCUSDT)"),
    exchange: str = Query(default="Binance", description="交易所"),
    interval: str = Query(default="1h", description="K线周期"),
    limit: int = Query(default=100, ge=1, le=1000, description="返回数量"),
    startTime: int | None = Query(default=None, description="开始时间 (毫秒)"),
    endTime: int | None = Query(default=None, description="结束时间 (毫秒)"),
) -> dict:
    """获取K线历史数据"""
    symbol = normalize_symbol(symbol)

    if interval not in VALID_INTERVALS:
        return error_response(ErrorCode.INVALID_INTERVAL, f"无效的 interval: {interval}")
    table = TABLE_BY_INTERVAL.get(interval)
    if not table:
        return error_response(ErrorCode.TABLE_NOT_FOUND, f"未配置 interval: {interval}")

    schema, table_name = market_dao.split_qualified_table(table)

    def _fetch_rows():
        if not market_dao.table_exists(schema, table_name):
            return ("table_missing", [])

        pool = market_dao.get_market_pool()
        tbl = sql.Identifier(schema, table_name)

        with pool.connection() as conn:
            with conn.cursor() as cursor:
                exchange_code = _normalize_exchange(exchange)

                query = sql.SQL(
                    """
                    SELECT symbol, bucket_ts, open, high, low, close, volume, quote_volume
                    FROM {tbl}
                    WHERE symbol = %s AND exchange = %s
                    """
                ).format(tbl=tbl)
                params: list[object] = [symbol, exchange_code]

                if startTime is not None:
                    query += sql.SQL(" AND bucket_ts >= to_timestamp(%s / 1000.0)")
                    params.append(startTime)
                if endTime is not None:
                    query += sql.SQL(" AND bucket_ts <= to_timestamp(%s / 1000.0)")
                    params.append(endTime)

                query += sql.SQL(" ORDER BY bucket_ts DESC LIMIT %s")
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
        # 转换为 CoinGlass 格式
        data = []
        for row in reversed(rows):
            volume_usd = row[7] if row[7] is not None else None
            data.append(
                {
                    "time": int(row[1].timestamp() * 1000),
                    "open": str(row[2]) if row[2] is not None else None,
                    "high": str(row[3]) if row[3] is not None else None,
                    "low": str(row[4]) if row[4] is not None else None,
                    "close": str(row[5]) if row[5] is not None else None,
                    "volume": str(row[6]) if row[6] is not None else None,
                    "volume_usd": str(volume_usd) if volume_usd is not None else None,
                }
            )
        return api_response(data)
    except psycopg.OperationalError:
        LOG.warning("K线数据库连接失败", exc_info=True)
        return error_response(ErrorCode.SERVICE_UNAVAILABLE, "数据库连接失败")
    except Exception:
        LOG.warning("查询K线失败 symbol=%s exchange=%s interval=%s", symbol, exchange, interval, exc_info=True)
        return error_response(ErrorCode.INTERNAL_ERROR, "查询失败")
