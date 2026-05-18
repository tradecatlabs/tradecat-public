from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib.resources import files
from typing import Literal
from urllib.parse import urlencode

DataMode = Literal["snapshot", "stream"]
DEFAULT_LANG = "zh"


class UnknownDatasetError(ValueError):
    """Raised only when a requested dataset_key is absent from the registry."""


@dataclass(frozen=True)
class WorkbookSource:
    key: str
    spreadsheet_id: str
    description: str


@dataclass(frozen=True)
class DatasetSpec:
    key: str
    workbook_key: str
    tab_name: str
    gid: str | None
    description: str
    data_mode: DataMode
    index_columns: tuple[str, ...] = field(default_factory=tuple)
    event_key_columns: tuple[str, ...] = field(default_factory=tuple)
    display_names: dict[str, str] = field(default_factory=dict)
    history_policy: str = "permanent"
    source_poll_interval_seconds: float | None = None
    source_fetch_timeout_seconds: float | None = None
    table_region_policy: dict[str, str | int | None] = field(default_factory=dict)
    active: bool = True

    def workbook(self) -> WorkbookSource:
        try:
            return WORKBOOKS[self.workbook_key]
        except KeyError as exc:
            raise ValueError(f"dataset {self.key} 引用了未知 workbook: {self.workbook_key}") from exc

    def export_url(self) -> str:
        workbook = self.workbook()
        if self.gid:
            query = urlencode({"format": "csv", "gid": self.gid})
            return f"https://docs.google.com/spreadsheets/d/{workbook.spreadsheet_id}/export?{query}"
        query = urlencode({"tqx": "out:csv", "sheet": self.tab_name})
        return f"https://docs.google.com/spreadsheets/d/{workbook.spreadsheet_id}/gviz/tq?{query}"

    def is_snapshot(self) -> bool:
        return self.data_mode == "snapshot"

    def is_stream(self) -> bool:
        return self.data_mode == "stream"

    def display_name(self, lang: str | None = None) -> str:
        resolved = lang if lang in self.display_names else DEFAULT_LANG
        return self.display_names.get(resolved) or self.display_names.get(DEFAULT_LANG) or self.tab_name


REGISTRY_RESOURCE = "dataset_registry.json"


def _load_registry_payload() -> dict[str, object]:
    text = files("tradecat_sources").joinpath(REGISTRY_RESOURCE).read_text(encoding="utf-8")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError(f"{REGISTRY_RESOURCE} 必须是 JSON object")
    return payload


def _load_workbooks(payload: dict[str, object]) -> dict[str, WorkbookSource]:
    raw_workbooks = payload.get("workbooks")
    if not isinstance(raw_workbooks, dict):
        raise ValueError(f"{REGISTRY_RESOURCE} 缺少 workbooks")
    workbooks: dict[str, WorkbookSource] = {}
    for key, raw in raw_workbooks.items():
        if not isinstance(raw, dict):
            raise ValueError(f"workbook {key} 必须是 object")
        workbooks[str(key)] = WorkbookSource(
            key=str(key),
            spreadsheet_id=str(raw.get("spreadsheet_id") or ""),
            description=str(raw.get("description") or ""),
        )
    return workbooks


def _load_datasets(payload: dict[str, object]) -> dict[str, DatasetSpec]:
    raw_datasets = payload.get("datasets")
    if not isinstance(raw_datasets, dict):
        raise ValueError(f"{REGISTRY_RESOURCE} 缺少 datasets")
    datasets: dict[str, DatasetSpec] = {}
    for key, raw in raw_datasets.items():
        if not isinstance(raw, dict):
            raise ValueError(f"dataset {key} 必须是 object")
        data_mode = str(raw.get("data_mode") or "snapshot")
        if data_mode not in ("snapshot", "stream"):
            raise ValueError(f"dataset {key} data_mode 非法: {data_mode}")
        datasets[str(key)] = DatasetSpec(
            key=str(key),
            workbook_key=str(raw.get("workbook_key") or ""),
            tab_name=str(raw.get("tab_name") or ""),
            gid=str(raw.get("gid")) if raw.get("gid") is not None else None,
            description=str(raw.get("description") or ""),
            data_mode=data_mode,  # type: ignore[arg-type]
            index_columns=tuple(str(item) for item in raw.get("index_columns") or []),
            event_key_columns=tuple(str(item) for item in raw.get("event_key_columns") or []),
            display_names={str(lang): str(name) for lang, name in (raw.get("display_names") or {}).items()}
            if isinstance(raw.get("display_names"), dict)
            else {},
            history_policy=str(raw.get("history_policy") or "permanent"),
            source_poll_interval_seconds=_optional_float(raw.get("source_poll_interval_seconds")),
            source_fetch_timeout_seconds=_optional_float(raw.get("source_fetch_timeout_seconds")),
            table_region_policy={str(name): value for name, value in (raw.get("table_region_policy") or {}).items()}
            if isinstance(raw.get("table_region_policy"), dict)
            else {},
            active=bool(raw.get("active", True)),
        )
    return datasets


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


_REGISTRY_PAYLOAD = _load_registry_payload()
WORKBOOKS = _load_workbooks(_REGISTRY_PAYLOAD)
DATASETS = _load_datasets(_REGISTRY_PAYLOAD)


def get_dataset(key: str) -> DatasetSpec:
    try:
        return DATASETS[key]
    except KeyError as exc:
        available = ", ".join(sorted(DATASETS))
        raise UnknownDatasetError(f"未知 dataset_key: {key}; 可用值: {available}") from exc


def list_active_datasets() -> list[DatasetSpec]:
    return [dataset for dataset in DATASETS.values() if dataset.active]


def list_datasets(include_inactive: bool = False) -> list[DatasetSpec]:
    return list(DATASETS.values()) if include_inactive else list_active_datasets()


def dataset_to_dict(dataset: DatasetSpec) -> dict[str, object]:
    from tradecat_sources.dataset_contract import dataset_consumption_contract_summary

    return {
        "key": dataset.key,
        "active": dataset.active,
        "workbook_key": dataset.workbook_key,
        "tab_name": dataset.tab_name,
        "gid": dataset.gid,
        "description": dataset.description,
        "display_names": dict(dataset.display_names),
        "data_mode": dataset.data_mode,
        "index_columns": list(dataset.index_columns),
        "event_key_columns": list(dataset.event_key_columns),
        "history_policy": dataset.history_policy,
        "source_poll_interval_seconds": dataset.source_poll_interval_seconds,
        "source_fetch_timeout_seconds": dataset.source_fetch_timeout_seconds,
        "table_region_policy": dict(dataset.table_region_policy),
        "consumption_contract": dataset_consumption_contract_summary(dataset.key),
    }
