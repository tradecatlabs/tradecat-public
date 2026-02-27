#!/usr/bin/env python3
"""
从 HuggingFace 下载历史数据并导入 TimescaleDB

用法:
    python scripts/download_hf_data.py [--symbols BTCUSDT,ETHUSDT]

默认下载 main4 币种 (BTC/ETH/BNB/SOL) 的全部历史数据
Main4 数据集约 415MB，包含 1150 万条记录（2020-2026）
"""

import argparse
import gzip
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 添加项目路径
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

try:
    import pandas as pd
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError as e:
    print(f"缺少依赖: {e}")
    print("请安装: pip install pandas psycopg2-binary huggingface_hub")
    sys.exit(1)

# HuggingFace 数据集 URL
HF_DATASET = "123olp/binance-futures-ohlcv-2018-2026"
CANDLES_FILE = "candles_1m.csv.gz"
METRICS_FILE = "futures_metrics_5m.csv.gz"

# 默认币种 (main4)
DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]


def load_env():
    """加载 .env 配置"""
    env_file = ROOT / "assets" / "config" / ".env"
    if not env_file.exists():
        # 兼容旧路径（只读回退）
        legacy = ROOT / "config" / ".env"
        env_file = legacy if legacy.exists() else env_file
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    value = value.strip().strip('"').strip("'")
                    os.environ.setdefault(key, value)


def get_db_connection():
    """获取数据库连接"""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL 未配置，请检查 assets/config/.env")
    return psycopg2.connect(db_url)


def download_from_hf(filename: str, output_dir: Path) -> Path:
    """从 HuggingFace 下载文件"""
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("请安装: pip install huggingface_hub")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename

    if output_path.exists():
        print(f"  文件已存在: {output_path}")
        return output_path

    print(f"  下载中: {filename} (可能需要较长时间...)")
    downloaded = hf_hub_download(
        repo_id=HF_DATASET,
        filename=filename,
        repo_type="dataset",
        local_dir=str(output_dir),
    )
    return Path(downloaded)


def stream_csv_gz(filepath: Path, symbols: list, days: int = None, chunksize: int = 100000):
    """流式读取 CSV.gz 文件，按币种和时间过滤"""
    cutoff_date = None
    if days:
        cutoff_date = datetime.utcnow() - timedelta(days=days)

    print(f"  过滤币种: {symbols}")
    if cutoff_date:
        print(f"  过滤时间: {cutoff_date.strftime('%Y-%m-%d')} 之后")

    total_rows = 0
    for chunk in pd.read_csv(filepath, compression="gzip", chunksize=chunksize):
        # 过滤币种
        chunk = chunk[chunk["symbol"].isin(symbols)]

        # 过滤时间
        if cutoff_date and "bucket_ts" in chunk.columns:
            chunk["bucket_ts"] = pd.to_datetime(chunk["bucket_ts"])
            chunk = chunk[chunk["bucket_ts"] >= cutoff_date]
        elif cutoff_date and "create_time" in chunk.columns:
            chunk["create_time"] = pd.to_datetime(chunk["create_time"])
            chunk = chunk[chunk["create_time"] >= cutoff_date]

        if len(chunk) > 0:
            total_rows += len(chunk)
            yield chunk

    print(f"  总计读取: {total_rows:,} 行")


