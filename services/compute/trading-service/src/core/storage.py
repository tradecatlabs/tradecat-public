"""
存储模块：结果落盘与后处理
"""
import os
from typing import Dict

import pandas as pd

from ..config import config
from ..db.reader import shared_pg_conn


# ==================== 写入结果 ====================

def write_results(all_results: Dict[str, list]):
    """写入指标结果（SQLite/PG 可切换）"""
    from ..db.reader import pg_writer, writer as sqlite_writer

    data: Dict[str, pd.DataFrame] = {}
    for indicator_name, records_list in all_results.items():
        if not records_list:
            continue
        all_records = []
        for records in records_list:
            if isinstance(records, list):
                all_records.extend(records)
            elif isinstance(records, dict):
                all_records.append(records)

        if all_records:
            data[indicator_name] = pd.DataFrame(all_records)

    mode = (config.indicator_store_mode or "sqlite").strip().lower()
    # 兜底：允许用 env 覆盖（便于运维热切换）
    env_mode = (os.environ.get("INDICATOR_STORE_MODE") or "").strip().lower()
    if env_mode:
        mode = env_mode

    if data:
        if mode in {"sqlite", "dual"}:
            sqlite_writer.write_batch(data)
        if mode in {"pg", "dual"}:
            pg_writer.write_batch(data)

    # 全局计算：市场占比
    update_market_share(mode=mode)

    # 清理期货表的1m数据（期货无1m粒度）
    cleanup_futures_1m(mode=mode)


def write_indicator_result(indicator_name: str, result: pd.DataFrame, interval: str):
    """单指标结果写入"""
    from ..db.reader import pg_writer, writer as sqlite_writer

    mode = (config.indicator_store_mode or "sqlite").strip().lower()
    env_mode = (os.environ.get("INDICATOR_STORE_MODE") or "").strip().lower()
    if env_mode:
        mode = env_mode

    if mode in {"sqlite", "dual"}:
        sqlite_writer.write(indicator_name, result, interval)
    if mode in {"pg", "dual"}:
        pg_writer.write(indicator_name, result)


# ==================== 后处理 ====================

def update_market_share(*, mode: str = "sqlite"):
    """更新期货情绪聚合表的市场占比字段（基于全市场持仓总额）"""
    import sqlite3
    from ..db.reader import inc_sqlite_commit

    try:
        # 1. 从 PostgreSQL 获取全市场各周期持仓总额（只取最新时间点）
        totals = {}
        with shared_pg_conn() as conn:
            with conn.cursor() as cur:
                # 5m 从原始表（取每个币种最新一条）
                cur.execute("""
                    SELECT SUM(oiv) FROM (
                        SELECT DISTINCT ON (symbol) sum_open_interest_value as oiv
                        FROM market_data.binance_futures_metrics_5m
                        WHERE create_time > NOW() - INTERVAL '1 hour'
                        ORDER BY symbol, create_time DESC
                    ) t
                """)
                row = cur.fetchone()
                if row and row[0]:
                    totals["5m"] = float(row[0])

                # 其他周期从物化视图（取最新 bucket）
                for interval in ["15m", "1h", "4h", "1d", "1w"]:
                    cur.execute(f"""
                        SELECT SUM(sum_open_interest_value)
                        FROM market_data.binance_futures_metrics_{interval}_last
                        WHERE bucket = (SELECT MAX(bucket) FROM market_data.binance_futures_metrics_{interval}_last)
                    """)
                    row = cur.fetchone()
                    if row and row[0]:
                        totals[interval] = float(row[0])

        if not totals:
            return

        # 2. 更新指标库（SQLite/PG 可选）
        if mode in {"sqlite", "dual"}:
            sqlite_conn = sqlite3.connect(str(config.sqlite_path))
            for interval, total in totals.items():
                if total > 0:
                    sqlite_conn.execute(
                        """
                        UPDATE '期货情绪聚合表.py'
                        SET 市场占比 = ROUND(CAST(持仓金额 AS REAL) * 100.0 / ?, 4)
                        WHERE 周期 = ? AND 持仓金额 IS NOT NULL AND 持仓金额 != ''
                        """,
                        (total, interval),
                    )
            sqlite_conn.commit()
            inc_sqlite_commit()
            sqlite_conn.close()

        if mode in {"pg", "dual"}:
            with shared_pg_conn() as conn:
                with conn.cursor() as cur:
                    for interval, total in totals.items():
                        if total > 0:
                            cur.execute(
                                """
                                UPDATE tg_cards."期货情绪聚合表.py"
                                SET "市场占比" = ROUND(("持仓金额" * 100.0 / %s)::numeric, 4)::double precision
                                WHERE "周期" = %s AND "持仓金额" IS NOT NULL
                                """,
                                (total, interval),
                            )
                conn.commit()
    except Exception:
        pass  # 静默失败


def cleanup_futures_1m(*, mode: str = "sqlite"):
    """清理期货表的1m数据（期货无1m粒度）"""
    import sqlite3
    from ..config import config
    from ..db.reader import inc_sqlite_commit
    try:
        if mode in {"sqlite", "dual"}:
            conn = sqlite3.connect(str(config.sqlite_path))
            conn.execute("DELETE FROM '期货情绪聚合表.py' WHERE 周期='1m'")
            conn.execute("DELETE FROM '期货情绪元数据.py' WHERE 周期='1m'")
            conn.commit()
            inc_sqlite_commit()
            conn.close()

        if mode in {"pg", "dual"}:
            with shared_pg_conn() as pg_conn:
                with pg_conn.cursor() as cur:
                    cur.execute('DELETE FROM tg_cards."期货情绪聚合表.py" WHERE "周期"=%s', ("1m",))
                    cur.execute('DELETE FROM tg_cards."期货情绪元数据.py" WHERE "周期"=%s', ("1m",))
                pg_conn.commit()
    except Exception:
        pass
