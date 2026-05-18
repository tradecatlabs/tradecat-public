from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

from tradecat_terminal.registry import DatasetSpec, list_datasets
from tradecat_terminal.sheets import find_header_row_index, is_section_header_row, normalize_headers
from tradecat_terminal.state import atomic_write_json, locked_path, read_json_file

DATASET_SCHEMA = "tradecat.dataset.v1"
CACHE_MANIFEST_SCHEMA = "tradecat.cache_manifest.v1"
LATEST_JSON_FILE = "latest.json"
LATEST_JSONL_FILE = "latest.jsonl"
LATEST_CSV_FILE = "latest.csv"
MANIFEST_FILE = "manifest.json"
SYMBOL_VALUE_RE = re.compile(r"^[A-Z0-9]{2,24}(?:USDT)?$")
BINANCE_FUTURES_URL_TEMPLATE = "https://www.binance.com/zh-CN/futures/{symbol}?type=perpetual"


def write_structured_latest(
    cache_dir: Path,
    dataset: DatasetSpec,
    matrix: list[list[str]],
    *,
    fetched_at: str,
    matrix_hash: str,
    previous_hash: str,
    changed: bool,
    snapshot_ref: str,
    status: str,
) -> dict[str, Any]:
    payload = _structured_dataset_payload(
        dataset,
        matrix,
        fetched_at=fetched_at,
        matrix_hash=matrix_hash,
        previous_hash=previous_hash,
        changed=changed,
        snapshot_ref=snapshot_ref,
        status=status,
    )
    dataset_dir = _dataset_dir(cache_dir, dataset.key)
    _write_json(dataset_dir / LATEST_JSON_FILE, payload)
    _write_jsonl(dataset_dir / LATEST_JSONL_FILE, payload)
    _write_clean_csv(dataset_dir / LATEST_CSV_FILE, payload)
    return payload


def write_cache_manifest(cache_dir: Path) -> None:
    with locked_path(cache_dir / MANIFEST_FILE):
        datasets: list[dict[str, Any]] = []
        for dataset in list_datasets(include_inactive=True):
            try:
                manifest = _read_json(_dataset_dir(cache_dir, dataset.key) / MANIFEST_FILE)
            except Exception:
                manifest = {}
            datasets.append(
                {
                    "dataset_key": dataset.key,
                    "display_name": dataset.tab_name,
                    "workbook": dataset.workbook_key,
                    "tab_name": dataset.tab_name,
                    "mode": dataset.data_mode,
                    "primary_key": _manifest_primary_key(cache_dir, dataset),
                    "latest_json": f"datasets/{dataset.key}/{LATEST_JSON_FILE}",
                    "latest_jsonl": f"datasets/{dataset.key}/{LATEST_JSONL_FILE}",
                    "latest_csv": f"datasets/{dataset.key}/{LATEST_CSV_FILE}",
                    "snapshot_dir": f"datasets/{dataset.key}/snapshots",
                    "snapshot_count": len(manifest.get("snapshots") or []),
                    "row_count": manifest.get("row_count", 0),
                    "column_count": manifest.get("column_count", 0),
                    "content_hash": manifest.get("current_hash", ""),
                    "last_success_at_utc8": manifest.get("fetched_at", ""),
                    "last_status": "available" if manifest else "missing",
                    "enabled": dataset.active,
                }
            )
        _write_json(
            cache_dir / MANIFEST_FILE,
            {
                "schema": CACHE_MANIFEST_SCHEMA,
                "app": {
                    "name": "TradeCat",
                    "cache_version": "1",
                    "generated_by": "tradecat",
                    "generated_at_utc8": _now_iso(),
                },
                "cache": {
                    "root": str(cache_dir),
                    "mode": "local_structured_cache",
                    "storage": "json_files",
                    "latest_policy": "overwrite",
                    "snapshot_policy": "append_on_content_hash_change",
                },
                "datasets": datasets,
            },
        )


