from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from src.signing import hmac_sha256_hex


@dataclass(frozen=True)
class WebhookResponse:
    ok: bool
    status: int
    body: dict[str, Any]


class SheetsWebhookClient:
    def __init__(self, url: str, secret: str, *, timeout_seconds: int = 10) -> None:
        self._url = url
        self._secret = secret
        self._timeout_seconds = timeout_seconds

    def post_json(self, payload: dict[str, Any]) -> WebhookResponse:
        body_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ts = str(int(time.time() * 1000))
        nonce = str(uuid.uuid4())
        signature = hmac_sha256_hex(self._secret, f"{ts}.{nonce}.{body_bytes.decode('utf-8')}")

        # Apps Script 对自定义 Header 的读取不稳定：同时把签名塞到 query 参数（双通道兼容）
        parsed = urlparse(self._url)
        q = dict(parse_qsl(parsed.query, keep_blank_values=True))
        q.update({"X-TC-Timestamp": ts, "X-TC-Nonce": nonce, "X-TC-Signature": signature})
        url = urlunparse(parsed._replace(query=urlencode(q)))

        req = Request(
            url,
            data=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-TC-Timestamp": ts,
                "X-TC-Nonce": nonce,
                "X-TC-Signature": signature,
                "User-Agent": "tradecat-sheets-service/1.0",
            },
            method="POST",
        )

        try:
            with urlopen(req, timeout=self._timeout_seconds) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    parsed = {"raw": raw}
                ok = bool(parsed.get("ok", True))
                return WebhookResponse(ok=ok, status=getattr(resp, "status", 200), body=parsed)
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
            return WebhookResponse(ok=False, status=exc.code, body={"error": "http_error", "raw": raw})
        except URLError as exc:
            return WebhookResponse(ok=False, status=0, body={"error": "url_error", "reason": str(exc.reason)})
