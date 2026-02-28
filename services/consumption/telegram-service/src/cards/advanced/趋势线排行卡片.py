"""趋势线榜单卡片（Pine 等价版）

数据源：PostgreSQL 指标库（tg_cards）表 趋势线榜单.py
字段：排名,币种,趋势方向,距离趋势线%,价格
"""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from cards.base import RankingCard
from cards.data_provider import format_symbol, get_ranking_provider
from cards.i18n import (
    gettext as _t,
    btn as _btn,
    resolve_lang,
    btn_auto as _btn_auto,
    translate_value,
    translate_field,
    format_sort_field,
)


class 趋势线排行卡片(RankingCard):
    FALLBACK = "card.trendline.fallback"
    provider = get_ranking_provider()

    def __init__(self) -> None:
        super().__init__(
            card_id="trendline_ranking",
            button_text="📈 趋势线",
            button_key="card.trendline.btn",
            category="free",
            description="多/空趋势线距离榜（Pine 趋势线 1:1 复刻）",
            default_state={
                "tl_period": "15m",
                "tl_sort": "desc",
                "tl_limit": 10,
                "tl_sort_field": "distance_pct",
                "tl_market": "futures",
                "tl_fields": {},
            },
            callback_prefixes=[
                "trendline_ranking",
                "tl_nop",
                "tl_period_",
                "tl_sort_",
                "tl_limit_",
                "tl_sort_field_",
                "tl_market_",
                "tl_settings",
                "field_tl_toggle_",
            ],
            priority=36,
        )
        self._logger = logging.getLogger(__name__)

        # 通用字段
        self.general_display_fields: List[Tuple[str, str, bool]] = [
            ("quote_volume", "成交额", False),
            ("振幅", "振幅", False),
            ("成交笔数", "成交笔数", False),
            ("主动买卖比", "主动买卖比", False),
            ("price", "价格", False),
        ]

        # 专用字段：方向 + 距离%
        self.special_display_fields: List[Tuple[str, str, bool]] = [
            ("trend_direction", "趋势方向", True),
            ("distance_pct", "距离趋势线%", True),
        ]

    # ========== 回调处理 ==========
    async def handle_callback(self, update, context, services: Dict[str, object]) -> bool:
        query = update.callback_query
        if not query:
            return False
        h = services.get("user_handler")
        ensure = services.get("ensure_valid_text")
        if h is None:
            return False
        data = query.data or ""

        # 进入卡片 / 刷新
        if data in (self.card_id, self.entry_callback, "trendline_ranking_refresh"):
            await self._reply(query, h, ensure)
            return True
        if data == "tl_nop":
            return True

        # 排序字段（需先处理避免与 tl_sort_ 冲突）
        if data.startswith("tl_sort_field_"):
            h.user_states["tl_sort_field"] = data.replace("tl_sort_field_", "")
            await self._edit(query, h, ensure)
            return True

        if data.startswith("tl_market_"):
            h.user_states["tl_market"] = data.replace("tl_market_", "")
            await self._edit(query, h, ensure)
            return True
        if data.startswith("tl_period_"):
            h.user_states["tl_period"] = data.replace("tl_period_", "")
            await self._edit(query, h, ensure)
            return True
        if data.startswith("tl_sort_"):
            h.user_states["tl_sort"] = data.replace("tl_sort_", "")
            await self._edit(query, h, ensure)
            return True
        if data.startswith("tl_limit_"):
            val = data.replace("tl_limit_", "")
            if val.isdigit():
                h.user_states["tl_limit"] = int(val)
                await self._edit(query, h, ensure)
                return True
            return False

        # 字段开关
        if data.startswith("field_tl_toggle_"):
            col = data.replace("field_tl_toggle_", "")
            fields_state = self._ensure_field_state(h)
            if col in fields_state:
                fields_state[col] = not fields_state[col]
                h.user_states["tl_fields"] = fields_state
            await self._edit(query, h, ensure)
            return True
        return False

    # ========== 输出渲染 ==========
    async def _reply(self, query, h, ensure):
        lang = resolve_lang(query)
        text, kb = await self._build_payload(h, ensure, lang, query)
        await query.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

    async def _edit(self, query, h, ensure):
        lang = resolve_lang(query)
        text, kb = await self._build_payload(h, ensure, lang, query)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    async def _build_payload(self, h, ensure, lang: str = None, update=None):
        if lang is None and update is not None:
            lang = resolve_lang(update)
        period = h.user_states.get("tl_period", "15m")
        sort_order = h.user_states.get("tl_sort", "desc")
        limit = h.user_states.get("tl_limit", 10)
        allowed_fields = {f[0] for f in self.general_display_fields + self.special_display_fields}
        sort_field = h.user_states.get("tl_sort_field", "distance_pct")
        if sort_field not in allowed_fields:
            sort_field = "distance_pct"
            h.user_states["tl_sort_field"] = sort_field
        fields_state = self._ensure_field_state(h)

        rows, header = self._load_rows(period, sort_order, limit, sort_field, fields_state, lang)
        aligned = h.dynamic_align_format(rows) if rows else _t("data.no_data", lang=lang)
        time_info = h.get_current_time_display()
        sort_symbol = "🔽" if sort_order == "desc" else "🔼"
        display_sort_field = format_sort_field(sort_field, lang=lang, field_lists=[getattr(self, "general_display_fields", []), getattr(self, "special_display_fields", [])])
        text = (
            f"{_t('card.trendline.title', lang=lang)}\n"
            f"{_t('time.update', update, lang=lang, time=time_info['full'])}\n"
            f"{_t('card.trendline.sort', update, lang=lang, period=period, field=display_sort_field, symbol=sort_symbol)}\n"
            f"{header}\n"
            f"```\n{aligned}\n```\n"
            f"{_t('card.trendline.source', lang=lang)}\n"
            f"{_t('time.last_update', update, lang=lang, time=time_info['full'])}"
        )
        if callable(ensure):
            text = ensure(text, _t(self.FALLBACK))
        kb = self._build_keyboard(h, lang, update)
        return text, kb

    def _build_keyboard(self, h, lang: str, update=None):
        fields_state = self._ensure_field_state(h)
        period = h.user_states.get("tl_period", "15m")
        sort_order = h.user_states.get("tl_sort", "asc")
        current_limit = h.user_states.get("tl_limit", 10)
        current_sort_field = h.user_states.get("tl_sort_field", "distance_pct")
        market = h.user_states.get("tl_market", "futures")

        def b(label: str, data: str, active: bool = False, disabled: bool = False):

            if disabled:

                return InlineKeyboardButton(label, callback_data=data or 'nop')

            return _btn_auto(None, label, data, active=active)


        kb: List[List[InlineKeyboardButton]] = []

        show_market_row = False
        if show_market_row:
            kb.append([
                b("现货", "tl_market_spot", active=market == "spot"),
                b("期货", "tl_market_futures", active=market == "futures"),
            ])

        # 通用字段开关
        gen_row: List[InlineKeyboardButton] = []
        for col_id, label, _ in self.general_display_fields:
            state_on = fields_state.get(col_id, True)
            show_label = label if state_on else f"❎{label}"
            gen_row.append(InlineKeyboardButton(show_label, callback_data=f"field_tl_toggle_{col_id}"))
        kb.append(gen_row)

        # 专用字段开关
        spec_row: List[InlineKeyboardButton] = []
        for col_id, label, _ in self.special_display_fields:
            state_on = fields_state.get(col_id, True)
            show_label = label if state_on else f"❎{label}"
            spec_row.append(InlineKeyboardButton(show_label, callback_data=f"field_tl_toggle_{col_id}"))
        kb.append(spec_row)

        # 通用排序
        general_sort = [(cid, lab) for cid, lab, _ in self.general_display_fields]
        if general_sort:
            kb.append([
                b(lbl, f"tl_sort_field_{fid}", active=(current_sort_field == fid))
                for fid, lbl in general_sort
            ])

        # 专用排序
        special_sort = [(cid, lab) for cid, lab, _ in self.special_display_fields]
        kb.append([
            b(lbl, f"tl_sort_field_{fid}", active=(current_sort_field == fid))
            for fid, lbl in special_sort
        ])

        periods = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]
        kb.append([b(p, f"tl_period_{p}", active=p == period) for p in periods])

        kb.append([
            _btn(update, "btn.sort.desc", "tl_sort_desc", active=sort_order == "desc"),
            _btn(update, "btn.sort.asc", "tl_sort_asc", active=sort_order == "asc"),
            _btn(update, "btn.limit.10", "tl_limit_10", active=current_limit == 10),
            _btn(update, "btn.limit.20", "tl_limit_20", active=current_limit == 20),
            _btn(update, "btn.limit.30", "tl_limit_30", active=current_limit == 30),
        ])

        kb.append([
            _btn(update, "menu.home", "ranking_menu"),
            _btn(update, "btn.refresh", "trendline_ranking_refresh"),
        ])

        return InlineKeyboardMarkup(kb)

    # ========== 数据加载与格式化 ==========
    def _load_rows(
        self,
        period: str,
        sort_order: str,
        limit: int,
        sort_field: str,
        field_state: Dict[str, bool],
        lang: str,
    ):
        items: List[Dict] = []
        try:
            metrics = self.provider.merge_with_base("趋势线榜单.py", period, base_fields=["当前价格", "成交额"])
            for row in metrics:
                sym = format_symbol(row.get("symbol") or row.get("交易对") or row.get("币种") or "")
                if not sym:
                    continue
                distance = float(row.get("距离趋势线%") or 0)
                direction = row.get("趋势方向") or "-"
                price = float(row.get("price") or row.get("当前价格") or 0)
                quote_volume = float(row.get("成交额") or row.get("quote_volume") or 0)
                items.append({
                    "symbol": sym,
                    "trend_direction": direction,
                    "distance_pct": distance,
                    "price": price,
                    "quote_volume": quote_volume,
                    "振幅": float(row.get("振幅") or 0),
                    "成交笔数": float(row.get("成交笔数") or 0),
                    "主动买卖比": float(row.get("主动买卖比") or 0),
                })
        except Exception as exc:  # pragma: no cover
            self._logger.warning("读取趋势线榜单.py失败: %s", exc)
            return [], _t("card.header.rank_symbol", lang=lang)

        reverse = sort_order != "asc"
        items.sort(key=lambda x: x.get(sort_field, 0), reverse=reverse)

        active_special = [f for f in self.special_display_fields if field_state.get(f[0], True)]
        active_general = [f for f in self.general_display_fields if field_state.get(f[0], True)]

        header_parts = [
            _t("card.header.rank", lang=lang),
            _t("card.header.symbol", lang=lang),
        ] + [translate_field(lab, lang=lang) for _, lab, _ in active_special] + [translate_field(lab, lang=lang) for _, lab, _ in active_general]

        rows: List[List[str]] = []
        for idx, item in enumerate(items[:limit], 1):
            row: List[str] = [f"{idx}", item["symbol"]]
            # 专用列
            for col_id, _, _ in active_special:
                val = item.get(col_id)
                if col_id == "distance_pct":
                    row.append(f"{val:.2f}%" if isinstance(val, (int, float)) else "-")
                else:
                    translated = translate_value(val, lang=lang)
                    row.append(str(translated) if translated not in (None, "") else "-")
            # 通用列
            for col_id, _, _ in active_general:
                val = item.get(col_id)
                if col_id == "price":
                    row.append(f"{val:.4f}" if isinstance(val, (int, float)) else "-")
                elif isinstance(val, (int, float)):
                    row.append(f"{val:.2f}")
                else:
                    translated = translate_value(val, lang=lang)
                    row.append(str(translated) if translated not in (None, "") else "-")
            rows.append(row)
        return rows, "/".join(header_parts)

    # ========== 工具 ==========
    def _ensure_field_state(self, h) -> Dict[str, bool]:
        state = h.user_states.get("tl_fields")
        if not state:
            state = {}
            for col, _, _ in self.general_display_fields + self.special_display_fields:
                state[col] = False
            # 默认只展示趋势方向与距离，价格默认关闭
            for _on in {"trend_direction", "distance_pct"}:
                state[_on] = True
            h.user_states["tl_fields"] = state
        return state


CARD = 趋势线排行卡片()
