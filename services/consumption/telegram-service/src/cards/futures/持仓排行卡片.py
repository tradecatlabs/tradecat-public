"""持仓量排行榜卡片"""

from __future__ import annotations

import asyncio
import re
from typing import Dict, List, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from cards.base import RankingCard
from cards.data_provider import format_symbol, get_ranking_provider
from cards.i18n import btn_auto as _btn_auto, gettext as _t, resolve_lang, format_sort_field, translate_field
from cards.排行榜服务 import POSITION_PERIODS, normalize_period


class PositionRankingCard(RankingCard):
    """🦅 持仓量排行 - 持仓量排行榜"""

    FALLBACK = "card.oi.fallback"
    provider = get_ranking_provider()

    def __init__(self) -> None:
        super().__init__(
            card_id="position_ranking",
            button_text="🐋 持仓量",
            button_key="card.oi_ranking.btn",
            category="free",
            description="持仓量排行榜，追踪主力动向",
            default_state={
                "position_limit": 10,
                "position_sort": "desc",
                "position_period": "15m",
                "position_sort_field": "position",
                "position_market": "futures",
                "position_fields": {},
            },
            callback_prefixes=[
                "position_ranking",
                "position_",
                "position_sort_field_",
                "position_period_",
                "position_sort_",
                "position_limit_",
                "position_market_",
                "field_position_toggle_",
            ],
            priority=2,
        )

        self.general_display_fields: List[Tuple[str, str, bool]] = [
            ("quote_volume", "成交额", False),
            ("振幅", "振幅", False),
            ("成交笔数", "成交笔数", False),
            ("主动买卖比", "主动买卖比", False),
            ("price", "价格", False),
        ]
        self.special_display_fields: List[Tuple[str, str, bool]] = [
            ("position", "持仓金额", False),
            ("long", "大户多空比", False),
            ("short", "全体多空比", False),
        ]

    def handles_callback(self, callback_data: str) -> bool:
        if super().handles_callback(callback_data):
            return True
        return bool(re.fullmatch(r"position_(10|20|30)", callback_data))

    async def handle_callback(self, update, context, services: Dict[str, object]) -> bool:  # noqa: D401
        query = update.callback_query
        if not query:
            return False

        user_handler = services.get("user_handler")
        ensure_valid_text = services.get("ensure_valid_text")
        if user_handler is None:
            return False

        data = query.data or ""

        if data in {self.card_id, "position_ranking_refresh"}:
            await self._reply(query, user_handler, ensure_valid_text)
            return True

        if data == "position_nop":
            return True
        if data.startswith("position_market_"):
            market = data.replace("position_market_", "")
            user_handler.user_states['position_market'] = market
            await self._edit(query, user_handler, ensure_valid_text)
            return True
        if data.startswith("position_sort_field_"):
            field = data.replace("position_sort_field_", "")
            user_handler.user_states["position_sort_field"] = field
            await self._edit(query, user_handler, ensure_valid_text)
            return True
        if data.startswith("position_sort_"):
            sort_order = data.replace("position_sort_", "")
            user_handler.user_states['position_sort'] = sort_order
            await self._edit(query, user_handler, ensure_valid_text)
            return True

        if data.startswith("position_period_"):
            period = data.replace("position_period_", "")
            user_handler.user_states['position_period'] = normalize_period(period, POSITION_PERIODS, default="15m")
            await self._edit(query, user_handler, ensure_valid_text)
            return True

        if data.startswith("position_limit_"):
            limit_val = data.replace("position_limit_", "")
            if limit_val.isdigit():
                user_handler.user_states['position_limit'] = int(limit_val)
                await self._edit(query, user_handler, ensure_valid_text)
                return True

        if data.startswith("field_position_toggle_"):
            col = data.replace("field_position_toggle_", "")
            fields_state = self._ensure_field_state(user_handler)
            if col in fields_state:
                fields_state[col] = not fields_state[col]
                user_handler.user_states["position_fields"] = fields_state
            await self._edit(query, user_handler, ensure_valid_text)
            return True

        return False

    async def _reply(self, query, user_handler, ensure_valid_text) -> None:
        lang = resolve_lang(query)
        text, keyboard = await self._build_payload(user_handler, ensure_valid_text, lang, query)
        await query.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')

    async def _edit(self, query, user_handler, ensure_valid_text) -> None:
        lang = resolve_lang(query)
        text, keyboard = await self._build_payload(user_handler, ensure_valid_text, lang, query)
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

    async def _build_payload(self, user_handler, ensure_valid_text, lang=None, query=None) -> Tuple[str, object]:
        if lang is None and query is not None:
            lang = resolve_lang(query)
        loop = asyncio.get_event_loop()
        limit = user_handler.user_states.get('position_limit', 10)
        sort_order = user_handler.user_states.get('position_sort', 'desc')
        period = user_handler.user_states.get('position_period', '4h')
        sort_field = user_handler.user_states.get('position_sort_field', 'position')
        period = normalize_period(period, POSITION_PERIODS, default="15m")
        user_handler.user_states['position_period'] = period
        fields_state = self._ensure_field_state(user_handler)

        rows, header = await loop.run_in_executor(
            None,
            self._load_rows,
            user_handler,
            limit,
            sort_order,
            period,
            sort_field,
            fields_state,
        )
        aligned = user_handler.dynamic_align_format(rows) if rows else _t("data.no_data", lang=lang)
        time_info = user_handler.get_current_time_display()
        sort_symbol = "🔽" if sort_order == "desc" else "🔼"
        text = (
            f"{_t('card.oi.title', lang=lang)}\n"
            f"{_t('card.common.update_time', lang=lang).format(time=time_info['full'])}\n"
            f"{_t('card.common.sort_info', lang=lang).format(period=period, field=format_sort_field(sort_field, lang=lang, field_lists=[self.general_display_fields, self.special_display_fields]), symbol=sort_symbol)}\n"
            f"{header}\n"
            f"```\n{aligned}\n```\n"
            f"{_t('card.oi.hint', lang=lang)}\n"
            f"{_t('card.common.last_update', lang=lang).format(time=time_info['full'])}"
        )
        if callable(ensure_valid_text):
            text = ensure_valid_text(text, self.FALLBACK)

        keyboard = self._build_keyboard(user_handler)
        return text, keyboard

    def _build_keyboard(self, handler):
        fields_state = self._ensure_field_state(handler)
        period = handler.user_states.get("position_period", "15m")
        sort_order = handler.user_states.get("position_sort", "desc")
        current_limit = handler.user_states.get("position_limit", 10)
        sort_field = handler.user_states.get("position_sort_field", "position")

        def b(label: str, data: str, active: bool = False, disabled: bool = False):

            if disabled:

                return InlineKeyboardButton(label, callback_data=data or 'nop')

            return _btn_auto(None, label, data, active=active)


        kb: List[List[InlineKeyboardButton]] = []

        # 行1 市场：仅期货，省略

        # 行2 通用字段开关
        gen_row: List[InlineKeyboardButton] = []
        for col_id, label, is_core in self.general_display_fields:
            state_on = fields_state.get(col_id, is_core or False)
            show_label = label if state_on or is_core else f"❎{label}"
            gen_row.append(InlineKeyboardButton(show_label, callback_data=f"field_position_toggle_{col_id}"))
        kb.append(gen_row)

        # 行3 专用字段开关
        spec_row: List[InlineKeyboardButton] = []
        for col_id, label, is_core in self.special_display_fields:
            state_on = fields_state.get(col_id, is_core or False)
            show_label = label if state_on or is_core else f"❎{label}"
            spec_row.append(InlineKeyboardButton(show_label, callback_data=f"field_position_toggle_{col_id}"))
        kb.append(spec_row)

        # 行4 通用排序
        general_sort = [(cid, lab) for cid, lab, _ in self.general_display_fields]
        kb.append([b(lbl, f"position_sort_field_{cid}", active=(sort_field == cid)) for cid, lbl in general_sort])

        # 行5 专用排序
        special_sort = [(cid, lab) for cid, lab, _ in self.special_display_fields]
        kb.append([b(lbl, f"position_sort_field_{cid}", active=(sort_field == cid)) for cid, lbl in special_sort])

        # 行6 周期
        kb.append([b(p, f"position_period_{p}", active=p == period) for p in POSITION_PERIODS])

        # 行7 排序方向 + 条数
        kb.append([
            b("降序", "position_sort_desc", active=sort_order == "desc"),
            b("升序", "position_sort_asc", active=sort_order == "asc"),
            b("10条", "position_limit_10", active=current_limit == 10),
            b("20条", "position_limit_20", active=current_limit == 20),
            b("30条", "position_limit_30", active=current_limit == 30),
        ])

        # 行8 主控
        kb.append([
            _btn_auto(None, "🏠主菜单", "ranking_menu"),
            _btn_auto(None, "🔄刷新", "position_ranking_refresh"),
        ])

        return InlineKeyboardMarkup(kb)

    def _load_rows(
        self,
        handler,
        limit: int,
        sort_order: str,
        period: str,
        sort_field: str,
        field_state: Dict[str, bool],
        lang: str | None = None,
    ) -> Tuple[List[List[str]], str]:
        try:
            metrics = self.provider.merge_with_base("期货情绪聚合表.py", period, base_fields=["数据时间"])
        except Exception:
            metrics = []

        items = []
        for row in metrics or []:
            sym = str(row.get("symbol") or "").strip().upper()
            if not sym:
                continue
            items.append(
                {
                    "symbol": sym,
                    "position": float(row.get("持仓金额") or 0),
                    "long": float(row.get("大户多空比") or 0),
                    "short": float(row.get("全体多空比") or 0),
                    "price": float(row.get("price") or 0),
                    "quote_volume": float(row.get("quote_volume") or 0),
                    "振幅": float(row.get("振幅") or 0),
                    "成交笔数": float(row.get("成交笔数") or row.get("交易次数") or 0),
                    "主动买卖比": float(row.get("主动买卖比") or 0),
                }
            )

        reverse = sort_order != "asc"
        items.sort(key=lambda x: x.get(sort_field, 0), reverse=reverse)
        active_special = [f for f in self.special_display_fields if field_state.get(f[0], f[2] or False)]
        active_general = [f for f in self.general_display_fields if field_state.get(f[0], f[2] or False)]
        header_parts = [_t("card.header.rank", lang=lang), _t("card.header.symbol", lang=lang)] + [translate_field(lab, lang=lang) for _, lab, _ in active_special] + [translate_field(lab, lang=lang) for _, lab, _ in active_general]

        rows: List[List[str]] = []
        for idx, item in enumerate(items[:limit], 1):
            display_symbol = format_symbol(item["symbol"])
            row: List[str] = [f"{idx}", display_symbol]
            for col_id, _, _ in active_special:
                val = item.get(col_id)
                row.append(self._format_num(val))
            for col_id, _, _ in active_general:
                val = item.get(col_id)
                if col_id == "quote_volume":
                    row.append(self._format_volume(val))
                elif col_id == "振幅":
                    pct = (val * 100) if isinstance(val, (int, float)) and val <= 5 else val
                    row.append(f"{pct:.2f}%" if isinstance(pct, (int, float)) else "-")
                elif col_id == "成交笔数":
                    row.append(f"{val:.2f}" if isinstance(val, (int, float)) else (str(val) if val not in (None, "") else "-"))
                elif col_id == "主动买卖比":
                    row.append(f"{val*100:.2f}%" if isinstance(val, (int, float)) else "-")
                elif col_id == "price":
                    row.append(f"{val:.4f}" if val else "-")
                else:
                    row.append(str(val) if val not in (None, "") else "-")
            rows.append(row)
        return rows, "/".join(header_parts)

    # ---------- 工具 ----------
    def _ensure_field_state(self, h) -> Dict[str, bool]:
        state = h.user_states.get("position_fields") or {}
        if not state:
            for col, _, is_core in self.general_display_fields + self.special_display_fields:
                if col in {"price", "position"}:
                    state[col] = True
                else:
                    state[col] = True if is_core else False
            h.user_states["position_fields"] = state

        for _off in {"quote_volume", "振幅", "成交笔数", "主动买卖比"}:
            if _off in state:
                state[_off] = False

        return state


CARD = PositionRankingCard()
