#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tradecat 加密市场情报机器人
"""

import os
import sys
import asyncio
import logging
import time
import json
import threading
import unicodedata
import re

# 提前初始化 logger
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional
# 当前位置 bot/app.py，需要上移一层回到 src 作为根
SRC_ROOT = Path(__file__).resolve().parent.parent  # .../src
PROJECT_ROOT = SRC_ROOT.parent                    # .../telegram-service
REPO_ROOT = PROJECT_ROOT.parents[2]               # 顶层项目根目录（tradecat/）
REPO_SRC_ROOT = REPO_ROOT                         # 兼容旧变量名：用于补齐 sys.path
ASSETS_DIR = PROJECT_ROOT / "assets"
ANIMATION_DIR = ASSETS_DIR / "animations"
LOCALE_STORE = PROJECT_ROOT / "data" / "user_locale.json"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(REPO_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_SRC_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ================== 提前加载 .env（必须在 cards 导入前）==================
# cards/i18n.py 在导入时会初始化 I18N，需要先加载环境变量
_ENV_FILE = REPO_ROOT / "assets" / "config" / ".env"
if not _ENV_FILE.exists():
    _ENV_FILE = REPO_ROOT / "config" / ".env"  # legacy（只读）
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _key, _val = _line.split("=", 1)
        if _key and _key not in os.environ:
            os.environ[_key] = _val

# 延后导入依赖于 sys.path 的模块
from assets.common.i18n import build_i18n_from_env

# 当以脚本方式运行时，显式注册模块别名
if __name__ == "__main__":
    sys.modules.setdefault("main", sys.modules[__name__])

from cards import RankingRegistry

# ==== 数据库指标服务（可选） ==============================================
# 前端仅消费本地 CSV/SQLite 时不需要连接 Postgres/Timescale。
# 为避免未安装 psycopg 导致启动失败，这里使用安全降级导入。
try:  # noqa: SIM105
    from services.币安数据库指标服务 import 币安数据库指标服务 as _MetricService
except Exception as exc:  # pragma: no cover - 环境缺依赖时降级
    _MetricService = None
    logger.warning("⚠️ 已禁用数据库指标服务（未安装 psycopg 或不需要PG）: %s", exc)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ChatAction
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,  # 用于在禁用场景下阻断后续命令处理
)
from telegram.error import BadRequest

# ================== 本地 .env 加载 ==================
ENV_FILE = REPO_ROOT / "assets" / "config" / ".env"
if not ENV_FILE.exists():
    ENV_FILE = REPO_ROOT / "config" / ".env"  # legacy（只读）


def _load_env_file(env_path: Path) -> None:
    """简易 .env 解析：KEY=VALUE，忽略已存在的环境变量。"""
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        if key and key not in os.environ:
            os.environ[key] = val


_load_env_file(ENV_FILE)


def _require_env(name: str, default=None, required: bool = False, cast=None):
    """获取必需/可选环境变量，可选类型转换。"""
    val = os.getenv(name, default)
    if required and (val is None or val == ""):
        raise RuntimeError(f"环境变量 {name} 未设置，请在 .env 中配置")
    if cast and val is not None and val != "":
        try:
            val = cast(val)
        except Exception as exc:  # pragma: no cover - 配置错误即抛
            raise RuntimeError(f"环境变量 {name} 解析失败: {exc}") from exc
    return val


# ================== i18n 支撑 ==================
I18N = build_i18n_from_env()
_user_locale_map: Dict[int, str] = {}
_user_locale_lock = threading.RLock()


def _ensure_locale_store():
    """确保语言偏好存储目录存在"""
    try:
        LOCALE_STORE.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _load_user_locales():
    """加载已存储的用户语言偏好"""
    global _user_locale_map
    with _user_locale_lock:
        if _user_locale_map:
            return _user_locale_map
        if not LOCALE_STORE.exists():
            _user_locale_map = {}
            return _user_locale_map
        try:
            _user_locale_map = json.loads(LOCALE_STORE.read_text(encoding="utf-8"))
        except Exception:
            _user_locale_map = {}
        return _user_locale_map


def _save_user_locale(user_id: int, lang: str):
    """持久化用户语言"""
    _ensure_locale_store()
    with _user_locale_lock:
        data = _load_user_locales()
        data[str(user_id)] = lang
        try:
            tmp_path = LOCALE_STORE.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp_path, LOCALE_STORE)
            _user_locale_map = data  # 刷新内存缓存
        except Exception as exc:
            logger.warning("⚠️ 保存用户语言失败: %s", exc)


def _resolve_lang(update) -> str:
    """解析用户语言：显式设置 > Telegram 语言码 > 默认"""
    _load_user_locales()
    user_id = getattr(getattr(update, "effective_user", None), "id", None)
    if user_id is not None:
        lang = _user_locale_map.get(str(user_id))
        if lang:
            return I18N.resolve(lang)
    tg_lang = getattr(getattr(update, "effective_user", None), "language_code", None)
    if tg_lang:
        return I18N.resolve(tg_lang)
    return I18N.resolve(None)


def _t(update, message_id: str, fallback: str | None = None, **kwargs) -> str:
    """获取带语言的翻译（支持 fallback）"""
    lang = _resolve_lang(update)
    try:
        text = I18N.gettext(message_id, lang=lang, **kwargs)
    except Exception as exc:  # pragma: no cover - 防御性兜底
        logger.error("获取翻译失败: lang=%s key=%s err=%s", lang, message_id, exc)
        return fallback or message_id
    if not text or text == message_id:
        return fallback or message_id
    return text


# ==================== 币种解析（允许中文符号） ====================
_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9]{2,15}")
_CJK_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{1,12}")


def _normalize_symbol_ascii(raw: str) -> Optional[str]:
    """规范化英文币种符号，返回不含 USDT 的大写结果。"""
    if not raw:
        return None
    cleaned = re.sub(r"[\\s/\\-_:]+", "", raw).upper()
    if not cleaned:
        return None
    if cleaned.endswith("USDT"):
        cleaned = cleaned[:-4]
    return cleaned if _ASCII_TOKEN_RE.fullmatch(cleaned) else None


def _build_allowed_symbol_sets(user_handler) -> tuple[set[str], set[str]]:
    """构建允许的币种集合（原始 + 基础币种），用于过滤中文误触发。"""
    if not user_handler:
        return set(), set()
    try:
        symbols = user_handler.get_active_symbols() or []
    except Exception:
        return set(), set()
    raw_set: set[str] = set()
    base_set: set[str] = set()
    for item in symbols:
        s = str(item).strip()
        if not s:
            continue
        raw_set.add(s)
        upper = s.upper()
        base_set.add(upper)
        base_set.add(upper.replace("USDT", ""))
    return raw_set, base_set


def _resolve_symbol_input(raw: str, *, allowed_raw: set[str] | None = None,
                          allowed_base: set[str] | None = None) -> Optional[str]:
    """解析输入为币种代码，支持中文符号，必要时校验是否在允许列表内。"""
    if not raw:
        return None
    raw = str(raw).strip()
    if not raw:
        return None

    # 中文币种：直接按原样匹配（不做别名映射）
    if _CJK_TOKEN_RE.search(raw):
        sym = re.sub(r"\\s+", "", raw)
        if not sym:
            return None
        if allowed_raw or allowed_base:
            if sym in (allowed_raw or set()):
                return sym
            if sym in (allowed_base or set()):
                return sym
            if f"{sym}USDT" in (allowed_raw or set()):
                return sym
            return None
        return sym

    # 英文/数字币种
    sym = _normalize_symbol_ascii(raw)
    if not sym:
        return None
    if allowed_raw or allowed_base:
        if sym in (allowed_base or set()):
            return sym
        if sym in (allowed_raw or set()):
            return sym
        if f"{sym}USDT" in (allowed_raw or set()):
            return sym
        return None
    return sym


def _extract_symbol_token(text: str, *, double_exclaim: bool) -> Optional[str]:
    """从文本中提取币种候选词（英文或中文）。"""
    if not text:
        return None
    if double_exclaim:
        pattern = r"([A-Za-z0-9]{2,15}|[\u4e00-\u9fff]{1,12})\\s*[!！]{2}"
    else:
        pattern = r"([A-Za-z0-9]{2,15}|[\u4e00-\u9fff]{1,12})\\s*[!！](?![!！])"
    m = re.search(pattern, text)
    if m:
        return m.group(1)
    tokens = _ASCII_TOKEN_RE.findall(text)
    if tokens:
        return tokens[0]
    m = _CJK_TOKEN_RE.search(text)
    if m:
        return m.group(0)
    return None


def _extract_symbol_at_token(text: str, *, double_at: bool) -> Optional[str]:
    """从文本中提取 @@ 触发的币种候选词（英文或中文）。"""
    if not text:
        return None
    if double_at:
        pattern = r"([A-Za-z0-9]{2,15}|[\u4e00-\u9fff]{1,12})\\s*[@＠]{2}"
    else:
        pattern = r"([A-Za-z0-9]{2,15}|[\u4e00-\u9fff]{1,12})\\s*[@＠](?![@＠])"
    m = re.search(pattern, text)
    if m:
        return m.group(1)
    tokens = _ASCII_TOKEN_RE.findall(text)
    if tokens:
        return tokens[0]
    m = _CJK_TOKEN_RE.search(text)
    if m:
        return m.group(0)
    return None


def _btn(update, key: str, callback: str, active: bool = False, prefix: str = "✅") -> InlineKeyboardButton:
    """国际化按钮工厂"""
    text = _t(update, key)
    if not text:
        text = key
    if active:
        text = prefix + text
    return InlineKeyboardButton(text, callback_data=callback)


def _btn_lang(lang: str, key: str, callback: str, active: bool = False, prefix: str = "✅") -> InlineKeyboardButton:
    """按语言代码创建按钮（无update时使用）"""
    text = I18N.gettext(key, lang=lang)
    if not text:
        text = key
    if active:
        text = prefix + text
    return InlineKeyboardButton(text, callback_data=callback)


def _sort_text(update, order: str) -> str:
    """获取排序文本"""
    key = "btn.desc" if order == "desc" else "btn.asc"
    return _t(update, key) if update else I18N.gettext(key, lang=I18N.default_locale)


def _sort_text_lang(lang: str, order: str) -> str:
    """按语言获取排序文本"""
    key = "btn.desc" if order == "desc" else "btn.asc"
    return I18N.gettext(key, lang=lang)


def _period_text(update, period: str) -> str:
    """按语言获取周期展示文本，找不到则回退原始值"""
    lang = _resolve_lang(update) if update else I18N.default_locale
    key = f"period.{period}"
    text = I18N.gettext(key, lang=lang)
    if text == key:
        logger.warning("⚠️ 周期翻译缺失，回退原值: lang=%s key=%s", lang, key)
        return period
    return text


def _period_text_lang(lang: str, period: str) -> str:
    """按给定语言获取周期文本，找不到则回退原始值"""
    key = f"period.{period}"
    text = I18N.gettext(key, lang=lang)
    if text == key:
        logger.warning("⚠️ 周期翻译缺失，回退原值: lang=%s key=%s", lang, key)
        return period
    return text

# 统一 sys.path 优先级：本服务 src 放最前，并移除不存在的占位路径
sys.path = [p for p in sys.path if p != str(SRC_ROOT)]
sys.path.insert(0, str(SRC_ROOT))
sys.path = [p for p in sys.path if not (p.endswith('/src') and not Path(p).exists())]


# 数据库指标服务（可选）
BINANCE_DB_METRIC_SERVICE = None

# ================== 权限检查 ==================

# 管理员用户ID列表（从环境变量加载）
ADMIN_USER_IDS: set = set()


def _load_admin_ids():
    """从环境变量加载管理员ID"""
    global ADMIN_USER_IDS
    admin_str = os.getenv("ADMIN_USER_IDS", "")
    if admin_str:
        try:
            ADMIN_USER_IDS = {int(uid.strip()) for uid in admin_str.split(",") if uid.strip().isdigit()}
            logger.info(f"已加载管理员ID: {ADMIN_USER_IDS}")
        except Exception as e:
            logger.error(f"解析 ADMIN_USER_IDS 失败: {e}")
            ADMIN_USER_IDS = set()


# 启动时加载管理员ID
_load_admin_ids()


def _is_admin(update) -> bool:
    """检查用户是否为管理员"""
    if not update:
        return False
    user_id = None
    if hasattr(update, 'callback_query') and update.callback_query:
        user_id = update.callback_query.from_user.id
    elif hasattr(update, 'message') and update.message:
        user_id = update.message.from_user.id
    return user_id in ADMIN_USER_IDS if user_id else False


def _get_user_id(update) -> Optional[int]:
    """获取用户ID"""
    if not update:
        return None
    if hasattr(update, 'callback_query') and update.callback_query:
        return update.callback_query.from_user.id
    elif hasattr(update, 'message') and update.message:
        return update.message.from_user.id
    return None


_GROUP_ALLOWED_PREFIXES = ("/", "!")
_GROUP_WHITELIST: set[int] = set()
_GROUP_REQUIRE_MENTION = True

BOT_USERNAME = os.getenv("BOT_USERNAME", "").lstrip("@").lower()
BOT_USER_ID: Optional[int] = None


def _parse_int_list(raw: str) -> set[int]:
    ids: set[int] = set()
    for item in (raw or "").split(","):
        token = item.strip()
        if not token:
            continue
        try:
            ids.add(int(token))
        except ValueError:
            logger.warning("群聊白名单ID非法: %s", token)
    return ids


def _load_group_whitelist() -> None:
    """加载群聊白名单（逗号分隔，群ID通常为负数）"""
    global _GROUP_WHITELIST
    raw = os.getenv("TELEGRAM_GROUP_WHITELIST") or os.getenv("TG_GROUP_WHITELIST") or ""
    _GROUP_WHITELIST = _parse_int_list(raw)
    if _GROUP_WHITELIST:
        logger.info("✅ 已加载群聊白名单: %s", sorted(_GROUP_WHITELIST))
    else:
        logger.warning("⚠️ 未配置 TELEGRAM_GROUP_WHITELIST，群聊消息将被忽略")


_load_group_whitelist()


def _get_update_message(update):
    if not update:
        return None
    if hasattr(update, "message") and update.message:
        return update.message
    if hasattr(update, "callback_query") and update.callback_query and update.callback_query.message:
        return update.callback_query.message
    return None


def _message_mentions_bot(message) -> bool:
    if not message:
        return False
    text = (message.text or message.caption or "").lower()

    if BOT_USER_ID and getattr(message, "reply_to_message", None):
        reply_user = message.reply_to_message.from_user if message.reply_to_message else None
        if reply_user and reply_user.id == BOT_USER_ID:
            return True

    if getattr(message, "entities", None):
        for ent in message.entities:
            if ent.type == "text_mention" and ent.user and BOT_USER_ID and ent.user.id == BOT_USER_ID:
                return True
            if BOT_USERNAME and ent.type in ("mention", "bot_command"):
                part = text[ent.offset: ent.offset + ent.length]
                if f"@{BOT_USERNAME}" in part:
                    return True

    if BOT_USERNAME and f"@{BOT_USERNAME}" in text:
        return True

    return False


def _is_command_allowed(update) -> bool:
    """群聊安全: 白名单 + 前缀 + @提及，私聊默认允许"""
    message = _get_update_message(update)
    if not message or not getattr(message, "chat", None):
        return False

    chat = message.chat
    chat_type = getattr(chat, "type", "")

    if chat_type == "private":
        return True

    if chat_type not in ("group", "supergroup"):
        return False

    # ===== 群聊放宽策略 =====
    # 只要是显式命令（/、! 前缀或 bot_command 实体）或回调查询，一律放行，便于群内直接使用
    text = (message.text or message.caption or "")
    has_command_prefix = bool(text) and text.lstrip().startswith(_GROUP_ALLOWED_PREFIXES)
    has_bot_command_entity = any(
        getattr(ent, "type", "") == "bot_command" for ent in (getattr(message, "entities", None) or [])
    )
    is_callback = getattr(update, "callback_query", None) is not None
    if has_command_prefix or has_bot_command_entity or is_callback:
        return True

    # 其他非命令消息仍按原有白名单+@ 提及约束
    if not _GROUP_WHITELIST or chat.id not in _GROUP_WHITELIST:
        return False
    if _GROUP_REQUIRE_MENTION and not _message_mentions_bot(message):
        return False
    return True


async def _refresh_bot_identity(application) -> None:
    """缓存 Bot 用户名与ID，用于群聊 @ 提及识别"""
    global BOT_USERNAME, BOT_USER_ID
    try:
        me = await application.bot.get_me()
        BOT_USERNAME = (me.username or "").lstrip("@").lower()
        BOT_USER_ID = me.id
        if BOT_USERNAME:
            logger.info("✅ Bot身份已确认: @%s (%s)", BOT_USERNAME, BOT_USER_ID)
        else:
            logger.warning("⚠️ Bot用户名为空，群聊 @ 提及识别可能受限")
    except Exception as exc:
        logger.warning("⚠️ 获取Bot身份失败: %s", exc)

async def send_help_message(update_or_query, context, *, via_query: bool = False):
    """发送帮助消息"""
    help_text = _t(update_or_query, "help.body")
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(_t(update_or_query, "menu.home"), callback_data="main_menu"),
            InlineKeyboardButton(_t(update_or_query, "menu.data"), callback_data="ranking_menu"),
        ]
    ])

    try:
        if via_query and hasattr(update_or_query, 'callback_query'):
            await update_or_query.callback_query.edit_message_text(help_text, reply_markup=keyboard, parse_mode='Markdown')
        elif hasattr(update_or_query, 'message') and update_or_query.message:
            await update_or_query.message.reply_text(help_text, reply_markup=keyboard, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"发送帮助消息失败: {e}")

def _ensure_ranking_sys_path():
    """保障排行榜卡片依赖路径完整，避免注册表为空"""
    added_paths = []
    for path in (REPO_ROOT, REPO_SRC_ROOT, SRC_ROOT):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
            added_paths.append(str(path))
    if added_paths:
        logger.info("🔧 已补充排行榜依赖路径: %s", added_paths)

# 全局排行榜注册表
ranking_registry = None

def ensure_ranking_registry() -> Optional[RankingRegistry]:
    """惰性初始化排行榜卡片注册表"""
    global ranking_registry
    if ranking_registry is not None:
        return ranking_registry

    try:
        _ensure_ranking_sys_path()
        registry = RankingRegistry("cards")
        registry.load_cards()
        if registry.card_count() == 0:
            logger.warning("⚠️ 排行榜卡片注册表为空，触发路径修复后重载")
            registry.load_cards()
        if registry.card_count() == 0:
            raise RuntimeError("排行榜卡片注册表为空，初始化失败")
        ranking_registry = registry
        logger.info("✅ 排行榜卡片注册表初始化完成，共 %d 个卡片", registry.card_count())
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("❌ 初始化排行榜卡片注册表失败: %s", exc)
        ranking_registry = None
    return ranking_registry

# 用户数据保护相关函数已移除，直接使用DataManager

# 北京时间工具函数
def get_beijing_time():
    """获取北京时间"""
    beijing_tz = timezone(timedelta(hours=8))
    return datetime.now(beijing_tz)

def beijing_time_isoformat():
    """获取北京时间的ISO格式字符串"""
    return get_beijing_time().isoformat()

def format_beijing_time(dt_str, format_str="%Y-%m-%d %H:%M:%S"):
    """将ISO格式的时间字符串转换为北京时间并格式化"""
    try:
        # 如果输入的是ISO格式字符串，先解析
        if isinstance(dt_str, str):
            dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        else:
            dt = dt_str

        # 如果没有时区信息，假设是UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        # 转换为北京时间
        beijing_tz = timezone(timedelta(hours=8))
        beijing_dt = dt.astimezone(beijing_tz)

        return beijing_dt.strftime(format_str)
    except Exception as e:
        logger.error(f"时间格式化失败: {e}")
        return str(dt_str)


# 配置（全部改由环境变量管理）
BOT_TOKEN = _require_env('BOT_TOKEN', required=True)
# Binance API 已废弃，数据由 data-service 采集
BINANCE_API_DISABLED = True  # 强制禁用

# 屏蔽币种（动态获取，支持热更新）
def get_blocked_symbols() -> set:
    """动态获取屏蔽币种（支持热更新）"""
    blocked_str = os.environ.get('BLOCKED_SYMBOLS', 'BNXUSDT,ALPACAUSDT')
    return set(s.strip().upper() for s in blocked_str.split(',') if s.strip())

# 保留全局变量用于向后兼容，但建议使用 get_blocked_symbols()
BLOCKED_SYMBOLS = get_blocked_symbols()

# 🔁 策略扫描脚本路径（用于定时刷新 CSV 榜单）

# 数据文件配置 - 使用项目根目录下的data文件夹
BASE_DIR = str(PROJECT_ROOT)
DATA_DIR = os.path.join(BASE_DIR, "data")  # 数据目录
CACHE_DIR = os.path.join(DATA_DIR, "cache")  # 缓存目录

# 确保数据目录存在
os.makedirs(DATA_DIR, exist_ok=True)

# 全局缓存
cache = {}
CACHE_DURATION = 60
CACHE_FILE_PRIMARY = os.path.join(CACHE_DIR, 'cache_data_primary.json')
CACHE_FILE_SECONDARY = os.path.join(CACHE_DIR, 'cache_data_secondary.json')

# 全局机器人实例
bot = None
user_handler = None
_user_handler_init_task = None
APP_LOOP = None


async def _trigger_user_handler_init() -> None:
    """触发 user_handler 懒初始化，避免首次请求无响应"""
    global _user_handler_init_task
    if user_handler is not None and bot is not None:
        return
    if _user_handler_init_task is not None and not _user_handler_init_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()
    logger.info("⚙️ 触发 user_handler 懒初始化")
    _user_handler_init_task = loop.run_in_executor(None, initialize_bot_sync)

# 全局点击限制器
_user_click_timestamps = {}
CLICK_COOLDOWN_SECONDS = 0.1

def check_click_rate_limit(user_id: int, button_data: str = "", is_ai_feature: bool = False) -> tuple[bool, float]:
    """

    Args:
        user_id: 用户ID
        button_data: 按钮回调数据（保留兼容性）
        is_ai_feature: 是否为AI功能（保留兼容性）

    Returns:
        tuple: (是否允许点击, 剩余冷却时间)
    """
    import time
    current_time = time.time()

    if user_id in _user_click_timestamps:
        last_click_time = _user_click_timestamps[user_id]
        time_since_last_click = current_time - last_click_time

        if time_since_last_click < CLICK_COOLDOWN_SECONDS:
            remaining_cooldown = CLICK_COOLDOWN_SECONDS - time_since_last_click
            return False, remaining_cooldown

    # 更新最后点击时间
    _user_click_timestamps[user_id] = current_time
    return True, 0.0

# ==================== 单币快照辅助 ====================
def _get_binance_web_base() -> str:
    return (os.getenv("BINANCE_WEB_BASE") or "").strip().rstrip("/")


def _build_binance_url(symbol: str, market: str = "futures") -> str:
    """构造 Binance 跳转链接，默认永续合约。"""
    web_base = _get_binance_web_base()
    sym = (symbol or "").upper().replace("/", "")
    if not sym.endswith("USDT"):
        sym = f"{sym}USDT"
    if market == "spot":
        base = sym.replace("USDT", "_USDT", 1)
        path = f"/en/trade/{base}?type=spot"
    else:
        path = f"/en/futures/{sym}?type=perpetual"
    return f"{web_base}{path}" if web_base else path


def build_single_snapshot_keyboard(enabled_periods: dict, panel: str, enabled_cards: dict, page: int = 0, pages: int = 1, update=None, lang: str = None, symbol: str | None = None):
    """构造单币快照按钮：卡片开关/周期开关/面板切换/主控+翻页。"""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    try:
        from bot.single_token_snapshot import ALL_PERIODS, TABLE_FIELDS
    except Exception:
        ALL_PERIODS = ("1m", "5m", "15m", "1h", "4h", "1d", "1w")
        TABLE_FIELDS = {}

    # 行0：卡片开关
    row_cards: list[list[InlineKeyboardButton]] = []

    def _clean(name: str) -> str:
        n = name.replace("排行卡片", "").replace("卡片", "").replace("榜单", "").replace(".py", "")
        # 特例精简
        n = n.replace("MACD柱状", "MACD")
        n = n.replace("OBV能量潮", "OBV")
        n = n.replace("随机指标", "")  # KDJ随机指标 -> KDJ
        n = n.replace("资金费率", "费率")
        n = n.replace("资金流向", "流向")
        n = n.replace("情绪分歧", "分歧")
        n = n.replace("情绪动量", "动量")
        n = n.replace("全市场情绪", "全市场")
        n = n.replace("大户情绪", "大户")
        n = n.replace("期货持仓情绪", "持仓情绪")
        n = n.replace("持仓增减速", "持仓变速")
        n = n.replace("风险拥挤度", "拥挤度")
        n = n.replace("翻转雷达", "翻雷达")
        n = n.replace("新鲜度告警", "新鲜度")
        n = n.replace("波动度", "波动")
        n = n.replace("超级精准趋势", "精趋势")
        n = n.replace("流动性", "流动")
        n = n.replace("趋势线", "线")
        return n

    # 卡片名称翻译映射
    CARD_NAME_MAP = {
        "成交量比率": "card.name.vol_ratio",
        "主动买卖比": "card.name.taker_ratio",
        "支撑阻力": "card.name.support_resistance",
        "RSI谐波": "card.name.rsi_harmonic",
        "布林带": "card.name.bollinger",
        "MACD": "card.name.macd",
        "KDJ": "card.name.kdj",
        "OBV": "card.name.obv",
        "EMA": "card.name.ema",
        "ATR": "card.name.atr",
        "CVD": "card.name.cvd",
        "VWAP": "card.name.vwap",
        "VPVR": "card.name.vpvr",
        "流动": "card.name.liquidity",
        "线": "card.name.trendline",
        "精趋势": "card.name.supertrend",
        "MFI": "card.name.mfi",
        "K线形态": "card.name.k_pattern",
        "持仓数据": "card.name.position",
        "大户": "card.name.big_sentiment",
        "全市场": "card.name.all_sentiment",
        "主动成交": "card.name.taker",
        "情绪综合": "card.name.sentiment",
    }

    def _translate_card_name(name: str, lang: str) -> str:
        key = CARD_NAME_MAP.get(name)
        if key:
            return I18N.gettext(key, lang=lang)
        return name

    def _layout(labels, max_w=35):
        # 宽度优先排布：先按宽度降序，再贪心铺行
        def disp_width(s: str) -> int:
            from bot.single_token_snapshot import _disp_width
            return _disp_width(s)

        items = [(lab, disp_width(lab)) for lab in labels]
        items.sort(key=lambda x: -x[1])
        rows = []
        cur = []
        w = 0
        for lab, lw in items:
            if cur and w + 1 + lw > max_w:
                rows.append(cur)
                cur = [lab]
                w = lw
            else:
                if cur:
                    w += 1 + lw
                else:
                    w = lw
                cur.append(lab)
        if cur:
            rows.append(cur)
        return rows

    tables = [t for t in TABLE_FIELDS.get(panel, {}).keys()]
    # 自适应分行（期货面板已精简为分组名，无需过滤）
    # 优先使用传入的 lang 参数，其次从 update 解析，最后回退默认
    if not lang:
        lang = _resolve_lang(update) if update else I18N.default_locale
    layout_rows = _layout([_clean(t) for t in tables], max_w=22)
    for row_labels in layout_rows:
        row: list[InlineKeyboardButton] = []
        for lab in row_labels:
            # 找回原始 key
            for t in tables:
                if _clean(t) == lab:
                    key = t
                    break
            else:
                key = lab
            on = enabled_cards.get(key, True)
            # 翻译卡片名称
            translated_lab = _translate_card_name(lab, lang)
            label = translated_lab if on else f"❎{translated_lab}"
            row.append(InlineKeyboardButton(label, callback_data=f"single_card_{key}"))
        row_cards.append(row)

    row_period: list[InlineKeyboardButton] = []
    for p in ALL_PERIODS:
        period_label = I18N.gettext(f"period.{p}", lang=lang)
        if period_label == f"period.{p}":
            period_label = p
        label = f"❎{period_label}" if not enabled_periods.get(p, False) else period_label
        data = f"single_toggle_{p}"
        # 合约面板不允许1m，禁用按钮
        if panel == "futures" and p == "1m":
            row_period.append(InlineKeyboardButton(f"❎{period_label}", callback_data="single_nop"))
            continue
        row_period.append(InlineKeyboardButton(label, callback_data=data))

    # 面板按钮使用i18n (lang 已在上面定义)
    def panel_btn(key: str, code: str):
        active = (panel == code)
        text = I18N.gettext(key, lang=lang)
        label = f"✅{text}" if active else text
        return InlineKeyboardButton(label, callback_data=f"single_panel_{code}")

    row_panel = [
        panel_btn("panel.basic", "basic"),
        panel_btn("panel.futures", "futures"),
        panel_btn("panel.advanced", "advanced"),
        InlineKeyboardButton(I18N.gettext("panel.pattern", lang=lang), callback_data="single_panel_pattern"),
    ]
    # 主控行：返回主菜单 / 刷新 / 下一页 / 上一页（无则省略按钮）
    row_ctrl: list[InlineKeyboardButton] = []
    row_ctrl.append(InlineKeyboardButton(I18N.gettext("btn.back_home", lang=lang), callback_data="main_menu"))
    row_ctrl.append(InlineKeyboardButton(I18N.gettext("btn.refresh", lang=lang), callback_data="single_refresh"))
    if pages > 1 and page < pages - 1:
        row_ctrl.append(InlineKeyboardButton(I18N.gettext("btn.next_page", lang=lang), callback_data="single_page_next"))
    if pages > 1 and page > 0:
        row_ctrl.append(InlineKeyboardButton(I18N.gettext("btn.prev_page", lang=lang), callback_data="single_page_prev"))

    kb_rows: list[list[InlineKeyboardButton]] = []
    if row_cards:
        kb_rows.extend(row_cards)
    # Binance 跳转按钮
    if symbol:
        market = "futures" if panel == "futures" else "spot"
        binance_url = _build_binance_url(symbol, market=market)
        kb_rows.append([InlineKeyboardButton(I18N.gettext("btn.binance", lang=lang), url=binance_url)])

    kb_rows.extend([row_period, row_panel, row_ctrl])
    return InlineKeyboardMarkup(kb_rows)


def build_pattern_keyboard(update=None) -> InlineKeyboardMarkup:
    """K线形态面板的按钮"""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    lang = _resolve_lang(update) if update else I18N.default_locale
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(I18N.gettext("panel.basic", lang=lang), callback_data="single_panel_basic"),
            InlineKeyboardButton(I18N.gettext("panel.futures", lang=lang), callback_data="single_panel_futures"),
            InlineKeyboardButton(I18N.gettext("panel.advanced", lang=lang), callback_data="single_panel_advanced"),
            InlineKeyboardButton("✅" + I18N.gettext("panel.pattern", lang=lang), callback_data="single_panel_pattern"),
        ],
        [
            InlineKeyboardButton(I18N.gettext("btn.back_home", lang=lang), callback_data="main_menu"),
            InlineKeyboardButton(I18N.gettext("btn.refresh", lang=lang), callback_data="single_refresh"),
        ]
    ])


def build_pattern_keyboard_with_periods(enabled_periods: dict, update=None) -> InlineKeyboardMarkup:
    """K线形态面板的按钮（带周期开关）"""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    lang = _resolve_lang(update) if update else I18N.default_locale
    periods = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]
    row_period = []
    for p in periods:
        on = enabled_periods.get(p, False)
        period_label = I18N.gettext(f"period.{p}", lang=lang)
        if period_label == f"period.{p}":
            period_label = p
        label = period_label if on else f"❎{period_label}"
        row_period.append(InlineKeyboardButton(label, callback_data=f"pattern_toggle_{p}"))

    return InlineKeyboardMarkup([
        row_period,
        [
            InlineKeyboardButton(I18N.gettext("panel.basic", lang=lang), callback_data="single_panel_basic"),
            InlineKeyboardButton(I18N.gettext("panel.futures", lang=lang), callback_data="single_panel_futures"),
            InlineKeyboardButton(I18N.gettext("panel.advanced", lang=lang), callback_data="single_panel_advanced"),
            InlineKeyboardButton("✅" + I18N.gettext("panel.pattern", lang=lang), callback_data="single_panel_pattern"),
        ],
        [
            InlineKeyboardButton(I18N.gettext("btn.back_home", lang=lang), callback_data="main_menu"),
            InlineKeyboardButton(I18N.gettext("btn.refresh", lang=lang), callback_data="single_refresh"),
        ]
    ])


def render_single_snapshot(symbol: str, panel: str, enabled_periods: dict, enabled_cards: dict, page: int = 0, lang: str | None = None, update=None) -> tuple[str, object, int, int]:
    """封装渲染 + 键盘构建，便于重用。返回(text, keyboard, pages, page_used)。"""
    from bot.single_token_snapshot import SingleTokenSnapshot
    snap = SingleTokenSnapshot()
    text, pages = snap.render_table(
        symbol,
        panel=panel,
        enabled_periods=enabled_periods,
        enabled_cards=enabled_cards,
        page=page,
        lang=lang,
    )
    keyboard = build_single_snapshot_keyboard(enabled_periods, panel, enabled_cards, page=page, pages=pages, update=update, lang=lang, symbol=symbol)
    return text, keyboard, pages, page

# 🤖 AI分析模块已下线（历史依赖 pandas/numpy/pandas-ta）。
# AI_FEATURE_NOTICE 使用 i18n
def _get_ai_notice(update=None):
    lang = _resolve_lang(update) if update else I18N.default_locale
    return I18N.gettext("feature.coming_soon", lang=lang)

def build_ai_placeholder_keyboard(update=None) -> InlineKeyboardMarkup:
    """统一的AI功能下线提示按钮"""
    lang = _resolve_lang(update) if update else I18N.default_locale
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(I18N.gettext("btn.back_home", lang=lang), callback_data="main_menu"),
            InlineKeyboardButton(I18N.gettext("btn.refresh", lang=lang), callback_data="main_menu"),
        ]
    ])


# 数据请求隔离修复导入
try:
    from data_request_isolation_fix import DataRequestIsolationManager, NonBlockingDataFetcher
    ISOLATION_AVAILABLE = True
    logger.info("✅ 数据请求隔离模块已加载")
except ImportError:
    ISOLATION_AVAILABLE = False
    logger.warning("⚠️ 数据请求隔离模块未找到")

# 全局数据隔离管理器
data_isolation_manager = None
non_blocking_fetcher = None

def initialize_data_isolation():
    global data_isolation_manager, non_blocking_fetcher
    if ISOLATION_AVAILABLE and data_isolation_manager is None:
        data_isolation_manager = DataRequestIsolationManager()
        non_blocking_fetcher = NonBlockingDataFetcher(data_isolation_manager)
        data_isolation_manager.start_background_processor()
        logger.info("✅ 数据隔离管理器已初始化")

# 初始化数据隔离
initialize_data_isolation()

# ===============================
# 立即响应和文件I/O优化函数
# ===============================

async def _send_instant_reply(update: Update, key: Optional[str] = None) -> None:
    """发送文本即时响应（不影响主流程）"""
    message = _get_update_message(update)
    if not message:
        return
    if not key:
        key = "loading.default"
    text = _t(update, key)
    if not text or text == key:
        text = _t(update, "loading.default")
    if not text or text == "loading.default":
        text = "处理中..."
    try:
        await message.reply_text(text)
    except Exception as exc:
        logger.debug("⚠️ 即时响应发送失败: %s", exc)

def optimize_button_response_logging():
    """优化按钮响应日志记录"""
    import sys

    # 确保日志输出到控制台
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)

    # 添加到根日志记录器
    root_logger = logging.getLogger()
    if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
        root_logger.addHandler(console_handler)
        root_logger.setLevel(logging.INFO)

    logger.info("✅ 按钮响应日志记录已优化")

# 初始化优化的日志记录
optimize_button_response_logging()

# ===============================
# 智能格式化函数 - 动态精度显示
# ===============================

def smart_spread_format(spread: float) -> str:
    """

    Args:
        spread: 价差数值

    Returns:
    """
    try:
        spread_float = float(spread)
        if spread_float == 0:
            return "0"

        # 对于非常小的数值（小于0.001），使用科学计数法
        if abs(spread_float) < 0.001:
            # 使用简洁的科学计数法格式
            formatted = f"{spread_float:.1e}"
            return formatted
        else:
            # 对于较大的数值，使用常规格式化
            formatted = f"{spread_float:.7f}"

            # 去除末尾的零
            if '.' in formatted:
                formatted = formatted.rstrip('0').rstrip('.')

            return formatted
    except Exception:
        return str(spread)


# 存储用户的选择状态
user_states = {
    'position_sort': 'desc',
    'position_limit': 10,
    'funding_sort': 'lowest',
    'funding_limit': 10,
    'volume_period': '15m',
    'volume_sort': 'desc',
    'volume_limit': 10,
    'liquidation_limit': 10,
    'position_market_sort': 'desc',
    'position_market_period': 'current',
    'position_market_limit': 10,
    'money_flow_sort': 'desc',
    'money_flow_limit': 10,
    'money_flow_type': 'absolute',  # 'absolute', 'inflow', 'outflow'
    'money_flow_market': 'futures',  # 'futures', 'spot', 'option'
    # 资金流向可选周期：1m/5m/15m/1h/4h/1d/1w（不含30m）
    'money_flow_period': '15m',
    'market_depth_limit': 10,
    'market_depth_sort': 'desc',
    # 基础行情新增状态
    'basic_market_sort_type': 'change',     # 'change' 或 'price'
    'basic_market_period': '1d',            # '5m', '15m', '30m', '1h', '4h', '12h', '1d'
    'basic_market_sort_order': 'desc',      # 'desc' 或 'asc'
    'basic_market_limit': 10,               # 10, 20, 30
    'basic_market_type': 'futures'          # 'futures', 'spot'
}

# ================== 简化 JSON 工具函数 ==================

def load_json(filename: str, default=None):
    """加载 JSON 文件"""
    try:
        if not os.path.exists(filename):
            return default if default is not None else {}
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"❌ 加载文件失败 {filename}: {e}")
        return default if default is not None else {}

def save_json(filename: str, data, create_backup=False):
    """保存 JSON 文件"""
    try:
        dir_path = os.path.dirname(filename)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"❌ 保存文件失败 {filename}: {e}")
        return False

class DataManager:
    """简化的数据管理器"""
    load_json = staticmethod(load_json)
    save_json = staticmethod(save_json)

    @staticmethod
    def validate_data_integrity():
        return {"issues_found": [], "fixes_applied": [], "success": True}


# ==================== 排行榜菜单分组（模块级常量） ====================
# 注意：button_callback() 内部存在 `from main import UserRequestHandler` 的局部绑定，
# 在该函数中直接引用同名类会触发 UnboundLocalError。
# 这里用模块级常量避免作用域陷阱。
DEFAULT_RANKING_GROUP = "recommend"
ALLOWED_RANKING_GROUPS = {DEFAULT_RANKING_GROUP, "basic", "futures", "advanced"}


class UserRequestHandler:
    """专门处理用户请求的轻量级处理器 - 只读取缓存，不进行网络请求"""

    # ==================== 排行榜卡片分组 ====================
    # 现有分组：basic / futures / advanced 通过模块路径自动归类
    # 新增分组：recommend 为“智能推荐”虚拟分组，只做 card_id 映射，不复制卡片对象，也不改变原分组行为
    RANKING_GROUP_RECOMMEND = "recommend"

    # 智能推荐：显式指定展示顺序（仅影响 recommend 分组）
    RECOMMENDED_CARD_ORDER: list[str] = [
        # ---- 你指定的卡片 ----
        "super_trend_ranking",      # 📐 超级趋势
        "ema_ranking",              # 🧮 EMA
        "vpvr_ranking",             # 🏛️ VPVR
        "vwap_ranking",             # 📏 VWAP
        "cvd_ranking",              # 🧾 CVD
        "candle_pattern_ranking",   # 🕯️ 形态
        "trendline_ranking",        # 📈 趋势线
        # ---- 我补充的推荐（你可以随时删/换）----
        "liquidity_ranking",        # 💧 流动性
        "mfi_ranking",              # 🧪 MFI
        "atr_ranking",              # 🌪️ ATR
        "macd_ranking",             # 🧲 MACD柱
        "rsi_harmonic_ranking",     # 🧩 RSI谐波
    ]

    def __init__(self, card_registry: Optional[RankingRegistry] = None):
        # 用户状态管理
        self.user_states = {
            'position_sort': 'desc',
            'position_limit': 10,
            'position_period': '1d',  # 添加持仓排行时间周期
            'funding_sort': 'desc',
            'funding_limit': 10,
            'funding_sort_type': 'funding_rate',
            'volume_period': '1d',
            'volume_sort': 'desc',
            'volume_limit': 10,
            'volume_market_type': 'futures',  # 'futures', 'spot'
            'liquidation_limit': 10,
            'liquidation_sort': 'desc',
            'liquidation_period': '1d',  # 添加时间周期选择
            'liquidation_type': 'total',  # 添加数据类型选择: total/long/short
            'position_market_sort': 'desc',
            'volume_market_sort': 'desc',
            'volume_market_limit': 10,
            'volume_oi_sort': 'desc',
            'volume_oi_limit': 10,
            'position_market_limit': 10,
            'current_ratio_type': 'position_market',  # 当前比率类型
            'money_flow_sort': 'desc',
            'money_flow_limit': 10,
            'money_flow_type': 'absolute',
            'money_flow_market': 'futures',  # 'futures', 'spot', 'option'
            'money_flow_period': '1d',
            'market_depth_limit': 10,
            'market_depth_sort': 'desc',
            'market_depth_sort_type': 'ratio',
            'basic_market_sort_type': 'change',
            'basic_market_period': '1d',
            'basic_market_sort_order': 'desc',
            'basic_market_limit': 10,
            'basic_market_type': 'futures',
            # 排行榜卡片分组：basic / futures / advanced
            'ranking_group': self.RANKING_GROUP_RECOMMEND,
        }

        # 排行榜卡片注册表（可选）
        self.card_registry = card_registry
        self._apply_card_registry_defaults()

    def _apply_card_registry_defaults(self):
        """注入卡片默认状态"""
        if not self.card_registry:
            return

        for card in self.card_registry.iter_cards():
            for state_key, state_value in card.iter_default_state():
                self.user_states.setdefault(state_key, state_value)

    def check_feature_access(self, user_id: int, feature_name: str) -> tuple:
        """检查功能访问权限 - 所有功能免费"""
        return True, None

    def deduct_feature_cost(self, user_id: int, feature_name: str) -> bool:
        """扣费 - 已禁用，所有功能免费"""
        return True

    def load_cached_data(self, cache_key, max_age_minutes=10):
        """从JSON文件加载缓存数据"""
        try:
            cache_file = os.path.join(DATA_DIR, "cache", f"{cache_key}.json")

            if not os.path.exists(cache_file):
                return None, "缓存文件不存在"

            cache_data = DataManager.load_json(cache_file)
            if not cache_data or 'data' not in cache_data:
                return None, "缓存数据格式无效"

            # 检查缓存时间
            cache_timestamp = cache_data.get('timestamp', 0)
            current_time = int(time.time() * 1000)
            age_minutes = (current_time - cache_timestamp) / (1000 * 60)

            if age_minutes > max_age_minutes:
                return None, f"缓存数据过期 ({age_minutes:.1f}分钟前)"

            logger.info(f"✅ 使用缓存数据: {cache_key} ({cache_data.get('total_coins', 0)}个币种, {age_minutes:.1f}分钟前)")
            return cache_data['data'], None

        except Exception as e:
            logger.error(f"❌ 加载缓存数据失败 {cache_key}: {e}")
            return None, str(e)


    def load_latest_futures_data(self):
        """CoinGlass 本地数据已下线，直接返回 None。"""
        return None

    def get_cached_data_safely(self, key, fallback_message=None):
        """安全获取缓存数据；CoinGlass 数据源已下线直接返回空。"""
        global cache
        if key.startswith("coinglass_"):
            return [], I18N.gettext("data.coinglass_offline")
        if not cache:
            return [], I18N.gettext("data.initializing")
        if key in cache:
            cache_age = time.time() - cache[key]['timestamp']
            logger.info(f"返回内存缓存数据: {key} (缓存年龄: {cache_age:.1f}秒)")
            return cache[key]['data'], None
        if fallback_message is None:
            fallback_message = _t(None, "data.loading_hint")
        logger.warning(f"缓存中没有数据: {key}")
        return [], fallback_message

    def dynamic_align_format(self, data_rows, left_align_cols: int = 2, align_override=None):
        """
        数据对齐：默认全部右对齐；可传入对齐列表 ["L","R",...] 控制列对齐。
        额外：自动裁剪数值字符串尾随 0，避免列宽被无效 0 撑大。
        """
        if not data_rows:
            return _t(None, "data.no_data")

        def _trim_zero(text: str) -> str:
            try:
                # 保留百分号、单位等特殊格式
                if "%" in text:
                    return text
                val = float(text)
                trimmed = f"{val:.8f}".rstrip("0").rstrip(".")
                if trimmed == "-0":
                    trimmed = "0"
                return trimmed
            except Exception:
                return text

        # 先裁剪所有单元格
        cleaned = [[_trim_zero(str(cell)) for cell in row] for row in data_rows]

        col_cnt = max(len(row) for row in cleaned)
        if not all(len(row) == col_cnt for row in cleaned):
            raise ValueError("列数需一致，先清洗或补齐输入数据")

        if align_override:
            align = (list(align_override) + ["R"] * (col_cnt - len(align_override)))[:col_cnt]
        else:
            align = ["R"] * col_cnt

        def _disp_width(text: str) -> int:
            return sum(2 if unicodedata.east_asian_width(ch) in {"F", "W"} else 1 for ch in text)

        widths = [max(_disp_width(row[i]) for row in cleaned) for i in range(col_cnt)]

        def fmt(row):
            cells = []
            for idx, cell_str in enumerate(row):
                pad = max(widths[idx] - _disp_width(cell_str), 0)
                cells.append(cell_str + " " * pad if align[idx] == "L" else " " * pad + cell_str)
            return " ".join(cells)

        return "\n".join(fmt(r) for r in cleaned)

    def get_current_time_display(self, data_time=None):
        """
        获取时间显示：必须且只使用“数据时间”
        - 优先使用显式传入 data_time
        - 否则使用 data_provider 记录的最新数据时间
        - 若仍为空，返回占位符而不是当前时间
        """
        ts = None
        if data_time is not None:
            ts = data_time
        else:
            try:
                from cards.data_provider import get_latest_data_time
                ts = get_latest_data_time()
            except Exception:
                ts = None

        def _parse(val):
            if val is None:
                return None
            if isinstance(val, datetime):
                return val
            if isinstance(val, (int, float)):
                return datetime.fromtimestamp(val, tz=timezone.utc)
            if isinstance(val, str):
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                    try:
                        return datetime.strptime(val, fmt).replace(tzinfo=timezone.utc)
                    except ValueError:
                        continue
            return None

        parsed = _parse(ts)
        if parsed is None:
            return {
                'full': '-',
                'time_only': '--:--',
                'hour_min': I18N.gettext("time.hour_min", hour="--", min="--"),
            }

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        bj = parsed.astimezone(timezone(timedelta(hours=8)))
        return {
            'full': bj.strftime('%Y-%m-%d %H:%M:%S'),
            'time_only': bj.strftime('%H:%M'),
            'hour_min': I18N.gettext("time.hour_min", hour=bj.hour, min=bj.minute)
        }

    def get_main_menu_text(self, update: Optional[Update] = None):
        """获取主菜单文本（随用户语言）"""
        time_info = self.get_current_time_display()
        lang = _resolve_lang(update) if update else I18N.default_locale
        return I18N.gettext("menu.main_text", lang=lang, time=time_info["full"])

    def get_main_menu_keyboard(self, update: Optional[Update] = None):
        """获取主菜单键盘（随用户语言渲染）"""
        lang = _resolve_lang(update) if update else I18N.default_locale
        keyboard = [
            [
                InlineKeyboardButton(I18N.gettext("kb.data", lang=lang), callback_data="ranking_menu"),
                InlineKeyboardButton(I18N.gettext("kb.query", lang=lang), callback_data="coin_query"),
                InlineKeyboardButton(I18N.gettext("kb.ai", lang=lang), callback_data="start_coin_analysis"),
            ],
            [
                InlineKeyboardButton(I18N.gettext("kb.signal", lang=lang), callback_data="signal_menu"),
                InlineKeyboardButton(I18N.gettext("kb.vis", lang=lang, fallback="📈 可视化"), callback_data="vis_menu"),
                InlineKeyboardButton(I18N.gettext("kb.lang", lang=lang), callback_data="lang_menu"),
            ],
            [
                InlineKeyboardButton(I18N.gettext("kb.help", lang=lang), callback_data="help"),
            ],
        ]
        # 管理员显示管理按钮
        if _is_admin(update):
            keyboard.append([
                InlineKeyboardButton(I18N.gettext("kb.admin", lang=lang, fallback="🔧 管理"), callback_data="admin_menu"),
            ])
        return InlineKeyboardMarkup(keyboard)

    # ===== 基础行情占位，避免缺失方法导致报错 =====
    def get_basic_market(self, sort_type='change', period='1d', sort_order='desc', limit=10, market_type='futures'):
        """AI分析占位，保持接口不报错"""
        return _t(None, "feature.ai_unavailable")

    def get_basic_market_keyboard(
        self,
        current_sort_type='change',
        current_period='1d',
        current_sort_order='desc',
        current_limit=10,
        current_market_type='futures',
        update=None
    ):
        """基础行情键盘（占位版）"""
        lang = _resolve_lang(update) if update else I18N.default_locale
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton(I18N.gettext("btn.back_home", lang=lang), callback_data="main_menu"),
                InlineKeyboardButton(I18N.gettext("btn.refresh", lang=lang), callback_data="basic_market"),
            ]
        ])

    def _build_card_button(self, card, update=None) -> InlineKeyboardButton:
        # 优先使用 i18n 键，回退到 button_text
        if card.button_key:
            lang = _resolve_lang(update) if update else I18N.default_locale
            text = I18N.gettext(card.button_key, lang=lang)
        else:
            text = card.button_text
        return InlineKeyboardButton(text, callback_data=card.entry_callback)

    def _chunk_buttons(self, buttons: List[InlineKeyboardButton], chunk_size: int = 3) -> List[List[InlineKeyboardButton]]:
        rows: List[List[InlineKeyboardButton]] = []
        for idx in range(0, len(buttons), chunk_size):
            rows.append(buttons[idx:idx + chunk_size])
        return rows

    @staticmethod
    def _card_group(card) -> str:
        """根据模块路径判定卡片所属分组"""
        mod = getattr(card, "__module__", "")
        if ".futures." in mod:
            return "futures"
        if ".advanced." in mod:
            return "advanced"
        if ".basic." in mod:
            return "basic"
        return "basic"  # 默认归入基础

    @classmethod
    def _iter_recommended_cards(cls, registry: RankingRegistry) -> list:
        """获取 recommend 分组卡片：映射到原卡片实例，不复制、不改动原分组。"""
        cards_by_id = {c.card_id: c for c in registry.iter_cards()}
        cards = []
        for cid in cls.RECOMMENDED_CARD_ORDER:
            card = cards_by_id.get(cid)
            if card is not None:
                cards.append(card)
        return cards


    def get_ranking_menu_keyboard(self, update=None) -> InlineKeyboardMarkup:
        """排行榜二级菜单：列出所有已注册的排行榜卡片"""
        registry = self.card_registry or ensure_ranking_registry()
        current_group = self.user_states.get("ranking_group", self.RANKING_GROUP_RECOMMEND)
        lang = _resolve_lang(update) if update else I18N.default_locale

        buttons: List[InlineKeyboardButton] = []
        if registry:
            if current_group == self.RANKING_GROUP_RECOMMEND:
                cards = self._iter_recommended_cards(registry)
            else:
                cards = [c for c in registry.iter_cards() if self._card_group(c) == current_group]
                cards.sort(key=lambda c: (c.priority, c.button_text))
            buttons = [self._build_card_button(card, update) for card in cards]

        rows = self._chunk_buttons(buttons, chunk_size=3) if buttons else []

        # 提示行
        rows.append([
            InlineKeyboardButton(I18N.gettext("btn.show_more", lang=lang), callback_data="ranking_menu_nop")
        ])

        # 分组切换行
        def _group_btn(key: str, value: str) -> InlineKeyboardButton:
            active = current_group == value
            text = I18N.gettext(key, lang=lang)
            prefix = "✅" if active else ""
            return InlineKeyboardButton(f"{prefix}{text}", callback_data=f"ranking_menu_group_{value}")

        rows.append(
            [
                _group_btn("panel.recommend", self.RANKING_GROUP_RECOMMEND),
                _group_btn("panel.futures", "futures"),
                _group_btn("panel.basic", "basic"),
                _group_btn("panel.advanced", "advanced"),
            ]
        )

        rows.append([
            InlineKeyboardButton(I18N.gettext("menu.home", lang=lang), callback_data="main_menu"),
            InlineKeyboardButton(I18N.gettext("btn.refresh", lang=lang), callback_data="ranking_menu"),
        ])
        return InlineKeyboardMarkup(rows)

    def get_reply_keyboard(self, update: Optional[Update] = None):
        """获取常驻回复键盘（按用户语言渲染）"""
        lang = _resolve_lang(update) if update else I18N.default_locale
        keyboard = [
            [
                KeyboardButton(I18N.gettext("kb.data", lang=lang)),
                KeyboardButton(I18N.gettext("kb.query", lang=lang)),
                KeyboardButton(I18N.gettext("kb.ai", lang=lang)),
            ],
            [
                KeyboardButton(I18N.gettext("kb.signal", lang=lang)),
                KeyboardButton(I18N.gettext("kb.vis", lang=lang)),
                KeyboardButton(I18N.gettext("kb.home", lang=lang)),
            ],
            [
                KeyboardButton(I18N.gettext("kb.config", lang=lang, fallback="⚙️ 配置")),
                KeyboardButton(I18N.gettext("kb.lang", lang=lang)),
                KeyboardButton(I18N.gettext("kb.help", lang=lang)),
            ],
        ]
        return ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True,
            is_persistent=True,
            one_time_keyboard=False,
            selective=False
        )

    async def send_with_persistent_keyboard(self, update, text, parse_mode='Markdown'):
        """
        Args:
            update: Telegram Update对象
            text: 要发送的文本内容
            parse_mode: 解析模式，默认Markdown
        """
        reply_keyboard = self.get_reply_keyboard(update)

        # 发送内容，使用常驻键盘
        await update.message.reply_text(
            text,
            reply_markup=reply_keyboard,
            parse_mode=parse_mode
        )

    def get_position_ranking(self, limit=10, sort_order='desc', period='1d', sort_field: str = "position", update=None):
        """获取持仓量排行榜 - 委托给TradeCatBot处理"""
        global bot
        if bot:
            return bot.get_position_ranking(limit=limit, sort_order=sort_order, period=period, sort_field=sort_field)
        else:
            # 如果全局bot不可用，创建临时实例
            try:
                temp_bot = TradeCatBot()
                return temp_bot.get_position_ranking(limit=limit, sort_order=sort_order, period=period, sort_field=sort_field)
            except Exception as e:
                logger.error(f"创建临时bot实例失败: {e}")
                return _t(update, "data.initializing")

    def get_position_ranking_keyboard(self, current_sort='desc', current_limit=10, current_period='1d', update=None):
        """获取持仓量排行榜键盘 - 委托给TradeCatBot处理"""
        global bot
        if bot:
            return bot.get_position_ranking_keyboard(
                current_sort=current_sort,
                current_limit=current_limit,
                current_period=current_period,
                update=update
            )
        else:
            # 如果全局bot不可用，创建临时实例
            try:
                temp_bot = TradeCatBot()
                return temp_bot.get_position_ranking_keyboard(
                    current_sort=current_sort,
                    current_limit=current_limit,
                    current_period=current_period,
                    update=update
                )
            except Exception as e:
                logger.error(f"创建临时bot实例失败: {e}")
                # 回退键盘
                keyboard = [[_btn(update, "btn.back_home", "main_menu")]]
                return InlineKeyboardMarkup(keyboard)

    def get_funding_rate_ranking(self, limit=10, sort_order='desc', sort_type='funding_rate'):
        """资金费率排行已下线占位。"""
        return _t(None, "feature.funding_offline")

    def get_coinglass_futures_data(self):
        """CoinGlass 数据源已下线，返回空列表。"""
        return []

    def get_funding_rate_keyboard(self, current_sort='desc', current_limit=10, current_sort_type='funding_rate', update=None):
        """资金费率排行已下线的占位键盘。"""
        return InlineKeyboardMarkup([
            [_btn(update, "btn.back_home", "main_menu")]
        ])

    def get_volume_ranking(self, limit=10, period='1d', sort_order='desc', market_type='futures', sort_field: str = "volume", update=None):
        """获取交易量排行榜"""
        if market_type == 'futures':
            return self.get_futures_volume_ranking(limit, period, sort_order, sort_field=sort_field, update=update)
        elif market_type == 'spot':
            return self.get_spot_volume_ranking(limit, period, sort_order, sort_field=sort_field, update=update)
        else:
            return _t(update, "error.unsupported_market")

    @staticmethod
    def _format_usd_value(value: float) -> str:
        if value >= 1e9:
            return f"${value/1e9:.2f}B"
        if value >= 1e6:
            return f"${value/1e6:.2f}M"
        if value >= 1e3:
            return f"${value/1e3:.2f}K"
        return f"${value:.0f}"

    @staticmethod
    def _format_price_value(price: float) -> str:
        if price >= 1000:
            return f"${price:,.0f}"
        if price >= 1:
            return f"${price:.3f}"
        return f"${price:.6f}"

    @staticmethod
    def _format_flow_value(value: float) -> str:
        prefix = "+" if value >= 0 else ""
        abs_value = abs(value)
        if abs_value >= 1e9:
            return f"{prefix}${abs_value/1e9:.2f}B"
        if abs_value >= 1e6:
            return f"{prefix}${abs_value/1e6:.2f}M"
        if abs_value >= 1e3:
            return f"{prefix}${abs_value/1e3:.2f}K"
        return f"{prefix}${abs_value:.0f}"

    def get_futures_volume_ranking(self, limit=10, period='1d', sort_order='desc', sort_field: str = "volume", update=None):
        """基于TimescaleDB生成合约交易量排行榜"""
        allowed_periods = {'5m', '15m', '30m', '1h', '4h', '12h', '1d'}
        if period not in allowed_periods:
            period = '1d'

        service = getattr(self, 'metric_service', None)
        if service is None:
            return _t(update, "data.service_unavailable")

        rows = service.获取交易量排行('futures', period, sort_order, limit * 2)
        processed = []
        for row in rows:
            symbol = row.get('symbol', '')
            if not symbol or symbol in get_blocked_symbols():
                continue
            volume = float(row.get('quote_volume') or 0)
            price = float(row.get('last_close') or 0)
            change_percent = float(row.get('price_change_percent') or 0)
            if volume <= 0 or price <= 0:
                continue
            processed.append((symbol, volume, price, change_percent))

        if not processed:
            return _t(update, "data.aggregating_futures_volume")

        reverse_sort = (sort_order == 'desc')

        def _key(item):
            if sort_field in {"price"}:
                return item[2]
            if sort_field in {"change", "change_percent"}:
                return item[3]
            return item[1]

        processed.sort(key=_key, reverse=reverse_sort)
        selected = processed[:limit]

        data_rows = []
        for idx, (symbol, volume, price, change_percent) in enumerate(selected, 1):
            volume_str = self._format_usd_value(volume)
            price_str = self._format_price_value(price)
            change_str = f"+{change_percent:.2f}%" if change_percent >= 0 else f"{change_percent:.2f}%"
            data_rows.append([f"{idx}.", symbol, volume_str, price_str, change_str])

        aligned_data = self.dynamic_align_format(data_rows)
        time_info = self.get_current_time_display()
        period_text = _period_text(update, period)
        sort_symbol = "⬇️" if sort_order == 'desc' else "🔼"
        sort_text = _sort_text(update, sort_order)

        return (
            f"""{_t(update, "ranking.volume")}
{_t(update, "time.update", time=time_info['full'])}
{_t(update, "ranking.sort.volume", period=period_text, symbol=sort_symbol, sort=sort_text)}
```
{aligned_data}
```
{_t(update, "time.last_update", time=time_info['full'])}"""
        )


    def get_spot_volume_ranking(self, limit=10, period='1d', sort_order='desc', sort_field: str = "volume", update=None):
        """基于TimescaleDB生成现货交易量排行榜"""
        allowed_periods = {'5m', '15m', '30m', '1h', '4h', '12h', '1d', '1w'}
        if period not in allowed_periods:
            period = '1d'

        service = getattr(self, 'metric_service', None)
        if service is None:
            return _t(update, "data.service_unavailable")

        rows = service.获取交易量排行('spot', period, sort_order, limit * 2)
        processed = []
        for row in rows:
            symbol = row.get('symbol', '')
            if not symbol or symbol in get_blocked_symbols():
                continue
            volume = float(row.get('quote_volume') or 0)
            price = float(row.get('last_close') or 0)
            change_percent = float(row.get('price_change_percent') or 0)
            if volume <= 0 or price <= 0:
                continue
            processed.append((symbol, volume, price, change_percent))

        if not processed:
            return _t(update, "data.aggregating_spot_volume")

        reverse_sort = (sort_order == 'desc')

        def _key(item):
            if sort_field in {"price"}:
                return item[2]
            if sort_field in {"change", "change_percent"}:
                return item[3]
            return item[1]

        processed.sort(key=_key, reverse=reverse_sort)
        selected = processed[:limit]

        data_rows = []
        for idx, (symbol, volume, price, change_percent) in enumerate(selected, 1):
            volume_str = self._format_usd_value(volume)
            price_str = self._format_price_value(price)
            change_str = f"+{change_percent:.2f}%" if change_percent >= 0 else f"{change_percent:.2f}%"
            data_rows.append([f"{idx}.", symbol, volume_str, price_str, change_str])

        aligned_data = self.dynamic_align_format(data_rows)
        time_info = self.get_current_time_display()
        period_text = _period_text(update, period)
        sort_symbol = "⬇️" if sort_order == 'desc' else "🔼"
        sort_text = _sort_text(update, sort_order)

        return (
            f"""{_t(update, "ranking.spot_volume", period=period_text)}
{_t(update, "time.update", time=time_info['full'])}
{_t(update, "ranking.sort.volume", period=period_text, symbol=sort_symbol, sort=sort_text)}
```
{aligned_data}
```
{_t(update, "time.last_update", time=time_info['full'])}"""
        )


    def get_position_market_ratio(self, limit=10, sort_order='desc', update=None):
        """获取持仓/市值比排行榜"""
        # 获取市场缓存数据
        coinglass_data = self.get_coinglass_cache_data()

        if not coinglass_data:
            return _t(update, "data.fetch_failed")

        # 计算持仓/市值比
        ratio_data = []
        for coin in coinglass_data:
            symbol = coin.get('symbol', '')
            if not symbol or symbol in get_blocked_symbols():
                continue

            # 使用持仓市值比字段
            ratio = coin.get('open_interest_market_cap_ratio', 0)
            if ratio <= 0:
                continue

            # 获取其他数据
            current_price = coin.get('current_price', 0)
            market_cap = coin.get('market_cap_usd', 0)
            open_interest = coin.get('open_interest_usd', 0)

            ratio_data.append({
                'symbol': symbol,
                'ratio': ratio,
                'current_price': current_price,
                'market_cap': market_cap,
                'open_interest': open_interest
            })

        # 排序
        reverse_sort = (sort_order == 'desc')
        sorted_data = sorted(ratio_data, key=lambda x: x['ratio'], reverse=reverse_sort)[:limit]

        # 准备数据行
        data_rows = []
        for i, item in enumerate(sorted_data, 1):
            symbol = item['symbol']
            ratio = item['ratio']
            open_interest = item['open_interest']

            # 格式化比率
            ratio_str = f"{ratio:.4f}"

            # 格式化持仓量
            if open_interest >= 1e9:
                value_str = f"${open_interest/1e9:.2f}B"
            elif open_interest >= 1e6:
                value_str = f"${open_interest/1e6:.2f}M"
            else:
                value_str = f"${open_interest/1e3:.2f}K"

            data_rows.append([
                f"{i}.",
                symbol,
                value_str,
                ratio_str
            ])

        # 动态对齐格式化
        aligned_data = self.dynamic_align_format(data_rows)

        time_info = self.get_current_time_display()

        # 排序方式显示
        sort_symbol = "⬇️" if sort_order == 'desc' else "🔼"
        sort_text = _sort_text(update, sort_order)

        text = f"""{_t(update, "ranking.ratio.position_market")}
{_t(update, "time.update", time=time_info['full'])}
{_t(update, "ranking.sort.ratio", symbol=sort_symbol, sort=sort_text)}
```
{aligned_data}
```
{_t(update, "ranking.hint.position_market")}
{_t(update, "time.last_update", time=time_info['full'])}"""

        return text

    def get_volume_market_ratio(self, limit=10, sort_order='desc', update=None):
        """获取交易量/市值比排行榜"""
        # 获取市场缓存数据
        coinglass_data = self.get_coinglass_cache_data()

        if not coinglass_data:
            return _t(update, "data.fetch_failed")

        # 计算交易量/市值比
        ratio_data = []
        for coin in coinglass_data:
            symbol = coin.get('symbol', '')
            if not symbol or symbol in get_blocked_symbols():
                continue

            # 计算交易量/市值比
            market_cap = coin.get('market_cap_usd', 0)
            open_interest = coin.get('open_interest_usd', 0)
            oi_volume_ratio = coin.get('open_interest_volume_ratio', 0)

            if market_cap <= 0 or oi_volume_ratio <= 0:
                continue

            # 根据 持仓量/交易量比 计算日线交易量
            volume_1d = open_interest / oi_volume_ratio if oi_volume_ratio > 0 else 0

            if volume_1d <= 0:
                continue

            # 计算交易量/市值比
            ratio = volume_1d / market_cap

            # 获取其他数据
            current_price = coin.get('current_price', 0)

            ratio_data.append({
                'symbol': symbol,
                'ratio': ratio,
                'current_price': current_price,
                'market_cap': market_cap,
                'volume_1d': volume_1d
            })

        # 排序
        reverse_sort = (sort_order == 'desc')
        sorted_data = sorted(ratio_data, key=lambda x: x['ratio'], reverse=reverse_sort)[:limit]

        # 准备数据行
        data_rows = []
        for i, item in enumerate(sorted_data, 1):
            symbol = item['symbol']
            ratio = item['ratio']
            volume_1d = item['volume_1d']

            # 格式化比率
            ratio_str = f"{ratio:.4f}"

            # 格式化交易量
            if volume_1d >= 1e9:
                value_str = f"${volume_1d/1e9:.2f}B"
            elif volume_1d >= 1e6:
                value_str = f"${volume_1d/1e6:.2f}M"
            else:
                value_str = f"${volume_1d/1e3:.2f}K"

            data_rows.append([
                f"{i}.",
                symbol,
                value_str,
                ratio_str
            ])

        # 动态对齐格式化
        aligned_data = self.dynamic_align_format(data_rows)

        time_info = self.get_current_time_display()

        # 排序方式显示
        sort_symbol = "⬇️" if sort_order == 'desc' else "🔼"
        sort_text = _sort_text(update, sort_order)

        text = f"""{_t(update, "ranking.ratio.volume_market")}
{_t(update, "time.update", time=time_info['full'])}
{_t(update, "ranking.sort.ratio", symbol=sort_symbol, sort=sort_text)}
```
{aligned_data}
```
{_t(update, "ranking.hint.volume_market")}
{_t(update, "time.last_update", time=time_info['full'])}"""

        return text

    def get_volume_oi_ratio(self, limit=10, sort_order='desc', update=None):
        """获取交易量/持仓量比排行榜"""
        # 获取市场缓存数据
        coinglass_data = self.get_coinglass_cache_data()

        if not coinglass_data:
            return _t(update, "data.fetch_failed")

        # 计算交易量/持仓量比
        ratio_data = []
        for coin in coinglass_data:
            symbol = coin.get('symbol', '')
            if not symbol or symbol in get_blocked_symbols():
                continue

            # 使用持仓交易量比字段的倒数
            oi_volume_ratio = coin.get('open_interest_volume_ratio', 0)

            if oi_volume_ratio <= 0:
                continue

            # 日线交易量/持仓量比 = 1 / (持仓量/日线交易量比)
            ratio = 1 / oi_volume_ratio

            # 获取其他数据
            current_price = coin.get('current_price', 0)
            open_interest = coin.get('open_interest_usd', 0)

            # 计算日线交易量
            volume_1d = open_interest / oi_volume_ratio if oi_volume_ratio > 0 else 0

            ratio_data.append({
                'symbol': symbol,
                'ratio': ratio,
                'current_price': current_price,
                'open_interest': open_interest,
                'volume_1d': volume_1d
            })

        # 排序
        reverse_sort = (sort_order == 'desc')
        sorted_data = sorted(ratio_data, key=lambda x: x['ratio'], reverse=reverse_sort)[:limit]

        # 准备数据行
        data_rows = []
        for i, item in enumerate(sorted_data, 1):
            symbol = item['symbol']
            ratio = item['ratio']
            volume_1d = item['volume_1d']

            # 格式化比率
            ratio_str = f"{ratio:.4f}"

            # 格式化交易量
            if volume_1d >= 1e9:
                value_str = f"${volume_1d/1e9:.2f}B"
            elif volume_1d >= 1e6:
                value_str = f"${volume_1d/1e6:.2f}M"
            else:
                value_str = f"${volume_1d/1e3:.2f}K"

            data_rows.append([
                f"{i}.",
                symbol,
                value_str,
                ratio_str
            ])

        # 动态对齐格式化
        aligned_data = self.dynamic_align_format(data_rows)

        time_info = self.get_current_time_display()

        # 排序方式显示
        sort_symbol = "⬇️" if sort_order == 'desc' else "🔼"
        sort_text = _sort_text(update, sort_order)

        text = f"""{_t(update, "ranking.ratio.volume_oi")}
{_t(update, "time.update", time=time_info['full'])}
{_t(update, "ranking.sort.ratio", symbol=sort_symbol, sort=sort_text)}
```
{aligned_data}
```
{_t(update, "ranking.hint.volume_oi")}
{_t(update, "time.last_update", time=time_info['full'])}"""

        return text

    def calculate_historical_ratio(self, coin, period):
        """计算历史时间点的持仓/市值比"""
        try:
            # 获取价格变化和持仓量变化
            price_change_key = f'price_change_percent_{period}'
            oi_change_key = f'open_interest_change_percent_{period}'

            price_change = coin.get(price_change_key, 0)
            oi_change = coin.get(oi_change_key, 0)

            # 当前值
            current_price = coin.get('current_price', 0)
            current_market_cap = coin.get('market_cap_usd', 0)
            current_oi = coin.get('open_interest_usd', 0)

            if current_price <= 0 or current_market_cap <= 0 or current_oi <= 0:
                return None

            # 计算历史价格和持仓量
            historical_price = current_price / (1 + price_change / 100)
            historical_oi = current_oi / (1 + oi_change / 100)

            # 计算历史市值（假设流通量不变）
            historical_market_cap = current_market_cap * (historical_price / current_price)

            # 计算历史比率
            if historical_market_cap > 0:
                historical_ratio = historical_oi / historical_market_cap
                return historical_ratio

            return None

        except Exception:
            return None

    def get_coinglass_cache_data(self):
        """CoinGlass 缓存已下线，返回空列表。"""
        return []

    def get_unified_ratio_keyboard(self, current_sort='desc', current_limit=10, current_ratio_type='position_market', update=None):
        """获取统一的比率键盘布局"""
        lang = _resolve_lang(update) if update else I18N.default_locale

        def _btn_active(key: str, callback: str, active: bool) -> InlineKeyboardButton:
            text = I18N.gettext(key, lang=lang)
            return InlineKeyboardButton(f"✅{text}" if active else text, callback_data=callback)

        ratio_buttons = [
            _btn_active("ratio.position_market", "ratio_type_position_market", current_ratio_type == 'position_market'),
            _btn_active("ratio.volume_market", "ratio_type_volume_market", current_ratio_type == 'volume_market'),
            _btn_active("ratio.volume_oi", "ratio_type_volume_oi", current_ratio_type == 'volume_oi'),
        ]

        sort_limit_buttons = []
        sort_limit_buttons.append(_btn_active("btn.desc", "unified_ratio_sort_desc", current_sort == 'desc'))
        sort_limit_buttons.append(_btn_active("btn.asc", "unified_ratio_sort_asc", current_sort == 'asc'))

        limits = [10, 20, 30]
        for limit_val in limits:
            label = I18N.gettext("sort.items", lang=lang, n=limit_val)
            sort_limit_buttons.append(
                InlineKeyboardButton(
                    f"✅{label}" if limit_val == current_limit else label,
                    callback_data=f"unified_ratio_{limit_val}"
                )
            )

        control_buttons = [
            _btn_lang(lang, "btn.back_home", "main_menu"),
            _btn_lang(lang, "btn.refresh", "unified_ratio_refresh"),
        ]

        keyboard = [ratio_buttons, sort_limit_buttons, control_buttons]

        return InlineKeyboardMarkup(keyboard)

    def get_position_market_ratio_keyboard(self, current_sort='desc', current_limit=10):
        """获取持仓/市值比键盘 - 兼容性保持"""
        return self.get_unified_ratio_keyboard(current_sort, current_limit, 'position_market')

    def get_volume_market_ratio_keyboard(self, current_sort='desc', current_limit=10):
        """获取交易量/市值比键盘 - 兼容性保持"""
        return self.get_unified_ratio_keyboard(current_sort, current_limit, 'volume_market')

    def get_volume_oi_ratio_keyboard(self, current_sort='desc', current_limit=10):
        """获取交易量/持仓量比键盘 - 兼容性保持"""
        return self.get_unified_ratio_keyboard(current_sort, current_limit, 'volume_oi')

    def get_money_flow(self, limit=10, period='1d', sort_order='desc', flow_type='absolute', market='futures', update=None):
        """获取资金流向排行榜 - 支持合约和现货数据"""
        if market == 'spot':
            # 现货数据支持多时间周期
            return self.get_spot_money_flow(limit, sort_order, flow_type, period, update=update)
        else:
            # 合约数据（原有逻辑）
            return self.get_futures_money_flow(limit, period, sort_order, flow_type, update=update)

    def get_option_money_flow(self, limit=10, sort_order='desc', flow_type='absolute', update=None):
        """获取期权资金流向排行榜"""
        option_data, error = self.get_cached_data_safely('coinglass_option_flow_data')

        if error:
            return _t(update, "data.option_failed")

        if not option_data:
            return _t(update, "data.option_loading")

        # 获取缓存状态信息
        cache_info = ""
        try:
            cache_file = os.path.join(DATA_DIR, "cache", "coinglass_option_flow_data.json")
            if os.path.exists(cache_file):
                cache_data = DataManager.load_json(cache_file)
                if cache_data and 'last_update' in cache_data:
                    cache_info = f"\n📄 缓存时间: {cache_data['last_update']}"
        except Exception:
            pass

        # 根据流向类型过滤和排序数据
        if flow_type == 'inflow':
            # 只显示资金流入的币种
            filtered_data = [item for item in option_data if item['net_flow_usd'] > 0]
            sorted_data = sorted(filtered_data, key=lambda x: x['net_flow_usd'], reverse=True)[:limit]
        elif flow_type == 'outflow':
            # 只显示资金流出的币种
            filtered_data = [item for item in option_data if item['net_flow_usd'] < 0]
            sorted_data = sorted(filtered_data, key=lambda x: x['net_flow_usd'], reverse=False)[:limit]
        else:  # flow_type == 'absolute'
            # 显示所有币种，按绝对值排序
            reverse_sort = (sort_order == 'desc')
            sorted_data = sorted(option_data, key=lambda x: abs(x['net_flow_usd']), reverse=reverse_sort)[:limit]

        # 准备数据行
        data_rows = []
        for i, item in enumerate(sorted_data, 1):
            symbol = item['symbol'].replace('USDT', '')
            net_flow = item['net_flow_usd']
            day_suffix = "1d"
            legacy_suffix = f"{24}h"
            oi_change = item.get(f'oi_change_{day_suffix}') or item.get(f'oi_change_{legacy_suffix}', 0)
            volume_change = item.get(f'volume_change_{day_suffix}') or item.get(f'volume_change_{legacy_suffix}', 0)

            # 格式化净流量
            if abs(net_flow) >= 1e9:
                flow_str = f"+{net_flow/1e9:.2f}B" if net_flow >= 0 else f"{net_flow/1e9:.2f}B"
            elif abs(net_flow) >= 1e6:
                flow_str = f"+{net_flow/1e6:.2f}M" if net_flow >= 0 else f"{net_flow/1e6:.2f}M"
            elif abs(net_flow) >= 1e3:
                flow_str = f"+{net_flow/1e3:.2f}K" if net_flow >= 0 else f"{net_flow/1e3:.2f}K"
            else:
                flow_str = f"+{net_flow:.0f}" if net_flow >= 0 else f"{net_flow:.0f}"

            # 持仓量变化
            oi_str = f"+{oi_change:.2f}%" if oi_change >= 0 else f"{oi_change:.2f}%"

            # 成交量变化
            vol_str = f"+{volume_change:.1f}%" if volume_change >= 0 else f"{volume_change:.1f}%"

            data_rows.append([
                f"{i}.",
                symbol,
                flow_str,
                oi_str,
                vol_str
            ])

        # 动态对齐格式化
        aligned_data = self.dynamic_align_format(data_rows)

        time_info = self.get_current_time_display()

        # 根据流向类型设置标题和说明
        if flow_type == 'inflow':
            title = _t(update, "flow.option.inflow")
            sort_desc = _t(update, "flow.option.sort_inflow")
            type_desc = _t(update, "flow.option.type_inflow")
            flow_desc = _t(update, "flow.option.desc_inflow")
        elif flow_type == 'outflow':
            title = _t(update, "flow.option.outflow")
            sort_desc = _t(update, "flow.option.sort_outflow")
            type_desc = _t(update, "flow.option.type_outflow")
            flow_desc = _t(update, "flow.option.desc_outflow")
        else:  # flow_type == 'absolute'
            title = _t(update, "flow.option.absolute")
            sort_symbol = "⬇️" if sort_order == 'desc' else "🔼"
            sort_text = _sort_text(update, sort_order)
            sort_desc = _t(update, "flow.option.sort_absolute", symbol=sort_symbol, sort=sort_text)
            type_desc = _t(update, "flow.option.type_absolute")
            flow_desc = _t(update, "flow.option.desc_absolute")

        text = f"""{title}
{_t(update, "time.update", time=time_info['full'])}
```
{aligned_data}
```
{sort_desc}
{type_desc}
{flow_desc}
💡 净流量 = 持仓量变化(70%) + 成交量变化(30%)
{_t(update, "time.last_update", time=time_info['full'])}{cache_info}"""

        return text



    def get_futures_money_flow(self, limit=10, period='1d', sort_order='desc', flow_type='absolute', update=None):
        """基于TimescaleDB的合约资金流向排行榜（CVD）"""
        allowed_periods = {'5m', '15m', '30m', '1h', '4h', '12h', '1d'}
        if period not in allowed_periods:
            period = '1d'

        service = getattr(self, 'metric_service', None)
        if service is None:
            return _t(update, "data.service_unavailable")

        raw_rows = service.获取资金流排行('futures', period, limit * 4, flow_type, sort_order)
        rows = []
        for row in raw_rows:
            symbol = row.get('symbol', '')
            if not symbol or symbol in get_blocked_symbols():
                continue
            net_flow = float(row.get('net_quote_flow') or 0)
            buy_quote = float(row.get('buy_quote') or 0)
            sell_quote = max(float(row.get('sell_quote') or 0), 0.0)
            quote_volume = float(row.get('quote_volume') or 0)
            change_percent = float(row.get('price_change_percent') or 0)
            rows.append((symbol, net_flow, buy_quote, sell_quote, quote_volume, change_percent))

        if not rows:
            return _t(update, "data.aggregating_futures_cvd")

        def _filter_by_type(data):
            if flow_type == 'inflow':
                return [item for item in data if item[1] > 0]
            if flow_type == 'outflow':
                return [item for item in data if item[1] < 0]
            return data

        filtered = _filter_by_type(rows)
        if not filtered:
            return _t(update, "data.no_flow_data")

        if flow_type == 'volume':
            reverse_sort = (sort_order == 'desc')
            filtered.sort(key=lambda item: item[4], reverse=reverse_sort)
        else:
            reverse_sort = (sort_order == 'desc')
            filtered.sort(key=lambda item: abs(item[1]) if flow_type == 'absolute' else item[1], reverse=reverse_sort)

        selected = filtered[:limit]
        data_rows = []
        for idx, (symbol, net_flow, buy_quote, sell_quote, _, change_percent) in enumerate(selected, 1):
            flow_str = self._format_flow_value(net_flow)
            if sell_quote <= 0:
                ratio_str = "∞" if buy_quote > 0 else "--"
            else:
                ratio_str = f"{buy_quote / sell_quote:.2f}"
            change_str = f"+{change_percent:.2f}%" if change_percent >= 0 else f"{change_percent:.2f}%"
            data_rows.append([f"{idx}.", symbol, flow_str, ratio_str, change_str])

        aligned_data = self.dynamic_align_format(data_rows)
        time_info = self.get_current_time_display()
        period_name = _period_text(update, period)
        sort_symbol = "⬇️" if sort_order == 'desc' else "🔼"
        sort_text = _sort_text(update, sort_order)

        if flow_type == 'inflow':
            title = _t(update, "flow.title.futures_long", period=period_name)
            _t(update, "flow.desc.futures_long")
        elif flow_type == 'outflow':
            title = _t(update, "flow.title.futures_short", period=period_name)
            _t(update, "flow.desc.futures_short")
        elif flow_type == 'volume':
            title = _t(update, "flow.title.futures_volume", period=period_name)
            _t(update, "flow.desc.volume")
        else:
            title = _t(update, "flow.title.futures", period=period_name)
            _t(update, "flow.desc.absolute", symbol=sort_symbol, sort=sort_text)

        return (
            f"""{title}
{_t(update, "time.update", time=time_info['full'])}
排名/币种/净流(CVD)/买卖比/涨跌幅
```
{aligned_data}
```
💡 {_t(update, "flow.desc.definition_futures")}
{_t(update, "time.last_update", time=time_info['full'])}"""
        )

    def get_spot_money_flow(self, limit=10, period='1d', sort_order='desc', flow_type='absolute', update=None):
        """基于TimescaleDB的现货资金流向排行榜"""
        allowed_periods = {'5m', '15m', '30m', '1h', '4h', '12h', '1d', '1w'}
        if period not in allowed_periods:
            period = '1d'

        service = getattr(self, 'metric_service', None)
        if service is None:
            return _t(update, "data.service_unavailable")

        raw_rows = service.获取资金流排行('spot', period, limit * 4, flow_type, sort_order)
        rows = []
        for row in raw_rows:
            symbol = row.get('symbol', '')
            if not symbol or symbol in get_blocked_symbols():
                continue
            net_flow = float(row.get('net_quote_flow') or 0)
            buy_quote = float(row.get('buy_quote') or 0)
            sell_quote = max(float(row.get('sell_quote') or 0), 0.0)
            quote_volume = float(row.get('quote_volume') or 0)
            change_percent = float(row.get('price_change_percent') or 0)
            rows.append((symbol, net_flow, buy_quote, sell_quote, quote_volume, change_percent))

        if not rows:
            return _t(update, "data.aggregating_spot_cvd")

        def _filter_by_type(data):
            if flow_type == 'inflow':
                return [item for item in data if item[1] > 0]
            if flow_type == 'outflow':
                return [item for item in data if item[1] < 0]
            return data

        filtered = _filter_by_type(rows)
        if not filtered:
            return _t(update, "data.no_spot_flow")

        if flow_type == 'volume':
            reverse_sort = (sort_order == 'desc')
            filtered.sort(key=lambda item: item[4], reverse=reverse_sort)
        else:
            reverse_sort = (sort_order == 'desc')
            filtered.sort(key=lambda item: abs(item[1]) if flow_type == 'absolute' else item[1], reverse=reverse_sort)

        selected = filtered[:limit]
        data_rows = []
        for idx, (symbol, net_flow, buy_quote, sell_quote, _, change_percent) in enumerate(selected, 1):
            flow_str = self._format_flow_value(net_flow)
            if sell_quote <= 0:
                ratio_str = "∞" if buy_quote > 0 else "--"
            else:
                ratio_str = f"{buy_quote / sell_quote:.2f}"
            change_str = f"+{change_percent:.2f}%" if change_percent >= 0 else f"{change_percent:.2f}%"
            data_rows.append([f"{idx}.", symbol, flow_str, ratio_str, change_str])

        aligned_data = self.dynamic_align_format(data_rows)
        time_info = self.get_current_time_display()
        period_name = _period_text(update, period)
        sort_symbol = "⬇️" if sort_order == 'desc' else "🔼"
        sort_text = _sort_text(update, sort_order)

        if flow_type == 'inflow':
            title = _t(update, "flow.title.spot_long", period=period_name)
            _t(update, "flow.desc.spot_long")
        elif flow_type == 'outflow':
            title = _t(update, "flow.title.spot_short", period=period_name)
            _t(update, "flow.desc.spot_short")
        elif flow_type == 'volume':
            title = _t(update, "flow.title.spot_volume", period=period_name)
            _t(update, "flow.desc.volume")
        else:
            title = _t(update, "flow.title.spot", period=period_name)
            _t(update, "flow.desc.absolute", symbol=sort_symbol, sort=sort_text)

        return (
            f"""{title}
{_t(update, "time.update", time=time_info['full'])}
排名/币种/净流(CVD)/买卖比/涨跌幅
```
{aligned_data}
```
💡 {_t(update, "flow.desc.definition_spot")}
{_t(update, "time.last_update", time=time_info['full'])}"""
        )


    def get_money_flow_keyboard(self, current_period='1d', current_sort='desc', current_limit=10, current_flow_type='absolute', current_market='futures', update=None):
        """获取资金流向键盘"""
        lang = _resolve_lang(update) if update else I18N.default_locale

        def _btn_active(key: str, callback: str, active: bool) -> InlineKeyboardButton:
            text = I18N.gettext(key, lang=lang)
            label = f"✅{text}" if active else text
            return InlineKeyboardButton(label, callback_data=callback)

        # 市场类型
        market_buttons = [
            _btn_active("market.spot", "money_flow_market_spot", current_market == "spot"),
            _btn_active("market.futures", "money_flow_market_futures", current_market == "futures"),
        ]

        # 流向类型
        flow_keys = [
            ("flow.absolute", "money_flow_type_absolute", "absolute"),
            ("flow.inflow", "money_flow_type_inflow", "inflow"),
            ("flow.outflow", "money_flow_type_outflow", "outflow"),
            ("flow.volume", "money_flow_type_volume", "volume"),
        ]
        flow_type_buttons = [
            _btn_active(key, cb, current_flow_type == value)
            for key, cb, value in flow_keys
            if current_market == "spot" or value in {"absolute", "inflow", "outflow", "volume"}
        ]

        # 排序按钮（仅绝对值/市值）
        sort_buttons = []
        if current_flow_type in ['absolute', 'volume']:
            sort_buttons.append(
                _btn_active("btn.desc", "money_flow_sort_desc", current_sort == 'desc')
            )
            sort_buttons.append(
                _btn_active("btn.asc", "money_flow_sort_asc", current_sort == 'asc')
            )

        # 周期按钮
        period_buttons = []
        if current_market in ['spot', 'futures']:
            periods = [
                ('5m',), ('15m',), ('30m',), ('1h',), ('4h',), ('12h',), ('1d',)
            ]
            if current_market == 'spot':
                periods.append(('1w',))

            for period_val, in periods:
                label = _period_text_lang(lang, period_val)
                active_label = f"✅{label}"
                period_buttons.append(
                    InlineKeyboardButton(
                        active_label if period_val == current_period else label,
                        callback_data=f"money_flow_period_{period_val}"
                    )
                )

        # 排序 + 数量
        sort_limit_buttons = []
        if sort_buttons:
            sort_limit_buttons.extend(sort_buttons)

        limits = [10, 20, 30]
        for limit_val in limits:
            label = I18N.gettext("sort.items", lang=lang, n=limit_val)
            sort_limit_buttons.append(
                InlineKeyboardButton(
                    f"✅{label}" if limit_val == current_limit else label,
                    callback_data=f"money_flow_{limit_val}"
                )
            )

        keyboard = [
            market_buttons,
            flow_type_buttons,
        ]

        if period_buttons:
            keyboard.append(period_buttons[:4])
            keyboard.append(period_buttons[4:])

        if sort_limit_buttons:
            keyboard.append(sort_limit_buttons)

        keyboard.append([
            _btn_lang(lang, "btn.back_home", "main_menu"),
            _btn_lang(lang, "btn.refresh", "money_flow"),
        ])

        return InlineKeyboardMarkup(keyboard)

    def get_market_depth(self, limit=10, sort_type='ratio', sort_order='desc'):
        """市场深度排行已下线占位。"""
        return _t(None, "feature.depth_offline")

    def get_market_depth_keyboard(self, current_limit=10, current_sort_type='ratio', current_sort='desc', update=None):
        """市场深度排行已下线的占位键盘。"""
        return InlineKeyboardMarkup([
            [_btn(update, "btn.back_home", "main_menu")]
        ])

    def get_market_sentiment(self):
        """市场情绪（基于Binance行情）已下线占位。"""
        return _t(None, "feature.sentiment_offline")

    def get_market_sentiment_keyboard(self, update=None):
        """市场情绪占位键盘。"""
        return InlineKeyboardMarkup([
            [_btn(update, "btn.back_home", "main_menu")]
        ])

class TradeCatBot:
    def __init__(self):
        self._active_symbols = None
        self._active_symbols_timestamp = 0
        self._is_initialized = False
        self._initialization_lock = asyncio.Lock() if 'asyncio' in globals() else None
        # 双缓存文件机制
        self.cache_file_primary = CACHE_FILE_PRIMARY
        self.cache_file_secondary = CACHE_FILE_SECONDARY
        self._current_cache_file = self.cache_file_primary  # 当前使用的缓存文件
        self._is_updating = False  # 是否正在更新缓存
        self.metric_service = BINANCE_DB_METRIC_SERVICE
        if self.metric_service is None:
            logger.warning("⚠️ 币安数据库指标服务未就绪，部分排行榜将回退至缓存逻辑")

    def filter_blocked_symbols(self, data_list):
        """过滤掉被屏蔽的币种"""
        if not data_list:
            return data_list

        filtered_data = []
        for item in data_list:
            symbol = item.get('symbol', '')
            if symbol not in get_blocked_symbols():
                filtered_data.append(item)

        return filtered_data

    def get_available_cache_files(self):
        """获取可用的缓存文件列表，按修改时间排序"""
        cache_files = []

        # 检查主缓存文件
        if os.path.exists(self.cache_file_primary):
            mtime = os.path.getmtime(self.cache_file_primary)
            cache_files.append((self.cache_file_primary, mtime))

        # 检查备份缓存文件
        if os.path.exists(self.cache_file_secondary):
            mtime = os.path.getmtime(self.cache_file_secondary)
            cache_files.append((self.cache_file_secondary, mtime))

        # 按修改时间降序排序（最新的在前面）
        cache_files.sort(key=lambda x: x[1], reverse=True)

        return [file_path for file_path, _ in cache_files]

    def load_cache_from_file(self):
        """从文件加载缓存数据 - 支持双缓存文件机制"""
        global cache

        available_files = self.get_available_cache_files()
        if not available_files:
            logger.info("📄 没有找到缓存文件，将创建新的缓存")
            return False

        # 尝试从最新的缓存文件加载
        for cache_file in available_files:
            try:
                logger.info(f"📄 尝试从缓存文件加载: {cache_file}")
                with open(cache_file, 'r', encoding='utf-8') as f:
                    file_cache = json.load(f)

                # 检查缓存是否过期
                now = time.time()
                valid_cache = {}
                total_items = len(file_cache)

                for key, cache_item in file_cache.items():
                    if isinstance(cache_item, dict) and 'timestamp' in cache_item:
                        # 检查缓存是否在有效期内（扩展到10分钟，允许更长的使用时间）
                        cache_age = now - cache_item['timestamp']
                        if cache_age < 600:  # 10分钟有效期
                            valid_cache[key] = cache_item
                            logger.debug(f"从文件加载有效缓存: {key} (年龄: {cache_age:.1f}秒)")
                        else:
                            logger.debug(f"文件缓存已过期: {key} (年龄: {cache_age:.1f}秒)")
                    else:
                        logger.warning(f"无效的缓存格式: {key}")

                if valid_cache:
                    cache.update(valid_cache)
                    logger.info(f"✅ 从文件 {cache_file} 加载了 {len(valid_cache)}/{total_items} 个有效缓存项")
                    self._current_cache_file = cache_file
                    return True
                else:
                    logger.info(f"📄 缓存文件 {cache_file} 中没有有效数据")

            except Exception as e:
                logger.error(f"❌ 加载缓存文件失败 {cache_file}: {e}")
                continue

        logger.warning("❌ 所有缓存文件都无法加载或已过期")
        return False

    def save_cache_to_file(self, force_new_file=False):
        """保存缓存数据到文件 - 双缓存文件机制"""
        global cache
        try:
            # 创建一个可序列化的缓存副本
            serializable_cache = {}
            for key, cache_item in cache.items():
                if isinstance(cache_item, dict) and 'data' in cache_item and 'timestamp' in cache_item:
                    # 确保数据可以序列化
                    try:
                        json.dumps(cache_item['data'])  # 测试序列化
                        serializable_cache[key] = cache_item
                    except (TypeError, ValueError) as e:
                        logger.warning(f"缓存项 {key} 无法序列化，跳过: {e}")
                        continue

            if not serializable_cache:
                logger.warning("⚠️ 没有可序列化的缓存数据")
                return False

            # 选择要写入的缓存文件
            if force_new_file or self._is_updating:
                # 如果正在更新或强制使用新文件，则使用备用文件
                if self._current_cache_file == self.cache_file_primary:
                    target_file = self.cache_file_secondary
                else:
                    target_file = self.cache_file_primary
            else:
                # 否则使用当前文件
                target_file = self._current_cache_file

            # 写入临时文件，然后重命名，确保原子性操作
            temp_file = target_file + '.tmp'
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(serializable_cache, f, ensure_ascii=False, indent=2)

            # 原子性重命名
            if os.path.exists(target_file):
                os.remove(target_file)
            os.rename(temp_file, target_file)

            # 更新当前使用的缓存文件
            if force_new_file or self._is_updating:
                self._current_cache_file = target_file
                logger.info(f"✅ 缓存已保存到新文件: {target_file} ({len(serializable_cache)} 个项目)")

                # 清理旧的缓存文件（保留最新的两个文件）
                self.cleanup_old_cache_files()
            else:
                logger.info(f"✅ 缓存已更新到文件: {target_file} ({len(serializable_cache)} 个项目)")

            return True

        except Exception as e:
            logger.error(f"❌ 保存缓存文件失败: {e}")
            # 清理临时文件
            temp_file = target_file + '.tmp' if 'target_file' in locals() else None
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass

        return False

    def cleanup_old_cache_files(self):
        """清理旧的缓存文件，只保留最新的两个"""
        try:
            available_files = self.get_available_cache_files()

            # 如果超过2个文件，删除最旧的
            if len(available_files) > 2:
                files_to_delete = available_files[2:]  # 保留前两个（最新的）
                for file_path in files_to_delete:
                    try:
                        os.remove(file_path)
                        logger.info(f"🗑️ 已删除旧缓存文件: {file_path}")
                    except Exception as e:
                        logger.warning(f"⚠️ 删除旧缓存文件失败 {file_path}: {e}")

        except Exception as e:
            logger.error(f"❌ 清理缓存文件失败: {e}")

    def get_cached_data(self, key, fetch_func, *args, **kwargs):
        """获取缓存数据或重新获取"""
        global cache
        now = time.time()
        if key in cache and now - cache[key]['timestamp'] < CACHE_DURATION:
            logger.info(f"使用缓存数据: {key}")
            return cache[key]['data']

        try:
            logger.info(f"获取新数据: {key}")
            data = fetch_func(*args, **kwargs)
            if data:  # 只缓存有效数据
                cache[key] = {'data': data, 'timestamp': now}
                logger.info(f"数据缓存成功: {key}, 条数: {len(data) if isinstance(data, list) else 1}")
            return data
        except Exception as e:
            logger.error(f"获取数据失败 {key}: {e}")
            # 返回旧缓存数据作为备选
            old_data = cache.get(key, {}).get('data', [])
            if old_data:
                logger.info(f"返回旧缓存数据: {key}")
            return old_data

    async def initialize_cache(self):
        """初始化缓存 - 预加载所有数据"""
        if self._is_initialized:
            return

        logger.info("🚀 开始初始化缓存，预加载所有数据...")

        # 首先尝试从文件加载缓存
        cache_loaded = self.load_cache_from_file()
        if cache_loaded:
            logger.info("📄 使用文件缓存数据")
        else:
            logger.info("🌐 文件缓存无效，将从数据库加载")

        # 预加载数据的任务列表 - 仅使用本地数据源
        cache_tasks = [
            # 预计算的市场指标（从 SQLite 读取）
            ('market_sentiment_cache', self.compute_market_sentiment_data),
            ('top_gainers_cache', lambda: self.compute_top_movers_data('gainers')),
            ('top_losers_cache', lambda: self.compute_top_movers_data('losers')),
            ('active_symbols_cache', lambda: self.get_active_symbols(force_refresh=True)),
        ]

        # 预加载活跃交易对
        try:
            logger.info("📊 预加载活跃交易对...")
            self.get_active_symbols(force_refresh=True)
            logger.info("✅ 活跃交易对加载完成")
        except Exception as e:
            logger.error(f"❌ 活跃交易对加载失败: {e}")

        # 使用异步方式预加载所有数据（避免阻塞）
        async def load_cache_async(key, fetch_func):
            """异步加载缓存数据"""
            try:
                # 检查是否已有有效缓存
                if key in cache:
                    now = time.time()
                    if now - cache[key]['timestamp'] < CACHE_DURATION:
                        logger.info(f"✅ {key} 缓存仍然有效，跳过网络请求")
                        return

                logger.info(f"📊 预加载 {key}...")
                # 在线程池中执行，避免阻塞
                loop = asyncio.get_event_loop()
                data = await loop.run_in_executor(None, fetch_func)

                if data:
                    cache[key] = {'data': data, 'timestamp': time.time()}
                    logger.info(f"✅ {key} 加载完成，数据量: {len(data) if isinstance(data, list) else 1}")
                else:
                    logger.warning(f"⚠️ {key} 数据为空")

            except Exception as e:
                logger.error(f"❌ {key} 加载失败: {e}")

        # 分批并发加载，避免过多并发请求
        batch_size = 4
        for i in range(0, len(cache_tasks), batch_size):
            batch = cache_tasks[i:i+batch_size]
            tasks = [load_cache_async(key, func) for key, func in batch]
            await asyncio.gather(*tasks, return_exceptions=True)

            # 批次间稍作休息
            if i + batch_size < len(cache_tasks):
                await asyncio.sleep(0.3)

        # 保存缓存到文件（异步执行）
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.save_cache_to_file)

        self._is_initialized = True
        logger.info("🎉 缓存初始化完成！")

    def get_cached_data_only(self, key):
        """仅获取缓存数据，不进行网络请求"""
        global cache
        if key in cache:
            cache_age = time.time() - cache[key]['timestamp']
            logger.info(f"返回缓存数据: {key} (缓存年龄: {cache_age:.1f}秒)")
            return cache[key]['data']
        else:
            logger.warning(f"缓存中没有数据: {key}")
            return []

    def get_cached_data_with_fallback(self, key, fallback_message=None):
        """获取缓存数据，如果没有则返回友好提示"""
        global cache
        if key in cache:
            cache_age = time.time() - cache[key]['timestamp']
            logger.info(f"返回缓存数据: {key} (缓存年龄: {cache_age:.1f}秒)")
            return cache[key]['data'], None
        else:
            logger.warning(f"缓存中没有数据: {key}")
            if fallback_message is None:
                fallback_message = _t(None, "data.loading_hint")
            return [], fallback_message

    def get_cache_status(self):
        """获取缓存状态信息"""
        global cache
        if not cache:
            return _t(None, "data.cache_empty")

        status_info = []
        current_time = time.time()

        for key, data in cache.items():
            age = current_time - data['timestamp']
            data_count = len(data['data']) if isinstance(data['data'], list) else 1
            status_info.append(f"- {key}: {data_count}条数据, {age:.1f}秒前")

        return _t(None, "cache.status_title") + "\n" + "\n".join(status_info)

    async def refresh_cache_background(self):
        """🚀 极轻量级后台刷新 - 完全非阻塞，用户体验优先"""
        update_interval = 120  # 基础更新间隔2分钟，进一步减少频率
        consecutive_failures = 0
        time.time()

        while True:
            try:
                # 智能调整更新间隔，失败时延长间隔
                current_interval = min(update_interval * (1 + consecutive_failures * 0.5), 600)  # 最大10分钟

                # 根据系统负载动态调整
                import psutil
                cpu_percent = psutil.cpu_percent(interval=0.1)
                if cpu_percent > 80:
                    current_interval *= 1.5  # CPU高负载时延长间隔

                await asyncio.sleep(current_interval)

                # 🔧 关键修复：使用轻量级更新，完全非阻塞
                logger.info(f"🚀 启动极轻量级缓存刷新... (间隔: {current_interval:.0f}秒, CPU: {cpu_percent:.1f}%)")

                try:
                    # 使用轻量级异步更新，不设置阻塞标志
                    await self.update_cache_lightweight()
                    consecutive_failures = 0  # 重置失败计数
                    logger.info("✅ 智能后台缓存刷新完成")
                except Exception as update_error:
                    logger.error(f"❌ 后台缓存更新失败: {update_error}")
                    consecutive_failures += 1

            except Exception as e:
                logger.error(f"❌ 后台缓存刷新失败: {e}")
                consecutive_failures += 1

                # 失败后等待时间递增，但保持较短
                wait_time = min(5 * consecutive_failures, 30)  # 最大30秒
                await asyncio.sleep(wait_time)

    async def update_cache_lightweight(self):
        """轻量级缓存更新 - 不设置阻塞标志，确保用户请求不受影响"""
        global cache
        if BINANCE_API_DISABLED:
            logger.info("⏸️ BINANCE_API_DISABLED=1，跳过轻量级缓存更新")
            return
        logger.info("📊 开始轻量级非阻塞缓存更新...")

        # 🔧 不设置 self._is_updating = True，确保用户请求不被阻塞

        # 创建新的缓存数据
        new_cache_data = {}

        # 轻量级异步包装器
        async def fetch_lightweight(key, fetch_func):
            """轻量级异步包装器，优先保证用户体验"""
            try:
                logger.info(f"🔄 轻量级更新 {key}...")
                # 在线程池中执行，设置较短超时
                loop = asyncio.get_event_loop()

                # 设置30秒超时，避免长时间阻塞
                try:
                    data = await asyncio.wait_for(
                        loop.run_in_executor(None, fetch_func),
                        timeout=30.0
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"⏰ {key} 更新超时，保留旧缓存")
                    # 保留旧缓存
                    if key in cache:
                        return key, cache[key]
                    return key, None

                if data:
                    logger.info(f"✅ {key} 轻量级更新完成")
                    return key, {'data': data, 'timestamp': time.time()}
                else:
                    logger.warning(f"⚠️ {key} 数据为空，保留旧缓存")
                    if key in cache:
                        return key, cache[key]
                    return key, None

            except Exception as e:
                logger.error(f"❌ 轻量级更新 {key} 失败: {e}")
                # 保留旧缓存数据
                if key in cache:
                    logger.info(f"🔄 保留 {key} 的旧缓存数据")
                    return key, cache[key]
                return key, None

        # 数据由 data-service 采集，此处仅更新本地计算的缓存
        critical_tasks = [
            ('active_symbols_cache', lambda: self.get_active_symbols(force_refresh=True)),
        ]

        for key, func in critical_tasks:
            try:
                result = await fetch_lightweight(key, func)
                if result[1] is not None:
                    new_cache_data[result[0]] = result[1]
            except Exception as e:
                logger.error(f"任务 {key} 异常: {e}")

        if new_cache_data:
            # 快速原子性更新
            cache.update(new_cache_data)

            # 异步保存到文件，不等待完成
            try:
                loop = asyncio.get_event_loop()
                # 后台线程写盘：无需再封装 create_task，run_in_executor 已返回 Future
                loop.run_in_executor(None, lambda: self.save_cache_to_file(force_new_file=False))
            except Exception as save_error:
                logger.warning(f"缓存保存任务创建失败: {save_error}")

            logger.info(f"🎉 轻量级缓存更新完成！更新了 {len(new_cache_data)} 个数据源")
        else:
            logger.warning("⚠️ 本次轻量级更新没有获取到新数据")

    async def update_cache_non_blocking(self):
        """非阻塞缓存更新 - 重定向到轻量级更新"""
        await self.update_cache_lightweight()

    def get_cache_file_info(self):
        """获取缓存文件信息"""
        info = []
        available_files = self.get_available_cache_files()

        for i, file_path in enumerate(available_files):
            try:
                mtime = os.path.getmtime(file_path)
                size = os.path.getsize(file_path)
                # 转换为北京时间 UTC+8
                mtime_str = datetime.fromtimestamp(mtime, timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
                size_str = f"{size/1024:.1f}KB" if size < 1024*1024 else f"{size/(1024*1024):.1f}MB"

                status = _t(None, "cache.current_use") if file_path == self._current_cache_file else _t(None, "cache.backup_file")
                info.append(f"- {file_path}: {status}, {mtime_str}, {size_str}")
            except Exception as e:
                info.append(f"- {file_path}: 读取失败 - {e}")

        return "\n".join(info) if info else _t(None, "cache.no_files")

    def get_active_symbols(self, force_refresh=False):
        """获取活跃的USDT合约交易对 - 从环境变量配置读取
        
        优先使用 SYMBOLS_GROUPS 配置，不再从 Binance API 获取。
        """
        now = time.time()
        if not force_refresh and self._active_symbols and (now - self._active_symbols_timestamp) < 300:
            return self._active_symbols

        from common.symbols import get_configured_symbols

        configured = get_configured_symbols()
        if configured:
            filtered = [s for s in configured if s not in get_blocked_symbols()]
            self._active_symbols = filtered
            self._active_symbols_timestamp = now
            groups = os.environ.get("SYMBOLS_GROUPS", "main4")
            preview = filtered[:10]
            logger.info("✅ 从配置加载币种 (%s): %s (共 %d)", groups, preview, len(filtered))
            return filtered

        # 默认回退到 main4
        default_symbols = os.environ.get('SYMBOLS_GROUP_main4', 'BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT')
        symbols = [s.strip() for s in default_symbols.split(',') if s.strip()]
        filtered = [s for s in symbols if s not in get_blocked_symbols()]
        self._active_symbols = filtered
        self._active_symbols_timestamp = now
        logger.info("✅ 使用默认币种配置: %s", filtered)
        return filtered

    def compute_market_sentiment_data(self):
        """预计算市场情绪数据"""
        try:
            # 获取基础数据
            price_data = self.get_cached_data_only('ticker_24hr_data')
            funding_data = self.get_cached_data_only('funding_rate_data')

            if not price_data or not funding_data:
                return None

            # 计算市场情绪指标
            filtered_price = [item for item in price_data if item['symbol'].endswith('USDT') and item['symbol'] not in get_blocked_symbols()]
            total_coins = len(filtered_price)
            rising_coins = len([item for item in filtered_price if float(item['priceChangePercent']) > 0])

            # 计算资金费率情绪
            filtered_funding = [item for item in funding_data if item['symbol'].endswith('USDT') and item['symbol'] not in get_blocked_symbols()]
            avg_funding_rate = sum([float(item['lastFundingRate']) for item in filtered_funding]) / len(filtered_funding) if filtered_funding else 0

            return {
                'total_coins': total_coins,
                'rising_coins': rising_coins,
                'rising_percentage': (rising_coins / total_coins) * 100 if total_coins > 0 else 0,
                'avg_funding_rate': avg_funding_rate,
                'timestamp': time.time()
            }
        except Exception as e:
            logger.error(f"计算市场情绪数据失败: {e}")
            return None

    def compute_top_movers_data(self, move_type='gainers'):
        """预计算涨跌幅排行数据"""
        try:
            price_data = self.get_cached_data_only('ticker_24hr_data')
            if not price_data:
                return None

            # 过滤数据
            filtered_data = [
                item for item in price_data
                if item['symbol'].endswith('USDT') and float(item['quoteVolume']) > 1000000 and item['symbol'] not in get_blocked_symbols()
            ]

            # 排序
            reverse_sort = (move_type == 'gainers')
            sorted_data = sorted(filtered_data, key=lambda x: float(x['priceChangePercent']), reverse=reverse_sort)

            return {
                'data': sorted_data[:50],  # 保存前50名
                'move_type': move_type,
                'timestamp': time.time()
            }
        except Exception as e:
            logger.error(f"计算涨跌幅排行数据失败: {e}")
            return None

    def load_latest_futures_data(self):
        """CoinGlass 本地数据已下线，直接返回 None。"""
        return None

    def validate_and_format_data(self, data_list, required_fields):
        """验证和格式化数据"""
        if not data_list:
            return []

        valid_data = []
        for item in data_list:
            if all(field in item for field in required_fields):
                try:
                    # 验证数值字段
                    for field in required_fields:
                        if field in ['lastPrice', 'priceChangePercent', 'quoteVolume', 'lastFundingRate']:
                            float(item[field])
                    valid_data.append(item)
                except (ValueError, TypeError):
                    continue

        return valid_data

    def dynamic_align_format(self, data_rows, left_align_cols: int = 2, align_override=None):
        """
        动态视图对齐：默认全部右对齐；可传入 align_override=["L","R"...] 控制每列。
        额外：自动裁剪数值字符串尾随 0，避免列宽被无效 0 撑大。
        """
        if not data_rows:
            return _t(None, "data.no_data")

        def _trim_zero(text: str) -> str:
            try:
                if "%" in text:
                    return text
                val = float(text)
                trimmed = f"{val:.8f}".rstrip("0").rstrip(".")
                if trimmed == "-0":
                    trimmed = "0"
                return trimmed
            except Exception:
                return text

        cleaned = [[_trim_zero(str(cell)) for cell in row] for row in data_rows]

        col_cnt = max(len(row) for row in cleaned)
        if not all(len(row) == col_cnt for row in cleaned):
            raise ValueError("列数需一致，先清洗或补齐输入数据")

        if align_override:
            align = (list(align_override) + ["R"] * (col_cnt - len(align_override)))[:col_cnt]
        else:
            align = ["R"] * col_cnt

        def _disp_width(text: str) -> int:
            return sum(2 if unicodedata.east_asian_width(ch) in {"F", "W"} else 1 for ch in text)

        widths = [max(_disp_width(row[i]) for row in cleaned) for i in range(col_cnt)]

        def fmt(row):
            cells = []
            for idx, cell_str in enumerate(row):
                pad = max(widths[idx] - _disp_width(cell_str), 0)
                cells.append(cell_str + " " * pad if align[idx] == "L" else " " * pad + cell_str)
            return " ".join(cells)

        return "\n".join(fmt(r) for r in cleaned)

    def get_current_time_display(self):
        """获取当前时间显示"""
        # 北京时间 UTC+8
        now = datetime.now(timezone(timedelta(hours=8)))
        return {
            'full': format_beijing_time(get_beijing_time().isoformat(), '%Y-%m-%d %H:%M:%S'),
            'time_only': format_beijing_time(get_beijing_time().isoformat(), '%H:%M'),
            'hour_min': I18N.gettext("time.hour_min", hour=now.hour, min=now.minute)
        }


    def get_main_menu_text(self, update: Optional[Update] = None):
        """获取主菜单文本（随用户语言）"""
        time_info = self.get_current_time_display()
        lang = _resolve_lang(update) if update else I18N.default_locale
        return I18N.gettext("menu.main_text", lang=lang, time=time_info["full"])

    def get_position_ranking(self, limit=10, sort_order='desc', period='1d', sort_field: str = "position", update=None):
        """获取持仓量排行榜"""
        # 加载最新的合约数据
        futures_data = self.load_latest_futures_data()

        if not futures_data:
            return _t(update, "data.oi_loading")

        # 映射时间周期到字段
        period_mapping = {
            '5m': '5m',
            '15m': '15m',
            '30m': '30m',
            '1h': '1h',
            '4h': '4h',
            '1d': '1d'
        }

        if period not in period_mapping:
            period = '1d'  # 默认使用1d

        period_suffix = period_mapping[period]

        # 处理数据
        processed_data = []
        for item in futures_data:
            try:
                symbol = item.get('symbol', '')
                if not symbol or symbol in get_blocked_symbols():
                    continue

                # 获取基础持仓量数据
                current_oi_usd = float(item.get('open_interest_usd', 0))
                current_oi_quantity = float(item.get('open_interest_quantity', 0))

                if current_oi_usd <= 0:
                    continue

                # 获取指定周期的变化数据
                change_percent = float(item.get(f'open_interest_change_percent_{period_suffix}', 0))
                change_usd = float(item.get(f'open_interest_change_usd_{period_suffix}', 0))

                # 获取价格数据
                current_price = float(item.get('current_price', 0))

                processed_data.append({
                    'symbol': symbol,
                    'current_oi_usd': current_oi_usd,
                    'current_oi_quantity': current_oi_quantity,
                    'change_percent': change_percent,
                    'change_usd': change_usd,  # 指定时间周期内的变化值
                    'current_price': current_price
                })

            except (ValueError, TypeError) as e:
                logger.warning(f"处理{symbol}持仓数据时出错: {e}")
                continue

        # 排序 - 根据变化金额的绝对值排序
        reverse_sort = (sort_order == 'desc')

        def _key(item):
            if sort_field in {"volume", "oi", "current_oi_usd"}:
                return item.get('current_oi_usd', 0)
            if sort_field in {"price"}:
                return item.get('current_price', 0)
            if sort_field in {"change_percent", "placeholder"}:
                return abs(item.get('change_percent', 0))
            return abs(item.get('change_usd', 0))

        sorted_data = sorted(processed_data, key=_key, reverse=reverse_sort)[:limit]

        # 准备数据行
        data_rows = []
        for i, item in enumerate(sorted_data, 1):
            symbol = item['symbol']
            change_percent = item['change_percent']
            change_usd = item['change_usd']

            # 格式化变化金额
            if abs(change_usd) >= 1e9:
                if change_usd >= 0:
                    change_value_str = f"+${change_usd/1e9:.2f}B"
                else:
                    change_value_str = f"-${abs(change_usd)/1e9:.2f}B"
            elif abs(change_usd) >= 1e6:
                if change_usd >= 0:
                    change_value_str = f"+${change_usd/1e6:.2f}M"
                else:
                    change_value_str = f"-${abs(change_usd)/1e6:.2f}M"
            elif abs(change_usd) >= 1e3:
                if change_usd >= 0:
                    change_value_str = f"+${change_usd/1e3:.2f}K"
                else:
                    change_value_str = f"-${abs(change_usd)/1e3:.2f}K"
            else:
                if change_usd >= 0:
                    change_value_str = f"+${change_usd:.0f}"
                else:
                    change_value_str = f"-${abs(change_usd):.0f}"

            # 显示变化百分比
            if change_percent >= 0:
                change_percent_str = f"+{change_percent:.2f}%"
            else:
                change_percent_str = f"{change_percent:.2f}%"

            data_rows.append([
                f"{i}.",
                symbol,
                change_value_str,
                change_percent_str
            ])

        # 动态对齐格式化
        aligned_data = self.dynamic_align_format(data_rows)

        time_info = self.get_current_time_display()

        # 时间周期显示
        period_text = _period_text(update, period)

        # 排序方式显示
        sort_symbol = "⬇️" if sort_order == 'desc' else "🔼"
        sort_text = _sort_text(update, sort_order)

        cache_info = ""
        text = f"""{_t(update, "ranking.position")}
{_t(update, "time.update", time=time_info['full'])}
{_t(update, "ranking.sort.change", period=period_text, symbol=sort_symbol, sort=sort_text)}
```
{aligned_data}
```
{_t(update, "time.last_update", time=time_info['full'])}{cache_info}"""

        return text
    def get_position_ranking_keyboard(self, current_sort='desc', current_limit=10, current_period='1d', update=None):
        """获取持仓量排行榜键盘"""
        lang = _resolve_lang(update) if update else I18N.default_locale
        # 时间周期按钮（第一行和第二行）- 新增更多周期
        period_buttons_row1 = []
        period_buttons_row2 = []
        periods_row1 = ['5m', '15m', '30m']
        periods_row2 = ['1h', '4h', '1d']

        for period_value in periods_row1:
            label = _period_text_lang(lang, period_value)
            period_buttons_row1.append(
                InlineKeyboardButton(
                    f"✅{label}" if period_value == current_period else label,
                    callback_data=f"position_period_{period_value}"
                )
            )

        for period_value in periods_row2:
            label = _period_text_lang(lang, period_value)
            period_buttons_row2.append(
                InlineKeyboardButton(
                    f"✅{label}" if period_value == current_period else label,
                    callback_data=f"position_period_{period_value}"
                )
            )

        # 排序和数量按钮合并为一行（第三行）
        sort_limit_buttons = []

        # 排序按钮
        if current_sort == 'desc':
            sort_limit_buttons.append(_btn_lang(lang, "btn.desc", "position_sort_desc", active=True))
            sort_limit_buttons.append(_btn_lang(lang, "btn.asc", "position_sort_asc"))
        else:
            sort_limit_buttons.append(_btn_lang(lang, "btn.desc", "position_sort_desc"))
            sort_limit_buttons.append(_btn_lang(lang, "btn.asc", "position_sort_asc", active=True))

        # 数量按钮
        limits = [10, 20, 30]
        for limit_val in limits:
            label = I18N.gettext("sort.items", lang=lang, n=limit_val)
            sort_limit_buttons.append(
                InlineKeyboardButton(
                    f"✅{label}" if limit_val == current_limit else label,
                    callback_data=f"position_{limit_val}"
                )
            )

        keyboard = [
            period_buttons_row1,  # 第一行：5分 15分 30分
            period_buttons_row2,  # 第二行：1小时 4小时 24小时
            sort_limit_buttons,   # 第三行：排序和数量按钮合并
            [                     # 第四行：功能按钮
                _btn_lang(lang, "btn.back_home", "main_menu"),
                _btn_lang(lang, "btn.refresh", "position_ranking"),
            ]
        ]
        return InlineKeyboardMarkup(keyboard)


def is_group_mention_required(update: Update) -> bool:
    """群组内是否必须 @ 才响应"""
    return _GROUP_REQUIRE_MENTION

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """启动命令处理器"""
    global user_handler

    if not _is_command_allowed(update):
        return

    if user_handler is None:
        await update.message.reply_text(_t(update, "start.initializing"))
        await _trigger_user_handler_init()
        return

    try:
        # 自动为所有用户开启信号订阅（首次 /start 即注册）
        try:
            from signals import ui as signal_ui
            target_id = signal_ui.resolve_target_id(update)
            if target_id:
                signal_ui.get_sub(target_id)
                logger.info("✅ 自动订阅信号: %s", target_id)
        except Exception as e:
            logger.warning(f"自动订阅信号失败: {e}")

        # 先发送带键盘的消息刷新底部键盘
        await update.message.reply_text(_t(update, "start.greet"), reply_markup=user_handler.get_reply_keyboard(update))

        text = user_handler.get_main_menu_text(update)
        inline_keyboard = user_handler.get_main_menu_keyboard(update)
        text = ensure_valid_text(text, _t(update, "start.fallback"))

        await update.message.reply_text(text, reply_markup=inline_keyboard)

    except Exception as e:
        logger.error(f"❌ /start 命令处理出错: {e}")
        import traceback
        traceback.print_exc()
        await update.message.reply_text(
            _t(update, "start.error", error=str(e))
        )

def ensure_valid_text(text, fallback=None):
    """确保文本有效，不为空，并且有实际内容"""
    if fallback is None:
        fallback = _t(None, "data.loading")
    try:
        if text and isinstance(text, str) and len(text.strip()) > 0:
            # 进一步检查是否包含有意义的内容
            if text.strip() not in ["", "None", "null", "undefined"]:
                return text
        # 如果文本无效，返回fallback
        return fallback
    except Exception as e:
        logger.warning(f"⚠️ ensure_valid_text处理异常: {e}")
        return fallback

def mdv2(text: str) -> str:
    """兼容旧调用，直接返回原文（统一使用Markdown普通模式）"""
    return text or ""
def _build_ranking_menu_text(group: str, update: Optional[Update] = None) -> str:
    """根据分组返回排行榜菜单文案（多语言）"""
    lang = _resolve_lang(update) if update else I18N.default_locale
    return I18N.gettext("menu.ranking", lang=lang)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """按钮回调处理器"""
    global user_handler, bot
    if not _is_command_allowed(update):
        try:
            if update.callback_query:
                await update.callback_query.answer()
        except Exception:
            pass
        return

    from telegram import InlineKeyboardMarkup

    query = update.callback_query
    user_id = query.from_user.id
    button_data = query.data

    # 自动为所有互动会话注册信号订阅（按钮点击即可注册）
    try:
        from signals import ui as signal_ui
        target_id = signal_ui.resolve_target_id(update)
        if target_id:
            signal_ui.get_sub(target_id)
    except Exception as e:
        logger.debug(f"自动订阅信号失败(回调): {e}")

    # =============================================================================
    # 全局统一快速响应 - 方案C（详细提示）
    # =============================================================================
    try:
        if button_data.endswith("_nop") or button_data.endswith("nop"):
            await query.answer()
        elif button_data.startswith(("ai_", "start_coin_analysis", "start_ai_analysis")):
            await query.answer(_t(update, "loading.ai", "🤖 启动AI分析..."))
        elif button_data.startswith("vis_") or button_data == "vis_menu":
            await query.answer(_t(update, "loading.vis", "📈 正在渲染图表..."))
        elif button_data.endswith("_refresh") or button_data == "admin_reload":
            await query.answer(_t(update, "loading.refresh", "🔄 正在刷新..."))
        elif button_data.startswith("single_query_") or button_data == "coin_query":
            await query.answer(_t(update, "loading.query", "🔍 正在查询..."))
        elif button_data.startswith(("set_lang_", "field_")) or button_data.endswith("_toggle_"):
            await query.answer(_t(update, "loading.switch", "✅ 已切换"))
        elif button_data.startswith(("ranking_", "single_", "position_", "funding_", "money_flow_", "market_", "basic_market", "admin_")):
            await query.answer(_t(update, "loading.data", "📊 正在加载数据..."))
        elif button_data.startswith("sig_"):
            await query.answer(_t(update, "loading.switch", "✅ 处理中..."))
        elif button_data in ("main_menu", "ranking_menu", "help", "lang_menu", "signal_menu", "admin_menu"):
            await query.answer()
        else:
            await query.answer(_t(update, "loading.default", "处理中..."))
    except Exception as e:
        # 仅记录日志，不阻断流程（可能是超时或重复 answer）
        logger.debug(f"query.answer failed for {button_data}: {e}")

    # 打开语言选择菜单
    if button_data == "lang_menu":
        await lang_command(update, context)
        return

    # =============================================================================
    # 配置管理回调 (env_*) - 已禁用（硬开关保护）
    # =============================================================================
    if button_data.startswith("env_"):
        if not ENABLE_ENV_MANAGER:
            await query.answer("⚠️ 功能已禁用", show_alert=True)
            return
        # env_* 回调处理已禁用，此处仅作防护

    # 语言切换
    if button_data.startswith("set_lang_"):
        new_lang = button_data.replace("set_lang_", "")
        new_lang = I18N.resolve(new_lang)
        _save_user_locale(user_id, new_lang)
        # 同步刷新 cards/i18n 模块的缓存
        try:
            from cards.i18n import reload_user_locale
            reload_user_locale()
        except Exception:
            pass
        display_names = {
            "zh_CN": I18N.gettext("lang.zh", lang=new_lang),
            "en": I18N.gettext("lang.en", lang=new_lang),
        }
        # 注意: 即时响应已在前面统一处理，此处不再重复 query.answer()
        await query.edit_message_text(
            I18N.gettext("lang.set", lang=new_lang, lang_name=display_names.get(new_lang, new_lang))
        )
        if user_handler:
            main_text = user_handler.get_main_menu_text(update)
            main_keyboard = user_handler.get_main_menu_keyboard(update)
            await query.message.reply_text(main_text, reply_markup=main_keyboard)
        return

    # AI深度分析入口
    if button_data == "start_ai_analysis":
        try:
            from bot.ai_integration import get_ai_handler, AI_SERVICE_AVAILABLE, SELECTING_COIN
            if not AI_SERVICE_AVAILABLE:
                raise ImportError("ai-service 未安装")
            ai_handler = get_ai_handler(symbols_provider=lambda: user_handler.get_active_symbols() if user_handler else None)
            context.user_data["ai_state"] = SELECTING_COIN
            await ai_handler.start_ai_analysis(update, context)
            return
        except ImportError as e:
            logger.warning(f"AI模块未安装: {e}")
            await query.edit_message_text(
                _t(update, "ai.not_installed"),
                reply_markup=InlineKeyboardMarkup([[ _btn(update, "btn.back_home", "main_menu") ]])
            )
            return
        except Exception as e:
            logger.error(f"AI分析启动失败: {e}")
            await query.edit_message_text(
                _t(update, "ai.failed", error=e),
                reply_markup=InlineKeyboardMarkup([[ _btn(update, "btn.back_home", "main_menu") ]])
            )
            return

    # AI 分析相关回调（币种选择、周期选择、提示词选择）
    if button_data.startswith("ai_"):
        try:
            from bot.ai_integration import get_ai_handler, AI_SERVICE_AVAILABLE, SELECTING_COIN, SELECTING_INTERVAL
            if not AI_SERVICE_AVAILABLE:
                await query.answer(_t(update, "ai.not_installed"))
                return
            # 记录用户语言偏好，贯通到 AI 服务
            context.user_data["lang_preference"] = _resolve_lang(update)
            ai_handler = get_ai_handler(symbols_provider=lambda: user_handler.get_active_symbols() if user_handler else None)

            # 根据按钮类型和当前状态分发
            if button_data.startswith("ai_interval_"):
                context.user_data["ai_state"] = SELECTING_INTERVAL
                await ai_handler.handle_interval_selection(update, context)
            elif button_data == "ai_back_to_coin":
                context.user_data["ai_state"] = SELECTING_COIN
                await ai_handler.handle_interval_selection(update, context)
            elif button_data.startswith("ai_coin_"):
                # 选择币种后进入周期选择
                context.user_data["ai_state"] = SELECTING_INTERVAL
                await ai_handler.handle_coin_selection(update, context)
            elif button_data == "ai_cancel":
                context.user_data.pop("ai_state", None)
                await ai_handler.handle_coin_selection(update, context)
            else:
                # 其他 ai_ 开头的按钮（翻页、提示词选择等）
                await ai_handler.handle_coin_selection(update, context)
            return
        except ImportError as e:
            logger.warning(f"AI模块未安装: {e}")
            await query.answer(_t(update, "ai.not_installed"))
            return
        except Exception as e:
            logger.error(f"AI回调处理失败: {e}")
            await query.answer(_t(update, "ai.failed", error=e))
            return

    # AI分析入口
    if button_data == "start_coin_analysis":
        try:
            from bot.ai_integration import get_ai_handler, AI_SERVICE_AVAILABLE
            if not AI_SERVICE_AVAILABLE:
                await query.answer(_t(update, "ai.not_installed"), show_alert=True)
                return
            context.user_data["lang_preference"] = _resolve_lang(update)
            ai_handler = get_ai_handler(symbols_provider=lambda: user_handler.get_active_symbols() if user_handler else None)
            await ai_handler.start_ai_analysis(update, context)
            return
        except Exception as e:
            logger.error(f"AI分析入口失败: {e}")
            await query.answer(_t(update, "ai.failed", error=e), show_alert=True)
            return

    # 信号开关界面
    if button_data == "signal_menu" or button_data.startswith("sig_"):
        try:
            from signals import ui as signal_ui
            if button_data == "signal_menu":
                # 注意: 即时响应已在前面统一处理
                await query.edit_message_text(
                    signal_ui.get_menu_text(signal_ui.resolve_target_id(update) or user_id),
                    reply_markup=signal_ui.get_menu_kb(signal_ui.resolve_target_id(update) or user_id, update=update),
                    parse_mode='HTML'
                )
            else:
                await signal_ui.handle(update, context)
            return
        except Exception as e:
            logger.error(f"信号界面失败: {e}")
            await query.answer(_t("error.signal_failed", update), show_alert=True)
            return

    # 管理员菜单
    if button_data == "admin_menu" or button_data.startswith("admin_"):
        # 检查管理员权限
        if not _is_admin(update):
            await query.answer(_t(update, "admin.no_permission", "⛔ 无权限"), show_alert=True)
            return
        # 注意: 即时响应已在前面统一处理，此处不再重复 query.answer()
        
        if button_data == "admin_menu":
            text = _build_admin_menu_text(update)
            keyboard = _build_admin_menu_keyboard(update)
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')
            return
        
        if button_data == "admin_stats":
            # 统计信息
            cache_count = len(cache.keys()) if cache else 0
            user_count = len(_user_locale_map) if _user_locale_map else 0
            text = (
                f"📊 **{_t(update, 'admin.stats_title', '系统统计')}**\n\n"
                f"🗄️ 缓存条目: {cache_count}\n"
                f"👥 语言配置用户: {user_count}\n"
                f"👑 管理员数量: {len(ADMIN_USER_IDS)}\n"
                f"📈 可视化模板: 9\n"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(_t(update, "btn.back", "⬅️ 返回"), callback_data="admin_menu")],
            ])
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')
            return
        
        if button_data == "admin_users":
            # 管理员列表
            admin_list = "\n".join([f"• `{uid}`" for uid in ADMIN_USER_IDS]) or "无"
            text = (
                f"👥 **{_t(update, 'admin.users_title', '管理员列表')}**\n\n"
                f"{admin_list}\n\n"
                f"💡 在 `assets/config/.env` 中配置 `ADMIN_USER_IDS`"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(_t(update, "btn.back", "⬅️ 返回"), callback_data="admin_menu")],
            ])
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')
            return
        
        if button_data == "admin_cache":
            # 缓存信息
            cache_keys = list(cache.keys())[:10] if cache else []
            cache_list = "\n".join([f"• {k}" for k in cache_keys]) or "空"
            text = (
                f"🗄️ **{_t(update, 'admin.cache_title', '缓存状态')}**\n\n"
                f"总条目: {len(cache.keys()) if cache else 0}\n"
                f"前10个:\n{cache_list}"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(_t(update, "btn.back", "⬅️ 返回"), callback_data="admin_menu")],
            ])
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')
            return
        
        if button_data == "admin_reload":
            # 重载配置
            _load_admin_ids()
            text = f"✅ {_t(update, 'admin.reloaded', '配置已重载')}\n\n管理员数量: {len(ADMIN_USER_IDS)}"
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(_t(update, "btn.back", "⬅️ 返回"), callback_data="admin_menu")],
            ])
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')
            return

    # 可视化菜单
    if button_data == "vis_menu" or button_data.startswith("vis_"):
        try:
            from bot.vis_handler import vis_callback_handler
            handled = await vis_callback_handler(update, context)
            if handled:
                return
        except Exception as e:
            logger.error(f"可视化界面失败: {e}")
            await query.answer(_t(update, "error.vis_failed", fallback="可视化功能暂不可用"), show_alert=True)
            return

    # 信号推送的币种分析跳转
    if button_data.startswith("single_query_"):
        symbol = button_data.replace("single_query_", "")
        # 注意: 即时响应已在前面统一处理，此处不再重复 query.answer()
        try:
            if os.getenv("DISABLE_SINGLE_TOKEN_QUERY", "1") == "1":
                await query.edit_message_text(_t(update, "query.disabled"))
                return
            from bot.single_token_snapshot import SingleTokenSnapshot
            enabled_periods = {"1m": False, "5m": False, "15m": True, "1h": True, "4h": True, "1d": True, "1w": False}
            ustate = user_handler.user_states.setdefault(user_id, {})
            ustate["single_symbol"] = symbol
            ustate["single_panel"] = "basic"
            ustate["single_periods"] = enabled_periods
            ustate["single_cards"] = {}
            ustate["single_page"] = 0
            snap = SingleTokenSnapshot()
            lang = _resolve_lang(update)
            text, pages = snap.render_table(
                symbol,
                panel="basic",
                enabled_periods=enabled_periods,
                enabled_cards={},
                page=0,
                lang=lang,
            )
            kb = build_single_snapshot_keyboard(enabled_periods, "basic", {}, page=0, pages=pages, update=update, lang=lang, symbol=symbol)
            await query.edit_message_text(text, reply_markup=kb, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"单币查询跳转失败: {e}")
            await query.edit_message_text(_t("error.query_failed", update))
        return

    # 点击频率限制
    can_click, remaining_cooldown = check_click_rate_limit(user_id)
    if not can_click:
        await query.answer(_t("ui.please_wait", update), show_alert=False)
        return

    try:
        await query.answer(_t(update, "ui.processing"))
    except Exception:
        pass

    logger.info(f"🔍 按钮回调 / 用户: {user_id} / 按钮: {button_data}")

    # ---- 形态面板周期开关 ----
    if button_data.startswith("pattern_toggle_"):
        if user_handler is None:
            await query.edit_message_text(_t(update, "error.not_ready"), parse_mode='Markdown')
            await _trigger_user_handler_init()
            return
        states = user_handler.user_states.setdefault(user_id, {})
        sym = states.get("single_symbol")
        if not sym:
            await query.edit_message_text(_t(update, "query.hint"), parse_mode='Markdown')
            return
        pattern_periods = states.get("pattern_periods", {"1m": False, "5m": False, "15m": True, "1h": True, "4h": True, "1d": False, "1w": False})
        period = button_data.replace("pattern_toggle_", "")
        pattern_periods[period] = not pattern_periods.get(period, False)
        states["pattern_periods"] = pattern_periods

        from bot.single_token_snapshot import render_pattern_panel
        text = render_pattern_panel(sym, pattern_periods, lang=_resolve_lang(update))
        keyboard = build_pattern_keyboard_with_periods(pattern_periods)
        try:
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')
        except BadRequest:
            pass
        return

    # ---- 单币快照按钮处理 ----
    if button_data.startswith("single_"):
        if user_handler is None:
            await query.edit_message_text(_t(update, "error.not_ready"), parse_mode='Markdown')
            await _trigger_user_handler_init()
            return
        states = user_handler.user_states.setdefault(user_id, {})
        sym = states.get("single_symbol")
        panel = states.get("single_panel", "basic")
        enabled = states.get("single_periods", {"1m": False, "5m": False, "15m": True, "1h": True, "4h": True, "1d": True, "1w": False})
        enabled_cards = states.get("single_cards", {})
        page = states.get("single_page", 0)
        if not sym:
            await query.edit_message_text(_t(update, "query.hint"), parse_mode='Markdown')
            return

        reset_page = False
        if button_data.startswith("single_toggle_"):
            period = button_data.replace("single_toggle_", "")
            if panel == "futures" and period == "1m":
                await query.answer(_t("ui.futures_no_1m", update), show_alert=False)
            else:
                enabled[period] = not enabled.get(period, False)
                reset_page = True
        elif button_data.startswith("single_panel_"):
            panel = button_data.replace("single_panel_", "")
            # K线形态独立面板
            if panel == "pattern":
                from bot.single_token_snapshot import render_pattern_panel
                states["single_panel"] = panel
                pattern_periods = states.get("pattern_periods", {"1m": False, "5m": False, "15m": True, "1h": True, "4h": True, "1d": False, "1w": False})
                text = render_pattern_panel(sym, pattern_periods, lang=_resolve_lang(update))
                keyboard = build_pattern_keyboard_with_periods(pattern_periods)
                try:
                    await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')
                except BadRequest as e:
                    if "message is not modified" not in str(e):
                        logger.error("形态面板渲染失败: %s", e)
                return
            if panel == "futures":
                enabled["1m"] = False
                enabled_cards = {}  # futures 默认全部启用
            elif panel == "basic":
                enabled_cards = {}  # basic 默认全部启用
            if panel == "advanced":
                from bot.single_token_snapshot import TABLE_FIELDS
                default_adv = {"EMA排行卡片", "ATR排行卡片", "超级精准趋势排行卡片"}
                enabled_cards = {k: (k in default_adv) for k in TABLE_FIELDS.get("advanced", {})}
            reset_page = True
        elif button_data.startswith("single_card_"):
            card = button_data.replace("single_card_", "")
            enabled_cards[card] = not enabled_cards.get(card, True)
            reset_page = True
        elif button_data == "single_refresh":
            # 形态面板刷新
            if panel == "pattern":
                from bot.single_token_snapshot import render_pattern_panel
                pattern_periods = states.get("pattern_periods", {"1m": False, "5m": False, "15m": True, "1h": True, "4h": True, "1d": False, "1w": False})
                text = render_pattern_panel(sym, pattern_periods, lang=_resolve_lang(update))
                keyboard = build_pattern_keyboard_with_periods(pattern_periods)
                try:
                    await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')
                except BadRequest:
                    pass
                return
            reset_page = False
        elif button_data == "single_page_prev":
            page = max(0, page - 1)
        elif button_data == "single_page_next":
            page = page + 1
        else:
            # single_nop 等
            return

        if reset_page:
            page = 0

        states["single_panel"] = panel
        states["single_periods"] = enabled
        states["single_cards"] = enabled_cards
        states["single_page"] = page

        lang = _resolve_lang(update)
        text, keyboard, pages, page_used = render_single_snapshot(sym, panel, enabled, enabled_cards, page=page, lang=lang, update=update)
        # 如果翻到超界页，回退最后一页再渲染一次
        if page_used >= pages:
            page_used = max(0, pages - 1)
            states["single_page"] = page_used
            text, keyboard, pages, page_used = render_single_snapshot(sym, panel, enabled, enabled_cards, page=page_used, lang=lang, update=update)
        try:
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')
        except BadRequest as e:
            msg = str(e)
            if "message is not modified" in msg:
                await query.edit_message_reply_markup(reply_markup=keyboard)
            elif "message is too long" in msg.lower():
                max_len = 3500
                parts = [text[i:i+max_len] for i in range(0, len(text), max_len)]
                await query.edit_message_text(parts[0], reply_markup=keyboard, parse_mode='Markdown')
                for p in parts[1:]:
                    await query.message.reply_text(p, parse_mode='Markdown')
            else:
                logger.error("单币快照编辑失败: %s", e)
                await query.message.reply_text(_t(update, "error.refresh_failed"), parse_mode='Markdown')
        return

    # ⚖️ 超买超卖卡片下线保护
    ratio_callbacks = (
        "position_market_ratio",
        "volume_market_ratio",
        "volume_oi_ratio",
        "unified_ratio",
        "ratio_",
        "ratio_sort_",
        "ratio_limit_",
        "ratio_period_",
        "volume_market_",
        "volume_oi_",
        "position_market_",
    )
    if any(button_data.startswith(prefix) for prefix in ratio_callbacks):
        await query.answer(_t("ui.card_offline", update), show_alert=False)
        await query.message.reply_text(
            _t(query, "feature.overbought_offline"),
            reply_markup=InlineKeyboardMarkup([[_btn(update, "btn.back_home", "main_menu")]]),
            parse_mode='Markdown'
        )
        return

    # 特殊处理：如果用户在AI对话中点击了其他功能按钮，强制结束AI对话状态
    if query.data in [
        "ranking_menu",
        "ranking_menu_group_recommend",
        "ranking_menu_group_basic",
        "ranking_menu_group_futures",
        "ranking_menu_group_advanced",
        "position_ranking",
        "funding_rate",
        "volume_ranking",
        "basic_market",
        "market_sentiment",
        "liquidation_ranking",
        "money_flow",
        "market_depth",
    ]:
        # 清理可能的AI对话状态
        if 'selected_symbol' in context.user_data:
            del context.user_data['selected_symbol']
        if 'selected_interval' in context.user_data:
            del context.user_data['selected_interval']
        if 'waiting_manual_input' in context.user_data:
            del context.user_data['waiting_manual_input']
        if 'symbols_page' in context.user_data:
            del context.user_data['symbols_page']

    if user_handler is None:
        logger.warning("⚠️ user_handler为None，尝试多种方式重新初始化...")
        try:
            # 方法1：尝试直接初始化
            from main import UserRequestHandler
            user_handler = UserRequestHandler(card_registry=ensure_ranking_registry())
            logger.info("✅ 直接初始化 user_handler 成功")
        except Exception as e1:
            logger.error(f"❌ 直接初始化失败: {e1}")
            try:
                # 方法2：使用异步执行器
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, initialize_bot_sync)
                if user_handler is not None:
                    logger.info("✅ 异步执行器重新初始化成功")
                else:
                    logger.error("❌ 所有初始化方法都失败")
                    await query.edit_message_text(
                        _t(update, "status.initializing"),
                        reply_markup=InlineKeyboardMarkup([[
                            _btn(update, "btn.retry", "main_menu")
                        ]])
                    )
                    return
            except Exception as e2:
                logger.error(f"❌ 异步重新初始化也失败: {e2}")
                await query.edit_message_text(
                    _t(update, "status.init_failed"),
                    reply_markup=InlineKeyboardMarkup([[
                        _btn(update, "btn.retry", "main_menu")
                    ]])
                )
                return

    registry = ensure_ranking_registry()
    if registry:
        handled = await registry.dispatch(update, context, {
            "user_handler": user_handler,
            "ensure_valid_text": ensure_valid_text,
        })
        if handled:
            return

    try:
        if query.data == "main_menu":
            try:
                # 🔧 强化主菜单文本处理：确保永远不为空
                try:
                    text = user_handler.get_main_menu_text(update)
                except Exception as e:
                    logger.warning(f"⚠️ 获取主菜单文本失败: {e}")
                    text = None

                # 强制检查：如果文本为空或无效，使用预设文本
                if not text or len(str(text).strip()) == 0:
                    logger.warning("⚠️ 主菜单文本为空，使用强制默认文本")
                    text = _t(update, "welcome.title")

                # 再次验证文本有效性
                text = ensure_valid_text(text, _t(update, "welcome.title"))

                # 强化键盘处理：确保永远有键盘
                try:
                    keyboard = user_handler.get_main_menu_keyboard(update)
                except Exception as e:
                    logger.warning(f"⚠️ 获取主菜单键盘失败: {e}")
                    keyboard = None

                if not keyboard:
                    logger.warning("⚠️ 主菜单键盘为空，使用强制默认键盘")
                    keyboard = InlineKeyboardMarkup([
                        [
                            _btn(update, "btn.position_ranking", "position_ranking"),
                            _btn(update, "btn.volume_ranking", "volume_ranking")
                        ],
                        [
                            _btn(update, "btn.liquidation_ranking", "liquidation_ranking"),
                            _btn(update, "btn.market_overview", "basic_market")
                        ],
                        [
                            _btn(update, "btn.refresh_menu", "main_menu")
                        ]
                    ])

                await query.edit_message_text(text, reply_markup=keyboard)

            except Exception as e:
                logger.error(f"❌ 主菜单处理错误: {e}")
                # 发送最简单的错误恢复消息
                try:
                    await query.edit_message_text(
                        f"{_t(update, 'welcome.title')}\n\n{_t(update, 'welcome.status')}",
                        reply_markup=InlineKeyboardMarkup([
                            [_btn(update, "btn.retry", "main_menu")]
                        ])
                    )
                except Exception:
                    await query.answer(_t("ui.system_reloading", update))

        elif query.data == "cancel_analysis":
            # 处理AI点位分析中的"返回主菜单"按钮
            # 清理AI对话状态
            if 'selected_symbol' in context.user_data:
                del context.user_data['selected_symbol']
            if 'selected_interval' in context.user_data:
                del context.user_data['selected_interval']
            if 'waiting_manual_input' in context.user_data:
                del context.user_data['waiting_manual_input']
            if 'symbols_page' in context.user_data:
                del context.user_data['symbols_page']

            # 直接返回主菜单，不显示中间提示
            text = user_handler.get_main_menu_text(update)
            keyboard = user_handler.get_main_menu_keyboard(update)
            text = ensure_valid_text(text, _t(query, "welcome.title"))
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

        elif query.data == "ranking_menu_nop":
            # 提示按钮，点击无响应 (即时响应已在前面统一处理)
            pass

        elif query.data == "coin_query":
            # 币种查询入口 - 显示配置的币种列表
            from common.symbols import get_configured_symbols
            symbols = get_configured_symbols()
            if symbols:
                # 去掉 USDT 后缀
                coins = [s.replace("USDT", "") for s in symbols]
                coins_text = "\n".join(coins)
            else:
                coins_text = "BTC\nETH\nSOL"
                coins = ["BTC", "ETH", "SOL"]
            text = (
                f"{_t(update, 'query.title')}\n\n"
                f"{_t(update, 'query.prompt')}\n"
                f"```\n{coins_text}\n```\n"
                f"{_t(update, 'query.format')}"
            )
            keyboard = InlineKeyboardMarkup([
                [
                    _btn(update, "btn.back_home", "main_menu"),
                ]
            ])
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

        elif query.data == "ranking_menu":
            current_group = user_handler.user_states.get("ranking_group", DEFAULT_RANKING_GROUP)
            keyboard = user_handler.get_ranking_menu_keyboard(update)
            await query.edit_message_text(
                _build_ranking_menu_text(current_group, update),
                reply_markup=keyboard,
                parse_mode='Markdown'
            )

        elif query.data.startswith("ranking_menu_group_"):
            group = query.data.replace("ranking_menu_group_", "")
            if group in ALLOWED_RANKING_GROUPS:
                user_handler.user_states["ranking_group"] = group
            current_group = user_handler.user_states.get("ranking_group", DEFAULT_RANKING_GROUP)
            keyboard = user_handler.get_ranking_menu_keyboard(update)
            await query.edit_message_text(
                _build_ranking_menu_text(current_group, update),
                reply_markup=keyboard,
                parse_mode='Markdown'
            )

        elif query.data == "market_sentiment":
            # 注意: 即时响应已在前面统一处理
            await query.message.reply_text(
                _t(query, "feature.sentiment_offline"),
                reply_markup=InlineKeyboardMarkup([[_btn(update, "btn.back_home", "main_menu")]]),
                parse_mode='Markdown'
            )

        elif query.data == "basic_market":
            # 免费功能 - 直接提供服务
            loop = asyncio.get_event_loop()

            # 安全获取用户状态，使用默认值
            sort_type = user_handler.user_states.get('basic_market_sort_type', 'change')
            period = user_handler.user_states.get('basic_market_period', '1d')
            sort_order = user_handler.user_states.get('basic_market_sort_order', 'desc')
            limit = user_handler.user_states.get('basic_market_limit', 10)
            market_type = user_handler.user_states.get('basic_market_type', 'futures')

            text = await loop.run_in_executor(None, lambda: user_handler.get_basic_market(
                sort_type=sort_type,
                period=period,
                sort_order=sort_order,
                limit=limit,
                market_type=market_type
            ))
            text = ensure_valid_text(text, _t(query, "loading.market"))
            keyboard = user_handler.get_basic_market_keyboard(
                current_sort_type=sort_type,
                current_period=period,
                current_sort_order=sort_order,
                current_limit=limit,
                current_market_type=market_type
            )
            await query.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')

        elif query.data == "money_flow":
            # 异步获取数据
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(
                None,
                lambda: user_handler.get_money_flow(
                    limit=user_handler.user_states['money_flow_limit'],
                    period=user_handler.user_states['money_flow_period'],
                    sort_order=user_handler.user_states['money_flow_sort'],
                    flow_type=user_handler.user_states['money_flow_type'],
                    market=user_handler.user_states['money_flow_market'],
                    update=update,
                ),
            )
            keyboard = user_handler.get_money_flow_keyboard(
                current_period=user_handler.user_states['money_flow_period'],
                current_sort=user_handler.user_states['money_flow_sort'],
                current_limit=user_handler.user_states['money_flow_limit'],
                current_flow_type=user_handler.user_states['money_flow_type'],
                current_market=user_handler.user_states['money_flow_market'],
                update=update,
            )
            text = ensure_valid_text(text, _t(query, "loading.money_flow"))

            await query.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')

        elif query.data == "market_depth":
            # 异步获取数据
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(
                None, user_handler.get_market_depth,
                user_handler.user_states.get('market_depth_limit', 10),
                user_handler.user_states.get('market_depth_sort_type', 'ratio'),
                user_handler.user_states.get('market_depth_sort', 'desc')
            )
            keyboard = user_handler.get_market_depth_keyboard(
                current_limit=user_handler.user_states.get('market_depth_limit', 10),
                current_sort_type=user_handler.user_states.get('market_depth_sort_type', 'ratio'),
                current_sort=user_handler.user_states.get('market_depth_sort', 'desc')
            )
            text = ensure_valid_text(text, _t(query, "loading.depth"))

            await query.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')

        # 智能数量选择按钮处理
        elif (
            "_" in query.data
            and query.data.split("_")[-1] in ["10", "20", "30"]
        ):
            # 解析按钮类型和数量
            parts = query.data.split("_")
            limit = int(parts[-1])
            feature_type = "_".join(parts[:-1])

            loop = asyncio.get_event_loop()

            # 根据功能类型更新用户状态并调用相应的方法
            if feature_type == "position":
                user_handler.user_states['position_limit'] = limit
                text = await loop.run_in_executor(
                    None,
                    lambda: user_handler.get_position_ranking(
                        limit=limit,
                        sort_order=user_handler.user_states['position_sort'],
                        period=user_handler.user_states['position_period'],
                        update=update,
                    ),
                )
                keyboard = user_handler.get_position_ranking_keyboard(
                    current_sort=user_handler.user_states['position_sort'],
                    current_limit=limit,
                    current_period=user_handler.user_states['position_period'],
                    update=update,
                )
            elif feature_type == "funding":
                user_handler.user_states['funding_limit'] = limit
                text = await loop.run_in_executor(
                    None, user_handler.get_funding_rate_ranking,
                    limit, user_handler.user_states['funding_sort']
                )
                keyboard = user_handler.get_funding_rate_keyboard(
                    current_sort=user_handler.user_states['funding_sort'],
                    current_limit=limit,
                    update=update,
                )
            elif feature_type == "liquidation":
                user_handler.user_states['liquidation_limit'] = limit
                text = await loop.run_in_executor(
                    None, user_handler.get_liquidation_ranking,
                    limit,
                    user_handler.user_states['liquidation_sort'],
                    user_handler.user_states['liquidation_period'],
                    user_handler.user_states['liquidation_type']
                )
                keyboard = user_handler.get_liquidation_ranking_keyboard(
                    current_limit=limit,
                    current_sort=user_handler.user_states['liquidation_sort'],
                    current_period=user_handler.user_states['liquidation_period'],
                    current_type=user_handler.user_states['liquidation_type']
                )

            elif feature_type == "money_flow":
                user_handler.user_states['money_flow_limit'] = limit
                text = await loop.run_in_executor(
                    None,
                    lambda: user_handler.get_money_flow(
                        limit=limit,
                        period=user_handler.user_states['money_flow_period'],
                        sort_order=user_handler.user_states['money_flow_sort'],
                        flow_type=user_handler.user_states['money_flow_type'],
                        market=user_handler.user_states['money_flow_market'],
                        update=update,
                    ),
                )
                keyboard = user_handler.get_money_flow_keyboard(
                    current_period=user_handler.user_states['money_flow_period'],
                    current_sort=user_handler.user_states['money_flow_sort'],
                    current_limit=limit,
                    current_flow_type=user_handler.user_states['money_flow_type'],
                    current_market=user_handler.user_states['money_flow_market'],
                    update=update,
                )
            elif feature_type == "market_depth":
                user_handler.user_states['market_depth_limit'] = limit
                text = await loop.run_in_executor(
                    None, user_handler.get_market_depth,
                    limit,
                    user_handler.user_states.get('market_depth_sort_type', 'ratio'),
                    user_handler.user_states.get('market_depth_sort', 'desc')
                )
                keyboard = user_handler.get_market_depth_keyboard(
                    current_limit=limit,
                    current_sort_type=user_handler.user_states.get('market_depth_sort_type', 'ratio'),
                    current_sort=user_handler.user_states.get('market_depth_sort', 'desc')
                )

            elif feature_type == "position_market":
                user_handler.user_states['position_market_limit'] = limit
                user_handler.user_states['current_ratio_type'] = 'position_market'
                text = await loop.run_in_executor(
                    None, user_handler.get_unified_ratio_data,
                    limit, user_handler.user_states['position_market_sort'], 'position_market'
                )
                keyboard = user_handler.get_unified_ratio_keyboard(
                    current_sort=user_handler.user_states['position_market_sort'],
                    current_limit=limit,
                    current_ratio_type='position_market'
                )
            elif feature_type == "basic_market":
                user_handler.user_states['basic_market_limit'] = limit
                text = await loop.run_in_executor(
                    None, lambda: user_handler.get_basic_market(
                        sort_type=user_handler.user_states['basic_market_sort_type'],
                        period=user_handler.user_states['basic_market_period'],
                        sort_order=user_handler.user_states['basic_market_sort_order'],
                        limit=limit,
                        market_type=user_handler.user_states['basic_market_type']
                    )
                )
                keyboard = user_handler.get_basic_market_keyboard(
                    current_sort_type=user_handler.user_states['basic_market_sort_type'],
                    current_period=user_handler.user_states['basic_market_period'],
                    current_sort_order=user_handler.user_states['basic_market_sort_order'],
                    current_limit=limit,
                    current_market_type=user_handler.user_states['basic_market_type']
                )
            elif feature_type == "unified_ratio":
                # 统一比率数量按钮处理
                # 使用当前比率类型状态
                current_ratio_type = user_handler.user_states.get('current_ratio_type', 'position_market')

                # 根据比率类型更新相应的数量状态
                if current_ratio_type == 'position_market':
                    current_sort = user_handler.user_states.get('position_market_sort', 'desc')
                    user_handler.user_states['position_market_limit'] = limit
                elif current_ratio_type == 'volume_market':
                    current_sort = user_handler.user_states.get('volume_market_sort', 'desc')
                    user_handler.user_states['volume_market_limit'] = limit
                elif current_ratio_type == 'volume_oi':
                    current_sort = user_handler.user_states.get('volume_oi_sort', 'desc')
                    user_handler.user_states['volume_oi_limit'] = limit
                else:
                    current_sort = 'desc'

                text = await loop.run_in_executor(
                    None, user_handler.get_unified_ratio_data,
                    limit, current_sort, current_ratio_type
                )
                keyboard = user_handler.get_unified_ratio_keyboard(
                    current_sort=current_sort,
                    current_limit=limit,
                    current_ratio_type=current_ratio_type
                )
            else:
                # 未知功能类型，返回主菜单
                loop = asyncio.get_event_loop()
                text = await loop.run_in_executor(None, lambda: user_handler.get_main_menu_text(update))
                keyboard = user_handler.get_main_menu_keyboard(update)

            text = ensure_valid_text(text, _t(query, "loading.data"))
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')



        # 比率类型选择按钮处理 - 使用统一数据函数
        elif query.data.startswith("ratio_type_"):
            ratio_type = query.data.replace("ratio_type_", "")
            loop = asyncio.get_event_loop()

            # 获取当前比率类型的状态，用于保持数量设置
            current_ratio_type = user_handler.user_states.get('current_ratio_type', 'position_market')

            # 获取当前显示的数量（从当前比率类型中获取）
            if current_ratio_type == "position_market":
                current_limit = user_handler.user_states.get('position_market_limit', 10)
            elif current_ratio_type == "volume_market":
                current_limit = user_handler.user_states.get('volume_market_limit', 10)
            elif current_ratio_type == "volume_oi":
                current_limit = user_handler.user_states.get('volume_oi_limit', 10)
            else:
                current_limit = 10

            # 更新当前比率类型状态
            user_handler.user_states['current_ratio_type'] = ratio_type

            # 获取新比率类型的排序状态，但保持当前的数量设置
            if ratio_type == "position_market":
                current_sort = user_handler.user_states.get('position_market_sort', 'desc')
                # 同步数量到新的比率类型
                user_handler.user_states['position_market_limit'] = current_limit
            elif ratio_type == "volume_market":
                current_sort = user_handler.user_states.get('volume_market_sort', 'desc')
                # 同步数量到新的比率类型
                user_handler.user_states['volume_market_limit'] = current_limit
            elif ratio_type == "volume_oi":
                current_sort = user_handler.user_states.get('volume_oi_sort', 'desc')
                # 同步数量到新的比率类型
                user_handler.user_states['volume_oi_limit'] = current_limit
            else:
                current_sort = 'desc'

            # 使用统一数据函数
            text = await loop.run_in_executor(
                None, user_handler.get_unified_ratio_data,
                current_limit, current_sort, ratio_type
            )
            keyboard = user_handler.get_unified_ratio_keyboard(
                current_sort=current_sort,
                current_limit=current_limit,
                current_ratio_type=ratio_type
            )

            text = ensure_valid_text(text, _t(query, "loading.data"))
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

        # 统一比率排序按钮处理
        elif query.data.startswith("unified_ratio_sort_"):
            sort_order = query.data.replace("unified_ratio_sort_", "")
            loop = asyncio.get_event_loop()

            # 使用当前比率类型状态
            current_ratio_type = user_handler.user_states.get('current_ratio_type', 'position_market')

            # 根据比率类型更新相应的排序状态
            if current_ratio_type == 'position_market':
                current_limit = user_handler.user_states.get('position_market_limit', 10)
                user_handler.user_states['position_market_sort'] = sort_order
            elif current_ratio_type == 'volume_market':
                current_limit = user_handler.user_states.get('volume_market_limit', 10)
                user_handler.user_states['volume_market_sort'] = sort_order
            elif current_ratio_type == 'volume_oi':
                current_limit = user_handler.user_states.get('volume_oi_limit', 10)
                user_handler.user_states['volume_oi_sort'] = sort_order
            else:
                current_limit = 10

            text = await loop.run_in_executor(
                None, user_handler.get_unified_ratio_data,
                current_limit, sort_order, current_ratio_type
            )
            keyboard = user_handler.get_unified_ratio_keyboard(
                current_sort=sort_order,
                current_limit=current_limit,
                current_ratio_type=current_ratio_type
            )

            text = ensure_valid_text(text, _t(query, "loading.data"))
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')


        # 统一比率刷新按钮处理
        elif query.data == "unified_ratio_refresh":
            loop = asyncio.get_event_loop()

            # 使用当前比率类型状态
            current_ratio_type = user_handler.user_states.get('current_ratio_type', 'position_market')

            # 根据比率类型获取相应的状态
            if current_ratio_type == 'position_market':
                current_limit = user_handler.user_states.get('position_market_limit', 10)
                current_sort = user_handler.user_states.get('position_market_sort', 'desc')
            elif current_ratio_type == 'volume_market':
                current_limit = user_handler.user_states.get('volume_market_limit', 10)
                current_sort = user_handler.user_states.get('volume_market_sort', 'desc')
            elif current_ratio_type == 'volume_oi':
                current_limit = user_handler.user_states.get('volume_oi_limit', 10)
                current_sort = user_handler.user_states.get('volume_oi_sort', 'desc')
            else:
                current_limit = 10
                current_sort = 'desc'

            # 异步获取数据
            text = await loop.run_in_executor(
                None, user_handler.get_unified_ratio_data,
                current_limit, current_sort, current_ratio_type
            )
            keyboard = user_handler.get_unified_ratio_keyboard(
                current_sort=current_sort,
                current_limit=current_limit,
                current_ratio_type=current_ratio_type
            )

            text = ensure_valid_text(text, _t(query, "loading.data"))
            await query.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')

        # 交易量/市值比排序按钮处理
        elif query.data.startswith("volume_market_sort_"):
            sort_order = query.data.replace("volume_market_sort_", "")
            user_handler.user_states['volume_market_sort'] = sort_order
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(
                None, user_handler.get_volume_market_ratio,
                user_handler.user_states.get('volume_market_limit', 10), sort_order
            )
            keyboard = user_handler.get_volume_market_ratio_keyboard(current_sort=sort_order, current_limit=user_handler.user_states.get('volume_market_limit', 10))
            text = ensure_valid_text(text, _t(query, "loading.volume_market"))
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

        # 交易量/市值比数量按钮处理
        elif query.data.startswith("volume_market_") and query.data.replace("volume_market_", "").isdigit():
            limit = int(query.data.replace("volume_market_", ""))
            user_handler.user_states['volume_market_limit'] = limit
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(
                None, user_handler.get_volume_market_ratio,
                limit, user_handler.user_states.get('volume_market_sort', 'desc')
            )
            keyboard = user_handler.get_volume_market_ratio_keyboard(current_sort=user_handler.user_states.get('volume_market_sort', 'desc'), current_limit=limit)
            text = ensure_valid_text(text, _t(query, "loading.volume_market"))
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

        # 交易量/持仓量比排序按钮处理
        elif query.data.startswith("volume_oi_sort_"):
            sort_order = query.data.replace("volume_oi_sort_", "")
            user_handler.user_states['volume_oi_sort'] = sort_order
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(
                None, user_handler.get_volume_oi_ratio,
                user_handler.user_states.get('volume_oi_limit', 10), sort_order
            )
            keyboard = user_handler.get_volume_oi_ratio_keyboard(current_sort=sort_order, current_limit=user_handler.user_states.get('volume_oi_limit', 10))
            text = ensure_valid_text(text, _t(query, "loading.volume_oi"))
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

        # 交易量/持仓量比数量按钮处理
        elif query.data.startswith("volume_oi_") and query.data.replace("volume_oi_", "").isdigit():
            limit = int(query.data.replace("volume_oi_", ""))
            user_handler.user_states['volume_oi_limit'] = limit
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(
                None, user_handler.get_volume_oi_ratio,
                limit, user_handler.user_states.get('volume_oi_sort', 'desc')
            )
            keyboard = user_handler.get_volume_oi_ratio_keyboard(current_sort=user_handler.user_states.get('volume_oi_sort', 'desc'), current_limit=limit)
            text = ensure_valid_text(text, _t(query, "loading.volume_oi"))
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

        # 持仓/市值比数量按钮处理
        elif query.data.startswith("position_market_") and query.data.replace("position_market_", "").isdigit():
            limit = int(query.data.replace("position_market_", ""))
            user_handler.user_states['position_market_limit'] = limit
            user_handler.user_states['current_ratio_type'] = 'position_market'
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(
                None, user_handler.get_unified_ratio_data,
                limit, user_handler.user_states['position_market_sort'], 'position_market'
            )
            keyboard = user_handler.get_unified_ratio_keyboard(
                current_sort=user_handler.user_states['position_market_sort'],
                current_limit=limit,
                current_ratio_type='position_market'
            )
            text = ensure_valid_text(text, _t(query, "loading.position_market"))
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

        # 资金流向周期选择按钮处理
        # 资金流向类型选择按钮处理
        elif query.data.startswith("money_flow_type_"):
            flow_type = query.data.replace("money_flow_type_", "")
            user_handler.user_states['money_flow_type'] = flow_type
            loop = asyncio.get_event_loop()

            text = await loop.run_in_executor(None, lambda: user_handler.get_money_flow(
                limit=user_handler.user_states['money_flow_limit'],
                period=user_handler.user_states['money_flow_period'],
                sort_order=user_handler.user_states['money_flow_sort'],
                flow_type=flow_type,
                market=user_handler.user_states['money_flow_market'],
                update=update,
            ))

            text = ensure_valid_text(text, _t(query, "loading.data"))
            keyboard = user_handler.get_money_flow_keyboard(
                current_period=user_handler.user_states['money_flow_period'],
                current_sort=user_handler.user_states['money_flow_sort'],
                current_limit=user_handler.user_states['money_flow_limit'],
                current_flow_type=flow_type,
                current_market=user_handler.user_states['money_flow_market'],
                update=update,
            )
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

        # 资金流向市场选择按钮处理
        elif query.data.startswith("money_flow_market_"):
            market = query.data.replace("money_flow_market_", "")
            user_handler.user_states['money_flow_market'] = market
            # 现货模式现在也支持市值排序，不需要重置
            loop = asyncio.get_event_loop()

            text = await loop.run_in_executor(None, lambda: user_handler.get_money_flow(
                limit=user_handler.user_states['money_flow_limit'],
                period=user_handler.user_states['money_flow_period'],
                sort_order=user_handler.user_states['money_flow_sort'],
                flow_type=user_handler.user_states['money_flow_type'],
                market=market,
                update=update,
            ))

            text = ensure_valid_text(text, _t(query, "loading.data"))
            keyboard = user_handler.get_money_flow_keyboard(
                current_period=user_handler.user_states['money_flow_period'],
                current_sort=user_handler.user_states['money_flow_sort'],
                current_limit=user_handler.user_states['money_flow_limit'],
                current_flow_type=user_handler.user_states['money_flow_type'],
                current_market=market,
                update=update,
            )
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

        # 资金流向排序选择按钮处理
        elif query.data.startswith("money_flow_sort_"):
            sort_order = query.data.replace("money_flow_sort_", "")
            user_handler.user_states['money_flow_sort'] = sort_order
            loop = asyncio.get_event_loop()

            text = await loop.run_in_executor(None, lambda: user_handler.get_money_flow(
                limit=user_handler.user_states['money_flow_limit'],
                period=user_handler.user_states['money_flow_period'],
                sort_order=sort_order,
                flow_type=user_handler.user_states['money_flow_type'],
                market=user_handler.user_states['money_flow_market'],
                update=update,
            ))

            text = ensure_valid_text(text, _t(query, "loading.data"))
            keyboard = user_handler.get_money_flow_keyboard(
                current_period=user_handler.user_states['money_flow_period'],
                current_sort=sort_order,
                current_limit=user_handler.user_states['money_flow_limit'],
                current_flow_type=user_handler.user_states['money_flow_type'],
                current_market=user_handler.user_states['money_flow_market'],
                update=update,
            )
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

        # 资金流向时间周期选择按钮处理
        elif query.data.startswith("money_flow_period_"):
            period = query.data.replace("money_flow_period_", "")
            user_handler.user_states['money_flow_period'] = period
            loop = asyncio.get_event_loop()

            text = await loop.run_in_executor(None, lambda: user_handler.get_money_flow(
                limit=user_handler.user_states['money_flow_limit'],
                period=period,
                sort_order=user_handler.user_states['money_flow_sort'],
                flow_type=user_handler.user_states['money_flow_type'],
                market=user_handler.user_states['money_flow_market'],
                update=update,
            ))

            text = ensure_valid_text(text, _t(query, "loading.data"))
            keyboard = user_handler.get_money_flow_keyboard(
                current_period=period,
                current_sort=user_handler.user_states['money_flow_sort'],
                current_limit=user_handler.user_states['money_flow_limit'],
                current_flow_type=user_handler.user_states['money_flow_type'],
                current_market=user_handler.user_states['money_flow_market'],
                update=update,
            )
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

        # 基础行情 - 市场类型选择按钮处理
        elif query.data.startswith("basic_market_type_"):
            market_type = query.data.replace("basic_market_type_", "")
            user_handler.user_states['basic_market_type'] = market_type
            loop = asyncio.get_event_loop()

            text = await loop.run_in_executor(None, lambda: user_handler.get_basic_market(
                sort_type=user_handler.user_states['basic_market_sort_type'],
                period=user_handler.user_states['basic_market_period'],
                sort_order=user_handler.user_states['basic_market_sort_order'],
                limit=user_handler.user_states['basic_market_limit'],
                market_type=market_type
            ))

            text = ensure_valid_text(text, _t(query, "loading.data"))
            keyboard = user_handler.get_basic_market_keyboard(
                current_sort_type=user_handler.user_states['basic_market_sort_type'],
                current_period=user_handler.user_states['basic_market_period'],
                current_sort_order=user_handler.user_states['basic_market_sort_order'],
                current_limit=user_handler.user_states['basic_market_limit'],
                current_market_type=market_type
            )
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

        # 基础行情 - 排序类型选择按钮处理
        elif query.data.startswith("basic_market_sort_type_"):
            sort_type = query.data.replace("basic_market_sort_type_", "")
            user_handler.user_states['basic_market_sort_type'] = sort_type
            loop = asyncio.get_event_loop()

            text = await loop.run_in_executor(None, lambda: user_handler.get_basic_market(
                sort_type=sort_type,
                period=user_handler.user_states['basic_market_period'],
                sort_order=user_handler.user_states['basic_market_sort_order'],
                limit=user_handler.user_states['basic_market_limit'],
                market_type=user_handler.user_states['basic_market_type']
            ))

            text = ensure_valid_text(text, _t(query, "loading.data"))
            keyboard = user_handler.get_basic_market_keyboard(
                current_sort_type=sort_type,
                current_period=user_handler.user_states['basic_market_period'],
                current_sort_order=user_handler.user_states['basic_market_sort_order'],
                current_limit=user_handler.user_states['basic_market_limit'],
                current_market_type=user_handler.user_states['basic_market_type']
            )
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

        # 基础行情 - 时间周期选择按钮处理
        elif query.data.startswith("basic_market_period_"):
            period = query.data.replace("basic_market_period_", "")
            user_handler.user_states['basic_market_period'] = period
            loop = asyncio.get_event_loop()

            text = await loop.run_in_executor(None, lambda: user_handler.get_basic_market(
                sort_type=user_handler.user_states['basic_market_sort_type'],
                period=period,
                sort_order=user_handler.user_states['basic_market_sort_order'],
                limit=user_handler.user_states['basic_market_limit'],
                market_type=user_handler.user_states['basic_market_type']
            ))

            text = ensure_valid_text(text, _t(query, "loading.data"))
            keyboard = user_handler.get_basic_market_keyboard(
                current_sort_type=user_handler.user_states['basic_market_sort_type'],
                current_period=period,
                current_sort_order=user_handler.user_states['basic_market_sort_order'],
                current_limit=user_handler.user_states['basic_market_limit'],
                current_market_type=user_handler.user_states['basic_market_type']
            )
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

        # 基础行情 - 排序方向选择按钮处理
        elif query.data.startswith("basic_market_sort_order_"):
            sort_order = query.data.replace("basic_market_sort_order_", "")
            user_handler.user_states['basic_market_sort_order'] = sort_order
            loop = asyncio.get_event_loop()

            text = await loop.run_in_executor(None, lambda: user_handler.get_basic_market(
                sort_type=user_handler.user_states['basic_market_sort_type'],
                period=user_handler.user_states['basic_market_period'],
                sort_order=sort_order,
                limit=user_handler.user_states['basic_market_limit'],
                market_type=user_handler.user_states['basic_market_type']
            ))

            text = ensure_valid_text(text, _t(query, "loading.data"))
            keyboard = user_handler.get_basic_market_keyboard(
                current_sort_type=user_handler.user_states['basic_market_sort_type'],
                current_period=user_handler.user_states['basic_market_period'],
                current_sort_order=sort_order,
                current_limit=user_handler.user_states['basic_market_limit'],
                current_market_type=user_handler.user_states['basic_market_type']
            )
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

        # 市场深度 - 排序类型选择按钮处理
        elif query.data.startswith("market_depth_sort_type_"):
            sort_type = query.data.replace("market_depth_sort_type_", "")
            user_handler.user_states['market_depth_sort_type'] = sort_type
            loop = asyncio.get_event_loop()

            text = await loop.run_in_executor(
                None, user_handler.get_market_depth,
                user_handler.user_states.get('market_depth_limit', 10),
                sort_type,
                user_handler.user_states.get('market_depth_sort', 'desc')
            )

            text = ensure_valid_text(text, _t(query, "loading.data"))
            keyboard = user_handler.get_market_depth_keyboard(
                current_limit=user_handler.user_states.get('market_depth_limit', 10),
                current_sort_type=sort_type,
                current_sort=user_handler.user_states.get('market_depth_sort', 'desc')
            )
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

        # 市场深度 - 排序方向选择按钮处理
        elif query.data.startswith("market_depth_sort_"):
            sort_order = query.data.replace("market_depth_sort_", "")
            user_handler.user_states['market_depth_sort'] = sort_order
            loop = asyncio.get_event_loop()

            text = await loop.run_in_executor(
                None, user_handler.get_market_depth,
                user_handler.user_states.get('market_depth_limit', 10),
                user_handler.user_states.get('market_depth_sort_type', 'ratio'),
                sort_order
            )

            text = ensure_valid_text(text, _t(query, "loading.data"))
            keyboard = user_handler.get_market_depth_keyboard(
                current_limit=user_handler.user_states.get('market_depth_limit', 10),
                current_sort_type=user_handler.user_states.get('market_depth_sort_type', 'ratio'),
                current_sort=sort_order
            )
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

        # 爆仓排行榜 - 时间周期选择按钮处理
        elif query.data.startswith("liquidation_period_"):
            period = query.data.replace("liquidation_period_", "")
            user_handler.user_states['liquidation_period'] = period
            loop = asyncio.get_event_loop()

            text = await loop.run_in_executor(
                None, user_handler.get_liquidation_ranking,
                user_handler.user_states['liquidation_limit'],
                user_handler.user_states['liquidation_sort'],
                period,
                user_handler.user_states['liquidation_type']
            )

            text = ensure_valid_text(text, _t(query, "loading.data"))
            keyboard = user_handler.get_liquidation_ranking_keyboard(
                current_limit=user_handler.user_states['liquidation_limit'],
                current_sort=user_handler.user_states['liquidation_sort'],
                current_period=period,
                current_type=user_handler.user_states['liquidation_type']
            )
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

        # 爆仓排行榜 - 数据类型选择按钮处理
        elif query.data.startswith("liquidation_type_"):
            liquidation_type = query.data.replace("liquidation_type_", "")
            user_handler.user_states['liquidation_type'] = liquidation_type
            loop = asyncio.get_event_loop()

            text = await loop.run_in_executor(
                None, user_handler.get_liquidation_ranking,
                user_handler.user_states['liquidation_limit'],
                user_handler.user_states['liquidation_sort'],
                user_handler.user_states['liquidation_period'],
                liquidation_type
            )

            text = ensure_valid_text(text, _t(query, "loading.data"))
            keyboard = user_handler.get_liquidation_ranking_keyboard(
                current_limit=user_handler.user_states['liquidation_limit'],
                current_sort=user_handler.user_states['liquidation_sort'],
                current_period=user_handler.user_states['liquidation_period'],
                current_type=liquidation_type
            )
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

        # 爆仓排行榜 - 排序选择按钮处理
        elif query.data.startswith("liquidation_sort_"):
            sort_order = query.data.replace("liquidation_sort_", "")
            user_handler.user_states['liquidation_sort'] = sort_order
            loop = asyncio.get_event_loop()

            text = await loop.run_in_executor(
                None, user_handler.get_liquidation_ranking,
                user_handler.user_states['liquidation_limit'],
                sort_order,
                user_handler.user_states['liquidation_period'],
                user_handler.user_states['liquidation_type']
            )

            text = ensure_valid_text(text, _t(query, "loading.data"))
            keyboard = user_handler.get_liquidation_ranking_keyboard(
                current_limit=user_handler.user_states['liquidation_limit'],
                current_sort=sort_order,
                current_period=user_handler.user_states['liquidation_period'],
                current_type=user_handler.user_states['liquidation_type']
            )
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

        elif query.data in ["coin_search", "help", "aggregated_alerts", "subscription"]:
            feature_key = f"feature.name.{query.data}"

            if query.data == "help":
                await send_help_message(update, context, via_query=True)
            elif query.data == "coin_search":
                # 币种搜索 -> 跳转到币种查询
                from common.symbols import get_configured_symbols
                symbols = get_configured_symbols()
                coins = [s.replace("USDT", "") for s in symbols] if symbols else ["BTC", "ETH", "SOL"]
                coins_text = "\n".join(coins)
                text = (
                    f"{_t(update, 'query.title')}\n\n"
                    f"```\n{coins_text}\n```\n"
                    f"{_t(update, 'query.count', count=len(coins))}\n"
                    f"{_t(update, 'query.usage')}\n"
                    f"{_t(update, 'query.usage_interactive')}\n"
                    f"{_t(update, 'query.usage_export')}"
                )
                keyboard = InlineKeyboardMarkup([[_btn(update, "btn.back_home", "main_menu")]])
                await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')
                return
            else:
                feature_name = _t(update, feature_key)
                await query.message.reply_text(
                    _t(update, "feature.developing", name=feature_name),
                    reply_markup=InlineKeyboardMarkup([[
                        _btn(update, "btn.back_home", "main_menu")
                    ]]),
                    parse_mode='Markdown'
                )

        # 信号历史查询
        elif query.data == "signal_history":
            from signals.ui import get_history_text, get_history_kb
            text = get_history_text(limit=20)
            await query.edit_message_text(text, reply_markup=get_history_kb())

        # 信号/订阅/AI相关回调 - 统一返回开发中提示
        elif query.data in {"show_subscription", "show_subscription_settings",
                           "subscription_config", "subscription_help", "confirm_subscribe",
                           "confirm_unsubscribe", "aggregated_alerts", "start_coin_analysis",
                           "start_ai_analysis", "start_basis_analysis", "start_batch_analysis",
                           "symbols_prev_page", "symbols_next_page", "show_all_symbols",
                           "manual_input", "manual_input_text", "back_to_coin_selection",
                           "coin_page_prev", "coin_page_next", "analysis_depth", "analysis_point",
                           "refresh_main_menu"} or query.data.startswith(("toggle_", "page_", "reanalyze_", "coin_", "sort_", "interval_")):
            await query.edit_message_text(
                _t(update, "feature.coming_soon"),
                reply_markup=InlineKeyboardMarkup([[
                    _btn(update, "btn.back_home", "main_menu")
                ]]),
                parse_mode='Markdown'
            )

        # 其他按钮处理
        else:
            await query.message.reply_text(
                _t(update, "feature.developing", name=""),
                reply_markup=InlineKeyboardMarkup([[
                    _btn(update, "btn.back_home", "main_menu")
                ]]),
                parse_mode='Markdown'
            )

    except Exception as e:
        logger.error(f"按钮回调处理错误: {e}")
        try:
            await query.answer()
        except Exception:
            pass

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """帮助命令处理器"""
    global user_handler
    # 先发送带键盘的消息刷新底部键盘
    if user_handler:
        await update.message.reply_text(_t(update, "start.greet"), reply_markup=user_handler.get_reply_keyboard(update))
    await send_help_message(update, context, via_query=False)


async def lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """语言切换命令 /lang - 直接切换中英文"""
    user_id = getattr(getattr(update, "effective_user", None), "id", None)
    if user_id is None:
        return

    chat = getattr(update, "effective_chat", None)
    target_id = user_id
    # 群组/频道优先保存 chat_id 作为语言偏好，避免群内信号默认回退到英文
    if chat and getattr(chat, "type", None) in ("group", "supergroup", "channel"):
        target_id = getattr(chat, "id", user_id)
        _load_user_locales()
        current_lang = _user_locale_map.get(str(target_id), I18N.default_locale)
    else:
        current_lang = _resolve_lang(update)

    new_lang = "en" if current_lang == "zh_CN" else "zh_CN"
    _save_user_locale(target_id, new_lang)
    # 同步刷新 cards/i18n 模块的缓存
    try:
        from cards.i18n import reload_user_locale
        reload_user_locale()
    except Exception:
        pass
    context.user_data["lang_preference"] = new_lang

    lang_name = I18N.gettext(f"lang.{new_lang}", lang=new_lang)
    msg = I18N.gettext("lang.set", lang=new_lang, lang_name=lang_name)
    main_text = None
    main_keyboard = None
    reply_keyboard = None
    if user_handler:
        # 预构建主菜单与常驻键盘，避免重复调用时语言不一致
        reply_keyboard = user_handler.get_reply_keyboard(update)
        main_text = user_handler.get_main_menu_text(update)
        main_keyboard = user_handler.get_main_menu_keyboard(update)

    if getattr(update, "callback_query", None):
        await update.callback_query.answer(msg)
        if user_handler:
            # 发送新消息刷新底部键盘与主菜单
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=msg,
                reply_markup=reply_keyboard
            )
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=main_text,
                reply_markup=main_keyboard
            )
    elif getattr(update, "message", None):
        if user_handler:
            # 发送带底部键盘与主菜单的消息
            await update.message.reply_text(msg, reply_markup=reply_keyboard)
            await update.message.reply_text(main_text, reply_markup=main_keyboard)


# =============================================================================
# /env 命令 - 配置管理（为"最糟糕的用户"设计）
# =============================================================================
# 硬开关：彻底禁用环境变量管理功能（安全审计要求）
ENABLE_ENV_MANAGER = False

async def env_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """配置管理命令 /env - 友好的可视化配置界面"""
    # 硬开关检查 - 即使命令被注册也会被拦截
    if not ENABLE_ENV_MANAGER:
        await update.message.reply_text(_t(update, "admin.env.disabled"))
        return
    from bot.env_manager import (
        CONFIG_CATEGORIES, get_config, set_config, validate_config_value, EDITABLE_CONFIGS
    )
    
    args = context.args if context.args else []
    
    # /env - 显示友好的配置中心（主入口）
    if not args:
        # 按优先级排序分类
        sorted_cats = sorted(CONFIG_CATEGORIES.items(), key=lambda x: x[1].get("priority", 99))
        
        text = "⚙️ *配置中心*\n\n"
        text += "👋 在这里可以轻松调整 Bot 的各项设置\n\n"
        text += "👇 选择要配置的类别："
        
        # 构建分类按钮
        buttons = []
        for cat_id, cat_info in sorted_cats:
            name = cat_info.get("name", cat_id)
            buttons.append(InlineKeyboardButton(
                name,
                callback_data=f"env_cat_{cat_id}"
            ))
        
        # 每行 2 个按钮，更友好的布局
        keyboard_rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
        keyboard_rows.append([InlineKeyboardButton("🏠 返回主菜单", callback_data="main_menu")])
        keyboard = InlineKeyboardMarkup(keyboard_rows)
        
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')
        return
    
    # /env get <key> - 获取配置值（保留命令行方式，但用友好文案）
    if args[0].lower() == "get" and len(args) >= 2:
        key = args[1].upper()
        config_info = EDITABLE_CONFIGS.get(key, {})
        config_name = config_info.get("name", key)
        value = get_config(key)
        
        if value is not None:
            # 敏感配置脱敏显示
            if "TOKEN" in key or "SECRET" in key or "PASSWORD" in key:
                display_value = value[:4] + "****" + value[-4:] if len(value) > 8 else "****"
            else:
                display_value = value
            await update.message.reply_text(
                f"📋 *{config_name}*\n\n当前值：`{display_value}`",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                f"📋 *{config_name}*\n\n当前值：未设置",
                parse_mode='Markdown'
            )
        return
    
    # /env set <key> <value> - 设置配置值
    if args[0].lower() == "set" and len(args) >= 3:
        key = args[1].upper()
        value = " ".join(args[2:])
        
        # 验证配置值
        valid, msg = validate_config_value(key, value)
        if not valid:
            await update.message.reply_text(msg, parse_mode='Markdown')
            return
        
        # 设置配置
        success, result_msg = set_config(key, value)
        await update.message.reply_text(result_msg, parse_mode='Markdown')
        return
    
    # /env list - 列出可配置项
    if args[0].lower() == "list":
        lines = ["📋 *可配置的项目*\n"]
        for key, info in EDITABLE_CONFIGS.items():
            icon = info.get("icon", "⚙️")
            name = info.get("name", key)
            hot = "🚀" if info.get("hot_reload") else "⏳"
            lines.append(f"{icon} {name} {hot}")
        lines.append("\n🚀 = 立即生效  ⏳ = 重启生效")
        await update.message.reply_text("\n".join(lines), parse_mode='Markdown')
        return
    
    # 帮助信息 - 友好版
    help_text = """⚙️ *配置帮助*

