from __future__ import annotations

import os


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


class IdempotencyStore:
    """
    幂等存储统一走 PG（不再支持 sqlite）。
    """

    def __init__(self) -> None:
        database_url = (os.environ.get("DATABASE_URL") or os.environ.get("TIMESCALE_DATABASE_URL") or "").strip()
        schema = (os.environ.get("SHEETS_STATE_PG_SCHEMA") or "sheets_state").strip() or "sheets_state"
        self._impl = PgIdempotencyStore(database_url=database_url, schema=schema)

    def has(self, card_key: str) -> bool:
        return bool(self._impl.has(card_key))

    def mark(self, card_key: str) -> None:
        self._impl.mark(card_key)
