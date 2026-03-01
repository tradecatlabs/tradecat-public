#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SQLite → PostgreSQL：迁移指标库 market_data.db（样本/增量回放用）

核心目标：
- 以“只读 SQLite（mode=ro）”方式读取 `assets/database/services/telegram-service/market_data.db`
- 将部分样本行写入 PG 的指定 schema（默认：tg_cards_sample）
- 不影响现网 `tg_cards.*`：默认写入新的 schema；未显式 --apply 时不写入

注意：
- 表名/列名包含中文与标点，PG 侧必须双引号引用（psycopg.sql.Identifier 已处理）
- 默认不做 retention 清理（仅做幂等删除：同 (交易对, 周期, 数据时间) 先删后插）
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


def _resolve_repo_root(start: Path) -> Path:
    for p in [start] + list(start.parents):
        if (p / "services").is_dir() and (p / "assets" / "config" / ".env.example").exists():
            return p
    raise RuntimeError(f"无法定位 repo root（从 {start} 向上未找到 services + assets/config/.env.example）")


def _read_env_file(repo_root: Path) -> dict[str, str]:
    env_file = repo_root / "assets" / "config" / ".env"
    if not env_file.exists():
        env_file = repo_root / "config" / ".env"
    if not env_file.exists():
        return {}

    out: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip("\"'")
    return out


def _mask_dsn(dsn: str) -> str:
    # postgresql://user:pass@host:port/db -> postgresql://user:***@host:port/db
    try:
        from urllib.parse import urlparse

        p = urlparse(dsn)
        userinfo = ""
        if p.username:
            userinfo = p.username
            if p.password is not None:
                userinfo += ":***"
        netloc = userinfo + ("@" if userinfo else "") + (p.hostname or "") + (f":{p.port}" if p.port else "")
        return p._replace(netloc=netloc).geturl()
    except Exception:
        return "<masked>"


def _sqlite_ro(path: Path, *, busy_timeout_ms: int) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=max(1.0, busy_timeout_ms / 1000.0))
    conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
    return conn


def _sqlite_quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _sqlite_list_tables(conn: sqlite3.Connection) -> list[str]:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return [str(r[0]) for r in cur.fetchall() or []]


def _sqlite_table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({_sqlite_quote_ident(table)})").fetchall()
    return [str(r[1]) for r in rows]


def _pick_time_column(cols: list[str]) -> str | None:
    for c in ["数据时间", "时间", "timestamp", "ts", "time"]:
        if c in cols:
            return c
    return None


def _sqlite_fetch_sample_df(
    conn: sqlite3.Connection,
    *,
    table: str,
    limit: int,
    order: str,
) -> "pd.DataFrame":
    import pandas as pd

    cols = _sqlite_table_columns(conn, table)
    if not cols:
        return pd.DataFrame()

    time_col = _pick_time_column(cols)
    safe_table = _sqlite_quote_ident(table)
    col_sql = ", ".join(_sqlite_quote_ident(c) for c in cols)

    base_sql = f"SELECT {col_sql} FROM {safe_table}"
    if time_col:
        safe_time = _sqlite_quote_ident(time_col)
        direction = "DESC" if order == "latest" else "ASC"
        base_sql += f" ORDER BY {safe_time} {direction}"
    base_sql += " LIMIT ?"

    rows = conn.execute(base_sql, (int(limit),)).fetchall()
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows, columns=cols)


def _sqlite_stream_rows(
    conn: sqlite3.Connection,
    *,
    table: str,
    pg_cols: list[str],
    sqlite_batch_size: int,
) -> Iterable[list[tuple[Any, ...]]]:
    """
    full 模式：按 PG 列顺序流式读取 SQLite 行。

    - SQLite 缺列：用 NULL 填充
    - 不做 ORDER BY（避免全表排序开销）
    """
    sqlite_cols = set(_sqlite_table_columns(conn, table))
    safe_table = _sqlite_quote_ident(table)

    exprs: list[str] = []
    for c in pg_cols:
        if c in sqlite_cols:
            exprs.append(_sqlite_quote_ident(c))
        else:
            exprs.append(f"NULL AS {_sqlite_quote_ident(c)}")
    select_sql = f"SELECT {', '.join(exprs)} FROM {safe_table}"

    cur = conn.cursor()
    cur.execute(select_sql)
    while True:
        rows = cur.fetchmany(int(sqlite_batch_size))
        if not rows:
            break
        yield rows


@dataclass(frozen=True)
class PgTarget:
    dsn: str
    schema: str
    clone_from_schema: str


def _pg_connect(dsn: str):
    import psycopg

    return psycopg.connect(dsn, connect_timeout=3)


