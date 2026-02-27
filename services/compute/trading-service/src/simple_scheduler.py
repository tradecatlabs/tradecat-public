#!/usr/bin/env python3
"""
简单可靠的定时计算服务

启动时：
1. 识别高优先级币种（K线+期货 11个维度）
2. 只计算高优先级币种

运行时：
1. 每10秒检查新数据
2. 每小时重新评估优先级
"""
import os
import sqlite3
import sys
import time
import atexit
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

from psycopg.rows import dict_row

TRADING_SERVICE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 将服务根目录加入路径，保证以包方式导入 src.*
if TRADING_SERVICE_DIR not in sys.path:
    sys.path.insert(0, TRADING_SERVICE_DIR)
REPO_ROOT = str(Path(__file__).resolve().parents[4])
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

def _resolve_sqlite_path(env_path: str | None, default_path: str) -> str:
    """支持相对路径，统一基于项目根目录解析为绝对路径。"""
    if env_path and env_path.strip():
        path = env_path.strip()
        if not os.path.isabs(path):
            path = os.path.abspath(os.path.join(REPO_ROOT, path))
        return path
    return default_path

SQLITE_PATH = _resolve_sqlite_path(
    os.environ.get("INDICATOR_SQLITE_PATH"),
    os.path.join(REPO_ROOT, "assets/database/services/telegram-service/market_data.db"),
)

# 币种管理配置
HIGH_PRIORITY_TOP_N = int(os.environ.get("HIGH_PRIORITY_TOP_N", "50"))

# 周期配置
INTERVALS = [i.strip() for i in os.environ.get("INTERVALS", "1m,5m,15m,1h,4h,1d,1w").split(",") if i.strip()]

# 指标开关配置
INDICATORS_ENABLED = [i.strip().lower() for i in os.environ.get("INDICATORS_ENABLED", "").split(",") if i.strip()]
INDICATORS_DISABLED = [i.strip().lower() for i in os.environ.get("INDICATORS_DISABLED", "").split(",") if i.strip()]

last_computed = {i: None for i in INTERVALS}
last_priority_update = None
high_priority_symbols = []

# SQLite 连接复用（避免频繁开关连接）
_sqlite_conn = None

def _get_sqlite_conn():
    """获取 SQLite 连接（单例复用）"""
    global _sqlite_conn
    if _sqlite_conn is None:
        _sqlite_conn = sqlite3.connect(SQLITE_PATH, check_same_thread=False)
        _sqlite_conn.execute("PRAGMA journal_mode=WAL")
    return _sqlite_conn

def _close_sqlite_conn():
    """关闭 SQLite 连接"""
    global _sqlite_conn
    if _sqlite_conn:
        _sqlite_conn.close()
        _sqlite_conn = None

atexit.register(_close_sqlite_conn)


from src.db.reader import shared_pg_conn


def log(msg: str):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


# 使用共享币种模块（仓库内 assets/common/symbols.py）
from assets.common.symbols import get_configured_symbols


# ============ 高优先级币种识别（复用 async_full_engine 完整逻辑）============

def _query_kline_priority(top_n: int = 30) -> set:
    """K线维度优先级 - 交易量+波动率+涨跌幅"""
    symbols = set()
    try:
        with shared_pg_conn() as conn:
            sql = """
                WITH base AS (
                    SELECT symbol, 
                           SUM(quote_volume) as total_qv,
                           AVG((high-low)/NULLIF(close,0)) as volatility
                    FROM market_data.candles_5m
                    WHERE bucket_ts > NOW() - INTERVAL '24 hours'
                    GROUP BY symbol
                ),
                volume_rank AS (
                    SELECT symbol FROM base ORDER BY total_qv DESC LIMIT %s
                ),
                volatility_rank AS (
                    SELECT symbol FROM base ORDER BY volatility DESC LIMIT %s
                ),
                change_rank AS (
                    WITH latest AS (
                        SELECT DISTINCT ON (symbol) symbol, close
                        FROM market_data.candles_5m
                        WHERE bucket_ts > NOW() - INTERVAL '1 hour'
                        ORDER BY symbol, bucket_ts DESC
                    ),
                    prev AS (
                        SELECT DISTINCT ON (symbol) symbol, close as prev_close
                        FROM market_data.candles_5m
                        WHERE bucket_ts BETWEEN NOW() - INTERVAL '25 hours' AND NOW() - INTERVAL '23 hours'
                        ORDER BY symbol, bucket_ts DESC
                    )
                    SELECT l.symbol
                    FROM latest l JOIN prev p ON l.symbol = p.symbol
                    ORDER BY ABS((l.close - p.prev_close) / NULLIF(p.prev_close, 0)) DESC
                    LIMIT %s
                )
                SELECT DISTINCT symbol FROM (
                    SELECT symbol FROM volume_rank
                    UNION SELECT symbol FROM volatility_rank
                    UNION SELECT symbol FROM change_rank
                ) combined
            """
            cur = conn.execute(sql, (top_n, top_n, top_n))
            symbols.update(r[0] for r in cur.fetchall())
    except Exception as e:
        log(f"K线优先级查询失败: {e}")
    return symbols


