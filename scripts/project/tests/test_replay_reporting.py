from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tradecat_auto.replay import build_paper_backtest_report, build_replay_report


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
                                "pipeline_report": {
                                    "selected_symbol": "IRYSUSDT",
                                    "signal": {"direction": "LONG", "score": 80},
                                    "risk_decision": {"decision": "ALLOW"},
                                    "paper_execution": {"status": "OPENED", "paper_execution_id": "exec-1"},
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


if __name__ == "__main__":
    unittest.main()
