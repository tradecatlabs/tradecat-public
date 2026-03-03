"""API Service - 对外数据消费 REST API"""

from __future__ import annotations

import sys
from pathlib import Path

__version__ = "1.0.0"


# 将仓库根目录加入 sys.path，供 api-service 复用 `assets/common/**`（全局契约/配置/工具）。
_repo_root = Path(__file__).resolve().parents[4]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))
