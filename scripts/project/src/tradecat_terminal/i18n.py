from __future__ import annotations

import locale
import os
from typing import Any

SUPPORTED_LANGS = ("zh", "en", "ko")
DEFAULT_LANG = "zh"
LANG_ENV = "TRADECAT_LANG"

_ALIASES = {
    "zh": "zh",
    "zh_cn": "zh",
    "zh_hans": "zh",
    "cn": "zh",
    "chinese": "zh",
    "中文": "zh",
    "en": "en",
    "en_us": "en",
    "english": "en",
    "ko": "ko",
    "kr": "ko",
    "ko_kr": "ko",
    "korean": "ko",
    "한국어": "ko",
}

MESSAGES: dict[str, dict[str, str]] = {
    "zh": {
        "app_title": "TradeCat",
        "notice_prefix": "提示",
        "plain_fallback": "已自动切换为 Rich 静态文本模式；不使用 psql 边框，避免 Windows/Web 终端换行错位。",
        "cache_label": "cache",
        "current_label": "current",
        "empty_cache_plain": "暂无本地快照缓存，请执行：tradecat sync event_stream 或 tradecat",
        "mode_live": "实时",
        "mode_history": "历史",
        "controls": (
            "<-/-> 切换 tap | up/down 快照/事件 | PgUp/PgDn 翻行 | "
            "/ 搜索 | x 清除 | g/G 首尾 | n/p 选行 | Enter/o 打开链接/交易对 | r 刷新 | ? 帮助 | "
            "l 切换语言 / Switch language / 언어 전환: 中文/English/한국어 | q 退出"
        ),
        "stream_status": "mode=stream | row={row_scroll} | probe={probe}",
        "batch_status": "batch {batch_index}/{batch_count}: {batch_label} | probe={probe}",
        "no_cache": "无缓存",
        "error_label": "error",
        "open_label": "open",
        "empty_cache_curses": "暂无本地快照缓存；按 r 拉取当前 tap，或执行 tradecat sync-all。",
        "force_plain_reason": "已按 TRADECAT_TERMINAL_FORCE_PLAIN=1 使用静态文本模式",
        "windows_plain_reason": "Windows 原生终端的 curses 渲染不稳定",
        "ssh_plain_reason": "远程 Web/SSH 终端的 curses 宽字符渲染不稳定",
        "no_curses_reason": "当前 Python 环境不支持 curses",
        "curses_failed_reason": "交互式 TUI 渲染失败：{error}",
        "pause_after_fallback": "当前终端已进入静态兼容模式；按 Enter 退出。",
        "lang_zh": "中文",
        "lang_en": "English",
        "lang_ko": "한국어",
    },
    "en": {
        "app_title": "TradeCat",
        "notice_prefix": "Notice",
        "plain_fallback": "Switched to Rich static text mode; psql borders are disabled for stable Windows/Web terminal output.",
        "cache_label": "cache",
        "current_label": "current",
        "empty_cache_plain": "No local snapshot cache. Run: tradecat sync event_stream or tradecat",
        "mode_live": "live",
        "mode_history": "history",
        "controls": (
            "<-/-> switch tap | up/down snapshot/event | PgUp/PgDn page | "
            "/ search | x clear | g/G top/end | n/p select | Enter/o open link/symbol | r refresh | ? help | "
            "l 切换语言 / Switch language / 언어 전환: 中文/English/한국어 | q quit"
        ),
        "stream_status": "mode=stream | row={row_scroll} | probe={probe}",
        "batch_status": "batch {batch_index}/{batch_count}: {batch_label} | probe={probe}",
        "no_cache": "no cache",
        "error_label": "error",
        "open_label": "open",
        "empty_cache_curses": "No local snapshot cache. Press r to fetch current tap, or run tradecat sync-all.",
        "force_plain_reason": "Using static text mode because TRADECAT_TERMINAL_FORCE_PLAIN=1 is set",
        "windows_plain_reason": "Native Windows terminal has unstable curses wide-character rendering",
        "ssh_plain_reason": "Remote Web/SSH terminal has unstable curses wide-character rendering",
        "no_curses_reason": "Current Python runtime does not support curses",
        "curses_failed_reason": "Interactive TUI rendering failed: {error}",
        "pause_after_fallback": "Static compatibility mode is active; press Enter to exit.",
        "lang_zh": "中文",
        "lang_en": "English",
        "lang_ko": "한국어",
    },
    "ko": {
        "app_title": "TradeCat",
        "notice_prefix": "알림",
        "plain_fallback": "Rich 정적 텍스트 모드로 전환했습니다. Windows/Web 터미널 안정성을 위해 psql 테두리를 사용하지 않습니다.",
        "cache_label": "cache",
        "current_label": "current",
        "empty_cache_plain": "로컬 스냅샷 캐시가 없습니다. 실행: tradecat sync event_stream 또는 tradecat",
        "mode_live": "실시간",
        "mode_history": "히스토리",
        "controls": (
            "<-/-> 탭 전환 | up/down 스냅샷/이벤트 | PgUp/PgDn 페이지 | "
            "/ 검색 | x 지우기 | g/G 처음/끝 | n/p 선택 | Enter/o 링크/거래쌍 열기 | r 새로고침 | ? 도움말 | "
            "l 切换语言 / Switch language / 언어 전환: 中文/English/한국어 | q 종료"
        ),
        "stream_status": "mode=stream | row={row_scroll} | probe={probe}",
        "batch_status": "batch {batch_index}/{batch_count}: {batch_label} | probe={probe}",
        "no_cache": "캐시 없음",
        "error_label": "error",
        "open_label": "open",
        "empty_cache_curses": "로컬 스냅샷 캐시가 없습니다. r을 눌러 현재 탭을 가져오거나 tradecat sync-all을 실행하세요.",
        "force_plain_reason": "TRADECAT_TERMINAL_FORCE_PLAIN=1 설정에 따라 정적 텍스트 모드를 사용합니다",
        "windows_plain_reason": "Windows 기본 터미널은 curses 와이드 문자 렌더링이 불안정합니다",
        "ssh_plain_reason": "원격 Web/SSH 터미널은 curses 와이드 문자 렌더링이 불안정합니다",
        "no_curses_reason": "현재 Python 환경은 curses를 지원하지 않습니다",
        "curses_failed_reason": "대화형 TUI 렌더링 실패: {error}",
        "pause_after_fallback": "정적 호환 모드입니다. Enter를 누르면 종료합니다.",
        "lang_zh": "中文",
        "lang_en": "English",
        "lang_ko": "한국어",
    },
}


