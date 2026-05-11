from __future__ import annotations

import json

from tradecat_terminal import cli
from tradecat_terminal.cache import write_dataset_body
from tradecat_terminal.registry import get_dataset


def _last_json(captured: str) -> dict:
    text = captured.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(text.splitlines()[-1])


def assert_contract(payload: dict, schema: str) -> None:
    assert payload["schema"] == schema
    assert payload["schema_version"] == "1.0.0"


def test_readonly_cli_json_contracts(tmp_path, capsys, monkeypatch):
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("TRADECAT_SETTINGS_PATH", str(tmp_path / "settings.json"))

    assert cli.main(["--cache-dir", str(cache_dir), "status", "--json"]) == 0
    assert_contract(_last_json(capsys.readouterr().out), "tradecat.status.v1")

    assert cli.main(["--cache-dir", str(cache_dir), "datasets", "--json"]) == 0
    datasets = _last_json(capsys.readouterr().out)
    assert_contract(datasets, "tradecat.dataset_list.v1")
    assert datasets["datasets"][0]["key"] == "market_snapshot"

    assert cli.main(["--cache-dir", str(cache_dir), "path", "event_stream", "--json"]) == 0
    assert_contract(_last_json(capsys.readouterr().out), "tradecat.path_map.v1")

    assert cli.main(["config", "show", "--json"]) == 0
    assert_contract(_last_json(capsys.readouterr().out), "tradecat.config.v1")


def test_mutating_cli_json_contracts(tmp_path, capsys, monkeypatch):
    cache_dir = tmp_path / "cache"

    import tradecat_terminal.cache as cache_module

    def fake_fetch_csv_body(url, timeout=30.0):
        return "https://dexscreener.com/x\n数据源,market\n排名,交易对,价格\n1,BTCUSDT,100\n"

    monkeypatch.setattr(cache_module, "fetch_csv_body", fake_fetch_csv_body)

    assert cli.main(["--cache-dir", str(cache_dir), "init", "--json"]) == 0
    assert_contract(_last_json(capsys.readouterr().out), "tradecat.init.v1")

    assert cli.main(["--cache-dir", str(cache_dir), "sync", "market_snapshot", "--json"]) == 0
    assert_contract(_last_json(capsys.readouterr().out), "tradecat.sync_result.v1")

    assert cli.main(["--cache-dir", str(cache_dir), "probe", "event_stream", "--no-write", "--json"]) == 0
    assert_contract(_last_json(capsys.readouterr().out), "tradecat.probe_result.v1")

    assert cli.main(["--cache-dir", str(cache_dir), "probe", "--no-write", "--json"]) == 0
    assert_contract(_last_json(capsys.readouterr().out), "tradecat.probe_results.v1")

    assert cli.main(["--cache-dir", str(cache_dir), "prune", "--json"]) == 0
    assert_contract(_last_json(capsys.readouterr().out), "tradecat.prune_result.v1")


def test_export_and_bundle_json_contracts(tmp_path, capsys):
    cache_dir = tmp_path / "cache"
    write_dataset_body(
        cache_dir,
        get_dataset("event_stream"),
        "时间(北京),内容\n2026-05-08 10:00:00,hello\n",
    )
    write_dataset_body(
        cache_dir,
        get_dataset("anomaly_panel"),
        "榜单,序号,交易对\n异动榜,1,BTCUSDT\n",
    )
    write_dataset_body(
        cache_dir,
        get_dataset("market_stats"),
        "窗口,覆盖合约数,交易对口径\n24h,200,USDT perpetual\n",
    )

    assert cli.main(["--cache-dir", str(cache_dir), "export", "event_stream", "--format", "json", "--limit", "1"]) == 0
    assert_contract(_last_json(capsys.readouterr().out), "tradecat.dataset_view.v1")

    assert cli.main(["--cache-dir", str(cache_dir), "analyze", "--json"]) == 0
    assert_contract(_last_json(capsys.readouterr().out), "tradecat.analysis_report.v1")

    assert cli.main(["--cache-dir", str(cache_dir), "features", "--json"]) == 0
    assert_contract(_last_json(capsys.readouterr().out), "tradecat.feature_bundle.v1")

    assert cli.main(["--cache-dir", str(cache_dir), "doctor", "--bundle", "-"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "tradecat.support_bundle.v1"
    assert payload["schema_version"] == "1.0.0"


def test_json_errors_have_stable_error_object(tmp_path, capsys):
    assert cli.main(["--cache-dir", str(tmp_path / "cache"), "path", "missing", "--json"]) == 2
    payload = _last_json(capsys.readouterr().out)

    assert payload["schema"] == "tradecat.path_map.v1"
    assert payload["ok"] is False
    assert payload["error"] == {
        "code": "invalid_dataset_key",
        "kind": "validation",
        "message": "未知 dataset_key: missing; 可用值: anomaly_panel, event_stream, market_snapshot, market_stats",
        "hint": "先执行 tradecat datasets --json 查看可用 dataset_key。",
        "retryable": False,
    }
