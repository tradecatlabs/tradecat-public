"""
REST 路由定义。

当前暴露健康检查、模板列表、示例渲染接口。
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.settings import Settings, get_settings
from templates.registry import TemplateMeta, register_defaults, render_kline_envelope

PROJECT_ROOT = Path(__file__).resolve().parents[5]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from assets.common.symbols import get_configured_symbols
except Exception:  # noqa: BLE001
    get_configured_symbols = None

router = APIRouter()
registry = register_defaults()


def _parse_symbol_list(val: str) -> List[str]:
    """解析逗号分隔的币种列表。"""
    return [s.strip().upper() for s in val.split(",") if s.strip()]


def _resolve_ui_symbols() -> List[str]:
    """从环境变量获取可视化页面的币种列表，优先使用配置的有效币种。"""
    symbols: List[str] | None = None
    if get_configured_symbols:
        try:
            symbols = get_configured_symbols()
        except Exception:
            symbols = None

    if symbols is None:
        base = _parse_symbol_list(os.environ.get("SYMBOLS_GROUP_main4", "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT"))
        extra = _parse_symbol_list(os.environ.get("SYMBOLS_EXTRA", ""))
        exclude = set(_parse_symbol_list(os.environ.get("SYMBOLS_EXCLUDE", "")))
        symbols = sorted(set(base).union(extra) - exclude)

    return symbols or ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]


class RenderRequest(BaseModel):
    """渲染请求体。"""

    template_id: str = Field(..., description="模板标识，如 line-basic")
    params: Dict[str, Any] = Field(default_factory=dict, description="模板参数")
    output: str = Field("png", description="输出类型：png 或 json")


def require_token(
    settings: Settings = Depends(get_settings),
    token: str | None = Header(default=None, alias="X-Vis-Token"),
):
    """简易 Token 校验，未配置 token 时直接放行。"""

    if not settings.token:
        return settings
    if token != settings.token:
        raise HTTPException(status_code=401, detail="无效的访问令牌")
    return settings


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> Dict[str, str]:
    """健康检查。"""

    return {"status": "ok", "service": settings.service_name}


@router.get("/templates", response_model=List[TemplateMeta])
def list_templates() -> List[TemplateMeta]:
    """列出已注册模板。"""

    return list(registry.list())


def _resolve_exchange_default() -> str:
    return os.environ.get("BINANCE_WS_DB_EXCHANGE") or os.environ.get("DB_EXCHANGE") or "binance_futures_um"


@router.get("/kline-envelope")
def kline_envelope_page(
    symbol: str | None = None,
    intervals: str | None = None,
    limit: int = 500,
    exchange: str | None = None,
    range_days: int | None = None,
):
    """多周期K线包络可视化页面（含币种选择）。"""
    symbols = _resolve_ui_symbols()
    selected = (symbol or symbols[0]).upper()
    if selected not in symbols:
        selected = symbols[0]

    interval_str = intervals or "1m,5m,15m,1h,4h,1d,1w"
    exchange = exchange or _resolve_exchange_default()
    range_days = range_days or 30
    query = urlencode(
        {
            "symbol": selected,
            "intervals": interval_str,
            "limit": limit,
            "exchange": exchange,
            "range_days": range_days,
        }
    )
    iframe_src = f"/kline-envelope/view?{query}"

    options = "\n".join(
        [f'<option value="{s}" {"selected" if s == selected else ""}>{s}</option>' for s in symbols]
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>多周期K线包络</title>
  <style>
    body {{
      margin: 0;
      font-family: "PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
      background: #f6f6f6;
      color: #1f1f1f;
    }}
    header {{
      padding: 16px 24px;
      background: #ffffff;
      border-bottom: 1px solid #e5e5e5;
      display: flex;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
    }}
    select {{
      padding: 6px 10px;
      border: 1px solid #d0d0d0;
      border-radius: 4px;
      background: #fff;
    }}
    .meta {{
      font-size: 12px;
      color: #666;
    }}
    iframe {{
      width: 100%;
      height: calc(100vh - 64px);
      border: none;
      background: #ffffff;
    }}
  </style>
</head>
<body>
  <header>
    <div>多周期K线包络</div>
    <label>
      币种：
      <select id="symbolSelect">
        {options}
      </select>
    </label>
    <label>
      时间范围：
      <select id="rangeSelect">
        <option value="3">3天</option>
        <option value="7">7天</option>
        <option value="14">14天</option>
        <option value="30">30天</option>
        <option value="60">60天</option>
        <option value="180">180天</option>
        <option value="365">365天</option>
      </select>
    </label>
    <span class="meta">周期：{interval_str}</span>
  </header>
  <iframe id="klineFrame" src="{iframe_src}"></iframe>
  <script>
    const select = document.getElementById("symbolSelect");
    const frame = document.getElementById("klineFrame");
    const rangeSelect = document.getElementById("rangeSelect");
    const baseQuery = "{interval_str}";
    const baseExchange = "{exchange}";
    const baseLimit = "{limit}";
    rangeSelect.value = "{range_days}";

    function reloadFrame() {{
      const params = new URLSearchParams({{
        symbol: select.value,
        intervals: baseQuery,
        limit: baseLimit,
        exchange: baseExchange,
        range_days: rangeSelect.value
      }});
      frame.src = `/kline-envelope/view?${{params.toString()}}`;
    }}

    select.addEventListener("change", reloadFrame);
    rangeSelect.addEventListener("change", reloadFrame);
  </script>
</body>
</html>
"""
    return Response(content=html, media_type="text/html; charset=utf-8")


@router.get("/kline-envelope/view")
def kline_envelope_view(
    symbol: str,
    intervals: str | None = None,
    limit: int = 500,
    exchange: str | None = None,
    startTime: int | None = None,
    endTime: int | None = None,
    range_days: int | None = None,
):
    """多周期K线包络视图（直接返回复用模板的 HTML）。"""
    exchange = exchange or _resolve_exchange_default()
    params: Dict[str, Any] = {
        "symbol": symbol,
        "intervals": intervals or "5m,1h,4h,1d",
        "limit": limit,
        "exchange": exchange,
    }
    if range_days is not None:
        params["range_days"] = range_days
    if startTime is not None:
        params["startTime"] = startTime
    if endTime is not None:
        params["endTime"] = endTime

    try:
        content, media_type = render_kline_envelope(params, "html")
        return Response(content=content, media_type=media_type)
    except ValueError as exc:
        err_html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>数据不可用</title></head>
<body style="font-family:Arial; padding:24px;">
  <h2>数据不可用</h2>
  <p>{str(exc)}</p>
  <p>请检查数据库是否已有对应周期数据，或确认 exchange 设置。</p>
</body></html>"""
        return Response(content=err_html, media_type="text/html; charset=utf-8", status_code=400)


@router.post("/render")
def render(req: RenderRequest, settings: Settings = Depends(require_token)):
    """渲染指定模板。"""

    meta_and_fn = registry.get(req.template_id)
    if not meta_and_fn:
        raise HTTPException(status_code=404, detail="模板不存在")

    meta, render_fn = meta_and_fn
    if req.output not in meta.outputs:
        raise HTTPException(status_code=400, detail=f"输出类型不支持: {req.output}")

    try:
        content, media_type = render_fn(req.params, req.output)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"渲染失败: {exc}") from exc

    if media_type == "application/json":
        return JSONResponse(content=content, media_type=media_type)

    return Response(content=content, media_type=media_type)