def _pg_schema_exists(cur, schema: str) -> bool:
    cur.execute("SELECT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name=%s)", (schema,))
    return bool(cur.fetchone()[0])


def _pg_list_tables(cur, schema: str) -> list[str]:
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema=%s AND table_type='BASE TABLE'
        ORDER BY table_name
        """,
        (schema,),
    )
    return [str(r[0]) for r in cur.fetchall() or []]


def _pg_ensure_schema_and_tables(cur, *, target_schema: str, clone_from_schema: str) -> None:
    from psycopg import sql

    cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(target_schema)))

    src_tables = _pg_list_tables(cur, clone_from_schema)
    if not src_tables:
        raise RuntimeError(f"clone schema 为空：{clone_from_schema}（请先确保 tg_cards.* 已创建）")

    for t in src_tables:
        cur.execute(
            sql.SQL("CREATE TABLE IF NOT EXISTS {} (LIKE {} INCLUDING ALL)").format(
                sql.Identifier(target_schema, t),
                sql.Identifier(clone_from_schema, t),
            )
        )


def _pg_load_columns(cur, *, schema: str, table: str) -> list[tuple[str, str]]:
    cur.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema=%s AND table_name=%s
        ORDER BY ordinal_position
        """,
        (schema, table),
    )
    rows = cur.fetchall() or []
    return [(str(r[0]), str(r[1])) for r in rows]


def _coerce_value(typ: str, val: Any) -> Any:
    if val is None:
        return None
    if typ == "integer":
        try:
            return int(val)
        except Exception:
            return None
    if typ == "double precision":
        try:
            return float(val)
        except Exception:
            return None
    # text/other
    try:
        return str(val)
    except Exception:
        return None


def _pg_quote_ident(name: str) -> str:
    # psycopg 使用 %s 占位符：SQL 文本里出现字面量 % 必须写成 %%
    return '"' + str(name).replace('"', '""').replace("%", "%%") + '"'


def _pg_qual_table(schema: str, table: str) -> str:
    return f"{_pg_quote_ident(schema)}.{_pg_quote_ident(table)}"


def _pg_delete_existing_keys(cur, *, schema: str, table: str, df: "pd.DataFrame", pg_cols: list[str]) -> int:
    if not {"交易对", "周期", "数据时间"}.issubset(set(pg_cols)):
        return 0
    if df is None or df.empty:
        return 0

    import pandas as pd

    keys = df[["交易对", "周期", "数据时间"]].drop_duplicates()
    keys = keys[(keys["交易对"].notna()) & (keys["周期"].notna()) & (keys["数据时间"].notna())]
    if keys.empty:
        return 0

    keys = keys.astype(str)
    tbl = _pg_qual_table(schema, table)
    delete_sql = (
        f"DELETE FROM {tbl} "
        f"WHERE {_pg_quote_ident('交易对')}=%s AND {_pg_quote_ident('周期')}=%s AND {_pg_quote_ident('数据时间')}=%s"
    )
    cur.executemany(delete_sql, list(keys.itertuples(index=False, name=None)))
    return int(len(keys))


def _pg_insert_rows(cur, *, schema: str, table: str, cols_meta: list[tuple[str, str]], df: "pd.DataFrame") -> int:
    if df is None or df.empty:
        return 0

    import pandas as pd

    pg_cols = [c for c, _t in cols_meta]

    # 对齐列：缺失补 None，多余丢弃
    for c in pg_cols:
        if c not in df.columns:
            df[c] = None
    df = df[pg_cols]

    # NaN -> None
    df = df.where(pd.notnull(df), None)

    tbl = _pg_qual_table(schema, table)
    cols_sql = ", ".join(_pg_quote_ident(c) for c in pg_cols)
    placeholders = ", ".join(["%s"] * len(pg_cols))
    insert_sql = f"INSERT INTO {tbl} ({cols_sql}) VALUES ({placeholders})"

    rows: list[tuple[Any, ...]] = []
    for tup in df.itertuples(index=False, name=None):
        rows.append(tuple(_coerce_value(typ, val) for (_c, typ), val in zip(cols_meta, tup)))

    if not rows:
        return 0

    cur.executemany(insert_sql, rows)
    return int(len(rows))


def _pg_truncate_table(cur, *, schema: str, table: str) -> None:
    cur.execute(f"TRUNCATE TABLE {_pg_qual_table(schema, table)}")


