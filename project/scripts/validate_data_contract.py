from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tradecat_terminal.registry import REGISTRY_RESOURCE, get_dataset, list_datasets
from tradecat_terminal.sheets import fetch_csv_body, find_header_row_index, parse_csv_matrix

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "src" / "tradecat_terminal" / REGISTRY_RESOURCE
REQUIRED_LANGS = {"zh", "en", "ko"}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dataset_keys = args.dataset or [dataset.key for dataset in list_datasets(include_inactive=args.include_inactive)]
    errors: list[str] = []

    errors.extend(validate_registry_file())
    for dataset_key in dataset_keys:
        try:
            dataset = get_dataset(dataset_key)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        errors.extend(validate_dataset_contract(dataset_key))
        if args.remote and dataset.active:
            errors.extend(validate_remote_csv(dataset_key, timeout=args.timeout))

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    mode = "registry+remote" if args.remote else "registry"
    print(f"data contract ok: mode={mode} datasets={len(dataset_keys)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate TradeCat public dataset registry and CSV contracts.")
    parser.add_argument("--remote", action="store_true", help="Fetch public Google Sheets CSV endpoints and validate shape.")
    parser.add_argument("--timeout", type=float, default=10.0, help="Remote CSV fetch timeout in seconds.")
    parser.add_argument("--dataset", action="append", help="Dataset key to validate; can be repeated.")
    parser.add_argument("--include-inactive", action="store_true", help="Include inactive datasets in registry validation.")
    return parser


def validate_registry_file() -> list[str]:
    errors: list[str] = []
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if payload.get("schema") != "tradecat.dataset_registry.v1":
        errors.append(f"{REGISTRY_RESOURCE} schema must be tradecat.dataset_registry.v1")
    if not isinstance(payload.get("workbooks"), dict) or not payload["workbooks"]:
        errors.append(f"{REGISTRY_RESOURCE} workbooks must be a non-empty object")
    if not isinstance(payload.get("datasets"), dict) or not payload["datasets"]:
        errors.append(f"{REGISTRY_RESOURCE} datasets must be a non-empty object")

    seen_export_keys: set[tuple[str, str]] = set()
    for key, raw in (payload.get("datasets") or {}).items():
        if not isinstance(raw, dict):
            errors.append(f"dataset {key} must be an object")
            continue
        workbook_key = raw.get("workbook_key")
        gid = raw.get("gid")
        tab_name = raw.get("tab_name")
        if workbook_key not in payload.get("workbooks", {}):
            errors.append(f"dataset {key} references unknown workbook: {workbook_key}")
        if raw.get("active", True) and not gid and not tab_name:
            errors.append(f"active dataset {key} must define gid or tab_name")
        if raw.get("data_mode") not in ("snapshot", "stream"):
            errors.append(f"dataset {key} data_mode must be snapshot or stream")
        display_names = raw.get("display_names")
        if not isinstance(display_names, dict) or not REQUIRED_LANGS.issubset(display_names):
            errors.append(f"dataset {key} display_names must include zh/en/ko")
        if gid or tab_name:
            export_key = (str(workbook_key), str(gid or f"sheet:{tab_name}"))
            if export_key in seen_export_keys:
                errors.append(f"dataset {key} duplicates workbook export key: {workbook_key}/{export_key[1]}")
            seen_export_keys.add(export_key)
    return errors


def validate_dataset_contract(dataset_key: str) -> list[str]:
    errors: list[str] = []
    dataset = get_dataset(dataset_key)
    if dataset.is_stream() and not dataset.event_key_columns:
        errors.append(f"stream dataset {dataset_key} must define event_key_columns")
    if dataset.is_snapshot() and not dataset.index_columns:
        errors.append(f"snapshot dataset {dataset_key} must define index_columns")
    if dataset.tui_fetch_timeout_seconds and dataset.tui_probe_interval_seconds:
        if dataset.tui_fetch_timeout_seconds > dataset.tui_probe_interval_seconds:
            errors.append(f"dataset {dataset_key} fetch timeout must not exceed probe interval")
    return errors


def validate_remote_csv(dataset_key: str, *, timeout: float) -> list[str]:
    errors: list[str] = []
    dataset = get_dataset(dataset_key)
    try:
        body = fetch_csv_body(dataset.export_url(), timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return [f"dataset {dataset_key} remote CSV fetch failed: {exc}"]

    matrix = parse_csv_matrix(body)
    if not matrix:
        return [f"dataset {dataset_key} remote CSV is empty"]

    header_index = find_header_row_index(matrix)
    header = [cell.strip() for cell in matrix[header_index] if cell.strip()]
    if len(header) < 2:
        errors.append(f"dataset {dataset_key} remote CSV header must contain at least 2 columns")
    data_rows = [row for row in matrix[header_index + 1 :] if any(cell.strip() for cell in row)]
    if not data_rows:
        errors.append(f"dataset {dataset_key} remote CSV must contain at least one data row")
    if dataset.index_columns and not any(column in header for column in dataset.index_columns):
        errors.append(f"dataset {dataset_key} remote CSV header lacks any configured index column")
    missing_event_keys = [column for column in dataset.event_key_columns if column not in header]
    if missing_event_keys:
        errors.append(f"dataset {dataset_key} remote CSV header lacks event key columns: {missing_event_keys}")
    return errors


if __name__ == "__main__":
    raise SystemExit(main())
