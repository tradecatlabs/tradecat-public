from __future__ import annotations

import json
from copy import deepcopy
from importlib.resources import files
from typing import Any

DATASET_CONSUMPTION_CONTRACT_RESOURCE = "dataset_consumption_contract.json"
DATASET_CONSUMPTION_SCHEMA = "tradecat.dataset_consumption_contract.v1"


def load_dataset_consumption_contract() -> dict[str, Any]:
    text = files("tradecat_terminal").joinpath(DATASET_CONSUMPTION_CONTRACT_RESOURCE).read_text(encoding="utf-8")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError(f"{DATASET_CONSUMPTION_CONTRACT_RESOURCE} 必须是 JSON object")
    if payload.get("schema") != DATASET_CONSUMPTION_SCHEMA:
        raise ValueError(f"{DATASET_CONSUMPTION_CONTRACT_RESOURCE} schema 非法: {payload.get('schema')}")
    return payload


def dataset_consumption_contract(dataset_key: str) -> dict[str, Any]:
    payload = load_dataset_consumption_contract()
    return _dataset_contract_from_payload(payload, dataset_key)


def dataset_consumption_contract_summary(dataset_key: str) -> dict[str, Any]:
    payload = load_dataset_consumption_contract()
    contract = _dataset_contract_from_payload(payload, dataset_key)
    return {
        "schema": DATASET_CONSUMPTION_SCHEMA,
        "schema_version": "1.0.0",
        "semantic_version": str(payload.get("semantic_version") or ""),
        "dataset_key": dataset_key,
        "primary_entity": contract.get("primary_entity"),
        "time_grain": contract.get("time_grain"),
        "quality_tier": contract.get("quality_tier"),
        "missing_value_policy": contract.get("missing_value_policy"),
        "required_column_groups": contract.get("required_column_groups") or [],
        "fields": contract.get("fields") or [],
    }


def _dataset_contract_from_payload(payload: dict[str, Any], dataset_key: str) -> dict[str, Any]:
    datasets = payload.get("datasets")
    if not isinstance(datasets, dict):
        raise ValueError(f"{DATASET_CONSUMPTION_CONTRACT_RESOURCE} 缺少 datasets")
    contract = datasets.get(dataset_key)
    if not isinstance(contract, dict):
        raise ValueError(f"dataset {dataset_key} 缺少消费语义契约")
    return deepcopy(contract)
