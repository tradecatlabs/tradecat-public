from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tradecat_terminal.diagnostics import record_recent_error, sanitize_error
from tradecat_terminal.migrations import CURRENT_CACHE_SCHEMA_VERSION, migrate_cache
from tradecat_terminal.registry import DatasetSpec, get_dataset, list_active_datasets, list_datasets
from tradecat_terminal.sheets import (
    RemoteCsvError,
    fetch_csv_body,
    find_header_row_index,
    is_section_header_row,
    normalize_headers,
    parse_csv_matrix,
)
from tradecat_terminal.state import (
    atomic_write_json,
    atomic_write_json_gzip,
    locked_path,
    preserve_corrupt_file,
    read_json_file,
)
from tradecat_terminal.structured_cache import (
    LATEST_CSV_FILE,
    LATEST_JSON_FILE,
    LATEST_JSONL_FILE,
    write_cache_manifest,
    write_structured_latest,
)

CACHE_SCHEMA_VERSION = CURRENT_CACHE_SCHEMA_VERSION
MANIFEST_FILE = "manifest.json"
STREAM_FILE = "stream_events.json"
CACHE_COMPRESSION_ENV = "TRADECAT_CACHE_COMPRESSION"


def init_cache(cache_dir: Path) -> dict[str, Any]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    for dataset in list_datasets(include_inactive=True):
        (_dataset_dir(cache_dir, dataset.key) / "snapshots").mkdir(parents=True, exist_ok=True)
    return {"ok": True, "cache_dir": str(cache_dir), "datasets": len(list_datasets(include_inactive=True))}


def status_cache(cache_dir: Path) -> dict[str, Any]:
    datasets: list[dict[str, Any]] = []
    for dataset in list_datasets(include_inactive=True):
        dataset_dir = _dataset_dir(cache_dir, dataset.key)
        manifest = read_manifest(cache_dir, dataset.key)
        latest_json_exists = (dataset_dir / LATEST_JSON_FILE).exists()
        latest_jsonl_exists = (dataset_dir / LATEST_JSONL_FILE).exists()
        latest_csv_exists = (dataset_dir / LATEST_CSV_FILE).exists()
        datasets.append(
            {
                "dataset_key": dataset.key,
                "tab_name": dataset.tab_name,
                "data_mode": dataset.data_mode,
                "active": dataset.active,
                "cache_state": _dataset_cache_state(dataset_dir, latest_json_exists),
                "dataset_dir": str(dataset_dir),
                "latest_json_exists": latest_json_exists,
                "latest_jsonl_exists": latest_jsonl_exists,
                "latest_csv_exists": latest_csv_exists,
                "snapshot_count": len(manifest.get("snapshots") or []),
                "event_count": _stream_event_count(cache_dir, dataset.key) if dataset.is_stream() else 0,
                "manifest_corrupt": bool(manifest.get("corrupt")),
                "manifest_error": manifest.get("error", ""),
                "manifest_corrupt_backup": manifest.get("corrupt_backup", ""),
                "current_hash": manifest.get("current_hash"),
                "fetched_at": manifest.get("fetched_at"),
                "row_count": manifest.get("row_count", 0),
                "column_count": manifest.get("column_count", 0),
                "cache_bytes": _directory_size(dataset_dir),
            }
        )
    ready_count = sum(1 for item in datasets if item["active"] and item["cache_state"] == "ready")
    missing_count = sum(1 for item in datasets if item["active"] and item["cache_state"] != "ready")
    return {
        "ok": True,
        "cache_dir": str(cache_dir),
        "exists": cache_dir.exists(),
        "dataset_count": len(datasets),
        "ready_dataset_count": ready_count,
        "missing_dataset_count": missing_count,
        "cache_bytes": _directory_size(cache_dir),
        "datasets": datasets,
    }


