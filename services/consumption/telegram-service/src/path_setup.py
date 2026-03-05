from __future__ import annotations

import sys
from pathlib import Path


def find_repo_root(start: Path) -> Path:
    """
    定位仓库根目录（tradecat/）：
    - 必须同时存在：services/ + assets/ + assets/config/.env.example（或 legacy config/.env.example）
    """
    start = start.resolve()
    for p in [start] + list(start.parents):
        has_services = (p / "services").is_dir()
        has_assets = (p / "assets").is_dir()
        has_env_example = (p / "assets" / "config" / ".env.example").exists() or (p / "config" / ".env.example").exists()
        if has_services and has_assets and has_env_example:
            return p
    # 兜底：telegram-service/src 的固定层级（src -> telegram-service -> consumption -> services -> repo root）
    return start.parents[4]


def _prepend_sys_path(paths: list[Path]) -> None:
    uniq: list[str] = []
    for p in paths:
        try:
            if not p or not p.is_dir():
                continue
        except Exception:
            continue
        s = str(p)
        if not s or s in uniq:
            continue
        uniq.append(s)
    if not uniq:
        return
    sys.path[:] = uniq + [p for p in sys.path if p not in uniq]


def ensure_runtime_sys_path() -> Path:
    """
    统一注入运行时依赖路径（幂等）：
    - repo root：允许 `import assets.*`
    - ai-service：允许 `import src.pipeline`（ai-service 的 src 包）
    - signal-service/src：允许 `import rules/engines/events/...`
    - vis-service/src：允许 `import core/templates/...`（vis-service 的模块根）
    - trading-service/src：允许 `import indicators/...`（供 vis_handler 复用指标计算）
    - telegram-service/src：允许 `import bot/cards/signals`

    ⚠️ 重要：路径注入顺序必须避免模块名冲突。
    例如 signal-service 的 `config.py` 与 telegram-service 的 `config/` 包同名，
    若 telegram 路径优先，会导致 signal-service 误导入 telegram 的 config 并启动失败。
    """
    here = Path(__file__).resolve()
    telegram_src = here.parent
    repo_root = find_repo_root(here)

    # 先放 repo_root（assets.*），再放其它 service 依赖，最后放 telegram 自身模块根。
    candidates: list[Path] = [repo_root]

    # ai-service（包名为 src）
    for p in (
        repo_root / "services" / "compute" / "ai-service",
        repo_root / "services" / "ai-service",
    ):
        if p.is_dir():
            candidates.append(p)
            break

    # signal-service（模块根为 src 目录）
    for p in (
        repo_root / "services" / "compute" / "signal-service" / "src",
        repo_root / "services" / "signal-service" / "src",
    ):
        if p.is_dir():
            candidates.append(p)
            break

    # vis-service（模块根为 src 目录）
    for p in (
        repo_root / "services" / "consumption" / "vis-service" / "src",
        repo_root / "services" / "vis-service" / "src",
    ):
        if p.is_dir():
            candidates.append(p)
            break

    # trading-service（模块根为 src 目录）
    for p in (
        repo_root / "services" / "compute" / "trading-service" / "src",
        repo_root / "services" / "trading-service" / "src",
    ):
        if p.is_dir():
            candidates.append(p)
            break

    candidates.append(telegram_src)

    _prepend_sys_path(candidates)
    return repo_root
