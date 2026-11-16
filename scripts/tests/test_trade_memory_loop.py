"""Unit tests for the Trade Memory Loop module."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.trade_memory_loop import (
    evaluate_trade_postmortem,
    format_postmortem_markdown,
    run_trade_memory_audit,
)


class TestTradeMemoryLoop(unittest.TestCase):
    def test_evaluate_trade_postmortem_target_win(self):
        trade = {
            "symbol": "TCS",
            "entry_date": "2026-11-01 09:30:00",
            "exit_date": "2026-11-05 15:15:00",
            "entry_price": 3000.0,
            "exit_price": 3240.0,
            "quantity": 50,
            "initial_stop": 2880.0,  # 120 risk/share
            "pnl": 12000.0,
            "pnl_pct": 8.0,
            "exit_reason": "TARGET_REACHED",
        }
        pm = evaluate_trade_postmortem(trade)
        self.assertEqual(pm["symbol"], "TCS")
        self.assertEqual(pm["hold_days"], 4)
        self.assertEqual(pm["r_multiple"], 2.0)
        self.assertEqual(pm["root_cause_category"], "SETUP_EDGE_PLAYED_OUT")
        self.assertIn("Minervini breakout momentum validated", pm["lesson"])

    def test_evaluate_trade_postmortem_breakeven_protection(self):
        trade = {
            "symbol": "INFY",
            "entry_date": "2026-11-02 10:00:00",
            "exit_date": "2026-11-06 14:00:00",
            "entry_price": 1800.0,
            "exit_price": 1800.0,
            "quantity": 50,
            "initial_stop": 1728.0,
            "pnl": 0.0,
            "pnl_pct": 0.0,
            "exit_reason": "BREAKEVEN_STOP_TRIGGERED",
        }
        pm = evaluate_trade_postmortem(trade)
        self.assertEqual(pm["symbol"], "INFY")
        self.assertEqual(pm["hold_days"], 4)
        self.assertEqual(pm["r_multiple"], 0.0)
        self.assertEqual(pm["root_cause_category"], "PROTECTED_CAPITAL")
        self.assertIn("protected capital", pm["lesson"])

    def test_evaluate_trade_postmortem_normal_stop(self):
        trade = {
            "symbol": "RELIANCE",
            "entry_date": "2026-11-10 10:00:00",
            "exit_date": "2026-11-12 11:30:00",
            "entry_price": 2500.0,
            "exit_price": 2400.0,
            "quantity": 20,
            "initial_stop": 2400.0,
            "pnl": -2000.0,
            "pnl_pct": -4.0,
            "exit_reason": "STOP_LOSS_HIT",
        }
        pm = evaluate_trade_postmortem(trade)
        self.assertEqual(pm["symbol"], "RELIANCE")
        self.assertEqual(pm["hold_days"], 2)
        self.assertEqual(pm["r_multiple"], -1.0)
        self.assertEqual(pm["root_cause_category"], "NORMAL_RISK_DISTRIBUTION")
        self.assertIn("Disciplined", pm["lesson"])

    def test_format_postmortem_markdown(self):
        pm = {
            "symbol": "ATHERENERG",
            "exit_date": "2026-11-15 15:00:00",
            "entry_price": 400.0,
            "exit_price": 432.0,
            "pnl": 3200.0,
            "pnl_pct": 8.0,
            "r_multiple": 2.0,
            "hold_days": 3,
            "exit_reason": "TARGET_REACHED",
            "root_cause_category": "SETUP_EDGE_PLAYED_OUT",
            "lesson": "Momentum confirmed.",
        }
        md = format_postmortem_markdown(pm)
        self.assertIn("Trade Postmortem: #ATHERENERG", md)
        self.assertIn("+2.00R", md)
        self.assertIn("SETUP_EDGE_PLAYED_OUT", md)

    def test_run_trade_memory_audit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            state = {
                "active_positions": {},
                "closed_trades": [
                    {
                        "symbol": "SONACOMS",
                        "entry_date": "2026-11-01 10:00:00",
                        "exit_date": "2026-11-04 15:00:00",
                        "entry_price": 500.0,
                        "exit_price": 540.0,
                        "quantity": 100,
                        "pnl": 4000.0,
                        "pnl_pct": 8.0,
                        "exit_reason": "TARGET_REACHED",
                    }
                ],
            }
            state_file.write_text(json.dumps(state), encoding="utf-8")

            audited = run_trade_memory_audit(state_file)
            self.assertEqual(len(audited), 1)
            self.assertEqual(audited[0]["symbol"], "SONACOMS")

            # Check that state was updated with postmortem attached
            with open(state_file, encoding="utf-8") as f:
                saved = json.load(f)
            self.assertIn("postmortem", saved["closed_trades"][0])
            self.assertEqual(saved["closed_trades"][0]["postmortem"]["r_multiple"], 2.0)


if __name__ == "__main__":
    unittest.main()
