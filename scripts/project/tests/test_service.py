from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from tradecat_auto.audit_journal import journal_summary
from tradecat_auto.paper_ledger import default_paper_ledger, save_paper_ledger
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
        return {
            "ok": True,
            "symbols": [
                {"raw_symbol": "IRYS", "normalized_symbol": "IRYSUSDT", "source_values": {"交易对": "IRYS"}}
            ],
            "rejected": [],
        }


def make_args(**overrides):
    values = {
        "symbol": "auto",
        "mode": "paper",
        "notional_usdt": 12.0,
        "event_limit": 5,
        "anomaly_limit": 20,
        "max_event_age_seconds": 3600,
        "ledger_path": "",
        "initial_balance_usdt": 1000.0,
        "paper_fee_bps": 4.0,
        "paper_slippage_bps": 5.0,
        "archive_path": "",
        "journal_path": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


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
            self.assertFalse(report["safety"]["binance_account_state"])
            self.assertEqual(report["action"], "PROCESSED")
            self.assertEqual(report["pipeline_report"]["selected_symbol"], "IRYSUSDT")
            self.assertTrue(state_path.exists())
            self.assertIn("evt-1", state_path.read_text(encoding="utf-8"))

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
            self.assertEqual(client.bundle_calls, 1)
            self.assertEqual(client.universe_calls, 1)

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
            self.assertEqual(client.universe_calls, 0)

    def test_run_service_cycle_archives_no_event_poll_without_market_calls(self) -> None:
        class EmptySource:
            def fetch_events(self, *, limit):
                return {"ok": True, "events": []}

            def fetch_anomaly_symbols(self, *, tradable_symbols, limit):  # pragma: no cover - should not be called
                raise AssertionError("no-event cycles must not call anomaly symbols")

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
            self.assertEqual(report["reason"], "no_events_available")
            self.assertEqual(client.bundle_calls, 0)
            self.assertEqual(client.universe_calls, 0)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["cycles_attempted"], 1)
            self.assertEqual(state["cycles_processed"], 0)
            self.assertEqual(state["last_error"], "no_events_available")
            rows = [json.loads(line) for line in archive_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["action"], "SKIPPED_NO_EVENT")
            self.assertEqual(rows[0]["reason"], "no_events_available")

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

            self.assertEqual(report["action"], "ERROR")
            self.assertFalse(report["ok"])
            self.assertEqual(report["reason"], "no_symbol_selected")
            self.assertEqual(client.bundle_calls, 0)
            self.assertIn("audit_journal", report)
            self.assertTrue(report["audit_journal"]["ok"])
            rows = [json.loads(line) for line in archive_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["action"], "ERROR")
            self.assertEqual(rows[0]["reason"], "no_symbol_selected")
            self.assertEqual(rows[0]["audit_journal"]["schema"], "tradecat_auto.audit_journal_write.v1")
            summary = journal_summary(journal_path)
            self.assertTrue(summary["ok"])
            self.assertEqual(summary["event_type_counts"]["service_cycle"], 1)

    def test_run_service_cycle_updates_paper_ledger_when_execution_opens(self) -> None:
        event = {
            "event_id": "evt-ledger",
            "source_time_bj": "2026-05-13 19:57:42",
            "content": "IRYS 异动",
        }
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "paper_ledger.json"
            report = run_service_cycle(
                make_args(ledger_path=str(ledger_path)),
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

    def test_run_service_cycle_risk_uses_existing_ledger_position_count(self) -> None:
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

            report = run_service_cycle(
                make_args(ledger_path=str(ledger_path)),
                state_path=Path(tmp) / "service_state.json",
                client=FakeClient(),
                source=FakeSource(event),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            risk = report["pipeline_report"]["risk_decision"]
            self.assertEqual(risk["decision"], "REJECT")
            self.assertIn("max_open_positions_reached", risk["reasons"])

    def test_run_service_cycle_risk_uses_existing_ledger_total_notional(self) -> None:
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

            report = run_service_cycle(
                make_args(ledger_path=str(ledger_path), notional_usdt=12.0),
                state_path=Path(tmp) / "service_state.json",
                client=FakeClient(),
                source=FakeSource(event),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            risk = report["pipeline_report"]["risk_decision"]
            self.assertEqual(risk["decision"], "REJECT")
            self.assertEqual(risk["policy"]["current_total_notional_usdt"], 45.0)
            self.assertIn("max_total_notional_reached", risk["reasons"])

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

            report = run_service_cycle(
                make_args(ledger_path=str(ledger_path), notional_usdt=12.0),
                state_path=Path(tmp) / "service_state.json",
                client=FakeClient(),
                source=FakeSource(event),
                now=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )

            risk = report["pipeline_report"]["risk_decision"]
            self.assertEqual(risk["decision"], "REJECT")
            self.assertEqual(risk["policy"]["daily_realized_pnl_usdt"], -22.5)
            self.assertEqual(risk["policy"]["consecutive_losses"], 3)
            self.assertIn("daily_loss_limit_reached", risk["reasons"])
            self.assertIn("consecutive_loss_limit_reached", risk["reasons"])

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
            self.assertEqual(report["audit_journal"]["run_id"], "evt-journal")
            summary = journal_summary(journal_path)
            self.assertEqual(summary["record_count"], 3)
            self.assertEqual(summary["event_type_counts"]["run_config_snapshot"], 1)
            self.assertEqual(summary["event_type_counts"]["service_cycle"], 1)
            self.assertEqual(summary["event_type_counts"]["risk_decision"], 1)

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

            first = run_service_cycle(make_args(ledger_path=str(ledger_path)), state_path=state_path, client=client, source=source, now=now)
            second = run_service_cycle(make_args(ledger_path=str(ledger_path)), state_path=state_path, client=client, source=source, now=now)

            self.assertEqual(first["action"], "PROCESSED")
            self.assertEqual(second["action"], "SKIPPED_DUPLICATE_EVENT")
            self.assertEqual(second["paper_ledger"]["closed_positions_count"], 1)
            self.assertGreaterEqual(client.bundle_calls, 2)


if __name__ == "__main__":
    unittest.main()
