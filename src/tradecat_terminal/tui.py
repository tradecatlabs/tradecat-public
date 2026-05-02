from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from io import StringIO
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

try:
    import curses
except ImportError:  # pragma: no cover
    curses = None

from tradecat_terminal.cache import init_cache
from tradecat_terminal.i18n import cycle_lang, lang_label, resolve_lang, tr
from tradecat_terminal.lifecycle import probe_dataset
from tradecat_terminal.registry import dataset_to_dict, get_dataset, list_active_datasets
from tradecat_terminal.settings import (
    default_dataset_from_settings,
    default_lang_from_settings,
    tui_fetch_timeout_from_settings,
    tui_probe_interval_from_settings,
)
from tradecat_terminal.view_model import build_dataset_view

MOUSE_WHEEL_STEP = 1
CURSES_POLL_TIMEOUT_MS = 100
DEFAULT_LIVE_PROBE_INTERVAL_SECONDS = 10.0
DEFAULT_LIVE_FETCH_TIMEOUT_SECONDS = 2.0
DEFAULT_BACKGROUND_PROBE_INTERVAL_SECONDS = 60.0
DEFAULT_BACKGROUND_STREAM_PROBE_INTERVAL_SECONDS = 10.0
DEFAULT_TUI_DATASET_KEY = "event_stream"
TUI_DEFAULT_DATASET_ENV = "TRADECAT_TERMINAL_TUI_DEFAULT_DATASET"
TUI_PROBE_INTERVAL_ENV = "TRADECAT_TERMINAL_TUI_PROBE_INTERVAL"
TUI_FETCH_TIMEOUT_ENV = "TRADECAT_TERMINAL_TUI_FETCH_TIMEOUT"
TUI_BACKGROUND_PROBE_ENV = "TRADECAT_TERMINAL_TUI_BACKGROUND_PROBE"
TUI_BACKGROUND_PROBE_INTERVAL_ENV = "TRADECAT_TERMINAL_TUI_BACKGROUND_PROBE_INTERVAL"
TUI_FORCE_CURSES_ENV = "TRADECAT_TERMINAL_FORCE_CURSES"
TUI_FORCE_PLAIN_ENV = "TRADECAT_TERMINAL_FORCE_PLAIN"
TUI_ALLOW_WINDOWS_CURSES_ENV = "TRADECAT_TERMINAL_ALLOW_WINDOWS_CURSES"
TUI_PLAIN_WIDTH_ENV = "TRADECAT_TERMINAL_PLAIN_WIDTH"
DEFAULT_SAFE_PLAIN_WIDTH = 120
MAX_SAFE_PLAIN_WIDTH = 160
BINANCE_FUTURES_URL_TEMPLATE = "https://www.binance.com/zh-CN/futures/{symbol}?type=perpetual"
SYMBOL_HEADER_NAMES = {"交易对", "合约代码", "代码", "币种", "symbol", "Symbol", "SYMBOL"}
SYMBOL_VALUE_RE = re.compile(r"^[A-Z0-9]{2,24}(?:USDT)?$")
URL_RE = re.compile(r"https?://[^\s|]+")


def render_basic_tui(cache_dir: Path, dataset_key: str | None = None, limit: int = 0, lang: str | None = None) -> str:
    return render_safe_plain_tui(cache_dir, dataset_key=dataset_key, limit=limit, lang=lang)


def render_plain_fallback(cache_dir: Path, dataset_key: str | None, limit: int, reason: str, lang: str | None = None) -> str:
    return render_safe_plain_tui(cache_dir, dataset_key=dataset_key, limit=limit, reason=reason, lang=lang)


def render_safe_plain_tui(
    cache_dir: Path,
    dataset_key: str | None = None,
    limit: int = 0,
    *,
    reason: str | None = None,
    lang: str | None = None,
) -> str:
    """用 Rich 为 Windows PowerShell / Web SSH 这类不稳定终端生成无边框静态输出。"""
    resolved_lang = resolve_lang(lang)
    dataset_key = _resolve_startup_dataset_key(cache_dir, dataset_key)
    width = _safe_plain_output_width()
    view = build_dataset_view(cache_dir, dataset_key, lang=resolved_lang)
    console, buffer = _rich_plain_console(width)
    if reason:
        _rich_print_line(console, f"{tr(resolved_lang, 'notice_prefix')}: {reason}")
        _rich_print_line(console, tr(resolved_lang, "plain_fallback"))
    _rich_print_line(console, tr(resolved_lang, "app_title"))
    _rich_print_line(console, f"{tr(resolved_lang, 'cache_label')}: {cache_dir}")
    _rich_print_line(console, f"{tr(resolved_lang, 'current_label')}: {dataset_key} ({_display_name_for_key(dataset_key, resolved_lang)})")
    if not view["rows"]:
        _rich_print_line(console, tr(resolved_lang, "empty_cache_plain"))
        return _rich_export_text(buffer)
    for line in view.get("top_lines") or []:
        _rich_print_line(console, line)
    rows = _rows_for_display(view, start=0, limit=limit)
    _rich_print_rows(console, rows, columns=view.get("columns") or None, width=width)
    return _rich_export_text(buffer)


def render_rows_table(
    rows: list[dict[str, Any]],
    *,
    columns: list[str] | None = None,
    max_columns: int | None = None,
) -> str:
    if not rows:
        return ""
    selected_columns = list(columns or _select_columns(rows))
    if max_columns is not None:
        selected_columns = selected_columns[: max(1, int(max_columns))]
    table_rows = [
        [row.get("row_index", ""), *[_format_cell(_row_values(row).get(column, "")) for column in selected_columns]]
        for row in rows
    ]
    return _render_psql_table(["#", *selected_columns], table_rows)


def _safe_plain_output_width() -> int:
    raw = os.environ.get(TUI_PLAIN_WIDTH_ENV, "").strip()
    if raw:
        try:
            return max(60, min(int(raw), MAX_SAFE_PLAIN_WIDTH))
        except ValueError:
            pass
    columns = shutil.get_terminal_size((DEFAULT_SAFE_PLAIN_WIDTH, 24)).columns
    return max(60, min(int(columns), MAX_SAFE_PLAIN_WIDTH))


def _rich_plain_console(width: int) -> tuple[Console, StringIO]:
    buffer = StringIO()
    console = Console(
        file=buffer,
        width=max(1, int(width)),
        force_terminal=False,
        color_system=None,
        legacy_windows=True,
        soft_wrap=False,
    )
    return console, buffer


def _rich_export_text(buffer: StringIO) -> str:
    return buffer.getvalue().rstrip("\n")


def _rich_print_line(console: Console, text: Any) -> None:
    console.print(Text(_format_cell(text)), overflow="ellipsis", no_wrap=True, highlight=False, crop=True)


def _rich_print_rows(
    console: Console,
    rows: list[dict[str, Any]],
    *,
    columns: list[str] | None,
    width: int,
) -> None:
    selected_columns = list(columns or _select_columns(rows))
    if not rows:
        return
    if len(selected_columns) <= 2:
        console.print(_rich_two_column_table(rows, selected_columns, width=width))
        return
    _rich_print_wide_rows(console, rows, selected_columns, width=width)


def _rich_two_column_table(rows: list[dict[str, Any]], columns: list[str], *, width: int) -> Table:
    selected_columns = columns[:2] or _select_columns(rows)[:2]
    row_width = min(6, max([1, *[_display_width(_format_cell(row.get("row_index", ""))) for row in rows]]))
    first_width = 0
    if selected_columns:
        first_values = [_format_cell(_row_values(row).get(selected_columns[0], "")) for row in rows]
        first_width = min(24, max([10, *[_display_width(value) for value in first_values]]))
    second_width = max(1, int(width) - row_width - first_width - 4)
    table = Table.grid(padding=(0, 1))
    table.add_column(justify="right", no_wrap=True, width=row_width, overflow="ellipsis")
    table.add_column(no_wrap=True, width=first_width, overflow="ellipsis")
    table.add_column(no_wrap=True, width=second_width, overflow="ellipsis")
    first_header = selected_columns[0] if selected_columns else ""
    second_header = selected_columns[1] if len(selected_columns) > 1 else ""
    table.add_row("#", first_header, second_header)
    for row in rows:
        values = _row_values(row)
        first = _format_cell(values.get(selected_columns[0], "")) if selected_columns else ""
        second = _format_cell(values.get(selected_columns[1], "")) if len(selected_columns) > 1 else ""
        table.add_row(_format_cell(row.get("row_index", "")), first, second)
    return table


