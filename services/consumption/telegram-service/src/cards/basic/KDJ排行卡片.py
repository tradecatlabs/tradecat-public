"""KDJ 随机指标排行榜卡片

数据源：PostgreSQL 指标库（tg_cards）表 KDJ随机指标扫描器.py
字段：排名,币种,周期,方向,强度,J值,K值,D值,信号概述,当前价格,成交额（USDT）,数据时间
"""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple

from cards.base import RankingCard, format_number
from cards.data_provider import get_ranking_provider, format_symbol
from cards.i18n import btn_auto as _btn_auto, gettext as _t, resolve_lang, translate_field, format_sort_field
from telegram import InlineKeyboardButton, InlineKeyboardMarkup



class KDJ排行卡片(RankingCard):
    FALLBACK = "card.kdj.fallback"
    provider = get_ranking_provider()
    DEFAULT_FIELDS_STATE = {
        # 通用字段默认关闭
        "quote_volume": False,
        "振幅": False,
        "成交笔数": False,
        "主动买卖比": False,
        "price": True,  # 价格默认开启
        # 专用字段默认开启
        "j": True,
        "k": True,
        "d": True,
        "direction": True,
    }

    def __init__(self) -> None:
        super().__init__(
            card_id="kdj_ranking",
            button_text="🎯 KDJ",
            button_key="card.kdj.btn",
            category="free",
            description="card.kdj.desc",
            default_state={
                "kdj_period": "15m",
                "kdj_sort": "desc",
                "kdj_limit": 10,
                "kdj_sort_field": "quote_volume",
                # 仅有期货数据时默认期货，并隐藏市场切换行
                "kdj_market": "futures",
                "kdj_fields": self.DEFAULT_FIELDS_STATE.copy(),
            },
            callback_prefixes=[
                "kdj_ranking",
                "kdj_period_",
                "kdj_sort_",
                "kdj_limit_",
                "kdj_sort_field_",
                "kdj_market_",
                "kdj_settings",
                "kdj_settings_",
                "field_kdj_toggle_",
            ],
            priority=29,
        )
        self._logger = logging.getLogger(__name__)

        # 字段定义（col_id, label, is_core）
        self.general_display_fields: List[Tuple[str, str, bool]] = [
            ("quote_volume", "成交额", False),
            ("振幅", "振幅", False),
            ("成交笔数", "成交笔数", False),
            ("主动买卖比", "主动买卖比", False),
            ("price", "价格", False),  # 允许开关
        ]
        self.special_display_fields: List[Tuple[str, str, bool]] = [
            ("j", "J", False),
            ("k", "K", False),
            ("d", "D", False),
            ("direction", "信号概述", False),  # 允许开关
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
        if data in (self.card_id, self.entry_callback, "kdj_ranking_refresh"):
            await self._reply(query, h, ensure)
            return True
        if data == "kdj_nop":
            return True
        # 设置菜单
        if data == "kdj_settings":
            await self._edit_settings(query, h, ensure)
            return True
        if data == "kdj_settings_back":
            await self._edit(query, h, ensure)
            return True
        if data.startswith("kdj_market_"):
            h.user_states["kdj_market"] = data.replace("kdj_market_", "")
            await self._edit(query, h, ensure)
            return True
        # 先处理排序字段，避免被 kdj_sort_ 前缀误判
        if data.startswith("kdj_sort_field_"):
            h.user_states["kdj_sort_field"] = data.replace("kdj_sort_field_", "")
            await self._edit(query, h, ensure)
            return True
        if data.startswith("kdj_period_"):
            h.user_states["kdj_period"] = data.replace("kdj_period_", "")
            await self._edit(query, h, ensure)
            return True
        if data.startswith("kdj_sort_"):
            h.user_states["kdj_sort"] = data.replace("kdj_sort_", "")
            await self._edit(query, h, ensure)
            return True
        if data.startswith("kdj_limit_"):
            val = data.replace("kdj_limit_", "")
            if val.isdigit():
                h.user_states["kdj_limit"] = int(val)
                await self._edit(query, h, ensure)
                return True
            return False
        if data.startswith("field_kdj_toggle_"):
            col = data.replace("field_kdj_toggle_", "")
            fields_state = self._ensure_field_state(h)
            if col in fields_state and not self._is_core(col):
                fields_state[col] = not fields_state[col]
                h.user_states["kdj_fields"] = fields_state
            await self._edit_settings(query, h, ensure)
            return True
        return False

    async def _reply(self, query, h, ensure):
        lang = resolve_lang(query)
        text, kb = await self._build_payload(h, ensure, lang, query)
        await query.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

    async def _edit(self, query, h, ensure):
        lang = resolve_lang(query)
        lang = resolve_lang(query)
        text, kb = await self._build_payload(h, ensure, lang, query)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    async def _edit_settings(self, query, h, ensure):
        lang = resolve_lang(query)
        text, kb = await self._build_settings_payload(h, ensure, lang=lang, update=query)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    async def _build_payload(self, h, ensure, lang: str = None, update=None) -> Tuple[str, object]:
        if lang is None and update is not None:
            lang = resolve_lang(update)
        period = h.user_states.get("kdj_period", "15m")
        sort_order = h.user_states.get("kdj_sort", "desc")
        limit = h.user_states.get("kdj_limit", 10)
        sort_field = h.user_states.get("kdj_sort_field", "quote_volume")
        fields_state = self._ensure_field_state(h)
        rows, header = self._load_rows(period, sort_order, limit, sort_field, fields_state, lang)
        aligned = h.dynamic_align_format(rows) if rows else _t("data.no_data", lang=lang)
        display_sort_field = format_sort_field(sort_field, lang=lang, field_lists=[getattr(self, "general_display_fields", []), getattr(self, "special_display_fields", [])])
        time_info = h.get_current_time_display()
        sort_symbol = "🔽" if sort_order == "desc" else "🔼"
        text = (
            f"{_t('card.kdj.title', lang=lang)}\n"
            f"{_t('time.update', update, lang=lang, time=time_info['full'])}\n"
            f"{_t('card.common.sort', update, lang=lang, period=period, field=display_sort_field, symbol=sort_symbol)}\n"
            f"{header}\n"
            f"```\n{aligned}\n```\n"
            f"{_t('card.kdj.hint', lang=lang)}\n"
            f"{_t('time.last_update', update, lang=lang, time=time_info['full'])}"
        )
        if callable(ensure):
            text = ensure(text, _t(self.FALLBACK))
        kb = self._build_keyboard(h)
        return text, kb

    async def _build_settings_payload(self, h, ensure, lang: str = None, update=None) -> Tuple[str, object]:
        period = h.user_states.get("kdj_period", "15m")
        sort_order = h.user_states.get("kdj_sort", "desc")
        limit = h.user_states.get("kdj_limit", 10)
        sort_field = h.user_states.get("kdj_sort_field", "quote_volume")
        fields_state = self._ensure_field_state(h)
        rows, header = self._load_rows(period, sort_order, limit, sort_field, fields_state, lang)
        aligned = h.dynamic_align_format(rows) if rows else _t("data.no_data", lang=lang)
        display_sort_field = format_sort_field(sort_field, lang=lang, field_lists=[getattr(self, "general_display_fields", []), getattr(self, "special_display_fields", [])])
        time_info = h.get_current_time_display()
        sort_symbol = "🔽" if sort_order == "desc" else "🔼"
        text = (
            f"{_t('card.kdj.settings.title', lang=lang)}\n"
            f"{_t('time.update', update, lang=lang, time=time_info['full'])}\n"
            f"{_t('card.common.sort', update, lang=lang, period=period, field=display_sort_field, symbol=sort_symbol)}\n"
            f"{header}\n"
            f"```\n{aligned}\n```\n"
            f"{_t('card.kdj.settings.hint', lang=lang)}"
        )
        if callable(ensure):
            text = ensure(text, _t(self.FALLBACK))
        kb = self._build_settings_keyboard(h)
        return text, kb

    def _build_keyboard(self, h):
        # 状态
        self._ensure_field_state(h)
        period = h.user_states.get("kdj_period", "15m")
        sort_order = h.user_states.get("kdj_sort", "desc")
        current_limit = h.user_states.get("kdj_limit", 10)
        current_sort_field = h.user_states.get("kdj_sort_field", "quote_volume")
        market = h.user_states.get("kdj_market", "spot")

        def b(label: str, data: str, active: bool = False, disabled: bool = False):

            if disabled:

                return InlineKeyboardButton(label, callback_data=data or 'nop')

            return _btn_auto(None, label, data, active=active)


        kb: List[List[InlineKeyboardButton]] = []

        show_market_row = False  # 当前仅期货数据，隐藏市场切换
        if show_market_row:
            kb.append([
                b("现货", "kdj_market_spot", active=market == "spot"),
                b("期货", "kdj_market_futures", active=market == "futures"),
            ])

        # 组1 通用排序行
        general_sort = [("quote_volume", "成交额"), ("振幅", "振幅"), ("成交笔数", "成交笔数"), ("主动买卖比", "主动买卖比"), ("price", "价格")]
        kb.append([
            b(lbl, f"kdj_sort_field_{fid}", active=(current_sort_field == fid))
            for fid, lbl in general_sort
        ])

        # 组2 专用排序行
        special_sort = [("j", "J"), ("k", "K"), ("d", "D"), ("direction", "方向")]
        kb.append([
            b(lbl, f"kdj_sort_field_{fid}", active=(current_sort_field == fid))
            for fid, lbl in special_sort
        ])

        # 组3 周期
        periods = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]
        kb.append([b(p, f"kdj_period_{p}", active=p == period) for p in periods])

        # 组4 排序方向 + 条数
        kb.append([
            b("降序", "kdj_sort_desc", active=sort_order == "desc"),
            b("升序", "kdj_sort_asc", active=sort_order == "asc"),
            b("10条", "kdj_limit_10", active=current_limit == 10),
            b("20条", "kdj_limit_20", active=current_limit == 20),
            b("30条", "kdj_limit_30", active=current_limit == 30),
        ])

        # 组5 主控
        kb.append([
            _btn_auto(None, "🏠主菜单", "ranking_menu"),
            _btn_auto(None, "⚙️设置", "kdj_settings"),
            _btn_auto(None, "🔄刷新", "kdj_ranking_refresh"),
        ])

        return InlineKeyboardMarkup(kb)

    def _build_settings_keyboard(self, h):
        fields_state = self._ensure_field_state(h)

        def b(label: str, data: str, is_core: bool = False):
            return InlineKeyboardButton(label, callback_data="kdj_nop" if is_core else data)

        kb: List[List[InlineKeyboardButton]] = []

        # 通用字段开关
        gen_row: List[InlineKeyboardButton] = []
        for col_id, label, is_core in self.general_display_fields:
            state_on = fields_state.get(col_id, is_core or True)
            show_label = f"✅{label}" if state_on else label
            gen_row.append(b(show_label, f"field_kdj_toggle_{col_id}", is_core))
        kb.append(gen_row)

        # 专用字段开关
        spec_row: List[InlineKeyboardButton] = []
        for col_id, label, is_core in self.special_display_fields:
            state_on = fields_state.get(col_id, is_core or True)
            show_label = f"✅{label}" if state_on else label
            spec_row.append(b(show_label, f"field_kdj_toggle_{col_id}", is_core))
        kb.append(spec_row)

        # 返回按钮
        kb.append([_btn_auto(None, "⬅️ 返回KDJ", "kdj_settings_back")])

        return InlineKeyboardMarkup(kb)

    def _load_rows(self, period: str, sort_order: str, limit: int, sort_field: str, field_state: Dict[str, bool], lang: str | None = None) -> Tuple[List[List[str]], str]:
        items: List[Dict] = []
        try:
            metrics = self.provider.merge_with_base("KDJ随机指标榜单", period, base_fields=["当前价格", "成交额"])
            for row in metrics:
                sym = format_symbol(row.get("symbol") or row.get("交易对") or row.get("币种") or "")
                if not sym:
                    continue
                items.append({
                    "symbol": sym,
                    "j": float(row.get("J值") or 0),
                    "k": float(row.get("K值") or 0),
                    "d": float(row.get("D值") or 0),
                    "direction": row.get("方向") or row.get("信号概述") or "-",
                    "quote_volume": float(row.get("quote_volume") or 0),
                    "振幅": float(row.get("振幅") or 0),
                    "成交笔数": float(row.get("成交笔数") or 0),
                    "主动买卖比": float(row.get("主动买卖比") or 0),
                    "price": float(row.get("price") or row.get("当前价格") or 0),
                })
        except Exception as exc:  # pragma: no cover
            self._logger.warning("读取 KDJ 榜单失败: %s", exc)
            return [], _t("card.header.rank_symbol", lang=lang)

        reverse = sort_order != "asc"
        items.sort(key=lambda x: x.get(sort_field, 0), reverse=reverse)
        # 决定展示列
        active_special = [f for f in self.special_display_fields if field_state.get(f[0], f[2] or True)]
        active_general = [f for f in self.general_display_fields if field_state.get(f[0], f[2] or True)]

        header_parts = [_t("card.header.rank", lang=lang), _t("card.header.symbol", lang=lang)] + [translate_field(lab, lang=lang) for _, lab, _ in active_special] + [translate_field(lab, lang=lang) for _, lab, _ in active_general]

        rows: List[List[str]] = []
        for idx, item in enumerate(items[:limit], 1):
            row: List[str] = [f"{idx}", item["symbol"]]
            for col_id, _, _ in active_special:
                val = item.get(col_id)
                if col_id in {"j", "k", "d"}:
                    row.append(format_number(val, 2) if val is not None else "-")
                else:
                    row.append(str(val) if val not in (None, "") else "-")
            for col_id, _, _ in active_general:
                val = item.get(col_id)
                if col_id == "振幅":
                    pct = (val * 100) if isinstance(val, (int, float)) and val <= 5 else val
                    row.append(f"{pct:.2f}%" if isinstance(pct, (int, float)) else "-")
                elif col_id in {"quote_volume"}:
                    row.append(self._format_volume(val))
                elif col_id == "price":
                    row.append(format_number(val, 4) if val else "-")
                elif isinstance(val, (int, float)):
                    row.append(format_number(val, 2))
                else:
                    row.append(str(val) if val not in (None, "") else "-")
            rows.append(row)
        return rows, "/".join(header_parts)

    # ---------- 工具 ----------
    def _ensure_field_state(self, h) -> Dict[str, bool]:
        current = h.user_states.get("kdj_fields") or {}
        # 以默认字段集合为基准，补齐缺失键，保留已有的用户选择
        merged = self.DEFAULT_FIELDS_STATE.copy()
        merged.update({k: bool(v) for k, v in current.items() if k in merged})
        h.user_states["kdj_fields"] = merged
        return merged

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


CARD = KDJ排行卡片()
