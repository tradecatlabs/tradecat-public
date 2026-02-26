#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
信号相关性分析（基于 cooldown.db + PG candles_1m）

输出：
- artifacts/analysis/signal_correlation/signal_events_snapshot.csv
- artifacts/analysis/signal_correlation/buy_sell_rank.csv
- artifacts/analysis/signal_correlation/alert_vol_rank.csv
- artifacts/analysis/signal_correlation/report.md
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

# ==================== 基础配置 ====================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COOLDOWN_DB = PROJECT_ROOT / "assets/database/services/signal-service/cooldown.db"
DEFAULT_HISTORY_DB = PROJECT_ROOT / "assets/database/services/signal-service/signal_history.db"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "artifacts/analysis/signal_correlation"
DEFAULT_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5433/market_data",
)
DEFAULT_HORIZONS = [5, 15, 60, 240, 1440]


# ==================== PG 信号方向映射 ====================

PG_SIGNAL_DIRECTIONS = {
    "price_surge": "BUY",
    "price_dump": "SELL",
    "volume_spike": "ALERT",
    "taker_buy_dominance": "BUY",
    "taker_sell_dominance": "SELL",
    "oi_surge": "ALERT",
    "oi_dump": "ALERT",
    "top_trader_extreme_long": "ALERT",
    "top_trader_extreme_short": "ALERT",
    "taker_ratio_flip_long": "BUY",
    "taker_ratio_flip_short": "SELL",
}


# ==================== 数据结构 ====================


@dataclass
class SignalEvent:
    key: str
    source: str
    rule_name: str
    symbol: str
    timeframe: str
    direction: str | None
    category: str | None
    table: str | None
    event_ts: datetime


# ==================== 工具函数 ====================


def _parse_datetime(value: str | None) -> datetime | None:
    """解析日期字符串，支持 YYYY-MM-DD 或 ISO8601。"""
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        if len(value) == 10:
            return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        raise SystemExit(f"无效的时间格式: {value!r}")


def _load_rule_meta() -> dict[str, dict]:
    """加载 sqlite 规则元数据（方向/分类等）。"""
    rules_path = PROJECT_ROOT / "services/compute/signal-service/src"
    if str(rules_path) not in sys.path:
        sys.path.insert(0, str(rules_path))

    rule_meta: dict[str, dict] = {}
    try:
        from rules import ALL_RULES  # type: ignore

        for r in ALL_RULES:
            rule_meta[r.name] = {
                "direction": r.direction,
                "category": r.category,
                "subcategory": r.subcategory,
                "timeframes": r.timeframes,
                "table": r.table,
            }
    except Exception as exc:
        print(f"警告: 规则元数据加载失败: {exc}", file=sys.stderr)
    return rule_meta


def _parse_pg_key(key: str) -> tuple[str, str] | None:
    """解析 pg: 前缀信号键，返回 (symbol, signal_type)。"""
    if not key.startswith("pg:"):
        return None
    raw = key[3:]
    for signal_type in sorted(PG_SIGNAL_DIRECTIONS.keys(), key=len, reverse=True):
        suffix = f"_{signal_type}"
        if raw.endswith(suffix):
            symbol = raw[: -len(suffix)]
            return symbol, signal_type
    # 兜底：按第一个下划线切分
    if "_" in raw:
        symbol, signal_type = raw.split("_", 1)
        return symbol, signal_type
    return None


def _load_cooldown_events(db_path: Path, rule_meta: dict[str, dict]) -> list[SignalEvent]:
    """从 cooldown.db 解析信号事件。"""
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT key, timestamp FROM cooldown").fetchall()
    conn.close()

    events: list[SignalEvent] = []
    for key, ts in rows:
        event_ts = datetime.fromtimestamp(ts, tz=timezone.utc)
        if key.startswith("pg:"):
            parsed = _parse_pg_key(key)
            if not parsed:
                continue
            symbol, signal_type = parsed
            direction = PG_SIGNAL_DIRECTIONS.get(signal_type)
            events.append(
                SignalEvent(
                    key=key,
                    source="pg",
                    rule_name=signal_type,
                    symbol=symbol,
                    timeframe="5m",
                    direction=direction,
                    category=None,
                    table=None,
                    event_ts=event_ts,
                )
            )
            continue

        parts = key.split("_")
        if len(parts) < 3:
            continue
        timeframe = parts[-1]
        symbol = parts[-2]
        rule_name = "_".join(parts[:-2])
        meta = rule_meta.get(rule_name, {})
        direction = meta.get("direction")
        category = meta.get("category")
        table = meta.get("table")
        events.append(
            SignalEvent(
                key=key,
                source="sqlite",
                rule_name=rule_name,
                symbol=symbol,
                timeframe=timeframe,
                direction=direction,
                category=category,
                table=table,
                event_ts=event_ts,
            )
        )
    return events


