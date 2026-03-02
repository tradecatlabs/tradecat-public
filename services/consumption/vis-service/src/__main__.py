"""
入口: python -m src

用法:
    cd services/consumption/vis-service
    python -m src                    # 启动服务
    python -m src --host 0.0.0.0     # 指定监听地址
    python -m src --port 8087        # 指定端口
"""
import argparse
import sys
from pathlib import Path

SRC_DIR = Path(__file__).parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def main():
    parser = argparse.ArgumentParser(description="TradeCat Visualization Service")
    parser.add_argument("--host", type=str, default=None, help="监听地址")
    parser.add_argument("--port", type=int, default=None, help="监听端口")
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    args = parser.parse_args()

    import uvicorn
    from core.settings import get_settings

    settings = get_settings()
    host = args.host or settings.host
    port = args.port or settings.port

    uvicorn.run(
        "src.main:app",
        host=host,
        port=port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