def sync_dataset(
    cache_dir: Path,
    dataset_key: str,
    *,
    fetch_timeout: float | None = None,
) -> dict[str, Any]:
    dataset = get_dataset(dataset_key)
    url = dataset.export_url()
    try:
        body = fetch_csv_body(url, timeout=fetch_timeout or 30.0)
        return write_dataset_body(cache_dir, dataset, body)
    except RemoteCsvError as exc:
        error = exc.to_dict()
        record_recent_error(cache_dir, source="sync", dataset_key=dataset.key, error=error)
        return _sync_error_result(cache_dir, dataset, error)


def sync_all_datasets(cache_dir: Path, *, fetch_timeout: float | None = None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    init_cache(cache_dir)
    for dataset in list_active_datasets():
        try:
            results.append(sync_dataset(cache_dir, dataset.key, fetch_timeout=fetch_timeout))
        except ValueError as exc:
            error = {
                "code": "invalid_runtime_configuration",
                "kind": "configuration",
                "message": str(exc),
                "hint": "检查本地配置、环境变量和缓存压缩参数后重试。",
                "retryable": False,
            }
            record_recent_error(cache_dir, source="sync-all", dataset_key=dataset.key, error=error)
            results.append(
                {
                    "ok": False,
                    "dataset_key": dataset.key,
                    "tab_name": dataset.tab_name,
                    "data_mode": dataset.data_mode,
                    "status": "error",
                    "changed": False,
                    "wrote": False,
                    "error": str(exc),
                    "error_code": error["code"],
                    "error_kind": error["kind"],
                    "error_retryable": error["retryable"],
                    "error_hint": error["hint"],
                    "error_info": error,
                    "cache_dir": str(cache_dir),
                }
            )
        except Exception as exc:
            error = sanitize_error(exc)
            record_recent_error(cache_dir, source="sync-all", dataset_key=dataset.key, error=error)
            results.append(
                {
                    "ok": False,
                    "dataset_key": dataset.key,
                    "tab_name": dataset.tab_name,
                    "data_mode": dataset.data_mode,
                    "error": str(exc),
                    "error_info": error,
                    "cache_dir": str(cache_dir),
                }
            )
    return results


def write_dataset_body(cache_dir: Path, dataset: DatasetSpec, body: str) -> dict[str, Any]:
    init_cache(cache_dir)
    migrate_cache(cache_dir, reason="write")
    with locked_path(_manifest_path(cache_dir, dataset.key)):
        return _write_dataset_body_locked(cache_dir, dataset, body)


def _write_dataset_body_locked(cache_dir: Path, dataset: DatasetSpec, body: str) -> dict[str, Any]:
    init_cache(cache_dir)
    matrix = parse_csv_matrix(body)
    matrix_hash = hash_matrix(matrix)
    fetched_at = _now_iso()
    dataset_dir = _dataset_dir(cache_dir, dataset.key)
    dataset_dir.mkdir(parents=True, exist_ok=True)
    snapshots_dir = dataset_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    manifest = read_manifest(cache_dir, dataset.key)
    previous_hash = manifest.get("current_hash")
    changed = manifest.get("current_hash") != matrix_hash
    compression, compression_suffix = _snapshot_compression()

    snapshot_ref = manifest.get("current_snapshot")
    if changed:
        snapshot_ref = f"snapshots/{_safe_time(fetched_at)}_{matrix_hash[:16]}.json{compression_suffix}"
        _write_json(
            dataset_dir / str(snapshot_ref),
            {
                "schema_version": CACHE_SCHEMA_VERSION,
                "dataset_key": dataset.key,
                "tab_name": dataset.tab_name,
                "fetched_at": fetched_at,
                "content_hash": matrix_hash,
                "compression": compression,
                "data_mode": dataset.data_mode,
                "row_count": len(matrix),
                "column_count": _matrix_width(matrix),
                "matrix": matrix,
            },
        )
    if dataset.is_stream():
        stream_result = _merge_stream_events(cache_dir, dataset, matrix, fetched_at=fetched_at)
        structured_matrix = _stream_structured_matrix(cache_dir, dataset, matrix)
    else:
        stream_result = {"new_events": 0, "updated_events": 0, "event_count": 0}
        structured_matrix = matrix

    snapshots = list(manifest.get("snapshots") or [])
    if changed and snapshot_ref:
        snapshots = [
            {
                "snapshot": snapshot_ref,
                "content_hash": matrix_hash,
                "fetched_at": fetched_at,
                "row_count": len(matrix),
                "column_count": _matrix_width(matrix),
                "compression": compression,
            },
            *[item for item in snapshots if item.get("content_hash") != matrix_hash],
        ]
    new_manifest = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "dataset_key": dataset.key,
        "data_mode": dataset.data_mode,
        "current_hash": matrix_hash,
        "current_snapshot": snapshot_ref,
        "latest_json": LATEST_JSON_FILE,
        "latest_jsonl": LATEST_JSONL_FILE,
        "latest_csv": LATEST_CSV_FILE,
        "fetched_at": fetched_at,
        "checked_at": fetched_at,
        "row_count": len(matrix),
        "column_count": _matrix_width(matrix),
        "snapshots": snapshots,
        "stream": stream_result,
    }
    _write_json(_manifest_path(cache_dir, dataset.key), new_manifest)
    latest_payload = write_structured_latest(
        cache_dir,
        dataset,
        structured_matrix,
        fetched_at=fetched_at,
        matrix_hash=matrix_hash,
        previous_hash=str(previous_hash or ""),
        changed=changed,
        snapshot_ref=str(snapshot_ref or ""),
        status="written" if changed else "unchanged",
    )
    write_cache_manifest(cache_dir)
    return {
        "ok": True,
        "dataset_key": dataset.key,
        "tab_name": dataset.tab_name,
        "data_mode": dataset.data_mode,
        "status": "written" if changed else "unchanged",
        "changed": changed,
        "wrote": changed,
        "row_count": len(matrix),
        "column_count": _matrix_width(matrix),
        "content_hash": matrix_hash,
        "compression": compression if changed else _snapshot_compression_for_ref(snapshot_ref),
        "snapshot": snapshot_ref,
        "stream": stream_result,
        "latest_json": LATEST_JSON_FILE,
        "latest_jsonl": LATEST_JSONL_FILE,
        "latest_csv": LATEST_CSV_FILE,
        "structured_row_count": latest_payload["stats"]["row_count"],
        "structured_column_count": latest_payload["stats"]["column_count"],
        "cache_dir": str(cache_dir),
    }