def _query_futures_priority(top_n: int = 30) -> set:
    """期货维度优先级 - 持仓价值+主动买卖比+多空比"""
    result = set()
    try:
        with shared_pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT ON (symbol) 
                        symbol, sum_open_interest_value as oi_val,
                        sum_taker_long_short_vol_ratio as taker_ratio,
                        count_long_short_ratio as ls_ratio
                    FROM market_data.binance_futures_metrics_5m 
                    WHERE create_time > NOW() - INTERVAL '7 days'
                    ORDER BY symbol, create_time DESC
                """)
                rows = cur.fetchall()

                oi_value_rank = []
                taker_extreme = set()
                ls_extreme = set()

                for row in rows:
                    sym, oi_val, taker, ls = row

                    # 持仓价值 Top N
                    if oi_val:
                        oi_value_rank.append((sym, float(oi_val)))

                    # 主动买卖比极端 (<0.2 或 >5.0)
                    if taker:
                        t = float(taker)
                        if t < 0.2 or t > 5.0:
                            taker_extreme.add(sym)

                    # 多空比极端 (<0.5 或 >4.0)
                    if ls:
                        ls_val = float(ls)
                        if ls_val < 0.5 or ls_val > 4.0:
                            ls_extreme.add(sym)

                top_oi_value = {s for s, _ in sorted(oi_value_rank, key=lambda x: x[1], reverse=True)[:top_n]}
                result = top_oi_value | taker_extreme | ls_extreme
    except Exception as e:
        log(f"期货优先级查询失败: {e}")
    return result


def get_high_priority_symbols_fast(top_n: int = 30) -> set:
    """快速获取高优先级币种 - K线+期货并行查询"""
    result = set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_query_kline_priority, top_n),
            executor.submit(_query_futures_priority, top_n),
        ]
        for f in as_completed(futures):
            try:
                result.update(f.result())
            except Exception as e:
                log(f"优先级查询失败: {e}")

    return result


def _load_all_symbols_from_db() -> list:
    """从数据库读取全量 USDT 永续符号（轻量查询）。"""
    try:
        with shared_pg_conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("""
                    SELECT DISTINCT symbol
                    FROM market_data.ingest_offsets
                    WHERE symbol LIKE '%USDT'
                """)
                rows = cur.fetchall()
        symbols = sorted({row["symbol"] for row in rows if row.get("symbol")})
        return symbols
    except Exception as e:
        log(f"全量币种查询失败: {e}")
        return []


# ============ 数据检查 ============

def get_source_latest(interval: str) -> datetime:
    """查询 TimescaleDB 该周期最新数据时间"""
    table = f"candles_{interval}"
    try:
        with shared_pg_conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(f"SELECT MAX(bucket_ts) as latest FROM market_data.{table}")
                row = cur.fetchone()
                return row["latest"] if row else None
    except Exception as e:
        log(f"查询 {table} 最新时间失败: {e}")
        return None


def get_indicator_latest(interval: str) -> datetime:
    """查询 SQLite 指标该周期最新数据时间"""
    try:
        conn = _get_sqlite_conn()
        row = conn.execute("""
            SELECT MAX(数据时间) as latest FROM [MACD柱状扫描器.py] WHERE 周期 = ?
        """, (interval,)).fetchone()
        if row and row[0]:
            ts_str = row[0].replace("+00:00", "").replace("T", " ")
            return datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
        return None
    except Exception as e:
        log(f"查询 SQLite 指标 {interval} 最新时间失败: {e}")
        return None


def check_need_calc() -> list:
    """对比数据源和指标库，返回需要计算的周期"""
    need_calc = []

    for interval in INTERVALS:
        try:
            source_ts = get_source_latest(interval)
            indicator_ts = get_indicator_latest(interval)

            if source_ts is None:
                continue

            if indicator_ts is None or source_ts > indicator_ts:
                need_calc.append(interval)

            last_computed[interval] = source_ts
        except Exception as e:
            log(f"检查 {interval} 需要计算失败: {e}")
            need_calc.append(interval)

    return need_calc


def run_calculation(intervals: list, symbols: list):
    """执行指标计算"""
    if not intervals or not symbols:
        return

    import subprocess

    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    env["TEST_SYMBOLS"] = ",".join(symbols)

    interval_str = ",".join(intervals)
    log(f"计算 {interval_str} ({len(symbols)}币种)")

    result = subprocess.run(
        ["python3", "-m", "src", "--intervals", interval_str],
        cwd=TRADING_SERVICE_DIR,
        env=env,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        for line in result.stdout.split("\n"):
            if "计算完成" in line or "rows" in line.lower():
                log(line.strip())
    else:
        log(f"错误: {result.stderr[:200]}")


def update_priority():
    """更新币种列表"""
    global high_priority_symbols, last_priority_update

    t0 = time.time()
    configured = get_configured_symbols()
    groups_str = os.environ.get("SYMBOLS_GROUPS", "auto")
    selected_groups = {g.strip().lower() for g in groups_str.split(",") if g.strip()}

    if configured:
        # 使用配置的分组
        symbols = configured
        log(f"使用配置分组: {len(symbols)} 币种")
    elif "all" in selected_groups:
        symbols = _load_all_symbols_from_db()
        # 应用额外添加和排除
        extra = [s.strip().upper() for s in os.environ.get("SYMBOLS_EXTRA", "").split(",") if s.strip()]
        exclude = {s.strip().upper() for s in os.environ.get("SYMBOLS_EXCLUDE", "").split(",") if s.strip()}
        symbols = sorted((set(symbols) | set(extra)) - exclude) if symbols else []
        if symbols:
            log(f"使用数据库全量币种: {len(symbols)} 币种")
        else:
            log("全量币种为空，回退自动高优先级")
            symbols = list(get_high_priority_symbols_fast(top_n=HIGH_PRIORITY_TOP_N))
            symbols = sorted((set(symbols) | set(extra)) - exclude)
            log(f"自动高优先级: {len(symbols)} 币种")
    else:
        # auto模式：动态高优先级
        symbols = list(get_high_priority_symbols_fast(top_n=HIGH_PRIORITY_TOP_N))
        # 应用额外添加和排除
        extra = [s.strip().upper() for s in os.environ.get("SYMBOLS_EXTRA", "").split(",") if s.strip()]
        exclude = {s.strip().upper() for s in os.environ.get("SYMBOLS_EXCLUDE", "").split(",") if s.strip()}
        symbols = sorted((set(symbols) | set(extra)) - exclude)
        log(f"自动高优先级: {len(symbols)} 币种")

    high_priority_symbols = symbols
    last_priority_update = time.time()
    log(f"币种更新完成, 耗时 {time.time()-t0:.1f}s")

    if high_priority_symbols:
        log(f"前10: {high_priority_symbols[:10]}")


def main():
    global last_priority_update

    log("=" * 50)
    log("简单定时计算服务启动")
    log("=" * 50)

    # 1. 识别高优先级币种
    update_priority()

    if not high_priority_symbols:
        log("无高优先级币种，退出")
        return

    # 2. 启动时强制计算全部周期（确保表里有全周期数据）
    log(f"首次启动，计算全部周期: {INTERVALS}")
    run_calculation(INTERVALS, high_priority_symbols)

    log("-" * 50)
    log("进入轮询检查 (每10秒检查新数据, 每小时更新优先级)...")

    while True:
        # 每小时更新优先级
        if time.time() - last_priority_update > 3600:
            update_priority()

        # 检查新数据
        to_calc = []
        for interval in INTERVALS:
            try:
                latest = get_source_latest(interval)
                if latest and (last_computed[interval] is None or latest > last_computed[interval]):
                    to_calc.append(interval)
                    last_computed[interval] = latest
            except Exception as e:
                log(f"检查 {interval} 失败: {e}")

        if to_calc:
            run_calculation(to_calc, high_priority_symbols)

        time.sleep(10)


if __name__ == "__main__":
    main()