def _load_history_events(db_path: Path, rule_meta: dict[str, dict]) -> list[SignalEvent]:
    """从 signal_history.db 读取事件日志。"""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, timestamp, symbol, signal_type, direction, timeframe, source
        FROM signal_history
        ORDER BY id ASC
        """
    ).fetchall()
    conn.close()

    events: list[SignalEvent] = []
    for row in rows:
        ts_raw = row["timestamp"]
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            else:
                ts = ts.astimezone(timezone.utc)
        except ValueError:
            ts = datetime.now(timezone.utc)

        rule_name = row["signal_type"]
        meta = rule_meta.get(rule_name, {})
        events.append(
            SignalEvent(
                key=str(row["id"]),
                source=row["source"] or "sqlite",
                rule_name=rule_name,
                symbol=row["symbol"],
                timeframe=row["timeframe"] or "1h",
                direction=row["direction"],
                category=meta.get("category"),
                table=meta.get("table"),
                event_ts=ts,
            )
        )
    return events


def _build_price_query(horizons: list[int]) -> str:
    """构建价格查询 SQL。"""
    select_cols = [
        "b.event_id",
        "b.entry_ts",
        "b.entry_close",
    ]
    joins = []
    for h in horizons:
        alias = f"c{h}"
        select_cols.append(f"{alias}.close AS close_{h}m")
        joins.append(
            f"""
LEFT JOIN LATERAL (
    SELECT close
    FROM market_data.candles_1m
    WHERE symbol = b.symbol
      AND bucket_ts >= b.entry_ts + interval '{h} minutes'
      AND is_closed = true
    ORDER BY bucket_ts ASC
    LIMIT 1
) {alias} ON true
"""
        )

    return f"""
WITH base AS (
    SELECT e.event_id,
           e.symbol,
           e.event_ts,
           c1.bucket_ts AS entry_ts,
           c1.close AS entry_close
    FROM tmp_signal_events e
    JOIN LATERAL (
        SELECT bucket_ts, close
        FROM market_data.candles_1m
        WHERE symbol = e.symbol
          AND bucket_ts >= e.event_ts
          AND is_closed = true
        ORDER BY bucket_ts ASC
        LIMIT 1
    ) c1 ON true
)
SELECT
    {", ".join(select_cols)}