def _sync_error_result(cache_dir: Path, dataset: DatasetSpec, error: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": False,
        "dataset_key": dataset.key,
        "tab_name": dataset.tab_name,
        "data_mode": dataset.data_mode,
        "status": "error",
        "changed": False,
        "wrote": False,
        "error": str(error.get("message") or error.get("code") or "remote sync failed"),
        "error_code": error.get("code"),
        "error_kind": error.get("kind"),
        "error_retryable": error.get("retryable"),
        "error_hint": error.get("hint"),
        "error_info": error,
        "cache_dir": str(cache_dir),
    }


def read_manifest(cache_dir: Path, dataset_key: str) -> dict[str, Any]:
    path = _manifest_path(cache_dir, dataset_key)
    if not path.exists():
        return {}
    try:
        return _read_json(path)
    except Exception as exc:
        backup = preserve_corrupt_file(path)
        return {
            "schema_version": CACHE_SCHEMA_VERSION,
            "dataset_key": dataset_key,
            "corrupt": True,
            "error": str(exc),
            "corrupt_backup": str(backup or ""),
            "snapshots": [],
        }


def list_snapshot_refs(cache_dir: Path, dataset_key: str) -> list[dict[str, Any]]:
    manifest = read_manifest(cache_dir, dataset_key)
    return list(manifest.get("snapshots") or [])


