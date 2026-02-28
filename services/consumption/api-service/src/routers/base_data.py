"""基础数据路由（优先 PG tg_cards，迁移期兼容 SQLite）"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime

from fastapi import APIRouter, Query
from fastapi.concurrency import run_in_threadpool
from psycopg import sql

from src.config import get_settings, get_pg_pool
from src.utils.errors import ErrorCode, api_response, error_response
from src.utils.symbol import normalize_symbol

router = APIRouter(tags=["futures"])

BASE_TABLE = "基础数据同步器.py"
BASE_FIELDS: tuple[str, ...] = (
    "交易对",
    "周期",
    "数据时间",
    "开盘价",
    "最高价",
    "最低价",
    "收盘价",
    "当前价格",
    "成交量",
    "成交额",
    "振幅",
    "变化率",
    "交易次数",
    "成交笔数",
    "主动买入量",
    "主动买量",
    "主动买额",
    "主动卖出量",
    "主动买卖比",
    "主动卖出额",
    "资金流向",
    "平均每笔成交额",
)


def _resolve_indicator_read_source() -> str:
    raw = (os.environ.get("INDICATOR_READ_SOURCE") or "auto").strip().lower()
    if raw in {"sqlite", "pg"}:
        return raw
    store_mode = (os.environ.get("INDICATOR_STORE_MODE") or "pg").strip().lower()
    return "pg" if store_mode in {"pg", "dual"} else "sqlite"


def _indicator_pg_schema() -> str:
    return (os.environ.get("INDICATOR_PG_SCHEMA") or "tg_cards").strip() or "tg_cards"


def _parse_ts(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value).timestamp() * 1000)
    except Exception:
        return None


@router.get("/base-data")
async def get_base_data(
    symbol: str = Query(..., description="交易对 (BTC 或 BTCUSDT)"),
    interval: str = Query(default="1h", description="周期 (如 1h/4h/1d)"),
    limit: int = Query(default=200, ge=1, le=5000, description="返回数量"),
    auto_resolve: bool = Query(default=True, description="自动解析交易对/周期"),
) -> dict:
    """读取基础数据（成交额/主动买卖比等）"""
    settings = get_settings()
    db_path = settings.SQLITE_INDICATORS_PATH

    input_symbol = symbol.strip()
    input_interval = interval.strip()

    def _fetch_rows_sqlite():
        if not db_path.exists():
            raise RuntimeError("SQLite 数据库不可用")
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (BASE_TABLE,),
            )
            if not cur.fetchone():
                raise RuntimeError("基础数据表不存在")

            resolved_symbol = normalize_symbol(input_symbol)
            resolved_interval = input_interval

            def _query(sym: str | None, itv: str | None):
                where = []
                params: list = []
                if sym:
                    where.append("交易对 = ?")
                    params.append(sym)
                if itv:
                    where.append("周期 = ?")
                    params.append(itv)
                where_sql = f"WHERE {' AND '.join(where)}" if where else ""
                cur.execute(
                    f'SELECT 交易对, 周期, 数据时间, 开盘价, 最高价, 最低价, 收盘价, 当前价格, '
                    f'成交量, 成交额, 振幅, 变化率, 交易次数, 成交笔数, 主动买入量, 主动买量, '
                    f'主动买额, 主动卖出量, 主动买卖比, 主动卖出额, 资金流向, 平均每笔成交额 '
                    f'FROM "{BASE_TABLE}" {where_sql} ORDER BY 数据时间 DESC LIMIT ?',
                    params + [limit],
                )
                return cur.fetchall()

            rows = _query(resolved_symbol, resolved_interval)

            if not rows and auto_resolve:
                # ==================== 自动解析交易对与周期 ====================
                base = resolved_symbol.replace("USDT", "")
                cur.execute(
                    f'SELECT 交易对, COUNT(*) AS c FROM "{BASE_TABLE}" WHERE 交易对 LIKE ? '
                    f'GROUP BY 交易对 ORDER BY c DESC LIMIT 1',
                    (f"{base}%",),
                )
                row = cur.fetchone()
                if row:
                    resolved_symbol = row[0]
                if resolved_symbol:
                    cur.execute(
                        f'SELECT 周期, COUNT(*) AS c FROM "{BASE_TABLE}" WHERE 交易对 = ? '
                        f'GROUP BY 周期 ORDER BY c DESC LIMIT 1',
                        (resolved_symbol,),
                    )
                    row = cur.fetchone()
                    if row:
                        resolved_interval = row[0]
                rows = _query(resolved_symbol, resolved_interval)

            data = []
            for row in reversed(rows):
                data.append(
                    {
                        "交易对": row["交易对"],
                        "周期": row["周期"],
                        "数据时间": row["数据时间"],
                        "timestamp_ms": _parse_ts(row["数据时间"]),
                        "开盘价": row["开盘价"],
                        "最高价": row["最高价"],
                        "最低价": row["最低价"],
                        "收盘价": row["收盘价"],
                        "当前价格": row["当前价格"],
                        "成交量": row["成交量"],
                        "成交额": row["成交额"],
                        "振幅": row["振幅"],
                        "变化率": row["变化率"],
                        "交易次数": row["交易次数"],
                        "成交笔数": row["成交笔数"],
                        "主动买入量": row["主动买入量"],
                        "主动买量": row["主动买量"],
                        "主动买额": row["主动买额"],
                        "主动卖出量": row["主动卖出量"],
                        "主动买卖比": row["主动买卖比"],
                        "主动卖出额": row["主动卖出额"],
                        "资金流向": row["资金流向"],
                        "平均每笔成交额": row["平均每笔成交额"],
                    }
                )

            return {
                "filters": {"symbol": input_symbol, "interval": input_interval},
                "resolved_filters": {"symbol": resolved_symbol, "interval": resolved_interval},
                "list": data,
            }

    def _fetch_rows_pg():
        pool = get_pg_pool()
        schema = _indicator_pg_schema()

        resolved_symbol = normalize_symbol(input_symbol)
        resolved_interval = input_interval

        def _query(cur, sym: str | None, itv: str | None):
            where = []
            params: list = []
            if sym:
                where.append(sql.SQL('"交易对"=%s'))
                params.append(sym)
            if itv:
                where.append(sql.SQL('"周期"=%s'))
                params.append(itv)
            where_sql = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(where) if where else sql.SQL("")

            query = sql.SQL('SELECT {} FROM {}{} ORDER BY {} DESC LIMIT %s').format(
                sql.SQL(",").join(sql.Identifier(c) for c in BASE_FIELDS),
                sql.Identifier(schema, BASE_TABLE),
                where_sql,
                sql.Identifier("数据时间"),
            )
            cur.execute(query, params + [int(limit)])
            return cur.fetchall() or []

        with pool.connection() as conn:
            with conn.cursor() as cur:
                # table exists?
                cur.execute(
                    "SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name=%s",
                    (schema, BASE_TABLE),
                )
                if not cur.fetchone():
                    raise RuntimeError(f"PG 基础数据表不存在: {schema}.{BASE_TABLE}")

                rows = _query(cur, resolved_symbol, resolved_interval)

                if not rows and auto_resolve:
                    base = resolved_symbol.replace("USDT", "")
                    cur.execute(
                        sql.SQL(
                            'SELECT "交易对", COUNT(*) AS c FROM {} WHERE "交易对" LIKE %s '
                            'GROUP BY "交易对" ORDER BY c DESC LIMIT 1'
                        ).format(sql.Identifier(schema, BASE_TABLE)),
                        (f"{base}%",),
                    )
                    row = cur.fetchone()
                    if row and row[0]:
                        resolved_symbol = str(row[0])

                    if resolved_symbol:
                        cur.execute(
                            sql.SQL(
                                'SELECT "周期", COUNT(*) AS c FROM {} WHERE "交易对"=%s '
                                'GROUP BY "周期" ORDER BY c DESC LIMIT 1'
                            ).format(sql.Identifier(schema, BASE_TABLE)),
                            (resolved_symbol,),
                        )
                        row = cur.fetchone()
                        if row and row[0]:
                            resolved_interval = str(row[0])

                    rows = _query(cur, resolved_symbol, resolved_interval)

        data = []
        for row in reversed(rows):
            r = dict(zip(BASE_FIELDS, row))
            data.append(
                {
                    "交易对": r.get("交易对"),
                    "周期": r.get("周期"),
                    "数据时间": r.get("数据时间"),
                    "timestamp_ms": _parse_ts(r.get("数据时间")),
                    "开盘价": r.get("开盘价"),
                    "最高价": r.get("最高价"),
                    "最低价": r.get("最低价"),
                    "收盘价": r.get("收盘价"),
                    "当前价格": r.get("当前价格"),
                    "成交量": r.get("成交量"),
                    "成交额": r.get("成交额"),
                    "振幅": r.get("振幅"),
                    "变化率": r.get("变化率"),
                    "交易次数": r.get("交易次数"),
                    "成交笔数": r.get("成交笔数"),
                    "主动买入量": r.get("主动买入量"),
                    "主动买量": r.get("主动买量"),
                    "主动买额": r.get("主动买额"),
                    "主动卖出量": r.get("主动卖出量"),
                    "主动买卖比": r.get("主动买卖比"),
                    "主动卖出额": r.get("主动卖出额"),
                    "资金流向": r.get("资金流向"),
                    "平均每笔成交额": r.get("平均每笔成交额"),
                }
            )

        return {
            "filters": {"symbol": input_symbol, "interval": input_interval},
            "resolved_filters": {"symbol": resolved_symbol, "interval": resolved_interval},
            "list": data,
        }

    try:
        source = _resolve_indicator_read_source()
        if source == "pg":
            payload = await run_in_threadpool(_fetch_rows_pg)
        else:
            payload = await run_in_threadpool(_fetch_rows_sqlite)
        return api_response(payload)
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, f"查询失败: {e}")
