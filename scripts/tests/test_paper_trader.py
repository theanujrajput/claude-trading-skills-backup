"""Unit tests for the local JSON paper trading engine."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.paper_trader import (
    close_position,
    enter_position,
    format_status_markdown,
    init_account,
    load_state,
)


class TestPaperTrader(unittest.TestCase):
    def setUp(self):
        self.telegram_patcher = patch("scripts.telegram_notifier.TelegramNotifier")
        self.mock_notifier = self.telegram_patcher.start()
        self.mock_notifier.return_value.is_configured = False
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temp_dir.name) / "test_paper_state.json"

    def tearDown(self):
        self.telegram_patcher.stop()
        self.temp_dir.cleanup()

    def test_init_account(self):
        state = init_account(200000.0, self.state_file)
        self.assertEqual(state["initial_capital"], 200000.0)
        self.assertEqual(state["cash"], 200000.0)
        self.assertEqual(state["active_positions"], {})
        self.assertEqual(state["closed_trades"], [])

    def test_enter_position_success(self):
        init_account(100000.0, self.state_file)
        ok, msg, state = enter_position(
            symbol="ATHERENERG",
            qty=10,
            entry_price=1760.0,
            stop_loss=1690.0,
            target=1900.0,
            state_file=self.state_file,
        )
        self.assertTrue(ok)
        self.assertEqual(state["cash"], 100000.0 - (10 * 1760.0))
        self.assertIn("ATHERENERG", state["active_positions"])
        self.assertEqual(state["active_positions"]["ATHERENERG"]["quantity"], 10)

    def test_enter_position_insufficient_cash(self):
        init_account(5000.0, self.state_file)
        ok, msg, state = enter_position(
            symbol="ATHERENERG",
            qty=10,
            entry_price=1760.0,
            stop_loss=1690.0,
            state_file=self.state_file,
        )
        self.assertFalse(ok)
        self.assertIn("Insufficient cash", msg)

    def test_close_position_profit(self):
        init_account(100000.0, self.state_file)
        enter_position("HAL", 10, 4800.0, 4600.0, 5200.0, state_file=self.state_file)
        ok, msg, state = close_position(
            "HAL", exit_price=5100.0, reason="TARGET_REACHED", state_file=self.state_file
        )

        self.assertTrue(ok)
        self.assertNotIn("HAL", state["active_positions"])
        self.assertEqual(len(state["closed_trades"]), 1)
        trade = state["closed_trades"][0]
        self.assertEqual(trade["symbol"], "HAL")
        self.assertEqual(trade["pnl"], (5100.0 - 4800.0) * 10)
        self.assertEqual(trade["exit_reason"], "TARGET_REACHED")
        self.assertEqual(state["cash"], 100000.0 + 3000.0)
        self.assertIn("postmortem", trade)
        self.assertIsNotNone(trade["postmortem"])
        self.assertEqual(trade["postmortem"]["symbol"], "HAL")

    def test_format_status_markdown(self):
        init_account(500000.0, self.state_file)
        enter_position("ATHERENERG", 71, 1760.0, 1690.0, 1900.0, state_file=self.state_file)
        state = load_state(self.state_file)
        md = format_status_markdown(state)
        self.assertIn("ATHERENERG", md)
        self.assertIn("₹500,000.00", md)
        self.assertIn("Open Positions (1)", md)

    def test_trailing_stop_to_breakeven(self):
        from unittest.mock import MagicMock, patch

        import pandas as pd

        init_account(100000.0, self.state_file)
        # Entry at 1000, initial stop at 960 (-4%), target at 1080 (+8%)
        enter_position("TESTSYM", 10, 1000.0, 960.0, 1080.0, state_file=self.state_file)

        # 1. Price moves to 1045 (+4.5% gain) -> Should move stop to break-even (1000.0)
        mock_df = MagicMock()
        mock_series = pd.Series([1045.0], name="TESTSYM.NS")
        mock_df.__getitem__.return_value = {"TESTSYM.NS": mock_series}

        from scripts.paper_trader import update_market_prices

        with patch("yfinance.download", return_value=mock_df):
            events, state = update_market_prices(state_file=self.state_file)
            pos = state["active_positions"]["TESTSYM"]
            self.assertEqual(pos["stop_loss"], 1000.0)
            self.assertTrue(pos["trailing_breakeven_triggered"])
            self.assertTrue(any("Trailing Stop moved to Break-Even" in e for e in events))

        # 2. Later price drops to 999.0 -> Break-even stop should trigger with ₹0 loss
        mock_series_drop = pd.Series([999.0], name="TESTSYM.NS")
        mock_df.__getitem__.return_value = {"TESTSYM.NS": mock_series_drop}

        with patch("yfinance.download", return_value=mock_df):
            events, state = update_market_prices(state_file=self.state_file)
            self.assertNotIn("TESTSYM", state["active_positions"])
            self.assertEqual(len(state["closed_trades"]), 1)
            trade = state["closed_trades"][0]
            self.assertEqual(trade["exit_reason"], "BREAKEVEN_STOP_TRIGGERED")

    def test_hybrid_partial_exit_and_runner_trailing_stop(self):
        from unittest.mock import MagicMock, patch

        import pandas as pd

        from scripts.paper_trader import update_market_prices

        init_account(100000.0, self.state_file)
        # 10 shares @ 1000, initial stop at 960 (-4%), target at 1080 (+8%)
        enter_position("RUNNER_TEST", 10, 1000.0, 960.0, 1080.0, state_file=self.state_file)

        mock_df = MagicMock()

        # Phase 1: Stock hits 1085 (+8.5% gain, above target)
        # Should book 50% (5 shares) and convert remaining 5 shares into a Runner
        mock_series1 = pd.Series([1085.0], name="RUNNER_TEST.NS")
        mock_df.__getitem__.return_value = {"RUNNER_TEST.NS": mock_series1}

        with patch("yfinance.download", return_value=mock_df):
            events, state = update_market_prices(state_file=self.state_file)
            pos = state["active_positions"]["RUNNER_TEST"]
            self.assertEqual(pos["quantity"], 5)
            self.assertTrue(pos["is_runner"])
            self.assertTrue(pos["partial_target_hit"])
            # Stop loss should now be at 1085 * 0.96 = 1041.60 (guaranteed profit!)
            self.assertAlmostEqual(pos["stop_loss"], 1041.60, places=1)
            self.assertEqual(len(state["closed_trades"]), 1)
            self.assertEqual(state["closed_trades"][0]["exit_reason"], "PARTIAL_TARGET_50PCT")
            self.assertEqual(state["closed_trades"][0]["quantity"], 5)

        # Phase 2: Stock surges to 1200 (+20%)
        # Trailing stop should ratchet up to 1200 * 0.96 = 1152.00
        mock_series2 = pd.Series([1200.0], name="RUNNER_TEST.NS")
        mock_df.__getitem__.return_value = {"RUNNER_TEST.NS": mock_series2}

        with patch("yfinance.download", return_value=mock_df):
            events, state = update_market_prices(state_file=self.state_file)
            pos = state["active_positions"]["RUNNER_TEST"]
            self.assertAlmostEqual(pos["stop_loss"], 1152.00, places=1)
            self.assertEqual(pos["highest_price"], 1200.0)

        # Phase 3: Stock pulls back to 1150 (below trailing stop of 1152)
        # Runner exits with TRAILING_STOP_TRIGGERED
        mock_series3 = pd.Series([1150.0], name="RUNNER_TEST.NS")
        mock_df.__getitem__.return_value = {"RUNNER_TEST.NS": mock_series3}

        with patch("yfinance.download", return_value=mock_df):
            events, state = update_market_prices(state_file=self.state_file)
            self.assertNotIn("RUNNER_TEST", state["active_positions"])
            self.assertEqual(len(state["closed_trades"]), 2)
            runner_exit = state["closed_trades"][1]
            self.assertEqual(runner_exit["exit_reason"], "TRAILING_STOP_TRIGGERED")
            self.assertEqual(runner_exit["quantity"], 5)
            self.assertAlmostEqual(runner_exit["exit_price"], 1150.0)
            self.assertGreater(runner_exit["pnl"], 0)

    def test_profit_lock_ladder_at_6_pct(self):
        from unittest.mock import MagicMock, patch

        import pandas as pd

        from scripts.paper_trader import update_market_prices

        init_account(100000.0, self.state_file)
        # 10 shares @ 1000, initial stop at 960 (-4%), target at 1080 (+8%)
        enter_position("LOCK_TEST", 10, 1000.0, 960.0, 1080.0, state_file=self.state_file)

        mock_df = MagicMock()

        # Step 1: Stock hits 1045 (+4.5%) -> Stop moves to break-even (1000)
        mock_series1 = pd.Series([1045.0], name="LOCK_TEST.NS")
        mock_df.__getitem__.return_value = {"LOCK_TEST.NS": mock_series1}
        with patch("yfinance.download", return_value=mock_df):
            events, state = update_market_prices(state_file=self.state_file)
            pos = state["active_positions"]["LOCK_TEST"]
            self.assertEqual(pos["stop_loss"], 1000.0)
            self.assertTrue(pos["trailing_breakeven_triggered"])
            self.assertFalse(pos.get("profit_lock_triggered", False))

        # Step 2: Stock hits 1065 (+6.5%) -> Profit Lock activates, stop moves to 1030 (+3%)
        mock_series2 = pd.Series([1065.0], name="LOCK_TEST.NS")
        mock_df.__getitem__.return_value = {"LOCK_TEST.NS": mock_series2}
        with patch("yfinance.download", return_value=mock_df):
            events, state = update_market_prices(state_file=self.state_file)
            pos = state["active_positions"]["LOCK_TEST"]
            self.assertEqual(pos["stop_loss"], 1030.0)
            self.assertTrue(pos["profit_lock_triggered"])

        # Step 3: Stock reverses sharply to 1025 (below 1030)
        # Position should exit with PROFIT_LOCK_STOP_TRIGGERED with guaranteed profit
        mock_series3 = pd.Series([1025.0], name="LOCK_TEST.NS")
        mock_df.__getitem__.return_value = {"LOCK_TEST.NS": mock_series3}
        with patch("yfinance.download", return_value=mock_df):
            events, state = update_market_prices(state_file=self.state_file)
            self.assertNotIn("LOCK_TEST", state["active_positions"])
            self.assertEqual(len(state["closed_trades"]), 1)
            trade = state["closed_trades"][0]
            self.assertEqual(trade["exit_reason"], "PROFIT_LOCK_STOP_TRIGGERED")
            self.assertAlmostEqual(trade["exit_price"], 1025.0)
            self.assertGreater(trade["pnl"], 0)
            self.assertEqual(trade["postmortem"]["root_cause_category"], "PROFIT_LOCK_PRESERVED")


if __name__ == "__main__":
    unittest.main()
