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
    paper_account_state,
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
        self.assertEqual(len(updated["paper_orders"]), 1)
        self.assertEqual(updated["paper_orders"][0]["schema"], "tradecat_auto.paper_order.v1")
        self.assertFalse(updated["paper_orders"][0]["real_order"])
        self.assertIsNone(updated["paper_orders"][0]["exchange_order_id"])
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

    def test_mark_to_market_does_not_apply_legacy_fixed_exits_when_plan_missing(self) -> None:
        execution = {
            **OPEN_LONG,
            "paper_execution_id": "exec-no-exit-plan",
            "stop_loss_price": None,
            "take_profit_price": None,
            "max_holding_minutes": None,
            "opened_at": "2026-05-14T00:00:00Z",
        }
        ledger = apply_paper_execution(
            default_paper_ledger(initial_balance_usdt=1000.0),
            execution,
            fee_bps=0.0,
            now_iso="2026-05-14T00:00:00Z",
        )

        updated = mark_to_market(
            ledger,
            {"IRYSUSDT": 80.0},
            fee_bps=0.0,
            now_iso="2026-05-14T12:00:00Z",
            max_holding_minutes=30,
        )

        self.assertIn("IRYSUSDT", updated["open_positions"])
        self.assertEqual(updated["closed_positions"], [])
        self.assertLess(updated["open_positions"]["IRYSUSDT"]["unrealized_pnl_usdt"], 0)
        self.assertEqual(updated["open_positions"]["IRYSUSDT"]["exit_management"], "agent_managed")
        self.assertEqual(updated["open_positions"]["IRYSUSDT"]["exit_plan_source"], "agent_required_missing")

    def test_mark_to_market_handles_multi_symbol_stop_loss_and_agent_time_stop(self) -> None:
        ledger = apply_paper_execution(
            default_paper_ledger(initial_balance_usdt=1000.0),
            {**OPEN_LONG, "opened_at": "2026-05-14T00:00:00Z", "max_holding_minutes": 30},
            fee_bps=0.0,
            now_iso="2026-05-14T00:00:00Z",
        )
        short_execution = {
            **OPEN_LONG,
            "paper_execution_id": "exec-short",
            "symbol": "BTCUSDT",
            "side": "SHORT",
            "entry_price": 50.0,
            "quantity": 0.4,
            "notional_usdt": 20.0,
            "stop_loss_price": 52.0,
            "take_profit_price": 47.0,
            "opened_at": "2026-05-14T00:20:00Z",
        }
        ledger = apply_paper_execution(ledger, short_execution, fee_bps=0.0, now_iso="2026-05-14T00:20:00Z")

        updated = mark_to_market(
            ledger,
            {"IRYSUSDT": 101.0, "BTCUSDT": 53.0},
            fee_bps=0.0,
            now_iso="2026-05-14T00:45:00Z",
            max_holding_minutes=0,
        )

        self.assertEqual(updated["open_positions"], {})
        reasons_by_symbol = {position["symbol"]: position["close_reason"] for position in updated["closed_positions"]}
        self.assertEqual(reasons_by_symbol["IRYSUSDT"], "time_stop")
        self.assertEqual(reasons_by_symbol["BTCUSDT"], "stop_loss")
        self.assertEqual(len(updated["fills"]), 4)

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

    def test_paper_account_state_is_derived_from_local_ledger_only(self) -> None:
        ledger = apply_paper_execution(default_paper_ledger(), OPEN_LONG, now_iso="2026-05-14T00:00:00Z")

        state = paper_account_state(ledger)

        self.assertEqual(state["schema"], "tradecat_auto.paper_account_state.v1")
        self.assertEqual(state["source"], "local_tradecat_paper_ledger")
        self.assertFalse(state["hard_boundaries"]["real_orders"])
        self.assertFalse(state["hard_boundaries"]["signed_requests"])
        self.assertFalse(state["hard_boundaries"]["reads_api_keys"])
        self.assertFalse(state["hard_boundaries"]["binance_account_state"])
        self.assertEqual(state["recent_paper_orders"][0]["schema"], "tradecat_auto.paper_order.v1")
        self.assertFalse(state["recent_paper_orders"][0]["real_order"])
        self.assertIn("not Binance account", state["limitations"][1])


if __name__ == "__main__":
    unittest.main()
