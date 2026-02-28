# -*- coding: utf-8 -*-
"""
数据获取器 - 全量版
- 从 TimescaleDB 获取 K线数据（50条）
- 从 PostgreSQL(tg_cards) 获取全部指标数据
- 复用 telegram-service 的 data_provider（单币快照）
"""
from __future__ import annotations

import os
import sys
from urllib.parse import urlparse
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Set

from src.config import PROJECT_ROOT

# 添加 telegram-service 路径，复用 data_provider
TELEGRAM_SRC = PROJECT_ROOT / "services" / "consumption" / "telegram-service" / "src"
if str(TELEGRAM_SRC) not in sys.path:
    sys.path.insert(0, str(TELEGRAM_SRC))

# TimescaleDB 连接配置（优先 DATABASE_URL）
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("TIMESCALE_DATABASE_URL")
if DATABASE_URL:
    parsed = urlparse(DATABASE_URL)
    DB_HOST = parsed.hostname or os.getenv("TIMESCALE_HOST", "localhost")
    DB_PORT = str(parsed.port or os.getenv("TIMESCALE_PORT", "5433"))
    DB_USER = parsed.username or os.getenv("TIMESCALE_USER", "postgres")
    DB_PASS = parsed.password or os.getenv("TIMESCALE_PASSWORD", "postgres")
    DB_NAME = (parsed.path or "").lstrip("/") or os.getenv("TIMESCALE_DB", "market_data")
else:
    DB_HOST = os.getenv("TIMESCALE_HOST", "localhost")
    DB_PORT = os.getenv("TIMESCALE_PORT", "5433")
    DB_USER = os.getenv("TIMESCALE_USER", "postgres")
    DB_PASS = os.getenv("TIMESCALE_PASSWORD", "postgres")
    DB_NAME = os.getenv("TIMESCALE_DB", "market_data")

ALL_INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]

# AI 指标表配置
def _get_ai_tables_config() -> Optional[Set[str]]:
    """从环境变量获取 AI 指标表配置"""
    enabled = os.getenv("AI_INDICATOR_TABLES", "").strip()
    disabled = os.getenv("AI_INDICATOR_TABLES_DISABLED", "").strip()

    enabled_set = {t.strip() for t in enabled.split(",") if t.strip()} if enabled else None
    disabled_set = {t.strip() for t in disabled.split(",") if t.strip()} if disabled else set()

    return enabled_set, disabled_set

AI_TABLES_ENABLED, AI_TABLES_DISABLED = _get_ai_tables_config()


def _get_pg_conn():
    """获取 PostgreSQL 连接"""
    import psycopg
    conninfo = f"host={DB_HOST} port={DB_PORT} user={DB_USER} password={DB_PASS} dbname={DB_NAME}"
    return psycopg.connect(conninfo)


def fetch_candles(symbol: str, intervals: List[str] = None, limit: int = 50) -> Dict[str, List[Dict[str, Any]]]:
    """获取多周期 K线数据（全量 50 条）"""
    intervals = intervals or ALL_INTERVALS
    candles: Dict[str, List[Dict[str, Any]]] = {}

    try:
        conn = _get_pg_conn()
        cur = conn.cursor()

        for iv in intervals:
            table = f"market_data.candles_{iv}"
            sql = f"""
                SELECT bucket_ts, open, high, low, close, volume, quote_volume, 
                       trade_count, taker_buy_volume, taker_buy_quote_volume
                FROM {table} 
                WHERE symbol = %s 
                ORDER BY bucket_ts DESC 
                LIMIT %s
            """
            cur.execute(sql, (symbol, limit))
            rows = cur.fetchall()

            parsed = []
            for row in rows:
                parsed.append({
                    "bucket_ts": str(row[0]) if row[0] else None,
                    "open": float(row[1]) if row[1] else None,
                    "high": float(row[2]) if row[2] else None,
                    "low": float(row[3]) if row[3] else None,
                    "close": float(row[4]) if row[4] else None,
                    "volume": float(row[5]) if row[5] else None,
                    "quote_volume": float(row[6]) if row[6] else None,
                    "trade_count": int(row[7]) if row[7] else None,
                    "taker_buy_volume": float(row[8]) if row[8] else None,
                    "taker_buy_quote_volume": float(row[9]) if row[9] else None,
                })
            candles[iv] = parsed

        cur.close()
        conn.close()
    except Exception:
        # 回退到 psql CLI
        candles = _fetch_candles_psql(symbol, intervals, limit)

    return candles


