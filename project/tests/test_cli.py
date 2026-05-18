from __future__ import annotations

import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tradecat_auto import cli as auto_cli
from tradecat_auto.audit_journal import append_audit_record, journal_summary
from tradecat_auto.binance_market import BinanceApiError
from tradecat_auto.cli import (
    exit_code_for_payload,
    paper_report,
    position_manage_report,
    research_cycle_report,
    run_loop_public,
    run_once_public,
)
from tradecat_auto.paper_ledger import apply_paper_execution, default_paper_ledger, mark_to_market, save_paper_ledger


class FakeClient:
    def market_universe(self):
        return {"ok": True, "symbols": ["IRYSUSDT", "BTCUSDT"]}

    def fetch_public_market_bundle(self, symbol):
        return {
            "ok": True,
            "symbol": symbol,
            "ticker24hr": {"lastPrice": "0.062", "priceChangePercent": "24", "quoteVolume": "50000000"},
            "depth_summary": {"spread_bps": 3.0},
            "openInterest": {"openInterest": "1000000"},
            "openInterestHist": [{"sumOpenInterestValue": "100000"}],
            "fundingRate": [{"fundingRate": "0.00005"}],
            "premiumIndex": {"markPrice": "0.062", "indexPrice": "0.0619"},
            "topLongShortAccountRatio": [{"longShortRatio": "1.1"}],
            "topLongShortPositionRatio": [{"longShortRatio": "1.1"}],
            "globalLongShortAccountRatio": [{"longShortRatio": "1.1"}],
            "takerlongshortRatio": [{"buySellRatio": "1.2"}],
            "errors": {},
        }


class FakeSource:
    def fetch_events(self, *, limit):
        return {"ok": True, "events": [{"event_id": "1", "content": "IRYS"}]}

    def fetch_anomaly_symbols(self, *, tradable_symbols, limit):
        return {
            "ok": True,
            "symbols": [
                {"raw_symbol": "IRYS", "normalized_symbol": "IRYSUSDT", "source_values": {"交易对": "IRYS"}}
            ],
            "rejected": [],
        }


class FakeSourceFactory(FakeSource):
    def __init__(self, root):
        self.root = root


class EmptyAnomalySource(FakeSource):
    def fetch_anomaly_symbols(self, *, tradable_symbols, limit):
        return {"ok": True, "symbols": [], "rejected": []}


class FailingUniverseClient:
    def __init__(self, *, base_url):
        self.base_url = base_url

    def market_universe(self):
        raise BinanceApiError("network error: boom", url=f"{self.base_url}/fapi/v1/exchangeInfo")


