from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def _resolve_backend() -> str:
    """
    幂等存储后端：
    - SHEETS_IDEMPOTENCY_BACKEND=pg|sqlite（默认 pg）
    """
    raw = (os.environ.get("SHEETS_IDEMPOTENCY_BACKEND") or "pg").strip().lower()
    return raw if raw in {"pg", "sqlite"} else "pg"


class PgIdempotencyStore:
    """PG 幂等存储（sheets_state.sent_keys）"""

    def __init__(self, database_url: str, *, schema: str = "sheets_state") -> None:
        self._database_url = (database_url or "").strip()
        if not self._database_url:
            raise RuntimeError("missing_database_url")
        self._schema = (schema or "sheets_state").strip() or "sheets_state"
        self._ensure_table()

    def _connect(self):
        import psycopg

        return psycopg.connect(self._database_url, connect_timeout=3)

    def _ensure_table(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass(%s)", (f"{self._schema}.sent_keys",))
                if cur.fetchone()[0] is None:
                    raise RuntimeError(
                        f"missing_table:{self._schema}.sent_keys (run assets/database/db/schema/023_sheets_state.sql)"
                    )

    def has(self, card_key: str) -> bool:
        if not card_key:
            return False
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT 1 FROM {self._schema}.sent_keys WHERE card_key=%s LIMIT 1", (card_key,))
                return cur.fetchone() is not None

    def mark(self, card_key: str) -> None:
        if not card_key:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {self._schema}.sent_keys(card_key) VALUES (%s) ON CONFLICT (card_key) DO NOTHING",
                    (card_key,),
                )


class SqliteIdempotencyStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path))
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sent_keys (
                    card_key TEXT PRIMARY KEY
                );
                """.strip()
            )

    def has(self, card_key: str) -> bool:
        if not card_key:
            return False
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM sent_keys WHERE card_key = ? LIMIT 1;", (card_key,)).fetchone()
            return row is not None

    def mark(self, card_key: str) -> None:
        if not card_key:
            return
        with self._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO sent_keys(card_key) VALUES (?);", (card_key,))


class IdempotencyStore:
    """
    兼容层：对外保持 IdempotencyStore(path) 的构造方式，
    内部按 env 选择 pg/sqlite。
    """

    def __init__(self, path: Path) -> None:
        backend = _resolve_backend()
        if backend == "pg":
            database_url = (os.environ.get("DATABASE_URL") or os.environ.get("TIMESCALE_DATABASE_URL") or "").strip()
            schema = (os.environ.get("SHEETS_STATE_PG_SCHEMA") or "sheets_state").strip() or "sheets_state"
            try:
                self._impl = PgIdempotencyStore(database_url=database_url, schema=schema)
                return
            except Exception:
                # PG 不可用时回退 sqlite（避免因环境缺失导致服务不可用）
                pass
        self._impl = SqliteIdempotencyStore(path)

    def has(self, card_key: str) -> bool:
        return bool(self._impl.has(card_key))

    def mark(self, card_key: str) -> None:
        self._impl.mark(card_key)
