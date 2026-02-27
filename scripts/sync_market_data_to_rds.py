#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
最小可行：将本地 SQLite 的 market_data.db 增量同步到 PostgreSQL（AWS RDS/Aurora）。

约定：
- 默认增量列：优先使用“数据时间”，其次“时间/time/timestamp/ts”
- 默认唯一键：优先 (交易对, 周期, 增量列)；缺失则降级
- 通过本地 state 文件记录各表最新水位

注意：
- 若目标库无表，会按 SQLite 列结构自动建表（TEXT/REAL/INTEGER -> TEXT/DOUBLE/BIGINT）
- 表名/列名包含中文/点号，统一使用双引号引用
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


# ==================== 基础工具 ====================
def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def load_state(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(path: str, state: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def pick_time_column(columns: Sequence[str]) -> Optional[str]:
    candidates = ["数据时间", "时间", "timestamp", "ts", "time"]
    for c in candidates:
        if c in columns:
            return c
    return None


def pick_key_columns(columns: Sequence[str], time_col: Optional[str]) -> List[str]:
    keys: List[str] = []
    if "交易对" in columns:
        keys.append("交易对")
    if "周期" in columns:
        keys.append("周期")
    if time_col:
        keys.append(time_col)
    return keys


def map_sqlite_type(sqlite_type: str) -> str:
    t = (sqlite_type or "").upper()
    if "INT" in t:
        return "BIGINT"
    if "REAL" in t or "FLOA" in t or "DOUB" in t:
        return "DOUBLE PRECISION"
    if "TEXT" in t or "CHAR" in t or "CLOB" in t:
        return "TEXT"
    return "TEXT"


# ==================== PostgreSQL 连接适配 ====================
def connect_pg(dsn: str):
    try:
        import psycopg  # type: ignore

        return psycopg.connect(dsn)
    except Exception:
        try:
            import psycopg2  # type: ignore

            return psycopg2.connect(dsn)
        except Exception as exc:
            raise RuntimeError(
                "未安装 PostgreSQL 驱动（psycopg 或 psycopg2）。"
                "请先在当前环境中安装：pip install psycopg[binary] 或 pip install psycopg2-binary"
            ) from exc


def pg_execute(cur, sql: str, params: Optional[Sequence[Any]] = None) -> None:
    if params is None:
        cur.execute(sql)
    else:
        cur.execute(sql, params)


def pg_execute_values(cur, sql: str, rows: List[Sequence[Any]]) -> None:
    try:
        from psycopg2.extras import execute_values  # type: ignore

        execute_values(cur, sql, rows)
    except Exception:
        # 回退：逐行插入
        for row in rows:
            cur.execute(sql, row)


# ==================== 核心同步逻辑 ====================
def ensure_table_and_index(
    cur,
    table: str,
    columns: Sequence[Tuple[str, str]],
    key_cols: Sequence[str],
) -> None:
    cols_sql = ", ".join(f"{quote_ident(name)} {map_sqlite_type(col_type)}" for name, col_type in columns)
    create_sql = f"CREATE TABLE IF NOT EXISTS {quote_ident(table)} ({cols_sql})"
    pg_execute(cur, create_sql)

    if key_cols:
        idx_name = f"{table}__uk".replace(" ", "_")
        key_sql = ", ".join(quote_ident(c) for c in key_cols)
        pg_execute(
            cur,
            f"CREATE UNIQUE INDEX IF NOT EXISTS {quote_ident(idx_name)} ON {quote_ident(table)} ({key_sql})",
        )


def build_upsert_sql(table: str, columns: Sequence[str], key_cols: Sequence[str]) -> str:
    col_sql = ", ".join(quote_ident(c) for c in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    if not key_cols:
        return f"INSERT INTO {quote_ident(table)} ({col_sql}) VALUES ({placeholders})"

    conflict_cols = ", ".join(quote_ident(c) for c in key_cols)
    update_cols = [c for c in columns if c not in key_cols]
    if update_cols:
        update_sql = ", ".join(f"{quote_ident(c)} = EXCLUDED.{quote_ident(c)}" for c in update_cols)
    else:
        update_sql = ", ".join(f"{quote_ident(c)} = EXCLUDED.{quote_ident(c)}" for c in columns)
    return (
        f"INSERT INTO {quote_ident(table)} ({col_sql}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict_cols}) DO UPDATE SET {update_sql}"
    )


def fetch_incremental_rows(
    conn: sqlite3.Connection,
    table: str,
    columns: Sequence[str],
    time_col: Optional[str],
    last_watermark: Optional[Any],
    batch_size: int,
) -> Iterable[List[Tuple[Any, ...]]]:
    col_sql = ", ".join(quote_ident(c) for c in columns)
    if time_col and last_watermark is not None:
        sql = f"SELECT {col_sql} FROM {quote_ident(table)} WHERE {quote_ident(time_col)} > ? ORDER BY {quote_ident(time_col)}"
        params = (last_watermark,)
    else:
        sql = f"SELECT {col_sql} FROM {quote_ident(table)}"
        params = None

    cur = conn.cursor()
    if params:
        cur.execute(sql, params)
    else:
        cur.execute(sql)

    while True:
        rows = cur.fetchmany(batch_size)
        if not rows:
            break
        yield rows


def sync_table(
    sqlite_conn: sqlite3.Connection,
    pg_conn,
    table: str,
    state: Dict[str, Any],
    batch_size: int,
) -> None:
    s_cur = sqlite_conn.cursor()
    cols_info = s_cur.execute(f"PRAGMA table_info({quote_ident(table)})").fetchall()
    columns = [(row[1], row[2]) for row in cols_info]
    col_names = [c[0] for c in columns]

    time_col = pick_time_column(col_names)
    key_cols = pick_key_columns(col_names, time_col)

    pg_cur = pg_conn.cursor()
    ensure_table_and_index(pg_cur, table, columns, key_cols)
    upsert_sql = build_upsert_sql(table, col_names, key_cols)

    last_watermark = state.get(table, {}).get("last_watermark")
    max_time = last_watermark
    total = 0

    for batch in fetch_incremental_rows(sqlite_conn, table, col_names, time_col, last_watermark, batch_size):
        pg_execute_values(pg_cur, upsert_sql, batch)
        total += len(batch)
        if time_col:
            idx = col_names.index(time_col)
            max_time = max((row[idx] for row in batch), default=max_time)

    pg_conn.commit()

    if time_col and total > 0:
        state[table] = {"last_watermark": max_time}

    print(f"[同步完成] 表={table} 条数={total} 增量列={time_col or '无'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="增量同步 SQLite market_data.db 到 PostgreSQL")
    parser.add_argument(
        "--sqlite",
        default="assets/database/services/telegram-service/market_data.db",
        help="SQLite 数据库路径",
    )
    parser.add_argument("--pg-dsn", default=os.environ.get("PG_DSN", ""), help="PostgreSQL DSN")
    parser.add_argument(
        "--state",
        default="assets/artifacts/sync_state_market_data.json",
        help="同步水位文件路径",
    )
    parser.add_argument("--tables", default="", help="仅同步指定表，逗号分隔")
    parser.add_argument("--batch-size", type=int, default=1000, help="批量大小")
    args = parser.parse_args()

    if not args.pg_dsn:
        print("[错误] 未提供 --pg-dsn 或环境变量 PG_DSN")
        return 2

    if not os.path.exists(args.sqlite):
        print(f"[错误] SQLite 文件不存在: {args.sqlite}")
        return 2

    state = load_state(args.state)
    sqlite_conn = sqlite3.connect(args.sqlite)
    sqlite_conn.row_factory = sqlite3.Row

    pg_conn = connect_pg(args.pg_dsn)

    s_cur = sqlite_conn.cursor()
    all_tables = [row[0] for row in s_cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    if args.tables:
        wanted = {t.strip() for t in args.tables.split(",") if t.strip()}
        tables = [t for t in all_tables if t in wanted]
    else:
        tables = all_tables

    if not tables:
        print("[提示] 未找到可同步的表")
        return 0

    for table in tables:
        sync_table(sqlite_conn, pg_conn, table, state, args.batch_size)

    save_state(args.state, state)
    print(f"[完成] 水位已写入: {args.state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
