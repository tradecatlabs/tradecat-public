"""布林带排行榜卡片

数据源：PostgreSQL 指标库（tg_cards）表 布林带扫描器.py
字段：排名,币种,周期,带宽%,中轨斜率%,中轨价格,上轨价格,下轨价格,百分比,状态,当前价格,成交额(USDT),数据时间
"""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from cards.data_provider import get_ranking_provider, format_symbol
from cards.i18n import btn_auto as _btn_auto, gettext as _t, resolve_lang, translate_field, format_sort_field
from cards.base import RankingCard


class 布林带排行卡片(RankingCard):
    FALLBACK = "card.bb.fallback"
    provider = get_ranking_provider()

    def __init__(self) -> None:
        super().__init__(
            card_id="bb_ranking",
            button_text="🎗️ 布林带",
            button_key="card.bollinger.btn",
            category="free",
            description="布林带带宽/百分比 榜单",
            default_state={
                "bb_period": "15m",
                "bb_sort": "desc",
                "bb_limit": 10,
                "bb_sort_field": "bandwidth",
                "bb_market": "futures",
                "bb_fields": {},
            },
            callback_prefixes=[
                "bb_ranking",
                "bb_period_",
                "bb_sort_",
                "bb_limit_",
                "bb_sort_field_",
                "bb_market_",
                "field_bb_toggle_",
            ],
            priority=27,
        )
        self._logger = logging.getLogger(__name__)

        # 字段定义（col_id, label, is_core）
        self.general_display_fields: List[Tuple[str, str, bool]] = [
            ("quote_volume", "成交额", False),
            ("振幅", "振幅", False),
            ("成交笔数", "成交笔数", False),
            ("主动买卖比", "主动买卖比", False),
            ("price", "价格", False),
        ]
        # 专有字段全部可开关
        self.special_display_fields: List[Tuple[str, str, bool]] = [
            ("bandwidth", "带宽", False),    # 默认开启但允许关闭
            ("percent_b", "百分比", False),  # 默认开启但允许关闭
            ("mid_slope", "中轨斜率", False),
            ("mid_price", "中轨价", False),
            ("upper", "上轨价", False),
            ("lower", "下轨价", False),
        ]

    async def handle_callback(self, update, context, services: Dict[str, object]) -> bool:
        query = update.callback_query
        if not query:
            return False
        h = services.get("user_handler")
        ensure = services.get("ensure_valid_text")
        if h is None:
            return False
        data = query.data or ""
        if data in (self.card_id, self.entry_callback, "bb_ranking_refresh"):
            await self._reply(query, h, ensure)
            return True
        if data == "bb_nop":
            return True
        if data.startswith("bb_market_"):
            h.user_states["bb_market"] = data.replace("bb_market_", "")
            await self._edit(query, h, ensure)
            return True
        if data.startswith("bb_sort_field_"):
            h.user_states["bb_sort_field"] = data.replace("bb_sort_field_", "")
            await self._edit(query, h, ensure)
            return True
        if data.startswith("bb_period_"):
            h.user_states["bb_period"] = data.replace("bb_period_", "")
            await self._edit(query, h, ensure)
            return True
        if data.startswith("bb_sort_"):
            h.user_states["bb_sort"] = data.replace("bb_sort_", "")
            await self._edit(query, h, ensure)
            return True
        if data.startswith("bb_limit_"):
            val = data.replace("bb_limit_", "")
            if val.isdigit():
                h.user_states["bb_limit"] = int(val)
                await self._edit(query, h, ensure)
                return True
            return False
        if data.startswith("field_bb_toggle_"):
            col = data.replace("field_bb_toggle_", "")
            fields_state = self._ensure_field_state(h)
            if col in fields_state and not self._is_core(col):
                fields_state[col] = not fields_state[col]
                h.user_states["bb_fields"] = fields_state
            await self._edit(query, h, ensure)
            return True
        return False

    async def _reply(self, query, h, ensure):
        lang = resolve_lang(query)
        text, kb = await self._build_payload(h, ensure, lang, query)
        await query.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

    async def _edit(self, query, h, ensure):
        lang = resolve_lang(query)
        text, kb = await self._build_payload(h, ensure, lang, query)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    async def _build_payload(self, h, ensure, lang: str = "zh_CN", update=None) -> Tuple[str, object]:
        period = h.user_states.get("bb_period", "15m")
        sort_order = h.user_states.get("bb_sort", "desc")
        limit = h.user_states.get("bb_limit", 10)
        sort_field = h.user_states.get("bb_sort_field", "bandwidth")
        fields_state = self._ensure_field_state(h)
        rows, header = self._load_rows(period, sort_order, limit, sort_field, fields_state, lang)
        aligned = h.dynamic_align_format(rows) if rows else _t("data.no_data", lang=lang)
        time_info = h.get_current_time_display()
        sort_symbol = "🔽" if sort_order == "desc" else "🔼"
        display_sort_field = format_sort_field(sort_field, lang=lang, field_lists=[getattr(self, "general_display_fields", []), getattr(self, "special_display_fields", [])])
        text = (
            f"{_t('card.bb.title', lang=lang)}\n"
            f"{_t('card.common.update_time', lang=lang).format(time=time_info['full'])}\n"
            f"{_t('card.common.sort_info', lang=lang).format(period=period, field=display_sort_field, symbol=sort_symbol)}\n"
            f"{header}\n"
            f"```\n{aligned}\n```\n"
            f"{_t('card.bb.hint', lang=lang)}\n"
            f"{_t('card.common.last_update', lang=lang).format(time=time_info['full'])}"
        )
        if callable(ensure):
            text = ensure(text, _t(self.FALLBACK))
        kb = self._build_keyboard(h)
        return text, kb

    def _build_keyboard(self, h):
        fields_state = self._ensure_field_state(h)
        period = h.user_states.get("bb_period", "15m")
        sort_order = h.user_states.get("bb_sort", "desc")
        current_limit = h.user_states.get("bb_limit", 10)
        current_sort_field = h.user_states.get("bb_sort_field", "bandwidth")
        market = h.user_states.get("bb_market", "futures")

        def b(label: str, data: str, active: bool = False, disabled: bool = False):

            if disabled:

                return InlineKeyboardButton(label, callback_data=data or 'nop')

            return _btn_auto(None, label, data, active=active)


        kb: List[List[InlineKeyboardButton]] = []

        show_market_row = False
        if show_market_row:
            kb.append([
                b("现货", "bb_market_spot", active=market == "spot"),
                b("期货", "bb_market_futures", active=market == "futures"),
            ])

        gen_row: List[InlineKeyboardButton] = []
        for col_id, label, is_core in self.general_display_fields:
            state_on = fields_state.get(col_id, is_core or True)
            show_label = label if state_on or is_core else f"❎{label}"
            gen_row.append(InlineKeyboardButton(show_label, callback_data="bb_nop" if is_core else f"field_bb_toggle_{col_id}"))
        kb.append(gen_row)

        spec_row: List[InlineKeyboardButton] = []
        for col_id, label, is_core in self.special_display_fields:
            state_on = fields_state.get(col_id, is_core)
            show_label = label if state_on or is_core else f"❎{label}"
            spec_row.append(InlineKeyboardButton(show_label, callback_data="bb_nop" if is_core else f"field_bb_toggle_{col_id}"))
        kb.append(spec_row)

        general_sort = [("quote_volume", "成交额"), ("振幅", "振幅"), ("成交笔数", "成交笔数"), ("主动买卖比", "主动买卖比"), ("price", "价格")]
        kb.append([
            b(lbl, f"bb_sort_field_{fid}", active=(current_sort_field == fid))
            for fid, lbl in general_sort
        ])

        special_sort = [
            ("bandwidth", "带宽"),
            ("percent_b", "百分比"),
            ("mid_slope", "中轨斜率"),
            ("mid_price", "中轨价"),
            ("upper", "上轨价"),
            ("lower", "下轨价"),
        ]
        kb.append([
            b(lbl, f"bb_sort_field_{fid}", active=(current_sort_field == fid))
            for fid, lbl in special_sort
        ])
        periods = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]
        kb.append([b(p, f"bb_period_{p}", active=p == period) for p in periods])

        kb.append([
            b("降序", "bb_sort_desc", active=sort_order == "desc"),
            b("升序", "bb_sort_asc", active=sort_order == "asc"),
            b("10条", "bb_limit_10", active=current_limit == 10),
            b("20条", "bb_limit_20", active=current_limit == 20),
            b("30条", "bb_limit_30", active=current_limit == 30),
        ])

        kb.append([
            _btn_auto(None, "🏠主菜单", "ranking_menu"),
            _btn_auto(None, "🔄刷新", "bb_ranking_refresh"),
        ])

        return InlineKeyboardMarkup(kb)

    def _load_rows(self, period: str, sort_order: str, limit: int, sort_field: str, field_state: Dict[str, bool], lang: str | None = None) -> Tuple[List[List[str]], str]:
        items: List[Dict] = []
        try:
            metrics = self.provider.merge_with_base("BB榜单", period, base_fields=["当前价格", "成交额"])
            for row in metrics:
                sym = format_symbol(row.get("symbol") or row.get("交易对") or row.get("币种") or "")
                if not sym:
                    continue
                items.append({
                    "symbol": sym,
                    # 兼容多种字段命名：中文/英文/% 后缀
                    "bandwidth": float(row.get("带宽") or row.get("bandwidth") or row.get("带宽%") or 0),
                    # 百分比b 有多种命名（百分比/百分比b/percent_b/位置百分比），逐个兼容
                    "percent_b": float(row.get("百分比") or row.get("百分比b") or row.get("percent_b") or row.get("位置百分比") or 0),
                    "mid_slope": float(row.get("中轨斜率") or 0),
                    "mid_price": float(row.get("中轨价格") or 0),
                    "upper": float(row.get("上轨价格") or 0),
                    "lower": float(row.get("下轨价格") or 0),
                    "price": float(row.get("price") or row.get("当前价格") or row.get("价格") or 0),
                    "quote_volume": float(row.get("quote_volume") or 0),
                    "振幅": float(row.get("振幅") or 0),
                    "成交笔数": float(row.get("成交笔数") or 0),
                    "主动买卖比": float(row.get("主动买卖比") or 0),
                })
        except Exception as exc:  # pragma: no cover
            self._logger.warning("读取布林带榜单失败: %s", exc)
            return [], _t("card.header.rank_symbol", lang=lang)

        reverse = sort_order != "asc"
        items.sort(key=lambda x: x.get(sort_field, 0), reverse=reverse)
        active_special = [f for f in self.special_display_fields if field_state.get(f[0], f[2] or True)]
        active_general = [f for f in self.general_display_fields if field_state.get(f[0], f[2] or True)]

        header_parts = [_t("card.header.rank", lang=lang), _t("card.header.symbol", lang=lang)] + [translate_field(lab, lang=lang) for _, lab, _ in active_special] + [translate_field(lab, lang=lang) for _, lab, _ in active_general]

        rows: List[List[str]] = []
        for idx, item in enumerate(items[:limit], 1):
            row: List[str] = [f"{idx}", item["symbol"]]
            for col_id, _, _ in active_special:
                val = item.get(col_id)
                if isinstance(val, (int, float)):
                    if col_id == "percent_b":
                        row.append(f"{val*100:.2f}%")
                    else:
                        row.append(f"{val:.4f}")
                else:
                    row.append(str(val) if val not in (None, "") else "-")
            for col_id, _, _ in active_general:
                val = item.get(col_id)
                if col_id == "振幅":
                    pct = (val * 100) if isinstance(val, (int, float)) and val <= 5 else val
                    row.append(f"{pct:.2f}%" if isinstance(pct, (int, float)) else "-")
                elif col_id == "quote_volume":
                    row.append(self._format_volume(val))
                elif col_id == "price":
                    row.append(f"{val:.4f}" if val else "-")
                elif isinstance(val, (int, float)):
                    row.append(f"{val:.2f}")
                else:
                    row.append(str(val) if val not in (None, "") else "-")
            rows.append(row)
        return rows, "/".join(header_parts)

    # ---------- 工具 ----------
    def _ensure_field_state(self, h) -> Dict[str, bool]:
        state = h.user_states.get("bb_fields")
        if not state:
            state = {}
            for col, _, _ in self.general_display_fields + self.special_display_fields:
                # 默认开启带宽与百分比，其余关闭
                if col in {"bandwidth", "percent_b"}:
                    state[col] = True
                else:
                    state[col] = False
            # 全局默认关闭的通用字段（仅初始化时执行）
            for _off in {"quote_volume", "振幅", "成交笔数", "主动买卖比"}:
                if _off in state:
                    state[_off] = False
            h.user_states["bb_fields"] = state

        return state

    def _is_core(self, col_id: str) -> bool:
        for cid, _, is_core in self.general_display_fields + self.special_display_fields:
            if cid == col_id:
                return is_core
        return False

    @staticmethod
    def _format_volume(value: float) -> str:
        if value is None:
            return "-"
        sign = "+" if value > 0 else "-" if value < 0 else ""
        v = abs(value)
        if v >= 1e9:
            return f"{sign}{v/1e9:.2f}B"
        if v >= 1e6:
            return f"{sign}{v/1e6:.2f}M"
        if v >= 1e3:
            return f"{sign}{v/1e3:.2f}K"
        return f"{sign}{v:.2f}"


CARD = 布林带排行卡片()
