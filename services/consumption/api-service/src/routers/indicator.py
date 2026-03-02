"""指标数据路由"""

from __future__ import annotations

import os

from fastapi import APIRouter, Query
from fastapi.concurrency import run_in_threadpool

from src.config import get_pg_pool
from src.query import service as query_service
from src.utils.errors import ErrorCode, api_response, error_response
from src.utils.symbol import normalize_symbol

router = APIRouter(tags=["indicator"])


def _indicator_pg_schema() -> str:
    return (os.environ.get("INDICATOR_PG_SCHEMA") or "tg_cards").strip() or "tg_cards"


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def _normalize_panels(raw: list[str]) -> list[str]:
    allowed = ("basic", "futures", "advanced")
    panels = [p.lower() for p in raw if p.lower() in allowed]
    return panels or list(allowed)


def _ordered_periods(all_periods: tuple[str, ...], picked: set[str]) -> list[str]:
    return [p for p in all_periods if p in picked]


# ==================== TG 快照表映射（仅用于结构化返回） ====================

ALL_PERIODS: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h", "1d", "1w")
FUTURES_PERIODS: tuple[str, ...] = ("5m", "15m", "1h", "4h", "1d", "1w")

TABLE_FIELDS: dict[str, dict[str, tuple[tuple[str, str], ...]]] = {
    "basic": {
        "布林带排行卡片": (
            ("bandwidth", "带宽"),
            ("百分比b", "百分比"),
            ("中轨斜率", "中轨斜率"),
            ("中轨价格", "中轨价格"),
            ("上轨价格", "上轨价格"),
            ("下轨价格", "下轨价格"),
        ),
        "成交量比率排行卡片": (("量比", "量比"), ("信号概述", "信号概述")),
        "支撑阻力排行卡片": (
            ("支撑位", "支撑位"),
            ("阻力位", "阻力位"),
            ("ATR", "ATR"),
            ("距支撑百分比", "距支撑%"),
            ("距阻力百分比", "距阻力%"),
            ("距关键位百分比", "距关键位%"),
        ),
        "主动买卖比排行卡片": (
            ("主动买量", "主动买量"),
            ("主动卖量", "主动卖量"),
            ("主动买卖比", "主动买卖比"),
        ),
        "KDJ排行卡片": (("J值", "J"), ("K值", "K"), ("D值", "D"), ("信号概述", "方向")),
        "MACD柱状排行卡片": (
            ("MACD", "MACD"),
            ("DIF", "DIF"),
            ("DEA", "DEA"),
            ("MACD柱状图", "柱状图"),
            ("信号概述", "信号"),
        ),
        "OBV排行卡片": (("OBV值", "OBV值"), ("OBV变化率", "OBV变化率")),
        "RSI谐波排行卡片": (("谐波值", "谐波值"),),
    },
    "futures": {
        "持仓数据": (
            ("持仓金额", "持仓金额"),
            ("持仓张数", "持仓张数"),
            ("持仓变动%", "持仓变动%"),
            ("持仓变动", "持仓变动"),
            ("持仓斜率", "持仓斜率"),
            ("持仓Z分数", "Z分数"),
            ("OI连续根数", "OI连续根数"),
        ),
        "大户情绪": (
            ("大户多空比", "大户多空比"),
            ("大户偏离", "大户偏离"),
            ("大户情绪动量", "大户动量"),
            ("大户波动", "大户波动"),
        ),
        "全市场情绪": (
            ("全体多空比", "全体多空比"),
            ("全体偏离", "全体偏离"),
            ("全体波动", "全体波动"),
        ),
        "主动成交": (
            ("主动成交多空比", "主动多空比"),
            ("主动偏离", "主动偏离"),
            ("主动情绪动量", "主动动量"),
            ("主动跳变幅度", "主动跳变"),
            ("主动连续根数", "主动连续"),
        ),
        "情绪综合": (
            ("情绪差值", "情绪差值"),
            ("情绪翻转信号", "翻转信号"),
            ("波动率", "波动率"),
            ("风险分", "风险分"),
            ("市场占比", "市场占比"),
        ),
    },
    "advanced": {
        "EMA排行卡片": (
            ("EMA7", "EMA7"),
            ("EMA25", "EMA25"),
            ("EMA99", "EMA99"),
            ("带宽评分", "带宽评分"),
            ("趋势方向", "趋势方向"),
            ("价格", "价格"),
        ),
        "VPVR排行卡片": (
            ("VPVR价格", "VPVR价"),
            ("价值区下沿", "价值区下沿"),
            ("价值区上沿", "价值区上沿"),
            ("价值区宽度百分比", "价值区宽度%"),
            ("价值区覆盖率", "价值区覆盖率"),
            ("价值区位置", "价值区位置"),
        ),
        "VWAP排行卡片": (
            ("偏离度", "偏离度"),
            ("偏离百分比", "偏离%"),
            ("成交量加权", "加权成交额"),
            ("VWAP带宽百分比", "带宽%"),
            ("VWAP上轨", "上轨"),
            ("VWAP下轨", "下轨"),
            ("VWAP价格", "VWAP价格"),
            ("当前价格", "当前价格"),
        ),
        "趋势线排行卡片": (("趋势方向", "趋势方向"), ("距离趋势线%", "距离%")),
        "ATR排行卡片": (
            ("ATR百分比", "ATR%"),
            ("波动分类", "波动"),
            ("上轨", "上轨"),
            ("中轨", "中轨"),
            ("下轨", "下轨"),
            ("当前价格", "价格"),
        ),
        "CVD排行卡片": (("CVD值", "CVD值"), ("变化率", "变化率")),
        "超级精准趋势排行卡片": (
            ("趋势强度", "趋势强度"),
            ("趋势持续根数", "持续根数"),
            ("趋势方向", "方向"),
            ("量能偏向", "量能偏向"),
            ("趋势带", "趋势带"),
            ("最近翻转时间", "最近翻转时间"),
        ),
        "MFI排行卡片": (("MFI值", "MFI"),),
        "流动性排行卡片": (
            ("流动性得分", "流动性得分"),
            ("流动性等级", "流动性等级"),
            ("Amihud得分", "Amihud得分"),
            ("Kyle得分", "Kyle得分"),
            ("波动率得分", "波动率得分"),
            ("成交量得分", "成交量得分"),
            ("Amihud原值", "Amihud原值"),
            ("Kyle原值", "Kyle原值"),
        ),
    },
}

