from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from tradecat_auto.agent_market_context import ALLOWED_ENDPOINTS_BY_FAMILY
from tradecat_auto.agent_research_cycle import (
    audit_agent_research_cycle,
    build_observe_only_drafts,
    build_observe_only_research_cycle,
    write_observe_only_drafts,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "tradecat-auto-agent-research-cycle.schema.json"
THESIS_SCHEMA_PATH = PROJECT_ROOT / "contracts" / "tradecat-auto-agent-trade-thesis.schema.json"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "agent_research_cycle"


def fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class AgentResearchCycleTests(unittest.TestCase):
    def test_schema_accepts_safe_research_cycle_fixtures_and_rejects_dangerous_endpoint(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)

        for name in (
            "success-paper-candidate.json",
            "missing-sizing-reject.json",
            "missing-exit-plan-reject.json",
            "tool-failure-request-more-context.json",
        ):
            errors = list(validator.iter_errors(fixture(name)))
            self.assertEqual(errors, [], name)

        self.assertTrue(list(validator.iter_errors(fixture("dangerous-endpoint-rejected.json"))))

    def test_audit_accepts_safe_paper_candidate(self) -> None:
        audit = audit_agent_research_cycle(fixture("success-paper-candidate.json"))

        self.assertEqual(audit["schema"], "tradecat_auto.agent_research_cycle_audit.v1")
        self.assertEqual(audit["schema_version"], "1.0.0")
        self.assertTrue(audit["ok"])
        self.assertIsNone(audit["error_code"])
        self.assertEqual(audit["next_action"], "run_context_paper")
        self.assertIn("/fapi/v1/klines", audit["accepted_endpoints"])
        self.assertFalse(audit["safety"]["real_orders"])
        self.assertFalse(audit["safety"]["signed_requests"])
        self.assertFalse(audit["safety"]["reads_api_keys"])

    def test_build_observe_only_research_cycle_requires_agent_context_before_paper(self) -> None:
        payload = build_observe_only_research_cycle(
            events={
                "schema": "tradecat_auto.sheet_events.v1",
                "ok": True,
                "events": [
                    {
                        "event_id": "evt-research",
                        "source_time_bj": "2026-05-18 00:00:00",
                        "content": "IRYS 异动",
                    }
                ],
            },
            anomaly_symbols={
                "schema": "tradecat_auto.anomaly_symbols.v1",
                "ok": True,
                "symbols": [
                    {"raw_symbol": "IRYS", "normalized_symbol": "IRYSUSDT"},
                ],
                "rejected": [],
            },
            generated_at="2026-05-18T00:00:00Z",
        )

        self.assertEqual(payload["schema"], "tradecat_auto.agent_research_cycle.v1")
        self.assertEqual(payload["schema_version"], "1.0.0")
        self.assertTrue(payload["ok"])
        self.assertIsNone(payload["error_code"])
        self.assertEqual(payload["mode"], "observe_only")
        self.assertEqual(payload["symbol"], "IRYSUSDT")
        self.assertEqual(payload["tool_calls"], [])
        self.assertEqual(payload["next_action"]["action"], "observe_only")
        self.assertFalse(payload["next_action"]["writes_paper_ledger"])
        self.assertEqual(payload["tool_orchestration_policy"]["schema"], "tradecat_auto.agent_tool_orchestration.v1")
        self.assertEqual(
            payload["tool_orchestration_policy"]["required_tool_failure"]["next_action"],
            "request_more_context",
        )
        self.assertFalse(payload["tool_orchestration_policy"]["required_tool_failure"]["writes_paper_ledger"])
        self.assertFalse(payload["safety"]["real_orders"])
        self.assertFalse(payload["safety"]["signed_requests"])
        self.assertFalse(payload["safety"]["reads_api_keys"])
        self.assertTrue(audit_agent_research_cycle(payload)["ok"])

    def test_observe_only_market_data_plan_is_ordered_public_readonly_allowlist(self) -> None:
        payload = build_observe_only_research_cycle(
            events={
                "schema": "tradecat_auto.sheet_events.v1",
                "ok": True,
                "events": [
                    {
                        "event_id": "evt-plan",
                        "source_time_bj": "2026-05-18 00:00:00",
                        "content": "IRYS 异动",
                    }
                ],
            },
            anomaly_symbols={"schema": "tradecat_auto.anomaly_symbols.v1", "ok": True, "symbols": []},
            requested_symbol="IRYS",
            generated_at="2026-05-18T00:00:00Z",
        )

        requested = payload["requested_market_data"]
        self.assertEqual([item["sequence"] for item in requested], list(range(1, len(requested) + 1)))
        for item in requested:
            self.assertEqual(item["method"], "GET")
            self.assertIn(item["endpoint"], ALLOWED_ENDPOINTS_BY_FAMILY[item["family"]])
            self.assertIn(item["fallback_next_action"], {"request_more_context", "hold"})
            self.assertIn("error_code", item)
        self.assertEqual(
            [item["fallback_next_action"] for item in requested if item["required"]],
            ["request_more_context"] * len([item for item in requested if item["required"]]),
        )
        self.assertTrue(audit_agent_research_cycle(payload)["ok"])

    def test_observe_only_drafts_are_context_audit_consumable_without_paper_intent(self) -> None:
        payload = build_observe_only_research_cycle(
            events={
                "schema": "tradecat_auto.sheet_events.v1",
                "ok": True,
                "events": [
                    {
                        "event_id": "evt-draft",
                        "source_time_bj": "2026-05-18 00:00:00",
                        "content": "IRYS 异动",
                    }
                ],
            },
            anomaly_symbols={"schema": "tradecat_auto.anomaly_symbols.v1", "ok": True, "symbols": []},
            requested_symbol="IRYS",
            generated_at="2026-05-18T00:00:00Z",
        )

        drafts = build_observe_only_drafts(payload)

        self.assertEqual(drafts["schema"], "tradecat_auto.observe_only_drafts.v1")
        self.assertTrue(drafts["agent_market_context_audit"]["ok"])
        self.assertEqual(
            {warning["code"] for warning in drafts["agent_market_context_audit"]["warnings"]},
            {"market_data_item_not_ok"},
        )
        self.assertEqual(drafts["agent_trade_thesis"]["schema"], "tradecat_auto.agent_trade_thesis.v1")
        self.assertEqual(drafts["agent_trade_thesis"]["direction"], "WATCH_ONLY")
        self.assertEqual(drafts["agent_trade_thesis"]["error_code"], "agent_trade_thesis_required")
        self.assertNotIn("paper_intent", drafts["agent_trade_thesis"])
        thesis_schema = json.loads(THESIS_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(list(Draft202012Validator(thesis_schema).iter_errors(drafts["agent_trade_thesis"])), [])

    def test_write_observe_only_drafts_uses_isolated_output_dir_and_rejects_auto_paper_runtime(self) -> None:
        payload = build_observe_only_research_cycle(
            events={
                "schema": "tradecat_auto.sheet_events.v1",
                "ok": True,
                "events": [{"event_id": "evt-write", "source_time_bj": "2026-05-18 00:00:00", "content": "IRYS"}],
            },
            anomaly_symbols={"schema": "tradecat_auto.anomaly_symbols.v1", "ok": True, "symbols": []},
            requested_symbol="IRYS",
            generated_at="2026-05-18T00:00:00Z",
        )
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "observe-only"
            result = write_observe_only_drafts(payload, output_dir)

            self.assertTrue(result["ok"])
            for path in result["files"].values():
                self.assertTrue(Path(path).exists())
            context = json.loads(Path(result["files"]["agent_market_context"]).read_text(encoding="utf-8"))
            self.assertEqual(context["schema"], "tradecat_auto.agent_market_context.v1")
            thesis = json.loads(Path(result["files"]["agent_trade_thesis"]).read_text(encoding="utf-8"))
            self.assertNotIn("paper_intent", thesis)

            with self.assertRaisesRegex(ValueError, "observe_only_output_dir_forbidden"):
                write_observe_only_drafts(payload, Path(tmp) / ".runtime" / "auto-paper" / "observe")

    def test_audit_accepts_fail_closed_reject_fixtures(self) -> None:
        for name, expected_code in (
            ("missing-sizing-reject.json", "agent_sizing_required"),
            ("missing-exit-plan-reject.json", "agent_exit_plan_required"),
        ):
            payload = fixture(name)
            audit = audit_agent_research_cycle(payload)

            self.assertTrue(audit["ok"], name)
            self.assertEqual(payload["error_code"], expected_code)
            self.assertEqual(audit["next_action"], "reject")

    def test_audit_rejects_run_context_paper_without_sizing_or_exit_plan(self) -> None:
        payload = fixture("success-paper-candidate.json")
        payload["agent_trade_thesis"].pop("paper_intent")
        audit = audit_agent_research_cycle(payload)

        self.assertFalse(audit["ok"])
        self.assertEqual(audit["error_code"], "agent_sizing_required")

        payload = fixture("success-paper-candidate.json")
        payload["agent_trade_thesis"].pop("invalidation_price")
        payload["agent_trade_thesis"].pop("take_profit_price")
        payload["agent_trade_thesis"].pop("max_holding_minutes")
        audit = audit_agent_research_cycle(payload)

        self.assertFalse(audit["ok"])
        self.assertEqual(audit["error_code"], "agent_exit_plan_required")

    def test_audit_rejects_dangerous_endpoint_and_unsafe_flags(self) -> None:
        audit = audit_agent_research_cycle(fixture("dangerous-endpoint-rejected.json"))

        self.assertFalse(audit["ok"])
        self.assertEqual(audit["error_code"], "forbidden_endpoint")

        payload = copy.deepcopy(fixture("success-paper-candidate.json"))
        payload["safety"]["reads_api_keys"] = True
        audit = audit_agent_research_cycle(payload)

        self.assertFalse(audit["ok"])
        self.assertEqual(audit["error_code"], "safety_boundary_violation")

        payload = copy.deepcopy(fixture("success-paper-candidate.json"))
        payload["tool_calls"][0]["signed"] = True
        audit = audit_agent_research_cycle(payload)

        self.assertFalse(audit["ok"])
        self.assertIn("signed_request_forbidden", {error["code"] for error in audit["errors"]})

    def test_tool_call_failure_degrades_to_request_more_context_without_paper(self) -> None:
        payload = fixture("tool-failure-request-more-context.json")
        audit = audit_agent_research_cycle(payload)

        self.assertTrue(audit["ok"])
        self.assertEqual(payload["error_code"], "market_context_incomplete")
        self.assertEqual(payload["next_action"]["action"], "request_more_context")
        self.assertFalse(payload["next_action"]["writes_paper_ledger"])
        self.assertEqual(audit["warnings"][0]["code"], "tool_call_not_ok")


if __name__ == "__main__":
    unittest.main()