最简单的方式：直接发送 `/env`，然后点击按钮操作~

如果你更喜欢命令行：

• `/env` - 打开配置中心
• `/env list` - 查看所有可配置项
• `/env get 配置名` - 查看某个配置
• `/env set 配置名 值` - 修改配置

💡 *小技巧*
发送 `/env` 后点按钮更方便哦！
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')


async def vol_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """交易量数据查询指令 /vol"""
    if not _is_command_allowed(update):
        return
    global user_handler
    if user_handler is None:
        await update.message.reply_text(_t(update, "start.initializing"))
        await _trigger_user_handler_init()
        return

    await _send_instant_reply(update, "loading.volume_market")

    try:
        loop = asyncio.get_event_loop()

        vol_limit = user_handler.user_states.get('volume_limit', 10)
        vol_period = user_handler.user_states.get('volume_period', '1d')
        vol_sort = user_handler.user_states.get('volume_sort', 'desc')
        text = await loop.run_in_executor(
            None,
            lambda: user_handler.get_volume_ranking(
                limit=vol_limit,
                period=vol_period,
                sort_order=vol_sort,
                update=update
            )
        )

        text = ensure_valid_text(text, _t(update, "loading.data"))
        keyboard = user_handler.get_volume_ranking_keyboard(current_period=user_handler.user_states['volume_period'], current_sort=user_handler.user_states['volume_sort'], current_limit=user_handler.user_states['volume_limit'])
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"交易量数据查询错误: {e}")
        await update.message.reply_text(
            _t(update, "error.volume_fetch", error=str(e)),
            parse_mode='Markdown'
        )