TABLE_ALIAS: dict[str, dict[str, str]] = {
    "basic": {
        "布林带排行卡片": "布林带扫描器",
        "成交量比率排行卡片": "成交量比率扫描器",
        "支撑阻力排行卡片": "全量支撑阻力扫描器",
        "主动买卖比排行卡片": "主动买卖比扫描器",
        "KDJ排行卡片": "KDJ随机指标扫描器",
        "MACD柱状排行卡片": "MACD柱状扫描器",
        "OBV排行卡片": "OBV能量潮扫描器",
        "RSI谐波排行卡片": "谐波信号扫描器",
    },
    "futures": {
        "持仓数据": "期货情绪聚合表",
        "大户情绪": "期货情绪聚合表",
        "全市场情绪": "期货情绪聚合表",
        "主动成交": "期货情绪聚合表",
        "情绪综合": "期货情绪聚合表",
    },
    "advanced": {
        "ATR排行卡片": "ATR波幅扫描器",
        "CVD排行卡片": "CVD信号排行榜",
        "EMA排行卡片": "G，C点扫描器",
        "K线形态排行卡片": "K线形态扫描器",
        "MFI排行卡片": "MFI资金流量扫描器",
        "VPVR排行卡片": "VPVR排行生成器",
        "VWAP排行卡片": "VWAP离线信号扫描",
        "流动性排行卡片": "流动性扫描器",
        "超级精准趋势排行卡片": "超级精准趋势扫描器",
        "趋势线排行卡片": "趋势线榜单",
    },
}


def _build_snapshot(symbol: str, panels: list[str], periods: list[str], include_base: bool,
                    include_pattern: bool) -> dict:
    raw_symbol = (symbol or "").strip().upper()
    if not raw_symbol:
        return {"error": "symbol 不能为空"}

    base_symbol = raw_symbol.replace("USDT", "")
    allowed_periods = set(ALL_PERIODS)
    period_set = {p.lower() for p in periods} if periods else set()
    normalized_panels = _normalize_panels(panels)

    # periods 参数名保持兼容（历史字段）；内部统一称 intervals
    if period_set:
        picked = {p for p in period_set if p in allowed_periods}
        interval_list = _ordered_periods(ALL_PERIODS, picked)
    else:
        interval_list = list(ALL_PERIODS)

    # 仅保留允许的面板
    panel_list = [p for p in normalized_panels if p in ("basic", "futures", "advanced")]

    # 复用 query 层实现：不再依赖 telegram-service 路径/模块
    return query_service.symbol_snapshot_payload(
        symbol=raw_symbol,
        panels=panel_list,
        intervals=interval_list,
        include_base=include_base,
        include_pattern=include_pattern,
        table_fields=TABLE_FIELDS,
        table_alias=TABLE_ALIAS,
    )


