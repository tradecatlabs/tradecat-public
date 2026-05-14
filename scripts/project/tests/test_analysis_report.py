from __future__ import annotations

import json

from tradecat_terminal import cli
from tradecat_terminal.analysis import build_analysis_report
from tradecat_terminal.cache import write_dataset_body
from tradecat_terminal.registry import get_dataset


def test_analysis_report_builds_observation_payload_from_local_cache(tmp_path):
    cache_dir = tmp_path / "cache"
    _seed_analysis_cache(cache_dir)

    payload = build_analysis_report(cache_dir, analysis_window="24h", candidate_limit=5)

    assert payload["ok"] is True
    assert payload["analysis_window"]["mode"] == "latest_cached"
    assert {item["dataset_key"] for item in payload["dataset_freshness"]} == {
        "event_stream",
        "anomaly_panel",
        "market_stats",
    }
    assert {item["id"] for item in payload["observations"]} == {
        "event_stream.activity",
        "anomaly_panel.candidates",
        "market_stats.context",
    }
    assert payload["candidate_symbols"][0]["symbol"] == "BTCUSDT"
    assert payload["candidate_symbols"][0]["confidence"] == "observed"
    assert payload["evidence"]
    assert "analysis_not_trading_advice" in {item["code"] for item in payload["risk_flags"]}


def test_analysis_report_empty_cache_returns_stable_error(tmp_path):
    payload = build_analysis_report(tmp_path / "empty-cache")

    assert payload["ok"] is False
    assert payload["error"]["code"] == "empty_analysis_cache"
    assert payload["error"]["kind"] == "local_state"
    assert payload["dataset_freshness"][0]["cache_state"] == "empty"


def test_analysis_report_limits_and_deduplicates_candidate_symbols(tmp_path):
    cache_dir = tmp_path / "cache"
    write_dataset_body(
        cache_dir,
        get_dataset("anomaly_panel"),
        "榜单,序号,交易对\n异动榜,1,BTCUSDT\n异动榜,2,btcusdt\n异动榜,3,ETHUSDT\n异动榜,4,SOLUSDT\n",
    )

    payload = build_analysis_report(cache_dir, candidate_limit=2)

    assert payload["ok"] is True
    assert [item["symbol"] for item in payload["candidate_symbols"]] == ["BTCUSDT", "ETHUSDT"]
    assert payload["candidate_symbols"][0]["evidence_ids"] == ["anomaly_panel:row:2", "anomaly_panel:row:3"]


def test_analysis_report_does_not_infer_symbols_from_event_text(tmp_path):
    cache_dir = tmp_path / "cache"
    write_dataset_body(
        cache_dir,
        get_dataset("event_stream"),
        "时间(北京),内容\n2026-05-11 09:00:00,BTCUSDT 出现公开事件\n",
    )

    payload = build_analysis_report(cache_dir)

    assert payload["ok"] is True
    assert payload["candidate_symbols"] == []
    assert "no_candidate_symbols" in {item["code"] for item in payload["risk_flags"]}


def test_analyze_cli_json_contract(tmp_path, capsys):
    cache_dir = tmp_path / "cache"
    _seed_analysis_cache(cache_dir)

    assert cli.main(["--cache-dir", str(cache_dir), "analyze", "--json", "--limit", "5"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema"] == "tradecat.analysis_report.v1"
    assert payload["schema_version"] == "1.0.0"
    assert payload["ok"] is True
    assert payload["candidate_symbols"][0]["symbol"] == "BTCUSDT"


def test_analyze_cli_invalid_request_has_stable_error(tmp_path, capsys):
    assert cli.main(["--cache-dir", str(tmp_path / "cache"), "analyze", "--json", "--window", "bad"]) == 2
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema"] == "tradecat.analysis_report.v1"
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_analysis_request"


def _seed_analysis_cache(cache_dir):
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
