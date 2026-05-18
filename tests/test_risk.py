from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tradecat_auto.risk import default_risk_policy, evaluate_risk

LONG_SIGNAL = {
    "schema": "tradecat_auto.signal_score.v1",
    "ok": True,
    "symbol": "IRYSUSDT",
    "direction": "LONG",
    "score": 75,
    "tradable_candidate": True,
    "do_not_trade_reasons": [],
}


class RiskTests(unittest.TestCase):
    def test_default_policy_rejects_strong_signal_without_agent_sizing(self) -> None:
        decision = evaluate_risk(LONG_SIGNAL, default_risk_policy(mode="paper"))

        self.assertEqual(decision["schema"], "tradecat_auto.risk_decision.v1")
        self.assertEqual(decision["schema_version"], "1.0.0")
        self.assertEqual(decision["decision"], "REJECT")
        self.assertEqual(decision["mode"], "paper")
        self.assertFalse(decision["real_orders"])
        self.assertFalse(decision["signed_requests"])
        self.assertFalse(decision["reads_api_keys"])
        self.assertFalse(decision["safety"]["binance_account_state"])
        self.assertEqual(decision["provenance"]["source"], "tradecat_auto.risk.evaluate_risk")
        self.assertIn("agent_sizing_required", decision["reasons"])
        self.assertIn("paper_only", decision["constraints"])

    def test_explicit_agent_sizing_allows_only_paper_for_strong_signal(self) -> None:
        policy = default_risk_policy(mode="paper")
        policy.update({"requested_margin_usdt": 7.5, "requested_notional_usdt": 22.5, "paper_leverage": 3.0})

        decision = evaluate_risk(LONG_SIGNAL, policy)

        self.assertEqual(decision["decision"], "ALLOW")
        self.assertEqual(decision["mode"], "paper")
        self.assertIsNone(decision["max_notional_usdt"])
        self.assertIn("paper_only", decision["constraints"])

    def test_default_policy_has_no_strategy_or_budget_upper_caps(self) -> None:
        policy = default_risk_policy(mode="paper")
        policy.update(
            {
                "requested_margin_usdt": 1_000_000.0,
                "requested_notional_usdt": 50_000_000.0,
                "paper_leverage": 125.0,
                "current_open_positions": 999,
                "current_total_notional_usdt": 999_999_999.0,
                "daily_realized_pnl_usdt": -999_999.0,
                "consecutive_losses": 999,
            }
        )

        decision = evaluate_risk(LONG_SIGNAL, policy)

        self.assertEqual(decision["decision"], "ALLOW")
        self.assertNotIn("margin_budget_exceeded", decision["reasons"])
        self.assertNotIn("max_leverage_exceeded", decision["reasons"])
        self.assertNotIn("max_open_positions_reached", decision["reasons"])
        self.assertNotIn("max_total_notional_reached", decision["reasons"])
        self.assertNotIn("daily_loss_limit_reached", decision["reasons"])
        self.assertNotIn("consecutive_loss_limit_reached", decision["reasons"])
        self.assertEqual(decision["policy"]["paper_margin_budget_usdt"], None)
        self.assertEqual(decision["policy"]["max_leverage"], None)
        self.assertEqual(decision["policy"]["max_symbol_notional_usdt"], None)
        self.assertEqual(decision["policy"]["max_total_notional_usdt"], None)

    def test_watch_only_signal_is_not_allowed_to_open_position(self) -> None:
        signal = dict(LONG_SIGNAL)
        signal.update({"direction": "WATCH_ONLY", "tradable_candidate": False, "score": 30})

        decision = evaluate_risk(signal, default_risk_policy(mode="paper"))

        self.assertEqual(decision["decision"], "WATCH_ONLY")
        self.assertIn("signal_not_tradable", decision["reasons"])

    def test_kill_switch_rejects_even_strong_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kill = Path(tmp) / "KILL_SWITCH"
            kill.write_text("stop", encoding="utf-8")
            policy = default_risk_policy(mode="paper")
            policy["kill_switch_file"] = str(kill)

            decision = evaluate_risk(LONG_SIGNAL, policy)

            self.assertEqual(decision["decision"], "REJECT")
            self.assertIn("kill_switch_active", decision["reasons"])

    def test_mainnet_is_rejected_until_explicitly_supported_later(self) -> None:
        policy = default_risk_policy(mode="mainnet")
        policy["mainnet_enabled"] = True

        decision = evaluate_risk(LONG_SIGNAL, policy)

        self.assertEqual(decision["decision"], "REJECT")
        self.assertIn("mainnet_execution_not_implemented", decision["reasons"])

    def test_daily_loss_limit_rejects_even_strong_signal(self) -> None:
        policy = default_risk_policy(mode="paper")
        policy.update({"max_daily_loss_usdt": 10.0, "daily_realized_pnl_usdt": -10.5})

        decision = evaluate_risk(LONG_SIGNAL, policy)

        self.assertEqual(decision["decision"], "REJECT")
        self.assertIn("daily_loss_limit_reached", decision["reasons"])

    def test_open_position_limit_rejects_new_entries(self) -> None:
        policy = default_risk_policy(mode="paper")
        policy.update({"max_open_positions": 2, "current_open_positions": 2})

        decision = evaluate_risk(LONG_SIGNAL, policy)

        self.assertEqual(decision["decision"], "REJECT")
        self.assertIn("max_open_positions_reached", decision["reasons"])

    def test_total_notional_limit_rejects_entries_that_exceed_portfolio_cap(self) -> None:
        policy = default_risk_policy(mode="paper")
        policy.update(
            {
                "max_total_notional_usdt": 50.0,
                "current_total_notional_usdt": 45.0,
                "requested_notional_usdt": 7.5,
            }
        )

        decision = evaluate_risk(LONG_SIGNAL, policy)

        self.assertEqual(decision["decision"], "REJECT")
        self.assertIn("max_total_notional_reached", decision["reasons"])
        self.assertEqual(decision["policy"]["current_total_notional_usdt"], 45.0)
        self.assertEqual(decision["policy"]["requested_notional_usdt"], 7.5)

    def test_consecutive_loss_limit_rejects_new_entries(self) -> None:
        policy = default_risk_policy(mode="paper")
        policy.update({"max_consecutive_losses": 3, "consecutive_losses": 3})

        decision = evaluate_risk(LONG_SIGNAL, policy)

        self.assertEqual(decision["decision"], "REJECT")
        self.assertIn("consecutive_loss_limit_reached", decision["reasons"])
        self.assertEqual(decision["policy"]["consecutive_losses"], 3)

    def test_portfolio_risk_policy_rejects_overexposure_with_policy_snapshot(self) -> None:
        portfolio_policy = {
            "schema": "tradecat_auto.portfolio_risk_policy.v1",
            "schema_version": "1.0.0",
            "mode": "paper",
            "enabled": True,
            "new_entries_enabled": True,
            "limits": {
                "max_open_positions": 2,
                "max_total_notional_usdt": 50.0,
                "max_symbol_risk_usdt": 5.0,
                "max_leverage": 3.0,
            },
            "provenance": {"source": "test"},
        }
        policy = default_risk_policy(mode="paper")
        policy.update(
            {
                "portfolio_risk_policy": portfolio_policy,
                "current_open_positions": 2,
                "current_total_notional_usdt": 45.0,
                "requested_margin_usdt": 10.0,
                "requested_notional_usdt": 30.0,
                "requested_symbol_risk_usdt": 7.0,
                "paper_leverage": 4.0,
            }
        )

        decision = evaluate_risk(LONG_SIGNAL, policy)

        self.assertEqual(decision["decision"], "REJECT")
        self.assertIn("max_open_positions_reached", decision["reasons"])
        self.assertIn("max_total_notional_reached", decision["reasons"])
        self.assertIn("max_symbol_risk_reached", decision["reasons"])
        self.assertIn("max_leverage_exceeded", decision["reasons"])
        self.assertEqual(
            decision["policy"]["portfolio_risk_policy"]["schema"], "tradecat_auto.portfolio_risk_policy.v1"
        )
        self.assertFalse(decision["real_orders"])

    def test_portfolio_risk_policy_requires_confidence_and_symbol_risk_when_limits_are_enabled(self) -> None:
        policy = default_risk_policy(mode="paper")
        policy.update(
            {
                "portfolio_risk_policy": {
                    "schema": "tradecat_auto.portfolio_risk_policy.v1",
                    "schema_version": "1.0.0",
                    "mode": "paper",
                    "enabled": True,
                    "limits": {"min_agent_confidence": 0.7, "max_symbol_risk_pct": 0.02},
                    "provenance": {"source": "test"},
                },
                "requested_margin_usdt": 5.0,
                "requested_notional_usdt": 10.0,
                "paper_leverage": 2.0,
                "account_equity_usdt": 1000.0,
            }
        )

        missing = evaluate_risk(LONG_SIGNAL, policy)
        self.assertEqual(missing["decision"], "REJECT")
        self.assertIn("agent_confidence_required", missing["reasons"])
        self.assertIn("agent_symbol_risk_pct_required", missing["reasons"])

        policy.update({"agent_confidence": 0.65, "requested_symbol_risk_usdt": 30.0})
        exceeded = evaluate_risk(LONG_SIGNAL, policy)
        self.assertIn("agent_confidence_below_minimum", exceeded["reasons"])
        self.assertIn("max_symbol_risk_pct_reached", exceeded["reasons"])

    def test_portfolio_kill_switch_and_abnormal_move_reject_new_entries(self) -> None:
        policy = default_risk_policy(mode="paper")
        policy.update(
            {
                "portfolio_risk_policy": {
                    "schema": "tradecat_auto.portfolio_risk_policy.v1",
                    "schema_version": "1.0.0",
                    "mode": "paper",
                    "enabled": True,
                    "new_entries_enabled": False,
                    "limits": {"abnormal_move_halt_bps": 500},
                    "kill_switch": {"active": True, "reason": "operator pause"},
                    "provenance": {"source": "test"},
                },
                "requested_margin_usdt": 5.0,
                "requested_notional_usdt": 10.0,
                "paper_leverage": 2.0,
                "current_abnormal_move_bps": 700,
            }
        )

        decision = evaluate_risk(LONG_SIGNAL, policy)

        self.assertEqual(decision["decision"], "REJECT")
        self.assertIn("portfolio_kill_switch_active", decision["reasons"])
        self.assertIn("new_entries_disabled", decision["reasons"])
        self.assertIn("abnormal_move_halt_active", decision["reasons"])


if __name__ == "__main__":
    unittest.main()
