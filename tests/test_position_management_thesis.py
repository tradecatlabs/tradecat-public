from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "position_management_thesis"
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "tradecat-auto-position-management-thesis.schema.json"


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class PositionManagementThesisSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_schema()
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)

    def assertValid(self, payload: dict) -> None:
        errors = sorted(self.validator.iter_errors(payload), key=lambda item: item.path)
        self.assertEqual(errors, [], [error.message for error in errors])

    def assertInvalid(self, payload: dict) -> None:
        errors = list(self.validator.iter_errors(payload))
        self.assertTrue(errors, "payload unexpectedly passed schema validation")

    def test_valid_position_management_fixtures_pass_schema(self) -> None:
        for name in ("hold.json", "close.json", "adjust-exit.json", "add.json", "reduce.json"):
            with self.subTest(name=name):
                payload = load_fixture(name)
                self.assertValid(payload)
                self.assertEqual(payload["schema"], "tradecat_auto.position_management_thesis.v1")
                self.assertTrue(payload["safety"]["public_readonly"])
                self.assertFalse(payload["safety"]["real_orders"])
                self.assertFalse(payload["safety"]["signed_requests"])
                self.assertFalse(payload["safety"]["reads_api_keys"])

    def test_unsafe_real_order_fixture_is_rejected(self) -> None:
        self.assertInvalid(load_fixture("unsafe-real-order.json"))

    def test_explicit_actions_require_reason_provenance_and_action_payload(self) -> None:
        close_payload = load_fixture("close.json")

        missing_reason = copy.deepcopy(close_payload)
        missing_reason.pop("reason")
        self.assertInvalid(missing_reason)

        missing_provenance = copy.deepcopy(close_payload)
        missing_provenance.pop("provenance")
        self.assertInvalid(missing_provenance)

        missing_position = copy.deepcopy(close_payload)
        missing_position.pop("position_ref")
        self.assertInvalid(missing_position)

        missing_close_intent = copy.deepcopy(close_payload)
        missing_close_intent.pop("close_intent")
        self.assertInvalid(missing_close_intent)

    def test_adjust_exit_and_add_reduce_are_fail_closed_without_explicit_intent(self) -> None:
        adjust = load_fixture("adjust-exit.json")
        adjust["exit_update"] = {
            "exit_rationale": "missing explicit price/time update",
            "agent_authorized": True,
            "real_order": False,
        }
        self.assertInvalid(adjust)

        add = load_fixture("add.json")
        add["paper_intent"] = {
            "side": "LONG",
            "requested_margin_usdt": 12,
            "agent_authorized": True,
            "real_order": False,
        }
        self.assertInvalid(add)

        reduce = load_fixture("reduce.json")
        reduce["paper_intent"] = {"agent_authorized": True, "real_order": False}
        self.assertInvalid(reduce)

    def test_safety_flags_cannot_be_reinterpreted_as_credentials_or_real_trading(self) -> None:
        payload = load_fixture("hold.json")
        for container_name, field in (
            ("safety", "real_orders"),
            ("safety", "signed_requests"),
            ("safety", "reads_api_keys"),
            ("safety", "binance_account_state"),
            ("hard_boundaries", "real_orders"),
            ("hard_boundaries", "signed_requests"),
            ("hard_boundaries", "reads_api_keys"),
            ("hard_boundaries", "binance_account_state"),
        ):
            with self.subTest(container_name=container_name, field=field):
                mutated = copy.deepcopy(payload)
                mutated[container_name][field] = True
                self.assertInvalid(mutated)


if __name__ == "__main__":
    unittest.main()
