from __future__ import annotations

from pathlib import Path


def find_repo_root(start: Path) -> Path:
    """
    兼容两套目录结构：
    - 新结构：services/consumption/telegram-service
    - 旧结构：services/telegram-service
    """
    for p in [start] + list(start.parents):
        if (p / "config").is_dir() and (p / "services").is_dir() and (p / "libs").is_dir():
            return p
    raise RuntimeError(f"无法定位 repo root（从 {start} 向上未找到 config/services/libs）")


def find_telegram_service_src(repo_root: Path) -> Path:
    candidates = [
        repo_root / "services" / "consumption" / "telegram-service" / "src",
        repo_root / "services" / "telegram-service" / "src",
    ]
    for p in candidates:
        if p.is_dir():
            return p
    raise RuntimeError(f"无法定位 telegram-service/src（尝试过：{', '.join(str(c) for c in candidates)}）")