def _pg_insert_many(
    cur,
    *,
    schema: str,
    table: str,
    cols_meta: list[tuple[str, str]],
    rows: list[tuple[Any, ...]],
) -> int:
    if not rows:
        return 0

    pg_cols = [c for c, _t in cols_meta]
    tbl = _pg_qual_table(schema, table)
    cols_sql = ", ".join(_pg_quote_ident(c) for c in pg_cols)
    placeholders = ", ".join(["%s"] * len(pg_cols))
    insert_sql = f"INSERT INTO {tbl} ({cols_sql}) VALUES ({placeholders})"

    types = [typ for _c, typ in cols_meta]
    out_rows: list[tuple[Any, ...]] = []
    for r in rows:
        out_rows.append(tuple(_coerce_value(t, v) for t, v in zip(types, r)))

    cur.executemany(insert_sql, out_rows)
    return int(len(out_rows))


def _batched(items: list[str], *, batch_size: int) -> Iterable[list[str]]:
    buf: list[str] = []
    for x in items:
        buf.append(x)
        if len(buf) >= batch_size:
            yield buf
            buf = []
    if buf:
        yield buf


def _normalize_windows_path(raw: str) -> str:
    s = (raw or "").strip().strip('"').strip("'")
    if not s:
        return s
    # Windows: C:\Users\foo\bar.db -> /mnt/c/Users/foo/bar.db（WSL）
    m = re.match(r"^([A-Za-z]):\\\\(.*)$", s)
    if m:
        drive = m.group(1).lower()
        rest = m.group(2).replace("\\\\", "/")
        return f"/mnt/{drive}/{rest}"
    return s