def _structured_dataset_payload(
    dataset: DatasetSpec,
    matrix: list[list[str]],
    *,
    fetched_at: str,
    matrix_hash: str,
    previous_hash: str,
    changed: bool,
    snapshot_ref: str,
    status: str,
) -> dict[str, Any]:
    layout = _structured_layout(matrix)
    header_index = int(layout["physical_rows"]["header_row"]) - 1
    header = _logical_header(matrix, header_index)
    primary_key = _primary_key_for_dataset(dataset, header)
    columns = _structured_columns(header, dataset, primary_key)
    rows = _structured_rows(dataset, matrix, header, header_index=header_index, primary_key=primary_key)
    return {
        "schema": DATASET_SCHEMA,
        "dataset": {
            "dataset_key": dataset.key,
            "display_name": dataset.tab_name,
            "workbook": dataset.workbook_key,
            "tab_name": dataset.tab_name,
            "mode": dataset.data_mode,
            "description": dataset.description,
        },
        "source": {
            "type": "google_sheets",
            "spreadsheet_id": dataset.workbook().spreadsheet_id,
            "gid": dataset.gid,
            "export_format": "csv",
            "export_url": dataset.export_url(),
        },
        "sync": {
            "status": status,
            "fetched_at_utc8": fetched_at,
            "remote_updated_at_utc8": str(layout.get("meta", {}).get("导出时间(UTC+8)") or ""),
            "content_hash": matrix_hash,
            "previous_content_hash": previous_hash,
            "changed": changed,
            "wrote_snapshot": changed,
            "snapshot_id": _snapshot_id_from_ref(snapshot_ref),
            "snapshot_path": f"datasets/{dataset.key}/{snapshot_ref}" if snapshot_ref else "",
        },
        "layout": layout,
        "columns": columns,
        "rows": rows,
        "indexes": _structured_indexes(dataset, primary_key, rows),
        "stats": {
            "row_count": len(rows),
            "column_count": len(header),
            "data_cell_count": len(rows) * len(header),
            "empty_cell_count": sum(
                1 for row in rows for value in row.get("values", {}).values() if str(value).strip() == ""
            ),
        },
    }


def _structured_layout(matrix: list[list[str]]) -> dict[str, Any]:
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
    header_index = find_header_row_index(matrix)
    top_lines, top_rows = _extract_top_lines(matrix[:header_index])
    meta, meta_row = _extract_meta(matrix[:header_index])
    return {
        "top_lines": top_lines,
        "meta": meta,
        "physical_rows": {
            "top_start_row": min(top_rows) if top_rows else None,
            "top_end_row": max(top_rows) if top_rows else None,
            "meta_row": meta_row,
            "header_row": header_index + 1,
            "data_start_row": header_index + 2,
        },
    }


def _extract_top_lines(rows: list[list[str]]) -> tuple[list[str], list[int]]:
    lines: list[str] = []
    row_numbers: list[int] = []
    for row_index, row in enumerate(rows, start=1):
        for value in row:
            for line in str(value).splitlines():
                clean = line.strip()
                if clean.startswith(("http://", "https://")):
                    lines.append(clean)
                    row_numbers.append(row_index)
    return lines, row_numbers


def _extract_meta(rows: list[list[str]]) -> tuple[dict[str, str], int | None]:
    for row_index, row in enumerate(rows, start=1):
        tokens = _meta_tokens(row)
        if not tokens:
            continue
        if tokens[0] != "数据源" and "数据源" not in tokens:
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


