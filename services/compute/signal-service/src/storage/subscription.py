"""
订阅管理（纯逻辑，不依赖 Telegram）
"""

import json
import logging
import threading
from contextlib import contextmanager

try:
    from ..rules import RULES_BY_TABLE
except ImportError:
    from rules import RULES_BY_TABLE

logger = logging.getLogger(__name__)

# 所有表
ALL_TABLES = list(RULES_BY_TABLE.keys())

_PG_SCHEMA = "signal_state"


class PgSubscriptionManager:
    """PG 订阅管理器（signal_state.signal_subs）"""

    def __init__(self, database_url: str | None = None, *, schema: str = _PG_SCHEMA):
        try:
            from ..config import get_database_url
        except ImportError:
            from config import get_database_url

        self.database_url = (database_url or get_database_url() or "").strip()
        if not self.database_url:
            raise RuntimeError("缺少 DATABASE_URL，无法使用 PG 订阅存储")
        self.schema = (schema or _PG_SCHEMA).strip() or _PG_SCHEMA
        self._cache: dict[int, dict] = {}
        self._lock = threading.Lock()
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
                cur.execute("SELECT to_regclass(%s)", (f"{self.schema}.signal_subs",))
                if cur.fetchone()[0] is None:
                    raise RuntimeError(
                        f"缺少 PG 表 {self.schema}.signal_subs；请先执行 assets/database/db/schema/022_signal_state.sql"
                    )

    @staticmethod
    def _parse_tables(raw) -> set[str]:
        if raw is None:
            return set(ALL_TABLES)
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = []
        if isinstance(raw, (list, tuple, set)):
            return {str(x) for x in raw if str(x).strip()}
        return set(ALL_TABLES)

    def _load(self, user_id: int) -> dict | None:
        try:
            with self._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT enabled, tables FROM {self.schema}.signal_subs WHERE user_id=%s",
                        (int(user_id),),
                    )
                    row = cur.fetchone()
            if row:
                enabled = bool(row[0])
                tables = self._parse_tables(row[1])
                return {"enabled": enabled, "tables": tables}
        except Exception as e:
            logger.warning("加载订阅失败 uid=%s: %s", user_id, e)
        return None

    def _save(self, user_id: int, sub: dict) -> None:
        try:
            tables_json = json.dumps(sorted(list(sub.get("tables") or [])), ensure_ascii=False)
            with self._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO {self.schema}.signal_subs (user_id, enabled, tables)
                        VALUES (%s, %s, (%s)::jsonb)
                        ON CONFLICT (user_id) DO UPDATE
                        SET enabled=EXCLUDED.enabled, tables=EXCLUDED.tables, updated_at=now()
                        """,
                        (int(user_id), bool(sub.get("enabled", True)), tables_json),
                    )
        except Exception as e:
            logger.warning("保存订阅失败 uid=%s: %s", user_id, e)

    def get(self, user_id: int) -> dict:
        with self._lock:
            if user_id not in self._cache:
                loaded = self._load(user_id)
                if loaded:
                    self._cache[user_id] = loaded
                else:
                    self._cache[user_id] = {"enabled": True, "tables": set(ALL_TABLES)}
                    self._save(user_id, self._cache[user_id])
            return self._cache[user_id]

    def set_enabled(self, user_id: int, enabled: bool):
        sub = self.get(user_id)
        sub["enabled"] = enabled
        self._save(user_id, sub)

    def toggle_table(self, user_id: int, table: str) -> bool:
        if table not in ALL_TABLES:
            return False
        sub = self.get(user_id)
        if table in sub["tables"]:
            sub["tables"].discard(table)
            result = False
        else:
            sub["tables"].add(table)
            result = True
        self._save(user_id, sub)
        return result

    def enable_all(self, user_id: int):
        sub = self.get(user_id)
        sub["tables"] = set(ALL_TABLES)
        self._save(user_id, sub)

    def disable_all(self, user_id: int):
        sub = self.get(user_id)
        sub["tables"] = set()
        self._save(user_id, sub)

    def is_table_enabled(self, user_id: int, table: str) -> bool:
        sub = self.get(user_id)
        return sub["enabled"] and table in sub["tables"]

    def get_enabled_subscribers(self) -> list[int]:
        try:
            with self._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT user_id FROM {self.schema}.signal_subs WHERE enabled=true")
                    rows = cur.fetchall() or []
            return [int(r[0]) for r in rows if r and r[0] is not None]
        except Exception as e:
            logger.warning("获取订阅用户失败: %s", e)
            return []

    def get_subscribers_for_table(self, table: str) -> list[int]:
        if table not in ALL_TABLES:
            return []
        try:
            with self._conn() as conn:
                with conn.cursor() as cur:
                    # tables 为空/NULL 表示“全部订阅”（兼容旧语义）
                    cur.execute(
                        f"""
                        SELECT user_id
                        FROM {self.schema}.signal_subs
                        WHERE enabled=true AND (tables IS NULL OR tables ? %s)
                        """,
                        (table,),
                    )
                    rows = cur.fetchall() or []
            return [int(r[0]) for r in rows if r and r[0] is not None]
        except Exception as e:
            logger.warning("获取订阅表用户失败 table=%s: %s", table, e)
            return []


# 单例
_manager: PgSubscriptionManager | None = None
_manager_lock = threading.Lock()


def get_subscription_manager() -> PgSubscriptionManager:
    """获取订阅管理器单例"""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = PgSubscriptionManager()
    return _manager