def _fetch_candles_psql(symbol: str, intervals: List[str], limit: int) -> Dict[str, List[Dict[str, Any]]]:
    """使用 psql CLI 获取 K线（回退方案）"""
    import subprocess

    candles: Dict[str, List[Dict[str, Any]]] = {}

    for iv in intervals:
        table = f"market_data.candles_{iv}"
        sql = (
            "SELECT bucket_ts,open,high,low,close,volume,quote_volume,trade_count,"
            f"taker_buy_volume,taker_buy_quote_volume FROM {table} "
            f"WHERE symbol='{symbol}' ORDER BY bucket_ts DESC LIMIT {limit}"
        )
        cmd = [
            "psql", "-h", DB_HOST, "-p", DB_PORT, "-U", DB_USER, "-d", DB_NAME,
            "-A", "-F", ",", "-q", "-t", "-P", "footer=off", "-c", sql,
        ]
        env = os.environ.copy()
        env["PGPASSWORD"] = DB_PASS

        res = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if res.returncode != 0:
            candles[iv] = []
            continue

        parsed = []
        for line in res.stdout.splitlines():
            if not line.strip():
                continue
            parts = line.split(",")
            if len(parts) >= 6:
                parsed.append({
                    "bucket_ts": parts[0],
                    "open": float(parts[1]) if parts[1] else None,
                    "high": float(parts[2]) if parts[2] else None,
                    "low": float(parts[3]) if parts[3] else None,
                    "close": float(parts[4]) if parts[4] else None,
                    "volume": float(parts[5]) if parts[5] else None,
                    "quote_volume": float(parts[6]) if len(parts) > 6 and parts[6] else None,
                    "trade_count": int(parts[7]) if len(parts) > 7 and parts[7] else None,
                    "taker_buy_volume": float(parts[8]) if len(parts) > 8 and parts[8] else None,
                    "taker_buy_quote_volume": float(parts[9]) if len(parts) > 9 and parts[9] else None,
                })
        candles[iv] = parsed

    return candles


def fetch_metrics(symbol: str, limit: int = 50) -> List[Dict[str, Any]]:
    """获取期货指标数据（全量 50 条）"""
    try:
        conn = _get_pg_conn()
        cur = conn.cursor()

        sql = """
            SELECT create_time, symbol, sum_open_interest, sum_open_interest_value,
                   sum_toptrader_long_short_ratio, sum_taker_long_short_vol_ratio
            FROM market_data.binance_futures_metrics_5m
            WHERE symbol = %s
            ORDER BY create_time DESC
            LIMIT %s
        """
        cur.execute(sql, (symbol, limit))
        rows = cur.fetchall()

        result = []
        for row in rows:
            result.append({
                "create_time": str(row[0]) if row[0] else None,
                "symbol": row[1],
                "sum_open_interest": str(row[2]) if row[2] else None,
                "sum_open_interest_value": str(row[3]) if row[3] else None,
                "sum_toptrader_long_short_ratio": str(row[4]) if row[4] else None,
                "sum_taker_long_short_vol_ratio": str(row[5]) if row[5] else None,
            })

        cur.close()
        conn.close()
        return result
    except Exception:
        return []


