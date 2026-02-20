# ruff: noqa: UP017
from __future__ import annotations

import hashlib
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.card_event import CardEvent, CardHeader, CardHint, CardRaw, CardTable
from src.repo import find_repo_root, find_telegram_service_src

_RE_UPDATE = re.compile(r"^⏰\s*更新\s+(?P<val>.+)$")
_RE_SORT = re.compile(r"^📊\s*排序\s+(?P<val>.+)$")
_RE_HINT = re.compile(r"^💡\s*(?P<val>.+)$")
_RE_LAST = re.compile(r"^⏰\s*最后更新\s+(?P<val>.+)$")


def _repo_root() -> Path:
    return find_repo_root(Path(__file__).resolve())


def _telegram_service_src() -> Path:
    return find_telegram_service_src(_repo_root())


class _DummyHandler:
    def __init__(self) -> None:
        self.user_states: dict[str, Any] = {}

    # ==================== 数据对齐（复刻 telegram-service） ====================
    def dynamic_align_format(self, data_rows, left_align_cols: int = 2, align_override=None):
        if not data_rows:
            return "-"

        def _trim_zero(text: str) -> str:
            try:
                if "%" in text:
                    return text
                val = float(text)
                trimmed = f"{val:.8f}".rstrip("0").rstrip(".")
                return "0" if trimmed == "-0" else trimmed
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

        import unicodedata

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
        """复刻 telegram-service 的时间显示：必须优先使用“数据时间”，否则返回占位符。"""
        ts = data_time
        if ts is None:
            try:
                from cards.data_provider import get_latest_data_time

                ts = get_latest_data_time()
            except Exception:
                ts = None

        if ts is None:
            return {"full": "-", "time_only": "--:--", "hour_min": "--:--"}

        if isinstance(ts, str):
            s = ts.strip().replace("Z", "+00:00")
            try:
                ts = datetime.fromisoformat(s)
            except Exception:
                return {"full": s, "time_only": s, "hour_min": s}

        if isinstance(ts, (int, float)):
            ts = datetime.fromtimestamp(ts, tz=timezone.utc)

        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            bj = ts.astimezone(timezone(timedelta(hours=8)))
            return {
                "full": bj.strftime("%Y-%m-%d %H:%M:%S"),
                "time_only": bj.strftime("%H:%M"),
                "hour_min": bj.strftime("%H:%M"),
            }

        return {"full": "-", "time_only": "--:--", "hour_min": "--:--"}


def _parse_card_text(text: str) -> tuple[CardHeader, CardHint, CardTable, dict[str, str]]:
    lines = [ln.rstrip("\n") for ln in (text or "").splitlines() if ln.strip() != ""]
    title = lines[0] if lines else "-"

    update_time = "-"
    sort_desc = "-"
    hint_text = "-"
    last_update = "-"

    header_line = ""
    code_lines: list[str] = []
    in_code = False
    for ln in lines[1:]:
        if ln.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            code_lines.append(ln)
            continue

        if m := _RE_UPDATE.match(ln):
            update_time = m.group("val").strip()
            continue
        if m := _RE_SORT.match(ln):
            sort_desc = m.group("val").strip()
            continue
        if m := _RE_HINT.match(ln):
            hint_text = m.group("val").strip()
            continue
        if m := _RE_LAST.match(ln):
            last_update = m.group("val").strip()
            continue
        if "/" in ln and not header_line and not ln.startswith("http"):
            header_line = ln.strip()

    columns = [c.strip() for c in header_line.split("/") if c.strip()] if header_line else []
    rows: list[dict[str, Any]] = []
    for raw in code_lines:
        raw = raw.strip()
        if not raw:
            continue
        parts = raw.split()
        row: dict[str, Any] = {"_raw": raw}
        for idx, col in enumerate(columns):
            row[col] = parts[idx] if idx < len(parts) else ""
        if not columns:
            row["cells"] = parts
        rows.append(row)

    header = CardHeader(title=title, update_time=update_time, sort_desc=sort_desc)
    hint = CardHint(text=hint_text)
    table = CardTable(columns=columns, rows=rows)
    extracted = {"last_update": last_update}
    return header, hint, table, extracted


def _stable_card_key(card_id: str, ts_utc: str, state: dict[str, Any]) -> str:
    # 必须稳定：对 state 做 canonical JSON（排序），避免 dict 展示差异导致幂等键漂移
    import json

    raw = json.dumps({"card_id": card_id, "ts_utc": ts_utc, "state": state}, ensure_ascii=False, sort_keys=True).encode(
        "utf-8"
    )
    h = hashlib.sha256(raw).hexdigest()[:16]
    return f"cards:{card_id}:{h}:{ts_utc}"