async def sentiment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """市场情绪数据查询指令 /sentiment"""
    if not _is_command_allowed(update):
        return
    global user_handler
    if user_handler is None:
        await update.message.reply_text(_t(update, "start.initializing"))
        await _trigger_user_handler_init()
        return

    await _send_instant_reply(update, "loading.sentiment")

    try:
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, user_handler.get_market_sentiment)
        text = ensure_valid_text(text, _t(update, "loading.sentiment"))
        keyboard = user_handler.get_market_sentiment_keyboard(update)
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"市场情绪数据查询错误: {e}")
        await update.message.reply_text(
            _t(update, "error.sentiment_fetch", error=str(e)),
            parse_mode='Markdown'
        )

async def market_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """基础行情数据查询指令 /market"""
    if not _is_command_allowed(update):
        return
    global user_handler
    if user_handler is None:
        await update.message.reply_text(_t(update, "start.initializing"))
        await _trigger_user_handler_init()
        return

    await _send_instant_reply(update, "loading.market")

    try:
        loop = asyncio.get_event_loop()

        text = await loop.run_in_executor(None, lambda: user_handler.get_basic_market(
            sort_type=user_handler.user_states['basic_market_sort_type'],
            period=user_handler.user_states['basic_market_period'],
            sort_order=user_handler.user_states['basic_market_sort_order'],
            limit=user_handler.user_states['basic_market_limit'],
            market_type=user_handler.user_states['basic_market_type']
        ))

        text = ensure_valid_text(text, _t(update, "loading.data"))
        keyboard = user_handler.get_basic_market_keyboard(
            current_sort_type=user_handler.user_states['basic_market_sort_type'],
            current_period=user_handler.user_states['basic_market_period'],
            current_sort_order=user_handler.user_states['basic_market_sort_order'],
            current_limit=user_handler.user_states['basic_market_limit'],
            current_market_type=user_handler.user_states['basic_market_type']
        )
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"基础行情数据查询错误: {e}")
        await update.message.reply_text(
            _t(update, "error.market_fetch", error=str(e)),
            parse_mode='Markdown'
        )