def _rich_print_wide_rows(console: Console, rows: list[dict[str, Any]], columns: list[str], *, width: int) -> None:
    for row in rows:
        values = _row_values(row)
        row_index = _format_cell(row.get("row_index", ""))
        parts = [f"#{row_index}"]
        for column in columns:
            value = _format_cell(values.get(column, ""))
            if value:
                parts.append(f"{column}={value}")
            if _display_width("  ".join(parts)) >= width:
                break
        console.print(Text("  ".join(parts)), overflow="ellipsis", no_wrap=True, highlight=False, crop=True)


def run_tui(
    cache_dir: Path,
    dataset_key: str | None = None,
    limit: int = 0,
    *,
    interactive: bool = True,
    live: bool = True,
    probe_interval_seconds: float | None = None,
    lang: str | None = None,
) -> str | None:
    init_cache(cache_dir)
    resolved_lang = resolve_lang(lang or default_lang_from_settings())
    startup_dataset_key = _resolve_startup_dataset_key(cache_dir, dataset_key)
    if not interactive:
        return render_basic_tui(cache_dir, dataset_key=startup_dataset_key, limit=limit, lang=resolved_lang)
    plain_reason = _plain_mode_reason(resolved_lang)
    if plain_reason:
        return render_plain_fallback(cache_dir, startup_dataset_key, limit, plain_reason, lang=resolved_lang)
    if curses is None:
        return render_plain_fallback(cache_dir, startup_dataset_key, limit, tr(resolved_lang, "no_curses_reason"), lang=resolved_lang)
    try:
        curses.wrapper(
            lambda stdscr: _run_curses(
                stdscr,
                cache_dir,
                dataset_key=startup_dataset_key,
                limit=limit,
                live=live,
                probe_interval_override=probe_interval_seconds,
                lang=resolved_lang,
            )
        )
    except curses.error as exc:
        reason = tr(resolved_lang, "curses_failed_reason", error=exc)
        return render_plain_fallback(cache_dir, startup_dataset_key, limit, reason, lang=resolved_lang)
    return None


def _plain_mode_reason(lang: str | None = None) -> str:
    resolved_lang = resolve_lang(lang)
    if _truthy_env(TUI_FORCE_CURSES_ENV):
        return ""
    if _truthy_env(TUI_FORCE_PLAIN_ENV):
        return tr(resolved_lang, "force_plain_reason")
    if sys.platform == "win32" and not _windows_native_curses_allowed():
        return tr(resolved_lang, "windows_plain_reason")
    if _is_web_or_unknown_ssh_terminal():
        return tr(resolved_lang, "ssh_plain_reason")
    return ""


def _windows_native_curses_allowed() -> bool:
    return _known_stable_terminal() or _truthy_env(TUI_ALLOW_WINDOWS_CURSES_ENV)


