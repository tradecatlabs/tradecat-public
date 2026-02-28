#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SQLite → PostgreSQL：迁移运行态状态库（signal-service / sheets-service）

目标：
- signal_state.*：cooldown / signal_subs / signal_history
- sheets_state.*：sent_keys

默认 dry-run（只读 + 统计），使用 --apply 才会写入。
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


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


def _resolve_repo_root(start: Path) -> Path:
    for p in [start] + list(start.parents):
        if (p / "services").is_dir() and (p / "assets" / "config" / ".env.example").exists():
            return p
    raise RuntimeError(f"无法定位 repo root（从 {start} 向上未找到 services + assets/config/.env.example）")


def _parse_ts(val: str) -> datetime:
    raw = (val or "").strip()
    if not raw:
        return datetime.now(timezone.utc)
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except Exception:
        return datetime.now(timezone.utc)


@dataclass(frozen=True)
class SqlitePaths:
    cooldown: Path
    subs: Path
    history: Path
    sheets_idem: Path


def _sqlite_ro(path: Path) -> sqlite3.Connection:
    # uri ro：避免误写
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _batched(rows: Iterable[tuple], *, batch_size: int) -> Iterable[list[tuple]]:
    buf: list[tuple] = []
    for r in rows:
        buf.append(r)
        if len(buf) >= batch_size:
            yield buf
            buf = []
    if buf:
        yield buf


