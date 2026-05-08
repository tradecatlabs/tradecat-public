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


def test_doctor_parameter_error_returns_nonzero_json(tmp_path, capsys):
    exit_code = cli.main(["--cache-dir", str(tmp_path / "cache"), "doctor", "--timeout", "5", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["schema"] == "tradecat.doctor.v1"
    assert payload["error"]["code"] == "invalid_timeout_option"
