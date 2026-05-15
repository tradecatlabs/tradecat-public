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
from tradecat_auto.binance_market import BinanceApiError
from tradecat_auto.cli import exit_code_for_payload, paper_report, run_loop_public, run_once_public
from tradecat_auto.paper_ledger import default_paper_ledger, save_paper_ledger


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

    def test_run_once_public_returns_paper_pipeline_report_without_real_orders(self) -> None:
        args = argparse.Namespace(symbol="auto", event_limit=5, anomaly_limit=20, mode="paper", notional_usdt=12.0)

        report = run_once_public(args, client=FakeClient(), source=FakeSource())

        self.assertEqual(report["schema"], "tradecat_auto.run_once_report.v1")
        self.assertEqual(report["selected_symbol"], "IRYSUSDT")
        self.assertEqual(report["paper_execution"]["schema"], "tradecat_auto.paper_execution_report.v1")
        self.assertIn("no real order was placed", report["limitations"])

    def test_run_loop_public_once_returns_service_cycle_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(
                symbol="auto",
                event_limit=5,
                anomaly_limit=20,
                mode="paper",
                notional_usdt=12.0,
                state_path=str(Path(tmp) / "service_state.json"),
                interval_seconds=60.0,
                max_cycles=1,
                once=True,
                max_event_age_seconds=None,
            )

            report = run_loop_public(args, client=FakeClient(), source=FakeSource())

            self.assertEqual(report["schema"], "tradecat_auto.service_cycle.v1")
            self.assertEqual(report["action"], "PROCESSED")
            self.assertEqual(report["pipeline_report"]["selected_symbol"], "IRYSUSDT")

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
                notional_usdt=12.0,
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
                notional_usdt=12.0,
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
                notional_usdt=12.0,
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

    def test_paper_report_returns_ledger_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "paper_ledger.json"
            ledger = default_paper_ledger(initial_balance_usdt=1000.0)
            ledger["open_positions"]["IRYSUSDT"] = {"symbol": "IRYSUSDT", "side": "LONG", "entry_price": 1.0, "quantity": 2.0, "last_mark_price": 1.1}
            save_paper_ledger(ledger_path, ledger)

            report = paper_report(argparse.Namespace(ledger_path=str(ledger_path), initial_balance_usdt=1000.0))

            self.assertEqual(report["schema"], "tradecat_auto.paper_report.v1")
            self.assertEqual(report["summary"]["open_positions_count"], 1)
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
            self.assertEqual(report["error_code"], "paper_ledger_load_failed")
            self.assertIn("paper_ledger_load_failed", report["error"])


if __name__ == "__main__":
    unittest.main()
