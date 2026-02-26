"""
类比预测（Analog Forecasting）

目标：
- 用当前 15m 行情窗口（收益率序列）在全历史中检索相似窗口（Top-K）
- 聚合这些相似窗口的“未来 H 根”真实走势，输出分位数带/上涨概率等统计

说明：
- 默认从 market_data.candles_1m 聚合 15m，避免依赖连续聚合视图的物化窗口
- 为了可解释性与稳定性，MVP 仅使用 numpy/pandas 做 z-normalized 欧氏距离检索
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
import psycopg

from ..config import config


DistanceMetric = Literal["znorm_l2", "corr"]
SourceMode = Literal["auto", "candles_15m", "aggregate_1m"]

LOG = logging.getLogger("analog_forecast")


@dataclass(frozen=True)
class ForecastResult:
    symbol: str
    exchange: str
    interval: str
    window: int
    horizon: int
    top_k: int
    metric: DistanceMetric
    asof_ts: str
    rows: int
    missing_bars: int
    neighbor_indices: list[int]
    neighbor_distances: list[float]
    # 每一步未来收益的分布摘要（以 log return 聚合）
    p10: list[float]
    p50: list[float]
    p90: list[float]
    up_prob: list[float]


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def fetch_15m_close_full(
    conn: psycopg.Connection,
    *,
    exchange: str,
    symbol: str,
    interval: str,
    source: SourceMode,
) -> pd.DataFrame:
    if interval != "15m":
        raise ValueError("MVP 仅支持 interval=15m（后续可扩展）")

    def fetch_from_cagg() -> pd.DataFrame:
        rows = conn.execute(
            """
            SELECT bucket_ts, close
            FROM market_data.candles_15m
            WHERE exchange=%(exchange)s AND symbol=%(symbol)s
            ORDER BY 1;
            """,
            {"exchange": exchange, "symbol": symbol},
        ).fetchall()
        return pd.DataFrame(rows, columns=["bucket_ts", "close"])

    def fetch_from_1m_aggregate() -> pd.DataFrame:
        rows = conn.execute(
            """
            SELECT
              time_bucket('15 minutes', bucket_ts) AS bucket_ts,
              last(close, bucket_ts) AS close
            FROM market_data.candles_1m
            WHERE exchange=%(exchange)s AND symbol=%(symbol)s
            GROUP BY 1
            ORDER BY 1;
            """,
            {"exchange": exchange, "symbol": symbol},
        ).fetchall()
        return pd.DataFrame(rows, columns=["bucket_ts", "close"])

    if source == "candles_15m":
        df = fetch_from_cagg()
    elif source == "aggregate_1m":
        df = fetch_from_1m_aggregate()
    elif source == "auto":
        df_cagg = fetch_from_cagg()
        df_agg = fetch_from_1m_aggregate()
        # 如果连续聚合视图本身不覆盖全历史（常见：只物化最近一段），自动回退到 1m 全历史聚合
        if df_cagg.empty or df_agg.empty:
            df = df_agg
        else:
            min_cagg = pd.to_datetime(df_cagg["bucket_ts"].iloc[0], utc=True)
            min_agg = pd.to_datetime(df_agg["bucket_ts"].iloc[0], utc=True)
            if min_cagg <= min_agg:
                df = df_cagg
            else:
                LOG.warning(
                    "candles_15m 视图不覆盖全历史(min=%s)，回退到 candles_1m 聚合(min=%s)",
                    min_cagg,
                    min_agg,
                )
                df = df_agg
    else:
        raise ValueError(f"不支持的 source: {source}")

    if df.empty:
        return df

    df["bucket_ts"] = pd.to_datetime(df["bucket_ts"], utc=True)
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df


def _make_continuous_index(df: pd.DataFrame, *, interval: str) -> tuple[pd.DataFrame, int]:
    if df.empty:
        return df, 0
    if interval != "15m":
        raise ValueError("MVP 仅支持 interval=15m（后续可扩展）")

    expected = pd.date_range(df["bucket_ts"].iloc[0], df["bucket_ts"].iloc[-1], freq="15min", tz="UTC")
    df2 = df.set_index("bucket_ts").reindex(expected)
    missing = int(df2["close"].isna().sum())
    df2 = df2.reset_index(names="bucket_ts")
    return df2, missing


def _rolling_windows(x: np.ndarray, window: int) -> np.ndarray:
    if window <= 0:
        raise ValueError("window 必须 > 0")
    if x.ndim != 1:
        raise ValueError("x 必须是一维数组")
    if len(x) < window:
        raise ValueError("数据长度不足以形成窗口")
    # shape: (n-window+1, window)
    return np.lib.stride_tricks.sliding_window_view(x, window_shape=window)


def _znorm(x: np.ndarray, axis: int = -1) -> np.ndarray:
    mean = np.nanmean(x, axis=axis, keepdims=True)
    std = np.nanstd(x, axis=axis, keepdims=True)
    std = np.where(std <= 1e-12, np.nan, std)
    return (x - mean) / std


def _dist_znorm_l2(candidates: np.ndarray, query: np.ndarray) -> np.ndarray:
    # candidates: (n, m), query: (m,)
    zc = _znorm(candidates, axis=1)
    zq = _znorm(query, axis=0)
    diff = zc - zq
    # ignore NaNs (shouldn't exist after clean, but keep robust)
    return np.sqrt(np.nanmean(diff * diff, axis=1))


def _dist_corr(candidates: np.ndarray, query: np.ndarray) -> np.ndarray:
    # distance = 1 - corr
    zc = _znorm(candidates, axis=1)
    zq = _znorm(query, axis=0)
    num = np.nanmean(zc * zq, axis=1)
    den = np.nanstd(zc, axis=1) * (np.nanstd(zq) if np.isfinite(np.nanstd(zq)) else np.nan)
    corr = np.where(den <= 1e-12, np.nan, num / den)
    return 1.0 - corr


def analog_forecast(
    close_df: pd.DataFrame,
    *,
    window: int,
    horizon: int,
    top_k: int,
    metric: DistanceMetric,
    exclude_recent: int = 0,
) -> tuple[list[int], list[float], pd.DataFrame]:
    if close_df.empty:
        raise ValueError("close_df 为空")
    if horizon <= 0:
        raise ValueError("horizon 必须 > 0")
    if top_k <= 0:
        raise ValueError("top_k 必须 > 0")

    close = close_df["close"].astype(float).to_numpy()

    # 对缺口保持“时间轴不变”的处理方式：
    # - close 存在 NaN 时，logret 会产生 NaN
    # - 后续滑窗时过滤掉包含 NaN 的窗口，避免跨缺口拼接造成伪相似
    logret = np.diff(np.log(close))
    if len(logret) < window + horizon + 1:
        raise ValueError("历史长度不足以做类比预测（logret 太短）")

    # windows are over logret
    X = _rolling_windows(logret, window)  # (n_win, window)
    # exclude windows that don't have forward horizon available
    n_total = X.shape[0]
    max_start = n_total - horizon  # last usable start index (inclusive) is max_start-1
    if max_start <= 0:
        raise ValueError("可用窗口不足（无法留出 horizon）")

    query = X[-1].copy()

    # candidates exclude tail region to avoid trivial/self match
    end = max_start
    if exclude_recent > 0:
        end = max(0, end - exclude_recent)
    candidates = X[:end]

    if candidates.shape[0] == 0:
        raise ValueError("候选窗口为空（请减少 exclude_recent 或增加历史长度）")

    # compute distance
    if metric == "znorm_l2":
        dist = _dist_znorm_l2(candidates, query)
    elif metric == "corr":
        dist = _dist_corr(candidates, query)
    else:
        raise ValueError(f"不支持的 metric: {metric}")

    # 过滤掉包含 NaN 的候选窗口（通常由历史 close 缺口导致）
    candidate_finite = np.isfinite(candidates).all(axis=1)
    query_finite = bool(np.isfinite(query).all())
    if not query_finite:
        raise ValueError("当前窗口包含 NaN/Inf（当前 close 序列存在缺口），无法做预测")

    # remove NaN distances (e.g., constant windows)
    valid = np.isfinite(dist) & candidate_finite
    cand_idx = np.where(valid)[0]
    dist = dist[valid]
    if dist.size == 0:
        raise ValueError("所有候选窗口距离均为 NaN（可能是常量序列/异常数据）")

    k = min(top_k, dist.size)
    top_pos = np.argpartition(dist, kth=k - 1)[:k]
    top_pos = top_pos[np.argsort(dist[top_pos])]

    nn_start_idx = cand_idx[top_pos]  # indices in X
    nn_dist = dist[top_pos]

    # collect forward paths (log returns)
    forward = np.stack([logret[i + window : i + window + horizon] for i in nn_start_idx], axis=0)  # (k, horizon)
    forward_df = pd.DataFrame(forward)

    return nn_start_idx.tolist(), nn_dist.astype(float).tolist(), forward_df


def summarize_forward(forward_df: pd.DataFrame) -> tuple[list[float], list[float], list[float], list[float]]:
    # forward_df: rows=neighbors, cols=step
    arr = forward_df.to_numpy(dtype=float)
    p10 = np.nanquantile(arr, 0.10, axis=0)
    p50 = np.nanquantile(arr, 0.50, axis=0)
    p90 = np.nanquantile(arr, 0.90, axis=0)
    up = np.nanmean(arr > 0, axis=0)
    return p10.tolist(), p50.tolist(), p90.tolist(), up.tolist()


def main() -> None:
    parser = argparse.ArgumentParser(description="类比预测（15m，全历史）")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--exchange", default=config.exchange)
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--window", type=int, default=128, help="相似窗口长度（以 log-return 步数计）")
    parser.add_argument("--horizon", type=int, default=32, help="预测未来步数（以 log-return 步数计）")
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--metric", choices=["znorm_l2", "corr"], default="znorm_l2")
    parser.add_argument("--exclude-recent", type=int, default=256, help="排除最近 N 个候选窗口，避免时序近邻泄漏")
    parser.add_argument(
        "--source",
        choices=["auto", "candles_15m", "aggregate_1m"],
        default="auto",
        help="取数源：auto=优先用 candles_15m（若覆盖全历史），否则回退到 candles_1m 聚合",
    )
    parser.add_argument("--out", type=str, default="", help="输出 JSON 文件路径（可选）")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    symbol = args.symbol.upper()
    interval = args.interval
    metric: DistanceMetric = args.metric

    with psycopg.connect(config.db_url) as conn:
        df = fetch_15m_close_full(
            conn,
            exchange=args.exchange,
            symbol=symbol,
            interval=interval,
            source=args.source,
        )

    if df.empty:
        raise SystemExit(f"无数据: exchange={args.exchange} symbol={symbol} interval={interval}")

    df, missing = _make_continuous_index(df, interval=interval)
    # 对于类比预测，保持时间轴完整，缺口通过“窗口过滤”处理，不做插值/前向填充（避免伪信号）

    nn_idx, nn_dist, forward_df = analog_forecast(
        df,
        window=args.window,
        horizon=args.horizon,
        top_k=args.top_k,
        metric=metric,
        exclude_recent=args.exclude_recent,
    )

    p10, p50, p90, up_prob = summarize_forward(forward_df)

    # asof 取最后一个可用 close 的时间（不是最后一行，最后一行可能是缺口 NaN）
    df_valid = df.dropna(subset=["close"])
    asof_ts = str(df_valid["bucket_ts"].iloc[-1])

    result = ForecastResult(
        symbol=symbol,
        exchange=args.exchange,
        interval=interval,
        window=args.window,
        horizon=args.horizon,
        top_k=args.top_k,
        metric=metric,
        asof_ts=asof_ts,
        rows=int(len(df_valid)),
        missing_bars=int(missing),
        neighbor_indices=nn_idx,
        neighbor_distances=nn_dist,
        p10=p10,
        p50=p50,
        p90=p90,
        up_prob=up_prob,
    )

    payload = json.loads(json.dumps(result.__dict__, ensure_ascii=False, default=str))
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