@router.get("/indicator/list")
async def get_indicator_list() -> dict:
    """获取可用的指标表列表"""
    def _fetch_tables_pg():
        schema = _indicator_pg_schema()
        pool = get_pg_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema=%s AND table_type='BASE TABLE'
                    ORDER BY table_name
                    """,
                    (schema,),
                )
                rows = cur.fetchall() or []
                return [str(r[0]) for r in rows]

    try:
        tables = await run_in_threadpool(_fetch_tables_pg)
        return api_response(tables)
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, f"查询失败: {e}")


@router.get("/indicator/data")
async def get_indicator_data(
    table: str = Query(..., description="指标表名"),
    symbol: str | None = Query(default=None, description="交易对"),
    interval: str | None = Query(default=None, description="周期"),
    limit: int = Query(default=100, ge=1, le=1000, description="返回数量"),
) -> dict:
    """获取指标数据"""
    def _fetch_rows_pg():
        from psycopg import sql  # type: ignore
        from psycopg.rows import dict_row  # type: ignore

        schema = _indicator_pg_schema()
        pool = get_pg_pool()

        with pool.connection() as conn:
            # 1) 检查表是否存在
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name=%s",
                    (schema, table),
                )
                if not cur.fetchone():
                    return "table_not_found"

                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema=%s AND table_name=%s
                    ORDER BY ordinal_position
                    """,
                    (schema, table),
                )
                cols = {str(r[0]) for r in (cur.fetchall() or [])}

            clauses: list[sql.Composed] = []
            params: list[object] = []

            if symbol and "交易对" in cols:
                clauses.append(sql.SQL("{}=%s").format(sql.Identifier("交易对")))
                params.append(normalize_symbol(symbol))
            if interval and "周期" in cols:
                clauses.append(sql.SQL("{}=%s").format(sql.Identifier("周期")))
                params.append(interval)

            where_sql = sql.SQL("")
            if clauses:
                where_sql = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(clauses)

            tbl = sql.Identifier(schema, table)
            query = sql.SQL("SELECT * FROM {}{} LIMIT %s").format(tbl, where_sql)
            params.append(int(limit))

            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, params)
                rows = cur.fetchall() or []
                return [dict(r) for r in rows]

    try:
        data = await run_in_threadpool(_fetch_rows_pg)
        if data == "table_not_found":
            return error_response(ErrorCode.TABLE_NOT_FOUND, f"表 '{table}' 不存在")

        return api_response(data)
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, f"查询失败: {e}")


@router.get("/indicator/snapshot")
async def get_indicator_snapshot(
    symbol: str = Query(..., description="交易对 (BTC 或 BTCUSDT)"),
    panels: str | None = Query(default=None, description="面板列表，逗号分隔 basic,futures,advanced"),
    periods: str | None = Query(default=None, description="周期列表，逗号分隔 1m,5m,15m,1h,4h,1d,1w"),
    include_base: bool = Query(default=True, description="是否包含基础数据表"),
    include_pattern: bool = Query(default=False, description="是否包含K线形态表"),
) -> dict:
    """结构化返回单币种完整数据（复用 TG 查询逻辑）"""
    raw_symbol = (symbol or "").strip()
    if not raw_symbol:
        return error_response(ErrorCode.PARAM_ERROR, "symbol 不能为空")
    panel_list = _parse_csv(panels)
    period_list = _parse_csv(periods)

    def _fetch():
        return _build_snapshot(raw_symbol, panel_list, period_list, include_base, include_pattern)

    try:
        data = await run_in_threadpool(_fetch)
        if "error" in data:
            return error_response(ErrorCode.PARAM_ERROR, data["error"])
        return api_response(data)
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, f"查询失败: {e}")