def fetch_indicators_full(symbol: str) -> Dict[str, Any]:
    """从 PG(tg_cards) 获取指标数据（每个周期只取最新一条，按配置过滤表）"""
    try:
        out = _fetch_indicators_full_pg(symbol)
        return out if isinstance(out, dict) else {}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def _fetch_indicators_full_pg(symbol: str) -> Dict[str, Any]:
    """
    从 PostgreSQL 读取 tg_cards schema 的指标表。

    读取策略（与 sqlite 版保持一致）：
    - 有 (周期, 数据时间)：每个周期取最新一条
    - 仅有 数据时间：取最新一条
    - 否则：取一条兜底
    """
    from psycopg import sql

    schema = (os.getenv("INDICATOR_PG_SCHEMA") or "tg_cards").strip() or "tg_cards"
    sym = (symbol or "").strip().upper()
    if not sym:
        return {"error": "empty_symbol"}

    conn = _get_pg_conn()
    cur = conn.cursor()

    # 表列表
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = %s AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """,
        (schema,),
    )
    tables = [r[0] for r in (cur.fetchall() or []) if r and r[0]]

    indicators: Dict[str, Any] = {}

    for tbl in tables:
        # 按配置过滤表
        if AI_TABLES_ENABLED and tbl not in AI_TABLES_ENABLED:
            continue
        if tbl in AI_TABLES_DISABLED:
            continue

        try:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema=%s AND table_name=%s
                ORDER BY ordinal_position
                """,
                (schema, tbl),
            )
            cols = [r[0] for r in (cur.fetchall() or []) if r and r[0]]
            if not cols:
                continue

            sym_col = None
            for cand in ["交易对", "币种", "symbol", "Symbol", "SYMBOL"]:
                if cand in cols:
                    sym_col = cand
                    break
            if sym_col is None:
                continue

            col_sql = sql.SQL(",").join(sql.Identifier(c) for c in cols)
            table_sql = sql.Identifier(schema, tbl)
            sym_sql = sql.Identifier(sym_col)

            rows = []
            if "周期" in cols and "数据时间" in cols:
                period_sql = sql.Identifier("周期")
                ts_sql = sql.Identifier("数据时间")
                q = sql.SQL(
                    "SELECT DISTINCT ON ({period}) {cols} FROM {tbl} "
                    "WHERE {sym_col}=%s ORDER BY {period}, {ts} DESC"
                ).format(period=period_sql, cols=col_sql, tbl=table_sql, sym_col=sym_sql, ts=ts_sql)
                cur.execute(q, (sym,))
                rows = cur.fetchall() or []
            elif "数据时间" in cols:
                ts_sql = sql.Identifier("数据时间")
                q = sql.SQL("SELECT {cols} FROM {tbl} WHERE {sym_col}=%s ORDER BY {ts} DESC LIMIT 1").format(
                    cols=col_sql, tbl=table_sql, sym_col=sym_sql, ts=ts_sql
                )
                cur.execute(q, (sym,))
                rows = cur.fetchall() or []
            else:
                q = sql.SQL("SELECT {cols} FROM {tbl} WHERE {sym_col}=%s LIMIT 1").format(
                    cols=col_sql, tbl=table_sql, sym_col=sym_sql
                )
                cur.execute(q, (sym,))
                rows = cur.fetchall() or []

            if rows:
                indicators[tbl] = [dict(zip(cols, r)) for r in rows]
        except Exception as e:
            indicators[tbl] = {"error": str(e)}

    cur.close()
    conn.close()
    return indicators


def fetch_single_token_data(symbol: str) -> Dict[str, Any]:
    """
    获取单币种完整数据（复用 telegram-service 的 data_provider）
    返回与单币查询相同的完整字段
    """
    try:
        from cards.data_provider import get_ranking_provider, format_symbol

        provider = get_ranking_provider()
        sym = format_symbol(symbol)
        if not sym:
            return {}

        sym_full = sym if sym.endswith("USDT") else sym + "USDT"

        # 获取所有面板数据
        data = {
            "basic": {},      # 基础面板
            "futures": {},    # 合约面板
            "advanced": {},   # 高级面板
        }

        # 基础面板表
        basic_tables = [
            "布林带扫描器", "成交量比率扫描器", "全量支撑阻力扫描器",
            "主动买卖比扫描器", "KDJ随机指标扫描器", "MACD柱状扫描器",
            "OBV能量潮扫描器", "谐波信号扫描器"
        ]

        # 合约面板表
        futures_tables = ["期货情绪聚合表"]

        # 高级面板表
        advanced_tables = [
            "ATR波幅扫描器", "CVD信号排行榜", "G，C点扫描器",
            "K线形态扫描器", "MFI资金流量扫描器", "VPVR排行生成器",
            "VWAP离线信号扫描", "流动性扫描器", "超级精准趋势扫描器", "趋势线榜单"
        ]

        periods = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]

        # 获取基础面板数据
        for tbl in basic_tables:
            data["basic"][tbl] = {}
            for p in periods:
                try:
                    row = provider._fetch_single_row(tbl, p, sym_full)
                    if row:
                        data["basic"][tbl][p] = row
                except Exception:
                    pass

        # 获取合约面板数据
        for tbl in futures_tables:
            data["futures"][tbl] = {}
            for p in periods[1:]:  # 合约不含 1m
                try:
                    row = provider._fetch_single_row(tbl, p, sym_full)
                    if row:
                        data["futures"][tbl][p] = row
                except Exception:
                    pass

        # 获取高级面板数据
        for tbl in advanced_tables:
            data["advanced"][tbl] = {}
            for p in periods:
                try:
                    row = provider._fetch_single_row(tbl, p, sym_full)
                    if row:
                        data["advanced"][tbl][p] = row
                except Exception:
                    pass

        return data
    except ImportError:
        return {}
    except Exception:
        return {}


