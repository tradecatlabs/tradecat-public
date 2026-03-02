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
import sys
import time
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


from src.db.reader import shared_pg_conn


def log(msg: str):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)

_TIME_DEBUG = os.environ.get("SCHEDULER_TIME_DEBUG", "").strip().lower() in {"1", "true", "yes", "y"}


def _normalize_utc(ts: datetime | None) -> datetime | None:
    """把 datetime 统一归一为 UTC tz-aware。"""
    if ts is None:
        return None
    if getattr(ts, "tzinfo", None) is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _parse_tg_ts(v: object) -> datetime | None:
    """
    解析 tg_cards.* 的 "数据时间"（text）为 UTC tz-aware datetime。

    兼容：
    - 2026-03-01T19:45:00+00:00
    - 2026-03-01 19:45:00+00:00
    - 2026-03-01T19:45:00Z
    - 2026-03-01 19:45:00   （无时区视为 UTC）
    """
    if v is None:
        return None
    if isinstance(v, datetime):
        return _normalize_utc(v)

    s = str(v).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    s = s.replace("T", " ")
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    return _normalize_utc(dt)


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
                    WHERE create_time > (NOW() AT TIME ZONE 'UTC') - INTERVAL '7 days'
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
                return _normalize_utc(row["latest"] if row else None)
    except Exception as e:
        log(f"查询 {table} 最新时间失败: {e}")
        return None


def get_futures_source_latest(interval: str) -> datetime:
    """查询期货情绪源数据最新时间（5m=原始表，其他=*_last 物化表）"""
    if interval == "1m":
        return None

    try:
        with shared_pg_conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                if interval == "5m":
                    cur.execute("SELECT MAX(create_time) AS latest FROM market_data.binance_futures_metrics_5m")
                    row = cur.fetchone()
                    latest = row["latest"] if row else None
                else:
                    table = f"binance_futures_metrics_{interval}_last"
                    cur.execute(f"SELECT MAX(bucket) AS latest FROM market_data.{table}")
                    row = cur.fetchone()
                    latest = row["latest"] if row else None

        return _normalize_utc(latest)
    except Exception as e:
        log(f"查询期货源最新时间失败({interval}): {e}")
        return None


def get_indicator_latest(interval: str) -> datetime:
    """查询 PG 指标该周期最新数据时间（tg_cards）"""
    try:
        with shared_pg_conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    'SELECT MAX("数据时间") AS latest FROM tg_cards."MACD柱状扫描器.py" WHERE "周期"=%s',
                    (interval,),
                )
                row = cur.fetchone()
                if row and row.get("latest"):
                    return _parse_tg_ts(row["latest"])
        return None
    except Exception as e:
        log(f"查询 tg_cards 指标 {interval} 最新时间失败: {e}")
        return None


def get_futures_indicator_latest(interval: str) -> datetime:
    """查询期货相关指标表该周期最新时间（以 max(meta,agg) 作为有效进度）。"""
    if interval == "1m":
        return None
    try:
        with shared_pg_conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    'SELECT MAX("数据时间") AS latest FROM tg_cards."期货情绪元数据.py" WHERE "周期"=%s AND "持仓金额" IS NOT NULL',
                    (interval,),
                )
                meta = cur.fetchone()
                cur.execute(
                    'SELECT MAX("数据时间") AS latest FROM tg_cards."期货情绪聚合表.py" WHERE "周期"=%s AND "持仓金额" IS NOT NULL',
                    (interval,),
                )
                agg = cur.fetchone()

        meta_ts = _parse_tg_ts(meta.get("latest") if meta else None)
        agg_ts = _parse_tg_ts(agg.get("latest") if agg else None)
        if meta_ts and agg_ts:
            return max(meta_ts, agg_ts)
        return meta_ts or agg_ts
    except Exception as e:
        log(f"查询 tg_cards 期货指标 {interval} 最新时间失败: {e}")
        return None


def get_effective_source_latest(interval: str) -> datetime:
    """综合源最新时间：max(candles, futures)。"""
    k_ts = get_source_latest(interval)
    f_ts = get_futures_source_latest(interval)
    if k_ts and f_ts:
        return max(k_ts, f_ts)
    return k_ts or f_ts


def get_effective_indicator_latest(interval: str) -> datetime:
    """综合指标最新时间：max(kline指标进度, 期货指标进度)。"""
    k_ts = get_indicator_latest(interval)
    f_ts = get_futures_indicator_latest(interval)
    if k_ts and f_ts:
        return max(k_ts, f_ts)
    return k_ts or f_ts


def check_need_calc() -> list:
    """对比数据源和指标库，返回需要计算的周期"""
    need_calc = []

    for interval in INTERVALS:
        try:
            source_ts = get_effective_source_latest(interval)
            indicator_ts = get_effective_indicator_latest(interval)

            if source_ts is None:
                continue

            if _TIME_DEBUG:
                delta = None
                if indicator_ts is not None:
                    try:
                        delta = (source_ts - indicator_ts).total_seconds()
                    except Exception:
                        delta = None
                log(f"[TIME_DEBUG] {interval} source={source_ts} indicator={indicator_ts} delta_s={delta}")

            if indicator_ts is None or source_ts > indicator_ts:
                need_calc.append(interval)
        except Exception as e:
            log(f"检查 {interval} 需要计算失败: {e}")
            need_calc.append(interval)

    return need_calc


def run_calculation(intervals: list, symbols: list):
    """执行指标计算"""
    if not intervals or not symbols:
        return False

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
        return True
    else:
        stderr = (result.stderr or "").strip()
        if not stderr:
            log("错误: 子进程非0退出，但 stderr 为空")
            return False

        # 只打印尾部，避免日志爆炸；但要保留 “哪张表写入失败” 等关键信息
        lines = stderr.splitlines()
        tail = lines[-60:] if len(lines) > 60 else lines
        for line in tail:
            log(f"错误: {line}")
        return False


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
    ok = run_calculation(INTERVALS, high_priority_symbols)
    if ok:
        # 只有在计算成功后才推进 last_computed，避免一次失败后“永不重试直到新数据出现”
        for interval in INTERVALS:
            last_computed[interval] = get_effective_source_latest(interval)

    log("-" * 50)
    log("进入轮询检查 (每10秒检查新数据, 每小时更新优先级)...")

    while True:
        # 每小时更新优先级
        if time.time() - last_priority_update > 3600:
            update_priority()

        # 计算触发条件：以“指标进度 vs 源进度”为准（不是以 last_computed 为准）
        to_calc = check_need_calc()
        if to_calc:
            ok = run_calculation(to_calc, high_priority_symbols)
            if ok:
                for interval in to_calc:
                    last_computed[interval] = get_effective_source_latest(interval)

        time.sleep(10)


if __name__ == "__main__":
    main()