def import_candles(conn, filepath: Path, symbols: list, days: int = None):
    """导入 K 线数据到 candles_1m 表"""
    print("\n=== 导入 K 线数据 ===")

    cursor = conn.cursor()

    # 检查表是否存在
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'market_data' AND table_name = 'candles_1m'
        )
    """)
    if not cursor.fetchone()[0]:
        print("  ✗ 表 market_data.candles_1m 不存在，请先导入 schema")
        return

    insert_sql = """
        INSERT INTO market_data.candles_1m 
        (exchange, symbol, bucket_ts, open, high, low, close, volume, 
         quote_volume, trade_count, is_closed, source, ingested_at, updated_at,
         taker_buy_volume, taker_buy_quote_volume)
        VALUES %s
        ON CONFLICT (exchange, symbol, bucket_ts) DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            quote_volume = EXCLUDED.quote_volume,
            trade_count = EXCLUDED.trade_count,
            taker_buy_volume = EXCLUDED.taker_buy_volume,
            taker_buy_quote_volume = EXCLUDED.taker_buy_quote_volume,
            updated_at = NOW()
    """

    total_inserted = 0
    for chunk in stream_csv_gz(filepath, symbols, days):
        rows = []
        for _, row in chunk.iterrows():
            rows.append((
                row.get("exchange", "binance_futures_um"),
                row["symbol"],
                row["bucket_ts"],
                row["open"],
                row["high"],
                row["low"],
                row["close"],
                row["volume"],
                row.get("quote_volume", 0),
                row.get("trade_count", 0),
                row.get("is_closed", "t"),
                row.get("source", "huggingface"),
                datetime.utcnow(),
                datetime.utcnow(),
                row.get("taker_buy_volume", 0),
                row.get("taker_buy_quote_volume", 0),
            ))

        if rows:
            execute_values(cursor, insert_sql, rows, page_size=1000)
            total_inserted += len(rows)
            print(f"  已导入: {total_inserted:,} 行", end="\r")

    conn.commit()
    print(f"\n  ✓ K 线数据导入完成: {total_inserted:,} 行")


def import_metrics(conn, filepath: Path, symbols: list, days: int = None):
    """导入期货指标数据"""
    print("\n=== 导入期货指标 ===")

    cursor = conn.cursor()

    # 检查表是否存在
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'market_data' AND table_name = 'binance_futures_metrics_5m'
        )
    """)
    if not cursor.fetchone()[0]:
        print("  ✗ 表 market_data.binance_futures_metrics_5m 不存在，跳过")
        return

    insert_sql = """
        INSERT INTO market_data.binance_futures_metrics_5m 
        (create_time, symbol, sum_open_interest, sum_open_interest_value,
         sum_toptrader_long_short_ratio, sum_taker_long_short_vol_ratio, count_long_short_ratio)
        VALUES %s
        ON CONFLICT (create_time, symbol) DO UPDATE SET
            sum_open_interest = EXCLUDED.sum_open_interest,
            sum_open_interest_value = EXCLUDED.sum_open_interest_value,
            sum_toptrader_long_short_ratio = EXCLUDED.sum_toptrader_long_short_ratio,
            sum_taker_long_short_vol_ratio = EXCLUDED.sum_taker_long_short_vol_ratio,
            count_long_short_ratio = EXCLUDED.count_long_short_ratio
    """

    total_inserted = 0
    for chunk in stream_csv_gz(filepath, symbols, days):
        rows = []
        for _, row in chunk.iterrows():
            rows.append((
                row["create_time"],
                row["symbol"],
                row.get("sum_open_interest", 0),
                row.get("sum_open_interest_value", 0),
                row.get("sum_toptrader_long_short_ratio", 0),
                row.get("sum_taker_long_short_vol_ratio", 0),
                row.get("count_long_short_ratio", 0),
            ))

        if rows:
            execute_values(cursor, insert_sql, rows, page_size=1000)
            total_inserted += len(rows)
            print(f"  已导入: {total_inserted:,} 行", end="\r")

    conn.commit()
    print(f"\n  ✓ 期货指标导入完成: {total_inserted:,} 行")


def main():
    parser = argparse.ArgumentParser(description="从 HuggingFace 下载并导入历史数据")
    parser.add_argument(
        "--symbols",
        type=str,
        default=",".join(DEFAULT_SYMBOLS),
        help=f"要下载的币种，逗号分隔 (默认: {','.join(DEFAULT_SYMBOLS)})",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="只导入最近 N 天的数据 (默认: 全部)",
    )
    parser.add_argument(
        "--skip-candles",
        action="store_true",
        help="跳过 K 线数据导入",
    )
    parser.add_argument(
        "--skip-metrics",
        action="store_true",
        help="跳过期货指标导入",
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="只下载，不导入数据库",
    )
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",")]

    print("=" * 50)
    print("  HuggingFace 历史数据下载工具")
    print("=" * 50)
    print(f"  数据集: {HF_DATASET}")
    print(f"  币种: {symbols}")
    print(f"  天数: {'全部' if not args.days else args.days}")
    print()

    # 加载配置
    load_env()

    # 下载目录
    download_dir = ROOT / "data" / "hf_downloads"

    # 下载文件
    candles_path = None
    metrics_path = None

    if not args.skip_candles:
        print("下载 K 线数据...")
        candles_path = download_from_hf(CANDLES_FILE, download_dir)

    if not args.skip_metrics:
        print("下载期货指标...")
        metrics_path = download_from_hf(METRICS_FILE, download_dir)

    if args.download_only:
        print("\n✓ 下载完成 (--download-only)")
        return

    # 连接数据库
    print("\n连接数据库...")
    try:
        conn = get_db_connection()
        print("  ✓ 数据库连接成功")
    except Exception as e:
        print(f"  ✗ 数据库连接失败: {e}")
        sys.exit(1)

    # 导入数据
    try:
        if candles_path and not args.skip_candles:
            import_candles(conn, candles_path, symbols, args.days)

        if metrics_path and not args.skip_metrics:
            import_metrics(conn, metrics_path, symbols, args.days)

    finally:
        conn.close()

    print("\n" + "=" * 50)
    print("  ✓ 数据导入完成")
    print("=" * 50)


if __name__ == "__main__":
    main()