FROM base b
{"".join(joins)}
""".strip()


def _format_pct(val: float | None) -> str:
    if val is None or pd.isna(val):
        return "-"
    return f"{val * 100:.2f}%"


def _format_num(val: float | None) -> str:
    if val is None or pd.isna(val):
        return "-"
    return f"{val:.6f}"


# ==================== 主流程 ====================


def main() -> int:
    parser = argparse.ArgumentParser(description="信号相关性分析（cooldown + PG candles）")
    parser.add_argument("--cooldown-db", default=str(DEFAULT_COOLDOWN_DB), help="cooldown.db 路径")
    parser.add_argument("--history-db", default=str(DEFAULT_HISTORY_DB), help="signal_history.db 路径")
    parser.add_argument("--database-url", default=DEFAULT_DB_URL, help="PostgreSQL 连接串")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    parser.add_argument("--start", default="", help="起始时间（YYYY-MM-DD 或 ISO8601）")
    parser.add_argument("--end", default="", help="结束时间（YYYY-MM-DD 或 ISO8601）")
    parser.add_argument("--min-n", type=int, default=30, help="排名最小样本数")
    parser.add_argument("--rank-top", type=int, default=10, help="排名 Top N")
    parser.add_argument(
        "--exclude-category",
        action="append",
        default=[],
        help="排除分类（可重复或逗号分隔，例如: pattern,volume）",
    )
    parser.add_argument(
        "--exclude-table",
        action="append",
        default=[],
        help="排除规则表名（可重复或逗号分隔，例如: K线形态扫描器.py）",
    )
    parser.add_argument(
        "--use-history",
        action="store_true",
        help="使用 signal_history.db 作为事件源（完整触发日志）",
    )
    args = parser.parse_args()

    cooldown_db = Path(args.cooldown_db)
    history_db = Path(args.history_db)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    start_dt = _parse_datetime(args.start)
    end_dt = _parse_datetime(args.end)

    rule_meta = _load_rule_meta()
    if args.use_history:
        if not history_db.exists():
            print(f"未找到 history DB: {history_db}", file=sys.stderr)
            return 1
        events = _load_history_events(history_db, rule_meta)
    else:
        events = _load_cooldown_events(cooldown_db, rule_meta)

    if not events:
        print("未解析到任何信号事件。", file=sys.stderr)
        return 1

    df = pd.DataFrame([e.__dict__ for e in events])
    if start_dt:
        df = df[df["event_ts"] >= start_dt]
    if end_dt:
        df = df[df["event_ts"] <= end_dt]

    df = df.dropna(subset=["symbol", "rule_name"]).reset_index(drop=True)

    exclude_categories = []
    for item in args.exclude_category:
        if item:
            exclude_categories.extend([x.strip().lower() for x in item.split(",") if x.strip()])
    exclude_tables = []
    for item in args.exclude_table:
        if item:
            exclude_tables.extend([x.strip() for x in item.split(",") if x.strip()])

    if exclude_categories or exclude_tables:
        mask = pd.Series([True] * len(df))
        if exclude_categories:
            mask &= ~df["category"].fillna("").str.lower().isin(exclude_categories)
        if exclude_tables:
            mask &= ~df["table"].fillna("").isin(exclude_tables)
        df = df[mask].reset_index(drop=True)
    if df.empty:
        print("过滤后无有效事件。", file=sys.stderr)
        return 1

    # ==================== 查询价格 ====================
    pg_conn = psycopg2.connect(args.database_url)
    pg_conn.autocommit = True
    cur = pg_conn.cursor()

    cur.execute("DROP TABLE IF EXISTS tmp_signal_events")
    cur.execute(
        """
        CREATE TEMP TABLE tmp_signal_events (
            event_id BIGINT,
            symbol TEXT,
            event_ts TIMESTAMPTZ
        )
        """
    )

    values = list(
        zip(
            df.index.astype(int).tolist(),
            df["symbol"].tolist(),
            df["event_ts"].dt.tz_convert("UTC").tolist(),
        )
    )
    execute_values(
        cur,
        "INSERT INTO tmp_signal_events (event_id, symbol, event_ts) VALUES %s",
        values,
        page_size=1000,
    )

    horizons = DEFAULT_HORIZONS
    price_sql = _build_price_query(horizons)
    cur.execute(price_sql)
    price_cols = [desc[0] for desc in cur.description]
    price_rows = cur.fetchall()
    prices = pd.DataFrame(price_rows, columns=price_cols)
    pg_conn.close()

    df = df.merge(prices, left_index=True, right_on="event_id", how="inner")

    # ==================== 计算收益 ====================
    for h in horizons:
        df[f"ret_{h}m"] = (df[f"close_{h}m"] - df["entry_close"]) / df["entry_close"]

    # ==================== 汇总统计 ====================
    def win_rate(series: pd.Series, direction: str | None) -> float | None:
        if direction == "BUY":
            return (series > 0).mean()
        if direction == "SELL":
            return (series < 0).mean()
        return None

    summary_rows = []
    for (source, rule_name, direction), grp in df.groupby(
        ["source", "rule_name", "direction"], dropna=False
    ):
        row: dict[str, object] = {
            "source": source,
            "rule_name": rule_name,
            "direction": direction,
            "n": len(grp),
        }
        for h in horizons:
            s = grp[f"ret_{h}m"].dropna()
            row[f"ret_{h}m_mean"] = s.mean() if not s.empty else None
            row[f"ret_{h}m_abs_mean"] = s.abs().mean() if not s.empty else None
            row[f"ret_{h}m_win_rate"] = win_rate(s, direction) if not s.empty else None
        summary_rows.append(row)

    summary = pd.DataFrame(summary_rows)

    # BUY/SELL 排名
    buy_sell = summary[summary["direction"].isin(["BUY", "SELL"])].copy()
    buy_sell["best_win_rate"] = buy_sell[
        [f"ret_{h}m_win_rate" for h in horizons]
    ].max(axis=1)
    buy_sell_rank = buy_sell.sort_values("best_win_rate", ascending=False)

    # ALERT 波动排名（以 60m 绝对均值为主）
    alert = summary[summary["direction"] == "ALERT"].copy()
    alert_rank = alert.sort_values("ret_60m_abs_mean", ascending=False)

    # ==================== 输出文件 ====================
    df.to_csv(output_dir / "signal_events_snapshot.csv", index=False)
    buy_sell_rank.to_csv(output_dir / "buy_sell_rank.csv", index=False)
    alert_rank.to_csv(output_dir / "alert_vol_rank.csv", index=False)

    # ==================== 生成报告 ====================
    report_lines = []
    report_lines.append("# 信号相关性分析报告")
    report_lines.append("")
    report_lines.append(f"- 生成时间: {datetime.now(timezone.utc).isoformat()}")
    report_lines.append(f"- 总事件数: {len(df)}")
    report_lines.append(f"- 信号类型数: {summary.shape[0]}")
    report_lines.append(f"- 数据来源占比: {df['source'].value_counts().to_dict()}")
    report_lines.append(f"- 时间范围: {df['event_ts'].min()} ~ {df['event_ts'].max()}")
    report_lines.append(f"- 事件来源: {'history' if args.use_history else 'cooldown'}")
    if exclude_categories or exclude_tables:
        report_lines.append(
            f"- 过滤条件: exclude_category={exclude_categories or '-'}; "
            f"exclude_table={exclude_tables or '-'}"
        )
    report_lines.append("")

    report_lines.append("## BUY/SELL 胜率 Top")
    report_lines.append(f"- 排名门槛: n >= {args.min_n}")
    report_lines.append("")
    top_buy_sell = buy_sell_rank[buy_sell_rank["n"] >= args.min_n].head(args.rank_top)
    for _, row in top_buy_sell.iterrows():
        report_lines.append(
            "- "
            + f"[{row['source']}] {row['rule_name']} ({row['direction']})"
            + f" | n={int(row['n'])}"
            + f" | 5m={_format_pct(row['ret_5m_win_rate'])}"
            + f" | 15m={_format_pct(row['ret_15m_win_rate'])}"
            + f" | 1h={_format_pct(row['ret_60m_win_rate'])}"
            + f" | 4h={_format_pct(row['ret_240m_win_rate'])}"
            + f" | 1d={_format_pct(row['ret_1440m_win_rate'])}"
        )
    report_lines.append("")

    report_lines.append("## ALERT 波动 Top（1小时绝对涨跌幅均值）")
    top_alert = alert_rank[alert_rank["n"] >= args.min_n].head(args.rank_top)
    for _, row in top_alert.iterrows():
        report_lines.append(
            "- "
            + f"[{row['source']}] {row['rule_name']} (ALERT)"
            + f" | n={int(row['n'])}"
            + f" | 1h_abs={_format_pct(row['ret_60m_abs_mean'])}"
            + f" | 1h_mean={_format_pct(row['ret_60m_mean'])}"
        )
    report_lines.append("")

    report_lines.append("## 注意事项")
    report_lines.append("- cooldown.db 只保存“最后一次触发时间”，不是完整事件日志。")
    report_lines.append("- 本分析仅评估价格走势相关性，未包含预测结果表（当前库中未发现预测表）。")
    report_lines.append("")

    report_lines.append("## MVP 与演进方向")
    report_lines.append("- MVP: 基于 cooldown + 1m K线，快速估算信号与价格的短/中期相关性。")
    report_lines.append("- 演进: 增加 append-only 信号事件表，纳入预测结果与真实成交结果闭环。")
    report_lines.append("")

    (output_dir / "report.md").write_text("\n".join(report_lines), encoding="utf-8")

    print(f"完成：已输出到 {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
