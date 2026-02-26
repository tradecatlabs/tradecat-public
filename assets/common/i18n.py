"""轻量级 i18n 工具

提供统一的语言规范化、翻译加载与占位符格式化。
默认使用 gettext，若缺少翻译文件则安全回退到源文案。
"""

from __future__ import annotations

import gettext
import os
import logging
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

# ==================== 路径与默认配置 ====================
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCALE_DIR = REPO_ROOT / "services" / "telegram-service" / "locales"
logger = logging.getLogger(__name__)


def _has_bot_catalog(locale_dir: Path) -> bool:
    """检测目录下是否存在 bot.po/bot.mo。"""
    if not locale_dir.exists():
        return False
    for lang in ("zh_CN", "en"):
        lc = locale_dir / lang / "LC_MESSAGES"
        if (lc / "bot.po").exists() or (lc / "bot.mo").exists():
            return True
    return False


def _discover_locale_dir() -> Path:
    """自动发现 i18n 目录（仅在默认目录不可用时启用）。"""
    default = DEFAULT_LOCALE_DIR
    if _has_bot_catalog(default):
        return default
    candidates: set[Path] = set()
    for po in REPO_ROOT.rglob("bot.po"):
        parts = po.parts
        if "node_modules" in parts:
            continue
        if "libs" in parts and "external" in parts:
            continue
        if po.parent.name != "LC_MESSAGES":
            continue
        locale_dir = po.parents[2]
        candidates.add(locale_dir)
    # 优先找同时包含 zh_CN + en 的目录
    for locale_dir in sorted(candidates):
        if _has_bot_catalog(locale_dir):
            return locale_dir
    return default


def normalize_locale(lang: Optional[str]) -> Optional[str]:
    """标准化语言代码，形如 zh-CN / en -> zh_CN / en。

    - 兼容 Telegram 常见的 zh-Hans / zh-Hant / zh-TW / zh-HK 变体，统一折叠到 zh_CN / zh_TW。
    - 返回值用于 gettext 目录命名。
    """
    if not lang:
        return None
    code = lang.strip().replace("-", "_")
    if not code:
        return None

    lower = code.lower()
    # ---------- 中文变体兼容 ----------
    zh_cn_aliases = {"zh", "zh_cn", "zh_hans", "zh_cn_hans", "zh_hans_cn"}
    zh_tw_aliases = {"zh_tw", "zh_hant", "zh_hk", "zh_hant_tw", "zh_hant_hk"}
    if lower in zh_cn_aliases:
        return "zh_CN"
    if lower in zh_tw_aliases:
        return "zh_TW"

    parts = code.split("_", 1)
    if len(parts) == 1:
        return parts[0].lower()
    return f"{parts[0].lower()}_{parts[1].upper()}"


def parse_supported_locales(raw: Optional[str]) -> list[str]:
    """从环境变量解析支持的语言列表。"""
    if not raw:
        return []
    locales: list[str] = []
    for item in raw.split(","):
        norm = normalize_locale(item)
        if norm:
            locales.append(norm)
    return locales


class I18nService:
    """gettext 封装器"""

    def __init__(
        self,
        *,
        locale_dir: Path | str = DEFAULT_LOCALE_DIR,
        domain: str = "bot",
        default_locale: Optional[str] = "en",
        fallback_locale: Optional[str] = None,
        supported_locales: Optional[Iterable[str]] = None,
    ) -> None:
        self.locale_dir = Path(locale_dir)
        self.domain = domain
        self.default_locale = normalize_locale(default_locale) or "en"
        self.fallback_locale = normalize_locale(fallback_locale) or self.default_locale
        parsed = [normalize_locale(x) for x in (supported_locales or []) if normalize_locale(x)]
        self.supported_locales = parsed or [self.default_locale, "en"]
        self._missing_keys: set[tuple[str, str]] = set()

        if not self.locale_dir.exists():
            self.locale_dir.mkdir(parents=True, exist_ok=True)

    # ---------- 语言解析 ----------
    def resolve(self, lang: Optional[str]) -> str:
        """选择最合适的语言，不在列表则回退。

        兼容 zh-Hans/zh-Hant：若未显式支持该变体但存在 zh_CN/zh_TW，则优先回退到对应的中文翻译。
        """
        norm = normalize_locale(lang)
        if norm and norm in self.supported_locales:
            return norm
        # 优先为中文变体寻找最接近的翻译
        if norm and norm.startswith("zh"):
            if "zh_CN" in self.supported_locales:
                return "zh_CN"
            if "zh_TW" in self.supported_locales:
                return "zh_TW"
        return self.default_locale if self.default_locale in self.supported_locales else self.supported_locales[0]

    # ---------- 翻译对象 ----------
    @lru_cache(maxsize=16)
    def _translation(self, lang: str):
        return gettext.translation(
            self.domain,
            localedir=str(self.locale_dir),
            languages=[lang, self.fallback_locale],
            fallback=True,
        )

    def gettext(self, message_id: str, lang: Optional[str] = None, **kwargs) -> str:
        """获取翻译并格式化占位符。"""
        # 防护：检测调用方参数错误
        if not isinstance(message_id, str):
            import traceback
            logger.error("❌ I18nService.gettext 参数错误: message_id 不是字符串\n"
                        "  type=%s, value=%s\n调用栈:\n%s",
                        type(message_id).__name__, str(message_id)[:100],
                        ''.join(traceback.format_stack()[-8:-1]))
            return str(message_id)
        resolved = self.resolve(lang)
        text = self._translation(resolved).gettext(message_id)
        if text == message_id:
            # 只记录一次缺失键，避免日志风暴
            key = (resolved, message_id)
            if key not in self._missing_keys:
                self._missing_keys.add(key)
                logger.warning("⚠️ 缺失翻译键: lang=%s key=%s", resolved, message_id)
        if kwargs:
            try:
                return text.format(**kwargs)
            except Exception:
                return text
        return text

    def get_lazy(self, lang: Optional[str] = None):
        """返回局部绑定语言的 gettext 函数。"""
        def _inner(message_id: str, **kwargs):
            return self.gettext(message_id, lang=lang, **kwargs)

        return _inner


def build_i18n_from_env(locale_dir: Path | str = DEFAULT_LOCALE_DIR) -> I18nService:
    """按环境变量构造 I18nService。"""
    if Path(locale_dir) == DEFAULT_LOCALE_DIR:
        locale_dir = _discover_locale_dir()
    default_locale = os.getenv("DEFAULT_LOCALE", "en")
    fallback_locale = os.getenv("FALLBACK_LOCALE", default_locale)
    supported_locales = parse_supported_locales(os.getenv("SUPPORTED_LOCALES", "zh-CN,en"))
    return I18nService(
        locale_dir=locale_dir,
        domain="bot",
        default_locale=default_locale,
        fallback_locale=fallback_locale,
        supported_locales=supported_locales,
    )


__all__ = [
    "I18nService",
    "build_i18n_from_env",
    "normalize_locale",
    "parse_supported_locales",
]
