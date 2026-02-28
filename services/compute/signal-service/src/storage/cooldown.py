"""
冷却状态持久化
防止服务重启后重复推送信号
"""

import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
import stat

logger = logging.getLogger(__name__)

_PG_SCHEMA = "signal_state"


def _get_cooldown_db_path() -> str:
    """获取冷却数据库路径"""
    # 兼容直接运行和作为模块导入
    try:
        from ..config import REPO_ROOT
    except ImportError:
        REPO_ROOT = Path(__file__).resolve().parents[5]
    return str(REPO_ROOT / "assets/database/services/signal-service/cooldown.db")

def _resolve_backend() -> str:
    """
    冷却存储后端选择：
    - SIGNAL_STATE_BACKEND=pg|sqlite（默认 pg）
    """
    raw = (os.environ.get("SIGNAL_STATE_BACKEND") or "pg").strip().lower()
    return raw if raw in {"pg", "sqlite"} else "pg"


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


class CooldownStorage:
    """冷却状态持久化存储"""

    def __init__(self, db_path: str = None):
        raw_path = db_path or _get_cooldown_db_path()
        resolved = Path(raw_path).resolve()
        repo_root = Path(_get_cooldown_db_path()).resolve().parents[4]
        try:
            resolved.relative_to(repo_root)
        except ValueError:
            raise ValueError(f"非法冷却存储路径: {resolved}")
        self.db_path = str(resolved)
        self._ensure_db()

    def _ensure_db(self):
        """确保数据库存在"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cooldown (
                    key TEXT PRIMARY KEY,
                    timestamp REAL NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON cooldown(timestamp)")
        try:
            os.chmod(self.db_path, stat.S_IRUSR | stat.S_IWUSR)
        except Exception as e:
            logger.warning("设置冷却数据库权限失败: %s", e)

    @contextmanager
    def _conn(self):
        import sqlite3

        conn = sqlite3.connect(self.db_path, timeout=5)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def get(self, key: str) -> float:
        """获取冷却时间戳，不存在返回 0"""
        with self._conn() as conn:
            row = conn.execute("SELECT timestamp FROM cooldown WHERE key = ?", (key,)).fetchone()
            return row[0] if row else 0.0

    def set(self, key: str, timestamp: float = None):
        """设置冷却时间戳"""
        ts = timestamp or time.time()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cooldown (key, timestamp) VALUES (?, ?)",
                (key, ts)
            )

    def load_all(self) -> dict[str, float]:
        """加载所有冷却状态"""
        with self._conn() as conn:
            rows = conn.execute("SELECT key, timestamp FROM cooldown").fetchall()
            return {k: v for k, v in rows}

    def cleanup(self, max_age: int = 86400):
        """清理过期记录（默认24小时）"""
        cutoff = time.time() - max_age
        with self._conn() as conn:
            conn.execute("DELETE FROM cooldown WHERE timestamp < ?", (cutoff,))


# 单例
_storage: CooldownStorage | PgCooldownStorage | None = None


def get_cooldown_storage() -> CooldownStorage | PgCooldownStorage:
    global _storage
    if _storage is None:
        backend = _resolve_backend()
        if backend == "pg":
            try:
                _storage = PgCooldownStorage()
            except Exception as e:
                logger.warning("PG 冷却存储初始化失败，将回退到 SQLite: %s", e)
                _storage = CooldownStorage()
        else:
            _storage = CooldownStorage()
    return _storage
