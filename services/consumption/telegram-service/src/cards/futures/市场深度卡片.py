"""市场深度排行榜卡片（下线占位）

市场深度属于高频/盘口类数据，历史链路依赖旧的数据源与回退逻辑。
在“Query Service Only”的约束下，本卡片暂时保留入口但不提供数据展示，
避免在消费层引入任何数据库直连或隐式回退。
"""

from __future__ import annotations

from typing import Dict, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from cards.base import RankingCard
from cards.i18n import gettext as _t, resolve_lang


class MarketDepthCard(RankingCard):
    """🧊 市场深度（占位）"""

    FALLBACK = "card.depth.fallback"

    def __init__(self) -> None:
        super().__init__(
            card_id="market_depth",
            button_text="🧊 市场深度",
            button_key="card.depth.btn",
            category="free",
            description="市场深度排行榜（当前下线占位）",
            default_state={},
            callback_prefixes=["market_depth", "market_depth_"],
            priority=6,
        )

    async def handle_callback(self, update, context, services: Dict[str, object]) -> bool:
        query = getattr(update, "callback_query", None)
        if not query:
            return False
        user_handler = services.get("user_handler")
        ensure_valid_text = services.get("ensure_valid_text")
        if user_handler is None:
            return False

        data = query.data or ""
        if data not in {self.card_id, "market_depth_refresh"} and not data.startswith("market_depth_"):
            return False

        lang = resolve_lang(query)
        text, keyboard = await self._build_payload(ensure_valid_text, lang)
        if data == "market_depth_refresh":
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
        else:
            await query.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
        return True

    async def _build_payload(self, ensure_valid_text, lang: str) -> Tuple[str, object]:
        text = _t("feature.depth_offline", lang=lang)
        if callable(ensure_valid_text):
            text = ensure_valid_text(text, self.FALLBACK)
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(_t("btn.back_home", lang=lang), callback_data="ranking_menu"),
                    InlineKeyboardButton(_t("btn.refresh", lang=lang), callback_data="market_depth_refresh"),
                ]
            ]
        )
        return text, keyboard


CARD = MarketDepthCard()

