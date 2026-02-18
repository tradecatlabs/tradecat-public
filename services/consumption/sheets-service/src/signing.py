from __future__ import annotations

import hashlib
import hmac


def hmac_sha256_hex(secret: str, message: str) -> str:
    key = secret.encode("utf-8")
    msg = message.encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()
