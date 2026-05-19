from __future__ import annotations

from typing import Any

FALSE_ONLY_SAFETY_KEYS = {
    "binance_account_state",
    "read_api_keys",
    "reads_api_keys",
    "real_order",
    "real_orders",
    "requires_signature",
    "signed",
    "signed_requests",
}
FALSE_ONLY_SAFETY_KEY_COMPACTS = {key.replace("_", "") for key in FALSE_ONLY_SAFETY_KEYS}
CREDENTIAL_KEY_MARKERS = ("api_key", "apikey", "secret", "signature", "listen_key", "private_key")


def paper_watch_safety_boundary() -> dict[str, bool]:
    return {
        "public_readonly_market_data": True,
        "public_readonly": True,
        "paper_or_watch_only": True,
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "binance_account_state": False,
    }


def paper_watch_report_flags() -> dict[str, bool]:
    safety = paper_watch_safety_boundary()
    return {
        "real_orders": safety["real_orders"],
        "signed_requests": safety["signed_requests"],
        "reads_api_keys": safety["reads_api_keys"],
    }


def paper_watch_hard_boundaries() -> dict[str, bool]:
    safety = paper_watch_safety_boundary()
    return {
        "real_orders": safety["real_orders"],
        "signed_requests": safety["signed_requests"],
        "reads_api_keys": safety["reads_api_keys"],
        "binance_account_state": safety["binance_account_state"],
    }


def normalize_paper_watch_safety(value: Any, *, error_prefix: str, allow_extra: bool = False) -> dict[str, bool]:
    expected = paper_watch_safety_boundary()
    if value in (None, ""):
        safety: dict[str, Any] = {}
    elif isinstance(value, dict):
        safety = value
    else:
        raise ValueError(f"{error_prefix}: safety must be an object")
    for key, expected_value in expected.items():
        if key in safety and safety.get(key) is not expected_value:
            raise ValueError(f"{error_prefix}: safety.{key} must be {expected_value!r}")
    for key in safety:
        if not allow_extra and key not in expected:
            raise ValueError(f"{error_prefix}: safety.{key} is not allowed")
    return expected


def compact_safety_key(key: Any) -> str:
    return str(key).lower().replace("-", "_").replace("_", "")


def normalize_safety_key(key: Any) -> str:
    return str(key).lower().replace("-", "_")


def is_false_only_safety_key(key: Any) -> bool:
    normalized = normalize_safety_key(key)
    return normalized in FALSE_ONLY_SAFETY_KEYS or compact_safety_key(key) in FALSE_ONLY_SAFETY_KEY_COMPACTS


def is_false_only_safety_violation(key: Any, value: Any) -> bool:
    return is_false_only_safety_key(key) and value is not False


def forbidden_private_or_real_trade_hits(value: Any, *, prefix: str = "") -> list[str]:
    """Return JSON paths that would cross the public-readonly paper/watch boundary."""

    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            normalized = normalize_safety_key(key_text)
            compact = compact_safety_key(key_text)
            if is_false_only_safety_key(key_text):
                if child is not False:
                    hits.append(path)
            elif _is_credential_like_key(normalized, compact):
                hits.append(path)
            hits.extend(forbidden_private_or_real_trade_hits(child, prefix=path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(
                forbidden_private_or_real_trade_hits(child, prefix=f"{prefix}[{index}]" if prefix else f"[{index}]")
            )
    return hits


def _is_credential_like_key(normalized_key: str, compact_key: str) -> bool:
    return any(marker in normalized_key for marker in CREDENTIAL_KEY_MARKERS) or any(
        marker in compact_key for marker in CREDENTIAL_KEY_MARKERS
    )
