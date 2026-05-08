from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tradecat_terminal.sheets import RemoteCsvError, fetch_csv_body

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _Response:
    status = 200
    data = b"\xff\xfe\x00"


def test_transport_classifies_timeout(monkeypatch):
    import tradecat_terminal.sheets as sheets

    def fake_request(*args, **kwargs):
        raise sheets.ReadTimeoutError(None, "https://example.invalid", "timed out")

    class FakePool:
        def __init__(self, *args, **kwargs):
            pass

        request = staticmethod(fake_request)

    monkeypatch.setattr(sheets.urllib3, "PoolManager", FakePool)

    with pytest.raises(RemoteCsvError) as error:
        fetch_csv_body("https://example.invalid/export.csv", timeout=1)

    assert error.value.code == "remote_timeout"
    assert error.value.kind == "timeout"
    assert error.value.retryable is True


def test_transport_classifies_http_status(monkeypatch):
    import tradecat_terminal.sheets as sheets

    class Response:
        status = 429
        data = b"rate limited"

    class FakePool:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(sheets.urllib3, "PoolManager", FakePool)

    with pytest.raises(RemoteCsvError) as error:
        fetch_csv_body("https://example.invalid/export.csv", timeout=1)

    assert error.value.code == "remote_http_status"
    assert error.value.kind == "http"
    assert error.value.status == 429
    assert error.value.retryable is True


def test_transport_classifies_decode_error(monkeypatch):
    import tradecat_terminal.sheets as sheets

    class FakePool:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            return _Response()

    monkeypatch.setattr(sheets.urllib3, "PoolManager", FakePool)

    with pytest.raises(RemoteCsvError) as error:
        fetch_csv_body("https://example.invalid/export.csv", timeout=1)

    assert error.value.code == "remote_decode_error"
    assert error.value.kind == "decode"
    assert error.value.retryable is False


def test_request_py_json_contract_uses_local_registry_file():
    registry = (PROJECT_ROOT / "src" / "tradecat_terminal" / "dataset_registry.json").resolve()
    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "request.py"),
            "--datasets",
            "--format",
            "json",
            "--registry-url",
            registry.as_uri(),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["schema"] == "tradecat.request_dataset_list.v1"
    assert payload["schema_version"] == "1.0.0"
    assert {item["key"] for item in payload["datasets"]} == {
        "market_snapshot",
        "anomaly_panel",
        "market_stats",
        "event_stream",
    }


def test_request_py_json_error_contract_for_bad_dataset():
    registry = (PROJECT_ROOT / "src" / "tradecat_terminal" / "dataset_registry.json").resolve()
    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "request.py"),
            "missing",
            "--format",
            "json",
            "--registry-url",
            registry.as_uri(),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["schema"] == "tradecat.request_result.v1"
    assert payload["ok"] is False
    assert payload["error"]["kind"] == "validation"


def test_request_error_classifier_is_stable():
    request_py = PROJECT_ROOT / "scripts" / "request.py"
    source = request_py.read_text(encoding="utf-8")

    assert "HTTPError" in source
    assert "URLError" in source
    assert "REQUEST_SCHEMA" in source
