from __future__ import annotations

import copy
import unittest

from tradecat_auto.agent_trade_thesis import normalize_agent_trade_thesis

VALID_THESIS = {
    "schema": "tradecat_auto.agent_trade_thesis.v1",
    "schema_version": "1.0.0",
    "ok": True,
    "symbol": "BTCUSDT",
    "mode": "paper_research",
    "direction": "LONG",
    "confidence": 0.7,
    "rationale": "Agent paper research thesis.",
    "paper_intent": {
        "allow_tradecat_paper_gate_to_decide": True,
        "requested_margin_usdt": 10,
        "paper_leverage": 2,
        "real_order": False,
    },
    "invalidation_price": 99,
    "take_profit_price": 105,
    "max_holding_minutes": 45,
    "limitations": ["paper/watch only; no Binance credentials; no real order"],
}


class AgentTradeThesisTests(unittest.TestCase):
    def test_normalize_accepts_safe_thesis_object_or_wrapper(self) -> None:
        normalized = normalize_agent_trade_thesis(VALID_THESIS)

        self.assertEqual(normalized["schema"], "tradecat_auto.agent_trade_thesis.v1")
        self.assertEqual(normalized["provenance"]["source"], "agent_supplied_trade_thesis")
        self.assertTrue(normalized["safety"]["public_readonly"])
        self.assertFalse(normalized["safety"]["real_orders"])
        wrapped = {"agent_trade_thesis": copy.deepcopy(VALID_THESIS)}
        self.assertEqual(normalize_agent_trade_thesis(wrapped)["symbol"], "BTCUSDT")

    def test_normalize_replaces_empty_provenance_source(self) -> None:
        payload = {**copy.deepcopy(VALID_THESIS), "provenance": {"source": ""}}

        normalized = normalize_agent_trade_thesis(payload)

        self.assertEqual(normalized["provenance"]["source"], "agent_supplied_trade_thesis")

    def test_normalize_rejects_unsafe_wrapper_safety(self) -> None:
        payload = {
            "safety": {
                "public_readonly_market_data": True,
                "public_readonly": False,
                "paper_or_watch_only": True,
                "real_orders": False,
                "signed_requests": False,
                "reads_api_keys": False,
                "binance_account_state": False,
            },
            "agent_trade_thesis": copy.deepcopy(VALID_THESIS),
        }

        with self.assertRaisesRegex(ValueError, r"agent_trade_thesis: safety\.public_readonly must be True"):
            normalize_agent_trade_thesis(payload)

    def test_normalize_rejects_credential_like_wrapper_fields(self) -> None:
        payload = {
            "agent_trade_thesis": copy.deepcopy(VALID_THESIS),
            "api_key": "placeholder",
        }

        with self.assertRaisesRegex(ValueError, r"agent_trade_thesis forbidden private/real-trade fields: api_key"):
            normalize_agent_trade_thesis(payload)

    def test_normalize_rejects_real_order_signed_and_credential_like_fields(self) -> None:
        unsafe_payloads = [
            {"paper_intent": {"real_order": True}},
            {"paper_intent": {"real_order": "true"}},
            {"safety": {"signed_requests": "true"}},
            {"safety": {"reads_api_keys": 1}},
            {"request": {"apiKey": "placeholder"}},
            {"request": {"requires_signature": "yes", "timestamp": 1234567890}},
        ]
        for unsafe in unsafe_payloads:
            with self.subTest(unsafe=unsafe):
                payload = copy.deepcopy(VALID_THESIS)
                for key, value in unsafe.items():
                    if isinstance(value, dict) and isinstance(payload.get(key), dict):
                        payload[key] = {**payload[key], **value}
                    else:
                        payload[key] = value

                with self.assertRaisesRegex(ValueError, "agent_trade_thesis forbidden private/real-trade fields"):
                    normalize_agent_trade_thesis(payload)

    def test_normalize_rejects_invalid_public_readonly_safety_boundary(self) -> None:
        payload = {
            **copy.deepcopy(VALID_THESIS),
            "safety": {
                "public_readonly_market_data": True,
                "public_readonly": False,
                "paper_or_watch_only": True,
                "real_orders": False,
                "signed_requests": False,
                "reads_api_keys": False,
                "binance_account_state": False,
            },
        }

        with self.assertRaisesRegex(ValueError, r"agent_trade_thesis: safety\.public_readonly must be True"):
            normalize_agent_trade_thesis(payload)


if __name__ == "__main__":
    unittest.main()
