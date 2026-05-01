from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tradecat_terminal.cache import read_cached_view
from tradecat_terminal.header_aliases import alias_headers
from tradecat_terminal.i18n import resolve_lang
from tradecat_terminal.registry import get_dataset


@dataclass(frozen=True)
class DisplayColumn:
    raw_name: str
    display_name: str
    letter: str
    role: str = "field"
    type: str = "string"


@dataclass(frozen=True)
class DisplayRow:
    row_index: int
    row_number: int
    key: str
    values: dict[str, str]
    raw_values: dict[str, str]
    physical_values: dict[str, str]
    display_column_by_raw: dict[str, str]
    links: dict[str, str]


@dataclass(frozen=True)
class DatasetView:
    ok: bool
    cache_dir: str
    dataset_key: str
    tab_name: str
    display_name: str
    data_mode: str
    batch_index: int
    batch_count: int
    batch_label: str
    content_hash: str
    top_lines: list[str]
    meta: dict[str, str]
    layout: dict[str, Any]
    columns: list[str]
    raw_columns: list[str]
    physical_columns: list[str]
    column_meta: list[DisplayColumn]
    rows: list[DisplayRow]
    fetched_at: str
    lang: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["column_meta"] = [asdict(column) for column in self.column_meta]
        payload["rows"] = [asdict(row) for row in self.rows]
        return payload


def build_dataset_view(
    cache_dir: Path,
    dataset_key: str,
    *,
    batch_index: int = 0,
    live: bool = True,
    lang: str | None = None,
) -> dict[str, Any]:
    resolved_lang = resolve_lang(lang)
    base = read_cached_view(cache_dir, dataset_key, batch_index=batch_index, live=live)
    dataset = get_dataset(dataset_key)
    raw_columns = [str(column) for column in base.get("table_columns") or []]
    physical_columns = [str(column) for column in base.get("physical_columns") or base.get("columns") or []]
    if not raw_columns:
        raw_columns = physical_columns
    source_rows = _physical_table_rows(base)
    display_columns = alias_headers(raw_columns, resolved_lang)
    display_by_raw = dict(zip(raw_columns, display_columns, strict=False))
    physical_by_raw = dict(zip(raw_columns, physical_columns, strict=False))
    type_by_raw = {
        str(column.get("name")): str(column.get("type") or "string")
        for column in base.get("structured_columns") or []
        if isinstance(column, dict)
    }
    role_by_raw = {
        str(column.get("name")): str(column.get("role") or "field")
        for column in base.get("structured_columns") or []
        if isinstance(column, dict)
    }
    columns = [
        DisplayColumn(
            raw_name=raw,
            display_name=display_by_raw.get(raw, raw),
            letter=physical_by_raw.get(raw, ""),
            role=role_by_raw.get(raw, "field"),
            type=type_by_raw.get(raw, "string"),
        )
        for raw in raw_columns
    ]
    rows = [_display_row(row, raw_columns, physical_columns, physical_by_raw) for row in source_rows]
    view = DatasetView(
        ok=bool(base.get("ok")),
        cache_dir=str(base.get("cache_dir") or cache_dir),
        dataset_key=dataset.key,
        tab_name=dataset.tab_name,
        display_name=dataset.display_name(resolved_lang),
        data_mode=dataset.data_mode,
        batch_index=int(base.get("batch_index") or 0),
        batch_count=int(base.get("batch_count") or 0),
        batch_label=str(base.get("batch_label") or ""),
        content_hash=str(base.get("content_hash") or ""),
        top_lines=[str(line) for line in base.get("display_top_lines") or base.get("top_lines") or []],
        meta={str(key): str(value) for key, value in (base.get("meta") or {}).items()},
        layout=base.get("layout") if isinstance(base.get("layout"), dict) else {},
        columns=physical_columns,
        raw_columns=raw_columns,
        physical_columns=physical_columns,
        column_meta=columns,
        rows=rows,
        fetched_at=str(base.get("fetched_at") or ""),
        lang=resolved_lang,
    )
    return view.to_dict()


def _physical_table_rows(base: dict[str, Any]) -> list[dict[str, Any]]:
    rows = list(base.get("rows") or [])
    layout = base.get("layout") if isinstance(base.get("layout"), dict) else {}
    physical_rows = layout.get("physical_rows") if isinstance(layout.get("physical_rows"), dict) else {}
    header_row = int(physical_rows.get("header_row") or 1)
    return [row for row in rows if int(row.get("row_index") or 0) >= header_row]


def _display_row(
    row: dict[str, Any],
    raw_columns: list[str],
    physical_columns: list[str],
    physical_by_raw: dict[str, str],
) -> DisplayRow:
    physical_values = {
        str(key): str(value)
        for key, value in (row.get("physical_values") or row.get("values") or {}).items()
        if value is not None
    }
    raw_values = {
        raw: str(physical_values.get(physical_columns[index], ""))
        for index, raw in enumerate(raw_columns)
        if index < len(physical_columns)
    }
    return DisplayRow(
        row_index=int(row.get("row_index") or 0),
        row_number=int(row.get("row_number") or 0),
        key=str(row.get("key") or ""),
        values=physical_values,
        raw_values=raw_values,
        physical_values=physical_values,
        display_column_by_raw=physical_by_raw,
        links={str(key): str(value) for key, value in (row.get("links") or {}).items()},
    )
