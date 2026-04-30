from __future__ import annotations

import gzip
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tradecat_terminal.registry import DatasetSpec, get_dataset, list_active_datasets, list_datasets
from tradecat_terminal.sheets import fetch_csv_body, find_header_row_index, normalize_headers, parse_csv_matrix

CACHE_SCHEMA_VERSION = 1
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
        manifest = read_manifest(cache_dir, dataset.key)
        datasets.append(
            {
                "dataset_key": dataset.key,
                "tab_name": dataset.tab_name,
                "data_mode": dataset.data_mode,
                "active": dataset.active,
                "snapshot_count": len(manifest.get("snapshots") or []),
                "event_count": _stream_event_count(cache_dir, dataset.key) if dataset.is_stream() else 0,
                "current_hash": manifest.get("current_hash"),
                "fetched_at": manifest.get("fetched_at"),
                "row_count": manifest.get("row_count", 0),
                "column_count": manifest.get("column_count", 0),
            }
        )
    return {"ok": True, "cache_dir": str(cache_dir), "exists": cache_dir.exists(), "datasets": datasets}


def sync_dataset(
    cache_dir: Path,
    dataset_key: str,
    *,
    fetch_timeout: float | None = None,
) -> dict[str, Any]:
    dataset = get_dataset(dataset_key)
    url = dataset.export_url()
    body = fetch_csv_body(url, timeout=fetch_timeout or 30.0)
    return write_dataset_body(cache_dir, dataset, body)


def sync_all_datasets(cache_dir: Path, *, fetch_timeout: float | None = None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    init_cache(cache_dir)
    for dataset in list_active_datasets():
        try:
            results.append(sync_dataset(cache_dir, dataset.key, fetch_timeout=fetch_timeout))
        except Exception as exc:
            results.append(
                {
                    "ok": False,
                    "dataset_key": dataset.key,
                    "tab_name": dataset.tab_name,
                    "data_mode": dataset.data_mode,
                    "error": str(exc),
                    "cache_dir": str(cache_dir),
                }
            )
    return results


def write_dataset_body(cache_dir: Path, dataset: DatasetSpec, body: str) -> dict[str, Any]:
    init_cache(cache_dir)
    matrix = parse_csv_matrix(body)
    matrix_hash = hash_matrix(matrix)
    fetched_at = _now_iso()
    dataset_dir = _dataset_dir(cache_dir, dataset.key)
    dataset_dir.mkdir(parents=True, exist_ok=True)
    snapshots_dir = dataset_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    manifest = read_manifest(cache_dir, dataset.key)
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
    else:
        stream_result = {"new_events": 0, "updated_events": 0, "event_count": 0}

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
        "fetched_at": fetched_at,
        "checked_at": fetched_at,
        "row_count": len(matrix),
        "column_count": _matrix_width(matrix),
        "snapshots": snapshots,
        "stream": stream_result,
    }
    _write_json(_manifest_path(cache_dir, dataset.key), new_manifest)
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
        "cache_dir": str(cache_dir),
    }


def read_manifest(cache_dir: Path, dataset_key: str) -> dict[str, Any]:
    path = _manifest_path(cache_dir, dataset_key)
    if not path.exists():
        return {}
    return _read_json(path)


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
    rows = _matrix_to_rows(dataset.key, matrix[1:], start_row_index=2)
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
        "rows": rows,
        "columns": _matrix_columns(matrix),
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
    new_events = 0
    updated_events = 0
    ordered_keys: list[str] = []
    for row in rows:
        key = event_key_for_row(dataset, row)
        normalized_key = normalized_event_key_for_row(dataset, row)
        ordered_keys.append(key)
        if key in existing:
            event = existing[key]
            event["last_seen_at"] = fetched_at
            event["seen_count"] = int(event.get("seen_count") or 1) + 1
            event["normalized_event_key"] = normalized_key
            event["values"] = row
            updated_events += 1
        else:
            existing[key] = {
                "event_key": key,
                "normalized_event_key": normalized_key,
                "first_seen_at": fetched_at,
                "last_seen_at": fetched_at,
                "seen_count": 1,
                "event_time": _event_time(dataset, row),
                "values": row,
            }
            new_events += 1
    previous_only = [key for key in existing if key not in set(ordered_keys)]
    events = [existing[key] for key in ordered_keys if key in existing] + [existing[key] for key in previous_only]
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


def _stream_display_matrix(cache_dir: Path, dataset: DatasetSpec, latest_matrix: list[list[str]]) -> list[list[str]]:
    path = _stream_path(cache_dir, dataset.key)
    if not path.exists():
        return latest_matrix
    state = _read_json(path)
    header = state.get("header")
    if not isinstance(header, list) or not header:
        return latest_matrix
    top = latest_matrix[:1]
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


def _matrix_columns(matrix: list[list[str]]) -> list[str]:
    width = _matrix_width(matrix[1:] if len(matrix) > 1 else matrix)
    return [_column_label(index) for index in range(width)]


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
        "rows": [],
        "columns": [],
        "fetched_at": "",
    }


def _stream_event_count(cache_dir: Path, dataset_key: str) -> int:
    path = _stream_path(cache_dir, dataset_key)
    if not path.exists():
        return 0
    return len(_read_json(path).get("events") or [])


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
    if path.name.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as file:
            return json.load(file)
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.name.endswith(".gz"):
        with gzip.open(tmp, "wt", encoding="utf-8") as file:
            file.write(text)
    else:
        tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


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
