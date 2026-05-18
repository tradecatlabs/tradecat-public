from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from tradecat_auto.audit_journal import journal_summary
from tradecat_auto.paper_ledger import default_paper_ledger, save_paper_ledger
from tradecat_auto.production_control import build_daily_report, build_health_report
from tradecat_auto.service import run_service_cycle


class FakeClient:
    def __init__(self) -> None:
        self.universe_calls = 0
        self.bundle_calls = 0

    def market_universe(self):
        self.universe_calls += 1
        return {"ok": True, "symbols": ["IRYSUSDT", "BTCUSDT"], "rate_limits": []}

    def fetch_public_market_bundle(self, symbol):
        self.bundle_calls += 1
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
    def __init__(self, event):
        self.event = event
        self.event_calls = 0
        self.anomaly_calls = 0

    def fetch_events(self, *, limit):
        self.event_calls += 1
        return {"ok": True, "events": [self.event]}

    def fetch_anomaly_symbols(self, *, tradable_symbols, limit):
        self.anomaly_calls += 1
        source_values = {
            "交易对": "IRYS",
            "时间(北京)": self.event.get("source_time_bj", ""),
            "内容": self.event.get("content", ""),
        }
        return {
            "ok": True,
            "symbols": [
                {
                    "raw_symbol": "IRYS",
                    "normalized_symbol": "IRYSUSDT",
                    "source_dataset_key": "anomaly_panel",
                    "first_row_index": 1,
                    "source_values": source_values,
                }
            ],
            "rejected": [],
        }


class SignalFlowSource(FakeSource):
    def fetch_anomaly_symbols(self, *, tradable_symbols, limit):
        return {
            "ok": True,
            "symbols": [
                {
                    "raw_symbol": "IRYS",
                    "normalized_symbol": "IRYSUSDT",
                    "source_dataset_key": "anomaly_panel",
                    "first_row_index": 1,
                    "source_values": {
                        "交易对": "IRYS",
                        "时间(北京)": "2026-05-13 19:57:42",
                        "5m量变化率": "1.23%",
                        "现持仓额": "1000",
                    },
                }
            ],
            "rejected": [],
        }

    def fetch_signal_flow_events(self, *, tradable_symbols, limit):
        return {
            "schema": "tradecat_auto.signal_flow_events.v1",
            "schema_version": "1.0.0",
            "ok": True,
            "source_dataset_key": "signal_flow",
            "events": [
                {
                    "schema": "tradecat_auto.signal_flow_event.v1",
                    "schema_version": "1.0.0",
                    "event_id": "signal-flow-1",
                    "source_dataset_key": "signal_flow",
                    "source_dataset_keys": ["signal_flow", "anomaly_panel"],
                    "row_index": 2,
                    "source_time_bj": "2026-05-13 19:57:42",
                    "symbol": "IRYSUSDT",
                    "raw_symbol": "IRYS",
                    "period": "5分钟",
                    "signal_type": "成交额暴增",
                    "content": "IRYSUSDT 信号流: 时间(北京)=2026-05-13 19:57:42; 交易对=IRYS; 周期=5分钟; 类型=成交额暴增; 内容=成交额暴增",
                    "source_values": {
                        "时间(北京)": "2026-05-13 19:57:42",
                        "交易对": "IRYS",
                        "周期": "5分钟",
                        "类型": "成交额暴增",
                        "内容": "成交额暴增",
                    },
                    "related_anomaly_panel": {
                        "source_dataset_key": "anomaly_panel",
                        "row_index": 1,
                        "normalized_symbol": "IRYSUSDT",
                        "source_values": {
                            "交易对": "IRYS",
                            "5m量变化率": "1.23%",
                            "现持仓额": "1000",
                        },
                    },
                }
            ],
            "rejected": [],
        }


def make_args(**overrides):
    values = {
        "symbol": "auto",
        "mode": "paper",
        "notional_usdt": None,
        "agent_margin_usdt": None,
        "paper_margin_budget_usdt": None,
        "event_limit": 5,
        "anomaly_limit": 20,
        "max_event_age_seconds": 3600,
        "maintenance_interval_seconds": 300.0,
        "ledger_path": "",
        "initial_balance_usdt": 1000.0,
        "paper_leverage": None,
        "agent_trade_thesis_path": "",
        "paper_autonomy_profile_path": "",
        "paper_fee_bps": 4.0,
        "paper_slippage_bps": 0.0,
        "archive_path": "",
        "journal_path": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def write_exit_plan_thesis(root: str | Path, *, research_cycle_run_id: str = "") -> Path:
    thesis_path = Path(root) / "agent_exit_plan.json"
    thesis = {
        "schema": "tradecat_auto.agent_trade_thesis.v1",
        "schema_version": "1.0.0",
        "invalidation_price": 0.055,
        "take_profit_price": 0.08,
        "max_holding_minutes": 45,
        "exit_rationale": "agent supplied invalidation and target",
    }
    if research_cycle_run_id:
        thesis["provenance"] = {"research_cycle_run_id": research_cycle_run_id}
    thesis_path.write_text(json.dumps(thesis), encoding="utf-8")
    return thesis_path


def write_paper_autonomy_profile(root: str | Path) -> Path:
    profile_path = Path(root) / "paper_autonomy_profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "schema": "tradecat_auto.paper_autonomy_profile.v1",
                "schema_version": "1.0.0",
                "ok": True,
                "enabled": True,
                "mode": "paper",
                "paper_intent": {
                    "allow_tradecat_paper_gate_to_decide": True,
                    "requested_margin_usdt": 7.5,
                    "paper_leverage": 2.0,
                    "allow_agent_direction_override": True,
                    "direction_policy": "price_momentum_on_conflict",
                    "min_signal_score": 60,
                    "real_order": False,
                },
                "exit_plan": {
                    "stop_loss_bps": 100,
                    "take_profit_bps": 200,
                    "max_holding_minutes": 45,
                    "exit_rationale": "operator delegated paper autonomy",
                },
                "provenance": {"source": "test_service"},
                "safety": {
                    "public_readonly_market_data": True,
                    "paper_or_watch_only": True,
                    "real_orders": False,
                    "signed_requests": False,
                    "reads_api_keys": False,
                    "binance_account_state": False,
                },
            }
        ),
        encoding="utf-8",
    )
    return profile_path


