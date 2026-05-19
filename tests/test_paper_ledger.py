from __future__ import annotations

import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from tradecat_auto.paper_ledger import (
    apply_paper_execution,
    apply_position_management_thesis,
    default_paper_ledger,
    load_paper_ledger,
    mark_to_market,
    paper_account_state,
    paper_ledger_lock,
    paper_ledger_summary,
    runtime_temp_path,
    save_paper_ledger,
    write_runtime_json_atomic,
)
from tradecat_auto.safety_boundary import paper_watch_hard_boundaries

PROJECT_ROOT = Path(__file__).resolve().parents[1]

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
    "requested_notional_usdt": 20.0,
    "requested_margin_usdt": 10.0,
    "leverage": 2.0,
    "sizing_source": "agent_supplied_test_fixture",
    "stop_loss_price": 97.0,
    "take_profit_price": 106.0,
}


POSITION_THESIS_BASE = {
    "schema": "tradecat_auto.position_management_thesis.v1",
    "schema_version": "1.0.0",
    "ok": True,
    "mode": "paper",
    "symbol": "IRYSUSDT",
    "reason": "Agent supplied explicit local paper position management.",
    "error_code": None,
    "provenance": {"source": "test_position_management", "research_cycle_run_id": "cycle-paper-1"},
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


class PaperLedgerTests(unittest.TestCase):
    def test_apply_open_execution_records_position_fill_fee_and_equity(self) -> None:
        ledger = default_paper_ledger(initial_balance_usdt=1000.0)

        updated = apply_paper_execution(
            ledger, OPEN_LONG, fee_bps=4.0, slippage_bps=5.0, now_iso="2026-05-14T00:00:00Z"
        )

        self.assertEqual(updated["schema"], "tradecat_auto.paper_ledger.v1")
        self.assertEqual(updated["schema_version"], "1.0.0")
        self.assertFalse(updated["safety"]["reads_api_keys"])
        self.assertEqual(updated["provenance"]["source"], "local_tradecat_paper_ledger")
        self.assertIn("IRYSUSDT", updated["open_positions"])
        self.assertEqual(len(updated["paper_orders"]), 1)
        self.assertEqual(updated["paper_orders"][0]["schema"], "tradecat_auto.paper_order.v1")
        self.assertFalse(updated["paper_orders"][0]["real_order"])
        self.assertIsNone(updated["paper_orders"][0]["exchange_order_id"])
        self.assertEqual(len(updated["fills"]), 1)
        self.assertEqual(updated["fills"][0]["schema"], "tradecat_auto.paper_fill.v1")
        self.assertEqual(updated["fills"][0]["schema_version"], "1.0.0")
        self.assertAlmostEqual(updated["fills"][0]["price"], 100.05)
        self.assertAlmostEqual(updated["fills"][0]["fee_usdt"], 0.008004)
        self.assertAlmostEqual(updated["cash_balance_usdt"], 999.991996)
        self.assertAlmostEqual(updated["equity_usdt"], 999.991996)

    def test_apply_open_execution_uses_per_execution_public_taker_cost_model(self) -> None:
        ledger = default_paper_ledger(initial_balance_usdt=1000.0)
        execution = {
            **OPEN_LONG,
            "entry_price": 101.0,
            "raw_entry_price": 100.0,
            "entry_price_includes_slippage": True,
            "paper_fee_bps": 4.0,
            "paper_fee_model": "binance_usdm_public_docs_vip0_taker_fallback",
            "liquidity_role": "taker",
            "execution_cost_model": {
                "schema": "tradecat_auto.paper_execution_cost_model.v1",
                "schema_version": "1.0.0",
                "ok": True,
                "fee_bps": 4.0,
                "estimated_fill_price": 101.0,
                "fill_price_includes_slippage": True,
                "price_source": "binance_usdm_public_order_book_depth",
            },
        }

        updated = apply_paper_execution(
            ledger, execution, fee_bps=2.0, slippage_bps=50.0, now_iso="2026-05-14T00:00:00Z"
        )

        position = updated["open_positions"]["IRYSUSDT"]
        self.assertAlmostEqual(position["entry_price"], 101.0)
        self.assertAlmostEqual(position["raw_entry_price"], 100.0)
        self.assertEqual(position["fee_bps"], 4.0)
        self.assertEqual(position["paper_fee_model"], "binance_usdm_public_docs_vip0_taker_fallback")
        self.assertEqual(position["liquidity_role"], "taker")
        self.assertEqual(position["execution_cost_model"]["price_source"], "binance_usdm_public_order_book_depth")
        self.assertAlmostEqual(updated["fills"][0]["fee_usdt"], 0.00808)

    def test_apply_open_execution_rejects_missing_agent_sizing(self) -> None:
        execution = copy.deepcopy(OPEN_LONG)
        execution.pop("leverage", None)
        execution.pop("requested_margin_usdt", None)
        execution.pop("requested_notional_usdt", None)

        updated = apply_paper_execution(
            default_paper_ledger(initial_balance_usdt=1000.0), execution, now_iso="2026-05-14T00:00:00Z"
        )

        self.assertEqual(updated["open_positions"], {})
        self.assertEqual(updated["last_rejected_execution"]["reason"], "agent_sizing_required")
        self.assertIn("exec-1", updated["ignored_execution_ids"])

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
            self.assertEqual(loaded["schema_version"], "1.0.0")
            self.assertFalse(loaded["safety"]["real_orders"])
            self.assertIn("IRYSUSDT", loaded["open_positions"])

    def test_save_paper_ledger_rejects_unsafe_runtime_payload(self) -> None:
        ledger = default_paper_ledger()
        ledger["fills"] = [{"fill_id": "bad", "real_order": True}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper_ledger.json"

            with self.assertRaisesRegex(ValueError, "paper_ledger_save_failed.*safety boundary violation"):
                save_paper_ledger(path, ledger)

            self.assertFalse(path.exists())

    def test_runtime_temp_path_is_unique_for_same_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper_ledger.json"

            generated = {runtime_temp_path(path).name for _ in range(32)}

            self.assertEqual(len(generated), 32)
            self.assertTrue(all(name.startswith("paper_ledger.json.") for name in generated))
            self.assertTrue(all(name.endswith(".tmp") for name in generated))

    def test_write_runtime_json_atomic_removes_temp_file_when_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "paper_ledger.json"
            target.mkdir()

            with self.assertRaises(OSError):
                write_runtime_json_atomic(target, {"schema": "test"})

            self.assertEqual(list(Path(tmp).glob("paper_ledger.json.*.tmp")), [])

    def test_apply_paper_execution_rejects_unsafe_execution_without_persisting_raw_payload(self) -> None:
        unsafe_execution = {
            **OPEN_LONG,
            "paper_execution_id": "unsafe-exec",
            "real_order": True,
            "api_key": "should-never-enter-ledger",
        }

        updated = apply_paper_execution(default_paper_ledger(), unsafe_execution, now_iso="2026-05-14T00:00:00Z")

        self.assertEqual(updated["open_positions"], {})
        self.assertEqual(updated["last_rejected_execution"]["reason"], "paper_execution_safety_violation")
        self.assertIn("unsafe-exec", updated["ignored_execution_ids"])
        self.assertNotIn("api_key", json.dumps(updated["last_rejected_execution"]))

    def test_paper_ledger_lock_uses_adjacent_runtime_lock_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper_ledger.json"

            with paper_ledger_lock(path):
                save_paper_ledger(path, default_paper_ledger())

            self.assertTrue(path.exists())
            self.assertTrue(Path(tmp, "paper_ledger.json.lock").exists())

    def test_paper_ledger_lock_serializes_concurrent_read_modify_write_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper_ledger.json"
            save_paper_ledger(path, default_paper_ledger())
            barrier = threading.Barrier(4)
            errors: list[BaseException] = []

            def worker(index: int) -> None:
                try:
                    barrier.wait()
                    with paper_ledger_lock(path):
                        ledger = load_paper_ledger(path)
                        ledger.setdefault("ignored_execution_ids", []).append(f"worker-{index}")
                        time.sleep(0.01)
                        save_paper_ledger(path, ledger)
                except BaseException as exc:  # pragma: no cover - surfaced by assertion below
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(index,)) for index in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=2.0)

            self.assertEqual(errors, [])
            loaded = load_paper_ledger(path)
            self.assertEqual(set(loaded["ignored_execution_ids"]), {f"worker-{index}" for index in range(4)})

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

    def test_load_existing_ledger_rejects_real_order_safety_flags(self) -> None:
        unsafe_ledgers = [
            {"paper_orders": [{"order_id": "bad", "real_order": True}]},
            {"fills": [{"fill_id": "bad", "signed_requests": "true"}]},
            {"open_positions": {"IRYSUSDT": {"symbol": "IRYSUSDT", "reads_api_keys": 1}}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for index, unsafe in enumerate(unsafe_ledgers):
                with self.subTest(unsafe=unsafe):
                    path = Path(tmp) / f"paper_ledger_{index}.json"
                    ledger = default_paper_ledger()
                    ledger.update(unsafe)
                    path.write_text(json.dumps(ledger), encoding="utf-8")

                    with self.assertRaisesRegex(ValueError, "paper_ledger_load_failed.*safety boundary violation"):
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

    def test_apply_open_execution_allows_same_symbol_multi_position_only_with_agent_authorization(self) -> None:
        ledger = apply_paper_execution(
            default_paper_ledger(initial_balance_usdt=1000.0),
            OPEN_LONG,
            fee_bps=0.0,
            now_iso="2026-05-14T00:00:00Z",
        )
        second = {
            **copy.deepcopy(OPEN_LONG),
            "paper_execution_id": "exec-2",
            "entry_price": 101.0,
            "allow_multiple_open_positions_per_symbol": True,
            "max_concurrent_positions_per_symbol": 2,
        }

        multi = apply_paper_execution(ledger, second, fee_bps=0.0, now_iso="2026-05-14T00:00:01Z")

        self.assertIn("IRYSUSDT", multi["open_positions"])
        self.assertEqual(len(multi["open_positions"]), 2)
        self.assertEqual([position["symbol"] for position in multi["open_positions"].values()].count("IRYSUSDT"), 2)
        self.assertEqual(paper_ledger_summary(multi)["open_positions_count"], 2)
        self.assertEqual(len(paper_account_state(multi)["open_positions"]), 2)

        third = {
            **copy.deepcopy(OPEN_LONG),
            "paper_execution_id": "exec-3",
            "entry_price": 102.0,
            "allow_multiple_open_positions_per_symbol": True,
            "max_concurrent_positions_per_symbol": 2,
        }
        rejected = apply_paper_execution(multi, third, fee_bps=0.0, now_iso="2026-05-14T00:00:02Z")
        self.assertEqual(len(rejected["open_positions"]), 2)
        self.assertEqual(rejected["last_rejected_execution"]["reason"], "max_concurrent_positions_per_symbol_reached")
        self.assertIn("exec-3", rejected["ignored_execution_ids"])

        closed = mark_to_market(rejected, {"IRYSUSDT": 107.0}, fee_bps=0.0, now_iso="2026-05-14T00:05:00Z")
        self.assertEqual(closed["open_positions"], {})
        self.assertEqual(len(closed["closed_positions"]), 2)
        self.assertEqual(len(closed["fills"]), 4)
        self.assertEqual({position["close_reason"] for position in closed["closed_positions"]}, {"take_profit"})
        self.assertEqual([position["symbol"] for position in closed["closed_positions"]].count("IRYSUSDT"), 2)

    def test_position_management_with_position_id_does_not_update_other_same_symbol_positions(self) -> None:
        first = {
            **copy.deepcopy(OPEN_LONG),
            "paper_execution_id": "exec-1",
            "allow_multiple_open_positions_per_symbol": True,
            "max_concurrent_positions_per_symbol": 2,
        }
        second = {
            **copy.deepcopy(OPEN_LONG),
            "paper_execution_id": "exec-2",
            "entry_price": 101.0,
            "allow_multiple_open_positions_per_symbol": True,
            "max_concurrent_positions_per_symbol": 2,
        }
        ledger = apply_paper_execution(default_paper_ledger(), first, fee_bps=0.0, now_iso="2026-05-14T00:00:00Z")
        ledger = apply_paper_execution(ledger, second, fee_bps=0.0, now_iso="2026-05-14T00:00:01Z")
        positions = list(ledger["open_positions"].values())
        target = positions[1]

        report = apply_position_management_thesis(
            ledger,
            {
                **copy.deepcopy(POSITION_THESIS_BASE),
                "action": "adjust_exit",
                "position_ref": {"position_id": target["position_id"], "symbol": target["symbol"]},
                "exit_update": {
                    "stop_loss_price": 98.0,
                    "take_profit_price": 109.0,
                    "max_holding_minutes": 30,
                    "agent_authorized": True,
                    "real_order": False,
                },
            },
            now_iso="2026-05-14T00:00:02Z",
        )

        updated = report["_ledger"]
        self.assertTrue(report["ok"])
        self.assertEqual(report["position_id"], target["position_id"])
        changed = [
            position
            for position in updated["open_positions"].values()
            if position.get("stop_loss_price") == 98.0 and position.get("take_profit_price") == 109.0
        ]
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]["position_id"], target["position_id"])

    def test_position_management_rejects_symbol_only_ref_when_same_symbol_positions_are_ambiguous(self) -> None:
        first = {
            **copy.deepcopy(OPEN_LONG),
            "paper_execution_id": "exec-1",
            "allow_multiple_open_positions_per_symbol": True,
            "max_concurrent_positions_per_symbol": 2,
        }
        second = {
            **copy.deepcopy(OPEN_LONG),
            "paper_execution_id": "exec-2",
            "entry_price": 101.0,
            "allow_multiple_open_positions_per_symbol": True,
            "max_concurrent_positions_per_symbol": 2,
        }
        ledger = apply_paper_execution(default_paper_ledger(), first, fee_bps=0.0, now_iso="2026-05-14T00:00:00Z")
        ledger = apply_paper_execution(ledger, second, fee_bps=0.0, now_iso="2026-05-14T00:00:01Z")

        report = apply_position_management_thesis(
            ledger,
            {
                **copy.deepcopy(POSITION_THESIS_BASE),
                "action": "close",
                "reason": "symbol-only close must not choose among multiple paper positions",
                "position_ref": {"symbol": "IRYSUSDT"},
                "close_intent": {"close_fraction": 1, "mark_price": 103.0},
            },
            now_iso="2026-05-14T00:00:02Z",
        )

        self.assertFalse(report["ok"])
        self.assertEqual(report["error_code"], "position_ref_ambiguous")
        self.assertFalse(report["ledger_mutated"])
        self.assertEqual(len(report["_ledger"]["open_positions"]), 2)

    def test_paper_account_state_is_derived_from_local_ledger_only(self) -> None:
        ledger = apply_paper_execution(default_paper_ledger(), OPEN_LONG, now_iso="2026-05-14T00:00:00Z")

        state = paper_account_state(ledger)

        self.assertEqual(state["schema"], "tradecat_auto.paper_account_state.v1")
        self.assertEqual(state["source"], "local_tradecat_paper_ledger")
        self.assertEqual(state["provenance"]["source"], "local_tradecat_paper_ledger")
        self.assertTrue(state["safety"]["public_readonly"])
        self.assertFalse(state["safety"]["real_orders"])
        self.assertFalse(state["safety"]["signed_requests"])
        self.assertFalse(state["safety"]["reads_api_keys"])
        self.assertFalse(state["safety"]["binance_account_state"])
        self.assertEqual(state["hard_boundaries"], paper_watch_hard_boundaries())
        self.assertEqual(state["recent_paper_orders"][0]["schema"], "tradecat_auto.paper_order.v1")
        self.assertFalse(state["recent_paper_orders"][0]["real_order"])
        self.assertIn("not Binance account", state["limitations"][1])
        schema = json.loads(
            (PROJECT_ROOT / "contracts" / "tradecat-auto-paper-account-state.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(state)), [])

    def test_position_management_hold_noop_does_not_mutate_ledger(self) -> None:
        ledger = apply_paper_execution(default_paper_ledger(), OPEN_LONG, now_iso="2026-05-14T00:00:00Z")
        thesis = {**copy.deepcopy(POSITION_THESIS_BASE), "action": "hold"}

        report = apply_position_management_thesis(ledger, thesis, now_iso="2026-05-14T00:10:00Z")

        self.assertTrue(report["ok"])
        self.assertEqual(report["status"], "HELD")
        self.assertFalse(report["ledger_mutated"])
        self.assertEqual(report["_ledger"]["open_positions"], ledger["open_positions"])
        self.assertNotIn("position_management_actions", report["_ledger"])

    def test_position_management_adjust_exit_updates_only_explicit_paper_exit_fields(self) -> None:
        ledger = apply_paper_execution(default_paper_ledger(), OPEN_LONG, now_iso="2026-05-14T00:00:00Z")
        position_id = ledger["open_positions"]["IRYSUSDT"]["position_id"]
        thesis = {
            **copy.deepcopy(POSITION_THESIS_BASE),
            "action": "adjust_exit",
            "position_ref": {"position_id": position_id, "symbol": "IRYSUSDT"},
            "exit_update": {
                "stop_loss_price": 98.5,
                "take_profit_price": 109.0,
                "max_holding_minutes": 45,
                "exit_rationale": "Agent tightened paper exits.",
                "agent_authorized": True,
                "real_order": False,
            },
        }

        report = apply_position_management_thesis(ledger, thesis, now_iso="2026-05-14T00:10:00Z")
        position = report["_ledger"]["open_positions"]["IRYSUSDT"]

        self.assertTrue(report["ok"])
        self.assertEqual(report["status"], "APPLIED")
        self.assertTrue(report["ledger_mutated"])
        self.assertEqual(position["stop_loss_price"], 98.5)
        self.assertEqual(position["take_profit_price"], 109.0)
        self.assertEqual(position["max_holding_minutes"], 45)
        self.assertEqual(position["exit_plan_source"], "position_management_thesis")
        self.assertEqual(
            report["_ledger"]["position_management_actions"][-1]["schema"],
            "tradecat_auto.position_management_action_report.v1",
        )

    def test_position_management_close_requires_explicit_agent_mark_price_and_closes_paper_position(self) -> None:
        ledger = apply_paper_execution(
            default_paper_ledger(initial_balance_usdt=1000.0), OPEN_LONG, fee_bps=0.0, now_iso="2026-05-14T00:00:00Z"
        )
        position_id = ledger["open_positions"]["IRYSUSDT"]["position_id"]
        thesis = {
            **copy.deepcopy(POSITION_THESIS_BASE),
            "action": "close",
            "position_ref": {"position_id": position_id, "symbol": "IRYSUSDT"},
            "close_intent": {
                "close_fraction": 1,
                "mark_price": 104.0,
                "mark_price_source": "agent_supplied_public_mark",
                "agent_authorized": True,
                "real_order": False,
            },
        }

        report = apply_position_management_thesis(ledger, thesis, fee_bps=0.0, now_iso="2026-05-14T00:15:00Z")

        self.assertTrue(report["ok"])
        self.assertEqual(report["status"], "APPLIED")
        self.assertEqual(report["_ledger"]["open_positions"], {})
        self.assertEqual(report["_ledger"]["closed_positions"][0]["close_reason"], "agent_position_management_close")
        self.assertEqual(report["_ledger"]["closed_positions"][0]["position_management_action_id"], report["action_id"])
        self.assertEqual(report["_ledger"]["fills"][-1]["action"], "CLOSE")
        self.assertEqual(report["_ledger"]["fills"][-1]["research_cycle_run_id"], "cycle-paper-1")

    def test_position_management_rejects_real_order_and_unsupported_add_reduce(self) -> None:
        ledger = apply_paper_execution(default_paper_ledger(), OPEN_LONG, now_iso="2026-05-14T00:00:00Z")
        unsafe = {
            **copy.deepcopy(POSITION_THESIS_BASE),
            "action": "close",
            "safety": {**POSITION_THESIS_BASE["safety"], "real_orders": True},
        }
        rejected = apply_position_management_thesis(ledger, unsafe, now_iso="2026-05-14T00:10:00Z")
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["error_code"], "position_management_safety_violation")
        self.assertFalse(rejected["ledger_mutated"])

        for unsafe_value in ("true", 1, "yes"):
            with self.subTest(unsafe_value=unsafe_value):
                stringy_unsafe = {
                    **copy.deepcopy(POSITION_THESIS_BASE),
                    "action": "close",
                    "safety": {**POSITION_THESIS_BASE["safety"], "real_orders": unsafe_value},
                }
                stringy_rejected = apply_position_management_thesis(
                    ledger, stringy_unsafe, now_iso="2026-05-14T00:10:00Z"
                )
                self.assertFalse(stringy_rejected["ok"])
                self.assertEqual(stringy_rejected["error_code"], "position_management_safety_violation")

        add = {
            **copy.deepcopy(POSITION_THESIS_BASE),
            "action": "add",
            "paper_intent": {
                "side": "LONG",
                "requested_margin_usdt": 10,
                "paper_leverage": 2,
                "agent_authorized": True,
                "real_order": False,
            },
        }
        unsupported = apply_position_management_thesis(ledger, add, now_iso="2026-05-14T00:10:00Z")
        self.assertFalse(unsupported["ok"])
        self.assertEqual(unsupported["status"], "UNSUPPORTED")
        self.assertEqual(unsupported["error_code"], "position_management_action_not_supported")


if __name__ == "__main__":
    unittest.main()
