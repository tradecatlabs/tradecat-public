"""
存储模块：结果落盘与后处理
"""
from typing import Dict

import pandas as pd

from ..db.reader import shared_pg_conn


# ==================== 写入结果 ====================

def write_results(all_results: Dict[str, list]):
    """写入指标结果（PG: tg_cards schema）"""
    from ..db.reader import pg_writer

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

    if data:
        pg_writer.write_batch(data)

    # 全局计算：市场占比
    update_market_share()

    # 清理期货表的1m数据（期货无1m粒度）
    cleanup_futures_1m()


def write_indicator_result(indicator_name: str, result: pd.DataFrame, interval: str):
    """单指标结果写入"""
    from ..db.reader import pg_writer
    pg_writer.write(indicator_name, result)


# ==================== 后处理 ====================

def update_market_share():
    """更新期货情绪聚合表的市场占比字段（基于全市场持仓总额）"""
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
                        WHERE create_time > (NOW() AT TIME ZONE 'UTC') - INTERVAL '1 hour'
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

        # 2. 更新指标库（PG: tg_cards）
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


def cleanup_futures_1m():
    """清理期货表的1m数据（期货无1m粒度）"""
    try:
        with shared_pg_conn() as pg_conn:
            with pg_conn.cursor() as cur:
                cur.execute('DELETE FROM tg_cards."期货情绪聚合表.py" WHERE "周期"=%s', ("1m",))
                cur.execute('DELETE FROM tg_cards."期货情绪元数据.py" WHERE "周期"=%s', ("1m",))
            pg_conn.commit()
    except Exception:
        pass