def main() -> int:
    p = argparse.ArgumentParser(description="Migrate sqlite state dbs to PostgreSQL (signal_state / sheets_state)")
    p.add_argument("--apply", action="store_true", help="执行写入（默认 dry-run）")
    p.add_argument("--database-url", default="", help="PG DSN（默认读 env:DATABASE_URL 或 assets/config/.env）")
    p.add_argument("--signal-sqlite-dir", default="assets/database/services/signal-service", help="signal-service sqlite 目录")
    p.add_argument("--sheets-idem-sqlite", default="services/consumption/sheets-service/data/idempotency.db", help="sheets-service 幂等 sqlite 路径")
    p.add_argument("--signal-schema", default="signal_state", help="PG schema：signal_state")
    p.add_argument("--sheets-schema", default="sheets_state", help="PG schema：sheets_state")
    p.add_argument("--history-since-days", type=int, default=30, help="迁移信号历史：仅迁移最近 N 天（默认 30）")
    p.add_argument("--history-truncate", action="store_true", help="迁移前清空 PG signal_history（危险操作）")
    p.add_argument("--batch-size", type=int, default=2000, help="PG executemany 批量大小（默认 2000）")
    args = p.parse_args()

    repo_root = _resolve_repo_root(Path(__file__).resolve())
    env = _read_env_file(repo_root)

    database_url = (args.database_url or os.environ.get("DATABASE_URL") or env.get("DATABASE_URL") or "").strip()
    if not database_url:
        print("❌ 缺少 DATABASE_URL（可用 --database-url 或在 assets/config/.env 中配置）")
        return 2

    signal_dir = (repo_root / args.signal_sqlite_dir).resolve()
    sqlite_paths = SqlitePaths(
        cooldown=(signal_dir / "cooldown.db"),
        subs=(signal_dir / "signal_subs.db"),
        history=(signal_dir / "signal_history.db"),
        sheets_idem=(repo_root / args.sheets_idem_sqlite).resolve(),
    )

    try:
        import psycopg
    except Exception as exc:
        print(f"❌ 缺少 psycopg：{type(exc).__name__}: {exc}")
        return 2

    apply = bool(args.apply)
    print(f"mode={'apply' if apply else 'dry-run'}")
    print(f"database_url={database_url}")
    print(f"signal_sqlite_dir={signal_dir}")
    print(f"sheets_idem_sqlite={sqlite_paths.sheets_idem}")

    # ---------- connect pg ----------
    with psycopg.connect(database_url, connect_timeout=3) as pg_conn:
        with pg_conn.cursor() as cur:
            # ensure tables exist
            required = [
                f"{args.signal_schema}.cooldown",
                f"{args.signal_schema}.signal_subs",
                f"{args.signal_schema}.signal_history",
                f"{args.sheets_schema}.sent_keys",
            ]
            for tbl in required:
                cur.execute("SELECT to_regclass(%s)", (tbl,))
                if cur.fetchone()[0] is None:
                    print(f"❌ 缺少 PG 表：{tbl}（请先执行 assets/database/db/schema/022_signal_state.sql / 023_sheets_state.sql）")
                    return 2

            def _pg_count(sql_text: str, params: tuple = ()) -> int:
                cur.execute(sql_text, params)
                row = cur.fetchone()
                return int((row or [0])[0] or 0)

            # ---------- cooldown ----------
            print(f"cooldown.pg rows={_pg_count(f'SELECT COUNT(*) FROM {args.signal_schema}.cooldown')}")
            if sqlite_paths.cooldown.exists():
                with _sqlite_ro(sqlite_paths.cooldown) as sconn:
                    rows = sconn.execute("SELECT key, timestamp FROM cooldown").fetchall()
                print(f"cooldown.sqlite rows={len(rows)}")
                if apply and rows:
                    for batch in _batched(((k, float(ts or 0.0)) for k, ts in rows), batch_size=args.batch_size):
                        cur.executemany(
                            f"""
                            INSERT INTO {args.signal_schema}.cooldown (key, ts_epoch)
                            VALUES (%s, %s)
                            ON CONFLICT (key) DO UPDATE
                            SET ts_epoch=EXCLUDED.ts_epoch, updated_at=now()
                            """,
                            batch,
                        )
                    print(f"cooldown.pg upserted~={len(rows)}")
            else:
                print(f"cooldown.sqlite missing: {sqlite_paths.cooldown}")

            # ---------- subs ----------
            print(f"signal_subs.pg rows={_pg_count(f'SELECT COUNT(*) FROM {args.signal_schema}.signal_subs')}")
            if sqlite_paths.subs.exists():
                with _sqlite_ro(sqlite_paths.subs) as sconn:
                    rows = sconn.execute("SELECT user_id, enabled, tables FROM signal_subs").fetchall()
                print(f"signal_subs.sqlite rows={len(rows)}")
                if apply and rows:
                    payload: list[tuple[int, bool, str]] = []
                    for user_id, enabled, tables in rows:
                        tables_raw = (tables or "").strip()
                        if not tables_raw:
                            tables_json = "null"
                        else:
                            # sqlite 中为 JSON 字符串，尽量原样迁移为 jsonb
                            try:
                                obj = json.loads(tables_raw)
                                tables_json = json.dumps(obj, ensure_ascii=False)
                            except Exception:
                                tables_json = json.dumps([], ensure_ascii=False)
                        payload.append((int(user_id), bool(int(enabled or 0)), tables_json))
                    for batch in _batched(payload, batch_size=args.batch_size):
                        cur.executemany(
                            f"""
                            INSERT INTO {args.signal_schema}.signal_subs (user_id, enabled, tables)
                            VALUES (%s, %s, (%s)::jsonb)
                            ON CONFLICT (user_id) DO UPDATE
                            SET enabled=EXCLUDED.enabled, tables=EXCLUDED.tables, updated_at=now()
                            """,
                            batch,
                        )
                    print(f"signal_subs.pg upserted~={len(rows)}")
            else:
                print(f"signal_subs.sqlite missing: {sqlite_paths.subs}")

            # ---------- history ----------
            if sqlite_paths.history.exists():
                since = datetime.now(timezone.utc) - timedelta(days=int(args.history_since_days))
                cutoff_iso = since.isoformat()
                print(
                    f"signal_history.pg rows={_pg_count(f'SELECT COUNT(*) FROM {args.signal_schema}.signal_history WHERE ts > %s', (since,))} since_days={args.history_since_days}"
                )
                with _sqlite_ro(sqlite_paths.history) as sconn:
                    rows = sconn.execute(
                        """
                        SELECT timestamp, symbol, signal_type, direction, strength, message, timeframe, price, source, extra
                        FROM signal_history
                        WHERE timestamp > ?
                        ORDER BY timestamp ASC
                        """,
                        (cutoff_iso,),
                    ).fetchall()
                print(f"signal_history.sqlite rows={len(rows)} since_days={args.history_since_days}")
                if apply:
                    if args.history_truncate:
                        print("⚠️ history-truncate=1：将清空 PG signal_history")
                        cur.execute(f"TRUNCATE TABLE {args.signal_schema}.signal_history")
                    if rows:
                        payload: list[tuple] = []
                        for ts, symbol, signal_type, direction, strength, message, timeframe, price, source, extra in rows:
                            dt = _parse_ts(str(ts or ""))
                            extra_json = (extra or "").strip()
                            if not extra_json:
                                extra_json = "{}"
                            payload.append(
                                (
                                    dt,
                                    str(symbol or ""),
                                    str(signal_type or ""),
                                    str(direction or ""),
                                    int(strength or 0),
                                    str(message or ""),
                                    str(timeframe or ""),
                                    float(price) if price is not None else None,
                                    str(source or "sqlite"),
                                    extra_json,
                                )
                            )
                        for batch in _batched(payload, batch_size=args.batch_size):
                            cur.executemany(
                                f"""
                                INSERT INTO {args.signal_schema}.signal_history
                                  (ts, symbol, signal_type, direction, strength, message, timeframe, price, source, extra)
                                VALUES
                                  (%s, %s, %s, %s, %s, %s, %s, %s, %s, (%s)::jsonb)
                                """,
                                batch,
                            )
                        print(f"signal_history.pg inserted~={len(rows)}")
            else:
                print(f"signal_history.sqlite missing: {sqlite_paths.history}")

            # ---------- sheets idempotency ----------
            print(f"sheets_state.sent_keys.pg rows={_pg_count(f'SELECT COUNT(*) FROM {args.sheets_schema}.sent_keys')}")
            if sqlite_paths.sheets_idem.exists():
                with _sqlite_ro(sqlite_paths.sheets_idem) as sconn:
                    rows = sconn.execute("SELECT card_key FROM sent_keys").fetchall()
                keys = [str(r[0]) for r in rows if r and r[0]]
                print(f"sheets_idempotency.sqlite keys={len(keys)}")
                if apply and keys:
                    for batch in _batched(((k,) for k in keys), batch_size=args.batch_size):
                        cur.executemany(
                            f"INSERT INTO {args.sheets_schema}.sent_keys(card_key) VALUES (%s) ON CONFLICT DO NOTHING",
                            batch,
                        )
                    print(f"sheets_state.sent_keys.pg inserted~={len(keys)}")
            else:
                print(f"sheets_idempotency.sqlite missing: {sqlite_paths.sheets_idem}")

        if apply:
            pg_conn.commit()
            print("✅ commit 完成")
        else:
            pg_conn.rollback()
            print("ℹ️ dry-run：未写入（已 rollback）")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
