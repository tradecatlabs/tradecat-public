from __future__ import annotations

from pathlib import Path


def find_repo_root(start: Path) -> Path:
    """
    兼容两套目录结构：
    - 新结构：services/consumption/telegram-service
    - 旧结构：services/telegram-service
    """
    for p in [start] + list(start.parents):
        has_services = (p / "services").is_dir()
        has_assets = (p / "assets").is_dir()
        has_env_example = (p / "assets" / "config" / ".env.example").exists() or (p / "config" / ".env.example").exists()
        if has_services and has_assets and has_env_example:
            return p
    raise RuntimeError(f"无法定位 repo root（从 {start} 向上未找到 services + assets/config/.env.example）")


def find_telegram_service_src(repo_root: Path) -> Path:
    candidates = [
        repo_root / "services" / "consumption" / "telegram-service" / "src",
        repo_root / "services" / "telegram-service" / "src",
    ]
    for p in candidates:
        if p.is_dir():
            return p
    raise RuntimeError(f"无法定位 telegram-service/src（尝试过：{', '.join(str(c) for c in candidates)}）")