def normalize_lang(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower().replace("-", "_").split(".", maxsplit=1)[0]
    if not normalized:
        return None
    if normalized in _ALIASES:
        return _ALIASES[normalized]
    prefix = normalized.split("_", maxsplit=1)[0]
    return prefix if prefix in SUPPORTED_LANGS else None


def resolve_lang(value: str | None = None) -> str:
    direct = normalize_lang(value)
    if direct:
        return direct
    env_lang = normalize_lang(os.environ.get(LANG_ENV))
    if env_lang:
        return env_lang
    locale_lang = normalize_lang(locale.getlocale()[0])
    if locale_lang:
        return locale_lang
    return DEFAULT_LANG


def cycle_lang(value: str | None) -> str:
    current = resolve_lang(value)
    index = SUPPORTED_LANGS.index(current)
    return SUPPORTED_LANGS[(index + 1) % len(SUPPORTED_LANGS)]


def lang_label(value: str | None, *, lang: str | None = None) -> str:
    target = resolve_lang(value)
    display_lang = resolve_lang(lang)
    return tr(display_lang, f"lang_{target}")


def tr(lang: str | None, key: str, **kwargs: Any) -> str:
    resolved = resolve_lang(lang)
    template = MESSAGES.get(resolved, MESSAGES[DEFAULT_LANG]).get(key, MESSAGES[DEFAULT_LANG].get(key, key))
    return template.format(**kwargs) if kwargs else template
