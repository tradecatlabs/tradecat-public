from __future__ import annotations

import json

from tradecat_terminal import cli
from tradecat_terminal.cache import write_dataset_body
from tradecat_terminal.registry import get_dataset


def _last_json(captured: str) -> dict:
    return json.loads(captured.strip().splitlines()[-1])


def test_export_rejects_negative_limit_with_stable_json_error(tmp_path, capsys):
    cache_dir = tmp_path / "cache"
    write_dataset_body(
        cache_dir,
        get_dataset("event_stream"),
        "时间(北京),内容\n2026-05-11 09:00:00,hello\n",
    )

    exit_code = cli.main(["--cache-dir", str(cache_dir), "export", "event_stream", "--format", "json", "--limit", "-1"])
    payload = _last_json(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["schema"] == "tradecat.dataset_view.v1"
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_export_request"
    assert "--limit" in payload["error"]["message"]


def test_prune_rejects_negative_max_snapshots_with_stable_json_error(tmp_path, capsys):
    exit_code = cli.main(["--cache-dir", str(tmp_path / "cache"), "prune", "--max-snapshots", "-1", "--json"])
    payload = _last_json(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["schema"] == "tradecat.prune_result.v1"
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_prune_request"
    assert "--max-snapshots" in payload["error"]["message"]


def test_prune_rejects_invalid_env_max_snapshots_with_stable_json_error(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("TRADECAT_CACHE_MAX_SNAPSHOTS", "bad")

    exit_code = cli.main(["--cache-dir", str(tmp_path / "cache"), "prune", "--json"])
    payload = _last_json(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["schema"] == "tradecat.prune_result.v1"
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_prune_request"
    assert "TRADECAT_CACHE_MAX_SNAPSHOTS" in payload["error"]["message"]


def test_watch_rejects_non_positive_interval_before_starting_loop(tmp_path, capsys):
    exit_code = cli.main(
        [
            "--cache-dir",
            str(tmp_path / "cache"),
            "watch",
            "--json",
            "--no-write",
            "--interval",
            "0",
            "--max-cycles",
            "1",
        ]
    )
    payload = _last_json(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["schema"] == "tradecat.watch_cycle.v1"
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_runtime_configuration"
    assert "--interval" in payload["error"]["message"]


def test_watch_rejects_non_positive_max_cycles_before_starting_loop(tmp_path, capsys):
    exit_code = cli.main(
        [
            "--cache-dir",
            str(tmp_path / "cache"),
            "watch",
            "--json",
            "--no-write",
            "--interval",
            "1",
            "--max-cycles",
            "0",
        ]
    )
    payload = _last_json(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["schema"] == "tradecat.watch_cycle.v1"
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_runtime_configuration"
    assert "--max-cycles" in payload["error"]["message"]
