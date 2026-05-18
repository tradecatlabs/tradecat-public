from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tradecat_auto.replay import (
    build_decision_quality_report,
    build_decision_trace_report,
    build_paper_backtest_report,
    build_replay_report,
)


class ReplayReportingTests(unittest.TestCase):
    def test_replay_report_summarizes_service_cycle_archive_with_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "cycles.jsonl"
            ledger = Path(tmp) / "paper_ledger.json"
            archive.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "schema": "tradecat_auto.service_cycle.v1",
                                "action": "PROCESSED",
                                "ok": True,
                                "latest_event": {"event_id": "evt-1"},
                                "pipeline_report": {
                                    "selected_symbol": "IRYSUSDT",
                                    "research_cycle_run_id": "cycle-1",
                                    "signal": {"direction": "LONG", "score": 80},
                                    "risk_decision": {"decision": "ALLOW"},
                                    "paper_execution": {
                                        "status": "OPENED",
                                        "paper_execution_id": "exec-1",
                                        "research_cycle_run_id": "cycle-1",
                                    },
                                },
                                "paper_ledger": {
                                    "recent_fills": [{"fill_id": "fill-1", "research_cycle_run_id": "cycle-1"}]
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "schema": "tradecat_auto.service_cycle.v1",
                                "action": "SKIPPED_DUPLICATE_EVENT",
                                "ok": True,
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            ledger.write_text(
                json.dumps(
                    {
                        "schema": "tradecat_auto.paper_ledger.v1",
                        "cash_balance_usdt": 1006.0,
                        "equity_usdt": 1006.0,
                        "initial_balance_usdt": 1000.0,
                        "realized_pnl_usdt": 6.0,
                        "unrealized_pnl_usdt": 0.0,
                        "open_positions": {},
                        "closed_positions": [
                            {"symbol": "IRYSUSDT", "net_pnl_usdt": 8.0, "entry_price": 1.0, "exit_price": 1.08},
                            {"symbol": "BTCUSDT", "net_pnl_usdt": -2.0, "entry_price": 2.0, "exit_price": 1.98},
                        ],
                        "fills": [{"fill_id": "1"}, {"fill_id": "2"}],
                        "applied_execution_ids": ["exec-1"],
                        "ignored_execution_ids": [],
                        "equity_curve": [
                            {"time": "t0", "equity_usdt": 1000.0},
                            {"time": "t1", "equity_usdt": 1010.0},
                            {"time": "t2", "equity_usdt": 1006.0},
                        ],
                        "last_updated_at": "2026-05-15T10:00:00Z",
                    }
                ),
                encoding="utf-8",
            )

            report = build_replay_report(archive_path=archive, ledger_path=ledger)

        self.assertEqual(report["schema"], "tradecat_auto.replay_report.v1")
        self.assertTrue(report["ok"])
        self.assertEqual(report["archive"]["cycle_count"], 2)
        self.assertEqual(report["archive"]["processed_count"], 1)
        self.assertEqual(report["archive"]["opened_count"], 1)
        self.assertEqual(len(report["archive"]["sha256"]), 64)
        self.assertEqual(report["decision_trace"]["schema"], "tradecat_auto.decision_trace_report.v1")
        self.assertEqual(report["decision_trace"]["trace_count"], 2)
        self.assertEqual(report["decision_trace"]["decision_counts"]["OPENED"], 1)
        self.assertEqual(report["decision_trace"]["error_code_counts"]["event_id_already_seen"], 1)
        self.assertEqual(report["decision_trace"]["traces"][0]["research_cycle_run_id"], "cycle-1")
        self.assertEqual(report["decision_quality"]["schema"], "tradecat_auto.decision_quality_report.v1")
        self.assertEqual(report["decision_quality"]["paper_outcomes"]["opened_count"], 1)
        self.assertIn("not investment advice", report["decision_quality"]["quality_notes"])
        self.assertEqual(report["paper_backtest"]["metrics"]["trade_count"], 2)
        self.assertEqual(report["paper_backtest"]["metrics"]["net_pnl_usdt"], 6.0)
        self.assertFalse(report["safety"]["real_orders"])
        self.assertFalse(report["safety"]["signed_requests"])

    def test_paper_backtest_metrics_are_deterministic_from_closed_positions_and_equity_curve(self) -> None:
        ledger = {
            "schema": "tradecat_auto.paper_ledger.v1",
            "initial_balance_usdt": 1000.0,
            "closed_positions": [
                {"net_pnl_usdt": 10.0},
                {"net_pnl_usdt": -5.0},
                {"net_pnl_usdt": 0.0},
            ],
            "fills": [{}, {}, {}, {}, {}, {}],
            "equity_curve": [
                {"equity_usdt": 1000.0},
                {"equity_usdt": 1010.0},
                {"equity_usdt": 1005.0},
            ],
        }

        report = build_paper_backtest_report(ledger)

        self.assertEqual(report["schema"], "tradecat_auto.paper_backtest_report.v1")
        self.assertTrue(report["ok"])
        self.assertEqual(report["metrics"]["trade_count"], 3)
        self.assertEqual(report["metrics"]["win_rate"], 1 / 3)
        self.assertEqual(report["metrics"]["loss_rate"], 1 / 3)
        self.assertEqual(report["metrics"]["profit_factor"], 2.0)
        self.assertEqual(report["metrics"]["max_drawdown_usdt"], 5.0)
        self.assertEqual(report["metrics"]["net_return_pct"], 0.5)

    def test_decision_trace_report_aggregates_reject_error_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "cycles.jsonl"
            archive.write_text(
                json.dumps(
                    {
                        "schema": "tradecat_auto.service_cycle.v1",
                        "action": "PROCESSED",
                        "ok": False,
                        "error_code": "agent_exit_plan_required",
                        "latest_event": {"event_id": "evt-reject"},
                        "pipeline_report": {
                            "selected_symbol": "TAUSDT",
                            "error_code": "agent_exit_plan_required",
                            "risk_decision": {"decision": "REJECT", "reasons": ["agent_exit_plan_required"]},
                            "paper_execution": {"status": "REJECTED", "reasons": ["risk_decision_not_allow"]},
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            report = build_decision_trace_report(archive_path=archive)

        self.assertEqual(report["schema"], "tradecat_auto.decision_trace_report.v1")
        self.assertTrue(report["ok"])
        self.assertEqual(report["trace_count"], 1)
        self.assertEqual(report["traces"][0]["decision"], "REJECTED")
        self.assertEqual(report["traces"][0]["error_code"], "agent_exit_plan_required")
        self.assertEqual(report["error_code_counts"]["agent_exit_plan_required"], 1)
        self.assertEqual(report["error_code_counts"]["risk_decision_not_allow"], 1)
        self.assertFalse(report["safety"]["real_orders"])

    def test_decision_quality_report_summarizes_missing_agent_inputs_and_paper_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "cycles.jsonl"
            ledger = Path(tmp) / "paper_ledger.json"
            archive.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "schema": "tradecat_auto.service_cycle.v1",
                                "action": "PROCESSED",
                                "ok": False,
                                "pipeline_report": {
                                    "selected_symbol": "AIAUSDT",
                                    "risk_decision": {"decision": "REJECT", "reasons": ["agent_sizing_required"]},
                                    "paper_execution": {"status": "REJECTED", "reasons": ["agent_sizing_required"]},
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "schema": "tradecat_auto.service_cycle.v1",
                                "action": "PROCESSED",
                                "ok": False,
                                "pipeline_report": {
                                    "selected_symbol": "TAUSDT",
                                    "risk_decision": {"decision": "REJECT", "reasons": ["agent_exit_plan_required"]},
                                    "paper_execution": {"status": "REJECTED", "reasons": ["agent_exit_plan_required"]},
                                },
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            ledger.write_text(
                json.dumps(
                    {
                        "schema": "tradecat_auto.paper_ledger.v1",
                        "cash_balance_usdt": 1000.0,
                        "equity_usdt": 1000.0,
                        "initial_balance_usdt": 1000.0,
                        "realized_pnl_usdt": 0.0,
                        "unrealized_pnl_usdt": 0.0,
                        "open_positions": {},
                        "closed_positions": [],
                        "fills": [],
                        "applied_execution_ids": [],
                        "ignored_execution_ids": [],
                        "equity_curve": [],
                    }
                ),
                encoding="utf-8",
            )

            report = build_decision_quality_report(archive_path=archive, ledger_path=ledger)

        self.assertEqual(report["schema"], "tradecat_auto.decision_quality_report.v1")
        self.assertTrue(report["ok"])
        self.assertEqual(report["agent_input_completeness"]["missing_sizing_count"], 1)
        self.assertEqual(report["agent_input_completeness"]["missing_exit_plan_count"], 1)
        self.assertEqual(report["agent_input_completeness"]["risk_reject_count"], 2)
        self.assertEqual(report["paper_outcomes"]["rejected_count"], 2)
        self.assertFalse(report["safety"]["real_orders"])
        self.assertTrue(report["safety"]["not_investment_advice"])

    def test_replay_report_is_deterministic_when_generated_at_is_fixed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "cycles.jsonl"
            ledger = Path(tmp) / "paper_ledger.json"
            archive.write_text(
                json.dumps(
                    {
                        "schema": "tradecat_auto.service_cycle.v1",
                        "action": "PROCESSED",
                        "ok": True,
                        "latest_event": {"event_id": "evt-deterministic"},
                        "pipeline_report": {
                            "selected_symbol": "IRYSUSDT",
                            "risk_decision": {"decision": "ALLOW"},
                            "paper_execution": {"status": "OPENED", "paper_execution_id": "exec-deterministic"},
                        },
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            ledger.write_text(
                json.dumps(
                    {
                        "schema": "tradecat_auto.paper_ledger.v1",
                        "cash_balance_usdt": 1000.0,
                        "equity_usdt": 1000.0,
                        "initial_balance_usdt": 1000.0,
                        "realized_pnl_usdt": 0.0,
                        "unrealized_pnl_usdt": 0.0,
                        "open_positions": {},
                        "closed_positions": [],
                        "fills": [],
                        "applied_execution_ids": [],
                        "ignored_execution_ids": [],
                        "equity_curve": [],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            first = build_replay_report(archive_path=archive, ledger_path=ledger, generated_at="2026-05-18T00:00:00Z")
            second = build_replay_report(archive_path=archive, ledger_path=ledger, generated_at="2026-05-18T00:00:00Z")

        self.assertEqual(first, second)
        self.assertEqual(first["generated_at"], "2026-05-18T00:00:00Z")
        self.assertEqual(first["decision_trace"]["generated_at"], "2026-05-18T00:00:00Z")
        self.assertEqual(first["decision_quality"]["generated_at"], "2026-05-18T00:00:00Z")
        self.assertEqual(first["paper_backtest"]["generated_at"], "2026-05-18T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
