from __future__ import annotations

import json

from tradecat_terminal import cli
from tradecat_terminal.cache import write_dataset_body
from tradecat_terminal.features import build_feature_bundle
from tradecat_terminal.registry import get_dataset


def test_feature_bundle_builds_symbol_facts_from_analysis_report(tmp_path):
    cache_dir = tmp_path / "cache"
    _seed_feature_cache(cache_dir)

    payload = build_feature_bundle(cache_dir, analysis_window="24h", symbol_limit=5)

    assert payload["ok"] is True
    assert payload["feature_window"]["source_schema"] == "tradecat.analysis_report.v1"
    assert payload["symbols"][0]["symbol"] == "BTCUSDT"
    assert {feature["name"] for feature in payload["symbols"][0]["features"]} == {
        "anomaly_panel.presence",
        "event_stream.activity_available",
        "market_stats.context_available",
    }
    assert payload["symbols"][0]["confidence"] == "observed"
    assert payload["symbols"][0]["evidence_ids"]
    assert "feature_bundle_not_signal" in {item["code"] for item in payload["risk_flags"]}


def test_feature_bundle_empty_cache_returns_stable_error(tmp_path):
    payload = build_feature_bundle(tmp_path / "empty-cache")

    assert payload["ok"] is False
    assert payload["error"]["code"] == "empty_feature_cache"
    assert payload["error"]["kind"] == "local_state"
    assert payload["symbols"] == []


def test_feature_bundle_respects_symbol_limit(tmp_path):
    cache_dir = tmp_path / "cache"
    _seed_feature_cache(cache_dir)

    payload = build_feature_bundle(cache_dir, symbol_limit=1)

    assert payload["ok"] is True
    assert [item["symbol"] for item in payload["symbols"]] == ["BTCUSDT"]


def test_feature_bundle_does_not_invent_context_features_when_context_cache_missing(tmp_path):
    cache_dir = tmp_path / "cache"
    write_dataset_body(
        cache_dir,
        get_dataset("anomaly_panel"),
        "榜单,序号,交易对\n异动榜,1,BTCUSDT\n",
    )

    payload = build_feature_bundle(cache_dir)

    assert payload["ok"] is True
    assert {feature["name"] for feature in payload["symbols"][0]["features"]} == {"anomaly_panel.presence"}
    assert payload["symbols"][0]["source_dataset_keys"] == ["anomaly_panel"]
    assert "partial_analysis_cache" in {item["code"] for item in payload["risk_flags"]}


def test_feature_bundle_does_not_infer_symbol_from_event_text(tmp_path):
    cache_dir = tmp_path / "cache"
    write_dataset_body(
        cache_dir,
        get_dataset("event_stream"),
        "时间(北京),内容\n2026-05-11 09:00:00,BTCUSDT 出现公开事件\n",
    )

    payload = build_feature_bundle(cache_dir)

    assert payload["ok"] is False
    assert payload["symbols"] == []
    assert payload["error"]["code"] == "empty_feature_cache"


def test_feature_bundle_does_not_fetch_network(tmp_path, monkeypatch):
    import tradecat_terminal.cache as cache_module

    def fail_fetch(*args, **kwargs):
        raise AssertionError("features must not fetch network data")

    cache_dir = tmp_path / "cache"
    _seed_feature_cache(cache_dir)
    monkeypatch.setattr(cache_module, "fetch_csv_body", fail_fetch)

    payload = build_feature_bundle(cache_dir)

    assert payload["ok"] is True
    assert payload["symbols"][0]["symbol"] == "BTCUSDT"


def test_features_cli_json_contract(tmp_path, capsys):
    cache_dir = tmp_path / "cache"
    _seed_feature_cache(cache_dir)

    assert cli.main(["--cache-dir", str(cache_dir), "features", "--json", "--limit", "5"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema"] == "tradecat.feature_bundle.v1"
    assert payload["schema_version"] == "1.0.0"
    assert payload["ok"] is True
    assert payload["symbols"][0]["symbol"] == "BTCUSDT"


def test_features_cli_invalid_request_has_stable_error(tmp_path, capsys):
    assert cli.main(["--cache-dir", str(tmp_path / "cache"), "features", "--json", "--limit", "0"]) == 2
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema"] == "tradecat.feature_bundle.v1"
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_feature_request"


def test_features_cli_unexpected_exception_has_stable_error(tmp_path, capsys, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "build_feature_bundle", boom)

    assert cli.main(["--cache-dir", str(tmp_path / "cache"), "features", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema"] == "tradecat.feature_bundle.v1"
    assert payload["ok"] is False
    assert payload["error"]["code"] == "local_runtime_error"
    assert payload["error"]["message"] == "boom"


def _seed_feature_cache(cache_dir):
    write_dataset_body(
        cache_dir,
        get_dataset("event_stream"),
        "数据源,alternative\n时间(北京),内容\n2026-05-11 09:00:00,资金费率事件\n",
    )
    write_dataset_body(
        cache_dir,
        get_dataset("anomaly_panel"),
        "数据源,market\n榜单,序号,交易对\n异动榜,1,BTCUSDT\n异动榜,2,ETHUSDT\n",
    )
    write_dataset_body(
        cache_dir,
        get_dataset("market_stats"),
        "数据源,market\n窗口,覆盖合约数,交易对口径\n24h,200,USDT perpetual\n",
    )
