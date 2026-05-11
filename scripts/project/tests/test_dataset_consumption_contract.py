from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from tradecat_terminal import cli
from tradecat_terminal.dataset_contract import (
    DATASET_CONSUMPTION_SCHEMA,
    dataset_consumption_contract,
    load_dataset_consumption_contract,
)
from tradecat_terminal.registry import get_dataset, list_datasets

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_SCRIPT = PROJECT_ROOT / "scripts" / "validate_dataset_consumption_contract.py"


def _last_json(captured: str) -> dict:
    return json.loads(captured.strip().splitlines()[-1])


def test_dataset_consumption_contract_covers_registry():
    payload = load_dataset_consumption_contract()

    assert payload["schema"] == DATASET_CONSUMPTION_SCHEMA
    assert set(payload["datasets"]) == {dataset.key for dataset in list_datasets(include_inactive=True)}
    validator = _load_validator_module()
    assert validator.validate_dataset_consumption_contract(include_inactive=True) == []


def test_event_stream_consumption_semantics_are_machine_readable():
    contract = dataset_consumption_contract("event_stream")
    dataset = get_dataset("event_stream")
    covered_columns = {
        column
        for field in contract["fields"]
        for column in field["source_columns"]
    }

    assert contract["data_mode"] == "stream"
    assert contract["time_semantics"]["event_time_column"] == "时间(北京)"
    assert set(dataset.event_key_columns).issubset(covered_columns)
    assert contract["missing_value_policy"] == "empty_string_is_missing"
    assert contract["quality_tier"] == "public_sheet_best_effort"


def test_datasets_json_exposes_consumption_contract(capsys):
    assert cli.main(["datasets", "--json"]) == 0
    payload = _last_json(capsys.readouterr().out)
    event_stream = next(dataset for dataset in payload["datasets"] if dataset["key"] == "event_stream")
    contract = event_stream["consumption_contract"]

    assert contract["schema"] == DATASET_CONSUMPTION_SCHEMA
    assert contract["dataset_key"] == "event_stream"
    assert contract["primary_entity"] == "event"
    assert contract["required_column_groups"][0]["name"] == "event_time"


def _load_validator_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tradecat_dataset_consumption_validator_test", VALIDATOR_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