def fetch_payload(symbol: str, interval: str) -> Dict[str, Any]:
    """
    获取完整数据负载（全量版）
    
    包含：
    - K线数据：全部 7 个周期，每个 50 条
    - 期货指标：50 条
    - tg_cards 指标：全部表的全部数据（按配置过滤；迁移期可回退 SQLite）
    - 单币快照数据：基础/合约/高级三面板完整字段
    """
    candles = fetch_candles(symbol, ALL_INTERVALS, limit=50)
    metrics = fetch_metrics(symbol, limit=50)
    indicators = fetch_indicators_full(symbol)
    snapshot = fetch_single_token_data(symbol)
    data_quality = _build_data_quality(candles, metrics, indicators, snapshot)

    return {
        "symbol": symbol,
        "interval": interval,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        # K线数据（全量）
        "candles": candles,
        # 期货指标（全量）
        "metrics": metrics,
        # SQLite 指标（全量）
        "indicators": indicators,
        # 单币快照数据（复用 telegram-service）
        "snapshot": snapshot,
        # 数据质量与完整性
        "data_quality": data_quality,
    }


def _build_data_quality(
    candles: Dict[str, List[Dict[str, Any]]],
    metrics: List[Dict[str, Any]],
    indicators: Dict[str, Any],
    snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    warnings: List[str] = []

    missing_intervals = []
    empty_intervals = []
    for iv in ALL_INTERVALS:
        rows = candles.get(iv)
        if rows is None:
            missing_intervals.append(iv)
        elif not rows:
            empty_intervals.append(iv)
    if missing_intervals or empty_intervals:
        warnings.append(f"candles_missing={missing_intervals}, empty={empty_intervals}")

    metrics_count = len(metrics) if metrics else 0
    if metrics_count == 0:
        warnings.append("metrics_empty")

    indicator_error_tables = []
    if isinstance(indicators, dict):
        if "error" in indicators and len(indicators) == 1:
            indicator_error_tables.append("all")
        else:
            for name, value in indicators.items():
                if isinstance(value, dict) and "error" in value:
                    indicator_error_tables.append(name)
    indicator_tables = len(indicators) if isinstance(indicators, dict) else 0
    if indicator_tables == 0 or indicator_error_tables:
        warnings.append(f"indicators_errors={indicator_error_tables}")

    snapshot_ok = bool(snapshot)
    if not snapshot_ok:
        warnings.append("snapshot_empty")

    return {
        "ok": len(warnings) == 0,
        "warnings": warnings,
        "candles": {
            "total_intervals": len(ALL_INTERVALS),
            "missing_intervals": missing_intervals,
            "empty_intervals": empty_intervals,
        },
        "metrics": {
            "count": metrics_count,
        },
        "indicators": {
            "tables": indicator_tables,
            "error_tables": indicator_error_tables,
        },
        "snapshot": {
            "ok": snapshot_ok,
            "sections": list(snapshot.keys()) if isinstance(snapshot, dict) else [],
        },
    }


__all__ = [
    "fetch_payload",
    "fetch_candles",
    "fetch_metrics",
    "fetch_indicators_full",
    "fetch_single_token_data",
]
