from __future__ import annotations

import sqlite3
from pathlib import Path


class IdempotencyStore:
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
