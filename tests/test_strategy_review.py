from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from tradecat_auto.cli import strategy_review_report
from tradecat_auto.paper_ledger import default_paper_ledger, save_paper_ledger
from tradecat_auto.strategy_review import (
    build_strategy_review_report,
    load_strategy_state,
    save_strategy_state,
    strategy_state_policy,
)


def closed_position(symbol: str, side: str, execution_id: str, pnl: float) -> dict:
    return {
        "position_id": f"pos-{execution_id}",
        "execution_id": execution_id,
        "symbol": symbol,
        "side": side,
        "status": "CLOSED",
        "close_reason": "stop_loss" if pnl < 0 else "take_profit",
        "net_pnl_usdt": pnl,
        "gross_pnl_usdt": pnl,
        "entry_fee_usdt": 0.004,
        "exit_fee_usdt": 0.004,
        "closed_at": "2026-05-19T00:00:00Z",
    }


def cycle_for_execution(execution_id: str, signal_type: str) -> dict:
    return {
        "schema": "tradecat_auto.service_cycle.v1",
        "schema_version": "1.0.0",
        "action": "PROCESSED",
        "latest_event": {
            "event_id": f"event-{execution_id}",
            "source_dataset_key": "signal_flow",
            "symbol": "RAVEUSDT",
            "signal_type": signal_type,
            "source_values": {"类型": signal_type},
        },
        "pipeline_report": {
            "paper_execution": {
                "status": "OPENED",
                "paper_execution_id": execution_id,
            }
        },
    }


class StrategyReviewTests(unittest.TestCase):
    def test_strategy_review_blocks_losing_symbol_signal_type_and_side(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = default_paper_ledger()
            ledger["closed_positions"] = [
                *(closed_position("RAVEUSDT", "SHORT", f"bad-{index}", -0.2) for index in range(6)),
                *(closed_position("GOODUSDT", "LONG", f"good-{index}", 0.1) for index in range(3)),
            ]
            ledger_path = root / "paper_ledger.json"
            save_paper_ledger(ledger_path, ledger)
            archive_path = root / "cycles.jsonl"
            archive_path.write_text(
                "\n".join(json.dumps(cycle_for_execution(f"bad-{index}", "BAD_SIGNAL")) for index in range(6)) + "\n",
                encoding="utf-8",
            )

            report = build_strategy_review_report(
                ledger_path=ledger_path,
                archive_path=archive_path,
                min_closed_positions=3,
                min_symbol_trades=3,
                symbol_loss_usdt=0.5,
                symbol_win_rate_below=0.4,
                min_signal_type_trades=3,
                signal_type_loss_usdt=0.5,
                signal_type_win_rate_below=0.4,
                min_side_trades=3,
                side_loss_usdt=0.5,
                side_win_rate_below=0.4,
            )

            self.assertTrue(report["ok"])
            self.assertEqual(report["schema"], "tradecat_auto.strategy_review_report.v1")
            self.assertIn("RAVEUSDT", report["recommendations"]["blocked_symbols"])
            self.assertIn("BAD_SIGNAL", report["recommendations"]["blocked_signal_types"])
            self.assertIn("SHORT", report["recommendations"]["blocked_sides"])
            self.assertFalse(report["safety"]["real_orders"])
            state = report["strategy_state"]
            self.assertEqual(state["schema"], "tradecat_auto.strategy_state.v1")
            self.assertIn("RAVEUSDT", state["policy"]["blocked_symbols"])

    def test_strategy_state_roundtrip_and_policy_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "strategy_state.json"
            state = {
                "schema": "tradecat_auto.strategy_state.v1",
                "schema_version": "1.0.0",
                "ok": True,
                "enabled": True,
                "status": "active",
                "policy": {
                    "new_entries_enabled": True,
                    "max_open_positions": 10,
                    "max_positions_per_symbol": 2,
                    "blocked_symbols": ["RAVEUSDT"],
                    "blocked_signal_types": ["BAD_SIGNAL"],
                    "blocked_sides": ["SHORT"],
                },
                "provenance": {"source": "test"},
                "safety": {
                    "public_readonly_market_data": True,
                    "paper_or_watch_only": True,
                    "real_orders": False,
                    "signed_requests": False,
                    "reads_api_keys": False,
                    "binance_account_state": False,
                },
            }
            save_strategy_state(path, state)
            loaded = load_strategy_state(path)
            policy = strategy_state_policy(
                loaded,
                selected_symbol="RAVEUSDT",
                latest_event={"signal_type": "BAD_SIGNAL"},
            )

            self.assertEqual(policy["max_open_positions"], 10)
            self.assertEqual(policy["max_positions_per_symbol"], 2)
            self.assertIn("RAVEUSDT", policy["blocked_symbols"])
            self.assertIn("BAD_SIGNAL", policy["blocked_signal_types"])
            self.assertIn("SHORT", policy["blocked_sides"])
            self.assertFalse(policy["strategy_state"]["policy"]["blocked_symbols_count"] == 0)

    def test_strategy_review_cli_writes_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = root / "paper_ledger.json"
            save_paper_ledger(ledger_path, default_paper_ledger())
            state_path = root / "strategy_state.json"

            report = strategy_review_report(
                argparse.Namespace(
                    ledger_path=str(ledger_path),
                    archive_path=str(root / "missing.jsonl"),
                    output_state_path=str(state_path),
                    min_closed_positions=50,
                    min_symbol_trades=5,
                    symbol_loss_usdt=0.75,
                    symbol_win_rate_below=0.35,
                    min_signal_type_trades=20,
                    signal_type_loss_usdt=2.0,
                    signal_type_win_rate_below=0.38,
                    min_side_trades=100,
                    side_loss_usdt=10.0,
                    side_win_rate_below=0.38,
                    max_open_positions=50,
                    max_positions_per_symbol=3,
                )
            )

            self.assertTrue(report["ok"])
            self.assertEqual(report["review_status"], "insufficient_closed_positions")
            self.assertTrue(state_path.exists())
            self.assertEqual(load_strategy_state(state_path)["schema"], "tradecat_auto.strategy_state.v1")


if __name__ == "__main__":
    unittest.main()
