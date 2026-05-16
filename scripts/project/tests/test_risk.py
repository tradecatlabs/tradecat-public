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
    def test_default_policy_allows_only_paper_for_strong_signal(self) -> None:
        decision = evaluate_risk(LONG_SIGNAL, default_risk_policy(mode="paper"))

        self.assertEqual(decision["schema"], "tradecat_auto.risk_decision.v1")
        self.assertEqual(decision["decision"], "ALLOW")
        self.assertEqual(decision["mode"], "paper")
        self.assertGreater(decision["max_notional_usdt"], 0)
        self.assertIn("paper_only", decision["constraints"])

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
                "requested_notional_usdt": 12.0,
            }
        )

        decision = evaluate_risk(LONG_SIGNAL, policy)

        self.assertEqual(decision["decision"], "REJECT")
        self.assertIn("max_total_notional_reached", decision["reasons"])
        self.assertEqual(decision["policy"]["current_total_notional_usdt"], 45.0)
        self.assertEqual(decision["policy"]["requested_notional_usdt"], 12.0)

    def test_consecutive_loss_limit_rejects_new_entries(self) -> None:
        policy = default_risk_policy(mode="paper")
        policy.update({"max_consecutive_losses": 3, "consecutive_losses": 3})

        decision = evaluate_risk(LONG_SIGNAL, policy)

        self.assertEqual(decision["decision"], "REJECT")
        self.assertIn("consecutive_loss_limit_reached", decision["reasons"])
        self.assertEqual(decision["policy"]["consecutive_losses"], 3)


if __name__ == "__main__":
    unittest.main()
