from __future__ import annotations

from fastapi import APIRouter, Header, Query
from fastapi.concurrency import run_in_threadpool

from src import __version__
from src.query import service as query_service
from src.query.dao import fetch_indicator_rows
from src.query.datasources import check_sources
from src.utils.errors import ErrorCode, api_response, error_response


router = APIRouter(tags=["query_v1"])


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def _require_token(x_internal_token: str | None) -> bool:
    # 为空 = 不启用鉴权
    import os

    expected = (os.environ.get("QUERY_SERVICE_TOKEN") or "").strip()
    if not expected:
        return True
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
    except Exception as exc:
        return error_response(ErrorCode.INTERNAL_ERROR, f"health_failed: {exc}")


@router.get("/dashboard")
async def dashboard(
    intervals: str | None = Query(default=None, description="周期列表，逗号分隔 5m,15m,1h,4h,1d,1w"),
    symbols: str | None = Query(default=None, description="交易对列表，逗号分隔 BTCUSDT,ETHUSDT,..."),
    shape: str = Query(default="wide", description="wide|long"),
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> dict:
    if not _require_token(x_internal_token):
        return error_response(ErrorCode.PARAM_ERROR, "unauthorized")

    interval_list = _parse_csv(intervals) or ["5m", "15m", "1h", "4h", "1d", "1w"]
    sym_list = _parse_csv(symbols) or None
    shape = (shape or "wide").strip().lower()
    if shape not in {"wide", "long"}:
        return error_response(ErrorCode.PARAM_ERROR, "invalid_shape")

    def _build():
        return query_service.dashboard_payload(intervals=interval_list, symbols=sym_list, shape=shape)

    try:
        data = await run_in_threadpool(_build)
        return api_response(data)
    except Exception as exc:
        return error_response(ErrorCode.INTERNAL_ERROR, f"dashboard_failed: {exc}")


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
    panel_list = [p.lower() for p in panel_list]
    interval_list = _parse_csv(intervals) or ["5m", "15m", "1h", "4h", "1d", "1w"]

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
    except Exception as exc:
        return error_response(ErrorCode.INTERNAL_ERROR, f"snapshot_failed: {exc}")


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
    if not _require_token(x_internal_token):
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
        payload = {"table": table, "interval": interval or "", "mode": mode, "rows": rows}
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
    except Exception as exc:
        return error_response(ErrorCode.INTERNAL_ERROR, f"indicators_failed: {exc}")

