# ruff: noqa: UP017
from __future__ import annotations

import sys
from pathlib import Path

from src.repo import find_repo_root, find_telegram_service_src


def _ensure_import_path() -> None:
    start = Path(__file__).resolve()
    repo_root = find_repo_root(start)
    tg_src = find_telegram_service_src(repo_root)

    # 让 `import libs.*` 可用
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    # 让 `import bot.*` / `import cards.*` 可用（telegram-service 的 src 包）
    if str(tg_src) not in sys.path:
        sys.path.insert(0, str(tg_src))


def export_symbol_full_txt(*, symbol: str, lang: str = "zh_CN") -> str:
    """
    导出“币种查询功能”的完整 TXT（与 TG 侧一致口径）。
    - symbol: 允许 BTC / BTCUSDT
    - 返回：多行文本（psql 风格）
    """
    _ensure_import_path()
    from bot.single_token_txt import export_single_token_txt  # type: ignore

    sym = (symbol or "").strip()
    if not sym:
        return ""
    return export_single_token_txt(sym, lang=lang)


def normalize_symbol_tab_title(*, symbol: str, prefix: str) -> str:
    sym = (symbol or "").strip().upper()
    if not sym:
        return (prefix or "币种查询_").strip() + "UNKNOWN"
    return f"{(prefix or '币种查询_').strip()}{sym}"