def _structured_columns(header: list[str], dataset: DatasetSpec, primary_key: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, name in enumerate(header):
        role = _column_role(dataset, name, primary_key)
        rows.append(
            {
                "name": name,
                "index": index,
                "letter": _column_label(index),
                "type": _column_type(name),
                "role": role,
                "nullable": role != "primary_key",
            }
        )
    return rows


def _structured_rows(
    dataset: DatasetSpec,
    matrix: list[list[str]],
    header: list[str],
    *,
    header_index: int,
    primary_key: str | None,
) -> list[dict[str, Any]]:
    if header_index < len(matrix) and is_section_header_row(matrix[header_index]):
        return _sectioned_structured_rows(dataset, matrix, header_index=header_index, primary_key=primary_key)
    rows: list[dict[str, Any]] = []
    for raw_index, raw_row in enumerate(matrix[header_index + 1 :], start=header_index + 2):
        if not any(str(cell).strip() for cell in raw_row):
            continue
        padded = [*raw_row, *([""] * max(0, len(header) - len(raw_row)))]
        values = {header[index]: str(padded[index]) for index in range(len(header))}
        typed_values = {name: _typed_value(name, value) for name, value in values.items()}
        key = _row_key(dataset, values, primary_key)
        row = {
            "row_index": raw_index,
            "row_number": len(rows) + 1,
            "key": key,
            "values": values,
            "typed_values": typed_values,
            "links": _row_links(values),
        }
        event_time = _event_time(dataset, values)
        if event_time:
            row["event_time"] = event_time
        rows.append(row)
    return rows


def _logical_header(matrix: list[list[str]], header_index: int) -> list[str]:
    if header_index < len(matrix) and is_section_header_row(matrix[header_index]):
        header: list[str] = ["榜单", "榜单名", "源行号"]
        for row in matrix[header_index:]:
            if not is_section_header_row(row):
                continue
            for column in normalize_headers([str(cell) for cell in row[1:]]):
                if column not in header:
                    header.append(column)
        return header
    raw_header = matrix[header_index] if 0 <= header_index < len(matrix) else []
    width = max(_matrix_width(matrix[header_index:]), len(raw_header))
    return normalize_headers([*raw_header, *([""] * max(0, width - len(raw_header)))])


def _sectioned_structured_rows(
    dataset: DatasetSpec,
    matrix: list[list[str]],
    *,
    header_index: int,
    primary_key: str | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    section_title = ""
    section_headers: list[str] = []
    for raw_index, raw_row in enumerate(matrix[header_index:], start=header_index + 1):
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
        values = {"榜单": section_title, "榜单名": section_title, "源行号": str(raw_index)}
        values.update({section_headers[index]: padded[index] for index in range(len(section_headers))})
        typed_values = {name: _typed_value(name, value) for name, value in values.items()}
        key = _row_key(dataset, values, primary_key)
        row = {
            "row_index": raw_index,
            "row_number": len(rows) + 1,
            "key": key,
            "values": values,
            "typed_values": typed_values,
            "links": _row_links(values),
            "section": section_title,
        }
        event_time = _event_time(dataset, values)
        if event_time:
            row["event_time"] = event_time
        rows.append(row)
    return rows


def _primary_key_for_dataset(dataset: DatasetSpec, header: list[str]) -> str | None:
    if dataset.is_stream():
        return "key"
    preferred = ("交易对", "合约代码", "币种符号", "symbol", "Symbol", "SYMBOL", *dataset.index_columns)
    for column in preferred:
        if column in header:
            return column
    return None


def _row_key(dataset: DatasetSpec, values: dict[str, str], primary_key: str | None) -> str:
    if primary_key and primary_key != "key":
        value = str(values.get(primary_key, "")).strip()
        if value:
            return _normalize_symbol(value) if primary_key in {"交易对", "合约代码", "币种符号", "symbol", "Symbol", "SYMBOL"} else value
    if dataset.is_stream():
        return f"sha256:{_event_key_for_row(dataset, values)[:16]}"
    return f"sha256:{_hash_json(values)[:16]}"


def _structured_indexes(dataset: DatasetSpec, primary_key: str | None, rows: list[dict[str, Any]]) -> dict[str, Any]:
    row_by_key = {str(row.get("key")): index for index, row in enumerate(rows) if row.get("key")}
    payload: dict[str, Any] = {"primary_key": primary_key, "row_by_key": row_by_key}
    if primary_key and primary_key != "key":
        payload["primary_key_values"] = [row.get("key") for row in rows if row.get("key")]
    if dataset.is_stream():
        payload["time_column"] = _first_existing_column(rows, ("时间(北京)", "时间", "time", "timestamp"))
    return payload


def _first_existing_column(rows: list[dict[str, Any]], names: tuple[str, ...]) -> str | None:
    if not rows:
        return None
    values = rows[0].get("values") if isinstance(rows[0], dict) else {}
    if not isinstance(values, dict):
        return None
    for name in names:
        if name in values:
            return name
    return None


def _column_role(dataset: DatasetSpec, name: str, primary_key: str | None) -> str:
    if name == primary_key:
        return "primary_key"
    if name in {"时间(北京)", "时间", "time", "timestamp"}:
        return "event_time"
    if name in {"内容", "content", "正文"}:
        return "body"
    if name in {"排名", "序号", "rank", "Rank"}:
        return "rank"
    if name in dataset.index_columns:
        return "index"
    if _column_type(name) in {"integer", "number", "percent"}:
        return "metric"
    return "field"


def _column_type(name: str) -> str:
    lower = name.lower()
    if name in {"时间(北京)", "时间", "time", "timestamp"}:
        return "datetime"
    if _is_text_column_name(name):
        return "string"
    if "%" in name:
        return "percent"
    if name in {"排名", "序号", "rank", "Rank"} or any(token in name for token in ("根数", "合约数", "条数", "连续bars")):
        return "integer"
    if any(token in lower for token in ("score", "value", "amount", "ratio", "gap")):
        return "number"
    if any(token in name for token in ("分", "量", "额", "比", "强度", "位置", "份额", "持仓", "账户")):
        return "number"
    return "string"


def _is_text_column_name(name: str) -> bool:
    lower = name.lower()
    text_tokens = (
        "标签",
        "方向",
        "口径",
        "模式",
        "标题",
        "内容",
        "交易对",
        "合约代码",
        "币种",
        "数据源",
        "schema",
        "symbol",
    )
    return any(token in lower or token in name for token in text_tokens)


def _typed_value(name: str, value: str) -> Any:
    text = str(value).strip()
    if text == "":
        return None
    if _column_type(name) == "percent":
        return _parse_percent(text)
    if _column_type(name) in {"integer", "number"}:
        return _parse_number(text)
    if _column_type(name) == "datetime":
        return _parse_datetime_utc8(text)
    parsed = _parse_number(text)
    return parsed if parsed is not None and _looks_numeric(text) else text


def _parse_percent(value: str) -> float | str:
    text = str(value).strip()
    try:
        return float(text.rstrip("%").replace(",", "")) / 100.0
    except ValueError:
        return value


def _parse_number(value: str) -> int | float | None:
    text = str(value).strip().replace(",", "")
    if text == "":
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return int(number) if number.is_integer() and not any(token in text for token in (".", "e", "E")) else number


def _looks_numeric(value: str) -> bool:
    return _parse_number(value) is not None


def _parse_datetime_utc8(value: str) -> str:
    text = str(value).strip()
    if not text:
        return text
    if "T" in text and ("+08:00" in text or text.endswith("Z")):
        return text
    if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", text):
        return text.replace(" ", "T") + "+08:00"
    return text


def _row_links(values: dict[str, str]) -> dict[str, str]:
    links: dict[str, str] = {}
    for name in ("交易对", "合约代码", "币种符号", "symbol", "Symbol", "SYMBOL"):
        value = str(values.get(name, "")).strip()
        if not value:
            continue
        symbol = _normalize_symbol(value)
        if SYMBOL_VALUE_RE.match(symbol):
            futures_symbol = f"{symbol}USDT" if not symbol.endswith("USDT") else symbol
            links[name] = BINANCE_FUTURES_URL_TEMPLATE.format(symbol=futures_symbol)
            break
    return links


def _normalize_symbol(value: str) -> str:
    symbol = str(value).strip().upper()
    return symbol[:-4] if symbol.endswith("USDT") else symbol


def _write_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    dataset_key = str(payload.get("dataset", {}).get("dataset_key") or "")
    lines = []
    for row in payload.get("rows", []):
        if not isinstance(row, dict):
            continue
        values = row.get("values") if isinstance(row.get("values"), dict) else {}
        lines.append(
            json.dumps(
                {"dataset_key": dataset_key, "row_index": row.get("row_index"), "key": row.get("key"), **values},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    tmp.replace(path)


def _write_clean_csv(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    columns = [str(column.get("name")) for column in payload.get("columns", []) if isinstance(column, dict)]
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in payload.get("rows", []):
        values = row.get("values") if isinstance(row, dict) and isinstance(row.get("values"), dict) else {}
        writer.writerow([values.get(column, "") for column in columns])
    tmp.write_text(buffer.getvalue(), encoding="utf-8")
    tmp.replace(path)


def _manifest_primary_key(cache_dir: Path, dataset: DatasetSpec) -> str | None:
    path = _dataset_dir(cache_dir, dataset.key) / LATEST_JSON_FILE
    if not path.exists():
        return None
    payload = _read_json(path)
    primary_key = payload.get("indexes", {}).get("primary_key")
    return str(primary_key) if primary_key else None


def _snapshot_id_from_ref(snapshot_ref: str) -> str:
    name = Path(snapshot_ref).name
    if not name:
        return ""
    return name.removesuffix(".gz").removesuffix(".json")


def _event_key_for_row(dataset: DatasetSpec, row: dict[str, str]) -> str:
    values = [str(row.get(column, "")).strip() for column in dataset.event_key_columns]
    if dataset.event_key_columns and all(values):
        return _hash_json({"columns": list(dataset.event_key_columns), "values": values})
    return _hash_json(row)


def _event_time(dataset: DatasetSpec, row: dict[str, str]) -> str:
    for column in (*dataset.event_key_columns, "时间(北京)", "时间", "time", "timestamp"):
        value = str(row.get(column, "")).strip()
        if value:
            return value
    return ""


def _dataset_dir(cache_dir: Path, dataset_key: str) -> Path:
    return cache_dir / "datasets" / dataset_key


def _matrix_width(matrix: list[list[str]]) -> int:
    return max((len(row) for row in matrix), default=0)


def _column_label(index: int) -> str:
    value = int(index)
    label = ""
    while True:
        value, remainder = divmod(value, 26)
        label = chr(ord("A") + remainder) + label
        if value == 0:
            return label
        value -= 1


def _read_json(path: Path) -> dict[str, Any]:
    return read_json_file(path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_json(path, payload)


def _hash_json(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).astimezone().isoformat()
