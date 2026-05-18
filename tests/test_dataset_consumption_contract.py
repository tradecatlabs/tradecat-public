from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from tradecat_sources.dataset_contract import (
    DATASET_CONSUMPTION_SCHEMA,
    dataset_consumption_contract,
    load_dataset_consumption_contract,
)
from tradecat_sources.registry import get_dataset, list_datasets

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_SCRIPT = PROJECT_ROOT / "scripts" / "validate_dataset_consumption_contract.py"


def test_dataset_consumption_contract_covers_registry():
    payload = load_dataset_consumption_contract()

    assert payload["schema"] == DATASET_CONSUMPTION_SCHEMA
    assert set(payload["datasets"]) == {dataset.key for dataset in list_datasets(include_inactive=True)}
    validator = _load_validator_module()
    assert validator.validate_dataset_consumption_contract(include_inactive=True) == []


def test_signal_flow_consumption_semantics_are_machine_readable():
    contract = dataset_consumption_contract("signal_flow")
    dataset = get_dataset("signal_flow")
    covered_columns = {column for field in contract["fields"] for column in field["source_columns"]}

    assert contract["data_mode"] == "stream"
    assert contract["time_semantics"]["event_time_column"] == "时间(北京)"
    assert any(field["canonical_name"] == "symbol" for field in contract["fields"])
    assert set(dataset.event_key_columns).issubset(covered_columns)
    assert contract["missing_value_policy"] == "empty_string_is_missing"
    assert contract["quality_tier"] == "public_sheet_best_effort"


def _load_validator_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tradecat_dataset_consumption_validator_test", VALIDATOR_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
