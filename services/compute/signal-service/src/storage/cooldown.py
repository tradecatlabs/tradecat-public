"""
冷却状态持久化
防止服务重启后重复推送信号
"""

import logging
import time
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_PG_SCHEMA = "signal_state"


class PgCooldownStorage:
    """PG 冷却状态持久化存储（signal_state.cooldown）"""

    def __init__(self, database_url: str | None = None, *, schema: str = _PG_SCHEMA) -> None:
        try:
            from ..config import get_database_url
        except ImportError:
            from config import get_database_url

        self.database_url = (database_url or get_database_url() or "").strip()
        if not self.database_url:
            raise RuntimeError("缺少 DATABASE_URL，无法使用 PG 冷却存储")
        self.schema = (schema or _PG_SCHEMA).strip() or _PG_SCHEMA
        self._ensure_table()

    @contextmanager
    def _conn(self):
        import psycopg

        conn = psycopg.connect(self.database_url, connect_timeout=3)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _ensure_table(self) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass(%s)", (f"{self.schema}.cooldown",))
                if cur.fetchone()[0] is None:
                    raise RuntimeError(
                        f"缺少 PG 表 {self.schema}.cooldown；请先执行 assets/database/db/schema/022_signal_state.sql"
                    )

    def get(self, key: str) -> float:
        if not key:
            return 0.0
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT ts_epoch FROM {self.schema}.cooldown WHERE key=%s", (key,))
                row = cur.fetchone()
                return float(row[0]) if row and row[0] is not None else 0.0

    def set(self, key: str, timestamp: float | None = None) -> None:
        if not key:
            return
        ts = float(timestamp or time.time())
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {self.schema}.cooldown (key, ts_epoch)
                    VALUES (%s, %s)
                    ON CONFLICT (key) DO UPDATE
                    SET ts_epoch=EXCLUDED.ts_epoch, updated_at=now()
                    """,
                    (key, ts),
                )

    def load_all(self) -> dict[str, float]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT key, ts_epoch FROM {self.schema}.cooldown")
                rows = cur.fetchall() or []
        out: dict[str, float] = {}
        for k, ts in rows:
            if k is None:
                continue
            try:
                out[str(k)] = float(ts or 0.0)
            except Exception:
                out[str(k)] = 0.0
        return out

    def cleanup(self, max_age: int = 86400) -> None:
        cutoff = time.time() - int(max_age)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM {self.schema}.cooldown WHERE ts_epoch < %s", (float(cutoff),))


# 单例
_storage: PgCooldownStorage | None = None


def get_cooldown_storage() -> PgCooldownStorage:
    global _storage
    if _storage is None:
        _storage = PgCooldownStorage()
    return _storage
