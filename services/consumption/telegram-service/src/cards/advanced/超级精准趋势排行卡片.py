"""超级精准趋势榜单卡片

数据源：assets/database/services/telegram-service/market_data.db 表 `超级精准趋势扫描器.py`
字段：趋势方向(1/-1)、趋势持续根数、趋势强度(价距趋势带/带宽)、趋势带、最近翻转时间、量能偏向
默认：15m / 降序 / 10 条；全部字段可开关、可排序；币种展示去掉 USDT 后缀。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from cards.base import RankingCard
from cards.data_provider import get_ranking_provider, format_symbol
from cards.i18n import btn_auto as _btn_auto, gettext as _t, resolve_lang, translate_field, format_sort_field


class 超级精准趋势排行卡片(RankingCard):
    FALLBACK = "card.supertrend.fallback"
    provider = get_ranking_provider()

    SHOW_MARKET_SWITCH = False
    DEFAULT_MARKET = "futures"

    def __init__(self) -> None:
        super().__init__(
            card_id="super_trend_ranking",
            button_text="📐 超级趋势",
            button_key="card.supertrend.btn",
            category="free",
            description="零延迟趋势信号：方向/持续/强度",
            default_state={
                "st_period": "15m",
                "st_sort": "desc",
                "st_limit": 10,
                "st_sort_field": "trend_strength",
                "st_market": self.DEFAULT_MARKET,
                "st_fields": {},
            },
            callback_prefixes=[
                "super_trend_ranking",
                "st_",
                "st_period_",
                "st_sort_",
                "st_limit_",
                "st_sort_field_",
                "st_market_",
                "field_st_toggle_",
            ],
            priority=32,
        )
        self._logger = logging.getLogger(__name__)

        # 通用字段（来自基础数据表）
        self.general_display_fields: List[Tuple[str, str, bool]] = [
            ("quote_volume", "成交额", False),
            ("振幅", "振幅", False),
            ("成交笔数", "成交笔数", False),
            ("主动买卖比", "主动买卖比", False),
            ("price", "价格", False),
        ]

        # 专用字段（来自超级精准趋势表）
        self.special_display_fields: List[Tuple[str, str, bool]] = [
            ("trend_strength", "强度", False),
            ("trend_duration", "持续根数", False),
            ("trend_dir", "方向", False),
            ("delta_volume", "量能偏向", False),
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

        if data in (self.card_id, self.entry_callback, "st_refresh"):
            await self._reply(query, h, ensure)
            return True

        if data.startswith("st_sort_field_"):
            h.user_states["st_sort_field"] = data.replace("st_sort_field_", "")
            await self._edit(query, h, ensure)
            return True

        if data.startswith("st_market_"):
            h.user_states["st_market"] = data.replace("st_market_", "")
            await self._edit(query, h, ensure)
            return True

        if data.startswith("st_period_"):
            h.user_states["st_period"] = data.replace("st_period_", "")
            await self._edit(query, h, ensure)
            return True
        if data.startswith("st_sort_"):
            h.user_states["st_sort"] = data.replace("st_sort_", "")
            await self._edit(query, h, ensure)
            return True
        if data.startswith("st_limit_"):
            val = data.replace("st_limit_", "")
            if val.isdigit():
                h.user_states["st_limit"] = int(val)
                await self._edit(query, h, ensure)
                return True
            return False

        if data.startswith("field_st_toggle_"):
            col = data.replace("field_st_toggle_", "")
            fields_state = self._ensure_field_state(h)
            if col in fields_state:
                fields_state[col] = not fields_state[col]
                h.user_states["st_fields"] = fields_state
            await self._edit(query, h, ensure)
            return True
        return False

    # ========== 渲染 ==========
    async def _reply(self, query, h, ensure):
        lang = resolve_lang(query)
        text, kb = await self._build_payload(h, ensure, lang, query)
        await query.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

    async def _edit(self, query, h, ensure):
        lang = resolve_lang(query)
        text, kb = await self._build_payload(h, ensure, lang, query)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    async def _build_payload(self, h, ensure, lang=None, query=None):
        if lang is None and query is not None:
            lang = resolve_lang(query)
        period = h.user_states.get("st_period", "15m")
        sort_order = h.user_states.get("st_sort", "desc")
        limit = h.user_states.get("st_limit", 10)
        sort_field = h.user_states.get("st_sort_field", "trend_strength")
        fields_state = self._ensure_field_state(h)

        rows, header = self._load_rows(period, sort_order, limit, sort_field, fields_state, lang)
        aligned = h.dynamic_align_format(rows) if rows else _t("data.no_data", lang=lang)

        sort_symbol = "🔽" if sort_order == "desc" else "🔼"
        display_sort_field = format_sort_field(sort_field, lang=lang, field_lists=[getattr(self, "general_display_fields", []), getattr(self, "special_display_fields", [])])
        time_info = h.get_current_time_display()

        text = (
            f"{_t('card.supertrend.title', lang=lang)}\n"
            f"{_t('card.common.update_time', lang=lang).format(time=time_info['full'])}\n"
            f"{_t('card.common.sort_info', lang=lang).format(period=period, field=display_sort_field, symbol=sort_symbol)}\n"
            f"{header}\n"
            f"```\n{aligned}\n```\n"
            f"{_t('card.supertrend.hint', lang=lang)}\n"
            f"{_t('card.common.last_update', lang=lang).format(time=time_info['full'])}"
        )
        if callable(ensure):
            text = ensure(text, _t(self.FALLBACK))
        kb = self._build_keyboard(h)
        return text, kb

    def _build_keyboard(self, h):
        fields_state = self._ensure_field_state(h)
        period = h.user_states.get("st_period", "15m")
        sort_order = h.user_states.get("st_sort", "desc")
        current_limit = h.user_states.get("st_limit", 10)
        current_sort_field = h.user_states.get("st_sort_field", "trend_strength")
        market = h.user_states.get("st_market", self.DEFAULT_MARKET)

        def b(label: str, data: str, active: bool = False):
            return InlineKeyboardButton(f"✅{label}" if active else label, callback_data=data)

        kb: List[List[InlineKeyboardButton]] = []

        if self.SHOW_MARKET_SWITCH:
            kb.append([
                b("现货", "st_market_spot", active=market == "spot"),
                b("期货", "st_market_futures", active=market == "futures"),
            ])

        kb.append([
            InlineKeyboardButton(label if fields_state.get(col, True) else f"❎{label}",
                                 callback_data=f"field_st_toggle_{col}")
            for col, label, _ in self.general_display_fields
        ])

        kb.append([
            InlineKeyboardButton(label if fields_state.get(col, True) else f"❎{label}",
                                 callback_data=f"field_st_toggle_{col}")
            for col, label, _ in self.special_display_fields
        ])

        kb.append([
            b(lbl, f"st_sort_field_{fid}", active=current_sort_field == fid)
            for fid, lbl, _ in self.general_display_fields
        ])

        kb.append([
            b(lbl, f"st_sort_field_{fid}", active=current_sort_field == fid)
            for fid, lbl, _ in self.special_display_fields
        ])

        periods = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]
        kb.append([b(p, f"st_period_{p}", active=p == period) for p in periods])

        kb.append([
            b("降序", "st_sort_desc", active=sort_order == "desc"),
            b("升序", "st_sort_asc", active=sort_order == "asc"),
            b("10条", "st_limit_10", active=current_limit == 10),
            b("20条", "st_limit_20", active=current_limit == 20),
            b("30条", "st_limit_30", active=current_limit == 30),
        ])

        kb.append([
            _btn_auto(None, "🏠主菜单", "ranking_menu"),
            _btn_auto(None, "🔄刷新", "st_refresh"),
        ])

        return InlineKeyboardMarkup(kb)

    # ========== 数据加载 ==========
    def _load_rows(
        self,
        period: str,
        sort_order: str,
        limit: int,
        sort_field: str,
        field_state: Dict[str, bool],
        lang: str | None = None,
    ):
        items: List[Dict] = []
        try:
            metrics = self.provider.merge_with_base(
                "超级精准趋势扫描器.py",
                period,
                base_fields=["当前价格", "成交额", "振幅", "成交笔数", "主动买卖比"],
            )
            for row in metrics:
                sym_raw = row.get("symbol") or row.get("交易对") or ""
                sym = format_symbol(sym_raw)
                if not sym:
                    continue
                items.append({
                    "symbol": sym,
                    "trend_strength": float(row.get("趋势强度") or 0),
                    "trend_duration": float(row.get("趋势持续根数") or 0),
                    "trend_dir": 1 if row.get("趋势方向") == "多" else -1 if row.get("趋势方向") == "空" else 0,
                    "delta_volume": float(row.get("量能偏向") or 0),
                    "quote_volume": float(row.get("成交额") or row.get("quote_volume") or 0),
                    "振幅": float(row.get("振幅") or 0),
                    "成交笔数": float(row.get("成交笔数") or 0),
                    "主动买卖比": float(row.get("主动买卖比") or 0),
                    "price": float(row.get("当前价格") or row.get("price") or 0),
                })
        except Exception as exc:  # pragma: no cover
            self._logger.warning("读取超级趋势榜单失败: %s", exc)
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
                if col_id == "trend_dir":
                    row.append("多" if val and float(val) > 0 else "空")
                elif isinstance(val, (int, float)):
                    row.append(f"{val:.2f}")
                else:
                    row.append("-")
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
                    row.append("-")
            rows.append(row)
        return rows, "/".join(header_parts)

    # ========== 工具 ==========
    def _ensure_field_state(self, h) -> Dict[str, bool]:
        state = h.user_states.get("st_fields")
        if not state:
            state = {}
            for col, _, _ in self.general_display_fields + self.special_display_fields:
                state[col] = True
            # 默认关闭通用的高噪声列
            for _off in {"quote_volume", "振幅", "成交笔数", "主动买卖比", "price"}:
                if _off in state:
                    state[_off] = False
            # 默认仅展示：强度/持续根数/方向，关闭量能偏向
            if "delta_volume" in state:
                state["delta_volume"] = False
            h.user_states["st_fields"] = state
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


# 注册入口
CARD = 超级精准趋势排行卡片()