def prune_cache(
    cache_dir: Path,
    *,
    max_snapshots_per_dataset: int | None,
    dataset_key: str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    init_cache(cache_dir)
    max_count = int(max_snapshots_per_dataset or 0)
    datasets = [get_dataset(dataset_key)] if dataset_key else list_datasets(include_inactive=True)
    results: list[dict[str, Any]] = []
    for dataset in datasets:
        with locked_path(_manifest_path(cache_dir, dataset.key)):
            manifest = read_manifest(cache_dir, dataset.key)
            snapshots = list(manifest.get("snapshots") or [])
            if max_count <= 0:
                results.append(
                    {
                        "dataset_key": dataset.key,
                        "mode": "disabled",
                        "snapshot_count": len(snapshots),
                        "candidate_count": 0,
                        "deleted_count": 0,
                        "candidates": [],
                    }
                )
                continue
            keep, candidates = _split_snapshot_prune_plan(manifest, snapshots, max_count)
            deleted = []
            if apply and candidates:
                for item in candidates:
                    ref = str(item.get("snapshot") or "")
                    if not ref:
                        continue
                    path = _dataset_dir(cache_dir, dataset.key) / ref
                    if path.exists():
                        path.unlink()
                    deleted.append(ref)
                manifest["snapshots"] = keep
                manifest["updated_at"] = _now_iso()
                _write_json(_manifest_path(cache_dir, dataset.key), manifest)
            results.append(
                {
                    "dataset_key": dataset.key,
                    "mode": "apply" if apply else "dry-run",
                    "snapshot_count": len(snapshots),
                    "keep_count": len(keep),
                    "candidate_count": len(candidates),
                    "deleted_count": len(deleted),
                    "candidates": candidates,
                    "deleted": deleted,
                }
            )
    if apply:
        write_cache_manifest(cache_dir)
    return {
        "ok": True,
        "cache_dir": str(cache_dir),
        "max_snapshots_per_dataset": max_count,
        "applied": apply,
        "datasets": results,
    }


def read_cached_view(
    cache_dir: Path,
    dataset_key: str,
    *,
    batch_index: int = 0,
    live: bool = True,
) -> dict[str, Any]:
    dataset = get_dataset(dataset_key)
    manifest = read_manifest(cache_dir, dataset.key)
    if not manifest:
        return _empty_view(dataset, cache_dir)
    snapshots = list(manifest.get("snapshots") or [])
    if not snapshots:
        return _empty_view(dataset, cache_dir)
    safe_index = 0 if live or dataset.is_stream() else min(max(0, int(batch_index)), len(snapshots) - 1)
    snapshot_ref = snapshots[safe_index].get("snapshot") or manifest.get("current_snapshot")
    snapshot = _read_json(_dataset_dir(cache_dir, dataset.key) / str(snapshot_ref))
    matrix = snapshot.get("matrix") if isinstance(snapshot.get("matrix"), list) else []
    if dataset.is_stream():
        matrix = _stream_display_matrix(cache_dir, dataset, matrix)
    header_index = find_header_row_index(matrix) if matrix else 0
    table_columns = _logical_table_columns(matrix, header_index)
    table_rows = _logical_table_rows(dataset.key, matrix, header_index)
    rows = _matrix_to_rows(dataset.key, matrix[1:], start_row_index=2)
    physical_columns = _matrix_columns(matrix)
    layout = _view_layout(matrix, header_index)
    return {
        "ok": True,
        "cache_dir": str(cache_dir),
        "dataset_key": dataset.key,
        "tab_name": dataset.tab_name,
        "data_mode": dataset.data_mode,
        "batch_index": safe_index,
        "batch_count": len(snapshots),
        "batch_label": snapshots[safe_index].get("fetched_at") or manifest.get("fetched_at"),
        "content_hash": snapshots[safe_index].get("content_hash") or manifest.get("current_hash"),
        "top_lines": _top_info_lines(matrix[:1]),
        "display_top_lines": _display_top_info_lines(matrix[:header_index]),
        "meta": layout["meta"],
        "layout": layout,
        "rows": rows,
        "columns": physical_columns,
        "physical_columns": physical_columns,
        "table_columns": table_columns,
        "table_rows": table_rows,
        "structured_columns": _table_column_meta(table_columns),
        "fetched_at": manifest.get("fetched_at"),
    }


def hash_matrix(matrix: list[list[str]]) -> str:
    return _hash_json(matrix)


def event_key_for_row(dataset: DatasetSpec, row: dict[str, str]) -> str:
    values = [str(row.get(column, "")).strip() for column in dataset.event_key_columns]
    if dataset.event_key_columns and all(values):
        return _hash_json({"columns": list(dataset.event_key_columns), "values": values})
    return _hash_json(row)


def normalized_event_key_for_row(dataset: DatasetSpec, row: dict[str, str]) -> str:
    del dataset
    text = _normalize_event_text(str(row.get("内容") or row.get("content") or row))
    return _hash_json({"normalized_content": text})


def _merge_stream_events(cache_dir: Path, dataset: DatasetSpec, matrix: list[list[str]], *, fetched_at: str) -> dict[str, int]:
    header, rows = _parse_sheet_rows(matrix)
    path = _stream_path(cache_dir, dataset.key)
    state = _read_json(path) if path.exists() else {"events": []}
    existing: dict[str, dict[str, Any]] = {
        str(event.get("event_key")): dict(event) for event in state.get("events", []) if event.get("event_key")
    }
    existing_by_normalized: dict[str, dict[str, Any]] = {
        str(event.get("normalized_event_key")): event
        for event in existing.values()
        if event.get("normalized_event_key")
    }
    new_events = 0
    updated_events = 0
    ordered_keys: list[str] = []
    for row in rows:
        key = event_key_for_row(dataset, row)
        normalized_key = normalized_event_key_for_row(dataset, row)
        event = existing.get(key) or existing_by_normalized.get(normalized_key)
        if event:
            key = str(event.get("event_key") or key)
            ordered_keys.append(key)
            event["last_seen_at"] = fetched_at
            event["seen_count"] = int(event.get("seen_count") or 1) + 1
            event["normalized_event_key"] = normalized_key
            observed_keys = list(event.get("observed_event_keys") or [])
            if key not in observed_keys:
                observed_keys.append(key)
            row_key = event_key_for_row(dataset, row)
            if row_key not in observed_keys:
                observed_keys.append(row_key)
            event["observed_event_keys"] = observed_keys[-20:]
            event["values"] = row
            updated_events += 1
        else:
            ordered_keys.append(key)
            existing[key] = {
                "event_key": key,
                "normalized_event_key": normalized_key,
                "first_seen_at": fetched_at,
                "last_seen_at": fetched_at,
                "seen_count": 1,
                "observed_event_keys": [key],
                "event_time": _event_time(dataset, row),
                "values": row,
            }
            existing_by_normalized[normalized_key] = existing[key]
            new_events += 1
    ordered_unique = _dedupe_ordered(ordered_keys)
    previous_only = [key for key in existing if key not in set(ordered_unique)]
    events = [existing[key] for key in ordered_unique if key in existing] + [existing[key] for key in previous_only]
    _write_json(
        path,
        {
            "schema_version": CACHE_SCHEMA_VERSION,
            "dataset_key": dataset.key,
            "updated_at": fetched_at,
            "header": header,
            "events": events,
        },
    )
    return {"new_events": new_events, "updated_events": updated_events, "event_count": len(events)}


def _dedupe_ordered(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _stream_display_matrix(cache_dir: Path, dataset: DatasetSpec, latest_matrix: list[list[str]]) -> list[list[str]]:
    path = _stream_path(cache_dir, dataset.key)
    if not path.exists():
        return latest_matrix
    state = _read_json(path)
    header = state.get("header")
    if not isinstance(header, list) or not header:
        return latest_matrix
    header_index = find_header_row_index(latest_matrix) if latest_matrix else 0
    top = latest_matrix[: max(1, header_index)]
    rows = []
    for event in state.get("events", []):
        values = event.get("values") if isinstance(event, dict) else {}
        if isinstance(values, dict):
            rows.append([str(values.get(column, "")) for column in header])
    return [*top, [str(item) for item in header], *rows]


def _stream_structured_matrix(cache_dir: Path, dataset: DatasetSpec, latest_matrix: list[list[str]]) -> list[list[str]]:
    path = _stream_path(cache_dir, dataset.key)
    if not path.exists():
        return latest_matrix
    state = _read_json(path)
    header = state.get("header")
    if not isinstance(header, list) or not header:
        return latest_matrix
    header_index = find_header_row_index(latest_matrix) if latest_matrix else 0
    top = latest_matrix[:header_index]
    rows = []
    for event in state.get("events", []):
        values = event.get("values") if isinstance(event, dict) else {}
        if isinstance(values, dict):
            rows.append([str(values.get(column, "")) for column in header])
    return [*top, [str(item) for item in header], *rows]


def _parse_sheet_rows(matrix: list[list[str]]) -> tuple[list[str], list[dict[str, str]]]:
    if not matrix:
        return [], []
    header_index = find_header_row_index(matrix)
    width = max((len(row) for row in matrix[header_index:]), default=0)
    raw_header = [*matrix[header_index], *([""] * max(0, width - len(matrix[header_index])))]
    header = normalize_headers(raw_header)
    rows: list[dict[str, str]] = []
    for raw_row in matrix[header_index + 1 :]:
        if not any(str(cell).strip() for cell in raw_row):
            continue
        padded = [*raw_row, *([""] * max(0, len(header) - len(raw_row)))]
        rows.append({header[index]: padded[index] for index in range(len(header))})
    return header, rows


def _event_time(dataset: DatasetSpec, row: dict[str, str]) -> str:
    for column in (*dataset.event_key_columns, "时间(北京)", "时间", "time", "timestamp"):
        value = str(row.get(column, "")).strip()
        if value:
            return value
    return ""


def _matrix_to_rows(dataset_key: str, matrix: list[list[str]], *, start_row_index: int) -> list[dict[str, Any]]:
    width = _matrix_width(matrix)
    rows: list[dict[str, Any]] = []
    for offset, raw_row in enumerate(matrix):
        values = {}
        for index in range(width):
            values[_column_label(index)] = str(raw_row[index]) if index < len(raw_row) else ""
        rows.append({"source": dataset_key, "row_index": start_row_index + offset, "values": values})
    return rows


def _logical_table_rows(dataset_key: str, matrix: list[list[str]], header_index: int) -> list[dict[str, Any]]:
    if header_index < len(matrix) and is_section_header_row(matrix[header_index]):
        return _sectioned_table_rows(dataset_key, matrix, start_index=header_index)
    return _matrix_to_table_rows(
        dataset_key,
        matrix[header_index + 1 :] if matrix else [],
        _table_columns(matrix, header_index),
        start_row_index=header_index + 2,
    )


def _sectioned_table_rows(dataset_key: str, matrix: list[list[str]], *, start_index: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    section_title = ""
    section_headers: list[str] = []
    row_number = 0
    for row_index, raw_row in enumerate(matrix[start_index:], start=start_index + 1):
        if is_section_header_row(raw_row):
            section_title = str(raw_row[0]).strip()
            section_headers = normalize_headers([str(cell) for cell in raw_row[1:]])
            continue
        if not section_headers:
            continue
        section_values = [str(cell) for cell in raw_row[1:]]
        if not any(cell.strip() for cell in section_values):
            continue
        padded = [*section_values, *([""] * max(0, len(section_headers) - len(section_values)))]
        physical_width = max(len(raw_row), len(section_headers) + 1)
        physical_values = {
            _column_label(index): str(raw_row[index]) if index < len(raw_row) else ""
            for index in range(physical_width)
        }
        raw_values = {"榜单": section_title, "榜单名": section_title, "源行号": str(row_index)}
        raw_values.update({section_headers[index]: padded[index] for index in range(len(section_headers))})
        row_number += 1
        rows.append(
            {
                "source": dataset_key,
                "row_index": row_index,
                "row_number": row_number,
                "values": physical_values,
                "physical_values": physical_values,
                "raw_values": raw_values,
                "section": section_title,
            }
        )
    return rows


def _matrix_to_table_rows(
    dataset_key: str,
    matrix: list[list[str]],
    header: list[str],
    *,
    start_row_index: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    width = len(header)
    for offset, raw_row in enumerate(matrix):
        if not any(str(cell).strip() for cell in raw_row):
            continue
        padded = [*raw_row, *([""] * max(0, width - len(raw_row)))]
        raw_values = {header[index]: str(padded[index]) for index in range(width)}
        physical_values = {_column_label(index): str(padded[index]) for index in range(width)}
        rows.append(
            {
                "source": dataset_key,
                "row_index": start_row_index + offset,
                "row_number": len(rows) + 1,
                "values": physical_values,
                "physical_values": physical_values,
                "raw_values": raw_values,
            }
        )
    return rows


def _matrix_columns(matrix: list[list[str]]) -> list[str]:
    width = _matrix_width(matrix[1:] if len(matrix) > 1 else matrix)
    return [_column_label(index) for index in range(width)]


def _logical_table_columns(matrix: list[list[str]], header_index: int) -> list[str]:
    if header_index < len(matrix) and is_section_header_row(matrix[header_index]):
        columns: list[str] = ["榜单", "榜单名", "源行号"]
        for row in matrix[header_index:]:
            if not is_section_header_row(row):
                continue
            for column in normalize_headers([str(cell) for cell in row[1:]]):
                if column not in columns:
                    columns.append(column)
        return columns
    return _table_columns(matrix, header_index)


def _table_columns(matrix: list[list[str]], header_index: int) -> list[str]:
    if not matrix or header_index >= len(matrix):
        return []
    width = max(_matrix_width(matrix[header_index:]), len(matrix[header_index]))
    raw_header = [*matrix[header_index], *([""] * max(0, width - len(matrix[header_index])))]
    return normalize_headers(raw_header)


def _table_column_meta(columns: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "name": column,
            "index": index,
            "letter": _column_label(index),
            "type": "string",
            "role": "field",
            "nullable": True,
        }
        for index, column in enumerate(columns)
    ]


def _view_layout(matrix: list[list[str]], header_index: int) -> dict[str, Any]:
    if not matrix:
        return {
            "top_lines": [],
            "meta": {},
            "physical_rows": {
                "top_start_row": None,
                "top_end_row": None,
                "meta_row": None,
                "header_row": 1,
                "data_start_row": 2,
            },
        }
    top_rows = matrix[:header_index]
    top_row_numbers = [index for index, row in enumerate(top_rows, start=1) if any(str(cell).strip() for cell in row)]
    meta, meta_row = _extract_meta(top_rows)
    return {
        "top_lines": _display_top_info_lines(top_rows),
        "meta": meta,
        "physical_rows": {
            "top_start_row": min(top_row_numbers) if top_row_numbers else None,
            "top_end_row": max(top_row_numbers) if top_row_numbers else None,
            "meta_row": meta_row,
            "header_row": header_index + 1,
            "data_start_row": header_index + 2,
        },
    }


def _column_label(index: int) -> str:
    value = int(index)
    label = ""
    while True:
        value, remainder = divmod(value, 26)
        label = chr(ord("A") + remainder) + label
        if value == 0:
            return label
        value -= 1


def _top_info_lines(rows: list[list[str]]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        for value in row:
            text = str(value).strip()
            if not text:
                continue
            for line in text.splitlines() or [text]:
                clean = line.strip()
                if clean:
                    lines.append(clean)
    return lines


def _display_top_info_lines(rows: list[list[str]]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        non_empty = [str(cell).strip() for cell in row if str(cell).strip()]
        if not non_empty:
            continue
        if len(non_empty) == 1:
            lines.extend(line.strip() for line in non_empty[0].splitlines() if line.strip())
        else:
            lines.append(", ".join(non_empty))
    return lines


def _extract_meta(rows: list[list[str]]) -> tuple[dict[str, str], int | None]:
    for row_index, row in enumerate(rows, start=1):
        tokens = _meta_tokens(row)
        if not tokens or (tokens[0] != "数据源" and "数据源" not in tokens):
            continue
        meta: dict[str, str] = {}
        for index in range(0, len(tokens) - 1, 2):
            key = str(tokens[index]).strip()
            value = str(tokens[index + 1]).strip()
            if key:
                meta[key] = value
        if meta:
            return meta, row_index
    return {}, None


def _meta_tokens(row: list[str]) -> list[str]:
    non_empty = [str(cell).strip() for cell in row if str(cell).strip()]
    if not non_empty:
        return []
    if len(non_empty) > 1 and non_empty[0] == "数据源":
        return non_empty
    for cell in non_empty:
        for line in str(cell).splitlines():
            text = line.strip()
            if text.startswith("数据源"):
                return [token.strip() for token in text.replace("，", ",").split(",") if token.strip()]
    if len(non_empty) == 1:
        text = non_empty[0]
        if text.startswith(("http://", "https://")):
            return []
        return [token.strip() for token in text.replace("，", ",").split(",") if token.strip()]
    return non_empty


def _empty_view(dataset: DatasetSpec, cache_dir: Path) -> dict[str, Any]:
    return {
        "ok": False,
        "cache_dir": str(cache_dir),
        "dataset_key": dataset.key,
        "tab_name": dataset.tab_name,
        "data_mode": dataset.data_mode,
        "batch_index": 0,
        "batch_count": 0,
        "batch_label": "",
        "content_hash": "",
        "top_lines": [],
        "display_top_lines": [],
        "meta": {},
        "layout": {},
        "rows": [],
        "columns": [],
        "physical_columns": [],
        "table_columns": [],
        "table_rows": [],
        "structured_columns": [],
        "fetched_at": "",
    }


def _stream_event_count(cache_dir: Path, dataset_key: str) -> int:
    path = _stream_path(cache_dir, dataset_key)
    if not path.exists():
        return 0
    return len(_read_json(path).get("events") or [])


def _dataset_cache_state(dataset_dir: Path, latest_json_exists: bool) -> str:
    if latest_json_exists:
        return "ready"
    if dataset_dir.exists():
        return "initialized"
    return "missing"


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def _split_snapshot_prune_plan(
    manifest: dict[str, Any], snapshots: list[dict[str, Any]], max_count: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    current_ref = str(manifest.get("current_snapshot") or "")
    keep: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for item in snapshots:
        ref = str(item.get("snapshot") or "")
        if ref == current_ref and item not in keep:
            keep.append(item)
            continue
        if len(keep) < max_count:
            keep.append(item)
        else:
            candidates.append(item)
    if len(keep) > max_count:
        overflow = keep[max_count:]
        keep = keep[:max_count]
        candidates = [*overflow, *candidates]
    return keep, candidates


def _dataset_dir(cache_dir: Path, dataset_key: str) -> Path:
    return cache_dir / "datasets" / dataset_key


def _manifest_path(cache_dir: Path, dataset_key: str) -> Path:
    return _dataset_dir(cache_dir, dataset_key) / MANIFEST_FILE


def _stream_path(cache_dir: Path, dataset_key: str) -> Path:
    return _dataset_dir(cache_dir, dataset_key) / STREAM_FILE


def _matrix_width(matrix: list[list[str]]) -> int:
    return max((len(row) for row in matrix), default=0)


def _read_json(path: Path) -> dict[str, Any]:
    return read_json_file(path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    if path.name.endswith(".gz"):
        atomic_write_json_gzip(path, payload)
        return
    atomic_write_json(path, payload)


def _snapshot_compression() -> tuple[str, str]:
    raw = os.environ.get(CACHE_COMPRESSION_ENV, "none").strip().lower()
    if raw in {"", "none", "plain", "off"}:
        return "none", ""
    if raw in {"gzip", "gz"}:
        return "gzip", ".gz"
    raise ValueError(f"不支持的 {CACHE_COMPRESSION_ENV}: {raw}; 可用值: none, gzip")


def _snapshot_compression_for_ref(snapshot_ref: str | None) -> str:
    return "gzip" if str(snapshot_ref or "").endswith(".gz") else "none"


def _normalize_event_text(value: str) -> str:
    return " ".join(str(value).strip().split())


def _hash_json(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).astimezone().isoformat()


def _safe_time(value: str) -> str:
    return value.replace(":", "").replace(".", "").replace("+", "p").replace("-", "").replace("T", "T")
