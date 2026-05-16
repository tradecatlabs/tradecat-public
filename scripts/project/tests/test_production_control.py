from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tradecat_auto.audit_journal import append_audit_record
from tradecat_auto.paper_ledger import apply_paper_execution, default_paper_ledger, mark_to_market, save_paper_ledger
from tradecat_auto.production_control import build_daily_report, build_health_report, build_telegram_alerts


class ProductionControlTests(unittest.TestCase):
    def test_health_report_combines_state_ledger_archive_and_journal_with_safety_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "service_state.json"
            ledger_path = root / "paper_ledger.json"
            archive_path = root / "cycles.jsonl"
            journal_path = root / "paper_audit.sqlite3"
            state_path.write_text(
                json.dumps(
                    {
                        "schema": "tradecat_auto.service_state.v1",
                        "cycles_attempted": 3,
                        "cycles_processed": 2,
                        "last_attempt_at": "2026-05-15T00:09:30Z",
                        "last_success_at": "2026-05-15T00:09:30Z",
                        "last_error": None,
                        "last_processed_event_id": "evt-2",
                        "last_selected_symbol": "IRYSUSDT",
                        "seen_event_ids": ["evt-2", "evt-1"],
                    }
                ),
                encoding="utf-8",
            )
            save_paper_ledger(ledger_path, default_paper_ledger(initial_balance_usdt=1000.0))
            archive_path.write_text('{"schema":"tradecat_auto.service_cycle.v1","action":"PROCESSED","ok":true}\n', encoding="utf-8")
            append_audit_record(
                journal_path,
                event_type="service_cycle",
                payload={"schema": "tradecat_auto.service_cycle.v1", "ok": True},
                run_id="evt-2",
                idempotency_key="cycle:evt-2",
                created_at="2026-05-15T00:09:30Z",
            )

            report = build_health_report(
                state_path=state_path,
                ledger_path=ledger_path,
                archive_path=archive_path,
                journal_path=journal_path,
                now_iso="2026-05-15T00:10:00Z",
                max_heartbeat_age_seconds=90,
            )

            self.assertEqual(report["schema"], "tradecat_auto.production_health.v1")
            self.assertTrue(report["ok"])
            self.assertEqual(report["status"], "healthy")
            self.assertEqual(report["heartbeat"]["age_seconds"], 30.0)
            self.assertEqual(report["archive"]["cycle_count"], 1)
            self.assertTrue(report["audit_journal"]["chain_valid"])
            self.assertFalse(report["safety"]["real_orders"])
            self.assertFalse(report["safety"]["signed_requests"])

    def test_health_report_flags_stale_or_missing_runtime_as_alertable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "service_state.json"
            state_path.write_text(
                json.dumps({"schema": "tradecat_auto.service_state.v1", "last_attempt_at": "2026-05-15T00:00:00Z", "last_error": "network_error"}),
                encoding="utf-8",
            )

            report = build_health_report(
                state_path=state_path,
                ledger_path=root / "paper_ledger.json",
                archive_path=root / "cycles.jsonl",
                journal_path=root / "paper_audit.sqlite3",
                now_iso="2026-05-15T00:10:00Z",
                max_heartbeat_age_seconds=90,
            )

            self.assertFalse(report["ok"])
            self.assertEqual(report["status"], "degraded")
            self.assertIn("heartbeat_stale", report["alerts"])
            self.assertIn("paper_ledger_missing", report["alerts"])
            self.assertIn("cycle_archive_missing", report["alerts"])
            self.assertIn("last_error_present", report["alerts"])

    def test_daily_report_and_telegram_alerts_are_machine_contract_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = root / "paper_ledger.json"
            archive_path = root / "cycles.jsonl"
            ledger = apply_paper_execution(default_paper_ledger(initial_balance_usdt=1000.0), {
                "ok": True,
                "status": "OPENED",
                "paper_execution_id": "exec-1",
                "symbol": "IRYSUSDT",
                "side": "LONG",
                "entry_price": 100.0,
                "quantity": 0.2,
                "notional_usdt": 20.0,
                "stop_loss_price": 97.0,
                "take_profit_price": 106.0,
            }, now_iso="2026-05-15T00:00:00Z")
            ledger = mark_to_market(ledger, {"IRYSUSDT": 107.0}, now_iso="2026-05-15T00:30:00Z")
            save_paper_ledger(ledger_path, ledger)
            archive_path.write_text(
                "\n".join(
                    [
                        json.dumps({"schema": "tradecat_auto.service_cycle.v1", "action": "PROCESSED", "ok": True}),
                        json.dumps({"schema": "tradecat_auto.service_cycle.v1", "action": "SKIPPED_DUPLICATE_EVENT", "ok": True}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            report = build_daily_report(ledger_path=ledger_path, archive_path=archive_path, date="2026-05-15")
            alerts = build_telegram_alerts(report)

            self.assertEqual(report["schema"], "tradecat_auto.daily_paper_report.v1")
            self.assertTrue(report["ok"])
            self.assertEqual(report["cycle_counts"]["PROCESSED"], 1)
            self.assertEqual(report["ledger_summary"]["closed_positions_count"], 1)
            self.assertEqual(report["trades"][0]["symbol"], "IRYSUSDT")
            self.assertEqual(alerts["schema"], "tradecat_auto.telegram_alerts.v1")
            self.assertTrue(alerts["ok"])
            self.assertEqual(alerts["alerts"][0]["kind"], "daily_report")
            self.assertIn("TradeCat paper daily", alerts["alerts"][0]["text"])
            self.assertFalse(alerts["alerts"][0]["real_orders"])


if __name__ == "__main__":
    unittest.main()
