"""流动性危机排行榜卡片

数据源：PostgreSQL 指标库（tg_cards）表 流动性扫描器.py
字段：排名,币种,周期,流动性指数,危机等级,Amihud贡献,Kyle贡献,波动率贡献,成交量贡献,Amihud原值,Kyle原值,成交额（USDT）,当前价格,数据时间
"""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from cards.data_provider import get_ranking_provider, format_symbol
from cards.i18n import btn_auto as _btn_auto, gettext as _t, resolve_lang, translate_field, format_sort_field

from cards.base import RankingCard


class 流动性排行卡片(RankingCard):
    FALLBACK = "card.liquidity.fallback"
    provider = get_ranking_provider()

    def __init__(self) -> None:
        super().__init__(
            card_id="liquidity_ranking",
            button_text="💧 流动性",
            button_key="card.liquidity.btn",
            category="free",
            description="流动性危机指数榜 (Amihud/Kyle 综合)",
            default_state={
                "liq_period": "15m",
                "liq_sort": "desc",
                "liq_limit": 10,
                "liq_sort_field": "quote_volume",
                "liq_market": "futures",
                "liq_fields": {},
            },
            callback_prefixes=[
                "liquidity_ranking",
                "liquidity_",             # 兼容旧版回调
                "liquidity_period_",      # 兼容旧版周期
                "liquidity_sort_",        # 兼容旧版排序
                "liquidity_limit_",       # 兼容旧版条数
                "liquidity_sort_field_",  # 兼容旧版排序字段
                "liq_period_",
                "liq_sort_",
                "liq_limit_",
                "liq_sort_field_",
                "liq_market_",
                "field_liq_toggle_",
            ],
            priority=33,
        )
        self._logger = logging.getLogger(__name__)

        self.general_display_fields: List[Tuple[str, str, bool]] = [
            ("quote_volume", "成交额", False),
            ("振幅", "振幅", False),
            ("成交笔数", "成交笔数", False),
            ("主动买卖比", "主动买卖比", False),
            ("price", "价格", False),
        ]
        self.special_display_fields: List[Tuple[str, str, bool]] = [
            ("index", "得分", True),
            ("level", "等级", True),
            ("amihud_score", "Amihud得分", False),
            ("kyle_score", "Kyle得分", False),
            ("vol_score", "波动率得分", False),
            ("volumn_score", "成交量得分", False),
            ("amihud_raw", "Amihud原值", False),
            ("kyle_raw", "Kyle原值", False),
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
        if data in (self.card_id, self.entry_callback, "liquidity_ranking_refresh"):
            await self._reply(query, h, ensure)
            return True
        if data == "liq_nop":
            return True
        # 兼容旧版前缀（liquidity_*）
        if data.startswith("liquidity_period_"):
            h.user_states["liq_period"] = data.replace("liquidity_period_", "")
            await self._edit(query, h, ensure)
            return True
        if data.startswith("liquidity_sort_field_"):
            h.user_states["liq_sort_field"] = data.replace("liquidity_sort_field_", "")
            await self._edit(query, h, ensure)
            return True
        if data.startswith("liquidity_sort_"):
            h.user_states["liq_sort"] = data.replace("liquidity_sort_", "")
            await self._edit(query, h, ensure)
            return True
        if data.startswith("liquidity_limit_"):
            val = data.replace("liquidity_limit_", "")
            if val.isdigit():
                h.user_states["liq_limit"] = int(val)
                await self._edit(query, h, ensure)
                return True
            return False

        if data.startswith("liq_market_"):
            h.user_states["liq_market"] = data.replace("liq_market_", "")
            await self._edit(query, h, ensure)
            return True
        if data.startswith("liq_sort_field_"):
            h.user_states["liq_sort_field"] = data.replace("liq_sort_field_", "")
            await self._edit(query, h, ensure)
            return True
        if data.startswith("liq_period_"):
            h.user_states["liq_period"] = data.replace("liq_period_", "")
            await self._edit(query, h, ensure)
            return True
        if data.startswith("liq_sort_"):
            h.user_states["liq_sort"] = data.replace("liq_sort_", "")
            await self._edit(query, h, ensure)
            return True
        if data.startswith("liq_limit_"):
            val = data.replace("liq_limit_", "")
            if val.isdigit():
                h.user_states["liq_limit"] = int(val)
                await self._edit(query, h, ensure)
                return True
            return False
        if data.startswith("field_liq_toggle_"):
            col = data.replace("field_liq_toggle_", "")
            fields_state = self._ensure_field_state(h)
            if col in fields_state:
                fields_state[col] = not fields_state[col]
                h.user_states["liq_fields"] = fields_state
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
        period = h.user_states.get("liq_period", "15m")
        sort_order = h.user_states.get("liq_sort", "desc")
        limit = h.user_states.get("liq_limit", 10)
        sort_field = h.user_states.get("liq_sort_field", "index")
        fields_state = self._ensure_field_state(h)
        rows, header = self._load_rows(period, sort_order, limit, sort_field, fields_state, lang)
        aligned = h.dynamic_align_format(rows) if rows else _t("data.no_data", lang=lang)
        time_info = h.get_current_time_display()
        sort_symbol = "🔽" if sort_order == "desc" else "🔼"
        display_sort_field = format_sort_field(sort_field, lang=lang, field_lists=[getattr(self, "general_display_fields", []), getattr(self, "special_display_fields", [])])
        text = (
            f"{_t('card.liquidity.title', lang=lang)}\n"
            f"{_t('card.common.update_time', lang=lang).format(time=time_info['full'])}\n"
            f"{_t('card.common.sort_info', lang=lang).format(period=period, field=display_sort_field, symbol=sort_symbol)}\n"
            f"{header}\n"
            f"```\n{aligned}\n```\n"
            f"{_t('card.liquidity.hint', lang=lang)}\n"
            f"{_t('card.common.last_update', lang=lang).format(time=time_info['full'])}"
        )
        if callable(ensure):
            text = ensure(text, _t(self.FALLBACK))
        kb = self._build_keyboard(h)
        return text, kb

    def _build_keyboard(self, h):
        fields_state = self._ensure_field_state(h)
        period = h.user_states.get("liq_period", "15m")
        sort_order = h.user_states.get("liq_sort", "desc")
        current_limit = h.user_states.get("liq_limit", 20)
        current_sort_field = h.user_states.get("liq_sort_field", "quote_volume")
        market = h.user_states.get("liq_market", "futures")

        def b(label: str, data: str, active: bool = False, disabled: bool = False):

            if disabled:

                return InlineKeyboardButton(label, callback_data=data or 'nop')

            return _btn_auto(None, label, data, active=active)


        kb: List[List[InlineKeyboardButton]] = []

        show_market_row = False
        if show_market_row:
            kb.append([
                b("现货", "liq_market_spot", active=market == "spot"),
                b("期货", "liq_market_futures", active=market == "futures"),
            ])

        gen_row: List[InlineKeyboardButton] = []
        for col_id, label, _ in self.general_display_fields:
            state_on = fields_state.get(col_id, True)
            show_label = label if state_on else f"❎{label}"
            gen_row.append(InlineKeyboardButton(show_label, callback_data=f"field_liq_toggle_{col_id}"))
        kb.append(gen_row)

        spec_row: List[InlineKeyboardButton] = []
        for col_id, label, _ in self.special_display_fields:
            state_on = fields_state.get(col_id, False)  # 默认关闭专用得分/原值
            show_label = label if state_on else f"❎{label}"
            spec_row.append(InlineKeyboardButton(show_label, callback_data=f"field_liq_toggle_{col_id}"))
        kb.append(spec_row)

        general_sort = [("quote_volume", "成交额"), ("振幅", "振幅"), ("成交笔数", "成交笔数"), ("主动买卖比", "主动买卖比"), ("price", "价格")]
        kb.append([
            b(lbl, f"liq_sort_field_{fid}", active=(current_sort_field == fid))
            for fid, lbl in general_sort
        ])

        special_sort = [
            ("index", "得分"),
            ("level", "等级"),
            ("amihud_score", "Amihud得分"),
            ("kyle_score", "Kyle得分"),
            ("vol_score", "波动率得分"),
            ("volumn_score", "成交量得分"),
            ("amihud_raw", "Amihud原值"),
            ("kyle_raw", "Kyle原值"),
        ]
        kb.append([
            b(lbl, f"liq_sort_field_{fid}", active=(current_sort_field == fid))
            for fid, lbl in special_sort
        ])
        periods = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]
        kb.append([b(p, f"liq_period_{p}", active=p == period) for p in periods])

        kb.append([
            b("降序", "liq_sort_desc", active=sort_order == "desc"),
            b("升序", "liq_sort_asc", active=sort_order == "asc"),
            b("10条", "liq_limit_10", active=current_limit == 10),
            b("20条", "liq_limit_20", active=current_limit == 20),
            b("30条", "liq_limit_30", active=current_limit == 30),
        ])

        kb.append([
            _btn_auto(None, "🏠主菜单", "ranking_menu"),
            _btn_auto(None, "🔄刷新", "liquidity_ranking_refresh"),
        ])

        return InlineKeyboardMarkup(kb)

    def _load_rows(self, period: str, sort_order: str, limit: int, sort_field: str, field_state: Dict[str, bool], lang: str | None = None) -> Tuple[List[List[str]], str]:
        items: List[Dict] = []
        try:
            metrics = self.provider.merge_with_base("流动性榜单", period, base_fields=["当前价格", "成交额"])
            for row in metrics:
                sym = format_symbol(row.get("symbol") or row.get("币种") or row.get("交易对") or "")
                if not sym:
                    continue
                items.append({
                    "symbol": sym,
                    "index": float(row.get("流动性得分") or row.get("流动性指数") or 0),
                    "level": row.get("流动性等级") or row.get("危机等级") or "-",
                    "amihud_score": float(row.get("Amihud得分") or 0),
                    "kyle_score": float(row.get("Kyle得分") or 0),
                    "vol_score": float(row.get("波动率得分") or 0),
                    "volumn_score": float(row.get("成交量得分") or 0),
                    "amihud_raw": float(row.get("Amihud原值") or 0),
                    "kyle_raw": float(row.get("Kyle原值") or 0),
                    "price": float(row.get("price") or row.get("当前价格") or 0),
                    "quote_volume": float(row.get("quote_volume") or row.get("成交额") or 0),
                    "成交笔数": float(row.get("成交笔数") or row.get("交易次数") or 0),
                    "振幅": float(row.get("振幅") or 0),
                    "主动买卖比": float(row.get("主动买卖比") or 0),
                })
        except Exception as exc:  # pragma: no cover
            self._logger.warning("读取流动性榜单失败: %s", exc)
            return [], _t("card.header.rank_symbol", lang=lang)

        reverse = sort_order != "asc"
        items.sort(key=lambda x: x.get(sort_field, 0), reverse=reverse)
        active_special = [f for f in self.special_display_fields if field_state.get(f[0], True)]
        active_general = [f for f in self.general_display_fields if field_state.get(f[0], True)]

        header_parts = [_t("card.header.rank", lang=lang), _t("card.header.symbol", lang=lang)] + [translate_field(lab, lang=lang) for _, lab, _ in active_special] + [translate_field(lab, lang=lang) for _, lab, _ in active_general]

        rows: List[List[str]] = []
        for idx, item in enumerate(items[:limit], 1):
            row: List[str] = [f"{idx}", item["symbol"]]
            for col_id, _, _ in active_special:
                val = item.get(col_id)
                if isinstance(val, (int, float)):
                    row.append(f"{val:.2f}")
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
        state = h.user_states.get("liq_fields")
        if not state:
            state = {}
            for col, _, _ in self.general_display_fields + self.special_display_fields:
                state[col] = False
            # 默认仅开启：得分、等级
            for _on in {"index", "level"}:
                if _on in state:
                    state[_on] = True
            h.user_states["liq_fields"] = state

        return state

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


CARD = 流动性排行卡片()
