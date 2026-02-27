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
    """从当前文件向上查找仓库根目录。

    约定：
    - 新结构以 `services/` + `assets/config/.env.example` 作为锚点。
    - 兼容旧结构（`config/.env.example`）仅用于定位 root，不作为写入路径。
    """

    for p in start.parents:
        if (p / "services").exists() and (p / "assets" / "config" / ".env.example").exists():
            return p
        if (p / "services").exists() and (p / "config" / ".env.example").exists():
            return p

    # 兜底：当前文件位于 assets/common/utils/路径助手.py，仓库根应为 parents[3]
    fallback_idx = 3
    if len(start.parents) <= fallback_idx:
        fallback_idx = len(start.parents) - 1
    return start.parents[fallback_idx]


_HERE: Final[Path] = Path(__file__).resolve()
仓库根目录: Final[Path] = _探测仓库根(_HERE)


# ---------------- 对外工具 ----------------

def 获取仓库根目录() -> Path:
    """返回仓库根路径。"""

    return 仓库根目录


def 获取服务根目录(service: str) -> Path:
    """返回指定微服务根目录。"""

    candidates = [
        仓库根目录 / "services" / "ingestion" / service,
        仓库根目录 / "services" / "compute" / service,
        仓库根目录 / "services" / "consumption" / service,
        仓库根目录 / "services" / service,  # legacy
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[-1]


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
