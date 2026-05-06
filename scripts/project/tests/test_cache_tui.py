from __future__ import annotations

import io
import json
import queue
from pathlib import Path

from tradecat_terminal import cli
from tradecat_terminal.cache import (
    init_cache,
    normalized_event_key_for_row,
    prune_cache,
    read_cached_view,
    status_cache,
    sync_dataset,
    write_dataset_body,
)
from tradecat_terminal.config import DEFAULT_APP_ROOT, load_config
from tradecat_terminal.i18n import cycle_lang, resolve_lang, tr
from tradecat_terminal.registry import dataset_to_dict, get_dataset, list_active_datasets
from tradecat_terminal.settings import load_settings
from tradecat_terminal.sheets import find_header_row_index, parse_csv_rows
from tradecat_terminal.tui import (
    CURSES_POLL_TIMEOUT_MS,
    MOUSE_WHEEL_STEP,
    _background_probe_interval,
    _build_binance_futures_url,
    _display_slice,
    _display_width,
    _drain_probe_results,
    _effective_probe_interval,
    _filter_rows,
    _handle_mouse_event,
    _handle_screen_resize,
    _handle_sgr_mouse_payload,
    _hovered_link_row_offset,
    _maybe_probe_background,
    _normalize_contract_symbol,
    _observed_screen_size,
    _open_selected_symbol,
    _probe_state_label,
    _read_raw_sgr_mouse_event,
    _read_view_cached,
    _record_probe_result,
    _render_event_stream_viewport,
    _render_rows_table_viewport,
    _render_viewport_cached,
    _resolve_fetch_timeout,
    _resolve_probe_interval,
    _resolve_startup_dataset_key,
    _start_probe_thread,
    _status_bar,
    _switch_dataset,
    _symbol_link_spans,
    _symbol_url_for_visible_row,
    _update_probe_tuning_state,
    _url_link_for_visible_row,
    render_basic_tui,
    render_plain_fallback,
    render_rows_table,
    render_safe_plain_tui,
    run_tui,
)
from tradecat_terminal.view_model import build_dataset_view

REPO_ROOT = Path(__file__).resolve().parents[1]


class _TtyInput:
    def __init__(self) -> None:
        self.read_count = 0

    def isatty(self) -> bool:
        return True

    def readline(self) -> str:
        self.read_count += 1
        return "\n"


