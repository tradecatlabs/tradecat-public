"""
信号历史记录管理
存储和查询信号触发历史
"""

import json
import logging
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_PG_SCHEMA = "signal_state"


# 最大保留天数
_MAX_RETENTION_DAYS = int(os.environ.get("SIGNAL_HISTORY_RETENTION_DAYS", "30"))


class PgSignalHistory:
    """PG 版本信号历史（signal_state.signal_history）"""

    def __init__(self, database_url: str | None = None, *, schema: str = _PG_SCHEMA):
        try:
            from ..config import get_database_url
        except ImportError:
            from config import get_database_url

        self.database_url = (database_url or get_database_url() or "").strip()
        if not self.database_url:
            raise RuntimeError("缺少 DATABASE_URL，无法使用 PG 历史存储")
        self.schema = (schema or _PG_SCHEMA).strip() or _PG_SCHEMA
        self._lock = threading.Lock()
        self._ensure_table()

        # 启动时清理旧记录（与历史行为保持一致）
        self.cleanup()

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
                cur.execute("SELECT to_regclass(%s)", (f"{self.schema}.signal_history",))
                if cur.fetchone()[0] is None:
                    raise RuntimeError(
                        f"缺少 PG 表 {self.schema}.signal_history；请先执行 assets/database/db/schema/022_signal_state.sql"
                    )

    @staticmethod
    def _parse_ts(val) -> datetime:
        if isinstance(val, datetime):
            if val.tzinfo is None:
                return val.replace(tzinfo=timezone.utc)
            return val
        if isinstance(val, str) and val:
            raw = val.strip()
            # 兼容 Z 后缀
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            try:
                dt = datetime.fromisoformat(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                pass
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_signal(signal, source: str) -> dict:
        ts = getattr(signal, "timestamp", None)
        timestamp = PgSignalHistory._parse_ts(ts)

        signal_type = getattr(signal, "signal_type", None) or getattr(signal, "rule_name", "")
        direction = getattr(signal, "direction", "ALERT")
        strength = getattr(signal, "strength", 0)
        timeframe = getattr(signal, "timeframe", "1h")
        price = getattr(signal, "price", 0)

        message = getattr(signal, "message", None)
        message_key = getattr(signal, "message_key", None)
        if not message:
            message = message_key or ""

        extra = {}
        extra_obj = getattr(signal, "extra", None)
        if isinstance(extra_obj, dict):
            extra.update(extra_obj)
        elif extra_obj is not None:
            extra["raw"] = str(extra_obj)
        msg_params = getattr(signal, "message_params", None)
        if isinstance(msg_params, dict) and msg_params:
            extra["message_params"] = msg_params
        if message_key:
            extra.setdefault("message_key", message_key)

        return {
            "ts": timestamp,
            "symbol": getattr(signal, "symbol", "") or "",
            "signal_type": signal_type,
            "direction": direction,
            "strength": int(strength or 0),
            "message": str(message) if message is not None else "",
            "timeframe": timeframe,
            "price": float(price or 0) if price is not None else None,
            "source": source or "pg",
            "extra": extra,
        }

    def save(self, signal, source: str = "pg", max_retries: int = 2) -> int:
        for attempt in range(max_retries + 1):
            try:
                data = self._normalize_signal(signal, source)
                extra_json = json.dumps(data["extra"], ensure_ascii=False)
                with self._lock:
                    with self._conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                f"""
                                INSERT INTO {self.schema}.signal_history
                                  (ts, symbol, signal_type, direction, strength, message, timeframe, price, source, extra)
                                VALUES
                                  (%s, %s, %s, %s, %s, %s, %s, %s, %s, (%s)::jsonb)
                                RETURNING id
                                """,
                                (
                                    data["ts"],
                                    data["symbol"],
                                    data["signal_type"],
                                    data["direction"],
                                    data["strength"],
                                    data["message"],
                                    data["timeframe"],
                                    data["price"],
                                    data["source"],
                                    extra_json,
                                ),
                            )
                            row = cur.fetchone()
                            return int(row[0]) if row and row[0] is not None else -1
            except Exception as e:
                if attempt < max_retries:
                    logger.warning("保存信号历史失败(重试%d): %s", attempt + 1, e)
                    import time

                    time.sleep(0.1 * (attempt + 1))
                    continue
                logger.error("保存信号历史失败: %s", e)
                return -1
        return -1

    def get_recent(self, limit: int = 20, symbol: str = None, direction: str = None) -> list[dict]:
        try:
            where = []
            params: list[object] = []
            if symbol:
                where.append("symbol=%s")
                params.append(symbol)
            if direction:
                where.append("direction=%s")
                params.append(direction)
            where_sql = ("WHERE " + " AND ".join(where)) if where else ""
            sql = (
                f"SELECT ts, symbol, signal_type, direction, strength, message, timeframe, price, source, extra "
                f"FROM {self.schema}.signal_history {where_sql} ORDER BY ts DESC LIMIT %s"
            )
            params.append(int(limit))
            with self._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    rows = cur.fetchall() or []
            out: list[dict] = []
            for row in rows:
                ts = row[0]
                out.append(
                    {
                        "timestamp": (ts.isoformat() if isinstance(ts, datetime) else str(ts or "")),
                        "symbol": row[1],
                        "signal_type": row[2],
                        "direction": row[3],
                        "strength": row[4],
                        "message": row[5],
                        "timeframe": row[6],
                        "price": row[7],
                        "source": row[8],
                        "extra": row[9],
                    }
                )
            return out
        except Exception as e:
            logger.error("获取信号历史失败: %s", e)
            return []

    def get_by_symbol(self, symbol: str, days: int = 7, limit: int = 50) -> list[dict]:
        try:
            since = datetime.now(timezone.utc) - timedelta(days=int(days))
            with self._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT ts, symbol, signal_type, direction, strength, message, timeframe, price, source, extra
                        FROM {self.schema}.signal_history
                        WHERE symbol=%s AND ts > %s
                        ORDER BY ts DESC
                        LIMIT %s
                        """,
                        (symbol, since, int(limit)),
                    )
                    rows = cur.fetchall() or []
            out: list[dict] = []
            for row in rows:
                ts = row[0]
                out.append(
                    {
                        "timestamp": (ts.isoformat() if isinstance(ts, datetime) else str(ts or "")),
                        "symbol": row[1],
                        "signal_type": row[2],
                        "direction": row[3],
                        "strength": row[4],
                        "message": row[5],
                        "timeframe": row[6],
                        "price": row[7],
                        "source": row[8],
                        "extra": row[9],
                    }
                )
            return out
        except Exception as e:
            logger.error("获取币种信号历史失败: %s", e)
            return []

    def get_stats(self, days: int = 7) -> dict:
        days_i = int(days)
        since = datetime.now(timezone.utc) - timedelta(days=days_i)
        try:
            with self._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT COUNT(*) FROM {self.schema}.signal_history WHERE ts > %s", (since,))
                    total = int((cur.fetchone() or [0])[0] or 0)

                    cur.execute(
                        f"""
                        SELECT direction, COUNT(*) as cnt
                        FROM {self.schema}.signal_history
                        WHERE ts > %s
                        GROUP BY direction
                        """,
                        (since,),
                    )
                    by_direction = {str(r[0]): int(r[1]) for r in (cur.fetchall() or []) if r and r[0] is not None}

                    cur.execute(
                        f"""
                        SELECT symbol, COUNT(*) as cnt
                        FROM {self.schema}.signal_history
                        WHERE ts > %s
                        GROUP BY symbol
                        ORDER BY cnt DESC
                        LIMIT 10
                        """,
                        (since,),
                    )
                    by_symbol = [{"symbol": str(r[0]), "count": int(r[1])} for r in (cur.fetchall() or []) if r and r[0]]

                    cur.execute(
                        f"""
                        SELECT source, COUNT(*) as cnt
                        FROM {self.schema}.signal_history
                        WHERE ts > %s
                        GROUP BY source
                        """,
                        (since,),
                    )
                    by_source = {str(r[0]): int(r[1]) for r in (cur.fetchall() or []) if r and r[0] is not None}

            return {
                "total": total,
                "days": days_i,
                "by_direction": by_direction,
                "by_symbol": by_symbol,
                "by_source": by_source,
            }
        except Exception as e:
            logger.error("获取信号统计失败: %s", e)
            return {"total": 0, "days": days_i, "by_direction": {}, "by_symbol": [], "by_source": {}}

    def cleanup(self, days: int = None) -> int:
        if days is None:
            days = _MAX_RETENTION_DAYS
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))
        try:
            with self._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"DELETE FROM {self.schema}.signal_history WHERE ts < %s", (cutoff,))
                    deleted = int(cur.rowcount or 0)
            if deleted > 0:
                logger.info("清理了 %s 条旧信号记录", deleted)
            return deleted
        except Exception as e:
            logger.error("清理信号历史失败: %s", e)
            return 0

    def format_history_text(self, records: list[dict], title: str = "信号历史") -> str:
        if not records:
            return f"📜 {title}\n\n暂无记录"

        lines = [f"📜 {title} ({len(records)}条)", ""]
        dir_icons = {"BUY": "🟢", "SELL": "🔴", "ALERT": "⚠️"}

        for r in records[:15]:
            ts = r.get("timestamp", "")[:16].replace("T", " ")
            symbol = r.get("symbol", "").replace("USDT", "")
            direction = r.get("direction", "")
            signal_type = r.get("signal_type", "")
            strength = r.get("strength", 0)
            icon = dir_icons.get(direction, "📊")

            lines.append(f"{icon} {symbol} | {signal_type}")
            lines.append(f"   {ts} | 强度:{strength}")

        if len(records) > 15:
            lines.append(f"\n... 还有 {len(records) - 15} 条")

        return "\n".join(lines)


# 单例
_history: PgSignalHistory | None = None
_history_lock = threading.Lock()


def get_history() -> PgSignalHistory:
    """获取历史记录管理器单例"""
    global _history
    if _history is None:
        with _history_lock:
            if _history is None:
                _history = PgSignalHistory()
    return _history
