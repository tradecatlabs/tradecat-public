from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tradecat_terminal.sheets import RemoteCsvError, fetch_csv_body

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_request_module() -> object:
    spec = importlib.util.spec_from_file_location("tradecat_request_script", PROJECT_ROOT / "scripts" / "request.py")
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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
    monkeypatch.setattr(sheets.urllib3, "ProxyManager", FakePool)

    with pytest.raises(RemoteCsvError) as error:
        fetch_csv_body("https://example.invalid/export.csv", timeout=1)

    assert error.value.code == "remote_timeout"
    assert error.value.kind == "timeout"
    assert error.value.retryable is True


def test_transport_classifies_connect_failure(monkeypatch):
    import tradecat_terminal.sheets as sheets

    def fake_request(*args, **kwargs):
        raise sheets.NewConnectionError(None, "connection refused")

    class FakePool:
        def __init__(self, *args, **kwargs):
            pass

        request = staticmethod(fake_request)

    monkeypatch.setattr(sheets.urllib3, "PoolManager", FakePool)
    monkeypatch.setattr(sheets.urllib3, "ProxyManager", FakePool)

    with pytest.raises(RemoteCsvError) as error:
        fetch_csv_body("https://example.invalid/export.csv", timeout=1)

    assert error.value.code == "remote_dns_or_connect_error"
    assert error.value.kind == "network"
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
    monkeypatch.setattr(sheets.urllib3, "ProxyManager", FakePool)

    with pytest.raises(RemoteCsvError) as error:
        fetch_csv_body("https://example.invalid/export.csv", timeout=1)

    assert error.value.code == "remote_http_status"
    assert error.value.kind == "http"
    assert error.value.status == 429
    assert error.value.retryable is True


def test_transport_classifies_non_retryable_http_status(monkeypatch):
    import tradecat_terminal.sheets as sheets

    class Response:
        status = 403
        data = b"forbidden"

    class FakePool:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(sheets.urllib3, "PoolManager", FakePool)
    monkeypatch.setattr(sheets.urllib3, "ProxyManager", FakePool)

    with pytest.raises(RemoteCsvError) as error:
        fetch_csv_body("https://example.invalid/export.csv", timeout=1)

    assert error.value.code == "remote_http_status"
    assert error.value.kind == "http"
    assert error.value.status == 403
    assert error.value.retryable is False


def test_transport_classifies_decode_error(monkeypatch):
    import tradecat_terminal.sheets as sheets

    class FakePool:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            return _Response()

    monkeypatch.setattr(sheets.urllib3, "PoolManager", FakePool)
    monkeypatch.setattr(sheets.urllib3, "ProxyManager", FakePool)

    with pytest.raises(RemoteCsvError) as error:
        fetch_csv_body("https://example.invalid/export.csv", timeout=1)

    assert error.value.code == "remote_decode_error"
    assert error.value.kind == "decode"
    assert error.value.retryable is False


def test_parse_csv_rows_normalizes_blank_and_duplicate_headers():
    from tradecat_terminal.sheets import parse_csv_rows

    rows = parse_csv_rows("名称,名称,\nBTC,duplicate,blank-header-value\n")

    assert rows == [
        {
            "名称": "BTC",
            "名称_2": "duplicate",
            "column_3": "blank-header-value",
        }
    ]


def test_request_parser_reads_sectioned_anomaly_panel_rows():
    request = load_request_module()
    matrix = request.parse_matrix(
        '"https://dexscreener.com/x\\n数据源，异动面板",,,,,,\n'
        "5m 异动榜,序号,交易对,5m量变化率,5m额变化率,现持仓额\n"
        ",1,FF,-0.082%,4.866%,35965182.49\n"
        "15m 异动榜,序号,交易对,15m量变化率,15m额变化率,现持仓额\n"
        ",1,MORPHO,2.939%,0.854%,8882523.83\n"
        "1h 异动榜,序号,交易对,1h量变化率,1h额变化率,现持仓额\n"
        ",1,FIDA,7.918%,14.474%,9122768.65\n"
    )
    header_index = request.find_header_row_index(matrix)
    headers = request.table_headers(matrix, header_index)
    rows = request.data_rows(matrix, header_index, headers)

    assert "15m量变化率" in headers
    assert "1h额变化率" in headers
    assert [row["榜单"] for row in rows] == ["5m 异动榜", "15m 异动榜", "1h 异动榜"]
    assert rows[0]["交易对"] == "FF"
    assert rows[1]["15m量变化率"] == "2.939%"
    assert rows[2]["1h额变化率"] == "14.474%"


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
        "signal_flow",
        "event_stream",
    }


def test_request_py_defaults_to_repo_local_registry_file():
    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "request.py"),
            "--datasets",
            "--format",
            "json",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["schema"] == "tradecat.request_dataset_list.v1"
    assert {item["key"] for item in payload["datasets"]} == {
        "market_snapshot",
        "anomaly_panel",
        "market_stats",
        "signal_flow",
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