class ServiceTests(unittest.TestCase):
    def test_run_service_cycle_processes_new_event_and_persists_seen_id(self) -> None:
        event = {
            "event_id": "evt-1",
            "source_time_bj": "2026-05-13 19:57:42",
            "content": "IRYS 异动",
        }
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "service_state.json"
            report = run_service_cycle(
                make_args(),
                state_path=state_path,
                client=FakeClient(),
                source=FakeSource(event),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            self.assertEqual(report["schema"], "tradecat_auto.service_cycle.v1")
            self.assertEqual(report["schema_version"], "1.0.0")
            self.assertFalse(report["real_orders"])
            self.assertFalse(report["signed_requests"])
            self.assertFalse(report["reads_api_keys"])
            self.assertEqual(report["error_code"], "agent_sizing_required")
            self.assertEqual(report["provenance"]["source"], "tradecat_auto.service.run_service_cycle")
            self.assertFalse(report["safety"]["binance_account_state"])
            self.assertEqual(report["action"], "PROCESSED")
            self.assertEqual(report["pipeline_report"]["selected_symbol"], "IRYSUSDT")
            self.assertEqual(report["pipeline_report"]["risk_decision"]["decision"], "REJECT")
            self.assertIn("agent_sizing_required", report["pipeline_report"]["risk_decision"]["reasons"])
            self.assertEqual(report["pipeline_report"]["paper_execution"]["status"], "REJECTED")
            self.assertTrue(state_path.exists())
            self.assertEqual(report["latest_event"]["source_dataset_key"], "anomaly_panel")
            self.assertEqual(report["latest_event"]["symbol"], "IRYSUSDT")
            self.assertIn(report["latest_event"]["event_id"], state_path.read_text(encoding="utf-8"))

    def test_run_service_cycle_prefers_signal_flow_as_input_event(self) -> None:
        event = {
            "event_id": "evt-anomaly",
            "source_time_bj": "2026-05-13 19:57:42",
            "content": "IRYS 异动",
        }
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "service_state.json"
            report = run_service_cycle(
                make_args(),
                state_path=state_path,
                client=FakeClient(),
                source=SignalFlowSource(event),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            self.assertEqual(report["action"], "PROCESSED")
            self.assertEqual(report["latest_event"]["source_dataset_key"], "signal_flow")
            self.assertEqual(report["latest_event"]["period"], "5分钟")
            self.assertEqual(report["pipeline_report"]["latest_event"]["source_dataset_key"], "signal_flow")
            self.assertEqual(report["pipeline_report"]["enrichment"]["source_layers"][0], "tradecat_signal_flow")
            self.assertIn("现持仓额", report["latest_event"]["related_anomaly_panel"]["source_values"])

    def test_run_service_cycle_skips_duplicate_event_before_binance_market_calls(self) -> None:
        event = {
            "event_id": "evt-dup",
            "source_time_bj": "2026-05-13 19:57:42",
            "content": "IRYS 异动",
        }
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "service_state.json"
            client = FakeClient()
            source = FakeSource(event)
            now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)

            first = run_service_cycle(make_args(), state_path=state_path, client=client, source=source, now=now)
            second = run_service_cycle(make_args(), state_path=state_path, client=client, source=source, now=now)

            self.assertEqual(first["action"], "PROCESSED")
            self.assertEqual(second["action"], "SKIPPED_DUPLICATE_EVENT")
            self.assertEqual(second["reason"], "input_snapshot_unchanged")
            self.assertEqual(client.bundle_calls, 1)
            self.assertEqual(client.universe_calls, 2)

    def test_run_service_cycle_processes_when_anomaly_snapshot_changes_with_same_signal_event(self) -> None:
        class ChangingAnomalySource(SignalFlowSource):
            def __init__(self, event):
                super().__init__(event)
                self.value = 0

            def fetch_anomaly_symbols(self, *, tradable_symbols, limit):
                self.value += 1
                return {
                    "ok": True,
                    "symbols": [
                        {
                            "raw_symbol": "IRYS",
                            "normalized_symbol": "IRYSUSDT",
                            "source_dataset_key": "anomaly_panel",
                            "first_row_index": 1,
                            "source_values": {
                                "交易对": "IRYS",
                                "5m量变化率": f"{self.value}.23%",
                                "现持仓额": "1000",
                            },
                        }
                    ],
                    "rows": [
                        {
                            "raw_symbol": "IRYS",
                            "normalized_symbol": "IRYSUSDT",
                            "source_dataset_key": "anomaly_panel",
                            "section": "5m 异动榜",
                            "source_values": {
                                "交易对": "IRYS",
                                "榜单": "5m 异动榜",
                                "5m量变化率": f"{self.value}.23%",
                                "现持仓额": "1000",
                            },
                        }
                    ],
                    "sections": [{"name": "5m 异动榜", "row_count": 1}],
                    "rejected": [],
                }

        event = {"event_id": "evt-anomaly-change", "source_time_bj": "2026-05-13 19:57:42", "content": "IRYS 异动"}
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "service_state.json"
            client = FakeClient()
            source = ChangingAnomalySource(event)
            now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)

            first = run_service_cycle(make_args(), state_path=state_path, client=client, source=source, now=now)
            second = run_service_cycle(make_args(), state_path=state_path, client=client, source=source, now=now)

            self.assertEqual(first["action"], "PROCESSED")
            self.assertEqual(second["action"], "PROCESSED")
            self.assertTrue(second["input_change"]["anomaly_panel_changed"])
            self.assertEqual(second["input_change"]["trigger_reason"], "anomaly_panel_snapshot_changed")
            self.assertEqual(client.bundle_calls, 2)

    def test_run_service_cycle_runs_maintenance_after_idle_without_new_input(self) -> None:
        event = {
            "event_id": "evt-maintenance",
            "source_time_bj": "2026-05-13 19:57:42",
            "content": "IRYS 异动",
        }
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "paper_ledger.json"
            ledger = default_paper_ledger(initial_balance_usdt=1000.0)
            ledger["open_positions"]["IRYSUSDT"] = {
                "position_id": "pos-IRYSUSDT",
                "symbol": "IRYSUSDT",
                "side": "LONG",
                "entry_price": 0.05,
                "quantity": 100.0,
                "notional_usdt": 5.0,
                "stop_loss_price": 0.01,
                "take_profit_price": 10.0,
                "status": "OPEN",
            }
            save_paper_ledger(ledger_path, ledger)
            state_path = Path(tmp) / "service_state.json"
            client = FakeClient()
            source = FakeSource(event)

            first = run_service_cycle(
                make_args(ledger_path=str(ledger_path), maintenance_interval_seconds=60),
                state_path=state_path,
                client=client,
                source=source,
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )
            second = run_service_cycle(
                make_args(ledger_path=str(ledger_path), maintenance_interval_seconds=60),
                state_path=state_path,
                client=client,
                source=source,
                now=datetime(2026, 5, 13, 12, 2, tzinfo=UTC),
            )

            self.assertEqual(first["action"], "PROCESSED")
            self.assertEqual(second["action"], "MAINTENANCE_NO_INPUT_CHANGE")
            self.assertEqual(second["reason"], "maintenance_due")
            self.assertEqual(second["input_change"]["trigger_reason"], "maintenance_due")
            self.assertIn("paper_ledger", second)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["cycles_maintenance"], 1)
            self.assertEqual(state["last_maintenance_at"], "2026-05-13T12:02:00Z")

    def test_run_service_cycle_skips_stale_event_before_binance_market_calls(self) -> None:
        event = {
            "event_id": "evt-stale",
            "source_time_bj": "2026-05-13 18:00:00",
            "content": "IRYS 旧异动",
        }
        client = FakeClient()
        with tempfile.TemporaryDirectory() as tmp:
            report = run_service_cycle(
                make_args(max_event_age_seconds=1800),
                state_path=Path(tmp) / "service_state.json",
                client=client,
                source=FakeSource(event),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            self.assertEqual(report["action"], "SKIPPED_STALE_EVENT")
            self.assertIn("stale", report["reason"])
            self.assertEqual(client.bundle_calls, 0)
            self.assertEqual(client.universe_calls, 1)

    def test_run_service_cycle_archives_no_event_poll_without_market_calls(self) -> None:
        class EmptySource:
            def fetch_events(self, *, limit):
                return {"ok": True, "events": []}

            def fetch_anomaly_symbols(self, *, tradable_symbols, limit):
                return {"ok": True, "symbols": [], "rejected": []}

        client = FakeClient()
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "cycles.jsonl"
            state_path = Path(tmp) / "service_state.json"

            report = run_service_cycle(
                make_args(archive_path=str(archive_path)),
                state_path=state_path,
                client=client,
                source=EmptySource(),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            self.assertEqual(report["action"], "SKIPPED_NO_EVENT")
            self.assertFalse(report["ok"])
            self.assertEqual(report["error_code"], "no_anomaly_signal_available")
            self.assertEqual(report["reason"], "no_anomaly_signal_available")
            self.assertEqual(report["provenance"]["source"], "tradecat_auto.service.run_service_cycle")
            self.assertEqual(client.bundle_calls, 0)
            self.assertEqual(client.universe_calls, 1)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["cycles_attempted"], 1)
            self.assertEqual(state["cycles_processed"], 0)
            self.assertEqual(state["last_error"], "no_anomaly_signal_available")
            rows = [json.loads(line) for line in archive_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["action"], "SKIPPED_NO_EVENT")
            self.assertEqual(rows[0]["reason"], "no_anomaly_signal_available")

    def test_run_service_cycle_monitors_open_positions_when_no_event(self) -> None:
        class EmptySource:
            def fetch_events(self, *, limit):
                return {"ok": True, "events": []}

            def fetch_anomaly_symbols(self, *, tradable_symbols, limit):
                return {"ok": True, "symbols": [], "rejected": []}

        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "paper_ledger.json"
            ledger = default_paper_ledger(initial_balance_usdt=1000.0)
            ledger["open_positions"]["IRYSUSDT"] = {
                "position_id": "pos-IRYSUSDT",
                "symbol": "IRYSUSDT",
                "side": "LONG",
                "entry_price": 0.05,
                "quantity": 100.0,
                "notional_usdt": 5.0,
                "stop_loss_price": 0.01,
                "take_profit_price": 10.0,
                "status": "OPEN",
            }
            save_paper_ledger(ledger_path, ledger)
            client = FakeClient()
            report = run_service_cycle(
                make_args(ledger_path=str(ledger_path)),
                state_path=Path(tmp) / "service_state.json",
                client=client,
                source=EmptySource(),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            self.assertEqual(report["action"], "SKIPPED_NO_EVENT")
            self.assertEqual(report["error_code"], "no_anomaly_signal_available")
            self.assertEqual(client.bundle_calls, 1)
            self.assertIn("paper_ledger", report)
            self.assertEqual(report["paper_ledger"]["open_positions_count"], 1)
            updated = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(updated["last_updated_at"], "2026-05-13T12:00:00Z")
            self.assertGreater(updated["unrealized_pnl_usdt"], 0.0)

    def test_run_service_cycle_uses_lightweight_last_price_for_existing_positions(self) -> None:
        class EmptySource:
            def fetch_anomaly_symbols(self, *, tradable_symbols, limit):
                return {"ok": True, "symbols": [], "rejected": []}

            def fetch_signal_flow_events(self, *, tradable_symbols, limit):
                return {
                    "schema": "tradecat_auto.signal_flow_events.v1",
                    "schema_version": "1.0.0",
                    "ok": False,
                    "source_dataset_key": "signal_flow",
                    "events": [],
                    "rejected": [],
                    "error_code": "no_signal_flow_available",
                    "error": {"code": "no_signal_flow_available"},
                }

        class LightweightClient(FakeClient):
            def __init__(self) -> None:
                super().__init__()
                self.price_calls = 0

            def fetch_last_price(self, symbol):
                self.price_calls += 1
                return {
                    "schema": "tradecat_auto.public_last_price.v1",
                    "schema_version": "1.0.0",
                    "ok": True,
                    "symbol": symbol,
                    "last_price": 0.062,
                }

        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "paper_ledger.json"
            ledger = default_paper_ledger(initial_balance_usdt=1000.0)
            ledger["open_positions"]["IRYSUSDT"] = {
                "position_id": "pos-IRYSUSDT",
                "symbol": "IRYSUSDT",
                "side": "LONG",
                "entry_price": 0.05,
                "quantity": 100.0,
                "notional_usdt": 5.0,
                "status": "OPEN",
                "exit_plan_source": "agent_required_missing",
            }
            save_paper_ledger(ledger_path, ledger)
            client = LightweightClient()

            report = run_service_cycle(
                make_args(ledger_path=str(ledger_path)),
                state_path=Path(tmp) / "service_state.json",
                client=client,
                source=EmptySource(),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            self.assertEqual(report["action"], "SKIPPED_NO_EVENT")
            self.assertEqual(client.price_calls, 1)
            self.assertEqual(client.bundle_calls, 0)
            self.assertIn("paper_ledger", report)
            updated = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertGreater(updated["unrealized_pnl_usdt"], 0.0)

    def test_run_service_cycle_batches_last_prices_for_existing_positions(self) -> None:
        class EmptySource:
            def fetch_anomaly_symbols(self, *, tradable_symbols, limit):
                return {"ok": True, "symbols": [], "rejected": []}

            def fetch_signal_flow_events(self, *, tradable_symbols, limit):
                return {
                    "schema": "tradecat_auto.signal_flow_events.v1",
                    "schema_version": "1.0.0",
                    "ok": False,
                    "source_dataset_key": "signal_flow",
                    "events": [],
                    "rejected": [],
                    "error_code": "no_signal_flow_available",
                    "error": {"code": "no_signal_flow_available"},
                }

        class BatchPriceClient(FakeClient):
            def __init__(self) -> None:
                super().__init__()
                self.batch_price_calls = 0
                self.single_price_calls = 0

            def fetch_last_prices(self, symbols):
                self.batch_price_calls += 1
                return {
                    "schema": "tradecat_auto.public_last_prices.v1",
                    "schema_version": "1.0.0",
                    "ok": True,
                    "symbols": list(symbols),
                    "prices": {"IRYSUSDT": 0.062, "BTCUSDT": 100.0},
                    "missing_symbols": [],
                }

            def fetch_last_price(self, symbol):
                self.single_price_calls += 1
                return {"ok": False, "error": "single price should not be called"}

        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "paper_ledger.json"
            ledger = default_paper_ledger(initial_balance_usdt=1000.0)
            ledger["open_positions"]["pos-IRYSUSDT"] = {
                "position_id": "pos-IRYSUSDT",
                "symbol": "IRYSUSDT",
                "side": "LONG",
                "entry_price": 0.05,
                "quantity": 100.0,
                "notional_usdt": 5.0,
                "status": "OPEN",
                "exit_plan_source": "agent_trade_thesis",
            }
            ledger["open_positions"]["pos-BTCUSDT"] = {
                "position_id": "pos-BTCUSDT",
                "symbol": "BTCUSDT",
                "side": "LONG",
                "entry_price": 90.0,
                "quantity": 0.1,
                "notional_usdt": 9.0,
                "status": "OPEN",
                "exit_plan_source": "agent_trade_thesis",
            }
            save_paper_ledger(ledger_path, ledger)
            client = BatchPriceClient()

            report = run_service_cycle(
                make_args(ledger_path=str(ledger_path)),
                state_path=Path(tmp) / "service_state.json",
                client=client,
                source=EmptySource(),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            self.assertEqual(report["action"], "SKIPPED_NO_EVENT")
            self.assertEqual(client.batch_price_calls, 1)
            self.assertEqual(client.single_price_calls, 0)
            self.assertEqual(client.bundle_calls, 0)
            updated = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(len(updated["open_positions"]), 2)
            self.assertGreater(updated["unrealized_pnl_usdt"], 0.0)

    def test_run_service_cycle_preserves_event_source_error_code(self) -> None:
        class BrokenSource:
            def fetch_events(self, *, limit):
                return {
                    "ok": False,
                    "error_code": "remote_http_status",
                    "error": {"code": "remote_http_status", "status": 404},
                    "events": [],
                }

            def fetch_anomaly_symbols(self, *, tradable_symbols, limit):
                return {
                    "ok": False,
                    "error_code": "remote_http_status",
                    "error": {"code": "remote_http_status", "status": 404},
                    "symbols": [],
                    "rejected": [],
                }

        client = FakeClient()
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "service_state.json"
            report = run_service_cycle(
                make_args(),
                state_path=state_path,
                client=client,
                source=BrokenSource(),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            self.assertEqual(report["action"], "SKIPPED_NO_EVENT")
            self.assertFalse(report["ok"])
            self.assertEqual(report["error_code"], "remote_http_status")
            self.assertEqual(report["reason"], "remote_http_status")
            self.assertEqual(report["events"]["error"]["status"], 404)
            self.assertEqual(client.bundle_calls, 0)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["last_error"], "remote_http_status")

    def test_run_service_cycle_archives_and_audits_no_symbol_selected(self) -> None:
        class EmptyUniverseClient(FakeClient):
            def market_universe(self):
                self.universe_calls += 1
                return {"ok": True, "symbols": [], "rate_limits": []}

        class NoSymbolSource(FakeSource):
            def fetch_anomaly_symbols(self, *, tradable_symbols, limit):
                self.anomaly_calls += 1
                return {"ok": True, "symbols": [], "rejected": []}

        event = {"event_id": "evt-no-symbol", "source_time_bj": "2026-05-13 19:57:42", "content": "UNKNOWN 异动"}
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "cycles.jsonl"
            journal_path = Path(tmp) / "paper_audit.sqlite3"
            client = EmptyUniverseClient()

            report = run_service_cycle(
                make_args(archive_path=str(archive_path), journal_path=str(journal_path)),
                state_path=Path(tmp) / "service_state.json",
                client=client,
                source=NoSymbolSource(event),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            self.assertEqual(report["action"], "SKIPPED_NO_EVENT")
            self.assertFalse(report["ok"])
            self.assertEqual(report["error_code"], "no_anomaly_signal_available")
            self.assertEqual(report["reason"], "no_anomaly_signal_available")
            self.assertEqual(client.bundle_calls, 0)
            self.assertIn("audit_journal", report)
            self.assertTrue(report["audit_journal"]["ok"])
            rows = [json.loads(line) for line in archive_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["action"], "SKIPPED_NO_EVENT")
            self.assertEqual(rows[0]["reason"], "no_anomaly_signal_available")
            self.assertEqual(rows[0]["audit_journal"]["schema"], "tradecat_auto.audit_journal_write.v1")
            summary = journal_summary(journal_path)
            self.assertTrue(summary["ok"])
            self.assertEqual(summary["event_type_counts"]["service_cycle"], 1)

    def test_run_service_cycle_does_not_fallback_to_btc_without_anomaly_signal(self) -> None:
        class NoSymbolSource(FakeSource):
            def fetch_anomaly_symbols(self, *, tradable_symbols, limit):
                self.anomaly_calls += 1
                return {"ok": True, "symbols": [], "rejected": []}

        event = {
            "event_id": "evt-no-anomaly-symbol",
            "source_time_bj": "2026-05-13 19:57:42",
            "content": "无可交易异动",
        }
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()

            report = run_service_cycle(
                make_args(),
                state_path=Path(tmp) / "service_state.json",
                client=client,
                source=NoSymbolSource(event),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            self.assertEqual(report["action"], "SKIPPED_NO_EVENT")
            self.assertFalse(report["ok"])
            self.assertEqual(report["error_code"], "no_anomaly_signal_available")
            self.assertEqual(report["reason"], "no_anomaly_signal_available")
            self.assertEqual(client.bundle_calls, 0)
            self.assertEqual(client.universe_calls, 1)

    def test_run_service_cycle_updates_paper_ledger_when_execution_opens(self) -> None:
        event = {
            "event_id": "evt-ledger",
            "source_time_bj": "2026-05-13 19:57:42",
            "content": "IRYS 异动",
        }
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "paper_ledger.json"
            thesis_path = write_exit_plan_thesis(tmp)
            report = run_service_cycle(
                make_args(
                    ledger_path=str(ledger_path),
                    agent_margin_usdt=7.5,
                    paper_leverage=1.0,
                    agent_trade_thesis_path=str(thesis_path),
                ),
                state_path=Path(tmp) / "service_state.json",
                client=FakeClient(),
                source=FakeSource(event),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            self.assertEqual(report["action"], "PROCESSED")
            self.assertIn("paper_ledger", report)
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertIn("IRYSUSDT", ledger["open_positions"])
            self.assertEqual(len(ledger["fills"]), 1)
            self.assertEqual(ledger["open_positions"]["IRYSUSDT"]["leverage"], 1.0)
            self.assertEqual(ledger["open_positions"]["IRYSUSDT"]["sizing_source"], "agent_supplied_cli_margin")
            position = ledger["open_positions"]["IRYSUSDT"]
            self.assertAlmostEqual(position["notional_usdt"], 7.5)
            self.assertEqual(position["fee_bps"], 4.0)
            self.assertEqual(
                position["execution_cost_model"]["error_code"],
                "paper_cost_depth_fallback_used",
            )
            self.assertEqual(position["execution_cost_model"]["fallback_slippage_bps"], 0.0)

    def test_run_service_cycle_uses_agent_trade_thesis_sizing_and_exit_plan(self) -> None:
        event = {
            "event_id": "evt-thesis",
            "source_time_bj": "2026-05-13 19:57:42",
            "content": "IRYS 异动",
        }
        thesis = {
            "schema": "tradecat_auto.agent_trade_thesis.v1",
            "schema_version": "1.0.0",
            "paper_intent": {
                "requested_margin_usdt": 7.5,
                "paper_leverage": 2.0,
            },
            "invalidation_price": 0.055,
            "take_profit_price": 0.08,
            "max_holding_minutes": 45,
            "exit_rationale": "agent supplied invalidation and target",
        }
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "paper_ledger.json"
            thesis_path = Path(tmp) / "agent_trade_thesis.json"
            thesis_path.write_text(json.dumps(thesis), encoding="utf-8")

            report = run_service_cycle(
                make_args(ledger_path=str(ledger_path), agent_trade_thesis_path=str(thesis_path)),
                state_path=Path(tmp) / "service_state.json",
                client=FakeClient(),
                source=FakeSource(event),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            self.assertEqual(report["action"], "PROCESSED")
            self.assertTrue(report["pipeline_report"]["ok"])
            self.assertFalse(report["safety"]["real_orders"])
            self.assertFalse(report["safety"]["signed_requests"])
            self.assertFalse(report["safety"]["reads_api_keys"])
            self.assertEqual(report["pipeline_report"]["paper_execution"]["status"], "OPENED")
            self.assertEqual(report["pipeline_report"]["paper_sizing"]["source"], "agent_trade_thesis.paper_intent")
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            position = ledger["open_positions"]["IRYSUSDT"]
            self.assertEqual(position["leverage"], 2.0)
            self.assertEqual(position["requested_margin_usdt"], 7.5)
            self.assertEqual(position["sizing_source"], "agent_trade_thesis.paper_intent")
            self.assertEqual(position["stop_loss_price"], 0.055)
            self.assertEqual(position["take_profit_price"], 0.08)
            self.assertEqual(position["max_holding_minutes"], 45.0)
            self.assertEqual(position["exit_plan_source"], "agent_trade_thesis")

    def test_run_service_cycle_uses_paper_autonomy_profile_when_thesis_missing(self) -> None:
        event = {
            "event_id": "evt-profile",
            "source_time_bj": "2026-05-13 19:57:42",
            "content": "IRYS 异动",
        }
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "paper_ledger.json"
            profile_path = write_paper_autonomy_profile(tmp)

            report = run_service_cycle(
                make_args(ledger_path=str(ledger_path), paper_autonomy_profile_path=str(profile_path)),
                state_path=Path(tmp) / "service_state.json",
                client=FakeClient(),
                source=FakeSource(event),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            self.assertEqual(report["action"], "PROCESSED")
            self.assertTrue(report["pipeline_report"]["ok"])
            self.assertFalse(report["safety"]["real_orders"])
            self.assertFalse(report["safety"]["signed_requests"])
            self.assertFalse(report["safety"]["reads_api_keys"])
            self.assertTrue(report["pipeline_report"]["agent_trade_thesis"]["paper_autonomy_profile"])
            self.assertEqual(report["pipeline_report"]["paper_sizing"]["source"], "agent_trade_thesis.paper_intent")
            self.assertEqual(report["pipeline_report"]["paper_execution"]["status"], "OPENED")
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            position = ledger["open_positions"]["IRYSUSDT"]
            self.assertEqual(position["leverage"], 2.0)
            self.assertEqual(position["requested_margin_usdt"], 7.5)
            self.assertEqual(position["sizing_source"], "agent_trade_thesis.paper_intent")
            self.assertAlmostEqual(position["stop_loss_price"], 0.06138)
            self.assertAlmostEqual(position["take_profit_price"], 0.06324)
            self.assertEqual(position["max_holding_minutes"], 45.0)
            self.assertEqual(position["exit_plan_source"], "agent_trade_thesis")

    def test_run_service_cycle_fails_closed_when_agent_trade_thesis_path_is_invalid(self) -> None:
        event = {
            "event_id": "evt-thesis-missing",
            "source_time_bj": "2026-05-13 19:57:42",
            "content": "IRYS 异动",
        }
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            report = run_service_cycle(
                make_args(agent_trade_thesis_path=str(Path(tmp) / "missing.json")),
                state_path=Path(tmp) / "service_state.json",
                client=client,
                source=FakeSource(event),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            self.assertEqual(report["action"], "ERROR")
            self.assertFalse(report["ok"])
            self.assertEqual(report["error_code"], "agent_trade_thesis_load_failed")
            self.assertEqual(report["error"]["code"], "agent_trade_thesis_load_failed")
            self.assertEqual(client.bundle_calls, 0)
            self.assertEqual(client.universe_calls, 0)

    def test_run_service_cycle_fails_closed_when_paper_autonomy_profile_path_is_invalid(self) -> None:
        event = {
            "event_id": "evt-profile-missing",
            "source_time_bj": "2026-05-13 19:57:42",
            "content": "IRYS 异动",
        }
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            report = run_service_cycle(
                make_args(paper_autonomy_profile_path=str(Path(tmp) / "missing.json")),
                state_path=Path(tmp) / "service_state.json",
                client=client,
                source=FakeSource(event),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            self.assertEqual(report["action"], "ERROR")
            self.assertFalse(report["ok"])
            self.assertEqual(report["error_code"], "paper_autonomy_profile_load_failed")
            self.assertEqual(report["error"]["code"], "paper_autonomy_profile_load_failed")
            self.assertEqual(client.bundle_calls, 0)
            self.assertEqual(client.universe_calls, 0)

    def test_run_service_cycle_applies_paper_leverage_to_effective_notional(self) -> None:
        event = {
            "event_id": "evt-leverage",
            "source_time_bj": "2026-05-13 19:57:42",
            "content": "IRYS 异动",
        }
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "paper_ledger.json"
            thesis_path = write_exit_plan_thesis(tmp)
            report = run_service_cycle(
                make_args(
                    ledger_path=str(ledger_path),
                    agent_margin_usdt=7.5,
                    paper_leverage=3.0,
                    paper_fee_bps=2.0,
                    paper_slippage_bps=0.5,
                    agent_trade_thesis_path=str(thesis_path),
                ),
                state_path=Path(tmp) / "service_state.json",
                client=FakeClient(),
                source=FakeSource(event),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            self.assertEqual(report["pipeline_report"]["paper_leverage"], 3.0)
            self.assertEqual(report["pipeline_report"]["requested_margin_usdt"], 7.5)
            self.assertEqual(report["pipeline_report"]["effective_notional_usdt"], 22.5)
            position = json.loads(ledger_path.read_text(encoding="utf-8"))["open_positions"]["IRYSUSDT"]
            self.assertEqual(position["leverage"], 3.0)
            self.assertEqual(position["sizing_source"], "agent_supplied_cli_margin")
            self.assertAlmostEqual(position["margin_usdt"], position["notional_usdt"] / 3.0)

    def test_run_service_cycle_records_existing_ledger_position_count_without_default_cap(self) -> None:
        event = {
            "event_id": "evt-risk-ledger",
            "source_time_bj": "2026-05-13 19:57:42",
            "content": "IRYS 异动",
        }
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "paper_ledger.json"
            ledger = default_paper_ledger(initial_balance_usdt=1000.0)
            for symbol in ("IRYSUSDT", "BTCUSDT", "ETHUSDT"):
                ledger["open_positions"][symbol] = {
                    "position_id": f"pos-{symbol}",
                    "symbol": symbol,
                    "side": "LONG",
                    "entry_price": 0.05,
                    "quantity": 1.0,
                    "notional_usdt": 0.05,
                    "stop_loss_price": 0.01,
                    "take_profit_price": 10.0,
                    "status": "OPEN",
                }
            save_paper_ledger(ledger_path, ledger)
            thesis_path = write_exit_plan_thesis(tmp)

            report = run_service_cycle(
                make_args(
                    ledger_path=str(ledger_path),
                    agent_margin_usdt=7.5,
                    paper_leverage=3.0,
                    agent_trade_thesis_path=str(thesis_path),
                ),
                state_path=Path(tmp) / "service_state.json",
                client=FakeClient(),
                source=FakeSource(event),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            risk = report["pipeline_report"]["risk_decision"]
            self.assertEqual(risk["decision"], "ALLOW")
            self.assertEqual(risk["policy"]["current_open_positions"], 3)
            self.assertNotIn("max_open_positions_reached", risk["reasons"])
            self.assertIsNone(risk["policy"]["max_open_positions"])

    def test_run_service_cycle_records_existing_ledger_total_notional_without_default_cap(self) -> None:
        event = {
            "event_id": "evt-risk-ledger-notional",
            "source_time_bj": "2026-05-13 19:57:42",
            "content": "IRYS 异动",
        }
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "paper_ledger.json"
            ledger = default_paper_ledger(initial_balance_usdt=1000.0)
            for symbol, notional in (("BTCUSDT", 25.0), ("ETHUSDT", 20.0)):
                ledger["open_positions"][symbol] = {
                    "position_id": f"pos-{symbol}",
                    "symbol": symbol,
                    "side": "LONG",
                    "entry_price": 1.0,
                    "quantity": notional,
                    "notional_usdt": notional,
                    "stop_loss_price": 0.01,
                    "take_profit_price": 100.0,
                    "status": "OPEN",
                }
            save_paper_ledger(ledger_path, ledger)
            thesis_path = write_exit_plan_thesis(tmp)

            report = run_service_cycle(
                make_args(
                    ledger_path=str(ledger_path),
                    agent_margin_usdt=7.5,
                    paper_leverage=1.0,
                    agent_trade_thesis_path=str(thesis_path),
                ),
                state_path=Path(tmp) / "service_state.json",
                client=FakeClient(),
                source=FakeSource(event),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            risk = report["pipeline_report"]["risk_decision"]
            self.assertEqual(risk["decision"], "ALLOW")
            self.assertEqual(risk["policy"]["current_total_notional_usdt"], 45.0)
            self.assertNotIn("max_total_notional_reached", risk["reasons"])
            self.assertIsNone(risk["policy"]["max_total_notional_usdt"])

    def test_run_service_cycle_risk_uses_same_day_loss_and_consecutive_loss_streak(self) -> None:
        event = {
            "event_id": "evt-risk-loss-streak",
            "source_time_bj": "2026-05-13 19:57:42",
            "content": "IRYS 异动",
        }
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "paper_ledger.json"
            ledger = default_paper_ledger(initial_balance_usdt=1000.0)
            ledger["closed_positions"] = [
                {"symbol": "BTCUSDT", "closed_at": "2026-05-12T23:00:00Z", "net_pnl_usdt": 999.0, "status": "CLOSED"},
                {"symbol": "ETHUSDT", "closed_at": "2026-05-13T09:00:00Z", "net_pnl_usdt": -7.5, "status": "CLOSED"},
                {"symbol": "SOLUSDT", "closed_at": "2026-05-13T10:00:00Z", "net_pnl_usdt": -7.5, "status": "CLOSED"},
                {"symbol": "BNBUSDT", "closed_at": "2026-05-13T11:00:00Z", "net_pnl_usdt": -7.5, "status": "CLOSED"},
            ]
            save_paper_ledger(ledger_path, ledger)
            thesis_path = write_exit_plan_thesis(tmp)

            report = run_service_cycle(
                make_args(
                    ledger_path=str(ledger_path),
                    agent_margin_usdt=7.5,
                    paper_leverage=3.0,
                    agent_trade_thesis_path=str(thesis_path),
                ),
                state_path=Path(tmp) / "service_state.json",
                client=FakeClient(),
                source=FakeSource(event),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            risk = report["pipeline_report"]["risk_decision"]
            self.assertEqual(risk["decision"], "ALLOW")
            self.assertEqual(risk["policy"]["daily_realized_pnl_usdt"], -22.5)
            self.assertEqual(risk["policy"]["consecutive_losses"], 3)
            self.assertNotIn("daily_loss_limit_reached", risk["reasons"])
            self.assertNotIn("consecutive_loss_limit_reached", risk["reasons"])
            self.assertEqual(risk["policy"]["max_daily_loss_usdt"], 0.0)
            self.assertEqual(risk["policy"]["max_consecutive_losses"], 0)

    def test_run_service_cycle_fails_closed_when_existing_ledger_is_unreadable(self) -> None:
        event = {
            "event_id": "evt-corrupt-ledger",
            "source_time_bj": "2026-05-13 19:57:42",
            "content": "IRYS 异动",
        }
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "paper_ledger.json"
            ledger_path.write_text("{}", encoding="utf-8")

            report = run_service_cycle(
                make_args(ledger_path=str(ledger_path)),
                state_path=Path(tmp) / "service_state.json",
                client=FakeClient(),
                source=FakeSource(event),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            risk = report["pipeline_report"]["risk_decision"]
            self.assertEqual(risk["decision"], "REJECT")
            self.assertIn("paper_ledger_load_failed", risk["reasons"])
            self.assertFalse(report["paper_ledger"]["ok"])
            self.assertIn("paper_ledger_load_failed", report["paper_ledger"]["error"])

    def test_run_service_cycle_appends_jsonl_archive(self) -> None:
        event = {
            "event_id": "evt-archive",
            "source_time_bj": "2026-05-13 19:57:42",
            "content": "IRYS 异动",
        }
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "cycles.jsonl"
            report = run_service_cycle(
                make_args(archive_path=str(archive_path)),
                state_path=Path(tmp) / "service_state.json",
                client=FakeClient(),
                source=FakeSource(event),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            self.assertEqual(report["action"], "PROCESSED")
            rows = [json.loads(line) for line in archive_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["schema"], "tradecat_auto.service_cycle.v1")
            self.assertEqual(rows[0]["pipeline_report"]["selected_symbol"], "IRYSUSDT")

    def test_run_service_cycle_writes_sqlite_audit_journal_when_configured(self) -> None:
        event = {
            "event_id": "evt-journal",
            "source_time_bj": "2026-05-13 19:57:42",
            "content": "IRYS 异动",
        }
        with tempfile.TemporaryDirectory() as tmp:
            journal_path = Path(tmp) / "paper_audit.sqlite3"
            report = run_service_cycle(
                make_args(journal_path=str(journal_path), interval_seconds=60.0, base_url="https://fapi.binance.com"),
                state_path=Path(tmp) / "service_state.json",
                client=FakeClient(),
                source=FakeSource(event),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            self.assertEqual(report["action"], "PROCESSED")
            self.assertIn("audit_journal", report)
            self.assertTrue(report["audit_journal"]["ok"])
            self.assertEqual(report["audit_journal"]["run_id"], report["latest_event"]["event_id"])
            self.assertEqual(report["latest_event"]["source_dataset_key"], "anomaly_panel")
            summary = journal_summary(journal_path)
            self.assertEqual(summary["record_count"], 3)
            self.assertEqual(summary["event_type_counts"]["run_config_snapshot"], 1)
            self.assertEqual(summary["event_type_counts"]["service_cycle"], 1)
            self.assertEqual(summary["event_type_counts"]["risk_decision"], 1)

    def test_thesis_driven_cycle_is_visible_in_ledger_archive_journal_and_reports(self) -> None:
        event = {
            "event_id": "evt-audit-chain",
            "source_time_bj": "2026-05-13 19:57:42",
            "content": "IRYS 异动",
        }
        research_cycle_run_id = "research-cycle-audit-chain"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "service_state.json"
            ledger_path = root / "paper_ledger.json"
            archive_path = root / "cycles.jsonl"
            journal_path = root / "paper_audit.sqlite3"
            thesis_path = write_exit_plan_thesis(root, research_cycle_run_id=research_cycle_run_id)

            report = run_service_cycle(
                make_args(
                    ledger_path=str(ledger_path),
                    archive_path=str(archive_path),
                    journal_path=str(journal_path),
                    agent_margin_usdt=7.5,
                    paper_leverage=2.0,
                    agent_trade_thesis_path=str(thesis_path),
                    interval_seconds=60.0,
                    base_url="https://fapi.binance.com",
                ),
                state_path=state_path,
                client=FakeClient(),
                source=FakeSource(event),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            self.assertTrue(report["ok"])
            self.assertEqual(report["pipeline_report"]["research_cycle_run_id"], research_cycle_run_id)
            self.assertEqual(
                report["pipeline_report"]["paper_execution"]["research_cycle_run_id"], research_cycle_run_id
            )
            self.assertEqual(report["paper_ledger"]["open_positions_count"], 1)
            self.assertEqual(
                report["paper_ledger"]["recent_paper_orders"][-1]["research_cycle_run_id"], research_cycle_run_id
            )
            self.assertEqual(report["paper_ledger"]["recent_fills"][-1]["research_cycle_run_id"], research_cycle_run_id)
            self.assertFalse(report["safety"]["real_orders"])
            self.assertFalse(report["safety"]["signed_requests"])
            self.assertFalse(report["safety"]["reads_api_keys"])

            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            position = ledger["open_positions"]["IRYSUSDT"]
            self.assertEqual(position["research_cycle_run_id"], research_cycle_run_id)
            self.assertEqual(ledger["paper_orders"][-1]["research_cycle_run_id"], research_cycle_run_id)
            self.assertEqual(ledger["fills"][-1]["research_cycle_run_id"], research_cycle_run_id)

            archived = [json.loads(line) for line in archive_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(archived[0]["pipeline_report"]["research_cycle_run_id"], research_cycle_run_id)
            self.assertEqual(
                archived[0]["paper_ledger"]["recent_fills"][-1]["research_cycle_run_id"], research_cycle_run_id
            )

            journal = journal_summary(journal_path)
            self.assertTrue(journal["ok"])
            self.assertTrue(journal["chain_valid"])
            self.assertEqual(journal["event_type_counts"]["paper_order"], 1)
            self.assertEqual(journal["event_type_counts"]["paper_fill"], 1)

            health = build_health_report(
                state_path=state_path,
                ledger_path=ledger_path,
                archive_path=archive_path,
                journal_path=journal_path,
                now_iso="2026-05-13T12:00:30Z",
                max_heartbeat_age_seconds=180.0,
            )
            self.assertTrue(health["ok"])
            self.assertEqual(health["ledger"]["summary"]["open_positions_count"], 1)
            self.assertEqual(health["archive"]["cycle_count"], 1)
            self.assertEqual(health["audit_journal"]["event_type_counts"]["paper_fill"], 1)
            self.assertFalse(health["safety"]["real_orders"])

            daily = build_daily_report(ledger_path=ledger_path, archive_path=archive_path, date="2026-05-13")
            self.assertTrue(daily["ok"])
            self.assertEqual(daily["cycle_counts"]["PROCESSED"], 1)
            self.assertEqual(daily["fills"][-1]["research_cycle_run_id"], research_cycle_run_id)
            self.assertFalse(daily["safety"]["real_orders"])

    def test_duplicate_event_still_marks_existing_paper_positions(self) -> None:
        event = {
            "event_id": "evt-dup-with-position",
            "source_time_bj": "2026-05-13 19:57:42",
            "content": "IRYS 异动",
        }
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "service_state.json"
            ledger_path = Path(tmp) / "paper_ledger.json"
            ledger = default_paper_ledger(initial_balance_usdt=1000.0)
            ledger["open_positions"]["IRYSUSDT"] = {
                "position_id": "pos-1",
                "symbol": "IRYSUSDT",
                "side": "LONG",
                "entry_price": 0.05,
                "quantity": 100.0,
                "notional_usdt": 5.0,
                "stop_loss_price": 0.049,
                "take_profit_price": 0.061,
                "opened_at": "2026-05-13T11:50:00Z",
                "status": "OPEN",
            }
            save_paper_ledger(ledger_path, ledger)
            client = FakeClient()
            source = FakeSource(event)
            now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)

            first = run_service_cycle(
                make_args(ledger_path=str(ledger_path)), state_path=state_path, client=client, source=source, now=now
            )
            second = run_service_cycle(
                make_args(ledger_path=str(ledger_path)), state_path=state_path, client=client, source=source, now=now
            )

            self.assertEqual(first["action"], "PROCESSED")
            self.assertEqual(second["action"], "SKIPPED_DUPLICATE_EVENT")
            self.assertEqual(second["paper_ledger"]["closed_positions_count"], 1)
            self.assertGreaterEqual(client.bundle_calls, 1)

    def test_duplicate_event_does_not_open_second_paper_position(self) -> None:
        event = {
            "event_id": "evt-dup-open",
            "source_time_bj": "2026-05-13 19:57:42",
            "content": "IRYS 异动",
        }
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "service_state.json"
            ledger_path = Path(tmp) / "paper_ledger.json"
            thesis_path = write_exit_plan_thesis(tmp)
            args = make_args(
                ledger_path=str(ledger_path),
                agent_margin_usdt=7.5,
                paper_leverage=2.0,
                agent_trade_thesis_path=str(thesis_path),
            )
            client = FakeClient()
            source = FakeSource(event)
            now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)

            first = run_service_cycle(args, state_path=state_path, client=client, source=source, now=now)
            second = run_service_cycle(args, state_path=state_path, client=client, source=source, now=now)

            self.assertEqual(first["action"], "PROCESSED")
            self.assertEqual(first["pipeline_report"]["paper_execution"]["status"], "OPENED")
            self.assertEqual(second["action"], "SKIPPED_DUPLICATE_EVENT")
            self.assertEqual(client.universe_calls, 2)
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(len(ledger["open_positions"]), 1)
            self.assertEqual(len(ledger["fills"]), 1)
            self.assertEqual(len(ledger["paper_orders"]), 1)
            self.assertIn(first["latest_event"]["event_id"], state_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
