from __future__ import annotations

import json
from pathlib import Path
from typing import Any

AGENT_TRADE_THESIS_SCHEMA = "tradecat_auto.agent_trade_thesis.v1"
SCHEMA_VERSION = "1.0.0"


def load_agent_trade_thesis(path: Path | str | None, *, mode: str = "paper") -> dict[str, Any] | None:
    """Load an optional Agent trade thesis for paper/watch research only."""

    if str(mode or "paper").strip().lower() not in {"paper", "watch"}:
        return None
    text = str(path or "").strip()
    if not text:
        return None
    thesis_path = Path(text)
    if not thesis_path.exists():
        raise ValueError(f"agent_trade_thesis_load_failed: missing file: {thesis_path}")
    try:
        data = json.loads(thesis_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"agent_trade_thesis_load_failed: {thesis_path}: {exc}") from exc
    return normalize_agent_trade_thesis(data)


def normalize_agent_trade_thesis(value: Any) -> dict[str, Any] | None:
    """Accept a raw thesis object or a wrapper containing agent_trade_thesis."""

    if not isinstance(value, dict):
        raise ValueError("agent_trade_thesis must be a JSON object")
    candidate = value.get("agent_trade_thesis") if isinstance(value.get("agent_trade_thesis"), dict) else value
    if not isinstance(candidate, dict):
        raise ValueError("agent_trade_thesis must be a JSON object")
    schema = candidate.get("schema")
    if schema not in (None, "", AGENT_TRADE_THESIS_SCHEMA):
        raise ValueError(f"agent_trade_thesis schema must be {AGENT_TRADE_THESIS_SCHEMA}")
    schema_version = candidate.get("schema_version")
    if schema_version not in (None, "", SCHEMA_VERSION):
        raise ValueError(f"agent_trade_thesis schema_version must be {SCHEMA_VERSION}")
    return dict(candidate)


def paper_intent_from_agent_trade_thesis(agent_trade_thesis: dict[str, Any] | None) -> dict[str, Any]:
    thesis = agent_trade_thesis if isinstance(agent_trade_thesis, dict) else {}
    paper_intent = thesis.get("paper_intent")
    return dict(paper_intent) if isinstance(paper_intent, dict) else {}