def _is_web_or_unknown_ssh_terminal() -> bool:
    if not (os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_CLIENT")):
        return False
    if _truthy_env("TRADECAT_TERMINAL_ALLOW_SSH_CURSES"):
        return False
    if _known_stable_terminal():
        return False
    return True


def _known_stable_terminal() -> bool:
    if os.environ.get("WT_SESSION"):
        return True
    if os.environ.get("VTE_VERSION") or os.environ.get("KONSOLE_VERSION"):
        return True
    if os.environ.get("ALACRITTY_WINDOW_ID") or os.environ.get("KITTY_WINDOW_ID"):
        return True
    term_program = os.environ.get("TERM_PROGRAM", "")
    return term_program in {"iTerm.app", "Apple_Terminal", "vscode", "WezTerm", "WarpTerminal"}


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _run_curses(
    stdscr,
    cache_dir: Path,
    dataset_key: str,
    limit: int,
    *,
    live: bool,
    probe_interval_override: float | None,
    lang: str,
) -> None:
    curses.curs_set(0)
    stdscr.keypad(True)
    stdscr.timeout(CURSES_POLL_TIMEOUT_MS)
    _enable_mouse()
    state = _load_state(dataset_key, lang=lang)
    state["live"] = live
    state["last_probe_at"] = 0.0
    state["last_probe_status"] = "cache"
    state["last_probe_error"] = None
    state["last_probe_success_at"] = None
    state["last_probe_error_at"] = None
    state["consecutive_probe_failures"] = 0
    state["probe_generation"] = 0
    state["probe_inflight"] = False
    state["background_probe_jobs"] = {}
    state["background_probe_enabled"] = _background_probe_enabled()
    state["view_cache"] = {}
    state["render_cache"] = {}
    state["show_help"] = False
    state["filter_query"] = ""
    state["screen_size"] = _observed_screen_size(stdscr)
    _update_probe_tuning_state(state, probe_interval_override)
    probe_results: queue.Queue[dict[str, Any]] = queue.Queue()
    dirty = True
    try:
        while True:
            dirty = _handle_screen_resize(stdscr, state) or dirty
            dirty = _drain_probe_results(state, probe_results) or dirty
            dirty = _maybe_probe_live(cache_dir, state, probe_interval_override, probe_results) or dirty
            dirty = _maybe_probe_background(cache_dir, state, probe_results) or dirty
            if dirty:
                _draw(stdscr, cache_dir, state, limit=limit)
                dirty = False
            key = stdscr.getch()
            if key == -1:
                continue
            if key in {ord("q"), ord("Q")}:
                return
            if key == 27:
                if state.get("show_help"):
                    state["show_help"] = False
                    dirty = True
                    continue
                dirty = _handle_raw_sgr_mouse_event(stdscr, state) or dirty
                continue
            if key in {ord("?"), curses.KEY_F1}:
                state["show_help"] = not bool(state.get("show_help"))
                dirty = True
                continue
            if key == ord("/"):
                _prompt_filter(stdscr, state)
                dirty = True
                continue
            if key in {ord("x"), ord("X")}:
                state["filter_query"] = ""
                state["row_scroll"] = 0
                dirty = True
                continue
            if key == curses.KEY_RESIZE:
                dirty = _handle_screen_resize(stdscr, state) or True
                continue
            if key == curses.KEY_RIGHT:
                _switch_dataset(state, 1)
                dirty = True
            elif key == curses.KEY_LEFT:
                _switch_dataset(state, -1)
                dirty = True
            elif key in {ord("d"), ord("D"), 9}:
                _switch_dataset(state, 1)
                dirty = True
            elif key in {ord("a"), ord("A"), getattr(curses, "KEY_BTAB", 353)}:
                _switch_dataset(state, -1)
                dirty = True
            elif key in {curses.KEY_DOWN, ord("j"), ord("J")}:
                if _current_dataset_mode(state) == "stream":
                    state["row_scroll"] = int(state.get("row_scroll", 0)) + 1
                else:
                    state["batch_index"] = min(
                        int(state.get("batch_index", 0)) + 1,
                        max(0, int(state.get("batch_count", 1)) - 1),
                    )
                    state["row_scroll"] = 0
                    state["live"] = state["batch_index"] == 0
                dirty = True
            elif key in {curses.KEY_UP, ord("k"), ord("K")}:
                if _current_dataset_mode(state) == "stream":
                    state["row_scroll"] = max(0, int(state.get("row_scroll", 0)) - 1)
                else:
                    state["batch_index"] = max(0, int(state.get("batch_index", 0)) - 1)
                    state["row_scroll"] = 0
                    state["live"] = state["batch_index"] == 0
                dirty = True
            elif key in {curses.KEY_NPAGE, ord(" ")}:
                state["row_scroll"] = int(state.get("row_scroll", 0)) + max(1, int(state.get("page_limit", 1)))
                dirty = True
            elif key == curses.KEY_PPAGE:
                state["row_scroll"] = max(
                    0, int(state.get("row_scroll", 0)) - max(1, int(state.get("page_limit", 1)))
                )
                dirty = True
            elif key == ord("g"):
                state["row_scroll"] = 0
                dirty = True
            elif key == ord("G"):
                state["row_scroll"] = int(state.get("max_row_scroll", 0))
                dirty = True
            elif key in {ord("r"), ord("R")}:
                _update_probe_tuning_state(state, probe_interval_override)
                state["live"] = True
                state["batch_index"] = 0
                _start_probe_thread(cache_dir, state, probe_results)
                dirty = True
            elif key in {ord("l"), ord("L")}:
                state["lang"] = cycle_lang(str(state.get("lang") or lang))
                _invalidate_view_cache(state)
                dirty = True
            elif key in {ord("n"), ord("N")}:
                state["selected_row_offset"] = min(
                    int(state.get("selected_row_offset", 0)) + 1,
                    max(0, len(state.get("visible_rows", [])) - 1),
                )
                dirty = True
            elif key in {ord("p"), ord("P")}:
                state["selected_row_offset"] = max(0, int(state.get("selected_row_offset", 0)) - 1)
                dirty = True
            elif key in {10, 13, ord("o"), ord("O")}:
                _open_selected_symbol(state)
                dirty = True
            elif key == curses.KEY_MOUSE:
                dirty = _handle_mouse_event(state) or dirty
    finally:
        _disable_mouse()


def _draw(stdscr, cache_dir: Path, state: dict, limit: int) -> None:
    height, width = stdscr.getmaxyx()
    dataset = state["datasets"][state["dataset_index"]]
    lang = resolve_lang(str(state.get("lang") or ""))
    dataset_key = str(dataset["dataset_key"])
    data_mode = str(dataset["data_mode"])
    view = _read_view_cached(
        cache_dir,
        state,
        dataset_key,
        batch_index=int(state.get("batch_index", 0)),
        live=bool(state.get("live", True)),
    )
    state["batch_count"] = int(view.get("batch_count") or 0)
    state["batch_index"] = int(view.get("batch_index") or 0)
    top_lines = list(view.get("top_lines") or [])
    page_limit = _page_limit(height, limit, reserved_lines=len(top_lines) + 1)
    rows = list(view.get("rows") or [])
    rows = _filter_rows(rows, str(state.get("filter_query") or ""))
    max_row_scroll = max(0, len(rows) - page_limit)
    state["max_row_scroll"] = max_row_scroll
    state["row_scroll"] = min(max(0, int(state.get("row_scroll", 0))), max_row_scroll)
    visible_rows = _rows_for_display(view, start=int(state["row_scroll"]), limit=page_limit)
    state["page_limit"] = page_limit
    state["visible_rows"] = visible_rows
    state["selected_row_offset"] = min(
        max(0, int(state.get("selected_row_offset", 0))),
        max(0, len(visible_rows) - 1),
    )

    mode = tr(lang, "mode_live") if state.get("live", True) else tr(lang, "mode_history")
    display_name = _dataset_display_name(dataset, lang)
    header = (
        f"TradeCat | {mode} | tap {state['dataset_index'] + 1}/{len(state['datasets'])}: "
        f"{dataset_key} ({display_name}) | {lang_label(lang, lang=lang)}"
    )
    controls = tr(lang, "controls")
    probe_label = _probe_state_label(state)
    if data_mode == "stream":
        batch_label = tr(lang, "stream_status", row_scroll=state["row_scroll"], probe=probe_label)
    else:
        batch_label = tr(
            lang,
            "batch_status",
            batch_index=int(view.get("batch_index") or 0) + 1,
            batch_count=int(view.get("batch_count") or 0),
            batch_label=view.get("batch_label") or tr(lang, "no_cache"),
            probe=probe_label,
        )
    if state.get("filter_query"):
        batch_label += f" | filter={state['filter_query']} matched={len(rows)}"
    if state.get("last_probe_error"):
        batch_label += f" | {tr(lang, 'error_label')}={state['last_probe_error']} | {_recovery_hint(state)}"
    if state.get("last_open_status"):
        batch_label += f" | {tr(lang, 'open_label')}={state['last_open_status']}"
    status_bar = _status_bar(view, state, lang=lang, cache_dir=cache_dir)
    _add_line(stdscr, 0, header, width, curses.A_REVERSE)
    _add_line(stdscr, 1, controls, width)
    _add_line(stdscr, 2, status_bar, width)
    _add_line(stdscr, 3, batch_label, width)
    _add_line(stdscr, 4, "-" * max(0, width - 1), width)
    y = 5
    if state.get("show_help"):
        _draw_help(stdscr, y, width, height, lang=lang, cache_dir=cache_dir)
        _finish_draw(stdscr, state, height, height)
        return
    for line in top_lines:
        _add_line(stdscr, y, line, width)
        y += 1
        if y >= height:
            _finish_draw(stdscr, state, y, height)
            return
    if top_lines:
        _add_line(stdscr, y, "-" * max(0, width - 1), width)
        y += 1
    if not visible_rows:
        state["data_start_y"] = None
        _add_line(stdscr, y, tr(lang, "empty_cache_curses"), width)
        _finish_draw(stdscr, state, y + 1, height)
        return
    viewport = _render_viewport_cached(
        state,
        data_mode,
        visible_rows,
        columns=list(view.get("columns") or []),
        content_hash=str(view.get("content_hash") or ""),
        row_scroll=int(state["row_scroll"]),
    )
    state["data_start_y"] = y + 3
    state["link_spans"] = _symbol_link_spans(visible_rows, viewport["columns"], viewport["widths"])
    for line_index, line in enumerate(viewport["lines"]):
        row_offset = line_index - 3
        spans = []
        link_span = state["link_spans"].get(row_offset)
        if link_span and row_offset == state.get("hover_row_offset"):
            spans.append((int(link_span["start"]), int(link_span["end"]), curses.A_UNDERLINE))
        _add_table_line(stdscr, y, line, width, spans=spans)
        y += 1
        if y >= height:
            break
    _finish_draw(stdscr, state, y, height)


def _load_state(dataset_key: str, *, lang: str | None = None) -> dict[str, Any]:
    datasets = [dataset_to_dict(dataset) for dataset in list_active_datasets()]
    keys = [str(row["key"]) for row in datasets]
    index = keys.index(dataset_key) if dataset_key in keys else 0
    normalized = [
        {
            "dataset_key": row["key"],
            "tab_name": row["tab_name"],
            "display_names": row.get("display_names", {}),
            "data_mode": row["data_mode"],
        }
        for row in datasets
    ]
    return {
        "datasets": normalized,
        "dataset_index": index,
        "batch_index": 0,
        "batch_count": 0,
        "row_scroll": 0,
        "selected_row_offset": 0,
        "hover_row_offset": None,
        "last_open_status": None,
        "lang": resolve_lang(lang),
        "show_help": False,
        "filter_query": "",
    }


def _status_bar(view: dict[str, Any], state: dict[str, Any], *, lang: str, cache_dir: Path) -> str:
    remote_time = _remote_time_label(view)
    fetched_at = str(view.get("fetched_at") or "-")
    cache_state = "cache-hit" if view.get("rows") else "empty-cache"
    probe = str(state.get("last_probe_status") or "-")
    next_seconds = _next_probe_seconds(state)
    parts = [
        f"lang={lang_label(lang, lang=lang)}",
        f"cache={cache_state}",
        f"remote={remote_time}",
        f"fetched={fetched_at}",
        f"probe={probe}",
        f"next={next_seconds}s",
        f"path={cache_dir}",
    ]
    return " | ".join(parts)


def _remote_time_label(view: dict[str, Any]) -> str:
    meta = view.get("meta")
    if not isinstance(meta, dict):
        return "-"
    for key in ("导出时间(UTC+8)", "导出时间", "更新时间", "更新时间(北京)"):
        value = meta.get(key)
        if value:
            return str(value)
    return "-"


def _recovery_hint(state: dict[str, Any]) -> str:
    error = str(state.get("last_probe_error") or "").lower()
    if "timed out" in error or "timeout" in error or "超时" in error:
        return "建议：检查网络或调大 TRADECAT_TERMINAL_TUI_FETCH_TIMEOUT"
    if "429" in error or "quota" in error or "rate" in error or "限流" in error:
        return "建议：等待退避或调大刷新间隔"
    if "no such" in error or "json" in error or "decode" in error:
        return "建议：执行 tradecat sync-all 重建缓存"
    return "建议：按 r 重试，或执行 tradecat doctor"


def _draw_help(stdscr, start_y: int, width: int, height: int, *, lang: str, cache_dir: Path) -> None:
    lines = _help_lines(lang=lang, cache_dir=cache_dir)
    y = start_y
    for line in lines:
        if y >= height:
            break
        _add_line(stdscr, y, line, width)
        y += 1


def _help_lines(*, lang: str, cache_dir: Path) -> list[str]:
    if lang == "en":
        return [
            "Help",
            "←/→ or a/d/Tab: switch tap",
            "↑/↓: switch snapshot batch for snapshot taps; scroll event_stream rows",
            "PgUp/PgDn/Space: page rows; g/G: top/end",
            "/: search visible rows; x: clear search",
            "n/p: select row; Enter/o: open URL or Binance Futures symbol link",
            "r: refresh current tap; l: switch language; ?: close help; q: quit",
            f"cache: {cache_dir}",
            "Recovery: network errors keep the local cache visible; press r or run tradecat sync-all.",
        ]
    if lang == "ko":
        return [
            "도움말",
            "←/→ 또는 a/d/Tab: 탭 전환",
            "↑/↓: 스냅샷 탭은 배치 전환, event_stream은 행 스크롤",
            "PgUp/PgDn/Space: 페이지 이동; g/G: 처음/끝",
            "/: 검색; x: 검색 해제",
            "n/p: 행 선택; Enter/o: URL 또는 Binance Futures 거래쌍 열기",
            "r: 현재 탭 새로고침; l: 언어 전환; ?: 도움말 닫기; q: 종료",
            f"cache: {cache_dir}",
            "복구: 네트워크 오류가 나도 로컬 캐시는 유지됩니다. r 또는 tradecat sync-all을 사용하세요.",
        ]
    return [
        "帮助",
        "←/→ 或 a/d/Tab：切换 tap",
        "↑/↓：snapshot tap 切换快照批次；event_stream 滚动事件",
        "PgUp/PgDn/Space：翻行；g/G：首尾跳转",
        "/：搜索当前表；x：清除搜索",
        "n/p：选择可见行；Enter/o：打开 URL 或交易对 Binance Futures 链接",
        "r：刷新当前 tap；l：切换语言；?：关闭帮助；q：退出",
        f"cache: {cache_dir}",
        "恢复：网络失败不会清空界面；按 r 重试，或执行 tradecat sync-all。",
    ]


def _prompt_filter(stdscr, state: dict[str, Any]) -> None:
    height, width = stdscr.getmaxyx()
    prompt = "filter> "
    value = str(state.get("filter_query") or "")
    try:
        curses.curs_set(1)
    except curses.error:
        pass
    while True:
        _safe_addstr(stdscr, max(0, height - 1), prompt + value, width, curses.A_REVERSE)
        key = stdscr.getch()
        if key in {10, 13}:
            state["filter_query"] = value.strip()
            state["row_scroll"] = 0
            break
        if key in {27}:
            break
        if key in {curses.KEY_BACKSPACE, 127, 8}:
            value = value[:-1]
            continue
        if 32 <= key <= 0x10FFFF:
            try:
                value += chr(key)
            except ValueError:
                continue
    try:
        curses.curs_set(0)
    except curses.error:
        pass


def _filter_rows(rows: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    needle = query.strip().lower()
    if not needle:
        return rows
    result: list[dict[str, Any]] = []
    for row in rows:
        haystack = " ".join(
            [
                *[str(value) for value in _row_values(row).values()],
                *[str(value) for value in _raw_row_values(row).values()],
            ]
        ).lower()
        if needle in haystack:
            result.append(row)
    return result


def _switch_dataset(state: dict[str, Any], step: int) -> None:
    state["dataset_index"] = (int(state["dataset_index"]) + step) % max(1, len(state["datasets"]))
    state["batch_index"] = 0
    state["batch_count"] = 0
    state["row_scroll"] = 0
    state["hover_row_offset"] = None
    state["selected_row_offset"] = 0
    state["live"] = True
    state["last_probe_at"] = 0.0
    state["last_probe_status"] = "cache"
    state["last_probe_error"] = None
    state["last_probe_error_at"] = None
    state["consecutive_probe_failures"] = 0
    state["probe_generation"] = int(state.get("probe_generation", 0)) + 1
    state["probe_inflight"] = False
    _invalidate_view_cache(state)


def _maybe_probe_live(
    cache_dir: Path,
    state: dict,
    probe_interval_override: float | None,
    probe_results: queue.Queue[dict[str, Any]],
) -> bool:
    if not state.get("live", True):
        return False
    _update_probe_tuning_state(state, probe_interval_override)
    if state.get("probe_inflight"):
        return False
    effective_interval = float(state.get("effective_probe_interval_seconds") or DEFAULT_LIVE_PROBE_INTERVAL_SECONDS)
    now = time.monotonic()
    if now - float(state.get("last_probe_at", 0.0)) < effective_interval:
        return False
    return _start_probe_thread(cache_dir, state, probe_results)


def _start_probe_thread(
    cache_dir: Path,
    state: dict[str, Any],
    probe_results: queue.Queue[dict[str, Any]],
) -> bool:
    if state.get("probe_inflight"):
        return False
    dataset_key = _current_dataset_key(state)
    generation = int(state.get("probe_generation", 0))
    fetch_timeout = float(state.get("current_fetch_timeout_seconds") or DEFAULT_LIVE_FETCH_TIMEOUT_SECONDS)
    state["probe_inflight"] = True
    state["last_probe_status"] = "probing"
    state["last_probe_error"] = None
    state["last_probe_at"] = time.monotonic()

    def worker() -> None:
        result = _probe_latest(cache_dir, dataset_key=dataset_key, fetch_timeout=fetch_timeout)
        probe_results.put({"dataset_key": dataset_key, "generation": generation, "result": result})

    thread = threading.Thread(target=worker, name=f"tradecat-probe-{dataset_key}", daemon=True)
    thread.start()
    return True


def _maybe_probe_background(
    cache_dir: Path,
    state: dict[str, Any],
    probe_results: queue.Queue[dict[str, Any]],
) -> bool:
    if not state.get("background_probe_enabled", True):
        return False
    current_key = _current_dataset_key(state)
    dirty = False
    for dataset in state.get("datasets", []):
        dataset_key = str(dataset.get("dataset_key") or "")
        if not dataset_key or (dataset_key == current_key and state.get("live", True)):
            continue
        dirty = _maybe_start_background_probe(cache_dir, state, probe_results, dataset_key) or dirty
    return dirty


def _maybe_start_background_probe(
    cache_dir: Path,
    state: dict[str, Any],
    probe_results: queue.Queue[dict[str, Any]],
    dataset_key: str,
) -> bool:
    jobs = state.setdefault("background_probe_jobs", {})
    job = jobs.setdefault(
        dataset_key,
        {
            "inflight": False,
            "last_probe_at": 0.0,
            "generation": 0,
            "consecutive_failures": 0,
        },
    )
    if job.get("inflight"):
        return False
    interval = _background_probe_interval(dataset_key, int(job.get("consecutive_failures") or 0))
    now = time.monotonic()
    last_probe_at = float(job.get("last_probe_at", 0.0))
    if last_probe_at > 0 and now - last_probe_at < interval:
        return False
    generation = int(job.get("generation") or 0) + 1
    job["generation"] = generation
    job["inflight"] = True
    job["last_probe_at"] = now
    fetch_timeout = _resolve_fetch_timeout(None, dataset_key, interval)

    def worker() -> None:
        result = _probe_latest(cache_dir, dataset_key=dataset_key, fetch_timeout=fetch_timeout)
        probe_results.put(
            {
                "dataset_key": dataset_key,
                "generation": generation,
                "scope": "background",
                "result": result,
            }
        )

    thread = threading.Thread(target=worker, name=f"tradecat-bg-probe-{dataset_key}", daemon=True)
    thread.start()
    return True


def _drain_probe_results(state: dict[str, Any], probe_results: queue.Queue[dict[str, Any]]) -> bool:
    dirty = False
    while True:
        try:
            item = probe_results.get_nowait()
        except queue.Empty:
            return dirty
        if item.get("scope") == "background":
            dirty = _drain_background_probe_result(state, item) or dirty
            continue
        if int(item.get("generation", -1)) != int(state.get("probe_generation", 0)):
            continue
        if str(item.get("dataset_key")) != _current_dataset_key(state):
            continue
        state["probe_inflight"] = False
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        _record_probe_result(state, result)
        state["batch_index"] = 0
        if result.get("changed") or result.get("wrote") or _cached_view_hash_mismatch(
            state,
            str(item.get("dataset_key")),
            str(result.get("content_hash") or ""),
        ):
            _invalidate_view_cache(state, str(item.get("dataset_key")))
        dirty = True


def _drain_background_probe_result(state: dict[str, Any], item: dict[str, Any]) -> bool:
    dataset_key = str(item.get("dataset_key") or "")
    jobs = state.setdefault("background_probe_jobs", {})
    job = jobs.setdefault(dataset_key, {"inflight": False, "generation": 0, "consecutive_failures": 0})
    if int(item.get("generation", -1)) != int(job.get("generation", 0)):
        return False
    job["inflight"] = False
    result = item.get("result") if isinstance(item.get("result"), dict) else {}
    if result.get("ok"):
        job["consecutive_failures"] = 0
        job["last_success_at"] = _clock_label()
    else:
        job["consecutive_failures"] = int(job.get("consecutive_failures") or 0) + 1
        job["last_error_at"] = _clock_label()
        job["last_error"] = _short_probe_error(_probe_error_label(result))
    changed = bool(
        result.get("changed")
        or result.get("wrote")
        or _cached_view_hash_mismatch(state, dataset_key, str(result.get("content_hash") or ""))
    )
    if changed:
        _invalidate_view_cache(state, dataset_key)
    if dataset_key != _current_dataset_key(state):
        return False
    if state.get("live", True):
        _record_probe_result(state, result)
        state["batch_index"] = 0
        return True
    return changed


def _probe_latest(cache_dir: Path, *, dataset_key: str | None, fetch_timeout: float | None = None) -> dict[str, Any]:
    if not dataset_key:
        return {"ok": False, "status": "error", "changed": False, "wrote": False, "error": "missing dataset_key"}
    try:
        return probe_dataset(
            cache_dir,
            dataset_key,
            write=True,
            fetch_timeout=fetch_timeout,
        )
    except KeyboardInterrupt:
        return {"ok": False, "status": "interrupted", "changed": False, "wrote": False, "error": "探针被用户中断"}
    except Exception as exc:
        return {"ok": False, "status": "error", "changed": False, "wrote": False, "error": str(exc)}


def _probe_status_label(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return "error"
    if result.get("wrote"):
        return "written"
    if result.get("changed"):
        return "changed"
    return str(result.get("status") or "unchanged")


def _probe_error_label(result: dict[str, Any]) -> str | None:
    return str(result["error"]) if result.get("error") else None


def _record_probe_result(state: dict[str, Any], result: dict[str, Any]) -> None:
    state["last_probe_status"] = _probe_status_label(result)
    state["last_probe_error"] = _short_probe_error(_probe_error_label(result))
    if result.get("ok"):
        state["last_probe_success_at"] = _clock_label()
        state["consecutive_probe_failures"] = 0
    elif result.get("error"):
        state["last_probe_error_at"] = _clock_label()
        state["consecutive_probe_failures"] = int(state.get("consecutive_probe_failures") or 0) + 1


def _probe_state_label(state: dict[str, Any]) -> str:
    label = str(state.get("last_probe_status") or "-")
    success = state.get("last_probe_success_at") or "-"
    error_at = state.get("last_probe_error_at") or "-"
    base_interval = float(state.get("base_probe_interval_seconds") or DEFAULT_LIVE_PROBE_INTERVAL_SECONDS)
    effective_interval = float(state.get("effective_probe_interval_seconds") or base_interval)
    timeout = float(state.get("current_fetch_timeout_seconds") or DEFAULT_LIVE_FETCH_TIMEOUT_SECONDS)
    failures = int(state.get("consecutive_probe_failures") or 0)
    next_seconds = _next_probe_seconds(state)
    interval_label = _format_seconds(effective_interval)
    if effective_interval != base_interval:
        interval_label = f"{interval_label}(base={_format_seconds(base_interval)})"
    return (
        f"{label} interval={interval_label} timeout={_format_seconds(timeout)} "
        f"fail={failures} ok={success} err_at={error_at} next={next_seconds}s"
    )


def _next_probe_seconds(state: dict[str, Any]) -> int:
    interval = float(state.get("effective_probe_interval_seconds") or 0.0)
    if not state.get("live", True) or interval <= 0:
        return 0
    elapsed = time.monotonic() - float(state.get("last_probe_at", 0.0))
    return max(0, int(round(interval - elapsed)))


def _clock_label() -> str:
    return time.strftime("%H:%M:%S")


def _resolve_startup_dataset_key(cache_dir: Path, dataset_key: str | None) -> str:
    del cache_dir
    if dataset_key:
        return dataset_key
    preferred = (
        os.environ.get(TUI_DEFAULT_DATASET_ENV)
        or default_dataset_from_settings()
        or DEFAULT_TUI_DATASET_KEY
    ).strip() or DEFAULT_TUI_DATASET_KEY
    keys = [dataset.key for dataset in list_active_datasets()]
    return preferred if preferred in keys else keys[0]


def _resolve_probe_interval(value: float | None, dataset_key: str | None = None) -> float:
    if value is not None:
        return max(1.0, float(value))
    dataset_env_value = _dataset_probe_interval_env_value(dataset_key)
    raw = dataset_env_value or os.environ.get(TUI_PROBE_INTERVAL_ENV)
    if raw is None or not str(raw).strip():
        settings_interval = tui_probe_interval_from_settings(dataset_key)
        if settings_interval is not None:
            return max(1.0, float(settings_interval))
        dataset_interval = _dataset_probe_interval(dataset_key)
        if dataset_interval is not None:
            return max(1.0, float(dataset_interval))
        return DEFAULT_LIVE_PROBE_INTERVAL_SECONDS
    try:
        return max(1.0, float(raw))
    except ValueError:
        settings_interval = tui_probe_interval_from_settings(dataset_key)
        if settings_interval is not None:
            return max(1.0, float(settings_interval))
        dataset_interval = _dataset_probe_interval(dataset_key)
        return max(1.0, float(dataset_interval)) if dataset_interval is not None else DEFAULT_LIVE_PROBE_INTERVAL_SECONDS


def _dataset_probe_interval_env_value(dataset_key: str | None) -> str | None:
    if not dataset_key:
        return None
    key = f"TRADECAT_TERMINAL_{dataset_key.upper()}_TUI_PROBE_INTERVAL"
    return os.environ.get(key)


def _dataset_probe_interval(dataset_key: str | None) -> float | None:
    if not dataset_key:
        return None
    try:
        value = get_dataset(dataset_key).tui_probe_interval_seconds
    except ValueError:
        return None
    return float(value) if value is not None else None


def _resolve_fetch_timeout(
    value: float | None,
    dataset_key: str | None = None,
    probe_interval_seconds: float | None = None,
) -> float:
    if value is not None:
        return _cap_fetch_timeout(max(0.5, float(value)), probe_interval_seconds)
    dataset_env_value = _dataset_fetch_timeout_env_value(dataset_key)
    raw = dataset_env_value or os.environ.get(TUI_FETCH_TIMEOUT_ENV)
    if raw is None or not str(raw).strip():
        settings_timeout = tui_fetch_timeout_from_settings(dataset_key)
        if settings_timeout is not None:
            return _cap_fetch_timeout(max(0.5, float(settings_timeout)), probe_interval_seconds)
        dataset_timeout = _dataset_fetch_timeout(dataset_key)
        timeout = dataset_timeout if dataset_timeout is not None else DEFAULT_LIVE_FETCH_TIMEOUT_SECONDS
        return _cap_fetch_timeout(max(0.5, float(timeout)), probe_interval_seconds)
    try:
        return _cap_fetch_timeout(max(0.5, float(raw)), probe_interval_seconds)
    except ValueError:
        settings_timeout = tui_fetch_timeout_from_settings(dataset_key)
        if settings_timeout is not None:
            return _cap_fetch_timeout(max(0.5, float(settings_timeout)), probe_interval_seconds)
        dataset_timeout = _dataset_fetch_timeout(dataset_key)
        timeout = dataset_timeout if dataset_timeout is not None else DEFAULT_LIVE_FETCH_TIMEOUT_SECONDS
        return _cap_fetch_timeout(max(0.5, float(timeout)), probe_interval_seconds)


def _dataset_fetch_timeout_env_value(dataset_key: str | None) -> str | None:
    if not dataset_key:
        return None
    key = f"TRADECAT_TERMINAL_{dataset_key.upper()}_TUI_FETCH_TIMEOUT"
    return os.environ.get(key)


def _dataset_fetch_timeout(dataset_key: str | None) -> float | None:
    if not dataset_key:
        return None
    try:
        value = get_dataset(dataset_key).tui_fetch_timeout_seconds
    except ValueError:
        return None
    return float(value) if value is not None else None


def _cap_fetch_timeout(timeout: float, probe_interval_seconds: float | None) -> float:
    if probe_interval_seconds is None or probe_interval_seconds <= 0:
        return timeout
    return min(timeout, max(0.5, float(probe_interval_seconds)))


def _update_probe_tuning_state(state: dict[str, Any], probe_interval_override: float | None) -> None:
    dataset_key = _current_dataset_key(state)
    base_interval = _resolve_probe_interval(probe_interval_override, dataset_key)
    failures = int(state.get("consecutive_probe_failures") or 0)
    effective_interval = _effective_probe_interval(base_interval, failures)
    fetch_timeout = _resolve_fetch_timeout(None, dataset_key, base_interval)
    state["base_probe_interval_seconds"] = base_interval
    state["effective_probe_interval_seconds"] = effective_interval
    state["current_fetch_timeout_seconds"] = fetch_timeout


def _effective_probe_interval(base_interval: float, consecutive_failures: int) -> float:
    if consecutive_failures <= 0:
        return max(1.0, float(base_interval))
    if consecutive_failures == 1:
        return max(float(base_interval), 3.0)
    if consecutive_failures == 2:
        return max(float(base_interval), 5.0)
    return max(float(base_interval), 15.0)


def _background_probe_enabled() -> bool:
    raw = os.environ.get(TUI_BACKGROUND_PROBE_ENV)
    if raw is None or not raw.strip():
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _background_probe_interval(dataset_key: str, consecutive_failures: int = 0) -> float:
    raw = _dataset_background_probe_interval_env_value(dataset_key) or os.environ.get(TUI_BACKGROUND_PROBE_INTERVAL_ENV)
    if raw and raw.strip():
        try:
            base = max(1.0, float(raw))
        except ValueError:
            base = _default_background_probe_interval(dataset_key)
    else:
        base = _default_background_probe_interval(dataset_key)
    return _effective_probe_interval(base, consecutive_failures)


def _dataset_background_probe_interval_env_value(dataset_key: str | None) -> str | None:
    if not dataset_key:
        return None
    key = f"TRADECAT_TERMINAL_{dataset_key.upper()}_TUI_BACKGROUND_PROBE_INTERVAL"
    return os.environ.get(key)


def _default_background_probe_interval(dataset_key: str) -> float:
    if dataset_key == "event_stream":
        return DEFAULT_BACKGROUND_STREAM_PROBE_INTERVAL_SECONDS
    return DEFAULT_BACKGROUND_PROBE_INTERVAL_SECONDS


def _format_seconds(value: float) -> str:
    text = f"{float(value):.1f}".rstrip("0").rstrip(".")
    return f"{text}s"


def _short_probe_error(value: str | None, *, limit: int = 80) -> str | None:
    if not value:
        return None
    text = " ".join(str(value).split())
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def _current_dataset_key(state: dict) -> str:
    datasets = state["datasets"]
    return str(datasets[state["dataset_index"]]["dataset_key"])


def _current_dataset_mode(state: dict) -> str:
    datasets = state["datasets"]
    return str(datasets[state["dataset_index"]].get("data_mode") or "snapshot")


def _dataset_display_name(dataset: dict[str, Any], lang: str | None = None) -> str:
    names = dataset.get("display_names")
    resolved_lang = resolve_lang(lang)
    if isinstance(names, dict):
        return str(names.get(resolved_lang) or names.get("zh") or dataset.get("tab_name") or dataset.get("dataset_key") or "")
    return str(dataset.get("tab_name") or dataset.get("dataset_key") or "")


def _display_name_for_key(dataset_key: str, lang: str | None = None) -> str:
    try:
        return get_dataset(dataset_key).display_name(lang)
    except ValueError:
        return dataset_key


def _render_rows_table_viewport(
    rows: list[dict[str, Any]],
    *,
    columns: list[str] | None = None,
) -> dict[str, Any]:
    selected_columns = ["#", *list(columns or _select_columns(rows))]
    selected_widths = _psql_widths_for_columns(rows, selected_columns)
    table_rows = [
        [
            row.get("row_index", ""),
            *[_format_cell(_row_values(row).get(column, "")) for column in selected_columns[1:]],
        ]
        for row in rows
    ]
    return {
        "lines": _render_psql_table(selected_columns, table_rows, widths=selected_widths).splitlines(),
        "columns": selected_columns[1:],
        "widths": selected_widths,
    }


def _render_event_stream_viewport(rows: list[dict[str, Any]], *, columns: list[str] | None = None) -> dict[str, Any]:
    selected_columns = list(columns or _select_columns(rows))
    if len(selected_columns) > 2:
        selected_columns = selected_columns[:2]
    return _render_rows_table_viewport(rows, columns=selected_columns)


def _render_viewport_cached(
    state: dict[str, Any],
    data_mode: str,
    rows: list[dict[str, Any]],
    *,
    columns: list[str],
    content_hash: str,
    row_scroll: int,
) -> dict[str, Any]:
    row_ids = tuple(int(row.get("row_index", 0)) for row in rows)
    key = (data_mode, content_hash, row_scroll, row_ids, tuple(columns))
    cache = state.setdefault("render_cache", {})
    cached = cache.get(key)
    if cached:
        return cached
    if data_mode == "stream":
        viewport = _render_event_stream_viewport(rows, columns=columns)
    else:
        viewport = _render_rows_table_viewport(rows, columns=columns)
    if len(cache) > 32:
        cache.clear()
    cache[key] = viewport
    return viewport


def _read_view_cached(
    cache_dir: Path,
    state: dict[str, Any],
    dataset_key: str,
    *,
    batch_index: int,
    live: bool,
) -> dict[str, Any]:
    lang = resolve_lang(str(state.get("lang") or ""))
    key = (dataset_key, int(batch_index), bool(live), lang)
    cache = state.setdefault("view_cache", {})
    cached = cache.get(key)
    if cached:
        return cached
    view = build_dataset_view(
        cache_dir,
        dataset_key,
        batch_index=batch_index,
        live=live,
        lang=lang,
    )
    if len(cache) > 16:
        cache.clear()
    cache[key] = view
    return view


def _invalidate_view_cache(state: dict[str, Any], dataset_key: str | None = None) -> None:
    if dataset_key is None:
        state["view_cache"] = {}
        state["render_cache"] = {}
        return
    view_cache = state.setdefault("view_cache", {})
    for key in list(view_cache):
        if key and key[0] == dataset_key:
            view_cache.pop(key, None)
    state["render_cache"] = {}


def _cached_view_hash_mismatch(state: dict[str, Any], dataset_key: str, content_hash: str) -> bool:
    if not content_hash:
        return False
    view_cache = state.setdefault("view_cache", {})
    for key, view in view_cache.items():
        if key and key[0] == dataset_key and isinstance(view, dict):
            cached_hash = str(view.get("content_hash") or "")
            if cached_hash and cached_hash != content_hash:
                return True
    return False


def _rows_for_display(view: dict[str, Any], *, start: int = 0, limit: int = 0) -> list[dict[str, Any]]:
    rows = list(view.get("rows") or [])
    safe_start = max(0, int(start))
    if limit <= 0:
        return rows[safe_start:]
    return rows[safe_start : safe_start + max(1, int(limit))]


def _psql_widths_for_columns(rows: list[dict[str, Any]], columns: list[str]) -> list[int]:
    widths: list[int] = []
    for column in columns:
        if column == "#":
            values = [_format_cell(row.get("row_index", "")) for row in rows]
            widths.append(max([1, _display_width("#"), *[_display_width(value) for value in values]]))
        else:
            widths.append(_psql_width_for_column(rows, column))
    return widths


def _psql_width_for_column(rows: list[dict[str, Any]], column: str) -> int:
    values = [_format_cell(_row_values(row).get(column, "")) for row in rows]
    return max([1, _display_width(column), *[_display_width(value) for value in values]])


def _psql_table_width(widths: list[int]) -> int:
    return 1 + sum(width + 3 for width in widths)


def _render_psql_table(headers: list[Any], rows: list[list[Any]], *, widths: list[int] | None = None) -> str:
    normalized_headers = [_format_cell(header) for header in headers]
    normalized_rows = [[_format_cell(cell) for cell in row] for row in rows]
    final_widths = widths or _psql_widths(normalized_headers, normalized_rows)
    separator = _psql_separator(final_widths)
    output = [separator, _psql_row(normalized_headers, final_widths), separator]
    output.extend(_psql_row(row, final_widths) for row in normalized_rows)
    output.append(separator)
    return "\n".join(output)


def _psql_widths(headers: list[Any], rows: list[list[Any]]) -> list[int]:
    normalized_headers = [_format_cell(header) for header in headers]
    normalized_rows = [[_format_cell(cell) for cell in row] for row in rows]
    widths = []
    for index, header in enumerate(normalized_headers):
        values = [row[index] if index < len(row) else "" for row in normalized_rows]
        widths.append(max([_display_width(header), *[_display_width(value) for value in values], 1]))
    return widths


def _psql_separator(widths: list[int]) -> str:
    return "+" + "+".join("-" * (width + 2) for width in widths) + "+"


def _psql_row(values: list[str], widths: list[int]) -> str:
    cells = []
    for index, width in enumerate(widths):
        value = values[index] if index < len(values) else ""
        cells.append(" " + _pad_display(value, width) + " ")
    return "|" + "|".join(cells) + "|"


def _pad_display(text: str, width: int) -> str:
    return text + (" " * max(0, width - _display_width(text)))


def _ellipsize_display(text: str, width: int) -> str:
    if _display_width(text) <= width:
        return text
    if width <= 3:
        return _display_slice(text, 0, width)
    return _display_slice(text, 0, width - 3).rstrip() + "..."


def _row_values(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("values")
    return payload if isinstance(payload, dict) else {}


def _raw_row_values(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("raw_values")
    if isinstance(payload, dict):
        return payload
    return _row_values(row)


def _display_column_for_row(row: dict[str, Any], raw_column: Any) -> str:
    mapping = row.get("display_column_by_raw")
    if isinstance(mapping, dict):
        return str(mapping.get(str(raw_column)) or raw_column)
    return str(raw_column)


def _select_columns(rows: list[dict[str, Any]]) -> list[str]:
    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for column in _row_values(row):
            if column not in seen:
                seen.add(column)
                columns.append(str(column))
    return columns


def _format_cell(value: Any) -> str:
    return "" if value is None else str(value).replace("\n", " ")


def _page_limit(height: int, limit: int, *, reserved_lines: int = 0) -> int:
    visible_rows = max(1, height - 7 - max(0, reserved_lines))
    return visible_rows if limit <= 0 else max(1, min(limit, visible_rows))


def _add_line(stdscr, y: int, text: str, width: int, attr: int = 0) -> None:
    if y >= stdscr.getmaxyx()[0]:
        return
    rendered = _display_ellipsize(text.replace("\n", " "), _safe_screen_width(width))
    _safe_addstr(stdscr, y, rendered, width, attr)


def _add_table_line(
    stdscr,
    y: int,
    text: str,
    width: int,
    *,
    attr: int = 0,
    spans: list[tuple[int, int, int]] | None = None,
) -> None:
    if y >= stdscr.getmaxyx()[0]:
        return
    rendered = _display_slice(text.replace("\n", " "), 0, _safe_screen_width(width))
    _safe_addstr(stdscr, y, rendered, width, attr)
    if spans:
        _overlay_spans(stdscr, y, rendered, spans=spans)


def _overlay_spans(stdscr, y: int, text: str, *, spans: list[tuple[int, int, int]]) -> None:
    for start, end, attr in spans:
        if start >= _display_width(text):
            continue
        rendered = _display_slice(text, start, max(0, end - start))
        if not rendered:
            continue
        try:
            stdscr.addstr(y, start, rendered, attr)
        except curses.error:
            continue


def _safe_screen_width(width: int) -> int:
    return max(1, width - 2)


def _safe_addstr(stdscr, y: int, text: str, width: int, attr: int = 0) -> None:
    rendered = _display_slice(text, 0, _safe_screen_width(width))
    try:
        stdscr.move(y, 0)
        stdscr.clrtoeol()
    except curses.error:
        return
    while rendered:
        try:
            stdscr.addstr(y, 0, rendered, attr)
            return
        except curses.error:
            rendered = rendered[:-1]


def _finish_draw(stdscr, state: dict[str, Any], y: int, height: int) -> None:
    previous_height = int(state.get("last_frame_height") or 0)
    clear_until = min(height, max(previous_height, y))
    for line in range(max(0, y), clear_until):
        try:
            stdscr.move(line, 0)
            stdscr.clrtoeol()
        except curses.error:
            continue
    state["last_frame_height"] = height
    try:
        stdscr.noutrefresh()
        curses.doupdate()
    except curses.error:
        try:
            stdscr.refresh()
        except curses.error:
            return


def _handle_screen_resize(stdscr, state: dict[str, Any]) -> bool:
    current_size = _observed_screen_size(stdscr)
    if current_size == state.get("screen_size"):
        return False
    _apply_screen_resize(stdscr, current_size)
    state["screen_size"] = current_size
    state["last_frame_height"] = 0
    state["render_cache"] = {}
    try:
        stdscr.erase()
    except curses.error:
        return True
    return True


def _observed_screen_size(stdscr) -> tuple[int, int]:
    terminal_size = _terminal_size()
    if terminal_size is not None:
        return terminal_size
    return tuple(int(value) for value in stdscr.getmaxyx())


def _terminal_size() -> tuple[int, int] | None:
    streams = [getattr(sys, "__stdout__", None), sys.stdout]
    for stream in streams:
        if stream is None:
            continue
        try:
            fileno = stream.fileno()
        except (AttributeError, OSError):
            continue
        try:
            size = os.get_terminal_size(fileno)
        except OSError:
            continue
        return (int(size.lines), int(size.columns))
    return None


def _apply_screen_resize(stdscr, size: tuple[int, int]) -> None:
    try:
        curses.update_lines_cols()
    except curses.error:
        pass
    rows, cols = size
    if rows <= 0 or cols <= 0:
        return
    try:
        curses.resize_term(rows, cols)
    except curses.error:
        return
    try:
        stdscr.resize(rows, cols)
    except curses.error:
        return


def _display_ellipsize(text: str, max_width: int) -> str:
    return _ellipsize_display(text, max_width)


def _display_slice(text: str, start: int, width: int) -> str:
    if width <= 0:
        return ""
    end = start + width
    pos = 0
    output: list[str] = []
    used = 0
    for char in text:
        char_width = _char_width(char)
        next_pos = pos + char_width
        if next_pos <= start:
            pos = next_pos
            continue
        if pos >= end:
            break
        if pos < start:
            pos = next_pos
            continue
        if used + char_width > width:
            break
        output.append(char)
        used += char_width
        pos = next_pos
    return "".join(output)


def _display_width(text: str) -> int:
    return sum(_char_width(char) for char in text)


def _char_width(char: str) -> int:
    if not char or unicodedata.combining(char):
        return 0
    if unicodedata.category(char) in {"Cc", "Cf"}:
        return 0
    return 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1


def _enable_mouse() -> None:
    if curses is None:
        return
    try:
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        curses.mouseinterval(0)
    except curses.error:
        return
    _write_terminal_control("\033[?1006h\033[?1003h")


def _disable_mouse() -> None:
    _write_terminal_control("\033[?1003l\033[?1006l")


def _write_terminal_control(sequence: str) -> None:
    try:
        sys.stdout.write(sequence)
        sys.stdout.flush()
    except OSError:
        return


def _handle_mouse_event(state: dict) -> bool:
    event = _read_mouse_event()
    if event is None:
        return False
    _id, x, y, _z, button_state = event
    return _handle_curses_mouse_payload(state, int(x), int(y), int(button_state))


def _handle_curses_mouse_payload(state: dict, x: int, y: int, button_state: int) -> bool:
    direction = _mouse_wheel_direction(button_state)
    if direction < 0:
        state["row_scroll"] = max(0, int(state.get("row_scroll", 0)) - MOUSE_WHEEL_STEP)
        state["hover_row_offset"] = None
        return True
    if direction > 0:
        state["row_scroll"] = int(state.get("row_scroll", 0)) + MOUSE_WHEEL_STEP
        state["hover_row_offset"] = None
        return True
    previous_hover = state.get("hover_row_offset")
    hover_row = _hovered_link_row_offset(state, int(x), int(y))
    state["hover_row_offset"] = hover_row
    changed = previous_hover != hover_row
    if not _is_left_click(button_state):
        return changed
    if hover_row is None:
        return changed
    state["selected_row_offset"] = hover_row
    _open_selected_symbol(state)
    return True


def _handle_raw_sgr_mouse_event(stdscr, state: dict) -> bool:
    event = _read_raw_sgr_mouse_event(stdscr)
    if event is None:
        return False
    button_code, x, y, final = event
    return _handle_sgr_mouse_payload(state, button_code, x, y, final)


def _read_raw_sgr_mouse_event(stdscr) -> tuple[int, int, int, str] | None:
    chars: list[int] = []
    try:
        stdscr.timeout(0)
        for _ in range(32):
            char = stdscr.getch()
            if char == -1:
                break
            chars.append(char)
            if char in {ord("M"), ord("m")}:
                break
    finally:
        stdscr.timeout(CURSES_POLL_TIMEOUT_MS)
    if not chars:
        return None
    text = "".join(chr(char) for char in chars if 0 <= char <= 255)
    match = re.fullmatch(r"\[<(\d+);(\d+);(\d+)([Mm])", text)
    if not match:
        return None
    return int(match.group(1)), max(0, int(match.group(2)) - 1), max(0, int(match.group(3)) - 1), match.group(4)


def _handle_sgr_mouse_payload(state: dict, button_code: int, x: int, y: int, final: str) -> bool:
    if button_code == 64:
        state["row_scroll"] = max(0, int(state.get("row_scroll", 0)) - MOUSE_WHEEL_STEP)
        state["hover_row_offset"] = None
        return True
    if button_code == 65:
        state["row_scroll"] = int(state.get("row_scroll", 0)) + MOUSE_WHEEL_STEP
        state["hover_row_offset"] = None
        return True
    previous_hover = state.get("hover_row_offset")
    hover_row = _hovered_link_row_offset(state, x, y)
    state["hover_row_offset"] = hover_row
    changed = previous_hover != hover_row
    if not _is_sgr_left_click(button_code, final):
        return changed
    if hover_row is None:
        return changed
    state["selected_row_offset"] = hover_row
    _open_selected_symbol(state)
    return True


def _is_sgr_left_click(button_code: int, final: str) -> bool:
    return final == "M" and button_code & 3 == 0 and button_code not in {32, 35, 64, 65}


def _is_left_click(button_state: int) -> bool:
    if curses is None:
        return False
    masks = [
        getattr(curses, "BUTTON1_CLICKED", 0),
        getattr(curses, "BUTTON1_PRESSED", 0),
        getattr(curses, "BUTTON1_RELEASED", 0),
    ]
    return any(mask and button_state & mask for mask in masks)


def _read_mouse_event() -> tuple[int, int, int, int, int] | None:
    try:
        return curses.getmouse()
    except curses.error:
        return None


def _mouse_wheel_direction(button_state: int) -> int:
    if curses is None:
        return 0
    wheel_up = getattr(curses, "BUTTON4_PRESSED", 0)
    wheel_down = getattr(curses, "BUTTON5_PRESSED", 0)
    if wheel_up and button_state & wheel_up:
        return -1
    if wheel_down and button_state & wheel_down:
        return 1
    return 0


def _hovered_link_row_offset(state: dict, x: int, y: int) -> int | None:
    data_start_y = state.get("data_start_y")
    if data_start_y is None:
        return None
    row_offset = y - int(data_start_y)
    span = (state.get("link_spans") or {}).get(row_offset)
    if not span:
        return None
    if int(span["start"]) <= x < int(span["end"]):
        return row_offset
    return None


def _symbol_link_spans(rows: list[dict[str, Any]], columns: list[str], widths: list[int]) -> dict[int, dict[str, Any]]:
    spans: dict[int, dict[str, Any]] = {}
    for row_pos, _row in enumerate(rows):
        link = _link_for_visible_row(rows, row_pos)
        if not link or link["column"] not in columns:
            continue
        table_column_index = 1 + columns.index(str(link["column"]))
        if table_column_index >= len(widths):
            continue
        start = _psql_cell_content_start(widths, table_column_index)
        display_offset = int(link.get("display_offset", 0))
        value_width = min(
            _display_width(_format_cell(link.get("value", ""))),
            max(0, widths[table_column_index] - display_offset),
        )
        if value_width <= 0:
            continue
        spans[row_pos] = {
            "start": start + display_offset,
            "end": start + display_offset + value_width,
            "url": link["url"],
            "column": link["column"],
        }
    return spans


def _psql_cell_content_start(widths: list[int], column_index: int) -> int:
    return 2 + sum(width + 3 for width in widths[:column_index])


def _normalize_contract_symbol(value: Any) -> str | None:
    text = _format_cell(value).strip().upper()
    if not text or text in {name.upper() for name in SYMBOL_HEADER_NAMES}:
        return None
    if text.startswith(("HTTP://", "HTTPS://")):
        return None
    normalized = text.replace("/", "").replace("-", "").replace("_", "").replace(" ", "")
    if normalized.isdigit() or not SYMBOL_VALUE_RE.fullmatch(normalized):
        return None
    return normalized if normalized.endswith("USDT") else f"{normalized}USDT"


def _build_binance_futures_url(value: Any) -> str | None:
    symbol = _normalize_contract_symbol(value)
    if not symbol:
        return None
    return BINANCE_FUTURES_URL_TEMPLATE.format(symbol=symbol)


def _symbol_url_for_visible_row(rows: list[dict[str, Any]], row_pos: int) -> str | None:
    link = _link_for_visible_row(rows, row_pos)
    return str(link["url"]) if link else None


def _link_for_visible_row(rows: list[dict[str, Any]], row_pos: int) -> dict[str, Any] | None:
    url_link = _url_link_for_visible_row(rows, row_pos)
    return url_link or _symbol_link_for_visible_row(rows, row_pos)


def _url_link_for_visible_row(rows: list[dict[str, Any]], row_pos: int) -> dict[str, Any] | None:
    if row_pos < 0 or row_pos >= len(rows):
        return None
    row = rows[row_pos]
    for key, value in _raw_row_values(row).items():
        match = URL_RE.search(_format_cell(value))
        if match:
            url = match.group(0).rstrip("，。；;、)")
            return {
                "column": _display_column_for_row(row, key),
                "value": url,
                "url": url,
                "display_offset": _display_width(_format_cell(value)[: match.start()]),
            }
    return None


def _symbol_link_for_visible_row(rows: list[dict[str, Any]], row_pos: int) -> dict[str, str] | None:
    if row_pos < 0 or row_pos >= len(rows):
        return None
    row = rows[row_pos]
    values = _raw_row_values(row)
    for key, value in values.items():
        if str(key) in SYMBOL_HEADER_NAMES:
            url = _build_binance_futures_url(value)
            if url:
                return {"column": _display_column_for_row(row, key), "value": _format_cell(value), "url": url}
    inferred_column = _infer_symbol_column(rows, row_pos)
    if inferred_column:
        value = values.get(inferred_column)
        url = _build_binance_futures_url(value)
        if url:
            return {
                "column": _display_column_for_row(row, inferred_column),
                "value": _format_cell(value),
                "url": url,
            }
    for key, value in values.items():
        url = _build_binance_futures_url(value)
        if url:
            return {"column": _display_column_for_row(row, key), "value": _format_cell(value), "url": url}
    return None


def _infer_symbol_column(rows: list[dict[str, Any]], row_pos: int) -> str | None:
    for scan_pos in range(row_pos, -1, -1):
        for column, value in _raw_row_values(rows[scan_pos]).items():
            if _format_cell(value).strip() in SYMBOL_HEADER_NAMES:
                return str(column)
    return None


def _open_selected_symbol(state: dict) -> bool:
    rows = state.get("visible_rows") or []
    row_pos = int(state.get("selected_row_offset", 0))
    url = _symbol_url_for_visible_row(rows, row_pos)
    if not url:
        state["last_open_status"] = "当前行没有交易对"
        return False
    ok, message = _open_url(url)
    state["last_open_status"] = message
    return ok


def _open_url(url: str) -> tuple[bool, str]:
    command = _open_url_command(url)
    try:
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        return False, f"打开失败:{exc}"
    return True, url


def _open_url_command(url: str) -> list[str]:
    if _is_wsl():
        return ["cmd.exe", "/c", "start", "", url]
    if sys.platform == "darwin":
        return ["open", url]
    return ["xdg-open", url]


def _is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False
