from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlencode

DataMode = Literal["snapshot", "stream"]


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
    history_policy: str = "permanent"
    tui_probe_interval_seconds: float | None = None
    tui_fetch_timeout_seconds: float | None = None
    table_region_policy: dict[str, str | int | None] = field(default_factory=dict)
    active: bool = True

    def workbook(self) -> WorkbookSource:
        try:
            return WORKBOOKS[self.workbook_key]
        except KeyError as exc:
            raise ValueError(f"dataset {self.key} 引用了未知 workbook: {self.workbook_key}") from exc

    def export_url(self) -> str:
        if not self.gid:
            raise ValueError(f"dataset {self.key} 缺少 gid；请更新内置 dataset registry")
        workbook = self.workbook()
        query = urlencode({"format": "csv", "gid": self.gid})
        return f"https://docs.google.com/spreadsheets/d/{workbook.spreadsheet_id}/export?{query}"

    def is_snapshot(self) -> bool:
        return self.data_mode == "snapshot"

    def is_stream(self) -> bool:
        return self.data_mode == "stream"


WORKBOOKS: dict[str, WorkbookSource] = {
    "market_data": WorkbookSource(
        key="market_data",
        spreadsheet_id="1k16nGFCE7oBXrEqvTpHSA2Z5530GM_kou-wiWklTsfY",
        description="交易猫市场数据入口",
    ),
    "alternative_data": WorkbookSource(
        key="alternative_data",
        spreadsheet_id="1q-2sXGsFYsKf3nV5u5golTVrLH5sfc0doiWwz_kavE4",
        description="交易猫另类数据入口",
    ),
}


DATASETS: dict[str, DatasetSpec] = {
    "market_snapshot": DatasetSpec(
        key="market_snapshot",
        workbook_key="market_data",
        tab_name="全市场快照",
        gid="1904613219",
        description="全市场主宽表快照，本地按 JSON 快照文件缓存。",
        data_mode="snapshot",
        index_columns=("排名", "序号", "交易对", "合约代码", "币种符号", "symbol", "Symbol", "SYMBOL"),
        table_region_policy={"header": "auto", "top": "public_info_and_meta"},
    ),
    "anomaly_panel": DatasetSpec(
        key="anomaly_panel",
        workbook_key="market_data",
        tab_name="异动面板",
        gid="1915220137",
        description="市场异动终端面板快照缓存。",
        data_mode="snapshot",
        index_columns=("榜单", "榜单名", "序号", "交易对", "合约代码", "币种符号", "symbol", "Symbol", "SYMBOL"),
        table_region_policy={"header": "auto", "top": "public_info_and_meta"},
    ),
    "market_stats": DatasetSpec(
        key="market_stats",
        workbook_key="market_data",
        tab_name="全市场统计",
        gid="1161752788",
        description="全市场统计汇总快照缓存。",
        data_mode="snapshot",
        index_columns=("窗口", "覆盖合约数", "合约数", "交易对口径"),
        table_region_policy={"header": "auto", "top": "public_info_and_meta"},
    ),
    "event_stream": DatasetSpec(
        key="event_stream",
        workbook_key="alternative_data",
        tab_name="事件流",
        gid="1419246950",
        description="另类数据事件流增量缓存。",
        data_mode="stream",
        index_columns=("时间(北京)", "内容"),
        event_key_columns=("时间(北京)", "内容"),
        tui_probe_interval_seconds=1.5,
        tui_fetch_timeout_seconds=1.0,
        table_region_policy={"header": "auto", "top": "public_info_and_meta"},
    ),
}


def get_dataset(key: str) -> DatasetSpec:
    try:
        return DATASETS[key]
    except KeyError as exc:
        available = ", ".join(sorted(DATASETS))
        raise ValueError(f"未知 dataset_key: {key}; 可用值: {available}") from exc


def list_active_datasets() -> list[DatasetSpec]:
    return [dataset for dataset in DATASETS.values() if dataset.active]


def list_datasets(include_inactive: bool = False) -> list[DatasetSpec]:
    return list(DATASETS.values()) if include_inactive else list_active_datasets()


def dataset_to_dict(dataset: DatasetSpec) -> dict[str, object]:
    return {
        "key": dataset.key,
        "active": dataset.active,
        "workbook_key": dataset.workbook_key,
        "tab_name": dataset.tab_name,
        "gid": dataset.gid,
        "description": dataset.description,
        "data_mode": dataset.data_mode,
        "index_columns": list(dataset.index_columns),
        "event_key_columns": list(dataset.event_key_columns),
        "history_policy": dataset.history_policy,
        "tui_probe_interval_seconds": dataset.tui_probe_interval_seconds,
        "tui_fetch_timeout_seconds": dataset.tui_fetch_timeout_seconds,
        "table_region_policy": dict(dataset.table_region_policy),
    }
