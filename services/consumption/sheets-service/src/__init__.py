"""
Sheets Service - src 包初始化

目标：把“路径引导”收敛到单点，避免业务模块里到处修改 `sys.path`。

约定：
- repo root（tradecat/）加入 sys.path：用于复用 `assets/common/**`
- telegram-service/src 加入 sys.path：用于复用 `cards/*` 与导出逻辑
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.repo import find_repo_root, find_telegram_service_src


def _prepend_sys_path(paths: list[Path]) -> None:
    uniq: list[str] = []
    for p in paths:
        s = str(p)
        if not s or s in uniq:
            continue
        uniq.append(s)
    if not uniq:
        return
    # 统一前置：保持顺序 + 去重
    sys.path[:] = uniq + [p for p in sys.path if p not in uniq]


try:
    _start = Path(__file__).resolve()
    _repo_root = find_repo_root(_start)
    _tg_src = find_telegram_service_src(_repo_root)
    _prepend_sys_path([_repo_root, _tg_src])
except Exception:
    # 路径定位失败不应阻塞导入；具体错误由调用端显式处理/日志化。
    pass
