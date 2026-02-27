"""
入口: python -m src

用法:
    python -m src --once                   # 一次性计算（推荐）
    python -m src --full-async             # 完全异步持续运行
    python -m src --event                  # 事件驱动模式（实验性）
    python -m src --symbols BTCUSDT,ETHUSDT --intervals 5m,15m
"""
import argparse
import os
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

# 加载 assets/config/.env（优先）→ config/.env（兼容只读回退）
_repo_root = Path(__file__).resolve().parents[4]
_env_file = _repo_root / "assets" / "config" / ".env"
if not _env_file.exists():
    _env_file = _repo_root / "config" / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main():
    parser = argparse.ArgumentParser(description="指标计算服务")
    parser.add_argument("--once", action="store_true", help="一次性计算（推荐，可配合crontab）")
    parser.add_argument("--full-async", dest="full_async", action="store_true", help="完全异步持续运行")
    parser.add_argument("--event", action="store_true", help="事件驱动模式（实验性）")
    parser.add_argument("--mode", choices=["all", "batch", "incremental"], default="all", help="计算模式")
    parser.add_argument("--symbols", type=str, help="交易对，逗号分隔")
    parser.add_argument("--intervals", type=str, help="周期，逗号分隔")
    parser.add_argument("--indicators", type=str, help="指标名，逗号分隔")
    parser.add_argument("--lookback", type=int, default=300, help="K线窗口大小")
    parser.add_argument(
        "--workers",
        type=int,
        default=int(os.getenv("MAX_WORKERS", "4")),
        help="并行进程数",
    )
    parser.add_argument("--log-file", type=str, help="日志文件路径")
    parser.add_argument("--log-level", type=str, default="INFO", help="日志级别")
    parser.add_argument("--json-log", action="store_true", help="使用JSON格式日志")
    parser.add_argument("--metrics-file", type=str, help="指标输出文件路径")

    args = parser.parse_args()

    # 初始化可观测性
    from .observability import setup_logging, metrics
    from .observability.alerting import setup_alerting

    setup_logging(
        level=args.log_level,
        log_file=args.log_file,
        json_format=args.json_log,
    )

    # 配置告警文件
    if args.log_file:
        alert_file = Path(args.log_file).parent / "alerts.jsonl"
        setup_alerting(file_path=alert_file)

    from . import indicators  # noqa - 触发指标注册

    # 优先读 --symbols 参数，其次读 TEST_SYMBOLS 环境变量
    symbols = args.symbols.split(",") if args.symbols else None
    if not symbols:
        test_symbols = os.environ.get("TEST_SYMBOLS")
        if test_symbols:
            symbols = test_symbols.split(",")

    intervals = args.intervals.split(",") if args.intervals else None
    indicator_list = args.indicators.split(",") if args.indicators else None

    try:
        if args.full_async:
            from .core.async_full_engine import run_async_full
            run_async_full(
                symbols=symbols,
                intervals=intervals,
                indicators=indicator_list,
                high_workers=args.workers,
                low_workers=max(1, args.workers // 2),
            )
        elif args.event:
            from .core.event_engine import run_event_engine
            run_event_engine(
                symbols=symbols,
                intervals=intervals,
                workers=args.workers,
            )
        else:
            # 默认：一次性计算
            from .core.engine import Engine
            Engine(
                symbols=symbols,
                intervals=intervals or ["1m", "5m", "15m", "1h", "4h", "1d", "1w"],
                indicators=indicator_list,
                lookback=args.lookback,
                max_workers=args.workers,
            ).run(mode=args.mode)
    finally:
        # 保存指标
        if args.metrics_file:
            metrics.save(Path(args.metrics_file))


if __name__ == "__main__":
    main()
