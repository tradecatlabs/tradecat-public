from __future__ import annotations

import logging

from fastapi import APIRouter, Header, Query
from fastapi.concurrency import run_in_threadpool

from src import __version__
from src.query import service as query_service
from src.query.cards import build_card_payload
from src.query.dao import fetch_indicator_rows
from src.query.datasources import check_sources
from src.routers.ohlc import get_ohlc_history as _get_futures_ohlc_history
from src.utils.errors import ErrorCode, api_response, error_response

from assets.common.contracts.cards_contract import ALL_CARD_CONTRACTS, CARD_ID_TO_CONTRACT


router = APIRouter(tags=["query_v1"])
LOG = logging.getLogger("tradecat.api.query_v1")


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def _require_token(x_internal_token: str | None) -> bool:
    import os

    mode = (os.environ.get("QUERY_SERVICE_AUTH_MODE") or "required").strip().lower()
    if mode in {"disabled", "off"}:
        return True
    expected = (os.environ.get("QUERY_SERVICE_TOKEN") or "").strip()
    if not expected:
        return False
    return (x_internal_token or "").strip() == expected


def _require_indicators_token(x_internal_token: str | None) -> bool:
    """indicators 表名直通端点属于调试接口：默认必须鉴权。"""
    import os

    expected = (os.environ.get("QUERY_SERVICE_TOKEN") or "").strip()
    if not expected:
        return False
    return (x_internal_token or "").strip() == expected


@router.get("/health")
async def health(x_internal_token: str | None = Header(default=None, alias="X-Internal-Token")) -> dict:
    if not _require_token(x_internal_token):
        return error_response(ErrorCode.PARAM_ERROR, "unauthorized")

    def _build():
        sources = check_sources()
        payload = query_service.health_payload(sources=sources)
        payload["version"] = __version__
        return payload

    try:
        data = await run_in_threadpool(_build)
        return api_response(data)
    except Exception:
        LOG.error("health_failed", exc_info=True)
        return error_response(ErrorCode.INTERNAL_ERROR, "health_failed")


@router.get("/capabilities")
async def capabilities(x_internal_token: str | None = Header(default=None, alias="X-Internal-Token")) -> dict:
    """能力发现：cards/intervals/sources。"""
    if not _require_token(x_internal_token):
        return error_response(ErrorCode.PARAM_ERROR, "unauthorized")

    def _build():
        sources = check_sources()
        payload = query_service.health_payload(sources=sources)
        payload["version"] = __version__

        cards = []
        intervals: set[str] = set()
        for c in ALL_CARD_CONTRACTS:
            intervals.update(c.intervals)
            cards.append(
                {
                    "card_id": c.card_id,
                    "title": c.title,
                    "description": c.description,
                    "available": bool(c.indicator_table),
                    "intervals": list(c.intervals),
                }
            )
        payload["cards"] = cards
        payload["intervals"] = sorted(intervals)
        payload["sources"] = sources
        return payload

    try:
        data = await run_in_threadpool(_build)
        return api_response(data)
    except Exception:
        LOG.error("capabilities_failed", exc_info=True)
        return error_response(ErrorCode.INTERNAL_ERROR, "capabilities_failed")

