from __future__ import annotations

import json
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from src.signing import hmac_sha256_hex


@dataclass(frozen=True)
class MockState:
    secret: str
    data_dir: Path

    @property
    def seen_cards_path(self) -> Path:
        return self.data_dir / "seen_cards.json"

    @property
    def seen_nonces_path(self) -> Path:
        return self.data_dir / "seen_nonces.json"

    @property
    def received_path(self) -> Path:
        return self.data_dir / "received.jsonl"


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True), encoding="utf-8")


class _Handler(BaseHTTPRequestHandler):
    state: MockState

    def log_message(self, fmt: str, *args) -> None:
        # 静默，避免测试时刷屏
        return

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        q = parse_qs(parsed.query)
        ts = (q.get("X-TC-Timestamp") or [""])[0]
        nonce = (q.get("X-TC-Nonce") or [""])[0]
        sig = (q.get("X-TC-Signature") or [""])[0]

        raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0")).decode("utf-8", errors="replace")

        # auth
        if not ts or not nonce or not sig:
            return self._json(401, {"ok": False, "error": "missing_auth"})
        try:
            t = int(ts)
        except Exception:
            return self._json(401, {"ok": False, "error": "bad_timestamp"})
        if abs(int(time.time() * 1000) - t) > 5 * 60 * 1000:
            return self._json(401, {"ok": False, "error": "timestamp_out_of_window"})

        calc = hmac_sha256_hex(self.state.secret, f"{ts}.{nonce}.{raw}")
        if calc != sig:
            return self._json(401, {"ok": False, "error": "bad_signature"})

        nonces: dict[str, int] = _load_json(self.state.seen_nonces_path, {})
        if nonce in nonces:
            return self._json(409, {"ok": False, "error": "nonce_replay"})
        nonces[nonce] = t
        _save_json(self.state.seen_nonces_path, nonces)

        try:
            payload = json.loads(raw) if raw else {}
        except Exception:
            payload = {"error": "invalid_json", "raw": raw}

        card_key = str(payload.get("card_key") or "")
        if not card_key:
            return self._json(400, {"ok": False, "error": "missing_card_key"})

        seen_cards: dict[str, int] = _load_json(self.state.seen_cards_path, {})
        if card_key in seen_cards:
            return self._json(200, {"ok": True, "card_key": card_key, "idempotent": True})
        seen_cards[card_key] = t
        _save_json(self.state.seen_cards_path, seen_cards)

        with self.state.received_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

        return self._json(
            200,
            {
                "ok": True,
                "card_key": card_key,
                "idempotent": False,
                "dashboard": {"sheet": "看板", "col_l": "A", "col_r": "M", "row_y": 1, "height": 1},
            },
        )

    def _json(self, code: int, obj: dict[str, Any]) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve_mock_webhook(*, host: str, port: int, secret: str, data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    st = MockState(secret=secret, data_dir=data_dir)

    handler_cls = type("MockWebhookHandler", (_Handler,), {})
    handler_cls.state = st  # type: ignore[attr-defined]

    httpd = HTTPServer((host, port), handler_cls)
    print(f"mock webhook listening on http://{host}:{port} (secret={'set' if secret else 'empty'})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
