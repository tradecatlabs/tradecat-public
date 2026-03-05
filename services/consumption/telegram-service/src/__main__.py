"""
入口: python -m src

用法:
    cd services/consumption/telegram-service
    python -m src
"""
import sys
from pathlib import Path

# 确保 src 目录在路径中
SRC_DIR = Path(__file__).parent
_src_dir = str(SRC_DIR)
sys.path[:] = [_src_dir] + [p for p in sys.path if p != _src_dir]

from bot.app import main

if __name__ == "__main__":
    main()
