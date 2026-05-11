from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tradecat_terminal import cli

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = PROJECT_ROOT.parents[1]


def _python_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    return env


def test_python_module_propagates_main_exit_code():
    result = subprocess.run(
        [sys.executable, "-m", "tradecat_terminal", "sync", "invalid_dataset", "--json"],
        cwd=PROJECT_ROOT,
        env=_python_env(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["schema"] == "tradecat.sync_result.v1"
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_dataset_key"


def test_root_wrapper_preserves_module_exit_code():
    result = subprocess.run(
        ["bash", "scripts/run-tradecat.sh", "sync", "invalid_dataset", "--json"],
        cwd=SKILL_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["error"]["code"] == "invalid_dataset_key"


def test_json_business_failure_returns_nonzero(tmp_path, monkeypatch, capsys):
    def fake_sync_dataset(cache_dir, dataset_key, *, fetch_timeout=None):
        return {
            "ok": False,
            "dataset_key": dataset_key,
            "status": "error",
            "error": "remote request timed out",
            "error_info": {
                "code": "remote_timeout",
                "kind": "timeout",
                "message": "remote request timed out",
                "hint": "稍后重试。",
                "retryable": True,
            },
        }

    monkeypatch.setattr(cli, "sync_dataset", fake_sync_dataset)

    exit_code = cli.main(["--cache-dir", str(tmp_path / "cache"), "sync", "event_stream", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "remote_timeout"


def test_sync_configuration_value_error_is_not_misclassified_as_dataset_error(tmp_path, monkeypatch, capsys):
    import tradecat_terminal.cache as cache_module

    def fake_fetch_csv_body(url, timeout=30.0):
        return "https://dexscreener.com/x\n数据源,market\n排名,交易对,价格\n1,BTCUSDT,100\n"

    monkeypatch.setattr(cache_module, "fetch_csv_body", fake_fetch_csv_body)
    monkeypatch.setenv("TRADECAT_CACHE_COMPRESSION", "bad")

    exit_code = cli.main(["--cache-dir", str(tmp_path / "cache"), "sync", "market_snapshot", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["schema"] == "tradecat.sync_result.v1"
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_runtime_configuration"
    assert payload["error"]["kind"] == "configuration"
    assert "TRADECAT_CACHE_COMPRESSION" in payload["error"]["message"]
    assert payload["error"]["code"] != "invalid_dataset_key"


def test_sync_all_configuration_value_error_uses_configuration_code(tmp_path, monkeypatch, capsys):
    import tradecat_terminal.cache as cache_module

    def fake_fetch_csv_body(url, timeout=30.0):
        return "https://dexscreener.com/x\n数据源,market\n排名,交易对,价格\n1,BTCUSDT,100\n"

    monkeypatch.setattr(cache_module, "fetch_csv_body", fake_fetch_csv_body)
    monkeypatch.setenv("TRADECAT_CACHE_COMPRESSION", "bad")

    exit_code = cli.main(["--cache-dir", str(tmp_path / "cache"), "sync-all", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["schema"] == "tradecat.sync_results.v1"
    assert payload["ok"] is False
    assert {item["error"]["code"] for item in payload["results"]} == {"invalid_runtime_configuration"}


def test_sync_unexpected_exception_is_stable_json_error(tmp_path, monkeypatch, capsys):
    def broken_sync_dataset(cache_dir, dataset_key, *, fetch_timeout=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "sync_dataset", broken_sync_dataset)

    exit_code = cli.main(["--cache-dir", str(tmp_path / "cache"), "sync", "event_stream", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["schema"] == "tradecat.sync_result.v1"
    assert payload["ok"] is False
    assert payload["error"]["code"] == "local_runtime_error"
    assert payload["error"]["kind"] == "runtime"
    assert payload["error"]["message"] == "boom"


def test_doctor_parameter_error_returns_nonzero_json(tmp_path, capsys):
    exit_code = cli.main(["--cache-dir", str(tmp_path / "cache"), "doctor", "--timeout", "5", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["schema"] == "tradecat.doctor.v1"
    assert payload["error"]["code"] == "invalid_timeout_option"


def test_analyze_empty_cache_returns_nonzero_json(tmp_path, capsys):
    exit_code = cli.main(["--cache-dir", str(tmp_path / "cache"), "analyze", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["schema"] == "tradecat.analysis_report.v1"
    assert payload["ok"] is False
    assert payload["error"]["code"] == "empty_analysis_cache"


def test_features_empty_cache_returns_nonzero_json(tmp_path, capsys):
    exit_code = cli.main(["--cache-dir", str(tmp_path / "cache"), "features", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["schema"] == "tradecat.feature_bundle.v1"
    assert payload["ok"] is False
    assert payload["error"]["code"] == "empty_feature_cache"