class CliTests(unittest.TestCase):

    def test_market_universe_cli_fails_closed_with_json_error_payload_on_binance_failure(self) -> None:
        stdout = io.StringIO()

        with patch.object(auto_cli, "BinanceMarketClient", FailingUniverseClient), contextlib.redirect_stdout(stdout):
            code = auto_cli.main(["market-universe", "--base-url", "https://example.test", "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(payload["schema"], "tradecat_auto.market_universe.v1")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["base_url"], "https://example.test")
        self.assertEqual(payload["symbol_count"], 0)
        self.assertEqual(payload["symbols"], [])
        self.assertEqual(payload["error_code"], "market_universe_failed")
        self.assertIn("BinanceApiError", payload["error"])
        self.assertFalse(payload["real_orders"])
        self.assertFalse(payload["signed_requests"])
        self.assertFalse(payload["reads_api_keys"])
        self.assertEqual(payload["provenance"]["endpoint"], "/fapi/v1/exchangeInfo")
        self.assertFalse(payload["safety"]["binance_account_state"])

    def test_run_once_public_returns_paper_pipeline_report_without_real_orders(self) -> None:
        args = argparse.Namespace(symbol="auto", event_limit=5, anomaly_limit=20, mode="paper", notional_usdt=None, agent_margin_usdt=7.5, paper_leverage=3.0, paper_margin_budget_usdt=None)

        report = run_once_public(args, client=FakeClient(), source=FakeSource())

        self.assertEqual(report["schema"], "tradecat_auto.run_once_report.v1")
        self.assertEqual(report["selected_symbol"], "IRYSUSDT")
        self.assertFalse(report["real_orders"])
        self.assertFalse(report["signed_requests"])
        self.assertFalse(report["reads_api_keys"])
        self.assertEqual(report["provenance"]["source"], "tradecat_auto.pipeline.build_paper_pipeline_report")
        self.assertFalse(report["safety"]["binance_account_state"])
        self.assertEqual(report["paper_execution"]["schema"], "tradecat_auto.paper_execution_report.v1")
        self.assertIn("no real order was placed", report["limitations"])

    def test_run_once_public_does_not_fallback_to_btc_without_anomaly_signal(self) -> None:
        args = argparse.Namespace(symbol="auto", event_limit=5, anomaly_limit=20, mode="paper", notional_usdt=None, agent_margin_usdt=7.5, paper_leverage=3.0, paper_margin_budget_usdt=None)

        report = run_once_public(args, client=FakeClient(), source=EmptyAnomalySource())

        self.assertEqual(report["schema"], "tradecat_auto.run_once_report.v1")
        self.assertFalse(report["ok"])
        self.assertFalse(report["real_orders"])
        self.assertFalse(report["signed_requests"])
        self.assertFalse(report["reads_api_keys"])
        self.assertEqual(report["error_code"], "no_symbol_selected")
        self.assertEqual(report["error"], "no_symbol_selected")
        self.assertEqual(report["provenance"]["source"], "tradecat_auto.cli.run_once_public")
        self.assertFalse(report["safety"]["real_orders"])
        self.assertEqual(report["universe"]["symbol_count"], 2)

    def test_run_once_public_applies_portfolio_abnormal_move_halt_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            thesis_path = root / "agent_exit_plan.json"
            policy_path = root / "portfolio_policy.json"
            thesis_path.write_text(
                json.dumps(
                    {
                        "schema": "tradecat_auto.agent_trade_thesis.v1",
                        "schema_version": "1.0.0",
                        "invalidation_price": 0.055,
                        "take_profit_price": 0.08,
                        "max_holding_minutes": 45,
                    }
                ),
                encoding="utf-8",
            )
            policy_path.write_text(
                json.dumps(
                    {
                        "schema": "tradecat_auto.portfolio_risk_policy.v1",
                        "schema_version": "1.0.0",
                        "mode": "paper",
                        "enabled": True,
                        "new_entries_enabled": True,
                        "limits": {"abnormal_move_halt_bps": 500},
                        "provenance": {"source": "test_cli"},
                    }
                ),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                symbol="auto",
                event_limit=5,
                anomaly_limit=20,
                mode="paper",
                notional_usdt=None,
                agent_margin_usdt=7.5,
                paper_leverage=3.0,
                paper_margin_budget_usdt=None,
                agent_trade_thesis_path=str(thesis_path),
                portfolio_risk_policy_path=str(policy_path),
                paper_kill_switch_path="",
            )

            report = run_once_public(args, client=FakeClient(), source=FakeSource())

        self.assertEqual(report["risk_decision"]["decision"], "REJECT")
        self.assertIn("abnormal_move_halt_active", report["risk_decision"]["reasons"])
        self.assertEqual(report["risk_decision"]["policy"]["portfolio_risk_policy"]["schema"], "tradecat_auto.portfolio_risk_policy.v1")
        self.assertFalse(report["real_orders"])

    def test_research_cycle_report_builds_observe_only_task_without_market_client_or_ledger(self) -> None:
        args = argparse.Namespace(tradecat_public=".", symbol="auto", event_limit=5, anomaly_limit=20, output_dir="")

        report = research_cycle_report(args, source=FakeSource())

        self.assertEqual(report["schema"], "tradecat_auto.agent_research_cycle.v1")
        self.assertEqual(report["schema_version"], "1.0.0")
        self.assertTrue(report["ok"])
        self.assertEqual(report["mode"], "observe_only")
        self.assertEqual(report["symbol"], "IRYSUSDT")
        self.assertIsNone(report["error_code"])
        self.assertEqual(report["next_action"]["action"], "observe_only")
        self.assertFalse(report["next_action"]["writes_paper_ledger"])
        self.assertEqual(report["tool_calls"], [])
        self.assertTrue(report["agent_research_cycle_audit"]["ok"])
        self.assertTrue(report["agent_market_context_audit"]["ok"])
        self.assertEqual(report["observe_only_draft_schemas"]["agent_market_context"], "tradecat_auto.agent_market_context.v1")
        self.assertEqual(report["observe_only_draft_schemas"]["agent_trade_thesis"], "tradecat_auto.agent_trade_thesis.v1")
        self.assertNotIn("paper_execution", report)
        self.assertNotIn("paper_orders", report)
        self.assertFalse(report["safety"]["real_orders"])
        self.assertFalse(report["safety"]["signed_requests"])
        self.assertFalse(report["safety"]["reads_api_keys"])

    def test_research_cycle_cli_smoke_outputs_context_audit_without_paper_execution(self) -> None:
        stdout = io.StringIO()

        with patch.object(auto_cli, "TradeCatPublicSource", FakeSourceFactory), contextlib.redirect_stdout(stdout):
            code = auto_cli.main(["research-cycle", "--symbol", "IRYS", "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["schema"], "tradecat_auto.agent_research_cycle.v1")
        self.assertTrue(payload["agent_market_context_audit"]["ok"])
        self.assertFalse(payload["next_action"]["writes_paper_ledger"])
        self.assertNotIn("paper_execution", payload)
        self.assertFalse(payload["safety"]["real_orders"])

    def test_research_cycle_report_optionally_writes_observe_only_drafts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(
                tradecat_public=".",
                symbol="auto",
                event_limit=5,
                anomaly_limit=20,
                output_dir=str(Path(tmp) / "observe-only"),
            )

            report = research_cycle_report(args, source=FakeSource())

            self.assertTrue(report["draft_outputs"]["ok"])
            self.assertTrue(Path(report["draft_outputs"]["files"]["research_cycle"]).exists())
            self.assertTrue(Path(report["draft_outputs"]["files"]["agent_market_context"]).exists())
            self.assertTrue(Path(report["draft_outputs"]["files"]["agent_trade_thesis"]).exists())
            self.assertFalse(report["draft_outputs"]["safety"]["real_orders"])

    def test_run_loop_public_once_returns_service_cycle_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            thesis_path = Path(tmp) / "agent_exit_plan.json"
            thesis_path.write_text(
                json.dumps(
                    {
                        "schema": "tradecat_auto.agent_trade_thesis.v1",
                        "schema_version": "1.0.0",
                        "invalidation_price": 0.055,
                        "take_profit_price": 0.08,
                        "max_holding_minutes": 45,
                    }
                ),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                symbol="auto",
                event_limit=5,
                anomaly_limit=20,
                mode="paper",
                notional_usdt=None,
                agent_margin_usdt=7.5,
                paper_leverage=3.0,
                paper_margin_budget_usdt=None,
                state_path=str(Path(tmp) / "service_state.json"),
                interval_seconds=60.0,
                max_cycles=1,
                once=True,
                max_event_age_seconds=None,
                agent_trade_thesis_path=str(thesis_path),
            )

            report = run_loop_public(args, client=FakeClient(), source=FakeSource())

            self.assertEqual(report["schema"], "tradecat_auto.service_cycle.v1")
            self.assertEqual(report["action"], "PROCESSED")
            self.assertIsNone(report["error_code"])
            self.assertEqual(report["provenance"]["source"], "tradecat_auto.service.run_service_cycle")
            self.assertFalse(report["safety"]["signed_requests"])
            self.assertEqual(report["pipeline_report"]["selected_symbol"], "IRYSUSDT")

    def test_run_loop_public_respects_local_paper_kill_switch_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            thesis_path = root / "agent_exit_plan.json"
            kill_switch = root / "PAPER_KILL_SWITCH"
            thesis_path.write_text(
                json.dumps(
                    {
                        "schema": "tradecat_auto.agent_trade_thesis.v1",
                        "schema_version": "1.0.0",
                        "invalidation_price": 0.055,
                        "take_profit_price": 0.08,
                        "max_holding_minutes": 45,
                    }
                ),
                encoding="utf-8",
            )
            kill_switch.write_text("pause local paper entries", encoding="utf-8")
            args = argparse.Namespace(
                symbol="auto",
                event_limit=5,
                anomaly_limit=20,
                mode="paper",
                notional_usdt=None,
                agent_margin_usdt=7.5,
                paper_leverage=3.0,
                paper_margin_budget_usdt=None,
                state_path=str(root / "service_state.json"),
                interval_seconds=60.0,
                max_cycles=1,
                once=True,
                max_event_age_seconds=None,
                agent_trade_thesis_path=str(thesis_path),
                portfolio_risk_policy_path="",
                paper_kill_switch_path=str(kill_switch),
            )

            report = run_loop_public(args, client=FakeClient(), source=FakeSource())

        self.assertEqual(report["schema"], "tradecat_auto.service_cycle.v1")
        self.assertEqual(report["pipeline_report"]["risk_decision"]["decision"], "REJECT")
        self.assertIn("kill_switch_active", report["pipeline_report"]["risk_decision"]["reasons"])
        self.assertFalse(report["safety"]["real_orders"])

    def test_run_loop_no_event_payload_is_successful_process_exit_for_systemd_timer(self) -> None:
        payload = {
            "schema": "tradecat_auto.service_cycle.v1",
            "action": "SKIPPED_NO_EVENT",
            "ok": False,
            "reason": "no_events_available",
        }

        self.assertEqual(exit_code_for_payload("run-loop", payload), 0)

    def test_run_loop_real_error_payload_remains_failed_process_exit(self) -> None:
        payload = {
            "schema": "tradecat_auto.service_cycle.v1",
            "action": "ERROR",
            "ok": False,
            "reason": "no_symbol_selected",
        }

        self.assertEqual(exit_code_for_payload("run-loop", payload), 1)

    def test_run_loop_public_rejects_invalid_loop_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(
                symbol="auto",
                event_limit=5,
                anomaly_limit=20,
                mode="paper",
                notional_usdt=None,
                agent_margin_usdt=7.5,
                paper_leverage=3.0,
                paper_margin_budget_usdt=None,
                state_path=str(Path(tmp) / "service_state.json"),
                interval_seconds=0.0,
                max_cycles=1,
                once=False,
                max_event_age_seconds=None,
            )

            with self.assertRaisesRegex(ValueError, "interval_seconds"):
                run_loop_public(args, client=FakeClient(), source=FakeSource(), sleep_func=lambda _: None)

    def test_run_loop_public_rejects_negative_max_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(
                symbol="auto",
                event_limit=5,
                anomaly_limit=20,
                mode="paper",
                notional_usdt=None,
                agent_margin_usdt=7.5,
                paper_leverage=3.0,
                paper_margin_budget_usdt=None,
                state_path=str(Path(tmp) / "service_state.json"),
                interval_seconds=1.0,
                max_cycles=-1,
                once=False,
                max_event_age_seconds=None,
            )

            with self.assertRaisesRegex(ValueError, "max_cycles"):
                run_loop_public(args, client=FakeClient(), source=FakeSource(), sleep_func=lambda _: None)

    def test_run_loop_public_rejects_negative_paper_cost_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(
                symbol="auto",
                event_limit=5,
                anomaly_limit=20,
                mode="paper",
                notional_usdt=None,
                agent_margin_usdt=7.5,
                paper_leverage=3.0,
                paper_margin_budget_usdt=None,
                state_path=str(Path(tmp) / "service_state.json"),
                ledger_path=str(Path(tmp) / "paper_ledger.json"),
                initial_balance_usdt=-1.0,
                paper_fee_bps=-0.1,
                paper_slippage_bps=-0.1,
                interval_seconds=1.0,
                max_cycles=1,
                once=False,
                max_event_age_seconds=None,
                archive_path="",
            )

            with self.assertRaisesRegex(ValueError, "initial_balance_usdt"):
                run_loop_public(args, client=FakeClient(), source=FakeSource(), sleep_func=lambda _: None)

    def test_audit_journal_cli_returns_checksum_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            journal_path = Path(tmp) / "paper_audit.sqlite3"
            record = append_audit_record(
                journal_path,
                event_type="heartbeat",
                payload={"schema": "tradecat_auto.paper_heartbeat.v1", "ok": True},
                run_id="run-cli",
                idempotency_key="heartbeat:run-cli",
                created_at="2026-05-15T00:00:00Z",
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                code = auto_cli.main(["audit-journal", "--journal-path", str(journal_path), "--json"])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["schema"], "tradecat_auto.audit_journal_summary.v1")
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["record_count"], 1)
            self.assertEqual(payload["event_type_counts"]["heartbeat"], 1)
            self.assertEqual(payload["latest_record_sha256"], record["record_sha256"])
            self.assertTrue(payload["chain_valid"])
            self.assertFalse(payload["safety"]["real_orders"])

    def test_paper_report_returns_ledger_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "paper_ledger.json"
            ledger = default_paper_ledger(initial_balance_usdt=1000.0)
            ledger["open_positions"]["IRYSUSDT"] = {"symbol": "IRYSUSDT", "side": "LONG", "entry_price": 1.0, "quantity": 2.0, "last_mark_price": 1.1}
            save_paper_ledger(ledger_path, ledger)

            report = paper_report(argparse.Namespace(ledger_path=str(ledger_path), initial_balance_usdt=1000.0))

            self.assertEqual(report["schema"], "tradecat_auto.paper_report.v1")
            self.assertFalse(report["real_orders"])
            self.assertFalse(report["signed_requests"])
            self.assertFalse(report["reads_api_keys"])
            self.assertIsNone(report["error_code"])
            self.assertEqual(report["summary"]["open_positions_count"], 1)
            self.assertEqual(report["provenance"]["source"], "local_tradecat_paper_ledger")
            self.assertFalse(report["safety"]["signed_requests"])
            self.assertFalse(report["safety"]["reads_api_keys"])
            self.assertIn("IRYSUSDT", report["open_positions"])

    def test_paper_report_fails_closed_for_corrupt_existing_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "paper_ledger.json"
            ledger_path.write_text("{}", encoding="utf-8")

            report = paper_report(argparse.Namespace(ledger_path=str(ledger_path), initial_balance_usdt=1000.0))

            self.assertEqual(report["schema"], "tradecat_auto.paper_report.v1")
            self.assertEqual(report["schema_version"], "1.0.0")
            self.assertFalse(report["ok"])
            self.assertEqual(report["ledger_path"], str(ledger_path))
            self.assertFalse(report["real_orders"])
            self.assertFalse(report["signed_requests"])
            self.assertFalse(report["reads_api_keys"])
            self.assertEqual(report["error_code"], "paper_ledger_load_failed")
            self.assertIn("paper_ledger_load_failed", report["error"])
            self.assertEqual(report["provenance"]["source"], "local_tradecat_paper_ledger")
            self.assertFalse(report["safety"]["real_orders"])

    def test_position_manage_report_applies_adjust_exit_and_writes_audit_journal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = root / "paper_ledger.json"
            thesis_path = root / "position_thesis.json"
            journal_path = root / "paper_audit.sqlite3"
            ledger = apply_paper_execution(default_paper_ledger(initial_balance_usdt=1000.0), {
                "ok": True,
                "status": "OPENED",
                "paper_execution_id": "exec-position-manage",
                "symbol": "IRYSUSDT",
                "side": "LONG",
                "entry_price": 100.0,
                "quantity": 0.2,
                "notional_usdt": 20.0,
                "requested_margin_usdt": 10.0,
                "leverage": 2.0,
                "stop_loss_price": 97.0,
                "take_profit_price": 106.0,
            }, now_iso="2026-05-18T00:00:00Z")
            position_id = ledger["open_positions"]["IRYSUSDT"]["position_id"]
            save_paper_ledger(ledger_path, ledger)
            thesis_path.write_text(
                json.dumps(
                    {
                        "schema": "tradecat_auto.position_management_thesis.v1",
                        "schema_version": "1.0.0",
                        "ok": True,
                        "mode": "paper",
                        "action": "adjust_exit",
                        "symbol": "IRYSUSDT",
                        "position_ref": {"position_id": position_id, "symbol": "IRYSUSDT"},
                        "reason": "Agent tightened local paper exits.",
                        "exit_update": {
                            "stop_loss_price": 98.0,
                            "take_profit_price": 109.0,
                            "max_holding_minutes": 60,
                            "agent_authorized": True,
                            "real_order": False,
                        },
                        "error_code": None,
                        "provenance": {"source": "test_cli_position_manage", "research_cycle_run_id": "cycle-cli-position"},
                        "safety": {
                            "public_readonly_market_data": True,
                            "paper_or_watch_only": True,
                            "real_orders": False,
                            "signed_requests": False,
                            "reads_api_keys": False,
                            "binance_account_state": False,
                        },
                        "hard_boundaries": {
                            "real_orders": False,
                            "signed_requests": False,
                            "reads_api_keys": False,
                            "binance_account_state": False,
                        },
                        "limitations": ["paper/watch only; no real Binance order"],
                    }
                ),
                encoding="utf-8",
            )

            report = position_manage_report(
                argparse.Namespace(
                    thesis_path=str(thesis_path),
                    ledger_path=str(ledger_path),
                    journal_path=str(journal_path),
                    initial_balance_usdt=1000.0,
                    paper_fee_bps=0.0,
                    paper_slippage_bps=0.0,
                    now="2026-05-18T00:10:00Z",
                )
            )
            reloaded = paper_report(argparse.Namespace(ledger_path=str(ledger_path), initial_balance_usdt=1000.0))
            journal = journal_summary(journal_path)

            self.assertEqual(report["schema"], "tradecat_auto.position_management_action_report.v1")
            self.assertTrue(report["ok"])
            self.assertTrue(report["ledger_mutated"])
            self.assertEqual(report["audit_journal"]["schema"], "tradecat_auto.audit_record_write.v1")
            self.assertEqual(journal["event_type_counts"]["position_management_action"], 1)
            self.assertEqual(reloaded["open_positions"]["IRYSUSDT"]["stop_loss_price"], 98.0)
            self.assertEqual(reloaded["open_positions"]["IRYSUSDT"]["exit_plan_source"], "position_management_thesis")
            self.assertFalse(report["safety"]["real_orders"])
            self.assertFalse(report["safety"]["signed_requests"])
            self.assertFalse(report["safety"]["reads_api_keys"])

    def test_production_health_daily_and_alert_payload_cli_commands(self) -> None:
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
                        "cycles_processed": 1,
                        "last_attempt_at": "2026-05-15T00:00:30Z",
                        "last_success_at": "2026-05-15T00:00:30Z",
                        "last_error": None,
                    }
                ),
                encoding="utf-8",
            )
            ledger = apply_paper_execution(default_paper_ledger(), {
                "ok": True,
                "status": "OPENED",
                "paper_execution_id": "exec-cli-prod",
                "symbol": "IRYSUSDT",
                "side": "LONG",
                "entry_price": 100.0,
                "quantity": 0.2,
                "notional_usdt": 20.0,
                "stop_loss_price": 97.0,
                "take_profit_price": 106.0,
            }, now_iso="2026-05-15T00:00:00Z")
            ledger = mark_to_market(ledger, {"IRYSUSDT": 107.0}, now_iso="2026-05-15T00:05:00Z")
            save_paper_ledger(ledger_path, ledger)
            archive_path.write_text('{"schema":"tradecat_auto.service_cycle.v1","action":"PROCESSED","ok":true}\n', encoding="utf-8")
            append_audit_record(journal_path, event_type="service_cycle", payload={"schema": "x", "ok": True}, run_id="run-prod", idempotency_key="service_cycle:run-prod")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = auto_cli.main([
                    "health-report",
                    "--state-path", str(state_path),
                    "--ledger-path", str(ledger_path),
                    "--archive-path", str(archive_path),
                    "--journal-path", str(journal_path),
                    "--now", "2026-05-15T00:01:00Z",
                    "--json",
                ])
            health = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(health["schema"], "tradecat_auto.production_health.v1")
            self.assertTrue(health["ok"])
            self.assertFalse(health["safety"]["real_orders"])

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = auto_cli.main([
                    "daily-report",
                    "--ledger-path", str(ledger_path),
                    "--archive-path", str(archive_path),
                    "--date", "2026-05-15",
                    "--json",
                ])
            daily = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(daily["schema"], "tradecat_auto.daily_paper_report.v1")
            self.assertEqual(daily["cycle_counts"]["PROCESSED"], 1)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = auto_cli.main([
                    "alert-payload",
                    "--kind", "daily",
                    "--ledger-path", str(ledger_path),
                    "--archive-path", str(archive_path),
                    "--date", "2026-05-15",
                    "--json",
                ])
            alert = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(alert["schema"], "tradecat_auto.telegram_alerts.v1")
            self.assertEqual(alert["alerts"][0]["kind"], "daily_report")
            self.assertFalse(alert["alerts"][0]["real_orders"])


if __name__ == "__main__":
    unittest.main()
