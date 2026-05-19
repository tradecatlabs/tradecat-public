from __future__ import annotations

import contextlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tradecat_auto import cli as cli_module
from tradecat_auto.paper_ledger import default_paper_ledger, save_paper_ledger
from tradecat_auto.safety_boundary import paper_watch_report_flags, paper_watch_safety_boundary


def assert_public_readonly_payload(testcase: unittest.TestCase, payload: dict[str, object]) -> None:
    for key, expected in paper_watch_report_flags().items():
        testcase.assertIs(payload[key], expected)
    testcase.assertEqual(payload["safety"], paper_watch_safety_boundary())


class CliRuntimeTests(unittest.TestCase):
    def test_print_ignores_broken_pipe_from_truncated_cli_consumers(self) -> None:
        class BrokenPipeWriter:
            def write(self, value: str) -> int:
                raise BrokenPipeError

            def flush(self) -> None:
                return None

        with contextlib.redirect_stdout(BrokenPipeWriter()):
            cli_module._print({"schema": "tradecat_auto.test.v1", "ok": True}, as_json=True)

    def test_append_jsonl_serializes_concurrent_runtime_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "run-context-cycles.jsonl"
            barrier = threading.Barrier(8)
            errors: list[BaseException] = []

            def worker(index: int) -> None:
                try:
                    barrier.wait()
                    cli_module._append_jsonl(
                        archive_path,
                        {
                            "schema": "tradecat_auto.service_cycle.v1",
                            "schema_version": "1.0.0",
                            "index": index,
                        },
                    )
                except BaseException as exc:  # pragma: no cover - surfaced by assertion below
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(index,)) for index in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=2.0)

            self.assertEqual(errors, [])
            rows = [json.loads(line) for line in archive_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual({row["index"] for row in rows}, set(range(8)))
            self.assertTrue(Path(tmp, "run-context-cycles.jsonl.lock").exists())

    def test_paper_report_bounds_verbose_ledger_details_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "paper_ledger.json"
            ledger = default_paper_ledger(initial_balance_usdt=1000.0)
            ledger["open_positions"] = {
                f"S{index}USDT": {"symbol": f"S{index}USDT", "position_id": f"pos-{index}"} for index in range(4)
            }
            ledger["closed_positions"] = [{"position_id": f"closed-{index}"} for index in range(4)]
            ledger["paper_orders"] = [{"order_id": f"order-{index}"} for index in range(4)]
            ledger["fills"] = [{"fill_id": f"fill-{index}"} for index in range(4)]
            ledger["equity_curve"] = [{"time": f"t-{index}", "equity_usdt": 1000.0 - index} for index in range(4)]
            save_paper_ledger(ledger_path, ledger)

            bounded = cli_module.paper_report(
                SimpleNamespace(ledger_path=str(ledger_path), initial_balance_usdt=1000.0, detail_limit=2)
            )
            full = cli_module.paper_report(
                SimpleNamespace(ledger_path=str(ledger_path), initial_balance_usdt=1000.0, detail_limit=0)
            )

            self.assertEqual(bounded["detail_limit"], 2)
            self.assertTrue(bounded["detail_truncated"]["open_positions"])
            self.assertEqual(list(bounded["open_positions"]), ["S2USDT", "S3USDT"])
            self.assertEqual([item["fill_id"] for item in bounded["recent_fills"]], ["fill-2", "fill-3"])
            self.assertEqual(len(bounded["paper_account_state"]["open_positions"]), 2)
            assert_public_readonly_payload(self, bounded)
            self.assertEqual(full["detail_limit"], 0)
            self.assertFalse(any(full["detail_truncated"].values()))
            self.assertEqual(len(full["open_positions"]), 4)
            assert_public_readonly_payload(self, full)

    def test_paper_report_load_failure_keeps_public_readonly_safety(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = cli_module.paper_report(
                SimpleNamespace(ledger_path=tmp, initial_balance_usdt=1000.0, detail_limit=20)
            )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_code"], "paper_ledger_load_failed")
        assert_public_readonly_payload(self, payload)

    def test_run_context_config_snapshot_keeps_public_readonly_safety(self) -> None:
        payload = cli_module._run_context_config_snapshot(
            SimpleNamespace(
                input="agent_market_context.json",
                mode="paper",
                ledger_path=".runtime/auto-paper/paper_ledger.json",
                archive_path=".runtime/auto-paper/cycles.jsonl",
                journal_path=".runtime/auto-paper/audit.sqlite3",
                paper_fee_bps=4.0,
                paper_slippage_bps=0.0,
            )
        )

        self.assertEqual(payload["schema"], "tradecat_auto.run_context_config_snapshot.v1")
        self.assertEqual(payload["command"], "run-context")
        assert_public_readonly_payload(self, payload)

    def test_agent_trade_thesis_load_failure_keeps_public_readonly_safety(self) -> None:
        run_once = cli_module._agent_trade_thesis_load_failed_payload(
            SimpleNamespace(command="run-once", mode="paper", agent_trade_thesis_path="bad-thesis.json"),
            "tradecat_auto.cli.run_once_public",
            ValueError("agent_trade_thesis_load_failed"),
        )
        run_loop = cli_module._agent_trade_thesis_load_failed_payload(
            SimpleNamespace(command="run-loop", mode="paper", agent_trade_thesis_path="bad-thesis.json"),
            "tradecat_auto.cli.run_loop_public",
            ValueError("agent_trade_thesis_load_failed"),
        )

        self.assertEqual(run_once["schema"], "tradecat_auto.run_once_report.v1")
        self.assertEqual(run_once["error_code"], "agent_trade_thesis_load_failed")
        self.assertEqual(run_loop["schema"], "tradecat_auto.service_cycle.v1")
        self.assertEqual(run_loop["action"], "ERROR")
        self.assertEqual(run_loop["reason"], "agent_trade_thesis_load_failed")
        assert_public_readonly_payload(self, run_once)
        assert_public_readonly_payload(self, run_loop)

    def test_paper_autonomy_profile_load_failure_keeps_public_readonly_safety(self) -> None:
        run_once = cli_module._paper_autonomy_profile_load_failed_payload(
            SimpleNamespace(command="run-once", mode="paper", paper_autonomy_profile_path="bad-profile.json"),
            "tradecat_auto.cli.run_once_public",
            ValueError("paper_autonomy_profile_load_failed"),
        )
        run_loop = cli_module._paper_autonomy_profile_load_failed_payload(
            SimpleNamespace(command="run-loop", mode="paper", paper_autonomy_profile_path="bad-profile.json"),
            "tradecat_auto.cli.run_loop_public",
            ValueError("paper_autonomy_profile_load_failed"),
        )

        self.assertEqual(run_once["schema"], "tradecat_auto.run_once_report.v1")
        self.assertEqual(run_once["error_code"], "paper_autonomy_profile_load_failed")
        self.assertEqual(run_loop["schema"], "tradecat_auto.service_cycle.v1")
        self.assertEqual(run_loop["action"], "ERROR")
        self.assertEqual(run_loop["reason"], "paper_autonomy_profile_load_failed")
        assert_public_readonly_payload(self, run_once)
        assert_public_readonly_payload(self, run_loop)

    def test_run_once_no_symbol_selected_keeps_public_readonly_safety(self) -> None:
        class NoSymbolClient:
            def market_universe(self) -> dict[str, object]:
                return {"ok": True, "symbols": [], "rate_limits": []}

        class EmptySource:
            def fetch_anomaly_symbols(self, *, tradable_symbols: set[str], limit: int) -> dict[str, object]:
                return {"ok": True, "symbols": [], "rows": [], "rejected": [], "sections": []}

            def fetch_signal_flow_events(self, *, tradable_symbols: set[str], limit: int) -> dict[str, object]:
                return {"ok": True, "events": [], "rejected": [], "duplicates": [], "duplicate_count": 0}

        payload = cli_module.run_once_public(
            SimpleNamespace(
                base_url="https://example.test",
                tradecat_public="unused-public-source",
                anomaly_limit=0,
                event_limit=0,
                symbol="auto",
                mode="paper",
                agent_trade_thesis_path="",
                paper_autonomy_profile_path="",
            ),
            client=NoSymbolClient(),
            source=EmptySource(),
        )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_code"], "no_symbol_selected")
        self.assertEqual(payload["selected_symbol"], "")
        assert_public_readonly_payload(self, payload)

    def test_probe_no_symbol_selected_keeps_public_readonly_safety(self) -> None:
        class NoSymbolClient:
            def __init__(self, *, base_url: str):
                self.base_url = base_url

            def market_universe(self) -> dict[str, object]:
                return {"ok": True, "symbols": [], "rate_limits": []}

        class EmptySource:
            def __init__(self, path: Path):
                self.path = path

            def fetch_anomaly_symbols(self, *, tradable_symbols: set[str], limit: int) -> dict[str, object]:
                return {"ok": True, "symbols": [], "rows": [], "rejected": [], "sections": []}

            def fetch_signal_flow_events(self, *, tradable_symbols: set[str], limit: int) -> dict[str, object]:
                return {"ok": True, "events": [], "rejected": [], "duplicates": [], "duplicate_count": 0}

        with (
            patch("tradecat_auto.cli.BinanceMarketClient", NoSymbolClient),
            patch("tradecat_auto.cli.TradeCatPublicSource", EmptySource),
        ):
            payload = cli_module.probe_public(
                SimpleNamespace(
                    base_url="https://example.test",
                    tradecat_public="unused-public-source",
                    anomaly_limit=0,
                    event_limit=0,
                    symbol="auto",
                )
            )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_code"], "public_probe_failed")
        self.assertEqual(payload["selected_symbol"], "")
        assert_public_readonly_payload(self, payload)


if __name__ == "__main__":
    unittest.main()
