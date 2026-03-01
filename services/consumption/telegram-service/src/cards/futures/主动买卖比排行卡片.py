"""主动买卖比排行榜卡片

特性：
- 文案/键盘与 KDJ 模板对齐：字段开关默认仅关键字段开启，关闭状态显示“❎”前缀
- 数据源：PostgreSQL 指标库（tg_cards）表 主动买卖比扫描器.py（provider.merge_with_base）
- 支持字段开关、排序字段切换、周期/方向/条数切换
"""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from cards.base import RankingCard
from cards.data_provider import get_ranking_provider, format_symbol
from cards.i18n import btn_auto as _btn_auto, gettext as _t, format_sort_field, resolve_lang, translate_field
from cards.排行榜服务 import DEFAULT_PERIODS, normalize_period


class 主动买卖比排行卡片(RankingCard):
    FALLBACK = "card.taker_ratio.fallback"

    def __init__(self) -> None:
        super().__init__(
            card_id="buy_sell_ratio_ranking",
            button_text="🧾 主动买卖比",
            button_key="card.taker_ratio.btn",
            category="free",
            description="按主动买成交额占比排序，洞察买盘强弱",
            default_state={
                "bsr_period": "15m",
                "bsr_sort": "desc",
                "bsr_limit": 10,
                "bsr_sort_field": "buy_ratio",
                "bsr_fields": {},
            },
            callback_prefixes=[
                "buy_sell_ratio_ranking",
                "buy_sell_ratio_",
                "buy_sell_ratio_period_",
                "buy_sell_ratio_sort_",
                "buy_sell_ratio_limit_",
                "buy_sell_ratio_sort_field_",
                "field_bsr_toggle_",
            ],
            priority=12,
        )
        self._logger = logging.getLogger(__name__)
        self.provider = get_ranking_provider()

        # 通用字段：成交额/振幅/成交笔数/主动买卖比/价格（价格默认开）
        self.general_display_fields: List[Tuple[str, str, bool]] = [
            ("quote_volume", "成交额", False),
            ("振幅", "振幅", False),
            ("成交笔数", "成交笔数", False),
            ("主动买卖比", "主动买卖比", False),
            ("price", "价格", False),
        ]
        # 专用字段：买卖比、买额、卖额（买卖比默认开）
        self.special_display_fields: List[Tuple[str, str, bool]] = [
            ("buy_ratio", "买卖比", False),
            ("buy_quote", "主动买额", False),
            ("sell_quote", "主动卖额", False),
        ]

    # ------------------ 回调处理 ------------------
    async def handle_callback(self, update, context, services: Dict[str, object]) -> bool:
        query = update.callback_query
        if not query:
            return False

        handler = services.get("user_handler")
        ensure_valid_text = services.get("ensure_valid_text")
        if handler is None:
            self._logger.error("❌ 无法处理 buy_sell_ratio_ranking：user_handler 缺失")
            return False

        data = query.data or ""
        if data in (self.card_id, self.entry_callback, "buy_sell_ratio_ranking_refresh"):
            await self._reply(query, handler, ensure_valid_text)
            return True
        if data == "bsr_nop":
            return True
        if data.startswith("buy_sell_ratio_sort_field_"):
            handler.user_states["bsr_sort_field"] = data.replace("buy_sell_ratio_sort_field_", "")
            await self._edit(query, handler, ensure_valid_text)
            return True
        if data.startswith("buy_sell_ratio_period_"):
            handler.user_states["bsr_period"] = data.replace("buy_sell_ratio_period_", "")
            await self._edit(query, handler, ensure_valid_text)
            return True

        if data.startswith("buy_sell_ratio_sort_"):
            handler.user_states["bsr_sort"] = data.replace("buy_sell_ratio_sort_", "")
            await self._edit(query, handler, ensure_valid_text)
            return True

        if data.startswith("buy_sell_ratio_limit_"):
            val = data.replace("buy_sell_ratio_limit_", "")
            if val.isdigit():
                handler.user_states["bsr_limit"] = int(val)
                await self._edit(query, handler, ensure_valid_text)
                return True
            return False
        if data.startswith("field_bsr_toggle_"):
            col = data.replace("field_bsr_toggle_", "")
            fields_state = self._ensure_field_state(handler)
            if col in fields_state and not self._is_core(col):
                fields_state[col] = not fields_state[col]
                handler.user_states["bsr_fields"] = fields_state
            await self._edit(query, handler, ensure_valid_text)
            return True

        return False

    async def _reply(self, query, handler, ensure_valid_text):
        lang = resolve_lang(query)
        text, kb = await self._build_payload(handler, ensure_valid_text, lang, query)
        await query.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

    async def _edit(self, query, handler, ensure_valid_text):
        lang = resolve_lang(query)
        text, kb = await self._build_payload(handler, ensure_valid_text, lang, query)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    async def _build_payload(self, handler, ensure_valid_text, lang=None, query=None) -> Tuple[str, object]:
        if lang is None and query is not None:
            lang = resolve_lang(query)
        limit = handler.user_states.get("bsr_limit", 10)
        period = handler.user_states.get("bsr_period", "15m")
        period = normalize_period(period, DEFAULT_PERIODS, default="15m")
        handler.user_states["bsr_period"] = period
        sort_order = handler.user_states.get("bsr_sort", "desc")
        sort_field = handler.user_states.get("bsr_sort_field", "buy_ratio")
        fields_state = self._ensure_field_state(handler)

        rows, header = self._load_rows(handler, period, sort_order, limit, sort_field, fields_state, lang)
        aligned = handler.dynamic_align_format(rows) if rows else _t("data.no_data", lang=lang)
        time_info = handler.get_current_time_display()
        sort_symbol = "🔽" if sort_order == "desc" else "🔼"
        display_sort_field = format_sort_field(sort_field, lang=lang, field_lists=[getattr(self, "general_display_fields", []), getattr(self, "special_display_fields", [])])
        text = (
            f"{_t('card.taker_ratio.title', lang=lang)}\n"
            f"{_t('card.common.update_time', lang=lang).format(time=time_info['full'])}\n"
            f"{_t('card.common.sort_info', lang=lang).format(period=period, field=display_sort_field, symbol=sort_symbol)}\n"
            f"{header}\n"
            f"```\n{aligned}\n```\n"
            f"{_t('card.taker_ratio.hint', lang=lang)}\n"
            f"{_t('card.common.last_update', lang=lang).format(time=time_info['full'])}"
        )

        if callable(ensure_valid_text):
            text = ensure_valid_text(text, self.FALLBACK)

        kb = self._build_keyboard(handler)
        if hasattr(handler, "set_card_cache"):
            handler.set_card_cache(self.card_id, text, kb)
        return text, kb

    # -------------- 键盘 --------------
    def _build_keyboard(self, handler):
        fields_state = self._ensure_field_state(handler)
        period = handler.user_states.get("bsr_period", "15m")
        sort_order = handler.user_states.get("bsr_sort", "desc")
        current_limit = handler.user_states.get("bsr_limit", 10)
        current_sort_field = handler.user_states.get("bsr_sort_field", "buy_ratio")

        def b(label: str, data: str, active: bool = False, disabled: bool = False):

            if disabled:

                return InlineKeyboardButton(label, callback_data=data or 'nop')

            return _btn_auto(None, label, data, active=active)


        kb: List[List[InlineKeyboardButton]] = []

        # 通用字段开关行
        gen_row: List[InlineKeyboardButton] = []
        for col_id, label, is_core in self.general_display_fields:
            state_on = fields_state.get(col_id, True if is_core else False)
            show_label = label if state_on or is_core else f"❎{label}"
            gen_row.append(
                InlineKeyboardButton(
                    show_label,
                    callback_data=f"field_bsr_toggle_{col_id}",
                )
            )
        kb.append(gen_row)

        # 专用字段开关行
        spec_row: List[InlineKeyboardButton] = []
        for col_id, label, is_core in self.special_display_fields:
            state_on = fields_state.get(col_id, True if is_core else False)
            show_label = label if state_on or is_core else f"❎{label}"
            spec_row.append(
                InlineKeyboardButton(
                    show_label,
                    callback_data=f"field_bsr_toggle_{col_id}",
                )
            )
        kb.append(spec_row)

        # 通用排序行
        general_sort = [(cid, lab) for cid, lab, _ in self.general_display_fields]
        kb.append([
            b(lbl, f"buy_sell_ratio_sort_field_{fid}", active=(current_sort_field == fid))
            for fid, lbl in general_sort
        ])

        # 专用排序行
        special_sort = [(cid, lab) for cid, lab, _ in self.special_display_fields]
        kb.append([
            b(lbl, f"buy_sell_ratio_sort_field_{fid}", active=(current_sort_field == fid))
            for fid, lbl in special_sort
        ])

        # 周期行
        kb.append([b(p, f"buy_sell_ratio_period_{p}", active=p == period) for p in DEFAULT_PERIODS])

        # 排序方向 + 条数
        kb.append([
            b("降序", "buy_sell_ratio_sort_desc", active=sort_order == "desc"),
            b("升序", "buy_sell_ratio_sort_asc", active=sort_order == "asc"),
            b("10条", "buy_sell_ratio_limit_10", active=current_limit == 10),
            b("20条", "buy_sell_ratio_limit_20", active=current_limit == 20),
            b("30条", "buy_sell_ratio_limit_30", active=current_limit == 30),
        ])

        # 主控行
        kb.append([
            _btn_auto(None, "🏠主菜单", "ranking_menu"),
            _btn_auto(None, "🔄刷新", "buy_sell_ratio_ranking_refresh"),
        ])

        return InlineKeyboardMarkup(kb)

    # -------------- 数据与字段状态 --------------
    def _load_rows(
        self,
        handler,
        period: str,
        sort_order: str,
        limit: int,
        sort_field: str,
        field_state: Dict[str, bool],
        lang: str | None = None,
    ) -> Tuple[List[List[str]], str]:
        items: List[Dict] = []
        # 优先 metric_service
        service = getattr(handler, "metric_service", None)
        if service and hasattr(service, "获取主动买卖比排行"):
            try:
                rows = service.获取主动买卖比排行("futures", period, limit, sort_order)
                for row in rows:
                    items.append({
                        "symbol": (row.get("symbol") or "").upper(),
                        "buy_ratio": float(row.get("buy_ratio") or 0),
                        "buy_quote": float(row.get("buy_quote") or 0),
                        "sell_quote": float(row.get("sell_quote") or 0),
                        "quote_volume": float(row.get("quote_volume") or 0),
                        "price": float(row.get("last_close") or 0),
                        "振幅": float(row.get("振幅") or 0),
                        "成交笔数": float(row.get("成交笔数") or 0),
                        "主动买卖比": float(row.get("buy_ratio") or 0),
                    })
            except Exception as exc:  # pragma: no cover
                self._logger.warning("metric_service 主动买卖比失败: %s", exc)

        if not items:
            try:
                metrics = self.provider.merge_with_base("主动买卖比榜单", period, base_fields=["成交额", "当前价格", "振幅", "成交笔数", "主动买卖比"])
                for row in metrics:
                    sym = format_symbol(row.get("symbol") or row.get("交易对") or row.get("币种") or "")
                    if not sym:
                        continue
                    items.append({
                        "symbol": sym,
                        "buy_ratio": float(row.get("主动买卖比") or row.get("buy_ratio") or 0),
                        "buy_quote": float(row.get("主动买量") or row.get("buy_quote") or 0),
                        "sell_quote": float(row.get("主动卖量") or row.get("sell_quote") or 0),
                        "price": float(row.get("价格") or row.get("price") or row.get("当前价格") or 0),
                        "quote_volume": float(row.get("成交额") or row.get("quote_volume") or 0),
                        "振幅": float(row.get("振幅") or 0),
                        "成交笔数": float(row.get("成交笔数") or 0),
                        "主动买卖比": float(row.get("主动买卖比") or row.get("buy_ratio") or 0),
                    })
            except Exception as exc:  # pragma: no cover
                self._logger.warning("主动买卖比兜底失败: %s", exc)

        reverse = sort_order != "asc"
        items.sort(key=lambda x: x.get(sort_field, 0), reverse=reverse)

        active_special = [f for f in self.special_display_fields if field_state.get(f[0], f[2] or False)]
        active_general = [f for f in self.general_display_fields if field_state.get(f[0], f[2] or False)]

        header_parts = [_t("card.header.rank", lang=lang), _t("card.header.symbol", lang=lang)] + [translate_field(lab, lang=lang) for _, lab, _ in active_special] + [translate_field(lab, lang=lang) for _, lab, _ in active_general]

        rows: List[List[str]] = []
        for idx, item in enumerate(items[:limit], 1):
            row: List[str] = [f"{idx}", item["symbol"]]
            for col_id, _, _ in active_special:
                val = item.get(col_id)
                if isinstance(val, (int, float)):
                    if col_id == "buy_ratio":
                        row.append(f"{val*100:.2f}%")
                    else:
                        row.append(self._format_volume(val))
                else:
                    row.append(str(val) if val not in (None, "") else "-")
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

    def _ensure_field_state(self, handler) -> Dict[str, bool]:
        state = handler.user_states.get("bsr_fields")
        if not state:
            state = {}
            for col, _, is_core in self.general_display_fields + self.special_display_fields:
                # 买卖比、价格默认开启，其余按 is_core，默认关
                if col in {"buy_ratio", "price"}:
                    state[col] = True
                else:
                    state[col] = True if is_core else False
            # 文档要求默认关闭通用四列（仅初始化时执行）
            for _off in {"quote_volume", "振幅", "成交笔数", "主动买卖比"}:
                if _off in state:
                    state[_off] = False
            handler.user_states["bsr_fields"] = state

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


CARD = 主动买卖比排行卡片()