def main() -> int:
    p = argparse.ArgumentParser(description="Import sample rows from sqlite market_data.db into PostgreSQL schema")
    p.add_argument("--apply", action="store_true", help="执行写入（默认 dry-run）")
    p.add_argument(
        "--database-url",
        default="",
        help="PG DSN（默认读 assets/config/.env 的 DATABASE_URL）",
    )
    p.add_argument(
        "--sqlite",
        default="assets/database/services/telegram-service/market_data.db",
        help="SQLite 指标库路径（只读）",
    )
    p.add_argument("--schema", default="tg_cards_sample", help="目标 PG schema（默认 tg_cards_sample）")
    p.add_argument("--clone-from-schema", default="tg_cards", help="克隆表结构来源 schema（默认 tg_cards）")
    p.add_argument("--tables", default="", help="仅导入指定表（逗号分隔），默认导入全部表")
    p.add_argument("--mode", choices=["sample", "full"], default="sample", help="导入模式：sample|full（默认 sample）")
    p.add_argument("--limit", type=int, default=200, help="每张表导入的样本行数（默认 200）")
    p.add_argument("--order", choices=["latest", "oldest"], default="latest", help="样本排序（默认 latest）")
    p.add_argument("--batch-tables", type=int, default=5, help="每批处理多少张表（默认 5）")
    p.add_argument("--sqlite-busy-timeout-ms", type=int, default=5000, help="SQLite busy_timeout 毫秒（默认 5000）")
    p.add_argument("--sqlite-batch-size", type=int, default=5000, help="full 模式：SQLite fetchmany 批量（默认 5000）")
    p.add_argument("--pg-batch-size", type=int, default=2000, help="full 模式：PG executemany 批量（默认 2000）")
    p.add_argument("--truncate", action="store_true", help="full 模式：导入前清空目标表（建议用于新 schema）")
    args = p.parse_args()

    repo_root = _resolve_repo_root(Path(__file__).resolve())
    env = _read_env_file(repo_root)

    database_url = (args.database_url or os.environ.get("DATABASE_URL") or env.get("DATABASE_URL") or "").strip()
    if not database_url:
        print("❌ 缺少 DATABASE_URL（可用 --database-url 或在 assets/config/.env 中配置）")
        return 2

    sqlite_arg = _normalize_windows_path(str(args.sqlite))
    sqlite_path = (repo_root / sqlite_arg).resolve() if not os.path.isabs(sqlite_arg) else Path(sqlite_arg).resolve()
    if not sqlite_path.exists():
        print(f"❌ SQLite 文件不存在：{sqlite_path}")
        return 2

    apply = bool(args.apply)
    print(f"mode={'apply' if apply else 'dry-run'}")
    print(f"sqlite={sqlite_path}")
    print(f"pg={_mask_dsn(database_url)}")
    print(f"target_schema={args.schema} clone_from={args.clone_from_schema}")
    print(f"import_mode={args.mode}")

    # ---------- list sqlite tables ----------
    with _sqlite_ro(sqlite_path, busy_timeout_ms=int(args.sqlite_busy_timeout_ms)) as sconn:
        sqlite_tables_all = _sqlite_list_tables(sconn)

        if args.tables:
            wanted = {t.strip() for t in args.tables.split(",") if t.strip()}
            sqlite_tables = [t for t in sqlite_tables_all if t in wanted]
        else:
            sqlite_tables = sqlite_tables_all

    if not sqlite_tables:
        print("✅ 未找到可导入的 SQLite 表（或 --tables 过滤后为空）")
        return 0

    # ---------- connect pg ----------
    imported_total = 0
    deleted_keys_total = 0

    import psycopg

    with psycopg.connect(database_url, connect_timeout=3) as pg_conn:
        with pg_conn.cursor() as cur:
            src_tables = _pg_list_tables(cur, args.clone_from_schema)
            if not src_tables:
                print(f"❌ clone schema 为空：{args.clone_from_schema}（请先执行 assets/database/db/schema/021_tg_cards_sqlite_parity.sql）")
                return 2

            # 仅导入 clone schema 已存在的表（避免 lost_and_found 等恢复残留）
            before_n = len(sqlite_tables)
            src_set = set(src_tables)
            sqlite_tables = [t for t in sqlite_tables if t in src_set]
            dropped = before_n - len(sqlite_tables)
            if dropped > 0:
                print(f"[过滤] dropped_tables={dropped}（不在 {args.clone_from_schema} 中）")

            if apply:
                _pg_ensure_schema_and_tables(cur, target_schema=args.schema, clone_from_schema=args.clone_from_schema)
                pg_conn.commit()
            else:
                if _pg_schema_exists(cur, args.schema):
                    tgt_tables = _pg_list_tables(cur, args.schema)
                    print(f"[dry-run] target schema 已存在：{args.schema} tables={len(tgt_tables)}")
                else:
                    print(f"[dry-run] target schema 不存在：{args.schema}（apply 时会创建并克隆 {len(src_tables)} 张表）")

        # 逐批处理，避免单事务过大
        for batch_tables in _batched(sqlite_tables, batch_size=int(args.batch_tables)):
            with _sqlite_ro(sqlite_path, busy_timeout_ms=int(args.sqlite_busy_timeout_ms)) as sconn:
                for table in batch_tables:
                    if args.mode == "sample":
                        # 取样本
                        try:
                            df = _sqlite_fetch_sample_df(sconn, table=table, limit=int(args.limit), order=args.order)
                        except Exception as exc:
                            print(f"⚠️ skip table={table} read_failed: {type(exc).__name__}: {exc}")
                            continue

                        rows = int(len(df)) if df is not None else 0
                        if not apply:
                            print(f"[dry-run] table={table} sample_rows={rows}")
                            continue

                        if rows <= 0:
                            print(f"[apply] table={table} empty")
                            continue

                        with pg_conn.cursor() as cur:
                            cols_meta = _pg_load_columns(cur, schema=args.schema, table=table)
                            if not cols_meta:
                                print(f"⚠️ skip table={table} missing_in_pg: {args.schema}.{table}")
                                continue

                            pg_cols = [c for c, _t in cols_meta]
                            deleted = _pg_delete_existing_keys(cur, schema=args.schema, table=table, df=df, pg_cols=pg_cols)
                            inserted = _pg_insert_rows(cur, schema=args.schema, table=table, cols_meta=cols_meta, df=df)

                        pg_conn.commit()
                        imported_total += inserted
                        deleted_keys_total += deleted
                        print(f"[apply] table={table} deleted_keys={deleted} inserted_rows={inserted}")
                        continue

                    # full 模式：流式导入全部行
                    with pg_conn.cursor() as cur:
                        cols_meta = _pg_load_columns(cur, schema=args.schema, table=table)
                        if not cols_meta:
                            print(f"⚠️ skip table={table} missing_in_pg: {args.schema}.{table}")
                            continue

                        pg_cols = [c for c, _t in cols_meta]

                        if not apply:
                            print(f"[dry-run] table={table} pg_cols={len(pg_cols)}")
                            continue

                        if args.truncate:
                            _pg_truncate_table(cur, schema=args.schema, table=table)
                            pg_conn.commit()

                        inserted = 0
                        for sqlite_rows in _sqlite_stream_rows(
                            sconn,
                            table=table,
                            pg_cols=pg_cols,
                            sqlite_batch_size=int(args.sqlite_batch_size),
                        ):
                            for i in range(0, len(sqlite_rows), int(args.pg_batch_size)):
                                chunk = sqlite_rows[i : i + int(args.pg_batch_size)]
                                inserted += _pg_insert_many(cur, schema=args.schema, table=table, cols_meta=cols_meta, rows=chunk)
                            pg_conn.commit()

                    imported_total += inserted
                    print(f"[apply] table={table} inserted_rows={inserted} (full)")

    if apply:
        print(f"✅ 完成：imported_rows={imported_total} deleted_keys={deleted_keys_total} target_schema={args.schema}")
    else:
        print(f"✅ dry-run 完成：tables={len(sqlite_tables)}")
        print("提示：加上 --apply 才会真正写入。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