async def flow_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """资金流向数据查询指令 /flow"""
    if not _is_command_allowed(update):
        return
    global user_handler
    if user_handler is None:
        await update.message.reply_text(_t(update, "start.initializing"))
        await _trigger_user_handler_init()
        return

    await _send_instant_reply(update, "loading.money_flow")

    try:
        loop = asyncio.get_event_loop()

        mf_limit = user_handler.user_states.get('money_flow_limit', 10)
        mf_period = user_handler.user_states.get('money_flow_period', '1d')
        mf_sort = user_handler.user_states.get('money_flow_sort', 'desc')
        mf_type = user_handler.user_states.get('money_flow_type', 'absolute')
        mf_market = user_handler.user_states.get('money_flow_market', 'futures')
        text = await loop.run_in_executor(
            None,
            lambda: user_handler.get_money_flow(
                limit=mf_limit,
                period=mf_period,
                sort_order=mf_sort,
                flow_type=mf_type,
                market=mf_market,
                update=update,
            ),
        )

        text = ensure_valid_text(text, _t(update, "loading.data"))
        keyboard = user_handler.get_money_flow_keyboard(
            current_period=mf_period,
            current_sort=mf_sort,
            current_limit=mf_limit,
            current_flow_type=mf_type,
            current_market=mf_market,
            update=update,
        )
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"资金流向数据查询错误: {e}")
        await update.message.reply_text(
            _t(update, "error.flow_fetch", error=str(e)),
            parse_mode='Markdown'
        )

