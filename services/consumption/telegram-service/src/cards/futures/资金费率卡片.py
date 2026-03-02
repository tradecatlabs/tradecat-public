"""资金费率排行榜卡片（下线占位）

历史版本的资金费率/市场深度依赖外部数据源与旧的直连/缓存链路。
在“Query Service Only”的硬约束下，本卡片暂时保持可见，但只提供下线占位提示，
避免在消费层引入任何数据库直连或隐式回退路径。
"""

from __future__ import annotations

from typing import Dict, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from cards.base import RankingCard
from cards.i18n import gettext as _t, resolve_lang


class FundingRateCard(RankingCard):
    """💱 资金费率（占位）"""

    FALLBACK = "card.funding.fallback"

    def __init__(self) -> None:
        super().__init__(
            card_id="funding_rate",
            button_text="💱 资金费率",
            button_key="card.funding_rate.btn",
            category="free",
            description="资金费率排行榜（当前下线占位）",
            default_state={},
            callback_prefixes=["funding_rate", "funding_"],
            priority=3,
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
        if data not in {self.card_id, "funding_rate_refresh"} and not data.startswith("funding_"):
            return False

        lang = resolve_lang(query)
        text, keyboard = await self._build_payload(ensure_valid_text, lang)
        if data == "funding_rate_refresh":
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
        else:
            await query.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
        return True

    async def _build_payload(self, ensure_valid_text, lang: str) -> Tuple[str, object]:
        text = _t("feature.funding_offline", lang=lang)
        if callable(ensure_valid_text):
            text = ensure_valid_text(text, self.FALLBACK)
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(_t("btn.back_home", lang=lang), callback_data="ranking_menu"),
                    InlineKeyboardButton(_t("btn.refresh", lang=lang), callback_data="funding_rate_refresh"),
                ]
            ]
        )
        return text, keyboard


CARD = FundingRateCard()

