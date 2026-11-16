"""Unit tests for the automated daily swing routine orchestrator."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.daily_swing_routine import is_market_hours, run_daily_cycle
from scripts.paper_trader import init_account


class TestDailySwingRoutine(unittest.TestCase):
    def setUp(self):
        self.telegram_patcher = patch("scripts.telegram_notifier.TelegramNotifier")
        self.mock_notifier = self.telegram_patcher.start()
        self.mock_notifier.return_value.is_configured = False
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temp_dir.name) / "test_cycle_state.json"
        init_account(500000.0, self.state_file)

    def tearDown(self):
        self.telegram_patcher.stop()
        self.temp_dir.cleanup()

    @patch("scripts.daily_swing_routine.run_screener")
    @patch("scripts.daily_swing_routine.update_market_prices")
    def test_run_daily_cycle_enters_trade(self, mock_update, mock_screener):
        # Mock price update
        mock_update.return_value = (
            ["Updated prices ok"],
            {
                "initial_capital": 500000.0,
                "cash": 500000.0,
                "portfolio_equity": 500000.0,
                "active_positions": {},
                "closed_trades": [],
            },
        )

        # Mock screener candidate
        mock_screener.return_value = [
            {
                "symbol": "ANANDRATHI",
                "close": 2200.0,
                "setup": "BREAKOUT",
                "trend_template_score": "7/7",
            }
        ]

        result = run_daily_cycle(
            auto_buy=True,
            risk_pct=1.0,
            max_positions=5,
            state_file=self.state_file,
        )

        self.assertIn("ANANDRATHI", result["new_trades"])
        self.assertEqual(result["active_positions_count"], 1)

    @patch("scripts.daily_swing_routine.run_screener")
    @patch("scripts.daily_swing_routine.update_market_prices")
    def test_run_daily_cycle_respects_max_slots(self, mock_update, mock_screener):
        # Mock full 5 positions
        mock_update.return_value = (
            ["Updated prices ok"],
            {
                "initial_capital": 500000.0,
                "cash": 50000.0,
                "portfolio_equity": 500000.0,
                "active_positions": {f"STOCK{i}": {} for i in range(5)},
                "closed_trades": [],
            },
        )

        mock_screener.return_value = [
            {
                "symbol": "NEWSTOCK",
                "close": 1000.0,
                "setup": "BREAKOUT",
                "trend_template_score": "7/7",
            }
        ]

        result = run_daily_cycle(
            auto_buy=True,
            max_positions=5,
            state_file=self.state_file,
        )

        self.assertEqual(len(result["new_trades"]), 0)
        self.assertIn("maximum capacity", result["digest"])

    def test_is_market_hours_logic(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        ist = ZoneInfo("Asia/Kolkata")
        # Tuesday at 11:30 AM IST (Open)
        tuesday_open = datetime(2026, 11, 3, 11, 30, tzinfo=ist)
        is_open, _ = is_market_hours(tuesday_open)
        self.assertTrue(is_open)

        # Tuesday at 08:30 AM IST (Pre-market / Closed)
        tuesday_pre = datetime(2026, 11, 3, 8, 30, tzinfo=ist)
        is_open, _ = is_market_hours(tuesday_pre)
        self.assertFalse(is_open)

        # Sunday at 11:30 AM IST (Weekend / Closed)
        sunday = datetime(2026, 11, 1, 11, 30, tzinfo=ist)
        is_open, _ = is_market_hours(sunday)
        self.assertFalse(is_open)

    @patch("scripts.daily_swing_routine.is_market_hours")
    def test_run_daily_cycle_skips_when_market_closed(self, mock_is_open):
        mock_is_open.return_value = (False, "Market closed today (Weekend)")
        result = run_daily_cycle(check_market_hours=True, state_file=self.state_file)
        self.assertEqual(result["status"], "market_closed")
        self.assertIn("Skipped", result["digest"])

    @patch("scripts.daily_swing_routine.run_screener")
    @patch("scripts.daily_swing_routine.update_market_prices")
    def test_run_daily_cycle_uses_cached_watchlist(self, mock_update, mock_screener):
        import json
        from datetime import datetime
        from zoneinfo import ZoneInfo

        ist = ZoneInfo("Asia/Kolkata")
        today_str = datetime.now(ist).strftime("%Y-%m-%d")

        # Set up state with pre-cached daily watchlist for today
        with open(self.state_file, encoding="utf-8") as f:
            state = json.load(f)
        state["watchlist_date"] = today_str
        state["daily_watchlist"] = [
            {
                "symbol": "CACHEDSYM",
                "close": 1500.0,
                "setup": "BREAKOUT",
                "trend_template_score": "7/7",
            }
        ]
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state, f)

        mock_update.return_value = (["Prices ok"], state)

        result = run_daily_cycle(
            auto_buy=True,
            risk_pct=1.0,
            max_positions=5,
            state_file=self.state_file,
        )

        # Full screener should NOT be called because watchlist was cached!
        mock_screener.assert_not_called()
        self.assertIn("CACHEDSYM", result["new_trades"])
        self.assertIn("Fast Watchlist Monitor", result["digest"])

    @patch("scripts.daily_swing_routine.run_screener")
    @patch("scripts.daily_swing_routine.update_market_prices")
    def test_run_daily_cycle_skips_cooldown_stock(self, mock_update, mock_screener):
        import json
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        ist = ZoneInfo("Asia/Kolkata")
        # Trade closed 1 day ago
        yesterday_str = (datetime.now(ist) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")

        with open(self.state_file, encoding="utf-8") as f:
            state = json.load(f)
        state["closed_trades"].append(
            {
                "symbol": "RECENTEXIT",
                "entry_date": "2026-11-01 10:00:00",
                "exit_date": yesterday_str,
                "entry_price": 1000.0,
                "exit_price": 1080.0,
                "quantity": 50,
                "cost": 50000.0,
                "proceeds": 54000.0,
                "pnl": 4000.0,
                "pnl_pct": 8.0,
                "exit_reason": "TARGET_REACHED",
            }
        )
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state, f)

        mock_update.return_value = (["Prices ok"], state)
        mock_screener.return_value = [
            {
                "symbol": "RECENTEXIT",
                "close": 1100.0,
                "setup": "BREAKOUT",
                "trend_template_score": "7/7",
            }
        ]

        result = run_daily_cycle(
            auto_buy=True,
            risk_pct=1.0,
            max_positions=5,
            cooldown_days=5,
            state_file=self.state_file,
        )

        # Should be skipped due to cooldown!
        self.assertNotIn("RECENTEXIT", result["new_trades"])
        self.assertIn("post-exit cooldown", result["digest"])

    @patch("scripts.daily_swing_routine.run_screener")
    @patch("scripts.daily_swing_routine.update_market_prices")
    def test_run_daily_cycle_allows_stock_after_cooldown_expires(self, mock_update, mock_screener):
        import json
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        ist = ZoneInfo("Asia/Kolkata")
        # Trade closed 10 days ago (past 5-day cooldown)
        old_exit_str = (datetime.now(ist) - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")

        with open(self.state_file, encoding="utf-8") as f:
            state = json.load(f)
        state["closed_trades"].append(
            {
                "symbol": "OLDEXIT",
                "entry_date": "2026-10-25 10:00:00",
                "exit_date": old_exit_str,
                "entry_price": 1000.0,
                "exit_price": 1080.0,
                "quantity": 50,
                "cost": 50000.0,
                "proceeds": 54000.0,
                "pnl": 4000.0,
                "pnl_pct": 8.0,
                "exit_reason": "TARGET_REACHED",
            }
        )
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state, f)

        mock_update.return_value = (["Prices ok"], state)
        mock_screener.return_value = [
            {
                "symbol": "OLDEXIT",
                "close": 1100.0,
                "setup": "BREAKOUT",
                "trend_template_score": "7/7",
            }
        ]

        result = run_daily_cycle(
            auto_buy=True,
            risk_pct=1.0,
            max_positions=5,
            cooldown_days=5,
            state_file=self.state_file,
        )

        # Should be allowed to re-enter!
        self.assertIn("OLDEXIT", result["new_trades"])

    @patch("scripts.daily_swing_routine.evaluate_drawdown_circuit_breaker")
    @patch("scripts.daily_swing_routine.run_screener")
    @patch("scripts.daily_swing_routine.update_market_prices")
    def test_circuit_breaker_halts_buying(self, mock_update, mock_screener, mock_cb):
        mock_update.return_value = (
            ["Prices ok"],
            {
                "initial_capital": 500000.0,
                "cash": 500000.0,
                "portfolio_equity": 500000.0,
                "active_positions": {},
                "closed_trades": [],
            },
        )
        mock_cb.return_value = {
            "is_allowed": False,
            "status": "HALTED_DAILY_LOSS",
            "reason": "Daily realized loss limit reached",
            "metrics": {},
        }
        mock_screener.return_value = [
            {
                "symbol": "TESTSYM",
                "close": 500.0,
                "setup": "BREAKOUT",
                "trend_template_score": "7/7",
            }
        ]

        result = run_daily_cycle(
            auto_buy=True,
            state_file=self.state_file,
        )

        self.assertEqual(result["new_trades"], [])
        self.assertIn("Circuit Breaker TRIPPED", result["digest"])
        mock_screener.assert_not_called()

    @patch("scripts.daily_swing_routine.get_current_market_regime")
    @patch("scripts.daily_swing_routine.run_screener")
    @patch("scripts.daily_swing_routine.update_market_prices")
    def test_market_regime_cash_priority_halts_buying(
        self, mock_update, mock_screener, mock_regime
    ):
        mock_update.return_value = (
            ["Prices ok"],
            {
                "initial_capital": 500000.0,
                "cash": 500000.0,
                "portfolio_equity": 500000.0,
                "active_positions": {},
                "closed_trades": [],
            },
        )
        mock_regime.return_value = {
            "status": "MARKET_CORRECTION",
            "posture": "CASH_PRIORITY",
            "reason": "NIFTY 50 trading below 200 SMA",
            "max_positions_cap": 0,
        }
        mock_screener.return_value = [
            {
                "symbol": "TESTSYM",
                "close": 500.0,
                "setup": "BREAKOUT",
                "trend_template_score": "7/7",
            }
        ]

        result = run_daily_cycle(
            auto_buy=True,
            state_file=self.state_file,
        )

        self.assertEqual(result["new_trades"], [])
        self.assertIn("Market in Correction", result["digest"])
        mock_screener.assert_not_called()

    @patch("scripts.daily_swing_routine.get_current_market_regime")
    @patch("scripts.daily_swing_routine.run_screener")
    @patch("scripts.daily_swing_routine.update_market_prices")
    def test_market_regime_restrict_caps_positions(self, mock_update, mock_screener, mock_regime):
        # 2 active positions already open, max_positions defaults to 5, but regime caps at 2
        mock_update.return_value = (
            ["Prices ok"],
            {
                "initial_capital": 500000.0,
                "cash": 300000.0,
                "portfolio_equity": 500000.0,
                "active_positions": {
                    "STOCKA": {"symbol": "STOCKA", "market_value": 100000.0},
                    "STOCKB": {"symbol": "STOCKB", "market_value": 100000.0},
                },
                "closed_trades": [],
            },
        )
        mock_regime.return_value = {
            "status": "UPTREND_UNDER_PRESSURE",
            "posture": "RESTRICT",
            "reason": "NIFTY below 50 SMA",
            "max_positions_cap": 2,
        }
        mock_screener.return_value = [
            {
                "symbol": "TESTSYM",
                "close": 500.0,
                "setup": "BREAKOUT",
                "trend_template_score": "7/7",
            }
        ]

        result = run_daily_cycle(
            auto_buy=True,
            max_positions=5,
            state_file=self.state_file,
        )

        self.assertEqual(result["new_trades"], [])
        self.assertIn("Restricting maximum positions from 5 to 2", result["digest"])
        self.assertIn("Portfolio is at maximum capacity (2/2 slots filled)", result["digest"])


if __name__ == "__main__":
    unittest.main()
