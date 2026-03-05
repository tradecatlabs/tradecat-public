"""入口: python -m src 或 python src/__main__.py"""

from __future__ import annotations

import argparse
import logging
import signal
import subprocess
import sys
import time
from pathlib import Path

# 确保 src 在路径中
SRC_DIR = Path(__file__).parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from config import settings  # noqa: E402

logger = logging.getLogger(__name__)


class Scheduler:
    """进程调度器"""

    def __init__(self):
        self._procs: dict[str, dict] = {}
        self._running = False

    def add(self, name: str, cmd: list[str]) -> None:
        self._procs[name] = {"cmd": cmd, "proc": None, "restarts": 0}

    def run(self) -> None:
        self._running = True
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "_running", False))
        signal.signal(signal.SIGINT, lambda *_: setattr(self, "_running", False))

        for name, info in self._procs.items():
            self._start(name, info)

        while self._running:
            for name, info in self._procs.items():
                if info["proc"] and info["proc"].poll() is not None:
                    if info["restarts"] < 10:
                        logger.warning("%s 退出，重启", name)
                        info["restarts"] += 1
                        time.sleep(min(5 * info["restarts"], 60))
                        self._start(name, info)
            time.sleep(5)

        for info in self._procs.values():
            if info["proc"]:
                info["proc"].terminate()

    def _start(self, name: str, info: dict) -> None:
        log = settings.log_dir / f"{name}.log"
        with open(log, "a") as f:
            info["proc"] = subprocess.Popen(info["cmd"], stdout=f, stderr=subprocess.STDOUT, cwd=str(SRC_DIR))
        logger.info("启动 %s (PID=%d)", name, info["proc"].pid)


def main() -> None:
    parser = argparse.ArgumentParser(description="Data Service")
    parser.add_argument("--ws", action="store_true", help="WebSocket 采集")
    parser.add_argument("--metrics", action="store_true", help="指标采集")
    parser.add_argument("--backfill", action="store_true", help="历史补齐")
    parser.add_argument("--all", action="store_true", help="全部启动")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    py = sys.executable
    sched = Scheduler()

    if args.all or args.ws:
        sched.add("ws", [py, "collectors/ws.py"])
    if args.all or args.metrics:
        sched.add("metrics", [py, "collectors/metrics.py"])
    if args.backfill:
        sched.add("backfill", [py, "collectors/backfill.py"])

    if not sched._procs:
        print("用法: python src/__main__.py --ws|--metrics|--backfill|--all")
        sys.exit(1)

    sched.run()


if __name__ == "__main__":
    main()