async def depth_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """市场深度数据查询指令 /depth"""
    if not _is_command_allowed(update):
        return
    global user_handler
    if user_handler is None:
        await update.message.reply_text(_t(update, "start.initializing"))
        await _trigger_user_handler_init()
        return

    await _send_instant_reply(update, "loading.depth")

    try:
        loop = asyncio.get_event_loop()

        text = await loop.run_in_executor(
            None, user_handler.get_market_depth,
            user_handler.user_states.get('market_depth_limit', 10),
            user_handler.user_states.get('market_depth_sort_type', 'ratio'),
            user_handler.user_states.get('market_depth_sort', 'desc')
        )

        text = ensure_valid_text(text, _t(update, "loading.data"))
        keyboard = user_handler.get_market_depth_keyboard(
            current_limit=user_handler.user_states.get('market_depth_limit', 10),
            current_sort_type=user_handler.user_states.get('market_depth_sort_type', 'ratio'),
            current_sort=user_handler.user_states.get('market_depth_sort', 'desc')
        )
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"市场深度数据查询错误: {e}")
        await update.message.reply_text(
            _t(update, "error.depth_fetch", error=str(e)),
            parse_mode='Markdown'
        )

async def ratio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """持仓/市值比数据查询指令 /ratio"""
    if not _is_command_allowed(update):
        return
    global user_handler
    if user_handler is None:
        await update.message.reply_text(_t(update, "start.initializing"))
        await _trigger_user_handler_init()
        return

    await _send_instant_reply(update, "loading.position_market")

    try:
        loop = asyncio.get_event_loop()

        text = await loop.run_in_executor(None, lambda: user_handler.get_position_market_ratio(
            user_handler.user_states['position_market_limit'],
            user_handler.user_states['position_market_sort']
        ))

        text = ensure_valid_text(text, _t(update, "loading.data"))
        keyboard = user_handler.get_position_market_ratio_keyboard(current_sort=user_handler.user_states['position_market_sort'], current_limit=user_handler.user_states['position_market_limit'])
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"持仓/市值比数据查询错误: {e}")
        await update.message.reply_text(
            _t(update, "error.ratio_fetch", error=str(e)),
            parse_mode='Markdown'
        )

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """币种查询指令 /search"""
    if not _is_command_allowed(update):
        return
    await update.message.reply_text(
        _t(update, "search.coming_soon"),
        reply_markup=InlineKeyboardMarkup([[
            _btn(update, "btn.back_home", "main_menu")
        ]]),
        parse_mode='Markdown'
    )

