from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tradecat_terminal.dataset_contract import (
    DATASET_CONSUMPTION_CONTRACT_RESOURCE,
    DATASET_CONSUMPTION_SCHEMA,
    load_dataset_consumption_contract,
)
from tradecat_terminal.registry import DATASETS, REGISTRY_RESOURCE, list_datasets

EXPECTED_CONTRACT_SCHEMA = "tradecat.dataset_consumption_contract.v1"
REGISTRY_PATH = Path(__file__).resolve().parents[1] / "src" / "tradecat_terminal" / REGISTRY_RESOURCE
CONTRACT_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "tradecat_terminal" / DATASET_CONSUMPTION_CONTRACT_RESOURCE
)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    errors = validate_dataset_consumption_contract(include_inactive=args.include_inactive)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    dataset_count = len(list_datasets(include_inactive=args.include_inactive))
    print(f"dataset consumption contract ok: datasets={dataset_count}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate TradeCat dataset consumption semantics.")
    parser.add_argument("--include-inactive", action="store_true", help="Require inactive datasets in the contract too.")
    return parser


def validate_dataset_consumption_contract(*, include_inactive: bool = False) -> list[str]:
    errors: list[str] = []
    registry_payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    contract = load_dataset_consumption_contract()

    if DATASET_CONSUMPTION_SCHEMA != EXPECTED_CONTRACT_SCHEMA:
        errors.append(f"validator schema pin drifted: {DATASET_CONSUMPTION_SCHEMA} != {EXPECTED_CONTRACT_SCHEMA}")
    if contract.get("schema") != EXPECTED_CONTRACT_SCHEMA:
        errors.append(f"{CONTRACT_PATH.name} schema must be {EXPECTED_CONTRACT_SCHEMA}")
    if contract.get("schema_version") != "1.0.0":
        errors.append(f"{CONTRACT_PATH.name} schema_version must be 1.0.0")

    policies = contract.get("missing_value_policies")
    if not isinstance(policies, dict) or not policies:
        errors.append(f"{CONTRACT_PATH.name} missing_value_policies must be non-empty")
        policies = {}

    quality_tiers = contract.get("quality_tiers")
    if not isinstance(quality_tiers, dict) or not quality_tiers:
        errors.append(f"{CONTRACT_PATH.name} quality_tiers must be non-empty")
        quality_tiers = {}

    contract_datasets = contract.get("datasets")
    if not isinstance(contract_datasets, dict):
        return [*errors, f"{CONTRACT_PATH.name} datasets must be an object"]

    expected_keys = {dataset.key for dataset in list_datasets(include_inactive=include_inactive)}
    actual_keys = set(contract_datasets)
    missing_keys = sorted(expected_keys - actual_keys)
    unknown_keys = sorted(actual_keys - set(DATASETS))
    if missing_keys:
        errors.append(f"{CONTRACT_PATH.name} missing dataset contracts: {missing_keys}")
    if unknown_keys:
        errors.append(f"{CONTRACT_PATH.name} has unknown dataset contracts: {unknown_keys}")

    raw_registry_datasets = registry_payload.get("datasets") if isinstance(registry_payload.get("datasets"), dict) else {}
    for dataset_key in sorted(expected_keys & actual_keys):
        raw_registry = raw_registry_datasets.get(dataset_key)
        raw_contract = contract_datasets.get(dataset_key)
        if not isinstance(raw_registry, dict) or not isinstance(raw_contract, dict):
            errors.append(f"dataset {dataset_key} registry and contract entries must be objects")
            continue
        errors.extend(_validate_dataset(dataset_key, raw_registry, raw_contract, policies, quality_tiers))

    return errors


def _validate_dataset(
    dataset_key: str,
    registry: dict[str, Any],
    contract: dict[str, Any],
    policies: dict[str, Any],
    quality_tiers: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if contract.get("dataset_key") != dataset_key:
        errors.append(f"dataset {dataset_key} contract dataset_key mismatch: {contract.get('dataset_key')}")
    if contract.get("data_mode") != registry.get("data_mode"):
        errors.append(f"dataset {dataset_key} data_mode mismatch: {contract.get('data_mode')} != {registry.get('data_mode')}")
    if contract.get("missing_value_policy") not in policies:
        errors.append(f"dataset {dataset_key} references unknown missing_value_policy: {contract.get('missing_value_policy')}")
    if contract.get("quality_tier") not in quality_tiers:
        errors.append(f"dataset {dataset_key} references unknown quality_tier: {contract.get('quality_tier')}")

    fields = contract.get("fields")
    if not isinstance(fields, list) or not fields:
        errors.append(f"dataset {dataset_key} fields must be non-empty")
        fields = []
    covered_columns = _covered_source_columns(fields)
    for column in [*registry.get("index_columns", []), *registry.get("event_key_columns", [])]:
        if str(column) not in covered_columns:
            errors.append(f"dataset {dataset_key} registry column is not covered by field semantics: {column}")

    groups = contract.get("required_column_groups")
    if not isinstance(groups, list) or not groups:
        errors.append(f"dataset {dataset_key} required_column_groups must be non-empty")
        groups = []
    for group in groups:
        if not isinstance(group, dict):
            errors.append(f"dataset {dataset_key} required_column_groups entries must be objects")
            continue
        any_of = group.get("any_of")
        if not isinstance(any_of, list) or not any_of:
            errors.append(f"dataset {dataset_key} required group {group.get('name')} must define any_of")
            continue
        uncovered = [str(column) for column in any_of if str(column) not in covered_columns]
        if uncovered:
            errors.append(f"dataset {dataset_key} required group {group.get('name')} has uncovered columns: {uncovered}")

    time_semantics = contract.get("time_semantics")
    if not isinstance(time_semantics, dict):
        errors.append(f"dataset {dataset_key} time_semantics must be an object")
    elif registry.get("data_mode") == "stream":
        event_time_column = time_semantics.get("event_time_column")
        if not event_time_column:
            errors.append(f"stream dataset {dataset_key} must define event_time_column")
        elif str(event_time_column) not in covered_columns:
            errors.append(f"stream dataset {dataset_key} event_time_column is not covered: {event_time_column}")

    return errors


def _covered_source_columns(fields: list[Any]) -> set[str]:
    result: set[str] = set()
    for field in fields:
        if not isinstance(field, dict):
            continue
        source_columns = field.get("source_columns")
        if isinstance(source_columns, list):
            result.update(str(column) for column in source_columns)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
