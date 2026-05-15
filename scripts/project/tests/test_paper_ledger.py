from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tradecat_auto.paper_ledger import (
    apply_paper_execution,
    default_paper_ledger,
    load_paper_ledger,
    mark_to_market,
    save_paper_ledger,
)

OPEN_LONG = {
    "schema": "tradecat_auto.paper_execution_report.v1",
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
}


class PaperLedgerTests(unittest.TestCase):
    def test_apply_open_execution_records_position_fill_fee_and_equity(self) -> None:
        ledger = default_paper_ledger(initial_balance_usdt=1000.0)

        updated = apply_paper_execution(ledger, OPEN_LONG, fee_bps=4.0, slippage_bps=5.0, now_iso="2026-05-14T00:00:00Z")

        self.assertEqual(updated["schema"], "tradecat_auto.paper_ledger.v1")
        self.assertIn("IRYSUSDT", updated["open_positions"])
        self.assertEqual(len(updated["fills"]), 1)
        self.assertAlmostEqual(updated["fills"][0]["price"], 100.05)
        self.assertAlmostEqual(updated["fills"][0]["fee_usdt"], 0.008004)
        self.assertAlmostEqual(updated["cash_balance_usdt"], 999.991996)
        self.assertAlmostEqual(updated["equity_usdt"], 999.991996)

    def test_apply_open_execution_is_idempotent_by_execution_id(self) -> None:
        ledger = default_paper_ledger(initial_balance_usdt=1000.0)

        once = apply_paper_execution(ledger, OPEN_LONG, now_iso="2026-05-14T00:00:00Z")
        twice = apply_paper_execution(once, OPEN_LONG, now_iso="2026-05-14T00:00:01Z")

        self.assertEqual(len(twice["fills"]), 1)
        self.assertEqual(len(twice["open_positions"]), 1)
        self.assertEqual(twice["ignored_execution_ids"], ["exec-1"])

    def test_mark_to_market_closes_take_profit_and_updates_realized_pnl(self) -> None:
        ledger = apply_paper_execution(
            default_paper_ledger(initial_balance_usdt=1000.0),
            OPEN_LONG,
            fee_bps=4.0,
            slippage_bps=0.0,
            now_iso="2026-05-14T00:00:00Z",
        )

        updated = mark_to_market(ledger, {"IRYSUSDT": 107.0}, fee_bps=4.0, now_iso="2026-05-14T00:05:00Z")

        self.assertNotIn("IRYSUSDT", updated["open_positions"])
        self.assertEqual(updated["closed_positions"][0]["close_reason"], "take_profit")
        self.assertAlmostEqual(updated["closed_positions"][0]["entry_fee_usdt"], 0.008)
        self.assertAlmostEqual(updated["closed_positions"][0]["exit_fee_usdt"], 0.00856)
        self.assertAlmostEqual(updated["closed_positions"][0]["net_pnl_usdt"], 1.38344)
        self.assertAlmostEqual(updated["realized_pnl_usdt"], 1.38344)
        self.assertEqual(len(updated["fills"]), 2)
        self.assertAlmostEqual(updated["cash_balance_usdt"], 1001.38344)
        self.assertAlmostEqual(updated["equity_usdt"], 1001.38344)

    def test_load_and_save_round_trip_ledger(self) -> None:
        ledger = apply_paper_execution(default_paper_ledger(), OPEN_LONG, now_iso="2026-05-14T00:00:00Z")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper_ledger.json"

            save_paper_ledger(path, ledger)
            loaded = load_paper_ledger(path)

            self.assertEqual(loaded["schema"], "tradecat_auto.paper_ledger.v1")
            self.assertIn("IRYSUSDT", loaded["open_positions"])

    def test_load_existing_corrupt_ledger_raises_without_resetting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper_ledger.json"
            path.write_text("{not json", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "paper_ledger_load_failed"):
                load_paper_ledger(path)

    def test_load_existing_wrong_schema_ledger_raises_without_resetting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper_ledger.json"
            path.write_text(json.dumps({"schema": "not_tradecat_auto.paper_ledger.v1"}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "paper_ledger_load_failed"):
                load_paper_ledger(path)

    def test_apply_open_execution_rejects_second_open_for_same_symbol(self) -> None:
        ledger = apply_paper_execution(
            default_paper_ledger(initial_balance_usdt=1000.0),
            OPEN_LONG,
            now_iso="2026-05-14T00:00:00Z",
        )
        second = copy.deepcopy(OPEN_LONG)
        second["paper_execution_id"] = "exec-2"
        second["entry_price"] = 120.0

        updated = apply_paper_execution(ledger, second, now_iso="2026-05-14T00:00:01Z")

        self.assertEqual(len(updated["fills"]), 1)
        self.assertEqual(len(updated["open_positions"]), 1)
        self.assertEqual(updated["open_positions"]["IRYSUSDT"]["execution_id"], "exec-1")
        self.assertEqual(updated["last_rejected_execution"]["reason"], "position_already_open_for_symbol")
        self.assertIn("exec-2", updated["ignored_execution_ids"])


if __name__ == "__main__":
    unittest.main()