async def user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """用户中心指令 /user"""
    if not _is_command_allowed(update):
        return

async def alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """信号订阅指令 /alerts - 开发中"""
    if not _is_command_allowed(update):
        return
    await update.message.reply_text(_t(update, "signal.coming_soon"))

async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """信号订阅指令 /subscribe - 开发中"""
    if not _is_command_allowed(update):
        return
    await update.message.reply_text(_t(update, "signal.coming_soon"))

async def status_command_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """用户中心指令 /status"""
    if not _is_command_allowed(update):
        return

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示主菜单指令 /menu"""
    if not _is_command_allowed(update):
        return
    global user_handler
    if user_handler is None:
        await update.message.reply_text(_t(update, "start.initializing"))
        await _trigger_user_handler_init()
        return

    # 发送主菜单，保持永久常驻键盘
    reply_keyboard = user_handler.get_reply_keyboard(update)
    text = user_handler.get_main_menu_text(update)
    keyboard = user_handler.get_main_menu_keyboard(update)

    # 确保文本不为空
    text = ensure_valid_text(text, _t(update, "welcome.title"))

    # 先发送简短欢迎消息和常驻键盘来激活常驻键盘
    await update.message.reply_text(
        _t(update, "welcome.title"),
        reply_markup=reply_keyboard    # 使用常驻键盘
    )

    # 再发送完整主菜单文本和内联键盘
    await update.message.reply_text(
        text,
        reply_markup=keyboard          # 使用内联键盘
    )


async def data_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """数据面板指令 /data"""
    if not _is_command_allowed(update):
        return
    global user_handler
    if user_handler is None:
        await update.message.reply_text(_t(update, "start.initializing"))
        await _trigger_user_handler_init()
        return
    await _send_instant_reply(update, "loading.data")
    # 先发送带键盘的消息刷新底部键盘
    await update.message.reply_text(_t(update, "start.greet"), reply_markup=user_handler.get_reply_keyboard(update))
    text = _build_ranking_menu_text("basic", update)
    keyboard = user_handler.get_ranking_menu_keyboard(update)
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')


async def query_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """币种查询指令 /query [币种]"""
    if not _is_command_allowed(update):
        return
    args = context.args
    if args:
        # 直接查询指定币种
        allowed_raw, allowed_base = _build_allowed_symbol_sets(user_handler)
        sym = _resolve_symbol_input(args[0], allowed_raw=allowed_raw, allowed_base=allowed_base)
        if not sym:
            await update.message.reply_text(_t(update, "snapshot.error.no_symbol"))
            return
        # 触发单币查询
        update.message.text = f"{sym}!"
        await handle_keyboard_message(update, context, bypass_checks=True)
    else:
        await _send_instant_reply(update, "loading.query")
        # 显示币种列表
        from common.symbols import get_configured_symbols
        symbols = get_configured_symbols()
        coins = [s.replace("USDT", "") for s in symbols] if symbols else ["BTC", "ETH", "SOL"]
        coins_text = "\n".join(coins)
        text = (
            f"{_t(update, 'query.title')}\n\n"
            f"```\n{coins_text}\n```\n"
            f"{_t(update, 'query.count', count=len(coins))}\n"
            f"{_t(update, 'query.usage')}\n"
            f"{_t(update, 'query.usage_interactive')}\n"
            f"{_t(update, 'query.usage_export')}"
        )
        keyboard = InlineKeyboardMarkup([[_btn(update, "btn.back_home", "main_menu")]])
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')


async def ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI分析指令 /ai"""
    if not _is_command_allowed(update):
        return
    await _send_instant_reply(update, "loading.ai")
    try:
        # 记录用户语言偏好，贯通到 AI 服务
        context.user_data["lang_preference"] = _resolve_lang(update)
        from bot.ai_integration import get_ai_handler
        ai_handler = get_ai_handler(symbols_provider=lambda: user_handler.get_active_symbols() if user_handler else None)
        await ai_handler.start_ai_analysis(update, context)
    except ImportError as e:
        logger.warning(f"AI模块未安装: {e}")
        await update.message.reply_text(
            _t(update, "ai.not_installed"),
            reply_markup=InlineKeyboardMarkup([[_btn(update, "btn.back_home", "main_menu")]])
        )
    except Exception as e:
        logger.error(f"AI分析启动失败: {e}")
        await update.message.reply_text(
            _t(update, "ai.failed", error=e),
            reply_markup=InlineKeyboardMarkup([[_btn(update, "btn.back_home", "main_menu")]])
        )


