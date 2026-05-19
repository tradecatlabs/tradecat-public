from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tradecat_auto.audit_journal import append_audit_record
from tradecat_auto.paper_ledger import apply_paper_execution, default_paper_ledger, mark_to_market, save_paper_ledger
from tradecat_auto.production_control import (
    build_daily_report,
    build_health_report,
    build_latest_cycle_report,
    build_latest_decision_report,
    build_telegram_alerts,
)
from tradecat_auto.safety_boundary import paper_watch_report_flags


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
            archive_path.write_text(
                '{"schema":"tradecat_auto.service_cycle.v1","action":"PROCESSED","ok":true}\n', encoding="utf-8"
            )
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
            self.assertEqual(report["heartbeat"]["status"], "fresh")
            self.assertEqual(report["heartbeat"]["age_seconds"], 30.0)
            self.assertEqual(report["service_state"]["last_error_code"], None)
            self.assertEqual(report["archive"]["cycle_count"], 1)
            self.assertTrue(report["audit_journal"]["chain_valid"])
            self.assertFalse(report["safety"]["real_orders"])
            self.assertFalse(report["safety"]["signed_requests"])

    def test_health_report_flags_stale_or_missing_runtime_as_alertable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "service_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "schema": "tradecat_auto.service_state.v1",
                        "last_attempt_at": "2026-05-15T00:00:00Z",
                        "last_error": "network_error",
                    }
                ),
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
            self.assertEqual(report["heartbeat"]["status"], "stale")
            self.assertEqual(report["service_state"]["last_error_code"], "network_error")
            self.assertIn("heartbeat_stale", report["alerts"])
            self.assertIn("paper_ledger_missing", report["alerts"])
            self.assertIn("cycle_archive_missing", report["alerts"])
            self.assertIn("last_error_present", report["alerts"])

    def test_health_report_ignores_no_events_available_when_runtime_artifacts_are_healthy(self) -> None:
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
                        "cycles_attempted": 4,
                        "cycles_processed": 1,
                        "last_attempt_at": "2026-05-15T00:09:30Z",
                        "last_success_at": "2026-05-15T00:08:30Z",
                        "last_error": "no_events_available",
                    }
                ),
                encoding="utf-8",
            )
            save_paper_ledger(ledger_path, default_paper_ledger(initial_balance_usdt=1000.0))
            archive_path.write_text(
                '{"schema":"tradecat_auto.service_cycle.v1","action":"PROCESSED","ok":true}\n'
                '{"schema":"tradecat_auto.service_cycle.v1","action":"SKIPPED_NO_EVENT","ok":false,"reason":"no_events_available"}\n',
                encoding="utf-8",
            )
            append_audit_record(
                journal_path,
                event_type="service_cycle",
                payload={"schema": "tradecat_auto.service_cycle.v1", "ok": True},
                run_id="evt-2",
                idempotency_key="cycle:evt-2",
                created_at="2026-05-15T00:08:30Z",
            )

            report = build_health_report(
                state_path=state_path,
                ledger_path=ledger_path,
                archive_path=archive_path,
                journal_path=journal_path,
                now_iso="2026-05-15T00:10:00Z",
                max_heartbeat_age_seconds=90,
            )

            self.assertTrue(report["ok"])
            self.assertEqual(report["status"], "healthy")
            self.assertNotIn("last_error_present", report["alerts"])

    def test_health_report_treats_missing_agent_authorization_as_non_runtime_failure(self) -> None:
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
                        "cycles_attempted": 5,
                        "cycles_processed": 2,
                        "last_attempt_at": "2026-05-15T00:09:30Z",
                        "last_error": {
                            "code": "agent_sizing_required",
                            "kind": "risk_reject",
                            "message": "paper pipeline did not open a position",
                            "retryable": True,
                        },
                    }
                ),
                encoding="utf-8",
            )
            save_paper_ledger(ledger_path, default_paper_ledger(initial_balance_usdt=1000.0))
            archive_path.write_text(
                '{"schema":"tradecat_auto.service_cycle.v1","action":"PROCESSED","ok":false,"error_code":"agent_sizing_required"}\n',
                encoding="utf-8",
            )
            append_audit_record(
                journal_path,
                event_type="service_cycle",
                payload={"schema": "tradecat_auto.service_cycle.v1", "ok": False},
                run_id="evt-agent-required",
                idempotency_key="cycle:evt-agent-required",
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

            self.assertTrue(report["ok"])
            self.assertEqual(report["status"], "healthy")
            self.assertEqual(report["service_state"]["last_error_code"], "agent_sizing_required")
            self.assertNotIn("last_error_present", report["alerts"])

    def test_health_report_surfaces_recovered_untrusted_service_state(self) -> None:
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
                        "cycles_attempted": 1,
                        "cycles_processed": 0,
                        "last_attempt_at": "2026-05-15T00:09:30Z",
                        "last_error": {
                            "code": "service_state_load_failed",
                            "kind": "local_runtime_state",
                            "message": "service_state.json: JSONDecodeError",
                            "retryable": False,
                        },
                        "state_load_error": {
                            "code": "service_state_load_failed",
                            "kind": "local_runtime_state",
                            "message": "service_state.json: JSONDecodeError",
                            "retryable": False,
                        },
                        "state_trust_level": "recovered_untrusted",
                    }
                ),
                encoding="utf-8",
            )
            save_paper_ledger(ledger_path, default_paper_ledger(initial_balance_usdt=1000.0))
            archive_path.write_text(
                '{"schema":"tradecat_auto.service_cycle.v1","action":"ERROR","ok":false,"error_code":"service_state_load_failed"}\n',
                encoding="utf-8",
            )
            append_audit_record(
                journal_path,
                event_type="service_cycle",
                payload={"schema": "tradecat_auto.service_cycle.v1", "ok": False},
                run_id="state-load-failed",
                idempotency_key="cycle:state-load-failed",
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

            self.assertFalse(report["ok"])
            self.assertEqual(report["status"], "degraded")
            self.assertEqual(report["service_state"]["last_error_code"], "service_state_load_failed")
            self.assertEqual(
                report["service_state"]["state_load_error"]["code"],
                "service_state_load_failed",
            )
            self.assertEqual(report["service_state"]["state_trust_level"], "recovered_untrusted")
            self.assertIn("last_error_present", report["alerts"])

    def test_health_report_ignores_non_retryable_risk_reject_as_runtime_alert(self) -> None:
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
                        "cycles_attempted": 4,
                        "cycles_processed": 2,
                        "last_attempt_at": "2026-05-15T00:09:30Z",
                        "last_success_at": "2026-05-15T00:08:30Z",
                        "last_error": {
                            "code": "signal_not_tradable",
                            "kind": "risk_reject",
                            "message": "paper pipeline did not open a position",
                            "retryable": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            save_paper_ledger(ledger_path, default_paper_ledger(initial_balance_usdt=1000.0))
            archive_path.write_text(
                '{"schema":"tradecat_auto.service_cycle.v1","action":"PROCESSED","ok":false,"error_code":"signal_not_tradable"}\n',
                encoding="utf-8",
            )
            append_audit_record(
                journal_path,
                event_type="service_cycle",
                payload={"schema": "tradecat_auto.service_cycle.v1", "ok": False},
                run_id="evt-risk-reject",
                idempotency_key="cycle:evt-risk-reject",
                created_at="2026-05-15T00:08:30Z",
            )

            report = build_health_report(
                state_path=state_path,
                ledger_path=ledger_path,
                archive_path=archive_path,
                journal_path=journal_path,
                now_iso="2026-05-15T00:10:00Z",
                max_heartbeat_age_seconds=90,
            )

            self.assertTrue(report["ok"])
            self.assertEqual(report["status"], "healthy")
            self.assertEqual(report["service_state"]["last_error_code"], "signal_not_tradable")
            self.assertNotIn("last_error_present", report["alerts"])

    def test_health_report_treats_legacy_strategy_reject_strings_as_non_runtime_failure(self) -> None:
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
                        "cycles_attempted": 4,
                        "cycles_processed": 2,
                        "last_attempt_at": "2026-05-15T00:09:30Z",
                        "last_error": "strategy_side_blocked",
                    }
                ),
                encoding="utf-8",
            )
            save_paper_ledger(ledger_path, default_paper_ledger(initial_balance_usdt=1000.0))
            archive_path.write_text(
                '{"schema":"tradecat_auto.service_cycle.v1","action":"PROCESSED","ok":false,"error_code":"strategy_side_blocked"}\n',
                encoding="utf-8",
            )
            append_audit_record(
                journal_path,
                event_type="service_cycle",
                payload={"schema": "tradecat_auto.service_cycle.v1", "ok": False},
                run_id="evt-strategy-side-blocked",
                idempotency_key="cycle:evt-strategy-side-blocked",
                created_at="2026-05-15T00:08:30Z",
            )

            report = build_health_report(
                state_path=state_path,
                ledger_path=ledger_path,
                archive_path=archive_path,
                journal_path=journal_path,
                now_iso="2026-05-15T00:10:00Z",
                max_heartbeat_age_seconds=90,
            )

            self.assertTrue(report["ok"])
            self.assertEqual(report["status"], "healthy")
            self.assertEqual(report["service_state"]["last_error_code"], "strategy_side_blocked")
            self.assertNotIn("last_error_present", report["alerts"])

    def test_health_report_returns_degraded_payload_when_local_component_crashes(self) -> None:
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
                        "last_attempt_at": "2026-05-15T00:09:30Z",
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch(
                    "tradecat_auto.production_control._ledger_health",
                    side_effect=RuntimeError("ledger read exploded"),
                ),
                patch(
                    "tradecat_auto.production_control._archive_health",
                    return_value={
                        "ok": True,
                        "path": str(archive_path),
                        "cycle_count": 0,
                        "action_counts": {},
                        "malformed_lines": 0,
                        "last_action": None,
                        "alert": None,
                    },
                ),
                patch(
                    "tradecat_auto.production_control.journal_summary",
                    side_effect=RuntimeError("audit read exploded"),
                ),
            ):
                report = build_health_report(
                    state_path=state_path,
                    ledger_path=ledger_path,
                    archive_path=archive_path,
                    journal_path=journal_path,
                    now_iso="2026-05-15T00:10:00Z",
                    max_heartbeat_age_seconds=90,
                )

            self.assertFalse(report["ok"])
            self.assertEqual(report["status"], "degraded")
            self.assertIn("paper_ledger_health_exception", report["alerts"])
            self.assertIn("audit_journal_health_exception", report["alerts"])
            self.assertEqual(report["ledger"]["error"]["code"], "paper_ledger_health_exception")
            self.assertEqual(report["audit_journal"]["error"]["code"], "audit_journal_health_exception")
            self.assertFalse(report["audit_journal"]["chain_valid"])
            self.assertFalse(report["safety"]["real_orders"])
            self.assertFalse(report["safety"]["signed_requests"])

    def test_daily_report_and_telegram_alerts_are_machine_contract_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = root / "paper_ledger.json"
            archive_path = root / "cycles.jsonl"
            ledger = apply_paper_execution(
                default_paper_ledger(initial_balance_usdt=1000.0),
                {
                    "ok": True,
                    "status": "OPENED",
                    "paper_execution_id": "exec-1",
                    "symbol": "IRYSUSDT",
                    "side": "LONG",
                    "entry_price": 100.0,
                    "quantity": 0.2,
                    "notional_usdt": 20.0,
                    "requested_notional_usdt": 20.0,
                    "requested_margin_usdt": 10.0,
                    "leverage": 2.0,
                    "sizing_source": "agent_supplied_test_fixture",
                    "stop_loss_price": 97.0,
                    "take_profit_price": 106.0,
                },
                now_iso="2026-05-15T00:00:00Z",
            )
            ledger = mark_to_market(ledger, {"IRYSUSDT": 107.0}, now_iso="2026-05-15T00:30:00Z")
            save_paper_ledger(ledger_path, ledger)
            archive_path.write_text(
                "\n".join(
                    [
                        json.dumps({"schema": "tradecat_auto.service_cycle.v1", "action": "PROCESSED", "ok": True}),
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
            self.assertEqual(
                {key: alerts["alerts"][0][key] for key in paper_watch_report_flags()}, paper_watch_report_flags()
            )

    def test_latest_cycle_and_decision_reports_read_auto_paper_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "cycles.jsonl"
            archive_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "schema": "tradecat_auto.service_cycle.v1",
                                "action": "SKIPPED_DUPLICATE_EVENT",
                                "ok": True,
                                "latest_event": {"event_id": "old", "symbol": "OLDUSDT"},
                            }
                        ),
                        json.dumps(
                            {
                                "schema": "tradecat_auto.service_cycle.v1",
                                "action": "PROCESSED",
                                "ok": True,
                                "latest_event": {
                                    "source_dataset_key": "signal_flow",
                                    "source_time_bj": "2026-05-18 23:36:04",
                                    "event_id": "evt-1",
                                    "symbol": "VANAUSDT",
                                    "signal_type": "主动成交多空比翻空",
                                    "content": "VANAUSDT 信号流",
                                },
                                "pipeline_report": {
                                    "schema": "tradecat_auto.run_once_report.v1",
                                    "schema_version": "1.0.0",
                                    "ok": True,
                                    "selected_symbol": "VANAUSDT",
                                    "agent_trade_thesis": {
                                        "symbol": "VANAUSDT",
                                        "direction": "SHORT",
                                        "confidence": 0.7,
                                        "rationale": "public-market taker flow flipped short",
                                    },
                                    "signal": {"symbol": "VANAUSDT", "direction": "SHORT"},
                                    "strategy_intent": {
                                        "action": "OPEN",
                                        "direction": "SHORT",
                                        "entry_price": 1.0,
                                        "invalidation_price": 1.02,
                                        "take_profit_price": 0.96,
                                        "max_holding_minutes": 30,
                                        "exit_plan_source": "agent_trade_thesis",
                                    },
                                    "risk_decision": {"decision": "ALLOW", "reasons": []},
                                    "paper_sizing": {
                                        "source": "agent_trade_thesis.paper_intent",
                                        "requested_margin_usdt": 10.0,
                                        "paper_leverage": 1.0,
                                        "effective_notional_usdt": 10.0,
                                    },
                                    "paper_execution": {
                                        "status": "OPENED",
                                        "side": "SHORT",
                                        "notional_usdt": 10.0,
                                        "margin_usdt": 10.0,
                                        "quantity": 10.0,
                                    },
                                },
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            latest = build_latest_cycle_report(archive_path=archive_path)
            decision = build_latest_decision_report(archive_path=archive_path)

            self.assertEqual(latest["schema"], "tradecat_auto.latest_cycle_report.v1")
            self.assertTrue(latest["ok"])
            self.assertEqual(latest["summary"]["schema"], "tradecat_auto.latest_cycle_summary.v1")
            self.assertEqual(
                latest["summary"]["provenance"]["source"],
                "tradecat_auto.production_control.cycle_summary",
            )
            self.assertFalse(latest["summary"]["safety"]["signed_requests"])
            self.assertEqual(latest["summary"]["event_id"], "evt-1")
            self.assertEqual(decision["schema"], "tradecat_auto.latest_decision_report.v1")
            self.assertTrue(decision["ok"])
            self.assertEqual(decision["symbol"], "VANAUSDT")
            self.assertEqual(decision["risk_decision"], "ALLOW")
            self.assertEqual(decision["paper_execution_status"], "OPENED")
            self.assertEqual(decision["cycle_summary"]["schema"], "tradecat_auto.latest_cycle_summary.v1")
            self.assertFalse(decision["cycle_summary"]["safety"]["reads_api_keys"])
            self.assertIn("public-market taker flow flipped short", decision["text"])
            self.assertIn("止损/失效价: 1.02", decision["text"])
            self.assertFalse(decision["safety"]["real_orders"])

    def test_latest_reports_do_not_trust_archived_pipeline_safety_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "cycles.jsonl"
            archive_path.write_text(
                json.dumps(
                    {
                        "schema": "tradecat_auto.service_cycle.v1",
                        "schema_version": "1.0.0",
                        "action": "PROCESSED",
                        "ok": True,
                        "latest_event": {"event_id": "evt-unsafe-safety", "symbol": "IRYSUSDT"},
                        "pipeline_report": {
                            "schema": "tradecat_auto.run_once_report.v1",
                            "schema_version": "1.0.0",
                            "ok": True,
                            "selected_symbol": "IRYSUSDT",
                            "risk_decision": {"decision": "ALLOW", "reasons": []},
                            "paper_execution": {"status": "OPENED", "side": "LONG"},
                            "safety": {
                                "public_readonly_market_data": False,
                                "public_readonly": False,
                                "paper_or_watch_only": False,
                                "real_orders": True,
                                "signed_requests": True,
                                "reads_api_keys": True,
                                "binance_account_state": True,
                            },
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            latest = build_latest_cycle_report(archive_path=archive_path)
            decision = build_latest_decision_report(archive_path=archive_path)

            self.assertFalse(latest["safety"]["real_orders"])
            self.assertFalse(latest["summary"]["safety"]["signed_requests"])
            self.assertFalse(decision["safety"]["reads_api_keys"])
            self.assertFalse(decision["cycle_summary"]["safety"]["binance_account_state"])

    def test_latest_cycle_and_decision_reports_read_long_tail_jsonl_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "cycles.jsonl"
            long_cycle = {
                "schema": "tradecat_auto.service_cycle.v1",
                "action": "PROCESSED",
                "ok": True,
                "raw_debug_blob": "x" * 1100000,
                "latest_event": {"event_id": "evt-long-tail", "symbol": "BIGUSDT"},
                "pipeline_report": {
                    "schema": "tradecat_auto.run_once_report.v1",
                    "schema_version": "1.0.0",
                    "ok": True,
                    "selected_symbol": "BIGUSDT",
                    "agent_trade_thesis": {
                        "symbol": "BIGUSDT",
                        "direction": "LONG",
                        "confidence": 0.8,
                        "rationale": "large cycle line remains readable",
                    },
                    "risk_decision": {"decision": "ALLOW", "reasons": []},
                    "paper_execution": {"status": "OPENED", "side": "LONG"},
                },
            }
            archive_path.write_text(
                json.dumps({"schema": "tradecat_auto.service_cycle.v1", "action": "PROCESSED", "ok": True})
                + "\n"
                + json.dumps(long_cycle)
                + "\n",
                encoding="utf-8",
            )

            latest = build_latest_cycle_report(archive_path=archive_path)
            decision = build_latest_decision_report(archive_path=archive_path)

            self.assertTrue(latest["ok"])
            self.assertEqual(latest["summary"]["event_id"], "evt-long-tail")
            self.assertTrue(decision["ok"])
            self.assertEqual(decision["symbol"], "BIGUSDT")
            self.assertEqual(decision["paper_execution_status"], "OPENED")

    def test_latest_decision_marks_open_execution_with_runtime_error_as_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "cycles.jsonl"
            archive_path.write_text(
                json.dumps(
                    {
                        "schema": "tradecat_auto.service_cycle.v1",
                        "action": "PROCESSED",
                        "ok": False,
                        "error_code": "paper_ledger_write_failed",
                        "latest_event": {"event_id": "evt-ledger-write-failed", "symbol": "IRYSUSDT"},
                        "pipeline_report": {
                            "schema": "tradecat_auto.run_once_report.v1",
                            "schema_version": "1.0.0",
                            "ok": False,
                            "error_code": "paper_ledger_write_failed",
                            "selected_symbol": "IRYSUSDT",
                            "risk_decision": {"decision": "ALLOW", "reasons": []},
                            "paper_execution": {
                                "status": "OPENED",
                                "side": "LONG",
                                "notional_usdt": 10.0,
                                "margin_usdt": 10.0,
                                "quantity": 10.0,
                            },
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            latest = build_latest_cycle_report(archive_path=archive_path)
            decision = build_latest_decision_report(archive_path=archive_path)

            self.assertEqual(latest["summary"]["paper_execution_status"], "ERROR")
            self.assertEqual(decision["paper_execution_status"], "ERROR")
            self.assertIn("错误码: paper_ledger_write_failed", decision["text"])
            self.assertIn("原始执行状态: OPENED", decision["text"])


if __name__ == "__main__":
    unittest.main()
