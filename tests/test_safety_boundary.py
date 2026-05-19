from __future__ import annotations

import re

from tradecat_auto.safety_boundary import (
    forbidden_private_or_real_trade_hits,
    is_false_only_safety_violation,
    normalize_paper_watch_safety,
    paper_watch_hard_boundaries,
    paper_watch_report_flags,
    paper_watch_safety_boundary,
)


def test_paper_watch_safety_boundary_is_public_readonly_and_false_only() -> None:
    safety = paper_watch_safety_boundary()

    assert safety["public_readonly_market_data"] is True
    assert safety["public_readonly"] is True
    assert safety["paper_or_watch_only"] is True
    assert safety["real_orders"] is False
    assert safety["signed_requests"] is False
    assert safety["reads_api_keys"] is False
    assert safety["binance_account_state"] is False


def test_paper_watch_report_flags_are_derived_from_canonical_safety_boundary() -> None:
    safety = paper_watch_safety_boundary()

    assert paper_watch_report_flags() == {
        "real_orders": safety["real_orders"],
        "signed_requests": safety["signed_requests"],
        "reads_api_keys": safety["reads_api_keys"],
    }


def test_paper_watch_hard_boundaries_are_derived_from_canonical_safety_boundary() -> None:
    safety = paper_watch_safety_boundary()

    assert paper_watch_hard_boundaries() == {
        "real_orders": safety["real_orders"],
        "signed_requests": safety["signed_requests"],
        "reads_api_keys": safety["reads_api_keys"],
        "binance_account_state": safety["binance_account_state"],
    }


def test_false_only_safety_flags_accept_exact_false_and_reject_stringy_or_numeric_truth() -> None:
    payload = {
        "safety": {
            "real_orders": False,
            "signed_requests": False,
            "reads_api_keys": False,
        },
        "market_data": [
            {"requires_signature": "true"},
            {"real_orders": 1},
        ],
    }

    hits = forbidden_private_or_real_trade_hits(payload)

    assert "safety.real_orders" not in hits
    assert "safety.signed_requests" not in hits
    assert "safety.reads_api_keys" not in hits
    assert "market_data[0].requires_signature" in hits
    assert "market_data[1].real_orders" in hits
    assert is_false_only_safety_violation("signed_requests", "false") is True


def test_normalize_paper_watch_safety_returns_canonical_flags_and_rejects_drift() -> None:
    normalized = normalize_paper_watch_safety({"public_readonly": True, "real_orders": False}, error_prefix="unit_test")

    assert normalized == paper_watch_safety_boundary()
    for bad_safety, expected_message in (
        ({"public_readonly": False}, r"unit_test: safety\.public_readonly must be True"),
        ({"real_orders": True}, r"unit_test: safety\.real_orders must be False"),
        ({"extra": False}, r"unit_test: safety\.extra is not allowed"),
        ("not-an-object", r"unit_test: safety must be an object"),
    ):
        try:
            normalize_paper_watch_safety(bad_safety, error_prefix="unit_test")
        except ValueError as exc:
            assert re.search(expected_message, str(exc))
        else:  # pragma: no cover - defensive assertion
            raise AssertionError(f"expected ValueError for {bad_safety}")

    assert normalize_paper_watch_safety({"extra": False}, error_prefix="unit_test", allow_extra=True) == normalized


def test_false_only_safety_flags_cover_common_agent_key_variants() -> None:
    payload = {
        "paperIntent": {
            "realOrder": False,
            "read-api-keys": False,
            "binanceAccountState": False,
            "signedRequests": "false",
        }
    }

    hits = forbidden_private_or_real_trade_hits(payload)

    assert "paperIntent.realOrder" not in hits
    assert "paperIntent.read-api-keys" not in hits
    assert "paperIntent.binanceAccountState" not in hits
    assert "paperIntent.signedRequests" in hits
    assert is_false_only_safety_violation("realOrder", True) is True
    assert is_false_only_safety_violation("read-api-keys", None) is True
    assert is_false_only_safety_violation("binanceAccountState", False) is False


def test_credential_like_keys_are_forbidden_without_flagging_benign_signed_wording() -> None:
    payload = {
        "provenance": {
            "commission_reference_requires_signed_user_data": False,
            "source": "unit_test",
        },
        "request": {
            "apiKey": "placeholder",
            "listen_key": "placeholder",
        },
    }

    hits = forbidden_private_or_real_trade_hits(payload)

    assert "provenance.commission_reference_requires_signed_user_data" not in hits
    assert "request.apiKey" in hits
    assert "request.listen_key" in hits
