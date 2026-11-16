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


if __name__ == "__main__":
    unittest.main()