async def vis_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """可视化指令 /vis"""
    if not _is_command_allowed(update):
        return
    global user_handler
    if user_handler is None:
        await update.message.reply_text(_t(update, "start.initializing"))
        await _trigger_user_handler_init()
        return
    await _send_instant_reply(update, "loading.vis")
    # 刷新底部键盘
    await update.message.reply_text(_t(update, "start.greet"), reply_markup=user_handler.get_reply_keyboard(update))
    # 显示可视化菜单
    try:
        from bot.vis_handler import get_vis_handler
        vis_handler = get_vis_handler()
        text = _t(update, "vis.menu.title", "📈 选择图表类型")
        keyboard = vis_handler.build_main_menu(update)
        await update.message.reply_text(text, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"可视化菜单加载失败: {e}")
        await update.message.reply_text(
            _t(update, "error.vis_failed", "可视化功能暂不可用"),
            reply_markup=InlineKeyboardMarkup([[_btn(update, "btn.back_home", "main_menu")]])
        )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """管理员配置指令 /admin"""
    if not _is_command_allowed(update):
        return
    # 检查是否为管理员
    if not _is_admin(update):
        await update.message.reply_text(_t(update, "admin.no_permission", "⛔ 您没有管理员权限"))
        return
    global user_handler
    if user_handler is None:
        await update.message.reply_text(_t(update, "start.initializing"))
        await _trigger_user_handler_init()
        return
    await _send_instant_reply(update, "loading.stats")
    # 显示管理面板
    text = _build_admin_menu_text(update)
    keyboard = _build_admin_menu_keyboard(update)
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')


def _build_admin_menu_text(update) -> str:
    """构建管理面板文本"""
    user_id = _get_user_id(update)
    admin_count = len(ADMIN_USER_IDS)
    return (
        f"⚙️ **{_t(update, 'admin.title', '管理面板')}**\n\n"
        f"👤 {_t(update, 'admin.your_id', '您的ID')}: `{user_id}`\n"
        f"👥 {_t(update, 'admin.admin_count', '管理员数量')}: {admin_count}\n"
        f"📊 {_t(update, 'admin.templates', '可视化模板')}: 9\n\n"
        f"💡 {_t(update, 'admin.hint', '管理员可访问高级配置和统计')}"
    )


