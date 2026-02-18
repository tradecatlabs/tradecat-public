from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class CardHeader:
    title: str
    update_time: str = "-"
    sort_desc: str = "-"


@dataclass(frozen=True)
class CardHint:
    text: str = "-"


@dataclass(frozen=True)
class CardTgRef:
    chat_id: int | None = None
    message_id: int | None = None
    url: str | None = None


@dataclass(frozen=True)
class CardTable:
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class CardRaw:
    telegram_text_full: str = ""
    payload_json_full: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CardEvent:
    schema_version: int
    card_key: str
    ts_utc: str
    source_service: str
    card_type: str
    header: CardHeader
    params: dict[str, Any] = field(default_factory=dict)
    table: CardTable = field(default_factory=CardTable)
    hint: CardHint = field(default_factory=CardHint)
    tg: CardTgRef = field(default_factory=CardTgRef)
    raw: CardRaw = field(default_factory=CardRaw)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # 兼容 PRD 字段名：raw.telegram_text_full / raw.payload_json_full
        data["raw"]["telegram_text_full"] = data["raw"].pop("telegram_text_full", "")
        data["raw"]["payload_json_full"] = data["raw"].pop("payload_json_full", {})
        return data