def _find_period_state_key(state: dict[str, Any]) -> str | None:
    # 约定：大多数排行榜卡片用 `<prefix>_period` 作为周期键（如 sr_period/liquid_period/streak_period）
    keys = [k for k, v in state.items() if k.endswith("_period") and isinstance(v, str) and v.strip()]
    if not keys:
        return None
    # 优先“最短”键（更通用），其次字母序稳定
    keys.sort(key=lambda s: (len(s), s))
    return keys[0]


def _find_fields_state_key(state: dict[str, Any]) -> str | None:
    # 约定：多数排行榜卡片用 `<prefix>_fields` 保存“字段开关”（dict[str,bool]）
    keys = [k for k, v in state.items() if k.endswith("_fields") and isinstance(v, dict)]
    if not keys:
        return None
    keys.sort(key=lambda s: (len(s), s))
    return keys[0]


def _force_enable_all_fields(card: Any, state: dict[str, Any]) -> None:
    """
    Sheets 侧诉求是“全字段无遗漏”：对支持字段开关的排行榜卡片，强制把所有可展示字段打开。
    设计要点：
    - 不依赖卡片内部的“默认关闭高噪声列”逻辑（例如 成交额/振幅/成交笔数/...）
    - 只在发现 `<prefix>_fields` 的情况下介入；否则保持卡片默认行为
    """
    fields_key = _find_fields_state_key(state)
    if not fields_key:
        return

    col_ids: list[str] = []
    for attr in ("general_display_fields", "special_display_fields", "display_fields", "special_fields"):
        items = getattr(card, attr, None)
        if not items:
            continue
        if not isinstance(items, list):
            continue
        for it in items:
            try:
                cid = str(it[0]).strip()
            except Exception:
                continue
            if cid and cid not in col_ids:
                col_ids.append(cid)

    if not col_ids:
        # 没找到字段清单：不碰，避免把未知结构写坏
        return

    state[fields_key] = dict.fromkeys(col_ids, True)


def _merge_multi_period_tables(
    *,
    base: CardTable,
    per_period: dict[str, CardTable],
    periods: list[str],
) -> CardTable:
    """
    将“单周期排行榜表”拼成“多周期横向表”：
    - 行：币种（取各周期 union）
    - 列：保留原卡片字段集合（无遗漏），并把“周期”展开为横向列：
      - 先放 `币种`
      - 然后对原表中除 `排名/币种` 之外的每个字段，按周期展开为 `{字段}@{周期}`（例如 `趋势强度@15m`）
      - `排名` 也按同样规则展开（例如 `排名@15m`），避免丢字段/丢信息

    备注：
    - 这样做会显著增加列数；Sheets 看板渲染会按固定宽度自动“分块纵向堆叠”（不丢列）。
    """
    base_cols = base.columns or []
    rank_col = base_cols[0] if len(base_cols) >= 1 else "排名"
    symbol_col = base_cols[1] if len(base_cols) >= 2 else "币种"

    # union_fields：字段全集（包含 rank_col，但不包含 symbol_col）
    union_fields: list[str] = []

    def add_field(name: str) -> None:
        n = str(name or "").strip()
        if not n:
            return
        if n == symbol_col:
            return
        if n not in union_fields:
            union_fields.append(n)

    # 先按 base 表的字段顺序
    for c in base_cols:
        add_field(c)

    # 再把其它周期新增字段补齐（稳定：按 periods 顺序扫描）
    for p in periods:
        t = per_period.get(p)
        if not t:
            continue
        for c in t.columns or []:
            add_field(c)

    # period -> symbol -> field -> value
    per_symbol: dict[str, dict[str, dict[str, str]]] = {}
    base_order: list[str] = []

    def add_rows(table: CardTable, *, period: str, is_base: bool) -> None:
        cols = table.columns or []
        rows = table.rows or []
        if len(cols) < 2:
            return
        r_col = cols[0]
        s_col = cols[1]
        for r in rows:
            sym = str(r.get(s_col) or r.get(symbol_col) or r.get("币种") or r.get("symbol") or "").strip()
            if not sym:
                continue
            by_field = per_symbol.setdefault(sym, {}).setdefault(period, {})
            for f in union_fields:
                # union_fields 里包含 rank_col；因此会自然写入每周期的排名
                val = r.get(f)
                if val is None and f == rank_col and r_col != rank_col:
                    val = r.get(r_col)
                by_field[f] = "" if val is None else str(val)
            if is_base and sym not in base_order:
                base_order.append(sym)

    for p in periods:
        t = per_period.get(p)
        if not t:
            continue
        add_rows(t, period=p, is_base=(t is base))

    # union symbols
    all_syms = set(per_symbol.keys())
    rest = sorted([s for s in all_syms if s not in set(base_order)])
    ordered = base_order + rest

    # columns：币种 + (按字段分组：该字段下的全部周期)
    # 目标：趋势强度(1m/5m/15m/1h/4h/1d/1w) → 持续根数(...) → ...
    columns: list[str] = [symbol_col]
    for f in union_fields:
        for p in periods:
            columns.append(f"{f}@{p}")

    out_rows: list[dict[str, Any]] = []
    for sym in ordered:
        row: dict[str, Any] = {symbol_col: sym}
        for f in union_fields:
            for p in periods:
                key = f"{f}@{p}"
                row[key] = per_symbol.get(sym, {}).get(p, {}).get(f, "")
        out_rows.append(row)

    return CardTable(columns=columns, rows=out_rows)


