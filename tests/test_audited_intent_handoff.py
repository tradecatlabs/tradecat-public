from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "audited_intent_handoff"
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "tradecat-auto-audited-intent-handoff.schema.json"


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class AuditedIntentHandoffSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_schema()
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)

    def assertValid(self, payload: dict) -> None:
        errors = sorted(self.validator.iter_errors(payload), key=lambda item: item.path)
        self.assertEqual(errors, [], [error.message for error in errors])

    def assertInvalid(self, payload: dict) -> None:
        self.assertTrue(list(self.validator.iter_errors(payload)), "payload unexpectedly passed schema validation")

    def test_valid_handoff_fixture_is_public_safe_candidate_only(self) -> None:
        payload = load_fixture("paper-open-candidate.json")

        self.assertValid(payload)
        self.assertEqual(payload["schema"], "tradecat_auto.audited_intent_handoff.v1")
        self.assertTrue(payload["executor_requirements"]["private_executor_must_recheck_account_state"])
        self.assertTrue(payload["safety"]["public_readonly"])
        self.assertFalse(payload["safety"]["real_orders"])
        self.assertFalse(payload["safety"]["contains_credentials"])
        self.assertTrue(payload["hard_boundaries"]["not_a_real_order"])

    def test_handoff_rejects_credentials_real_orders_and_missing_executor_checks(self) -> None:
        self.assertInvalid(load_fixture("unsafe-credential-handoff.json"))

        payload = load_fixture("paper-open-candidate.json")
        for field, value in (
            ("signature", "abc"),
            ("listen_key", "listen"),
            ("real_order", True),
            ("exchange_order_id", "123"),
        ):
            with self.subTest(field=field):
                mutated = copy.deepcopy(payload)
                mutated[field] = value
                self.assertInvalid(mutated)

        missing_approval = copy.deepcopy(payload)
        missing_approval["executor_requirements"]["operator_approval_required"] = False
        self.assertInvalid(missing_approval)


if __name__ == "__main__":
    unittest.main()
