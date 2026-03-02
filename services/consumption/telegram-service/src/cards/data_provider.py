#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""排行榜数据访问层（Query Service Only）

硬约束：
- 本服务（consumption）禁止直连 PostgreSQL/TimescaleDB
- 所有指标/行情等内部数据读取必须通过 Query Service（/api/v1）完成
"""

from __future__ import annotations

import atexit
import logging
import os
import sys as _sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path as _Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import quote

import httpx


LOGGER = logging.getLogger(__name__)
UTC = timezone.utc


# ============ 币种过滤（使用共享模块）============
_repo_root = str(_Path(__file__).resolve().parents[5])
if _repo_root not in _sys.path:
    _sys.path.insert(0, _repo_root)
from assets.common.symbols import get_configured_symbols_set  # noqa: E402


# 缓存配置的币种（延迟初始化）
_ALLOWED_SYMBOLS: Optional[Set[str]] = None
_SYMBOLS_LOADED = False
_latest_data_time: datetime | None = None   # 历史全局最大
_last_fetch_data_time: datetime | None = None  # 最近一次读取到的数据时间（本次 fetch）


def _get_allowed_symbols() -> Optional[Set[str]]:
    """获取允许的币种集合（延迟加载，首次调用时读取环境变量）"""
    global _ALLOWED_SYMBOLS, _SYMBOLS_LOADED
    if not _SYMBOLS_LOADED:
        _ALLOWED_SYMBOLS = get_configured_symbols_set()
        _SYMBOLS_LOADED = True
        if _ALLOWED_SYMBOLS:
            LOGGER.info("币种过滤已启用: %d 个币种", len(_ALLOWED_SYMBOLS))
    return _ALLOWED_SYMBOLS


def reset_symbols_cache() -> None:
    """重置币种缓存（用于热更新配置）。"""
    global _ALLOWED_SYMBOLS, _SYMBOLS_LOADED
    _ALLOWED_SYMBOLS = None
    _SYMBOLS_LOADED = False
    LOGGER.info("币种缓存已重置，下次请求将重新加载")


def _update_latest(ts: datetime) -> None:
    """记录最近一次读取到的数据时间（模块级共享）。"""
    global _latest_data_time, _last_fetch_data_time
    if ts and ts != datetime.min:
        _last_fetch_data_time = ts
        if _latest_data_time is None or ts > _latest_data_time:
            _latest_data_time = ts


def get_latest_data_time() -> Optional[datetime]:
    """供 UI 查询最近一次 fetch 得到的数据时间；如未读取过数据返回 None。"""
    return _last_fetch_data_time or _latest_data_time


def _parse_timestamp(ts_str: str) -> datetime:
    """解析时间戳字符串为 UTC-aware datetime（失败返回 datetime.min）。"""
    if not ts_str:
        return datetime.min.replace(tzinfo=UTC)
    s = ts_str.strip().replace(" ", "T").replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        else:
            dt = dt.astimezone(UTC)
        return dt
    except Exception:
        return datetime.min.replace(tzinfo=UTC)


# 表名映射（简称 -> 实际表名）
TABLE_NAME_MAP = {
    # 基础
    "基础数据": "基础数据同步器.py",
    # 指标
    "ATR波幅榜单": "ATR波幅扫描器.py",
    "BB榜单": "布林带扫描器.py",
    "布林带榜单": "布林带扫描器.py",
    "CVD榜单": "CVD信号排行榜.py",
    "KDJ随机指标榜单": "KDJ随机指标扫描器.py",
    "K线形态榜单": "K线形态扫描器.py",
    "MACD柱状榜单": "MACD柱状扫描器.py",
    "MFI资金流量榜单": "MFI资金流量扫描器.py",
    "OBV能量潮榜单": "OBV能量潮扫描器.py",
    "VPVR榜单": "VPVR排行生成器.py",
    "VWAP榜单": "VWAP离线信号扫描.py",
    "主动买卖比榜单": "主动买卖比扫描器.py",
    "成交量比率榜单": "成交量比率扫描器.py",
    "支撑阻力榜单": "全量支撑阻力扫描器.py",
    "收敛发散榜单": "G，C点扫描器.py",
    "流动性榜单": "流动性扫描器.py",
    "谐波信号榜单": "谐波信号扫描器.py",
    "趋势线榜单": "趋势线榜单.py",
    "期货情绪聚合榜单": "期货情绪聚合表.py",
}


def format_symbol(sym: str) -> str:
    """将交易对显示为基础币种（去除 USDT 后缀），保持大写."""
    s = (sym or "").strip().upper()
    for suffix in ("USDT",):
        if s.endswith(suffix):
            return s[: -len(suffix)] or s
    return s


def _normalize_period_value(period: str) -> str:
    p = (period or "").strip().lower()
    if p in (f"{24}h", "1day"):
        return "1d"
    return p


def _period_candidates(period: str) -> List[str]:
    target = _normalize_period_value(period)
    return list({target, target.upper(), period, period.lower(), period.upper()})


@dataclass(frozen=True)
class _CacheEntry:
    ts: float
    value: Any


class QueryServiceClient:
    """Query Service HTTP 客户端（进程级复用，带轻量缓存）。"""

    def __init__(self) -> None:
        base = (os.environ.get("QUERY_SERVICE_BASE_URL") or "").strip().rstrip("/")
        if not base:
            raise RuntimeError("missing_env:QUERY_SERVICE_BASE_URL")
        self._base = base
        self._token = (os.environ.get("QUERY_SERVICE_TOKEN") or "").strip()
        self._timeout = float(os.environ.get("QUERY_SERVICE_TIMEOUT_SECONDS", "6"))
        self._cache_ttl = float(os.environ.get("QUERY_SERVICE_CACHE_TTL_SECONDS", "2"))
        self._cache: dict[str, _CacheEntry] = {}
        self._client = httpx.Client(timeout=self._timeout)

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    def _headers(self) -> dict[str, str]:
        if not self._token:
            return {}
        return {"X-Internal-Token": self._token}

    def _cache_get(self, key: str):
        ent = self._cache.get(key)
        if not ent:
            return None
        if (time.time() - ent.ts) > self._cache_ttl:
            self._cache.pop(key, None)
            return None
        return ent.value

    def _cache_set(self, key: str, value: Any) -> None:
        self._cache[key] = _CacheEntry(ts=time.time(), value=value)

    def get_indicators(
        self,
        *,
        table: str,
        interval: str | None,
        mode: str,
        symbol: str | None = None,
        symbols: list[str] | None = None,
        field_nonempty: str | None = None,
        limit: int = 1000,
    ) -> dict[str, Any]:
        table_q = quote(table, safe="")
        url = f"{self._base}/api/v1/indicators/{table_q}"
        params: dict[str, Any] = {"mode": mode, "limit": int(limit)}
        if interval:
            params["interval"] = _normalize_period_value(interval)
        if symbol:
            params["symbol"] = symbol
        if symbols:
            params["symbols"] = ",".join(symbols)
        if field_nonempty:
            params["field_nonempty"] = field_nonempty

        cache_key = f"{url}?{sorted(params.items())}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        resp = self._client.get(url, params=params, headers=self._headers())
        resp.raise_for_status()
        payload = resp.json()
        if not payload or not payload.get("success"):
            raise RuntimeError(f"query_failed:{payload.get('msg') if isinstance(payload, dict) else 'unknown'}")
        data = payload.get("data") or {}
        self._cache_set(cache_key, data)
        return data


_CLIENT: QueryServiceClient | None = None


def _get_client() -> QueryServiceClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = QueryServiceClient()
        atexit.register(lambda: _CLIENT.close() if _CLIENT else None)
    return _CLIENT


class HttpRankingDataProvider:
    """HTTP 读取端：通过 Query Service 获取指标表数据。"""

    def __init__(self) -> None:
        self._client = _get_client()

    def _resolve_table(self, name: str) -> str:
        if name in TABLE_NAME_MAP:
            return TABLE_NAME_MAP[name]
        if not name.endswith(".py"):
            with_py = name + ".py"
            if with_py in TABLE_NAME_MAP:
                return TABLE_NAME_MAP[with_py]
            return with_py
        return name

    def _allowed_symbols_list(self) -> list[str] | None:
        allowed = _get_allowed_symbols()
        if not allowed:
            return None
        return sorted({s.strip().upper() for s in allowed if s and s.strip()})

    def fetch_base(self, period: str) -> Dict[str, Dict]:
        allowed_vals = self._allowed_symbols_list()
        data = self._client.get_indicators(
            table="基础数据同步器.py",
            interval=period,
            mode="latest_at_max_ts",
            symbols=allowed_vals,
            limit=5000,
        )
        rows = list(data.get("rows") or [])
        if ts := data.get("latest_ts_utc"):
            _update_latest(_parse_timestamp(str(ts)))
        latest: Dict[str, Dict] = {}
        for r in rows:
            sym = str(r.get("交易对") or r.get("币种") or r.get("symbol") or "").upper()
            if not sym:
                continue
            allowed = _get_allowed_symbols()
            if allowed and sym not in allowed:
                continue
            if sym not in latest:
                latest[sym] = dict(r)
        return latest

    def fetch_base_with_field(self, period: str, field: str) -> Dict[str, Dict]:
        allowed_vals = self._allowed_symbols_list()
        data = self._client.get_indicators(
            table="基础数据同步器.py",
            interval=period,
            mode="latest_at_max_ts",
            symbols=allowed_vals,
            field_nonempty=(field or "").strip(),
            limit=5000,
        )
        rows = list(data.get("rows") or [])
        if ts := data.get("latest_ts_utc"):
            _update_latest(_parse_timestamp(str(ts)))
        latest: Dict[str, Dict] = {}
        for r in rows:
            sym = str(r.get("交易对") or r.get("币种") or r.get("symbol") or "").upper()
            if not sym:
                continue
            allowed = _get_allowed_symbols()
            if allowed and sym not in allowed:
                continue
            if sym not in latest:
                latest[sym] = dict(r)
        return latest

    def fetch_metric(self, table: str, period: str) -> List[Dict]:
        table = self._resolve_table(table)
        allowed_vals = self._allowed_symbols_list()
        data = self._client.get_indicators(
            table=table,
            interval=period,
            mode="latest_per_symbol",
            symbols=allowed_vals,
            limit=5000,
        )
        rows = list(data.get("rows") or [])
        if ts := data.get("latest_ts_utc"):
            _update_latest(_parse_timestamp(str(ts)))
        return [dict(r) for r in rows]

    def fetch_base_row(self, period: str, symbol: str) -> Dict:
        return self._fetch_single_row("基础数据同步器.py", period, symbol)

    def _fetch_single_row(self, table: str, period: str, symbol: str) -> Dict:
        table = self._resolve_table(table)
        data = self._client.get_indicators(
            table=table,
            interval=period,
            mode="single_latest",
            symbol=symbol,
            limit=1,
        )
        rows = list(data.get("rows") or [])
        if ts := data.get("latest_ts_utc"):
            _update_latest(_parse_timestamp(str(ts)))
        return dict(rows[0]) if rows else {}

    def fetch_row(
        self,
        table: str,
        period: str,
        symbol: str,
        *,
        symbol_keys: tuple = ("交易对", "币种", "symbol"),
        base_fields: Optional[List[str]] = None,
    ) -> Dict:
        row = self._fetch_single_row(table, period, symbol)
        if not row:
            return {}
        base = self.fetch_base_row(period, symbol) or {}
        sym = (symbol or "").strip().upper()
        merged = dict(row)
        merged["symbol"] = sym
        merged["price"] = float(base.get("当前价格", row.get("当前价格", 0)) or 0)
        merged["quote_volume"] = float(base.get("成交额", row.get("成交额", 0)) or 0)
        merged["change_percent"] = float(base.get("变化率", 0) or 0)
        merged["updated_at"] = base.get("数据时间") or row.get("数据时间")
        for k in ["振幅", "交易次数", "成交笔数", "主动买入量", "主动卖出量", "主动买额", "主动卖额", "主动买卖比"]:
            if k in base:
                merged[k] = base.get(k)
        if base_fields:
            for bf in base_fields:
                if bf in base:
                    merged[bf] = base.get(bf)
        return merged

    def merge_with_base(
        self,
        table: str,
        period: str,
        symbol_keys: tuple = ("交易对", "币种", "symbol"),
        base_fields: Optional[List[str]] = None,
    ) -> List[Dict]:
        metrics = self.fetch_metric(table, period)
        if not metrics:
            return []
        base_map = self.fetch_base(period)
        merged: List[Dict] = []
        for r in metrics:
            sym = ""
            for key in symbol_keys:
                val = r.get(key)
                if val:
                    sym = str(val).upper()
                    break
            if not sym:
                continue
            base = base_map.get(sym, {})
            row = dict(r)
            row["symbol"] = sym
            row["price"] = float(base.get("当前价格", r.get("当前价格", 0)) or 0)
            row["quote_volume"] = float(base.get("成交额", r.get("成交额", 0)) or 0)
            row["change_percent"] = float(base.get("变化率", 0) or 0)
            row["updated_at"] = base.get("数据时间") or r.get("数据时间")
            for k in ["振幅", "交易次数", "成交笔数", "主动买入量", "主动卖出量", "主动买额", "主动卖额", "主动买卖比"]:
                if k in base:
                    row[k] = base.get(k)
            if base_fields:
                for bf in base_fields:
                    if bf in base:
                        row[bf] = base.get(bf)
            merged.append(row)
        return merged

    # 兼容旧接口（部分卡片直接调用）
    def get_volume_rows(self, period: str) -> List[Dict]:
        # Volume 不是实际表名：直接从基础数据取“成交量/成交额/价格”
        base_map = self.fetch_base(period)
        merged: List[Dict] = []
        for sym, base in base_map.items():
            merged.append(
                {
                    "symbol": sym,
                    "quote_volume": float(base.get("成交额", 0) or 0),
                    "base_volume": float(base.get("成交量", 0) or 0),
                    "last_close": float(base.get("当前价格", 0) or 0),
                    "first_close": float(base.get("开盘价", 0) or 0),
                    "change_percent": float(base.get("变化率", 0) or 0),
                    "updated_at": base.get("数据时间"),
                }
            )
        return merged

    def get_atr_rows(self, period: str) -> List[Dict]:
        metrics = self.fetch_metric("ATR波幅榜单", period)
        if not metrics:
            return []
        base_map = self.fetch_base(period)
        out: List[Dict] = []
        for r in metrics:
            sym = str(r.get("交易对", r.get("币种", ""))).upper()
            if not sym:
                continue
            base = base_map.get(sym, {})
            out.append(
                {
                    "symbol": sym,
                    "strength": float(r.get("强度", 0) or 0),
                    "atr_pct": float(r.get("ATR百分比", 0) or 0),
                    "price": float(base.get("当前价格", r.get("当前价格", 0)) or 0),
                    "category": r.get("波动分类") or "-",
                    "quote_volume": float(base.get("成交额", 0) or 0),
                    "updated_at": (base.get("数据时间") or r.get("数据时间")),
                }
            )
        return out


_PROVIDER: HttpRankingDataProvider | None = None


def get_ranking_provider() -> HttpRankingDataProvider:
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = HttpRankingDataProvider()
    return _PROVIDER


__all__ = ["HttpRankingDataProvider", "get_ranking_provider", "format_symbol", "get_latest_data_time", "reset_symbols_cache"]

