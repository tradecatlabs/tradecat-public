#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""路径助手

统一提供仓库/服务/数据目录的解析，避免在脚本中反复手写 parents[n]。
约定：新增路径相关逻辑一律经由本模块，严禁再写相对路径或随意猜测层级。
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

# ---------------- 基础定位 ----------------

def _探测仓库根(start: Path) -> Path:
    """从当前文件向上查找同时存在 services 与 libs 的目录，找不到则兜底 parents[4]。"""

    for p in start.parents:
        if (p / "services").exists() and (p / "libs").exists():
            return p
    # 兜底：假设 libs/common/utils/路径助手.py 深度为 4
    return start.parents[4]


_HERE: Final[Path] = Path(__file__).resolve()
仓库根目录: Final[Path] = _探测仓库根(_HERE)


# ---------------- 对外工具 ----------------

def 获取仓库根目录() -> Path:
    """返回仓库根路径。"""

    return 仓库根目录


def 获取服务根目录(service: str) -> Path:
    """返回指定微服务根目录。"""

    return 仓库根目录 / "services" / service


def 获取数据服务CSV目录() -> Path:
    """返回 data-service 统一 CSV 根目录。"""

    return 获取服务根目录("data-service") / "data" / "csv"


def 获取日志目录(service: str) -> Path:
    """返回指定服务的日志目录。"""

    return 获取服务根目录(service) / "logs"


def 确保目录(path: Path) -> Path:
    """确保目录存在并返回自身，方便链式调用。"""

    path.mkdir(parents=True, exist_ok=True)
    return path


__all__ = [
    "仓库根目录",
    "获取仓库根目录",
    "获取服务根目录",
    "获取数据服务CSV目录",
    "获取日志目录",
    "确保目录",
]
