from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OutboxItem:
    offset: int
    payload: dict


class JsonlOutbox:
    def __init__(self, outbox_path: Path, checkpoint_path: Path) -> None:
        self._outbox_path = outbox_path
        self._checkpoint_path = checkpoint_path
        self._outbox_path.parent.mkdir(parents=True, exist_ok=True)
        self._checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, payload: dict) -> None:
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        with self._outbox_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def load_checkpoint(self) -> int:
        if not self._checkpoint_path.exists():
            return 0
        try:
            data = json.loads(self._checkpoint_path.read_text(encoding="utf-8"))
            return int(data.get("offset", 0))
        except Exception:
            return 0

    def save_checkpoint(self, offset: int) -> None:
        self._checkpoint_path.write_text(json.dumps({"offset": offset}, ensure_ascii=False), encoding="utf-8")

    def iter_unsent(self) -> Iterator[OutboxItem]:
        last = self.load_checkpoint()
        if not self._outbox_path.exists():
            return
        with self._outbox_path.open("r", encoding="utf-8") as f:
            for idx, line in enumerate(f, 1):
                if idx <= last:
                    continue
                s = line.strip()
                if not s:
                    continue
                try:
                    payload = json.loads(s)
                except Exception:
                    payload = {"error": "invalid_jsonl_line", "raw": s}
                yield OutboxItem(offset=idx, payload=payload)
