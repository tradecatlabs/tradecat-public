#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快速检查代码中的 i18n key 与 bot.po 的对齐情况。

扫描 `services/consumption/telegram-service/src` 下的 Python 代码，抽取 `_t/_btn/_btn_lang/I18N.gettext`
中的字符串字面量作为消息键，与 `services/consumption/telegram-service/locales/*/LC_MESSAGES/bot.po`
中的 msgid 做集合对比：
- 缺失键：代码使用但 po 中不存在
- 冗余键：po 中存在但代码未使用（仅提示，不视为错误）

退出码：
- 0: 无缺失键
- 1: 存在缺失键
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "services" / "consumption" / "telegram-service" / "src"


def _discover_locale_dir() -> Path:
    """自动发现 i18n 目录。"""
    default = REPO_ROOT / "services" / "consumption" / "telegram-service" / "locales"
    def _has_bot(locale_dir: Path) -> bool:
        for lang in ("zh_CN", "en"):
            lc = locale_dir / lang / "LC_MESSAGES"
            if (lc / "bot.po").exists() or (lc / "bot.mo").exists():
                return True
        return False
    if _has_bot(default):
        return default
    candidates: set[Path] = set()
    for po in REPO_ROOT.rglob("bot.po"):
        parts = po.parts
        if "node_modules" in parts:
            continue
        if ("assets" in parts and "repo" in parts) or ("assets" in parts and "services-preview" in parts):
            continue
        if po.parent.name != "LC_MESSAGES":
            continue
        locale_dir = po.parents[2]
        candidates.add(locale_dir)
    for locale_dir in sorted(candidates):
        if _has_bot(locale_dir):
            return locale_dir
    return default


LOCALE_DIR = _discover_locale_dir()
PO_FILES = [
    LOCALE_DIR / "zh_CN" / "LC_MESSAGES" / "bot.po",
    LOCALE_DIR / "en" / "LC_MESSAGES" / "bot.po",
]


def collect_po_keys(po_path: Path) -> set[str]:
    keys: set[str] = set()
    current = None
    for line in po_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("msgid"):
            # 简易解析：msgid "xxx"
            m = re.match(r'msgid\s+"(.*)"', line)
            current = m.group(1) if m else None
            if current is not None:
                keys.add(current)
    return keys


def collect_code_keys() -> set[str]:
    keys: set[str] = set()
    patterns = [
        r"_t\([^,]*,\s*['\"]([^'\"}]+)['\"]",
        r"_btn(?:_lang)?\([^,]*,\s*['\"]([^'\"}]+)['\"]",
        r"gettext\(\s*['\"]([^'\"}]+)['\"]",
    ]
    regexes = [re.compile(p) for p in patterns]
    for path in SRC_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for rgx in regexes:
            for m in rgx.finditer(text):
                key = m.group(1)
                # 跳过动态/占位键，减少误报
                if "{" in key or "}" in key:
                    continue
                allowed_prefixes = (
                    "btn",
                    "kb",
                    "lang",
                    "menu",
                    "start",
                    "error",
                    "flow",
                    "period",
                    "ranking",
                    "time",
                    "signal",
                    "query",
                    "feature",
                    "ai",
                    "panel",
                    "sort",
                    "ratio",
                    "help",
                    "market",
                )
                if "." in key or key.startswith(allowed_prefixes):
                    keys.add(key)
    return keys


def main() -> int:
    code_keys = collect_code_keys()
    po_keys = set().union(*(collect_po_keys(p) for p in PO_FILES if p.exists()))

    missing = sorted(code_keys - po_keys)
    extra = sorted(po_keys - code_keys)

    print(f"[i18n] 代码键数量: {len(code_keys)}, 词条数量: {len(po_keys)}")
    if missing:
        print("❌ 缺失键 (代码中存在，po 中不存在):")
        for k in missing:
            print(f"  - {k}")
    else:
        print("✅ 未发现缺失键")

    if extra:
        print("ℹ️  冗余键 (po 中存在，代码未使用) - 仅提示:")
        for k in extra[:50]:
            print(f"  - {k}")
        if len(extra) > 50:
            print(f"  ... 共 {len(extra)} 项")

    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
