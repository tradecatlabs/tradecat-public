from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from tradecat_terminal import cli
from tradecat_terminal.cache import write_dataset_body
from tradecat_terminal.registry import get_dataset

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = PROJECT_ROOT / "contracts"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "json_contract"
REQUEST_SCRIPT = PROJECT_ROOT / "scripts" / "request.py"
REQUEST_REGISTRY_URL = "https://example.local/tradecat-registry.json"
SHEET_CSV = "https://dexscreener.com/example\nrank,pair,price\n1,BTCUSDT,100\n"
EVENT_CSV = "time,content\n2026-05-10 10:00:00,hello\n"
REQUEST_REGISTRY = {
    "workbooks": {
        "main": {
            "spreadsheet_id": "sheet-id",
            "description": "test workbook",
        }
    },
    "datasets": {
        "event_stream": {
            "workbook_key": "main",
            "tab_name": "event_stream",
            "gid": "1",
            "description": "test dataset",
            "data_mode": "stream",
            "active": True,
        }
    },
}


def test_advertised_cli_payloads_validate_against_formal_schemas(tmp_path, capsys, monkeypatch):
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("TRADECAT_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.delenv("TRADECAT_CACHE_COMPRESSION", raising=False)

    import tradecat_terminal.cache as cache_module

    monkeypatch.setattr(cache_module, "fetch_csv_body", _fake_sheet_fetch)
    write_dataset_body(cache_dir, get_dataset("event_stream"), EVENT_CSV)

    payloads = [
        _run_cli_json(capsys, ["--cache-dir", str(cache_dir), "init", "--json"]),
        _run_cli_json(capsys, ["--cache-dir", str(cache_dir), "status", "--json"]),
        _run_cli_json(capsys, ["--cache-dir", str(cache_dir), "doctor", "--json"]),
        _run_cli_json(capsys, ["--cache-dir", str(cache_dir), "path", "event_stream", "--json"]),
        _run_cli_json(capsys, ["--cache-dir", str(cache_dir), "datasets", "--json"]),
        _run_cli_json(capsys, ["config", "show", "--json"]),
        _run_cli_json(capsys, ["--cache-dir", str(cache_dir), "sync", "market_snapshot", "--json"]),
        _run_cli_json(capsys, ["--cache-dir", str(cache_dir), "sync-all", "--json"]),
        _run_cli_json(capsys, ["--cache-dir", str(cache_dir), "probe", "event_stream", "--no-write", "--json"]),
        _run_cli_json(capsys, ["--cache-dir", str(cache_dir), "probe", "--no-write", "--json"]),
        _run_cli_json(capsys, ["--cache-dir", str(cache_dir), "prune", "--json"]),
        _run_cli_json(capsys, ["--cache-dir", str(cache_dir), "export", "event_stream", "--format", "json"]),
        _run_cli_json(capsys, ["--cache-dir", str(cache_dir), "doctor", "--bundle", "-"]),
    ]

    for payload in payloads:
        validate_payload(payload)


def test_request_script_payloads_validate_against_formal_schemas(capsys, monkeypatch):
    request_module = _load_request_module()
    monkeypatch.setattr(request_module, "fetch_body", _fake_request_fetch)

    datasets = _run_request_json(
        request_module,
        capsys,
        ["--registry-url", REQUEST_REGISTRY_URL, "--datasets", "--format", "json"],
    )
    result = _run_request_json(
        request_module,
        capsys,
        ["event_stream", "--registry-url", REQUEST_REGISTRY_URL, "--format", "json", "--limit", "1"],
    )

    validate_payload(datasets)
    validate_payload(result)


def test_real_error_payloads_validate_against_formal_schemas(tmp_path, capsys, monkeypatch):
    cache_dir = tmp_path / "cache"

    invalid_dataset = _run_cli_json(
        capsys,
        ["--cache-dir", str(cache_dir), "sync", "missing", "--json"],
        expected_code=2,
    )
    validate_payload(invalid_dataset)
    assert invalid_dataset["error"]["code"] == "invalid_dataset_key"

    import tradecat_terminal.cache as cache_module

    monkeypatch.setattr(cache_module, "fetch_csv_body", _fake_sheet_fetch)
    monkeypatch.setenv("TRADECAT_CACHE_COMPRESSION", "bad")
    invalid_runtime = _run_cli_json(
        capsys,
        ["--cache-dir", str(cache_dir), "sync", "market_snapshot", "--json"],
        expected_code=2,
    )
    validate_payload(invalid_runtime)
    assert invalid_runtime["error"]["code"] == "invalid_runtime_configuration"

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.delenv("TRADECAT_CACHE_COMPRESSION", raising=False)
    monkeypatch.setattr(cli, "sync_dataset", boom)
    local_runtime = _run_cli_json(
        capsys,
        ["--cache-dir", str(cache_dir), "sync", "market_snapshot", "--json"],
        expected_code=1,
    )
    validate_payload(local_runtime)
    assert local_runtime["error"]["code"] == "local_runtime_error"


def test_golden_json_fixtures_validate_against_formal_schemas():
    expected = {
        "invalid-dataset-error.json",
        "invalid-runtime-configuration-error.json",
        "local-runtime-error.json",
        "request-dataset-list-success.json",
        "status-success.json",
        "support-bundle-success.json",
    }
    fixture_paths = sorted(FIXTURES_DIR.glob("*.json"))

    assert {path.name for path in fixture_paths} == expected
    for path in fixture_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_payload(payload)


def validate_payload(payload: dict[str, Any]) -> None:
    schema_id = payload["schema"]
    schema = _schema_by_payload_schema()[schema_id]
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, registry=_schema_registry())
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.path))

    assert not errors, "\n".join(_format_schema_error(error) for error in errors)


def _run_cli_json(capsys, args: list[str], *, expected_code: int = 0) -> dict[str, Any]:
    assert cli.main(args) == expected_code
    return _json_from_stdout(capsys.readouterr().out)


def _run_request_json(request_module: ModuleType, capsys, args: list[str], *, expected_code: int = 0) -> dict[str, Any]:
    assert request_module.main(args) == expected_code
    return _json_from_stdout(capsys.readouterr().out)


def _json_from_stdout(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(text.splitlines()[-1])


def _fake_sheet_fetch(url: str, timeout: float = 30.0) -> str:
    del url, timeout
    return SHEET_CSV


def _fake_request_fetch(url: str, *, timeout: float) -> str:
    del timeout
    if url == REQUEST_REGISTRY_URL:
        return json.dumps(REQUEST_REGISTRY)
    return EVENT_CSV


def _load_request_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tradecat_request_payload_schema_test", REQUEST_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _schema_by_payload_schema() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for schema in _schema_payloads().values():
        schema_id = schema.get("properties", {}).get("schema", {}).get("const")
        if isinstance(schema_id, str):
            result[schema_id] = schema
    return result


def _schema_registry() -> Registry:
    return Registry().with_resources(
        (
            str(schema["$id"]),
            Resource.from_contents(schema, default_specification=DRAFT202012),
        )
        for schema in _schema_payloads().values()
    )


def _schema_payloads() -> dict[str, dict[str, Any]]:
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(CONTRACTS_DIR.glob("*.schema.json"))
    }


def _format_schema_error(error) -> str:
    location = ".".join(str(item) for item in error.path) or "<root>"
    return f"{location}: {error.message}"
