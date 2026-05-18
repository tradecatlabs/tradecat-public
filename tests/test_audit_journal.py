from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from tradecat_auto.audit_journal import (
    append_audit_record,
    init_audit_journal,
    journal_summary,
    record_service_cycle,
)


class AuditJournalTests(unittest.TestCase):
    def test_init_creates_versioned_sqlite_schema_without_network_or_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper_audit.sqlite3"

            meta = init_audit_journal(path)

            self.assertEqual(meta["schema"], "tradecat_auto.audit_journal.v1")
            self.assertEqual(meta["schema_version"], "1.0.0")
            self.assertTrue(path.exists())
            with sqlite3.connect(path) as conn:
                tables = {row[0] for row in conn.execute("select name from sqlite_master where type='table'")}
                self.assertIn("audit_records", tables)
                self.assertIn("production_runs", tables)
                self.assertIn("journal_meta", tables)
            self.assertTrue(meta["safety"]["paper_or_watch_only"])
            self.assertFalse(meta["safety"]["real_orders"])
            self.assertFalse(meta["safety"]["signed_requests"])
            self.assertFalse(meta["safety"]["reads_api_keys"])

    def test_append_record_is_idempotent_and_checksum_chained(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper_audit.sqlite3"

            first = append_audit_record(
                path,
                event_type="service_cycle",
                payload={"schema": "tradecat_auto.service_cycle.v1", "action": "PROCESSED"},
                run_id="run-1",
                idempotency_key="cycle:evt-1",
                created_at="2026-05-15T00:00:00Z",
            )
            duplicate = append_audit_record(
                path,
                event_type="service_cycle",
                payload={"schema": "tradecat_auto.service_cycle.v1", "action": "PROCESSED"},
                run_id="run-1",
                idempotency_key="cycle:evt-1",
                created_at="2026-05-15T00:00:01Z",
            )
            second = append_audit_record(
                path,
                event_type="paper_fill",
                payload={"fill_id": "fill-1", "real_order": False},
                run_id="run-1",
                idempotency_key="fill:fill-1",
                created_at="2026-05-15T00:00:02Z",
            )

            self.assertEqual(first["record_id"], duplicate["record_id"])
            self.assertFalse(duplicate["inserted"])
            self.assertTrue(first["inserted"])
            self.assertTrue(second["inserted"])
            self.assertEqual(len(first["record_sha256"]), 64)
            self.assertEqual(second["prev_record_sha256"], first["record_sha256"])
            summary = journal_summary(path)
            self.assertEqual(summary["record_count"], 2)
            self.assertEqual(summary["event_type_counts"]["service_cycle"], 1)
            self.assertEqual(summary["event_type_counts"]["paper_fill"], 1)
            self.assertEqual(summary["latest_record_sha256"], second["record_sha256"])
            self.assertTrue(summary["chain_valid"])
            self.assertEqual(summary["sqlite_user_version"], 1)

    def test_record_service_cycle_persists_config_snapshot_decision_orders_fills_and_rejects_real_order_payloads(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper_audit.sqlite3"
            cycle = {
                "schema": "tradecat_auto.service_cycle.v1",
                "action": "PROCESSED",
                "ok": True,
                "latest_event": {"event_id": "evt-1"},
                "pipeline_report": {
                    "selected_symbol": "IRYSUSDT",
                    "signal": {"schema": "tradecat_auto.signal_score.v1", "direction": "LONG", "score": 80},
                    "risk_decision": {"schema": "tradecat_auto.risk_decision.v1", "decision": "ALLOW"},
                    "paper_execution": {
                        "schema": "tradecat_auto.paper_execution_report.v1",
                        "status": "OPENED",
                        "paper_execution_id": "exec-1",
                    },
                    "paper_ledger": {},
                },
                "paper_ledger": {
                    "recent_paper_orders": [{"order_id": "order-1", "real_order": False}],
                    "recent_fills": [{"fill_id": "fill-1", "action": "OPEN"}],
                },
            }

            result = record_service_cycle(
                path,
                cycle,
                run_id="run-prod-1",
                config_snapshot={"interval_seconds": 60, "source": "test"},
                created_at="2026-05-15T00:00:00Z",
            )

            self.assertEqual(result["schema"], "tradecat_auto.audit_journal_write.v1")
            self.assertTrue(result["ok"])
            self.assertEqual(result["run_id"], "run-prod-1")
            self.assertEqual(result["records_inserted"], 5)
            self.assertEqual(result["records_total"], 5)
            summary = journal_summary(path)
            self.assertEqual(summary["run_count"], 1)
            self.assertEqual(summary["event_type_counts"]["run_config_snapshot"], 1)
            self.assertEqual(summary["event_type_counts"]["service_cycle"], 1)
            self.assertEqual(summary["event_type_counts"]["risk_decision"], 1)
            self.assertEqual(summary["event_type_counts"]["paper_order"], 1)
            self.assertEqual(summary["event_type_counts"]["paper_fill"], 1)

            bad_cycle = dict(cycle)
            bad_cycle["paper_ledger"] = {"recent_paper_orders": [{"order_id": "bad", "real_order": True}]}
            bad = record_service_cycle(
                path, bad_cycle, run_id="run-prod-2", config_snapshot={}, created_at="2026-05-15T00:00:01Z"
            )
            self.assertFalse(bad["ok"])
            self.assertEqual(bad["error"]["code"], "real_order_payload_rejected")

    def test_journal_summary_is_read_only_when_journal_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing" / "paper_audit.sqlite3"

            summary = journal_summary(path)

            self.assertFalse(summary["ok"])
            self.assertEqual(summary["error"]["code"], "audit_journal_missing")
            self.assertEqual(summary["record_count"], 0)
            self.assertFalse(path.exists())
            self.assertFalse(path.parent.exists())
            self.assertFalse(Path(f"{path}-wal").exists())

    def test_record_service_cycle_rejects_broad_real_order_and_account_payload_fields(self) -> None:
        forbidden_payloads = [
            {"paper_ledger": {"recent_paper_orders": [{"orderId": 12345, "status": "FILLED"}]}},
            {"paper_ledger": {"recent_paper_orders": [{"clientOrderId": "cli-123"}]}},
            {"account": {"balance": "1000"}},
            {"position": {"symbol": "BTCUSDT", "positionAmt": "1"}},
            {"request": {"apiKey": "placeholder", "signature": "abc", "timestamp": 1234567890}},
            {"order_response": {"fills": [{"price": "1", "qty": "2"}], "executedQty": "2"}},
            {"order_response": {"newClientOrderId": "cli-456", "origQty": "10", "transactTime": 1234567890}},
            {"order_response": {"avgPrice": "1.23", "reduceOnly": True, "positionSide": "LONG"}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for index, payload in enumerate(forbidden_payloads):
                path = Path(tmp) / f"paper_audit_{index}.sqlite3"
                cycle = {
                    "schema": "tradecat_auto.service_cycle.v1",
                    "action": "PROCESSED",
                    "latest_event": {"event_id": f"evt-{index}"},
                }
                cycle.update(payload)

                result = record_service_cycle(
                    path, cycle, run_id=f"run-{index}", config_snapshot={}, created_at="2026-05-15T00:00:00Z"
                )

                self.assertFalse(result["ok"], payload)
                self.assertEqual(result["error"]["code"], "real_order_payload_rejected")
                self.assertFalse(path.exists(), payload)

    def test_append_audit_record_rejects_direct_real_order_and_credential_payload_without_creating_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "direct" / "paper_audit.sqlite3"

            result = append_audit_record(
                path,
                event_type="service_cycle",
                payload={
                    "schema": "bad.binance.order_response.v1",
                    "real_order": True,
                    "orderId": 12345,
                    "newClientOrderId": "cli-123",
                    "apiKey": "placeholder",
                    "signature": "abc",
                    "timestamp": 1234567890,
                },
                run_id="bad-run",
                idempotency_key="bad:order",
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["error"]["code"], "real_order_payload_rejected")
            self.assertFalse(path.exists())
            self.assertFalse(path.parent.exists())


if __name__ == "__main__":
    unittest.main()