def _build_admin_menu_keyboard(update) -> InlineKeyboardMarkup:
    """构建管理面板键盘"""
    lang = _resolve_lang(update) if update else I18N.default_locale
    keyboard = [
        [
            InlineKeyboardButton(I18N.gettext("admin.stats", lang=lang, fallback="📊 统计"), callback_data="admin_stats"),
            InlineKeyboardButton(I18N.gettext("admin.users", lang=lang, fallback="👥 用户"), callback_data="admin_users"),
        ],
        [
            InlineKeyboardButton(I18N.gettext("admin.cache", lang=lang, fallback="🗄️ 缓存"), callback_data="admin_cache"),
            InlineKeyboardButton(I18N.gettext("admin.reload", lang=lang, fallback="🔄 重载"), callback_data="admin_reload"),
        ],
        [
            InlineKeyboardButton(I18N.gettext("btn.back_home", lang=lang), callback_data="main_menu"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """健康检查 /ping"""
    try:
        cache_keys = list(cache.keys())
        latest_cache_ts = max((cache[k]['timestamp'] for k in cache_keys), default=0)
        age_seconds = int(time.time() - latest_cache_ts) if latest_cache_ts else None
        await update.message.reply_text('\n'.join([
            '✅ pong',
            f'BINANCE_API_DISABLED={BINANCE_API_DISABLED}',
            f'WEBSOCKET_MONITOR={os.getenv("ENABLE_WEBSOCKET_MONITOR", "0")}',
            f'cache_keys={len(cache_keys)}',
            f'cache_age_sec={age_seconds if age_seconds is not None else "n/a"}',
        ]))
    except Exception as e:
        await update.message.reply_text(f'❌ ping failed: {e}')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示机器人状态指令 /status"""
    if not _is_command_allowed(update):
        return
    global bot
    if bot is None:
        await update.message.reply_text(_t(update, "start.initializing"))
        await _trigger_user_handler_init()
        return

    await _send_instant_reply(update, "loading.stats")

    try:
        # 安全地获取缓存信息，避免Markdown解析错误
        def escape_markdown_safe(text):
            """安全转义Markdown特殊字符"""
            if not text:
                return text
            special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '/', '{', '}', '.', '!']
            for char in special_chars:
                text = text.replace(char, f'\\{char}')
            return text

        cache_info = bot.get_cache_file_info()
        cache_status = bot.get_cache_status()

        # 安全地格式化所有动态内容
        safe_cache_info = escape_markdown_safe(str(cache_info)) if cache_info else "缓存信息获取失败"
        safe_cache_status = escape_markdown_safe(str(cache_status)) if cache_status else "缓存状态获取失败"
        safe_current_file = escape_markdown_safe(str(bot._current_cache_file)) if bot._current_cache_file else "未知"

        status_text = f"""🤖tradecat机器人状态
- 已初始化: {'✅' if bot._is_initialized else '❌'}
- 后台更新: {'🔄 进行中' if bot._is_updating else '✅ 空闲'}
- 当前使用文件: {safe_current_file}

{safe_cache_info}

{safe_cache_status}

- 系统使用两个缓存文件轮替更新
- 更新时用户请求不受影响
- 自动清理过期的缓存文件
- 缓存有效期: 10分钟（宽松模式）

- 非阻塞后台更新
- 智能缓存降级
- 原子性文件操作
- 请求频率控制"""

        await update.message.reply_text(
            status_text,
            reply_markup=InlineKeyboardMarkup([[
                _btn(update, "btn.back_home", "main_menu")
            ]]),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"状态命令错误: {e}")
        await update.message.reply_text(_t(update, "error.status_failed"))

_TEXT_ACTION_INSTANT_KEYS = {
    "position_ranking": "loading.data",
    "funding_rate_ranking": "loading.data",
    "volume_ranking": "loading.data",
    "liquidation_ranking": "loading.data",
    "market_sentiment": "loading.sentiment",
    "basic_market": "loading.market",
    "money_flow": "loading.money_flow",
    "market_depth": "loading.depth",
    "ranking_menu": "loading.data",
    "signal_menu": "loading.switch",
    "start_coin_analysis": "loading.ai",
    "coin_query": "loading.query",
    "vis_menu": "loading.vis",
}

async def handle_keyboard_message(update: Update, context: ContextTypes.DEFAULT_TYPE, *, bypass_checks: bool = False):
    """处理常驻键盘按钮消息"""
    global user_handler

    # 安全检查
    if not update or not update.message or not hasattr(update.message, 'text') or not update.message.text:
        return

    # 全局权限拦截（群聊：允许“已知键盘文本”和 AI 触发词，即使未在白名单）
    if not bypass_checks and not _is_command_allowed(update):
        if getattr(update.message.chat, "type", "") in ("group", "supergroup"):
            text = update.message.text.strip()
            # 与下方 button_mapping 共享的快捷键文本（无需 admin/白名单）
            known_texts = {
                "🐋 持仓量排行", "💱 资金费率排行", "📈 成交量排行", "💥 爆仓排行",
                "🎭 市场情绪", "📡 行情总览", "📈 市场总览", "💧 资金流向排行",
                "🧊 市场深度排行", "📊 数据面板", "🚨 信号", "🔔 信号",
                "🤖 AI分析", "🔍 币种查询", "📈 可视化", "📈 Charts",
                "🏠 主菜单", "ℹ️ 帮助", "🌐 语言", "🌐 Language",
            }
            # 允许形如 "BTC@" 的 AI 触发词
            is_ai_trigger = text.endswith("@") and 2 <= len(text) <= 12
            if text not in known_texts and not is_ai_trigger:
                return
        else:
            return

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    except Exception:
        pass

    message_text = update.message.text
    lang = _resolve_lang(update)
    instant_replied = False

    async def _instant_once(key: Optional[str]) -> None:
        nonlocal instant_replied
        if instant_replied:
            return
        await _send_instant_reply(update, key)
        instant_replied = True

    # =============================================================================
    # 处理配置编辑的用户输入 - 已禁用
    # =============================================================================
    # if context.user_data.get("env_editing_key"):
    #     ... (env 配置编辑已禁用)

    if user_handler is None:
        logger.warning("user_handler 未初始化")
        await update.message.reply_text(_t(update, "start.initializing"))
        await _trigger_user_handler_init()
        return

    # 映射常驻键盘按钮到对应功能
    button_mapping = {
        "🐋 持仓量排行": "position_ranking",
        "💱 资金费率排行": "funding_rate_ranking",
        "📈 成交量排行": "volume_ranking",
        "💥 爆仓排行": "liquidation_ranking",
        "🎭 市场情绪": "market_sentiment",
        "📡 行情总览": "basic_market",
        "📈 市场总览": "basic_market",
        "💧 资金流向排行": "money_flow",
        "🧊 市场深度排行": "market_depth",
        I18N.gettext("kb.data", lang=lang): "ranking_menu",
        "📊 数据面板": "ranking_menu",
        "🚨 信号": "signal_menu",
        "🔔 信号": "signal_menu",
        I18N.gettext("kb.signal", lang=lang): "signal_menu",
        I18N.gettext("kb.ai", lang=lang): "start_coin_analysis",
        "🤖 AI分析": "start_coin_analysis",
        I18N.gettext("kb.query", lang=lang): "coin_query",
        "🔍 币种查询": "coin_query",
        I18N.gettext("kb.vis", lang=lang): "vis_menu",
        "📈 可视化": "vis_menu",
        "📈 Charts": "vis_menu",
        I18N.gettext("kb.home", lang=lang): "main_menu",
        "🏠 主菜单": "main_menu",

        I18N.gettext("kb.help", lang=lang): "help",
        "ℹ️ 帮助": "help",
        I18N.gettext("kb.lang", lang=lang): "lang_menu",
        "🌐 语言": "lang_menu",
        "🌐 Language": "lang_menu",
    }

    try:
        # -------- AI 分析触发：如 "btc@" 或 "BTC@" --------
        import re
        norm_text = (message_text or "").replace("\u200b", "").strip()
        if norm_text.startswith("!") and len(norm_text) > 1:
            norm_text = norm_text[1:].strip()
            if not any(ch in norm_text for ch in ("!", "！", "@")):
                norm_text = f"{norm_text}!"

        if "@" in norm_text:
            m = re.match(r'^([A-Za-z0-9]{2,15})@$', norm_text.strip())
            if m:
                try:
                    from bot.ai_integration import get_ai_handler, AI_SERVICE_AVAILABLE, SELECTING_INTERVAL
                    if not AI_SERVICE_AVAILABLE:
                        await update.message.reply_text(_t(update, "ai.not_installed"))
                        return
                    await _instant_once("loading.ai")
                    context.user_data["lang_preference"] = _resolve_lang(update)
                    ai_handler = get_ai_handler(symbols_provider=lambda: user_handler.get_active_symbols() if user_handler else None)
                    coin = m.group(1).upper()
                    context.user_data["ai_state"] = SELECTING_INTERVAL
                    await ai_handler.handle_coin_input(update, context, coin)
                    return
                except Exception as e:
                    logger.error(f"AI 分析触发失败: {e}")
                    await update.message.reply_text(_t(update, "ai.failed", error=e))
                    return

        allowed_raw, allowed_base = _build_allowed_symbol_sets(user_handler)

        # -------- AI 分析 TXT 导出：如 "btc@@" 或 "BTC＠＠" --------
        if "@@" in norm_text or "＠＠" in norm_text:
            token = _extract_symbol_at_token(norm_text, double_at=True)
            sym = _resolve_symbol_input(token, allowed_raw=allowed_raw, allowed_base=allowed_base) if token else None
            if not sym:
                await update.message.reply_text(_t(update, "snapshot.error.no_symbol"))
                return
            try:
                from bot.ai_integration import get_ai_handler, AI_SERVICE_AVAILABLE, SELECTING_INTERVAL
                if not AI_SERVICE_AVAILABLE:
                    await update.message.reply_text(_t(update, "ai.not_installed"))
                    return
                await _instant_once("loading.ai")

                ai_handler = get_ai_handler(
                    symbols_provider=lambda: user_handler.get_active_symbols() if user_handler else None
                )
                context.user_data["lang_preference"] = _resolve_lang(update)
                context.user_data["ai_export_txt"] = True
                context.user_data["ai_state"] = SELECTING_INTERVAL
                await ai_handler.handle_coin_input(update, context, sym)
            except Exception as e:
                logger.error(f"AI TXT 导出失败: {e}")
                await update.message.reply_text(_t(update, "ai.failed", error=e))
            return

        # -------- 单币双感叹号触发完整TXT：如 "btc!!" 或 "BTC！！" --------
        if "!!" in norm_text or "！！" in norm_text:
            token = _extract_symbol_token(norm_text, double_exclaim=True)
            sym = _resolve_symbol_input(token, allowed_raw=allowed_raw, allowed_base=allowed_base) if token else None
            if not sym:
                await update.message.reply_text(_t(update, "snapshot.error.no_symbol"))
                return
            try:
                await _instant_once("loading.query")
                from bot.single_token_txt import export_single_token_txt
                import io
                from datetime import datetime

                # 获取用户语言
                lang = _resolve_lang(update)
                txt_content = export_single_token_txt(sym, lang=lang)

                # 创建文件对象
                file_obj = io.BytesIO(txt_content.encode('utf-8'))
                file_obj.name = f"{sym}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

                # Binance 跳转按钮（与信号一致，默认永续）
                binance_btn = InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        I18N.gettext("btn.binance", lang=lang),
                        url=_build_binance_url(sym, market="futures")
                    )
                ]])

                # 发送文件
                await update.message.reply_document(
                    document=file_obj,
                    filename=file_obj.name,
                    caption=_t(update, "export.caption", symbol=sym),
                    reply_markup=binance_btn,
                )
            except Exception as e:
                logger.error(f"完整TXT导出失败: {e}")
                await update.message.reply_text(_t("error.export_failed", update))
            return

        # -------- 单币感叹号触发：如 "btc!" 或 "BTC！" --------
        sym = None
        if "!" in norm_text or "！" in norm_text:
            token = _extract_symbol_token(norm_text, double_exclaim=False)
            sym = _resolve_symbol_input(token, allowed_raw=allowed_raw, allowed_base=allowed_base) if token else None
        if sym:
            await _instant_once("loading.query")
            user_id = update.effective_user.id
            # 性能优化：临时关闭单币查询
            if os.getenv("DISABLE_SINGLE_TOKEN_QUERY", "1") == "1":
                await update.message.reply_text(_t(update, "query.disabled"))
                return
            # 默认周期开关：仅开 15m/1h/4h/1d，其他可通过按钮再开启
            enabled_periods = {"1m": False, "5m": False, "15m": True, "1h": True, "4h": True, "1d": True, "1w": False}
            # 持久化用户态（按 user_id 分桶），按钮可复用
            ustate = user_handler.user_states.setdefault(user_id, {})
            ustate["single_symbol"] = sym
            ustate["single_panel"] = "basic"
            ustate["single_periods"] = enabled_periods
            ustate["single_cards"] = {}  # 默认全开，按需存 False
            ustate["single_page"] = 0
            try:
                from bot.single_token_snapshot import SingleTokenSnapshot
                lang = _resolve_lang(update)
                kb = build_single_snapshot_keyboard(enabled_periods, "basic", ustate["single_cards"], page=0, pages=1, update=update, lang=lang, symbol=sym)
                snap = SingleTokenSnapshot()
                text, pages = snap.render_table(
                    sym,
                    panel="basic",
                    enabled_periods=enabled_periods,
                    enabled_cards=ustate["single_cards"],
                    page=0,
                    lang=lang,
                )
                kb = build_single_snapshot_keyboard(enabled_periods, "basic", ustate["single_cards"], page=0, pages=pages, update=update, lang=lang, symbol=sym)
                try:
                    await update.message.reply_text(text, reply_markup=kb, parse_mode='Markdown')
                except BadRequest as e:
                    msg = str(e).lower()
                    if "message is too long" in msg:
                        max_len = 3500
                        parts = [text[i:i+max_len] for i in range(0, len(text), max_len)]
                        await update.message.reply_text(parts[0], reply_markup=kb, parse_mode='Markdown')
                        for p in parts[1:]:
                            await update.message.reply_text(p, parse_mode='Markdown')
                    else:
                        raise
            except Exception as exc:
                logger.error("单币快照渲染失败: %s", exc)
                await update.message.reply_text(_t(update, "error.query_failed", error=""), parse_mode='Markdown')
            return
        if ("!" in norm_text or "！" in norm_text) and not sym:
            await update.message.reply_text(_t(update, "snapshot.error.no_symbol"))
            return

        if message_text in button_mapping:
            action = button_mapping[message_text]
            instant_key = _TEXT_ACTION_INSTANT_KEYS.get(action)
            if instant_key:
                await _instant_once(instant_key)

            if action == "lang_menu":
                await lang_command(update, context)
                return

            # 统一占位：未开放功能的提示
            if action == "aggregated_alerts":
                placeholder_kb = InlineKeyboardMarkup([[
                    _btn(update, "btn.back_home", "main_menu"),
                    _btn(update, "btn.refresh", "main_menu")
                ]])
                await update.message.reply_text(
                    "🚨 信号功能暂未开发",
                    reply_markup=placeholder_kb,
                    parse_mode='Markdown'
                )
                return

            # 信号开关界面
            if action == "signal_menu":
                try:
                    from signals import ui as signal_ui
                    await update.message.reply_text(
                        signal_ui.get_menu_text(update.effective_user.id),
                        reply_markup=signal_ui.get_menu_kb(update.effective_user.id, update=update),
                        parse_mode='HTML'
                    )
                except Exception as e:
                    logger.error(f"信号界面失败: {e}")
                    await update.message.reply_text(_t("error.signal_failed", update))
                return

            if action == "position_ranking":
                loop = asyncio.get_event_loop()
                text = await loop.run_in_executor(None, lambda: user_handler.get_position_ranking(
                    limit=user_handler.user_states.get('position_limit', 10),
                    sort_order=user_handler.user_states.get('position_sort', 'desc'),
                    period=user_handler.user_states.get('position_period', '1d'),
                    update=update
                ))
                text = ensure_valid_text(text, _t(update, "loading.data"))
                keyboard = user_handler.get_position_ranking_keyboard(
                    current_sort=user_handler.user_states.get('position_sort', 'desc'),
                    current_limit=user_handler.user_states.get('position_limit', 10),
                    current_period=user_handler.user_states.get('position_period', '1d')
                )
                await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')

            elif action == "funding_rate_ranking":
                await update.message.reply_text(_t("feature.coming_soon", update), parse_mode='Markdown')

            elif action == "volume_ranking":
                loop = asyncio.get_event_loop()
                # 修复: 使用具体的参数而不是通用的[:3]切片
                user_states = user_handler.user_states.get(update.effective_user.id, {})
                text = await loop.run_in_executor(None, lambda: user_handler.get_volume_ranking(
                    limit=user_states.get('volume_limit', 10),
                    period=user_states.get('volume_period', '1d'),
                    sort_order=user_states.get('volume_sort', 'desc'),
                    update=update
                ))
                text = ensure_valid_text(text, _t(update, "loading.data"))
                keyboard = user_handler.get_volume_ranking_keyboard(
                    current_period=user_states.get('volume_period', '1d'),
                    current_sort=user_states.get('volume_sort', 'desc'),
                    current_limit=user_states.get('volume_limit', 10)
                )
                await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')

            elif action == "liquidation_ranking":
                loop = asyncio.get_event_loop()
                # 修复: 使用具体的参数而不是通用的[:3]切片
                user_states = user_handler.user_states.get(update.effective_user.id, {})
                text = await loop.run_in_executor(None, lambda: user_handler.get_liquidation_ranking(
                    limit=user_states.get('liquidation_limit', 10),
                    sort_order=user_states.get('liquidation_sort', 'desc'),
                    period=user_states.get('liquidation_period', '1d'),
                    liquidation_type=user_states.get('liquidation_type', 'total')
                ))
                text = ensure_valid_text(text, _t(update, "loading.data"))
                keyboard = user_handler.get_liquidation_ranking_keyboard(
                    current_limit=user_states.get('liquidation_limit', 10),
                    current_sort=user_states.get('liquidation_sort', 'desc'),
                    current_period=user_states.get('liquidation_period', '1d'),
                    current_type=user_states.get('liquidation_type', 'total')
                )
                await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')

            elif action == "market_sentiment":
                await update.message.reply_text(
                    _t(update, "feature.sentiment_offline"),
                    reply_markup=user_handler.get_market_sentiment_keyboard(update),
                    parse_mode='Markdown'
                )

            elif action == "basic_market":
                loop = asyncio.get_event_loop()
                # 修复: 使用具体的参数而不是通用的[:3]切片
                user_states = user_handler.user_states.get(update.effective_user.id, {})
                text = await loop.run_in_executor(None, lambda: user_handler.get_basic_market(
                    sort_type=user_states.get('basic_market_sort_type', 'change'),
                    period=user_states.get('basic_market_period', '1d'),
                    sort_order=user_states.get('basic_market_sort_order', 'desc'),
                    limit=user_states.get('basic_market_limit', 10),
                    market_type=user_states.get('basic_market_type', 'futures')
                ))
                text = ensure_valid_text(text, _t(update, "loading.data"))
                keyboard = user_handler.get_basic_market_keyboard(
                    current_sort_type=user_states.get('basic_market_sort_type', 'change'),
                    current_period=user_states.get('basic_market_period', '1d'),
                    current_sort_order=user_states.get('basic_market_sort_order', 'desc'),
                    current_limit=user_states.get('basic_market_limit', 10),
                    current_market_type=user_states.get('basic_market_type', 'futures')
                )
                await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')

            elif action == "money_flow":
                loop = asyncio.get_event_loop()
                # 修复: 使用具体的参数而不是通用的[:3]切片
                user_states = user_handler.user_states.get(update.effective_user.id, {})
                text = await loop.run_in_executor(None, lambda: user_handler.get_money_flow(
                    period=user_states.get('money_flow_period', '1d'),
                    sort=user_states.get('money_flow_sort', 'net_inflow'),
                    limit=user_states.get('money_flow_limit', 10),
                    flow_type=user_states.get('money_flow_type', 'all'),
                    market=user_states.get('money_flow_market', 'spot')
                ))
                text = ensure_valid_text(text, _t(update, "loading.data"))
                keyboard = user_handler.get_money_flow_keyboard(
                    current_period=user_states.get('money_flow_period', '1d'),
                    current_sort=user_states.get('money_flow_sort', 'net_inflow'),
                    current_limit=user_states.get('money_flow_limit', 10),
                    current_flow_type=user_states.get('money_flow_type', 'all'),
                    current_market=user_states.get('money_flow_market', 'spot')
                )
                await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')

            elif action == "market_depth":
                await update.message.reply_text(
                    _t(update, "feature.depth_offline"),
                    reply_markup=user_handler.get_market_depth_keyboard(update=update),
                    parse_mode='Markdown'
                )

            elif action == "ranking_menu":
                # 数据面板入口：显示榜单列表
                text = _build_ranking_menu_text(
                    user_handler.user_states.get("ranking_group", DEFAULT_RANKING_GROUP),
                    update,
                )
                keyboard = user_handler.get_ranking_menu_keyboard(update)
                await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')

            elif action == "main_menu":
                # 修复: 使用与/start命令相同的逻辑，避免空字符串错误
                reply_keyboard = user_handler.get_reply_keyboard(update)  # 常驻键盘
                main_text = user_handler.get_main_menu_text(update)
                main_keyboard = user_handler.get_main_menu_keyboard(update)  # 内联键盘

                # 确保文本不为空
                main_text = ensure_valid_text(main_text, "⚡️欢迎使用交易猫")

                # 先发送简短欢迎消息和常驻键盘来激活常驻键盘
                await update.message.reply_text(
                    "⚡️欢迎使用交易猫",
                    reply_markup=reply_keyboard,      # 激活常驻键盘
                    parse_mode='Markdown'
                )

                # 再发送完整主菜单文本和内联键盘
                await update.message.reply_text(
                    main_text,
                    reply_markup=main_keyboard,     # 使用内联键盘
                    parse_mode='Markdown'
                )

            elif action == "help":
                await help_command(update, context)

            elif action == "coin_query":
                # 币种查询入口
                from common.symbols import get_configured_symbols
                symbols = get_configured_symbols()
                coins = [s.replace("USDT", "") for s in symbols] if symbols else ["BTC", "ETH", "SOL"]
                coins_text = "\n".join(coins)
                text = (
                    f"{_t(update, 'query.title')}\n\n"
                    f"```\n{coins_text}\n```\n"
                    f"{_t(update, 'query.count', count=len(coins))}\n"
                    f"{_t(update, 'query.usage')}\n"
                    f"{_t(update, 'query.usage_interactive')}\n"
                    f"{_t(update, 'query.usage_export')}"
                )
                keyboard = InlineKeyboardMarkup([[_btn(update, "btn.back_home", "main_menu")]])
                await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')

            elif action == "start_coin_analysis":
                # AI 分析入口
                try:
                    from bot.ai_integration import get_ai_handler, AI_SERVICE_AVAILABLE
                    if not AI_SERVICE_AVAILABLE:
                        await update.message.reply_text(_t(update, "ai.not_installed"))
                        return
                    context.user_data["lang_preference"] = _resolve_lang(update)
                    ai_handler = get_ai_handler(symbols_provider=lambda: user_handler.get_active_symbols() if user_handler else None)
                    await ai_handler.start_ai_analysis(update, context)
                except Exception as e:
                    logger.error(f"AI分析入口失败: {e}")
                    await update.message.reply_text(_t(update, "ai.failed", error=e))

            elif action == "vis_menu":
                # 可视化入口
                try:
                    from bot.vis_handler import get_vis_handler
                    vis_handler = get_vis_handler()
                    text = _t(update, "vis.menu.title", "📈 选择图表类型")
                    keyboard = vis_handler.build_main_menu(update)
                    await update.message.reply_text(text, reply_markup=keyboard)
                except Exception as e:
                    logger.error(f"可视化菜单加载失败: {e}")
                    await update.message.reply_text(_t(update, "error.vis_failed", "可视化功能暂不可用"))

            # env_back 功能已禁用
            # elif action == "env_back":
            #     # 配置中心入口
            #     from bot.env_manager import CONFIG_CATEGORIES
            #     sorted_cats = sorted(CONFIG_CATEGORIES.items(), key=lambda x: x[1].get("priority", 99))
            #     
            #     text = "⚙️ *配置中心*\n\n"
            #     text += "👋 在这里可以轻松调整 Bot 的各项设置\n\n"
            #     text += "👇 选择要配置的类别："
            #     
            #     buttons = []
            #     for cat_id, cat_info in sorted_cats:
            #         name = cat_info.get("name", cat_id)
            #         buttons.append(InlineKeyboardButton(name, callback_data=f"env_cat_{cat_id}"))
            #     
            #     keyboard_rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
            #     keyboard_rows.append([InlineKeyboardButton("🏠 返回主菜单", callback_data="main_menu")])
            #     keyboard = InlineKeyboardMarkup(keyboard_rows)
            #     
            #     await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')

            elif action in {"aggregated_alerts", "coin_search"}:
                await update.message.reply_text(_t(update, "feature.coming_soon"))
                return

        else:
            # 如果是斜杠开头但不是已知按钮，可能是命令，不做处理
            if message_text.startswith('/'):
                return

            # 未识别的消息，显示提示
            await update.message.reply_text(
                "🤔 没有识别到您的指令，请使用下方按钮或输入 /help 查看帮助。",
                parse_mode='Markdown'
            )
    except Exception as e:
        logger.error(f"处理键盘消息错误: {e}")
        await update.message.reply_text(
            _t(update, "error.request_failed", error=str(e)),
            parse_mode='Markdown'
        )

async def initialize_bot_background():
    """后台非阻塞初始化机器人和缓存 - 并行启动版本"""
    try:
        print("🚀 开始并行启动所有后台服务...")

        # 定义所有启动任务
        startup_tasks = []
        task_names = []

        # 1. 后台缓存初始化任务
        async def cache_init_task():
            try:
                print("📊 开始后台预加载数据缓存...")
                await bot.initialize_cache()
                logger.info("✅ 后台缓存初始化完成！")
            except Exception as e:
                logger.error(f"❌ 缓存初始化失败: {e}")
                logger.error(f"缓存初始化失败: {e}")

        startup_tasks.append(cache_init_task())
        task_names.append("缓存初始化")

        # 2. 后台刷新任务
        async def refresh_task():
            try:
                print("🔄 启动后台缓存刷新任务...")
                asyncio.create_task(bot.refresh_cache_background())
                logger.info("✅ 后台刷新任务已启动！")
            except Exception as e:
                logger.error(f"❌ 后台刷新任务启动失败: {e}")

        startup_tasks.append(refresh_task())
        task_names.append("后台刷新")

        # 并行执行所有启动任务
        logger.info(f"🚀 开始并行执行 {len(startup_tasks)} 个启动任务...")
        start_time = time.time()

        # 使用asyncio.gather并行执行，return_exceptions=True确保即使某个任务失败也不影响其他任务
        results = await asyncio.gather(*startup_tasks, return_exceptions=True)

        elapsed_time = time.time() - start_time

        # 统计结果
        success_count = 0
        error_count = 0

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                error_count += 1
                name = task_names[i] if i < len(task_names) else f"任务{i}"
                logger.error(f"❌ {name}任务失败: {result}")
                logger.error(f"{name}任务失败: {result}")
            else:
                success_count += 1

        print(f"🎉 并行启动完成! 成功: {success_count}/{len(startup_tasks)}, 用时: {elapsed_time:.2f}秒")

        if error_count > 0:
            logger.warning(f"⚠️ 有 {error_count} 个任务启动失败，但系统将继续运行")
        else:
            logger.info("✅ 所有后台服务启动成功！")

    except Exception as e:
        logger.error(f"❌ 并行启动过程发生异常: {e}")
        logger.error(f"并行启动过程发生异常: {e}")
        import traceback
        traceback.print_exc()

def initialize_bot_sync():
    """同步初始化机器人实例（不加载缓存）"""
    global user_handler, bot

    print("🚀 启动tradecat加密市场情报机器人...")

    try:
        user_handler = UserRequestHandler(card_registry=ensure_ranking_registry())
        bot = TradeCatBot()
        logger.info("✅ 核心组件初始化完成")
    except Exception as e:
        logger.error(f"❌ 组件初始化失败: {e}")


async def post_init(application):
    """应用启动后的初始化"""
    global APP_LOOP
    logger.info("✅ 应用启动完成")
    try:
        APP_LOOP = asyncio.get_running_loop()
    except RuntimeError:
        APP_LOOP = None
    await _refresh_bot_identity(application)

    # 延迟启动后台缓存加载任务
    async def delayed_init():
        await asyncio.sleep(5)
        await initialize_bot_background()

    asyncio.create_task(delayed_init())

    # 设置Telegram命令菜单
    from telegram import BotCommand
    commands = [
        BotCommand("start", "🏠 主菜单"),
        BotCommand("data", "📊 数据面板"),
        BotCommand("query", "🔍 币种查询"),
        BotCommand("ai", "🤖 AI分析"),
        BotCommand("lang", "🌐 语言"),
        BotCommand("help", "ℹ️ 帮助")
    ]

    try:
        await application.bot.set_my_commands(commands)
        logger.info("✅ Telegram命令菜单设置成功")
    except Exception as e:
        logger.warning(f"⚠️ 设置命令菜单失败: {e}")

    # 启动信号检测服务（绑定主事件循环，避免跨线程/跨循环发送消息）
    try:
        from signals import init_pusher, start_signal_loop

        async def send_signal(user_id: int, text: str, reply_markup):
            """发送信号消息"""
            try:
                await application.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.warning(f"发送信号给 {user_id} 失败: {e}")

        init_pusher(send_signal, loop=APP_LOOP)
        start_signal_loop(interval=60)
        logger.info("✅ SQLite信号检测服务已启动")
        print("🔔 SQLite信号检测服务已启动，间隔60秒")
    except Exception as e:
        logger.warning(f"⚠️ SQLite信号服务启动失败: {e}")

    # 启动 PG 实时信号检测服务
    try:
        from signals import start_pg_signal_loop, get_pg_engine

        # 仅启动 PG 引擎，推送由 SignalPublisher -> signals.adapter 统一处理
        engine = get_pg_engine()
        start_pg_signal_loop(interval=60)
        logger.info(f"✅ PG实时信号检测服务已启动，监控: {engine.symbols}")
        print(f"🔔 PG实时信号检测服务已启动，监控 {len(engine.symbols)} 个币种")
    except Exception as e:
        logger.warning(f"⚠️ PG信号服务启动失败: {e}")



def cleanup_existing_processes():
    """清理已存在的Python进程，避免机器人实例冲突"""
    try:
        import subprocess
        import platform
        import time
        import psutil

        system = platform.system()
        current_pid = os.getpid()

        print("🧹 正在强力检查并清理可能冲突的进程...")
        print(f"🔍 当前进程 PID: {current_pid}")

        # 方法1：精确查找和终止冲突的Python进程（排除当前进程）
        if system == "Windows":
            try:
                print("🔧 方法1: 查找并终止冲突的Python进程...")

                # 先查找所有Python进程
                result = subprocess.run(
                    ['tasklist', '/FI', 'IMAGENAME eq python.exe', '/FO', 'CSV'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0 and result.stdout:
                    lines = result.stdout.strip().split('\n')
                    killed_count = 0

                    for line in lines[1:]:  # 跳过标题行
                        if 'python.exe' in line:
                            try:
                                # 解析CSV格式的输出
                                parts = line.split(',')
                                if len(parts) >= 2:
                                    pid_str = parts[1].strip('"')
                                    pid = int(pid_str)

                                    # 不终止当前进程
                                    if pid != current_pid:
                                        subprocess.run(['taskkill', '/F', '/PID', str(pid)],
                                                     capture_output=True, timeout=5)
                                        killed_count += 1
                                        print(f"🔧 已终止进程 PID: {pid}")
                            except (ValueError, subprocess.TimeoutExpired):
                                continue

                    if killed_count > 0:
                        print(f"✅ 已清理 {killed_count} 个冲突进程")
                        time.sleep(2)  # 等待进程完全终止
                    else:
                        print("✅ 未发现冲突进程")
                else:
                    print("✅ 未发现Python进程")

            except Exception as e:
                print(f"⚠️ 进程清理失败: {e}")

        # 方法2：使用psutil精确查找和终止
        try:
            print("🔧 方法2: 使用psutil精确清理...")
            killed_count = 0

            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if proc.info['name'] and 'python' in proc.info['name'].lower():
                        pid = proc.info['pid']
                        if pid != current_pid:  # 不终止当前进程
                            proc.kill()
                            killed_count += 1
                            print(f"🔧 已终止Python进程 PID: {pid}")
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue

            if killed_count > 0:
                print(f"✅ 已精确清理 {killed_count} 个Python进程")
                time.sleep(2)  # 等待进程完全终止
            else:
                print("✅ 未发现需要清理的Python进程")

        except ImportError:
            print("⚠️ psutil不可用，跳过精确清理")
        except Exception as e:
            print(f"⚠️ 精确清理失败: {e}")

        # 方法3：验证清理结果
        try:
            print("🔍 方法3: 验证清理结果...")
            if system == "Windows":
                result = subprocess.run(
                    ['tasklist', '/FI', 'IMAGENAME eq python.exe'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if "python.exe" in result.stdout:
                    remaining_lines = [line for line in result.stdout.split('\n') if 'python.exe' in line]
                    print(f"⚠️ 仍有 {len(remaining_lines)} 个Python进程运行")
                    for line in remaining_lines:
                        print(f"   {line.strip()}")
                else:
                    print("✅ 确认：没有发现其他Python进程")

        except Exception as e:
            print(f"⚠️ 验证失败: {e}")

        print("🚀 进程清理完成，准备启动机器人...")
        print("⏳ 等待5秒确保进程完全终止...")
        time.sleep(5)

    except Exception as e:
        print(f"⚠️ 进程清理过程中出现错误: {e}")
        print("🔄 继续启动机器人...")
        import traceback
        traceback.print_exc()

def main():
    """主函数"""
    try:
        # 🔧 第一步：清理可能冲突的进程 (暂时禁用以避免自杀)
        # cleanup_existing_processes()

        print(f"🔑 使用 BOT_TOKEN: {BOT_TOKEN[:10]}...{BOT_TOKEN[-10:]}")

        # 🔍 第二步：数据完整性检查 - 防止数据重置
        print("🔍 正在进行数据完整性检查...")
        try:
            integrity_result = DataManager.validate_data_integrity()
            if integrity_result["success"]:
                if integrity_result["issues_found"]:
                    print(f"⚠️ 发现 {len(integrity_result['issues_found'])} 个数据问题")
                    print(f"✅ 应用了 {len(integrity_result['fixes_applied'])} 个修复")
                else:
                    print("✅ 数据完整性检查通过")
            else:
                print("❌ 数据完整性检查失败，但继续启动")
        except Exception as e:
            print(f"❌ 数据完整性检查异常: {e}")
            print("🔄 继续启动机器人...")

        # 首先同步初始化机器人实例（快速，不阻塞）
        initialize_bot_sync()

        # 创建应用（增加超时与重试容错）
        print("🏗️ 正在创建 Telegram Application...")
        # httpx 自动读取 HTTPS_PROXY/HTTP_PROXY 环境变量
        import os
        proxy_url = os.environ.get('HTTPS_PROXY') or os.environ.get('HTTP_PROXY') or os.environ.get('https_proxy') or os.environ.get('http_proxy')
        if proxy_url:
            logger.info(f"🌐 检测到代理环境变量: {proxy_url}")
        else:
            logger.info("🌐 未设置代理，直连")

        request = HTTPXRequest(
            connect_timeout=8,
            read_timeout=15,
        )
        application = Application.builder().token(BOT_TOKEN).request(request).build()
        logger.info("✅ Telegram Application 创建成功")

        # 全局错误处理
        async def log_error(update, context):
            import asyncio as _asyncio
            err = context.error
            logger.exception("Telegram handler error", exc_info=err)
            from telegram.error import NetworkError, TimedOut, RetryAfter
            delay = 1
            if isinstance(err, RetryAfter):
                delay = min(30, int(getattr(err, "retry_after", 1)) + 1)
            elif isinstance(err, (NetworkError, TimedOut)):
                delay = 3
            await _asyncio.sleep(delay)

        application.add_error_handler(log_error)
        logger.info("✅ 全局错误处理器已注册")

        # 添加处理器 - 注册所有命令
        print("📋 正在注册命令处理器...")
        application.add_handler(CommandHandler("start", start))
        logger.info("✅ /start 命令处理器已注册")
        application.add_handler(CommandHandler("help", help_command))
        logger.info("✅ /help 命令处理器已注册")
        application.add_handler(CommandHandler("menu", menu_command))
        logger.info("✅ /menu 命令处理器已注册")
        application.add_handler(CommandHandler("ping", health_command))
        logger.info("✅ /ping 命令处理器已注册")

        # 命令系统
        application.add_handler(CommandHandler("subscribe", subscribe_command))
        logger.info("✅ /subscribe 命令处理器已注册")
        application.add_handler(CommandHandler("status", status_command_user))
        logger.info("✅ /status 命令处理器已注册")
        application.add_handler(CommandHandler("data", data_command))
        logger.info("✅ /data 命令处理器已注册")
        application.add_handler(CommandHandler("query", query_command))
        logger.info("✅ /query 命令处理器已注册")
        application.add_handler(CommandHandler("ai", ai_command))
        logger.info("✅ /ai 命令处理器已注册")
        application.add_handler(CommandHandler("vis", vis_command))
        logger.info("✅ /vis 命令处理器已注册")
        application.add_handler(CommandHandler("admin", admin_command))
        logger.info("✅ /admin 命令处理器已注册")
        application.add_handler(CommandHandler("lang", lang_command))
        logger.info("✅ /lang 命令处理器已注册")
        # /env 命令已禁用
        # application.add_handler(CommandHandler("env", env_command))
        # logger.info("✅ /env 命令处理器已注册")

        # 保留旧命令兼容性
        application.add_handler(CommandHandler("stats", user_command))
        logger.info("✅ /stats 命令处理器已注册（兼容）")

        logger.info("✅ 所有命令处理器已注册")

        logger.info("🤖 AI分析暂未开放，跳过AI对话处理器注册")

        application.add_handler(CallbackQueryHandler(button_callback))
        logger.info("✅ 全局回调查询处理器已注册")

        # 添加消息处理器（处理常驻键盘按钮）
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_keyboard_message))
        logger.info("✅ 消息处理器已注册")

        # 设置启动后初始化（后台异步加载缓存）
        application.post_init = post_init

        # 启动机器人
        logger.info("✅ 机器人已启动，等待消息...")
        print("🔗 数据源: Binance Futures API")
        print("💾 缓存策略: 机器人立即可用，数据后台异步加载")
        print("📞 现在可以发送 /start 命令测试机器人！")
        print("⚡ 注意：初次使用时数据功能可能需要几秒钟加载")

        # 显式阻塞主线程：close_loop=True 交由库关闭事件循环，stop_signals=None 避免额外信号干扰
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,  # 丢弃待处理的更新，避免冲突
            close_loop=True,  # 允许库关闭循环（修复不阻塞问题）
            stop_signals=None  # 不注册信号处理，确保正常阻塞
        )

    except Exception as e:
        logger.error(f"❌ 机器人启动失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # 使用完整启动模式，包含所有功能
    main()