@router.get("/ohlc/history")
async def ohlc_history(
    symbol: str = Query(..., description="交易对 (BTC 或 BTCUSDT)"),
    exchange: str = Query(default="Binance", description="交易所"),
    interval: str = Query(default="1h", description="K线周期"),
    limit: int = Query(default=100, ge=1, le=1000, description="返回数量"),
    startTime: int | None = Query(default=None, description="开始时间 (毫秒)"),
    endTime: int | None = Query(default=None, description="结束时间 (毫秒)"),
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> dict:
    """Query Service v1: K线历史数据（消费侧稳定契约）。"""
    if not _require_token(x_internal_token):
        return error_response(ErrorCode.PARAM_ERROR, "unauthorized")
    # 复用 CoinGlass 风格实现，避免重复 SQL/格式化逻辑。
    return await _get_futures_ohlc_history(
        symbol=symbol,
        exchange=exchange,
        interval=interval,
        limit=limit,
        startTime=startTime,
        endTime=endTime,
    )


@router.get("/cards/{card_id}")
async def card(
    card_id: str,
    interval: str | None = Query(default=None, description="周期"),
    symbols: str | None = Query(default=None, description="交易对列表（逗号分隔）"),
    limit: int = Query(default=1000, ge=1, le=5000, description="返回数量"),
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> dict:
    if not _require_token(x_internal_token):
        return error_response(ErrorCode.PARAM_ERROR, "unauthorized")

    interval = (interval or "").strip() or "15m"
    sym_list = _parse_csv(symbols) or None

    def _build():
        if card_id not in CARD_ID_TO_CONTRACT:
            return ("card_not_found", None)
        try:
            payload = build_card_payload(card_id=card_id, interval=interval, symbols=sym_list, limit=limit)
            return ("ok", payload)
        except ValueError as ve:
            return (str(ve), None)

    try:
        status, payload = await run_in_threadpool(_build)
        if status != "ok":
            if status in {"card_not_found"}:
                return error_response(ErrorCode.PARAM_ERROR, "card_not_found")
            if status in {"card_offline"}:
                return error_response(ErrorCode.PARAM_ERROR, "card_offline")
            return error_response(ErrorCode.INTERNAL_ERROR, f"card_failed:{status}")
        return api_response(payload)
    except Exception:
        LOG.error("card_failed card_id=%s", card_id, exc_info=True)
        return error_response(ErrorCode.INTERNAL_ERROR, "card_failed")


@router.get("/dashboard")
async def dashboard(
    cards: str | None = Query(default=None, description="卡片列表(card_id)，逗号分隔"),
    intervals: str | None = Query(default=None, description="周期列表，逗号分隔 5m,15m,1h,4h,1d,1w"),
    symbols: str | None = Query(default=None, description="交易对列表，逗号分隔 BTCUSDT,ETHUSDT,..."),
    shape: str = Query(default="wide", description="wide|long"),
    limit: int = Query(default=1000, ge=1, le=5000, description="每卡片每周期最多返回数量"),
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> dict:
    if not _require_token(x_internal_token):
        return error_response(ErrorCode.PARAM_ERROR, "unauthorized")

    card_list = _parse_csv(cards) or ["volume_ranking"]
    interval_list = _parse_csv(intervals) or ["5m", "15m", "1h", "4h", "1d", "1w"]
    sym_list = _parse_csv(symbols) or None

    # 防滥用：硬上限（避免 N×M×K 查询放大打爆 DB/线程池）
    card_list = list(dict.fromkeys(card_list))
    interval_list = list(dict.fromkeys(interval_list))
    if sym_list:
        sym_list = list(dict.fromkeys(sym_list))
    if len(card_list) > 20 or len(interval_list) > 7 or (sym_list and len(sym_list) > 200):
        return error_response(ErrorCode.PARAM_ERROR, "too_many_items")
    shape = (shape or "wide").strip().lower()
    if shape not in {"wide", "long"}:
        return error_response(ErrorCode.PARAM_ERROR, "invalid_shape")

    def _build():
        # 过滤未知卡片，避免单卡片缺失导致整个 dashboard 500
        picked = [c for c in card_list if c in CARD_ID_TO_CONTRACT]
        ignored = [c for c in card_list if c not in CARD_ID_TO_CONTRACT]
        payload = query_service.dashboard_payload(cards=picked, intervals=interval_list, symbols=sym_list, shape=shape, limit=limit)
        if ignored:
            payload = {**payload, "ignored_cards": ignored}
        return payload

    try:
        data = await run_in_threadpool(_build)
        return api_response(data)
    except Exception:
        LOG.error("dashboard_failed", exc_info=True)
        return error_response(ErrorCode.INTERNAL_ERROR, "dashboard_failed")


@router.get("/symbol/{symbol}/snapshot")
async def symbol_snapshot(
    symbol: str,
    panels: str | None = Query(default=None, description="面板列表 basic,futures,advanced"),
    intervals: str | None = Query(default=None, description="周期列表 5m,15m,1h,4h,1d,1w"),
    include_base: bool = Query(default=True, description="是否包含基础数据"),
    include_pattern: bool = Query(default=False, description="是否包含K线形态表"),
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> dict:
    if not _require_token(x_internal_token):
        return error_response(ErrorCode.PARAM_ERROR, "unauthorized")
    raw_symbol = (symbol or "").strip()
    if not raw_symbol:
        return error_response(ErrorCode.PARAM_ERROR, "symbol_empty")

    panel_list = _parse_csv(panels)
    if not panel_list:
        panel_list = ["basic", "futures", "advanced"]
    panel_list = list(dict.fromkeys([p.lower() for p in panel_list]))
    interval_list = list(dict.fromkeys(_parse_csv(intervals) or ["5m", "15m", "1h", "4h", "1d", "1w"]))

    # 防滥用：硬上限（snapshot 是 panels×tables×intervals 的嵌套查询）
    if len(panel_list) > 10 or len(interval_list) > 7:
        return error_response(ErrorCode.PARAM_ERROR, "too_many_items")

    # 复用 indicator router 的字段映射（不再 import TG provider）
    from src.routers.indicator import TABLE_FIELDS, TABLE_ALIAS

    def _build():
        return query_service.symbol_snapshot_payload(
            symbol=raw_symbol,
            panels=panel_list,
            intervals=interval_list,
            include_base=include_base,
            include_pattern=include_pattern,
            table_fields=TABLE_FIELDS,
            table_alias=TABLE_ALIAS,
        )

    try:
        data = await run_in_threadpool(_build)
        return api_response(data)
    except Exception:
        LOG.error("snapshot_failed symbol=%s", raw_symbol, exc_info=True)
        return error_response(ErrorCode.INTERNAL_ERROR, "snapshot_failed")


@router.get("/indicators/{table}")
async def indicators(
    table: str,
    interval: str | None = Query(default=None, description="周期"),
    mode: str = Query(default="latest_per_symbol", description="latest_per_symbol|latest_at_max_ts|single_latest|raw"),
    symbol: str | None = Query(default=None, description="交易对（单币种）"),
    symbols: str | None = Query(default=None, description="交易对列表（逗号分隔）"),
    field_nonempty: str | None = Query(default=None, description="字段非空过滤（仅对 base 类有意义）"),
    limit: int = Query(default=1000, ge=1, le=5000, description="raw 模式 limit"),
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> dict:
    if not _require_indicators_token(x_internal_token):
        return error_response(ErrorCode.PARAM_ERROR, "unauthorized")
    mode = (mode or "").strip()
    if mode not in {"latest_per_symbol", "latest_at_max_ts", "single_latest", "raw"}:
        return error_response(ErrorCode.PARAM_ERROR, "invalid_mode")

    sym_list = _parse_csv(symbols) or None

    def _fetch():
        rows, latest_dt = fetch_indicator_rows(
            table=table,
            interval=interval,
            mode=mode,
            symbol=symbol,
            symbols=sym_list,
            field_nonempty=field_nonempty,
            limit=limit,
        )
        payload = {
            "deprecated": True,
            "deprecated_hint": "请改用 /api/v1/cards/{card_id} 或 /api/v1/dashboard；该接口仅用于内网调试。",
            "table": table,
            "interval": interval or "",
            "mode": mode,
            "rows": rows,
        }
        if latest_dt:
            from src.query.time import format_ts_bundle

            ts = format_ts_bundle(latest_dt)
            payload["latest_ts_utc"] = ts.ts_utc
            payload["latest_ts_ms"] = ts.ts_ms
            payload["latest_ts_shanghai"] = ts.ts_shanghai
        return payload

    try:
        data = await run_in_threadpool(_fetch)
        return api_response(data)
    except Exception:
        LOG.error("indicators_failed table=%s", table, exc_info=True)
        return error_response(ErrorCode.INTERNAL_ERROR, "indicators_failed")
