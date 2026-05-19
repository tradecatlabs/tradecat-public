from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "portfolio_risk_policy"
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "tradecat-auto-portfolio-risk-policy.schema.json"


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class PortfolioRiskPolicySchemaTests(unittest.TestCase):
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

    def test_valid_portfolio_risk_policies_pass_schema(self) -> None:
        for name in ("strict-paper-policy.json", "kill-switch-policy.json"):
            with self.subTest(name=name):
                payload = load_fixture(name)
                self.assertValid(payload)
                self.assertEqual(payload["schema"], "tradecat_auto.portfolio_risk_policy.v1")
                self.assertTrue(payload["safety"]["public_readonly"])
                self.assertFalse(payload["safety"]["real_orders"])
                self.assertTrue(payload["hard_boundaries"]["does_not_set_order_size"])

    def test_policy_cannot_supply_trade_sizing_leverage_or_exits(self) -> None:
        self.assertInvalid(load_fixture("unsafe-sizing-policy.json"))
        for forbidden_field, value in (
            ("requested_notional_usdt", 20),
            ("paper_leverage", 2),
            ("stop_loss_price", 97),
            ("take_profit_price", 106),
            ("max_holding_minutes", 30),
        ):
            with self.subTest(forbidden_field=forbidden_field):
                payload = load_fixture("strict-paper-policy.json")
                payload[forbidden_field] = value
                self.assertInvalid(payload)

    def test_policy_safety_flags_are_fail_closed(self) -> None:
        payload = load_fixture("strict-paper-policy.json")
        for container_name, field in (
            ("safety", "real_orders"),
            ("safety", "signed_requests"),
            ("safety", "reads_api_keys"),
            ("safety", "binance_account_state"),
            ("hard_boundaries", "real_orders"),
            ("hard_boundaries", "signed_requests"),
            ("hard_boundaries", "reads_api_keys"),
        ):
            with self.subTest(container_name=container_name, field=field):
                mutated = copy.deepcopy(payload)
                mutated[container_name][field] = True
                self.assertInvalid(mutated)

    def test_policy_limits_are_positive_when_present(self) -> None:
        payload = load_fixture("strict-paper-policy.json")
        payload["limits"]["max_open_positions"] = 0
        self.assertInvalid(payload)

        payload = load_fixture("strict-paper-policy.json")
        payload["limits"]["min_agent_confidence"] = 1.5
        self.assertInvalid(payload)


if __name__ == "__main__":
    unittest.main()