class _TtyOutput(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_init_cache_does_not_write_registry_projection(tmp_path):
    cache_dir = tmp_path / "cache"

    payload = init_cache(cache_dir)
    status = status_cache(cache_dir)

    assert payload["ok"] is True
    assert not (cache_dir / "registry.json").exists()
    assert (cache_dir / "datasets" / "market_snapshot" / "snapshots").exists()
    assert [item["dataset_key"] for item in status["datasets"]] == [
        "market_snapshot",
        "anomaly_panel",
        "market_stats",
        "event_stream",
    ]


def test_default_cache_dir_is_app_root_dot_tradecat_cache(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TRADECAT_CACHE_DIR", raising=False)

    config = load_config()

    assert config.cache_dir == DEFAULT_APP_ROOT / ".tradecat" / "cache"


def test_registry_has_no_freeze_columns_contract():
    keys = [dataset.key for dataset in list_active_datasets()]
    snapshot = dataset_to_dict(get_dataset("market_snapshot"))
    event_stream = dataset_to_dict(get_dataset("event_stream"))

    assert keys == ["market_snapshot", "anomaly_panel", "market_stats", "event_stream"]
    assert snapshot["data_mode"] == "snapshot"
    assert "freeze_columns" not in snapshot
    assert event_stream["data_mode"] == "stream"
    assert "freeze_columns" not in event_stream
    assert snapshot["display_names"]["en"] == "Market Snapshot"
    assert get_dataset("event_stream").display_name("ko") == "이벤트 스트림"
    assert event_stream["tui_probe_interval_seconds"] == 1.5
    assert event_stream["tui_fetch_timeout_seconds"] == 1.0


def test_request_script_uses_shared_dataset_registry_contract():
    request_py = (REPO_ROOT / "scripts" / "request.py").read_text(encoding="utf-8")
    registry_json = json.loads(
        (REPO_ROOT / "src" / "tradecat_terminal" / "dataset_registry.json").read_text(encoding="utf-8")
    )

    assert "dataset_registry.json" in request_py
    assert "WORKBOOKS =" not in request_py
    assert "DATASETS =" not in request_py
    assert sorted(registry_json["datasets"]) == ["anomaly_panel", "event_stream", "market_snapshot", "market_stats"]


def test_i18n_resolves_aliases_and_cycles_language(monkeypatch):
    monkeypatch.delenv("TRADECAT_LANG", raising=False)

    assert resolve_lang("en-US") == "en"
    assert resolve_lang("ko_KR.UTF-8") == "ko"
    assert resolve_lang("中文") == "zh"
    assert cycle_lang("zh") == "en"
    assert cycle_lang("en") == "ko"
    assert cycle_lang("ko") == "zh"
    assert tr("en", "mode_live") == "live"
    language_hint = "l 切换语言 / Switch language / 언어 전환: 中文/English/한국어"
    assert language_hint in tr("zh", "controls")
    assert language_hint in tr("en", "controls")
    assert language_hint in tr("ko", "controls")


def test_install_launchers_enable_default_auto_update():
    install_sh = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    install_ps1 = (REPO_ROOT / "install.ps1").read_text(encoding="utf-8")
    uninstall_ps1 = (REPO_ROOT / "uninstall.ps1").read_text(encoding="utf-8")

    assert "auto_update" in install_sh
    assert 'git -C "$APP_DIR" fetch origin "$BRANCH"' in install_sh
    assert 'git -C "$APP_DIR" pull --ff-only origin "$BRANCH"' in install_sh
    assert "TRADECAT_UPDATE_INTERVAL_SECONDS" in install_sh
    assert "run_update_blocking >/dev/null 2>&1 || true) &" in install_sh
    assert 'TRADECAT_NO_AUTO_UPDATE=1 "$BIN_DIR/tradecat" init' in install_sh
    assert "TRADECAT_INSTALL_SKIP_SYNC" in install_sh
    assert "TRADECAT_INSTALL_SKIP_PATH_WRITE" in install_sh
    assert "TRADECAT_FORCE_UPDATE" in install_sh
    assert "TRADECAT_NO_AUTO_UPDATE" in install_sh
    assert "Invoke-TradeCatAutoUpdate" in install_ps1
    assert "tradecat-update.ps1" in install_ps1
    assert "TRADECAT_UPDATE_INTERVAL_SECONDS" in install_ps1
    assert "Start-Process -FilePath \"powershell\"" in install_ps1
    assert "$env:TRADECAT_NO_AUTO_UPDATE = \"1\"" in install_ps1
    assert "TRADECAT_INSTALL_SKIP_SYNC" in install_ps1
    assert "TRADECAT_INSTALL_SKIP_PATH_WRITE" in install_ps1
    assert "TRADECAT_FORCE_UPDATE" in install_ps1
    assert "tradecat.ps1" in install_ps1
    assert "tradecat.ps1" in uninstall_ps1


def test_powershell_installers_are_ascii_for_windows_powershell_51():
    for relative_path in ("install.ps1", "uninstall.ps1"):
        content = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert content.encode("ascii").decode("ascii") == content


def test_parse_csv_rows_skips_public_top_row():
    rows = parse_csv_rows(
        '"https://dexscreener.com/x\\nhttps://t.me/y\\n数据源，事件流",\n'
        "数据源,market\n"
        "时间(北京),内容\n"
        "2026-04-28 12:00:00,hello\n"
    )

    assert rows == [{"时间(北京)": "2026-04-28 12:00:00", "内容": "hello"}]
    assert find_header_row_index([["https://dexscreener.com/x", ""], ["时间(北京)", "内容"]]) == 1


def test_sync_dataset_writes_snapshot_files(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"

    import tradecat_terminal.cache as cache_module

    monkeypatch.setattr(
        cache_module,
        "fetch_csv_body",
        lambda url, timeout=30.0: "https://dexscreener.com/x\n数据源,market\n排名,交易对,价格\n1,BTCUSDT,100\n",
    )

    first = sync_dataset(cache_dir, "market_snapshot")
    second = sync_dataset(cache_dir, "market_snapshot")
    view = read_cached_view(cache_dir, "market_snapshot")

    assert first["status"] == "written"
    assert second["status"] == "unchanged"
    assert first["row_count"] == 4
    assert len(list((cache_dir / "datasets" / "market_snapshot" / "snapshots").glob("*.json"))) == 1
    assert view["top_lines"] == ["https://dexscreener.com/x"]
    assert view["rows"][0]["row_index"] == 2
    assert view["rows"][0]["values"]["A"] == "数据源"
    assert view["rows"][2]["values"]["B"] == "BTCUSDT"
    assert len(view["columns"]) == 3


def test_sync_dataset_writes_structured_latest_files(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"

    import tradecat_terminal.cache as cache_module

    monkeypatch.setattr(
        cache_module,
        "fetch_csv_body",
        lambda url, timeout=30.0: (
            "https://dexscreener.com/x\n"
            "数据源,market,导出时间(UTC+8),2026-05-01T12:00:00+08:00\n"
            "排名,交易对,综合分,5m量变(%)\n"
            "1,BTCUSDT,98.2,1.23%\n"
        ),
    )

    result = sync_dataset(cache_dir, "market_snapshot")
    dataset_dir = cache_dir / "datasets" / "market_snapshot"
    latest = json.loads((dataset_dir / "latest.json").read_text(encoding="utf-8"))
    jsonl = (dataset_dir / "latest.jsonl").read_text(encoding="utf-8").strip()
    csv_text = (dataset_dir / "latest.csv").read_text(encoding="utf-8")
    root_manifest = json.loads((cache_dir / "manifest.json").read_text(encoding="utf-8"))

    assert result["structured_row_count"] == 1
    assert latest["schema"] == "tradecat.dataset.v1"
    assert latest["layout"]["meta"]["数据源"] == "market"
    assert latest["indexes"]["primary_key"] == "交易对"
    assert latest["rows"][0]["key"] == "BTC"
    assert latest["rows"][0]["typed_values"]["综合分"] == 98.2
    assert latest["rows"][0]["typed_values"]["5m量变(%)"] == 0.0123
    assert "BTCUSDT" in jsonl
    assert csv_text.splitlines()[0] == "排名,交易对,综合分,5m量变(%)"
    assert root_manifest["schema"] == "tradecat.cache_manifest.v1"
    assert root_manifest["datasets"][0]["latest_json"] == "datasets/market_snapshot/latest.json"


def test_structured_latest_extracts_meta_from_public_top_cell(tmp_path):
    cache_dir = tmp_path / "cache"
    dataset = get_dataset("event_stream")

    write_dataset_body(
        cache_dir,
        dataset,
        (
            "https://dexscreener.com/x\n"
            "https://t.me/y\n"
            "数据源，事件流，导出时间(UTC+8)，2026-05-01T12:00:00+08:00，刷新间隔(s)，1.5\n"
            "时间(北京),内容\n"
            "2026-05-01 12:00:00,hello\n"
        ),
    )

    latest = json.loads((cache_dir / "datasets" / "event_stream" / "latest.json").read_text(encoding="utf-8"))

    assert latest["layout"]["top_lines"] == ["https://dexscreener.com/x", "https://t.me/y"]
    assert latest["layout"]["meta"]["数据源"] == "事件流"
    assert latest["layout"]["meta"]["刷新间隔(s)"] == "1.5"
    assert latest["sync"]["remote_updated_at_utc8"] == "2026-05-01T12:00:00+08:00"


def test_snapshot_cache_supports_optional_gzip_snapshots(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    dataset = get_dataset("market_snapshot")
    monkeypatch.setenv("TRADECAT_CACHE_COMPRESSION", "gzip")

    result = write_dataset_body(
        cache_dir,
        dataset,
        "https://dexscreener.com/x\n排名,交易对,价格\n1,BTCUSDT,100\n",
    )
    view = read_cached_view(cache_dir, "market_snapshot")

    assert result["compression"] == "gzip"
    assert str(result["snapshot"]).endswith(".json.gz")
    assert view["rows"][1]["values"]["B"] == "BTCUSDT"


def test_snapshot_cache_keeps_multiple_batches(tmp_path):
    cache_dir = tmp_path / "cache"
    dataset = get_dataset("market_snapshot")

    first = write_dataset_body(
        cache_dir,
        dataset,
        "https://dexscreener.com/x\n排名,交易对,价格\n1,BTCUSDT,100\n",
    )
    second = write_dataset_body(
        cache_dir,
        dataset,
        "https://dexscreener.com/x\n排名,交易对,价格\n1,BTCUSDT,101\n",
    )

    latest = read_cached_view(cache_dir, "market_snapshot", batch_index=0, live=False)
    older = read_cached_view(cache_dir, "market_snapshot", batch_index=1, live=False)

    assert first["changed"] is True
    assert second["changed"] is True
    assert latest["batch_count"] == 2
    assert latest["rows"][1]["values"]["C"] == "101"
    assert older["rows"][1]["values"]["C"] == "100"


def test_prune_cache_is_dry_run_by_default_and_apply_is_explicit(tmp_path):
    cache_dir = tmp_path / "cache"
    dataset = get_dataset("market_snapshot")
    for price in ["100", "101", "102"]:
        write_dataset_body(
            cache_dir,
            dataset,
            f"https://dexscreener.com/x\n排名,交易对,价格\n1,BTCUSDT,{price}\n",
        )

    dry_run = prune_cache(cache_dir, dataset_key="market_snapshot", max_snapshots_per_dataset=1, apply=False)
    assert dry_run["datasets"][0]["candidate_count"] == 2
    assert len(list((cache_dir / "datasets" / "market_snapshot" / "snapshots").glob("*.json*"))) == 3

    applied = prune_cache(cache_dir, dataset_key="market_snapshot", max_snapshots_per_dataset=1, apply=True)
    view = read_cached_view(cache_dir, "market_snapshot")

    assert applied["datasets"][0]["deleted_count"] == 2
    assert len(list((cache_dir / "datasets" / "market_snapshot" / "snapshots").glob("*.json*"))) == 1
    assert view["rows"][1]["values"]["C"] == "102"


def test_event_stream_uses_incremental_event_file(tmp_path):
    cache_dir = tmp_path / "cache"
    dataset = get_dataset("event_stream")

    first = write_dataset_body(
        cache_dir,
        dataset,
        "时间(北京),内容\n2026-04-28 12:00:00,hello\n",
    )
    second = write_dataset_body(
        cache_dir,
        dataset,
        "时间(北京),内容\n2026-04-28 12:00:00,hello\n2026-04-28 12:01:00,world\n",
    )
    view = read_cached_view(cache_dir, "event_stream")

    assert first["stream"]["new_events"] == 1
    assert second["stream"]["new_events"] == 1
    assert second["stream"]["updated_events"] == 1
    assert view["data_mode"] == "stream"
    assert view["rows"][0]["values"] == {"A": "时间(北京)", "B": "内容"}
    assert [row["values"]["B"] for row in view["rows"][1:]] == ["hello", "world"]


def test_event_stream_keeps_normalized_event_key_for_diagnostics(tmp_path):
    cache_dir = tmp_path / "cache"
    dataset = get_dataset("event_stream")
    row = {"时间(北京)": "2026-04-28 12:00:00", "内容": " hello   world "}

    write_dataset_body(
        cache_dir,
        dataset,
        "时间(北京),内容\n2026-04-28 12:00:00, hello   world \n",
    )
    state_path = cache_dir / "datasets" / "event_stream" / "stream_events.json"

    assert normalized_event_key_for_row(dataset, row)
    assert "normalized_event_key" in state_path.read_text(encoding="utf-8")


def test_event_stream_merges_same_normalized_content_when_time_drifts(tmp_path):
    cache_dir = tmp_path / "cache"
    dataset = get_dataset("event_stream")

    first = write_dataset_body(
        cache_dir,
        dataset,
        "时间(北京),内容\n2026-04-28 12:00:00,美国总统特朗普讲话\n",
    )
    second = write_dataset_body(
        cache_dir,
        dataset,
        "时间(北京),内容\n2026-04-28 12:00:05, 美国总统特朗普讲话 \n",
    )
    state = json.loads((cache_dir / "datasets" / "event_stream" / "stream_events.json").read_text(encoding="utf-8"))

    assert first["stream"]["new_events"] == 1
    assert second["stream"]["new_events"] == 0
    assert second["stream"]["updated_events"] == 1
    assert len(state["events"]) == 1
    assert state["events"][0]["seen_count"] == 2
    assert len(state["events"][0]["observed_event_keys"]) == 2


def test_cli_without_subcommand_opens_tui(tmp_path, monkeypatch):
    calls = {}

    def fake_run_tui(
        cache_dir,
        dataset_key=None,
        limit=0,
        *,
        interactive=True,
        live=True,
        probe_interval_seconds=None,
        lang=None,
    ):
        calls["cache_dir"] = cache_dir
        calls["dataset_key"] = dataset_key
        calls["limit"] = limit
        calls["interactive"] = interactive
        calls["live"] = live
        calls["probe_interval_seconds"] = probe_interval_seconds
        calls["lang"] = lang
        return None

    monkeypatch.setattr(cli, "run_tui", fake_run_tui)

    assert cli.main(["--cache-dir", str(tmp_path / "cache")]) == 0
    assert calls == {
        "cache_dir": tmp_path / "cache",
        "dataset_key": None,
        "limit": 0,
        "interactive": True,
        "live": True,
        "probe_interval_seconds": None,
        "lang": None,
    }


def test_cli_routes_language_option_to_default_tui(tmp_path, monkeypatch):
    calls = {}

    def fake_run_tui(
        cache_dir,
        dataset_key=None,
        limit=0,
        *,
        interactive=True,
        live=True,
        probe_interval_seconds=None,
        lang=None,
    ):
        calls["cache_dir"] = cache_dir
        calls["lang"] = lang
        calls["interactive"] = interactive
        return None

    monkeypatch.setattr(cli, "run_tui", fake_run_tui)

    assert cli.main(["--cache-dir", str(tmp_path / "cache"), "--lang", "ko"]) == 0
    assert calls == {"cache_dir": tmp_path / "cache", "lang": "ko", "interactive": True}


def test_cli_path_outputs_agent_friendly_cache_paths(tmp_path, capsys):
    cache_dir = tmp_path / "cache"

    assert cli.main(["--cache-dir", str(cache_dir), "path", "event_stream", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["manifest"] == str(cache_dir / "datasets" / "event_stream" / "manifest.json")
    assert payload["latest_json"] == str(cache_dir / "datasets" / "event_stream" / "latest.json")
    assert payload["latest_jsonl"] == str(cache_dir / "datasets" / "event_stream" / "latest.jsonl")
    assert payload["latest_csv"] == str(cache_dir / "datasets" / "event_stream" / "latest.csv")
    assert payload["stream_events"] == str(cache_dir / "datasets" / "event_stream" / "stream_events.json")


def test_cli_config_set_show_unset_uses_local_settings_file(tmp_path, monkeypatch, capsys):
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("TRADECAT_SETTINGS_PATH", str(settings_path))

    assert cli.main(["config", "set", "default_lang", "en"]) == 0
    assert cli.main(["config", "set", "default_dataset", "event_stream"]) == 0
    assert load_settings()["default_lang"] == "en"
    assert load_settings()["default_dataset"] == "event_stream"

    assert cli.main(["config", "show", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert payload["settings"]["default_lang"] == "en"

    assert cli.main(["config", "unset", "default_lang"]) == 0
    assert "default_lang" not in load_settings()


def test_cli_export_outputs_raw_csv_and_display_table(tmp_path, capsys):
    cache_dir = tmp_path / "cache"
    write_dataset_body(
        cache_dir,
        get_dataset("market_snapshot"),
        "https://dexscreener.com/x\n排名,交易对,综合分\n1,BTCUSDT,98.2\n",
    )

    assert cli.main(["--cache-dir", str(cache_dir), "export", "market_snapshot", "--format", "csv"]) == 0
    csv_output = capsys.readouterr().out
    assert csv_output.splitlines()[0] == "排名,交易对,综合分"
    assert "BTCUSDT" in csv_output

    assert cli.main(["--cache-dir", str(cache_dir), "export", "market_snapshot", "--format", "table", "--lang", "en"]) == 0
    table_output = capsys.readouterr().out
    assert "| A " in table_output
    assert "| B " in table_output
    assert "交易对" in table_output
    assert "BTCUSDT" in table_output


def test_cli_pauses_after_automatic_plain_fallback(monkeypatch):
    stdin = _TtyInput()
    stdout = _TtyOutput()
    monkeypatch.delenv("TRADECAT_TERMINAL_NO_PAUSE", raising=False)
    monkeypatch.setattr(cli.sys, "stdin", stdin)
    monkeypatch.setattr(cli.sys, "stdout", stdout)

    cli._pause_after_interactive_fallback(enabled=True)

    assert stdin.read_count == 1
    assert "按 Enter 退出" in stdout.getvalue()


def test_cli_does_not_pause_for_explicit_plain(monkeypatch):
    stdin = _TtyInput()
    stdout = _TtyOutput()
    monkeypatch.setattr(cli.sys, "stdin", stdin)
    monkeypatch.setattr(cli.sys, "stdout", stdout)

    cli._pause_after_interactive_fallback(enabled=False)

    assert stdin.read_count == 0
    assert stdout.getvalue() == ""


def test_cli_no_pause_env_skips_interactive_fallback(monkeypatch):
    stdin = _TtyInput()
    stdout = _TtyOutput()
    monkeypatch.setenv("TRADECAT_TERMINAL_NO_PAUSE", "1")
    monkeypatch.setattr(cli.sys, "stdin", stdin)
    monkeypatch.setattr(cli.sys, "stdout", stdout)

    cli._pause_after_interactive_fallback(enabled=True)

    assert stdin.read_count == 0
    assert stdout.getvalue() == ""


def test_tui_plain_render_reads_snapshot_cache(tmp_path):
    cache_dir = tmp_path / "cache"
    write_dataset_body(
        cache_dir,
        get_dataset("market_snapshot"),
        "https://dexscreener.com/x\n数据源,market\n排名,交易对,价格\n1,BTCUSDT,100\n",
    )

    output = render_basic_tui(cache_dir, dataset_key="market_snapshot", limit=0)

    assert "TradeCat" in output
    assert "https://dexscreener.com/x" in output
    assert "+---" not in output
    assert "| A " not in output
    assert "#4" in output
    assert "数据源" in output
    assert "BTCUSDT" in output


def test_tui_table_renderer_preserves_full_plain_structure():
    values = {f"字段{i}": f"值{i}" for i in range(1, 13)}
    values["长文本"] = "abcdefghijklmnopqrstuvwxyz0123456789"

    output = render_rows_table([{"source": "market_snapshot", "row_index": 1, "values": values}])

    assert "| 字段12 " in output
    assert "| 长文本 " in output
    assert "abcdefghijklmnopqrstuvwxyz0123456789" in output
    assert len({_display_width(line) for line in output.splitlines()}) == 1


def test_tui_safe_plain_fallback_uses_borderless_width_capped_output(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    long_text = "美国总统特朗普：伊朗的无人机和导弹工厂数量大幅下降。" * 8
    write_dataset_body(
        cache_dir,
        get_dataset("event_stream"),
        f"https://dexscreener.com/x\n时间(北京),内容\n2026-05-01 03:09:56,{long_text}\n",
    )
    monkeypatch.setenv("TRADECAT_TERMINAL_PLAIN_WIDTH", "80")

    output = render_plain_fallback(cache_dir, "event_stream", 0, "Windows 原生终端的 curses 渲染不稳定", lang="zh")
    lines = output.splitlines()

    assert "Windows 原生终端的 curses 渲染不稳定" in output
    assert "已自动切换为 Rich 静态文本模式" in output
    assert "+---" not in output
    assert not any(line.startswith("+") or set(line) <= {"-", "+"} for line in lines if line)
    assert all(_display_width(line) <= 80 for line in lines)
    assert "2026-05-01 03:09:56" in output
    assert "美国总统特朗普" in output


def test_tui_safe_plain_renderer_handles_wide_snapshot_without_psql_borders(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    columns = ",".join(f"字段{i}" for i in range(1, 18))
    values = ",".join(f"值{i}" for i in range(1, 18))
    write_dataset_body(
        cache_dir,
        get_dataset("market_snapshot"),
        f"数据源,market\n{columns}\n{values}\n",
    )
    monkeypatch.setenv("TRADECAT_TERMINAL_PLAIN_WIDTH", "90")

    output = render_safe_plain_tui(cache_dir, dataset_key="market_snapshot", limit=0)

    assert "+---" not in output
    assert "| 字段" not in output
    assert all(_display_width(line) <= 90 for line in output.splitlines())
    assert "#3" in output
    assert "数据源" in output


def test_tui_plain_renderer_uses_requested_language_without_translating_data(tmp_path):
    cache_dir = tmp_path / "cache"
    write_dataset_body(
        cache_dir,
        get_dataset("event_stream"),
        "https://dexscreener.com/x\n时间(北京),内容\n2026-05-01 03:09:56,美国总统特朗普讲话\n",
    )

    output = render_safe_plain_tui(cache_dir, dataset_key="event_stream", limit=0, lang="en")

    assert "current: event_stream (Event Stream)" in output
    assert " A " in output
    assert " B " in output
    assert "时间(北京)" in output
    assert "内容" in output
    assert "美国总统特朗普讲话" in output


def test_view_model_keeps_physical_columns_and_alias_metadata(tmp_path):
    cache_dir = tmp_path / "cache"
    write_dataset_body(
        cache_dir,
        get_dataset("market_snapshot"),
        (
            "https://dexscreener.com/x\n"
            "数据源,market,导出时间(UTC+8),2026-05-01T12:00:00\n"
            "排名,交易对,综合分,5m量变(%)\n"
            "1,BTCUSDT,98.2,1.23%\n"
        ),
    )

    view = build_dataset_view(cache_dir, "market_snapshot", lang="en")
    latest = json.loads((cache_dir / "datasets" / "market_snapshot" / "latest.json").read_text(encoding="utf-8"))

    assert view["columns"] == ["A", "B", "C", "D"]
    assert view["raw_columns"] == ["排名", "交易对", "综合分", "5m量变(%)"]
    assert [item["display_name"] for item in view["column_meta"]] == ["Rank", "Symbol", "Score", "5m Volume Change (%)"]
    assert view["rows"][0]["values"]["B"] == "交易对"
    assert view["rows"][1]["values"]["B"] == "BTCUSDT"
    assert view["rows"][1]["raw_values"]["交易对"] == "BTCUSDT"
    assert view["rows"][1]["display_column_by_raw"]["交易对"] == "B"
    assert latest["columns"][1]["name"] == "交易对"
    assert latest["rows"][0]["values"]["交易对"] == "BTCUSDT"


def test_view_model_supports_korean_header_aliases(tmp_path):
    cache_dir = tmp_path / "cache"
    write_dataset_body(
        cache_dir,
        get_dataset("event_stream"),
        "https://dexscreener.com/x\n时间(北京),内容\n2026-05-01 03:09:56,美国总统特朗普讲话\n",
    )

    view = build_dataset_view(cache_dir, "event_stream", lang="ko")

    assert view["display_name"] == "이벤트 스트림"
    assert view["columns"] == ["A", "B"]
    assert [item["display_name"] for item in view["column_meta"]] == ["시간(UTC+8)", "내용"]
    assert view["rows"][0]["values"]["B"] == "内容"
    assert view["rows"][1]["values"]["B"] == "美国总统特朗普讲话"
    assert view["rows"][1]["raw_values"]["内容"] == "美国总统特朗普讲话"


def test_tui_empty_plain_renderer_uses_korean_language(tmp_path):
    output = run_tui(tmp_path / "cache", dataset_key="event_stream", interactive=False, live=True, lang="ko")

    assert "current: event_stream (이벤트 스트림)" in output
    assert "로컬 스냅샷 캐시가 없습니다" in output


def test_viewport_renderer_outputs_all_columns_without_freezing_or_horizontal_scroll():
    rows = [
        {
            "source": "market_snapshot",
            "row_index": 2,
            "values": {f"字段{i}": f"值{i}" for i in range(1, 30)},
        }
    ]
    columns = list(rows[0]["values"])

    viewport = _render_rows_table_viewport(rows, columns=columns)

    assert viewport["columns"] == columns
    assert viewport["columns"][-1] == "字段29"
    assert all(line.endswith("+") or line.endswith("|") for line in viewport["lines"])


def test_viewport_renderer_keeps_long_cell_width_for_terminal_zoom():
    long_text = "这是一条很长的事件流内容" * 12
    rows = [
        {"source": "event_stream", "row_index": 2, "values": {"A": "时间(北京)", "B": "内容"}},
        {"source": "event_stream", "row_index": 3, "values": {"A": "2026-04-30 14:57:54", "B": long_text}},
    ]

    viewport = _render_rows_table_viewport(rows, columns=["A", "B"])
    rendered = "\n".join(viewport["lines"])

    assert "..." not in rendered
    assert long_text in rendered
    assert max(_display_width(line) for line in viewport["lines"]) > 120


def test_event_stream_viewport_uses_lightweight_two_column_renderer():
    rows = [
        {
            "source": "event_stream",
            "row_index": 2,
            "values": {"A": "时间(北京)", "B": "内容", "C": "不应渲染"},
        }
    ]

    viewport = _render_event_stream_viewport(rows, columns=["A", "B", "C"])
    rendered = "\n".join(viewport["lines"])

    assert viewport["columns"] == ["A", "B"]
    assert "不应渲染" not in rendered


def test_tui_read_view_cache_reuses_snapshot_until_invalidated(tmp_path, monkeypatch):
    import tradecat_terminal.tui as tui_module

    cache_dir = tmp_path / "cache"
    calls = []

    def fake_build_dataset_view(path, dataset_key, *, batch_index=0, live=True, lang=None):
        calls.append((path, dataset_key, batch_index, live, lang))
        return {"rows": [], "columns": [], "content_hash": f"hash-{len(calls)}"}

    monkeypatch.setattr(tui_module, "build_dataset_view", fake_build_dataset_view)
    state = {"view_cache": {}, "render_cache": {}}

    first = _read_view_cached(cache_dir, state, "event_stream", batch_index=0, live=True)
    second = _read_view_cached(cache_dir, state, "event_stream", batch_index=0, live=True)
    tui_module._invalidate_view_cache(state, "event_stream")
    third = _read_view_cached(cache_dir, state, "event_stream", batch_index=0, live=True)

    assert first is second
    assert first is not third
    assert len(calls) == 2


def test_tui_read_view_cache_is_language_aware(tmp_path, monkeypatch):
    import tradecat_terminal.tui as tui_module

    cache_dir = tmp_path / "cache"
    calls = []

    def fake_build_dataset_view(path, dataset_key, *, batch_index=0, live=True, lang=None):
        calls.append((path, dataset_key, batch_index, live, lang))
        return {"rows": [], "columns": [], "content_hash": f"hash-{len(calls)}", "lang": lang}

    monkeypatch.setattr(tui_module, "build_dataset_view", fake_build_dataset_view)
    state = {"view_cache": {}, "render_cache": {}, "lang": "zh"}

    first = _read_view_cached(cache_dir, state, "event_stream", batch_index=0, live=True)
    second = _read_view_cached(cache_dir, state, "event_stream", batch_index=0, live=True)
    state["lang"] = "en"
    third = _read_view_cached(cache_dir, state, "event_stream", batch_index=0, live=True)

    assert first is second
    assert third is not first
    assert [call[-1] for call in calls] == ["zh", "en"]


def test_tui_symbol_link_uses_raw_values_with_physical_columns():
    rows = [
        {
            "row_index": 3,
            "values": {"A": "1", "B": "ETH"},
            "raw_values": {"排名": "1", "交易对": "ETH"},
            "display_column_by_raw": {"排名": "A", "交易对": "B"},
        }
    ]
    viewport = _render_rows_table_viewport(rows, columns=["A", "B"])
    spans = _symbol_link_spans(rows, viewport["columns"], viewport["widths"])

    assert _symbol_url_for_visible_row(rows, 0) == "https://www.binance.com/zh-CN/futures/ETHUSDT?type=perpetual"
    assert spans[0]["column"] == "B"
    assert spans[0]["url"] == "https://www.binance.com/zh-CN/futures/ETHUSDT?type=perpetual"


def test_tui_filter_rows_matches_display_and_raw_values():
    rows = [
        {"values": {"Symbol": "BTCUSDT", "Content": "hello"}, "raw_values": {"交易对": "BTCUSDT", "内容": "你好"}},
        {"values": {"Symbol": "ETHUSDT", "Content": "world"}, "raw_values": {"交易对": "ETHUSDT", "内容": "世界"}},
    ]

    assert len(_filter_rows(rows, "ETH")) == 1
    assert len(_filter_rows(rows, "世界")) == 1
    assert _filter_rows(rows, "") == rows


def test_tui_status_bar_exposes_freshness_and_cache_context(tmp_path):
    view = {
        "rows": [{"values": {"A": "1"}}],
        "meta": {"导出时间(UTC+8)": "2026-05-01T17:52:26"},
        "fetched_at": "2026-05-01T09:52:26+00:00",
    }
    state = {"last_probe_status": "cache", "live": True, "last_probe_at": 0.0, "effective_probe_interval_seconds": 10.0}

    status = _status_bar(view, state, lang="zh", cache_dir=tmp_path)

    assert "cache=cache-hit" in status
    assert "remote=2026-05-01T17:52:26" in status
    assert f"path={tmp_path}" in status


def test_tui_render_view_cache_reuses_rendered_viewport(monkeypatch):
    import tradecat_terminal.tui as tui_module

    calls = []

    def fake_render(rows, *, columns=None):
        calls.append((rows, columns))
        return {"lines": ["cached"], "columns": list(columns or []), "widths": [1]}

    monkeypatch.setattr(tui_module, "_render_rows_table_viewport", fake_render)
    rows = [{"row_index": 2, "values": {"A": "1"}}]
    state = {"render_cache": {}}

    first = _render_viewport_cached(state, "snapshot", rows, columns=["A"], content_hash="h1", row_scroll=0)
    second = _render_viewport_cached(state, "snapshot", rows, columns=["A"], content_hash="h1", row_scroll=0)
    third = _render_viewport_cached(state, "snapshot", rows, columns=["A"], content_hash="h2", row_scroll=0)

    assert first is second
    assert first is not third
    assert len(calls) == 2


def test_tui_resize_detection_invalidates_render_cache(monkeypatch):
    import tradecat_terminal.tui as tui_module

    class FakeScreen:
        def __init__(self):
            self.erased = False
            self.resized = []

        def getmaxyx(self):
            return (24, 80)

        def erase(self):
            self.erased = True

        def resize(self, rows, cols):
            self.resized.append((rows, cols))

    screen = FakeScreen()
    state = {"screen_size": (24, 80), "last_frame_height": 24, "render_cache": {"old": "value"}}
    monkeypatch.setattr(tui_module, "_terminal_size", lambda: (40, 140))
    monkeypatch.setattr(tui_module.curses, "update_lines_cols", lambda: None)
    monkeypatch.setattr(tui_module.curses, "resize_term", lambda rows, cols: None)

    assert _handle_screen_resize(screen, state) is True
    assert state["screen_size"] == (40, 140)
    assert state["last_frame_height"] == 0
    assert state["render_cache"] == {}
    assert screen.erased is True
    assert screen.resized == [(40, 140)]


def test_tui_resize_detection_noops_when_size_is_unchanged(monkeypatch):
    import tradecat_terminal.tui as tui_module

    class FakeScreen:
        def getmaxyx(self):
            return (24, 80)

    screen = FakeScreen()
    state = {"screen_size": (24, 80), "render_cache": {"old": "value"}}
    monkeypatch.setattr(tui_module, "_terminal_size", lambda: None)

    assert _observed_screen_size(screen) == (24, 80)
    assert _handle_screen_resize(screen, state) is False
    assert state["render_cache"] == {"old": "value"}


def test_tui_display_slice_is_terminal_width_aware_for_cjk():
    text = "A窗口覆盖合约数BTC"

    assert _display_width("窗口") == 4
    assert _display_width(_display_slice(text, 0, 5)) <= 5
    assert _display_width(_display_slice(text, 2, 6)) <= 6


def test_tui_left_right_switch_tap_resets_view_state():
    state = {
        "datasets": [
            {"dataset_key": "event_stream"},
            {"dataset_key": "market_snapshot"},
        ],
        "dataset_index": 0,
        "batch_index": 1,
        "batch_count": 2,
        "row_scroll": 4,
        "hover_row_offset": 1,
        "selected_row_offset": 2,
        "live": False,
        "last_probe_at": 123.0,
        "view_cache": {("event_stream", 0, True): {"content_hash": "old"}},
        "render_cache": {"old": "value"},
    }

    _switch_dataset(state, 1)

    assert state["dataset_index"] == 1
    assert state["batch_index"] == 0
    assert state["row_scroll"] == 0
    assert state["live"] is True
    assert state["hover_row_offset"] is None
    assert state["last_probe_at"] == 0.0
    assert state["view_cache"] == {}
    assert state["render_cache"] == {}


def test_tui_probe_result_refreshes_stale_cached_view_even_when_remote_hash_is_unchanged():
    state = {
        "datasets": [{"dataset_key": "market_snapshot"}],
        "dataset_index": 0,
        "probe_generation": 0,
        "probe_inflight": True,
        "view_cache": {("market_snapshot", 0, True): {"content_hash": "old-hash"}},
        "render_cache": {"old": "value"},
    }
    results = queue.Queue()
    results.put(
        {
            "dataset_key": "market_snapshot",
            "generation": 0,
            "result": {
                "ok": True,
                "status": "unchanged",
                "changed": False,
                "wrote": False,
                "content_hash": "new-hash",
            },
        }
    )

    assert _drain_probe_results(state, results) is True
    assert state["view_cache"] == {}
    assert state["render_cache"] == {}


def test_tui_mouse_wheel_updates_vertical_scroll(monkeypatch):
    import curses

    import tradecat_terminal.tui as tui_module

    button_down = getattr(curses, "BUTTON5_PRESSED", 0) or 0x200000
    button_up = getattr(curses, "BUTTON4_PRESSED", 0) or 0x100000
    monkeypatch.setattr(tui_module.curses, "BUTTON5_PRESSED", button_down, raising=False)
    monkeypatch.setattr(tui_module.curses, "BUTTON4_PRESSED", button_up, raising=False)

    state = {"row_scroll": 0}

    monkeypatch.setattr(tui_module, "_read_mouse_event", lambda: (0, 0, 10, 0, button_down))
    assert _handle_mouse_event(state) is True
    assert state["row_scroll"] == MOUSE_WHEEL_STEP

    monkeypatch.setattr(tui_module, "_read_mouse_event", lambda: (0, 0, 10, 0, button_up))
    assert _handle_mouse_event(state) is True
    assert state["row_scroll"] == 0


def test_tui_symbol_url_uses_nearest_sheet_header_row():
    rows = [
        {"row_index": 2, "values": {"A": "排名", "B": "交易对"}},
        {"row_index": 3, "values": {"A": "1", "B": "BTC"}},
    ]

    assert _symbol_url_for_visible_row(rows, 1) == "https://www.binance.com/zh-CN/futures/BTCUSDT?type=perpetual"


def test_tui_url_link_takes_priority_over_symbol_link():
    rows = [{"row_index": 2, "values": {"A": "公告", "B": "https://example.com/path?x=1"}}]

    assert _url_link_for_visible_row(rows, 0) == {
        "column": "B",
        "value": "https://example.com/path?x=1",
        "url": "https://example.com/path?x=1",
        "display_offset": 0,
    }
    assert _symbol_url_for_visible_row(rows, 0) == "https://example.com/path?x=1"


def test_tui_builds_binance_futures_url_from_contract_symbol():
    assert _normalize_contract_symbol("BTC") == "BTCUSDT"
    assert _normalize_contract_symbol("BTCUSDT") == "BTCUSDT"
    assert _normalize_contract_symbol("btc/usdt") == "BTCUSDT"
    assert _normalize_contract_symbol("交易对") is None
    assert _normalize_contract_symbol("12345") is None
    assert _build_binance_futures_url("ETH") == "https://www.binance.com/zh-CN/futures/ETHUSDT?type=perpetual"


def test_tui_mouse_click_opens_clicked_symbol(monkeypatch):
    import curses

    import tradecat_terminal.tui as tui_module

    click = getattr(curses, "BUTTON1_PRESSED", 0) or 0x2
    monkeypatch.setattr(tui_module.curses, "BUTTON1_PRESSED", click, raising=False)
    rows = [
        {"row_index": 2, "values": {"A": "排名", "B": "交易对"}},
        {"row_index": 3, "values": {"A": "1", "B": "ETH"}},
    ]
    viewport = _render_rows_table_viewport(rows, columns=["A", "B"])
    link_spans = _symbol_link_spans(rows, viewport["columns"], viewport["widths"])
    monkeypatch.setattr(tui_module, "_read_mouse_event", lambda: (0, link_spans[1]["start"], 11, 0, click))
    opened = []
    monkeypatch.setattr(tui_module, "_open_url", lambda url: opened.append(url) or (True, url))
    state = {"data_start_y": 10, "selected_row_offset": 0, "visible_rows": rows, "link_spans": link_spans}

    assert _handle_mouse_event(state) is True
    assert state["selected_row_offset"] == 1
    assert opened == ["https://www.binance.com/zh-CN/futures/ETHUSDT?type=perpetual"]


def test_tui_mouse_hover_only_matches_symbol_cell():
    rows = [
        {"row_index": 2, "values": {"A": "排名", "B": "交易对"}},
        {"row_index": 3, "values": {"A": "1", "B": "ETH"}},
    ]
    viewport = _render_rows_table_viewport(rows, columns=["A", "B"])
    link_spans = _symbol_link_spans(rows, viewport["columns"], viewport["widths"])
    state = {"data_start_y": 10, "visible_rows": rows, "link_spans": link_spans}

    assert _hovered_link_row_offset(state, link_spans[1]["start"], 11) == 1
    assert _hovered_link_row_offset(state, link_spans[1]["end"], 11) is None
    assert _hovered_link_row_offset(state, 0, 11) is None


def test_tui_open_selected_symbol_uses_visible_row(monkeypatch):
    import tradecat_terminal.tui as tui_module

    opened = []
    monkeypatch.setattr(tui_module, "_open_url", lambda url: opened.append(url) or (True, url))
    state = {
        "selected_row_offset": 1,
        "visible_rows": [
            {"row_index": 2, "values": {"A": "排名", "B": "交易对"}},
            {"row_index": 3, "values": {"A": "1", "B": "BTC"}},
        ],
    }

    assert _open_selected_symbol(state) is True
    assert opened == ["https://www.binance.com/zh-CN/futures/BTCUSDT?type=perpetual"]


def test_tui_open_selected_url_uses_visible_row(monkeypatch):
    import tradecat_terminal.tui as tui_module

    opened = []
    monkeypatch.setattr(tui_module, "_open_url", lambda url: opened.append(url) or (True, url))
    state = {
        "selected_row_offset": 0,
        "visible_rows": [{"row_index": 2, "values": {"A": "链接", "B": "https://example.com/report"}}],
    }

    assert _open_selected_symbol(state) is True
    assert opened == ["https://example.com/report"]


def test_tui_reads_raw_sgr_mouse_event_without_leaking_escape_tail():
    class FakeScreen:
        def __init__(self):
            self.timeout_values = []
            self.chars = [ord(char) for char in "[<35;52;58M"]

        def timeout(self, value):
            self.timeout_values.append(value)

        def getch(self):
            if not self.chars:
                return -1
            return self.chars.pop(0)

    screen = FakeScreen()

    assert _read_raw_sgr_mouse_event(screen) == (35, 51, 57, "M")
    assert screen.timeout_values == [0, CURSES_POLL_TIMEOUT_MS]


def test_tui_sgr_left_click_opens_symbol(monkeypatch):
    import tradecat_terminal.tui as tui_module

    rows = [
        {"row_index": 2, "values": {"A": "排名", "B": "交易对"}},
        {"row_index": 3, "values": {"A": "1", "B": "ETH"}},
    ]
    viewport = _render_rows_table_viewport(rows, columns=["A", "B"])
    link_spans = _symbol_link_spans(rows, viewport["columns"], viewport["widths"])
    opened = []
    monkeypatch.setattr(tui_module, "_open_url", lambda url: opened.append(url) or (True, url))
    state = {"data_start_y": 10, "selected_row_offset": 0, "visible_rows": rows, "link_spans": link_spans}

    assert _handle_sgr_mouse_payload(state, 0, link_spans[1]["start"], 11, "M") is True
    assert state["selected_row_offset"] == 1
    assert opened == ["https://www.binance.com/zh-CN/futures/ETHUSDT?type=perpetual"]


def test_tui_fetch_timeout_defaults_to_short_live_timeout(monkeypatch):
    monkeypatch.delenv("TRADECAT_TERMINAL_TUI_FETCH_TIMEOUT", raising=False)
    monkeypatch.delenv("TRADECAT_TERMINAL_EVENT_STREAM_TUI_FETCH_TIMEOUT", raising=False)

    assert _resolve_fetch_timeout(None) == 2.0
    assert _resolve_fetch_timeout(None, "event_stream", 1.5) == 1.0
    assert _resolve_fetch_timeout(None, "market_snapshot", 10.0) == 2.0

    monkeypatch.setenv("TRADECAT_TERMINAL_TUI_FETCH_TIMEOUT", "0.1")
    assert _resolve_fetch_timeout(None, "event_stream", 1.5) == 0.5

    monkeypatch.setenv("TRADECAT_TERMINAL_TUI_FETCH_TIMEOUT", "3.5")
    assert _resolve_fetch_timeout(None, "event_stream", 1.5) == 1.5

    monkeypatch.setenv("TRADECAT_TERMINAL_EVENT_STREAM_TUI_FETCH_TIMEOUT", "0.8")
    assert _resolve_fetch_timeout(None, "event_stream", 1.5) == 0.8
    assert _resolve_fetch_timeout(4.0, "event_stream", 1.5) == 1.5


def test_tui_probe_interval_is_dataset_specific(monkeypatch):
    monkeypatch.delenv("TRADECAT_TERMINAL_TUI_PROBE_INTERVAL", raising=False)
    monkeypatch.delenv("TRADECAT_TERMINAL_EVENT_STREAM_TUI_PROBE_INTERVAL", raising=False)

    assert _resolve_probe_interval(None, "event_stream") == 1.5
    assert _resolve_probe_interval(None, "market_snapshot") == 10.0

    monkeypatch.setenv("TRADECAT_TERMINAL_TUI_PROBE_INTERVAL", "3")
    assert _resolve_probe_interval(None, "event_stream") == 3.0

    monkeypatch.setenv("TRADECAT_TERMINAL_EVENT_STREAM_TUI_PROBE_INTERVAL", "2")
    assert _resolve_probe_interval(None, "event_stream") == 2.0

    assert _resolve_probe_interval(4, "event_stream") == 4.0


def test_tui_probe_backoff_and_state_label_for_high_frequency_stream():
    state = {
        "datasets": [{"dataset_key": "event_stream"}],
        "dataset_index": 0,
        "live": True,
        "last_probe_at": 0.0,
        "consecutive_probe_failures": 0,
    }

    assert _effective_probe_interval(1.5, 0) == 1.5
    assert _effective_probe_interval(1.5, 1) == 3.0
    assert _effective_probe_interval(1.5, 2) == 5.0
    assert _effective_probe_interval(1.5, 3) == 15.0

    _update_probe_tuning_state(state, None)
    assert state["base_probe_interval_seconds"] == 1.5
    assert state["effective_probe_interval_seconds"] == 1.5
    assert state["current_fetch_timeout_seconds"] == 1.0

    _record_probe_result(state, {"ok": False, "status": "error", "error": "timeout"})
    _update_probe_tuning_state(state, None)

    label = _probe_state_label(state)
    assert state["consecutive_probe_failures"] == 1
    assert state["effective_probe_interval_seconds"] == 3.0
    assert "interval=3s(base=1.5s)" in label
    assert "timeout=1s" in label
    assert "fail=1" in label

    _record_probe_result(state, {"ok": True, "status": "unchanged"})
    _update_probe_tuning_state(state, None)
    assert state["consecutive_probe_failures"] == 0
    assert state["effective_probe_interval_seconds"] == 1.5


def test_tui_background_probe_does_not_block_main_thread(monkeypatch, tmp_path):
    import tradecat_terminal.tui as tui_module

    results: queue.Queue[dict] = queue.Queue()
    cache_dir = tmp_path / "cache"
    state = {
        "datasets": [{"dataset_key": "event_stream"}],
        "dataset_index": 0,
        "batch_index": 0,
        "live": True,
        "probe_generation": 0,
        "probe_inflight": False,
        "current_fetch_timeout_seconds": 1.0,
        "consecutive_probe_failures": 0,
    }
    monkeypatch.setattr(
        tui_module,
        "_probe_latest",
        lambda path, *, dataset_key, fetch_timeout=None: {
            "ok": True,
            "status": "unchanged",
            "changed": False,
            "wrote": False,
        },
    )

    assert _start_probe_thread(cache_dir, state, results) is True
    assert state["probe_inflight"] is True
    item = results.get(timeout=1)
    results.put(item)

    assert _drain_probe_results(state, results) is True
    assert state["probe_inflight"] is False
    assert state["last_probe_status"] == "unchanged"


def test_tui_background_probe_keeps_non_focused_taps_fresh(monkeypatch, tmp_path):
    import tradecat_terminal.tui as tui_module

    results: queue.Queue[dict] = queue.Queue()
    cache_dir = tmp_path / "cache"
    calls = []
    state = {
        "datasets": [
            {"dataset_key": "event_stream"},
            {"dataset_key": "market_snapshot"},
            {"dataset_key": "anomaly_panel"},
        ],
        "dataset_index": 0,
        "batch_index": 0,
        "live": True,
        "background_probe_enabled": True,
        "background_probe_jobs": {},
    }

    def fake_probe(path, *, dataset_key, fetch_timeout=None):
        calls.append((path, dataset_key, fetch_timeout))
        return {
            "ok": True,
            "status": "unchanged",
            "changed": False,
            "wrote": False,
            "content_hash": dataset_key,
        }

    monkeypatch.setattr(tui_module, "_probe_latest", fake_probe)

    assert _maybe_probe_background(cache_dir, state, results) is True
    item_1 = results.get(timeout=1)
    item_2 = results.get(timeout=1)
    seen = {item_1["dataset_key"], item_2["dataset_key"]}

    assert seen == {"market_snapshot", "anomaly_panel"}
    assert {call[1] for call in calls} == {"market_snapshot", "anomaly_panel"}
    assert all(state["background_probe_jobs"][key]["inflight"] is True for key in seen)

    results.put(item_1)
    results.put(item_2)
    assert _drain_probe_results(state, results) is False
    assert all(state["background_probe_jobs"][key]["inflight"] is False for key in seen)


def test_tui_background_probe_interval_is_dataset_specific(monkeypatch):
    monkeypatch.delenv("TRADECAT_TERMINAL_TUI_BACKGROUND_PROBE_INTERVAL", raising=False)
    monkeypatch.delenv("TRADECAT_TERMINAL_EVENT_STREAM_TUI_BACKGROUND_PROBE_INTERVAL", raising=False)

    assert _background_probe_interval("event_stream") == 10.0
    assert _background_probe_interval("market_snapshot") == 60.0
    assert _background_probe_interval("event_stream", consecutive_failures=1) == 10.0

    monkeypatch.setenv("TRADECAT_TERMINAL_TUI_BACKGROUND_PROBE_INTERVAL", "30")
    assert _background_probe_interval("market_snapshot") == 30.0

    monkeypatch.setenv("TRADECAT_TERMINAL_EVENT_STREAM_TUI_BACKGROUND_PROBE_INTERVAL", "5")
    assert _background_probe_interval("event_stream") == 5.0


def test_tui_ignores_background_probe_result_from_previous_generation():
    results: queue.Queue[dict] = queue.Queue()
    state = {
        "datasets": [{"dataset_key": "event_stream"}],
        "dataset_index": 0,
        "probe_generation": 2,
        "probe_inflight": False,
    }
    results.put(
        {
            "dataset_key": "event_stream",
            "generation": 1,
            "result": {"ok": True, "status": "written", "changed": True, "wrote": True},
        }
    )

    assert _drain_probe_results(state, results) is False
    assert "last_probe_status" not in state


def test_tui_plain_mode_does_not_probe_before_render(monkeypatch, tmp_path):
    import tradecat_terminal.tui as tui_module

    calls = []
    monkeypatch.setattr(tui_module, "_probe_latest", lambda *args, **kwargs: calls.append((args, kwargs)))

    output = run_tui(tmp_path / "cache", interactive=False, live=True, lang="zh")

    assert "暂无本地快照缓存" in output
    assert calls == []


def test_tui_without_curses_falls_back_to_plain(monkeypatch, tmp_path):
    import tradecat_terminal.tui as tui_module

    calls = []
    monkeypatch.setattr(tui_module, "curses", None)
    monkeypatch.setattr(tui_module, "_probe_latest", lambda *args, **kwargs: calls.append((args, kwargs)))

    output = run_tui(tmp_path / "cache", interactive=True, live=True, lang="zh")

    assert "当前 Python 环境不支持 curses" in output
    assert "已自动切换为 Rich 静态文本模式" in output
    assert "暂无本地快照缓存" in output
    assert calls == []


def test_tui_windows_native_defaults_to_plain(monkeypatch, tmp_path):
    import tradecat_terminal.tui as tui_module

    calls = []
    monkeypatch.setattr(tui_module.sys, "platform", "win32")
    monkeypatch.delenv("TRADECAT_TERMINAL_FORCE_CURSES", raising=False)
    monkeypatch.delenv("TRADECAT_TERMINAL_ALLOW_WINDOWS_CURSES", raising=False)
    monkeypatch.delenv("WT_SESSION", raising=False)
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    monkeypatch.delenv("ALACRITTY_WINDOW_ID", raising=False)
    monkeypatch.delenv("KITTY_WINDOW_ID", raising=False)
    monkeypatch.setattr(tui_module, "_probe_latest", lambda *args, **kwargs: calls.append((args, kwargs)))

    output = run_tui(tmp_path / "cache", interactive=True, live=True, lang="zh")

    assert "Windows 原生终端的 curses 渲染不稳定" in output
    assert "已自动切换为 Rich 静态文本模式" in output
    assert calls == []


def test_tui_windows_terminal_uses_curses_when_available(monkeypatch, tmp_path):
    import tradecat_terminal.tui as tui_module

    calls = []
    monkeypatch.setattr(tui_module.sys, "platform", "win32")
    monkeypatch.delenv("TRADECAT_TERMINAL_FORCE_CURSES", raising=False)
    monkeypatch.delenv("TRADECAT_TERMINAL_FORCE_PLAIN", raising=False)
    monkeypatch.setenv("WT_SESSION", "stable")
    monkeypatch.setattr(tui_module, "_probe_latest", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(tui_module.curses, "wrapper", lambda callback: None)

    output = run_tui(tmp_path / "cache", interactive=True, live=True, lang="zh")

    assert output is None
    assert calls == []


def test_tui_windows_native_can_allow_curses(monkeypatch, tmp_path):
    import tradecat_terminal.tui as tui_module

    calls = []
    monkeypatch.setattr(tui_module.sys, "platform", "win32")
    monkeypatch.delenv("TRADECAT_TERMINAL_FORCE_CURSES", raising=False)
    monkeypatch.setenv("TRADECAT_TERMINAL_ALLOW_WINDOWS_CURSES", "1")
    monkeypatch.setattr(tui_module, "_probe_latest", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(tui_module.curses, "wrapper", lambda callback: None)

    output = run_tui(tmp_path / "cache", interactive=True, live=True, lang="zh")

    assert output is None
    assert calls == []


def test_tui_windows_native_can_force_curses(monkeypatch, tmp_path):
    import tradecat_terminal.tui as tui_module

    calls = []
    monkeypatch.setattr(tui_module.sys, "platform", "win32")
    monkeypatch.setenv("TRADECAT_TERMINAL_FORCE_CURSES", "1")
    monkeypatch.setattr(tui_module, "_probe_latest", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(tui_module.curses, "wrapper", lambda callback: None)

    output = run_tui(tmp_path / "cache", interactive=True, live=True, lang="zh")

    assert output is None
    assert calls == []


def test_tui_unknown_ssh_terminal_defaults_to_plain(monkeypatch, tmp_path):
    import tradecat_terminal.tui as tui_module

    calls = []
    monkeypatch.setattr(tui_module.sys, "platform", "linux")
    monkeypatch.setenv("SSH_CONNECTION", "1.1.1.1 1 2.2.2.2 2")
    monkeypatch.delenv("WT_SESSION", raising=False)
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    monkeypatch.delenv("VTE_VERSION", raising=False)
    monkeypatch.delenv("KONSOLE_VERSION", raising=False)
    monkeypatch.delenv("ALACRITTY_WINDOW_ID", raising=False)
    monkeypatch.delenv("KITTY_WINDOW_ID", raising=False)
    monkeypatch.delenv("TRADECAT_TERMINAL_FORCE_CURSES", raising=False)
    monkeypatch.setattr(tui_module, "_probe_latest", lambda *args, **kwargs: calls.append((args, kwargs)))

    output = run_tui(tmp_path / "cache", interactive=True, live=True)

    assert "远程 Web/SSH 终端的 curses 宽字符渲染不稳定" in output
    assert calls == []


def test_tui_known_stable_ssh_terminal_can_use_curses(monkeypatch, tmp_path):
    import tradecat_terminal.tui as tui_module

    calls = []
    monkeypatch.setattr(tui_module.sys, "platform", "linux")
    monkeypatch.setenv("SSH_CONNECTION", "1.1.1.1 1 2.2.2.2 2")
    monkeypatch.setenv("WT_SESSION", "stable")
    monkeypatch.setattr(tui_module, "_probe_latest", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(tui_module.curses, "wrapper", lambda callback: None)

    output = run_tui(tmp_path / "cache", interactive=True, live=True)

    assert output is None
    assert calls == []


def test_tui_live_startup_is_cache_first_without_blocking_probe(monkeypatch, tmp_path):
    import tradecat_terminal.tui as tui_module

    cache_dir = tmp_path / "cache"
    calls = []
    monkeypatch.setattr(tui_module, "_probe_latest", lambda path, *, dataset_key, fetch_timeout=None: calls.append((path, dataset_key, fetch_timeout)) or {"ok": True})
    monkeypatch.setattr(tui_module.curses, "wrapper", lambda callback: None)

    output = run_tui(cache_dir, interactive=True, live=True)

    assert output is None
    assert calls == []
    assert _resolve_startup_dataset_key(cache_dir, None) == "event_stream"
