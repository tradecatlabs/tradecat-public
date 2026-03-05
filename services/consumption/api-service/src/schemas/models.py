"""Pydantic 数据模型定义"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ApiEnvelope(BaseModel):
    """统一响应封套（对齐 CoinGlass V4 风格）。

    说明：
    - 允许附加字段（例如 `trace_id` / `missing_table` / `ignored_cards`），避免 response_model 过滤掉诊断信息。
    - `data` 的具体结构由各端点负责定义（本模型仅做统一外壳）。
    """

    model_config = ConfigDict(extra="allow")

    code: str
    msg: str
    success: bool
    data: Any | None = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    timestamp: datetime


class SymbolsResponse(BaseModel):
    symbols: list[str]
    count: int


class CandleData(BaseModel):
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float | None = None


class CandlesResponse(BaseModel):
    symbol: str
    interval: str
    data: list[CandleData]
    count: int


class MetricsData(BaseModel):
    symbol: str
    timestamp: datetime
    open_interest: float | None = None
    funding_rate: float | None = None
    long_short_ratio: float | None = None


class MetricsResponse(BaseModel):
    symbol: str
    interval: str
    data: list[MetricsData]
    count: int


class IndicatorResponse(BaseModel):
    table: str
    symbol: str | None
    interval: str | None
    data: list[dict[str, Any]]
    count: int


class TablesResponse(BaseModel):
    tables: list[str]
    count: int


class CooldownItem(BaseModel):
    key: str
    timestamp: float
    expires_at: datetime


class CooldownResponse(BaseModel):
    data: list[CooldownItem]
    count: int