@dataclass(frozen=True)
class ExportResult:
    card_id: str
    ok: bool
    event: CardEvent | None
    error: str = ""


class TgCardsExporter:
    def __init__(self, *, include_blacklist: bool = False, lang: str = "zh_CN") -> None:
        self._include_blacklist = include_blacklist
        self._lang = lang

    def _prepare_import_path(self) -> None:
        tg_src = _telegram_service_src()
        root = _repo_root()
        # 让 `import libs.*` 可用
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        # 让 `import cards.*` 可用（telegram-service 的 src 包）
        if str(tg_src) not in sys.path:
            sys.path.insert(0, str(tg_src))

    async def export(self, *, only_cards: list[str] | None = None) -> list[ExportResult]:
        self._prepare_import_path()

        # ==================== 币种范围（导出侧强控） ====================
        # 默认行为：
        # - telegram-service 的 cards.data_provider 会按 libs/common/symbols.py 做币种过滤
        # - 这会导致“看板只有 main4 几个币种”，与“使用服务器全量数据”诉求冲突
        #
        # 这里提供一个导出侧开关：SHEETS_EXPORT_SYMBOLS_UNFILTERED=1 时，强制关闭过滤。
        # 实现：把 SYMBOLS_GROUPS 置为 auto（get_configured_symbols_set() -> None），并重置 data_provider 缓存。
        export_groups = (os.environ.get("SHEETS_EXPORT_SYMBOLS_GROUPS", "") or "").strip()
        export_unfiltered = (os.environ.get("SHEETS_EXPORT_SYMBOLS_UNFILTERED", "0") or "0").strip() == "1"
        if export_unfiltered or export_groups:
            # 约定：unfiltered 优先级更高（显式要求“不做过滤”）
            os.environ["SYMBOLS_GROUPS"] = "auto" if export_unfiltered else export_groups
            try:
                from cards.data_provider import reset_symbols_cache

                reset_symbols_cache()
            except Exception:
                pass

        from cards.registry import RankingRegistry

        if self._include_blacklist:
            RankingRegistry.BLACKLIST = set()

        reg = RankingRegistry()
        reg.load_cards()

        results: list[ExportResult] = []
        for card in reg.iter_cards():
            cid = card.card_id
            if only_cards and cid not in only_cards:
                continue
            results.append(await self._export_one(card))
        return results

    async def _export_one(self, card) -> ExportResult:
        handler = _DummyHandler()
        for k, v in card.iter_default_state():
            handler.user_states[k] = v

        ensure = lambda t, _fallback=None: t  # noqa: E731
        try:
            # Sheets 的“全字段无遗漏”口径：对有字段开关的卡片，强制开启全部可展示字段。
            state0 = dict(handler.user_states)
            _force_enable_all_fields(card, state0)
            handler.user_states = dict(state0)

            build = getattr(card, "_build_payload", None)
            if not callable(build):
                return ExportResult(card_id=card.card_id, ok=False, event=None, error="card_no_build_payload")
            # ---------------- multi-period export (7 周期横向) ----------------
            state0 = dict(handler.user_states)
            period_key = _find_period_state_key(state0)

            periods: list[str] | None = None
            try:
                from cards.排行榜服务 import DEFAULT_PERIODS  # type: ignore

                periods = list(DEFAULT_PERIODS)
            except Exception:
                periods = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]

            use_multi = os.environ.get("SHEETS_EXPORT_MULTI_PERIODS", "1").strip() != "0"

            per_text: dict[str, str] = {}
            per_table: dict[str, CardTable] = {}
            base_period = ""
            base_header: CardHeader | None = None
            base_hint: CardHint | None = None
            base_extracted: dict[str, str] = {}
            if use_multi and period_key and periods:
                base_period = str(state0.get(period_key) or "").strip()
                for p in periods:
                    handler.user_states[period_key] = p
                    t, _kb = await build(handler, ensure, self._lang, None)  # type: ignore[misc]
                    per_text[p] = t
                    h, hn, tb, ex = _parse_card_text(t)
                    per_table[p] = tb
                    if (not base_header) and (p == base_period or not base_period):
                        base_header, base_hint, base_extracted = h, hn, ex
                # fallback base：取第一个成功周期
                if not base_header and per_text:
                    first_p = next(iter(per_text.keys()))
                    base_period = first_p
                    base_header, base_hint, _tb0, base_extracted = _parse_card_text(per_text[first_p])

            if base_header and per_table:
                base_table = per_table.get(base_period) or next(iter(per_table.values()))
                merged = _merge_multi_period_tables(base=base_table, per_period=per_table, periods=periods or [])

                # sort_desc：把 “15m XXX(🔽)” 改为 “多周期 XXX(🔽)”
                sort_desc = base_header.sort_desc
                parts = str(sort_desc).split(maxsplit=1)
                if len(parts) == 2:
                    sort_desc = f"多周期 {parts[1]}"
                else:
                    sort_desc = f"多周期 {sort_desc}"

                header = CardHeader(title=base_header.title, update_time=base_header.update_time, sort_desc=sort_desc)
                hint = base_hint or CardHint(text="-")
                # 附加说明：本卡片为多周期横向视图
                hint = CardHint(text=f"{hint.text}（多周期：{','.join(periods or [])}）")
                table = merged
                extracted = {"last_update": base_extracted.get("last_update", "-")}
                raw_text = per_text.get(base_period, next(iter(per_text.values()), "")) if per_text else ""
                raw_json = {
                    "card_id": card.card_id,
                    "state": state0,
                    "multi_period": {
                        "period_key": period_key,
                        "periods": periods,
                        "base_period": base_period,
                        "period_texts": per_text,
                    },
                }
            else:
                text, _kb = await build(handler, ensure, self._lang, None)  # type: ignore[misc]
                header, hint, table, extracted = _parse_card_text(text)
                raw_text = text
                raw_json = {"card_id": card.card_id, "state": state0}

            # 幂等关键：优先使用 data_provider 记录的“数据时间”（UTC），避免每次运行生成新 card_key
            ts = None
            try:
                from cards.data_provider import get_latest_data_time

                ts = get_latest_data_time()
            except Exception:
                ts = None
            if isinstance(ts, datetime):
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                ts_utc = ts.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            else:
                ts_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

            state = dict(state0)
            # 多周期事件：把 multi 的关键信息写入 state，避免 “最后一次循环把 period_key=1w” 导致幂等键漂移
            if use_multi and period_key and periods:
                state["_multi_periods"] = list(periods)
                state["_multi_period_key"] = period_key
            card_key = _stable_card_key(card.card_id, ts_utc, state)
            params: dict[str, Any] = {
                "user_state": state,
                "export_lang": self._lang,
                "last_update": extracted.get("last_update", "-"),
            }

            event = CardEvent(
                schema_version=1,
                card_key=card_key,
                ts_utc=ts_utc,
                source_service="sheets-service",
                card_type=card.card_id,
                header=header,
                params=params,
                table=table,
                hint=hint,
                raw=CardRaw(telegram_text_full=raw_text, payload_json_full=raw_json),
            )
            return ExportResult(card_id=card.card_id, ok=True, event=event)
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            # 即使失败也产出一个“错误卡片事件”，避免“无遗漏”出现黑洞
            ts_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            card_key = _stable_card_key(f"{card.card_id}.error", ts_utc, {})
            event = CardEvent(
                schema_version=1,
                card_key=card_key,
                ts_utc=ts_utc,
                source_service="sheets-service",
                card_type="export_error",
                header=CardHeader(title=f"❌ 导出失败: {card.card_id}", update_time="-", sort_desc="-"),
                params={"card_id": card.card_id, "error": err},
                raw=CardRaw(telegram_text_full=err, payload_json_full={"error": err}),
            )
            return ExportResult(card_id=card.card_id, ok=False, event=event, error=err)
