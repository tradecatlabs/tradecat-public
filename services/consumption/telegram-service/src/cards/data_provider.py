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
from assets.common.contracts.cards_contract import resolve_card_id  # noqa: E402


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

    def get_card(
        self,
        *,
        card_id: str,
        interval: str | None,
        symbols: list[str] | None = None,
        limit: int = 1000,
    ) -> dict[str, Any]:
        card_q = quote(card_id, safe="")
        url = f"{self._base}/api/v1/cards/{card_q}"
        params: dict[str, Any] = {"limit": int(limit)}
        if interval:
            params["interval"] = _normalize_period_value(interval)
        if symbols:
            params["symbols"] = ",".join(symbols)

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

    def get_symbol_snapshot(
        self,
        *,
        symbol: str,
        panels: list[str] | None,
        intervals: list[str] | None,
        include_base: bool,
        include_pattern: bool,
    ) -> dict[str, Any]:
        sym_q = quote(symbol, safe="")
        url = f"{self._base}/api/v1/symbol/{sym_q}/snapshot"
        params: dict[str, Any] = {
            "include_base": bool(include_base),
            "include_pattern": bool(include_pattern),
        }
        if panels:
            params["panels"] = ",".join(panels)
        if intervals:
            params["intervals"] = ",".join([_normalize_period_value(i) for i in intervals])

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
    """HTTP 读取端：通过 Query Service 获取卡片/快照数据。"""

    def __init__(self) -> None:
        self._client = _get_client()

    def _allowed_symbols_list(self) -> list[str] | None:
        allowed = _get_allowed_symbols()
        if not allowed:
            return None
        return sorted({s.strip().upper() for s in allowed if s and s.strip()})

    @staticmethod
    def _compat_alias_fields(row: dict[str, Any]) -> dict[str, Any]:
        """为历史卡片逻辑补齐常用别名（不影响新契约字段）。"""
        # symbol aliases
        sym = str(row.get("symbol") or row.get("交易对") or "").upper()
        base_sym = str(row.get("base_symbol") or row.get("币种") or "").upper()
        if sym and "交易对" not in row:
            row["交易对"] = sym
        if base_sym and "币种" not in row:
            row["币种"] = base_sym

        # base aliases
        if "quote_volume" in row and "成交额" not in row:
            row["成交额"] = row.get("quote_volume")
        if "price" in row and "当前价格" not in row:
            row["当前价格"] = row.get("price")
        if "updated_at" in row and "数据时间" not in row:
            row["数据时间"] = row.get("updated_at")
        if "change_percent" in row and "变化率" not in row:
            row["变化率"] = row.get("change_percent")
        return row

    def _flatten_card_rows(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        rows = list(data.get("rows") or [])
        out: list[dict[str, Any]] = []
        for r in rows:
            fields = dict(r.get("fields") or {})
            fields["symbol"] = r.get("symbol") or ""
            fields["base_symbol"] = r.get("base_symbol") or ""
            if r.get("rank") is not None:
                fields["排名"] = r.get("rank")
            out.append(self._compat_alias_fields(fields))
        return out

    def _resolve_card(self, key: str) -> str:
        cid = resolve_card_id(key)
        if not cid:
            raise ValueError(f"unknown_card:{key}")
        return cid

    def fetch_base(self, period: str) -> Dict[str, Dict]:
        """基础数据（按 max_ts 一次取全）。"""
        allowed_vals = self._allowed_symbols_list()
        data = self._client.get_card(card_id="volume_ranking", interval=period, symbols=allowed_vals, limit=5000)
        if ts := data.get("latest_ts_utc"):
            _update_latest(_parse_timestamp(str(ts)))
        latest: Dict[str, Dict] = {}
        for r in self._flatten_card_rows(data):
            sym = str(r.get("交易对") or r.get("symbol") or "").upper()
            if not sym:
                continue
            allowed = _get_allowed_symbols()
            if allowed and sym not in allowed:
                continue
            if sym not in latest:
                latest[sym] = dict(r)
        return latest

    def fetch_metric(self, table: str, period: str) -> List[Dict]:
        """排行榜指标数据（按 latest_per_symbol）。"""
        card_id = self._resolve_card(table)
        allowed_vals = self._allowed_symbols_list()
        data = self._client.get_card(card_id=card_id, interval=period, symbols=allowed_vals, limit=5000)
        if ts := data.get("latest_ts_utc"):
            _update_latest(_parse_timestamp(str(ts)))
        return [dict(r) for r in self._flatten_card_rows(data)]

    def fetch_base_row(self, period: str, symbol: str) -> Dict:
        snap = self._client.get_symbol_snapshot(
            symbol=symbol,
            panels=None,
            intervals=[period],
            include_base=True,
            include_pattern=False,
        )
        if ts := snap.get("latest_ts_utc"):
            _update_latest(_parse_timestamp(str(ts)))
        base = ((snap.get("base") or {}).get("intervals") or {}).get(period) or {}
        return dict(base) if base else {}

    def fetch_row(
        self,
        table: str,
        period: str,
        symbol: str,
        *,
        symbol_keys: tuple = ("交易对", "币种", "symbol"),
        base_fields: Optional[List[str]] = None,
    ) -> Dict:
        # 统一从 Query Service 的结构化快照读取（避免消费端直连/表名直通）
        snap = self._client.get_symbol_snapshot(
            symbol=symbol,
            panels=["basic", "futures", "advanced"],
            intervals=[period],
            include_base=True,
            include_pattern=True,
        )
        if ts := snap.get("latest_ts_utc"):
            _update_latest(_parse_timestamp(str(ts)))

        def _norm(name: str) -> str:
            n = (name or "").strip()
            if n.endswith(".py"):
                n = n[: -3]
            return n

        target = _norm(table)
        if target in {"基础数据同步器", "基础数据"}:
            base = ((snap.get("base") or {}).get("intervals") or {}).get(period) or {}
            return dict(base) if base else {}

        if target in {"K线形态扫描器", "K线形态扫描器.py"}:
            pat = ((snap.get("pattern") or {}).get("intervals") or {}).get(period) or {}
            return dict(pat) if pat else {}

        panels = snap.get("panels") or {}
        for panel_payload in panels.values():
            tables = panel_payload.get("tables") or {}
            for tp in tables.values():
                tname = _norm(str(tp.get("table") or ""))
                if tname == target:
                    row = (tp.get("intervals") or {}).get(period) or {}
                    return dict(row) if row else {}
        return {}

    def merge_with_base(
        self,
        table: str,
        period: str,
        symbol_keys: tuple = ("交易对", "币种", "symbol"),
        base_fields: Optional[List[str]] = None,
    ) -> List[Dict]:
        # 新契约端点 /api/v1/cards 已经在服务端合并基础数据，消费端不再做 join。
        # base_fields 仅用于兼容历史卡片逻辑：这里确保别名字段存在即可。
        rows = self.fetch_metric(table, period)
        if base_fields:
            for r in rows:
                # fetch_metric 已经通过 _compat_alias_fields 补齐
                _ = r
        return rows

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
