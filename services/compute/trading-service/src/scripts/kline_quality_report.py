"""
K线质量报告（全历史）

用途：
- 校验“全历史”是否齐全（以 candles_1m 为唯一真相源）
- 输出：最近30天 1m 日条数异常、15m bucket 缺失数与缺失时间戳样例

说明：
- 不修改数据库，只读分析
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import psycopg


@dataclass(frozen=True)
class Report:
    exchange: str
    symbol: str
    min_ts: str
    max_ts: str
    staleness_minutes: float
    missing_15m: int
    missing_15m_samples: list[str]
    bad_1m_days_30d: int
    bad_1m_days_30d_samples: list[str]


def _read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _repo_root() -> Path:
    # services/compute/trading-service/src/scripts/*.py -> tradecat/
    return Path(__file__).resolve().parents[5]


def _load_db_url() -> str:
    env_file = _repo_root() / "assets" / "config" / ".env"
    if not env_file.exists():
        env_file = _repo_root() / "config" / ".env"
    env = _read_env(env_file)
    url = env.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not found in assets/config/.env")
    return url


def _load_symbols() -> list[str]:
    env_file = _repo_root() / "assets" / "config" / ".env"
    if not env_file.exists():
        env_file = _repo_root() / "config" / ".env"
    env = _read_env(env_file)
    groups = [g.strip() for g in env.get("SYMBOLS_GROUPS", "").split(",") if g.strip()]
    if not groups:
        raise RuntimeError("SYMBOLS_GROUPS missing/empty")
    syms: list[str] = []
    for g in groups:
        raw = env.get(f"SYMBOLS_GROUP_{g}", "")
        if raw:
            syms.extend([s.strip().upper() for s in raw.split(",") if s.strip()])
    if not syms:
        raise RuntimeError("no symbols from SYMBOLS_GROUPS")
    return sorted(set(syms))


def _fetch_15m_bucket_ts(conn: psycopg.Connection, *, exchange: str, symbol: str) -> pd.DatetimeIndex:
    rows = conn.execute(
        """
        SELECT time_bucket('15 minutes', bucket_ts) AS bucket_ts
        FROM market_data.candles_1m
        WHERE exchange=%(exchange)s AND symbol=%(symbol)s
        GROUP BY 1
        ORDER BY 1;
        """,
        {"exchange": exchange, "symbol": symbol},
    ).fetchall()
    if not rows:
        return pd.DatetimeIndex([])
    ts = pd.to_datetime([r[0] for r in rows], utc=True)
    return pd.DatetimeIndex(ts)


def _missing_15m(ts: pd.DatetimeIndex) -> pd.DatetimeIndex:
    expected = pd.date_range(ts[0], ts[-1], freq="15min", tz="UTC")
    return expected.difference(ts)


def _bad_1m_days_last_30d(conn: psycopg.Connection, *, exchange: str, symbol: str) -> list[str]:
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=30)
    rows = conn.execute(
        """
        SELECT date(bucket_ts at time zone 'UTC') AS d, count(*) AS c
        FROM market_data.candles_1m
        WHERE exchange=%(exchange)s AND symbol=%(symbol)s
          AND bucket_ts >= %(start_ts)s AND bucket_ts < %(end_ts)s
        GROUP BY 1
        ORDER BY 1;
        """,
        {
            "exchange": exchange,
            "symbol": symbol,
            "start_ts": f"{start.isoformat()} 00:00:00+00",
            "end_ts": f"{(end + timedelta(days=1)).isoformat()} 00:00:00+00",
        },
    ).fetchall()
    got = {str(r[0]): int(r[1]) for r in rows}

    bad: list[str] = []
    d = start
    while d <= end:
        ds = d.isoformat()
        if got.get(ds, 0) != 1440:
            bad.append(f"{ds}:{got.get(ds, 0)}")
        d += timedelta(days=1)
    return bad


def build_report(conn: psycopg.Connection, *, exchange: str, symbol: str) -> Report:
    ts = _fetch_15m_bucket_ts(conn, exchange=exchange, symbol=symbol)
    if len(ts) == 0:
        raise RuntimeError(f"no data: {exchange} {symbol}")

    miss = _missing_15m(ts)
    now = pd.Timestamp.now(tz="UTC")
    staleness = (now - ts[-1]).total_seconds() / 60.0

    bad_days = _bad_1m_days_last_30d(conn, exchange=exchange, symbol=symbol)

    samples = [str(x) for x in miss[:10]]
    if len(miss) > 10:
        samples.append("...")
        samples.extend([str(x) for x in miss[-10:]])

    bad_samples = bad_days[:12]
    if len(bad_days) > 12:
        bad_samples.append("...")

    return Report(
        exchange=exchange,
        symbol=symbol,
        min_ts=str(ts[0]),
        max_ts=str(ts[-1]),
        staleness_minutes=float(staleness),
        missing_15m=int(len(miss)),
        missing_15m_samples=samples,
        bad_1m_days_30d=int(len(bad_days)),
        bad_1m_days_30d_samples=bad_samples,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="K线质量报告（全历史）")
    parser.add_argument("--exchange", default="binance_futures_um")
    args = parser.parse_args()

    url = _load_db_url()
    symbols = _load_symbols()

    with psycopg.connect(url) as conn:
        reports = [build_report(conn, exchange=args.exchange, symbol=s) for s in symbols]

    # 输出为一份可读的纯文本（避免太长 JSON）
    for r in reports:
        print("=".ljust(80, "="))
        print("symbol:", r.symbol, "exchange:", r.exchange)
        print("range:", r.min_ts, "->", r.max_ts)
        print("staleness_minutes:", f"{r.staleness_minutes:.1f}")
        print("missing_15m:", r.missing_15m)
        if r.missing_15m:
            print("missing_15m_samples:")
            for x in r.missing_15m_samples:
                print(" ", x)
        print("bad_1m_days_last30d:", r.bad_1m_days_30d)
        if r.bad_1m_days_30d:
            print("bad_1m_days_last30d_samples:")
            for x in r.bad_1m_days_30d_samples:
                print(" ", x)


if __name__ == "__main__":
    main()
