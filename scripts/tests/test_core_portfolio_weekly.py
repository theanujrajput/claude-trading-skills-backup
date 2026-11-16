"""Unit tests for the Core Portfolio Weekly Review module."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.core_portfolio_weekly import (
    evaluate_core_portfolio,
    format_core_portfolio_markdown,
    get_sector_for_symbol,
    run_core_portfolio_review,
)


class TestCorePortfolioWeekly(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temp_dir.name) / "test_portfolio_state.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_get_sector_for_symbol(self):
        self.assertEqual(get_sector_for_symbol("INFY"), "Information Technology")
        self.assertEqual(get_sector_for_symbol("HDFCBANK.NS"), "Banking")
        self.assertEqual(get_sector_for_symbol("UNKNOWN_SYM"), "Diversified / General")

    def test_evaluate_core_portfolio_empty(self):
        state = {
            "portfolio_equity": 500000.0,
            "cash": 500000.0,
            "active_positions": {},
        }
        res = evaluate_core_portfolio(state)
        self.assertEqual(res["portfolio_equity"], 500000.0)
        self.assertEqual(res["cash_pct"], 100.0)
        self.assertEqual(res["positions_count"], 0)
        self.assertEqual(len(res["warnings"]), 0)

    def test_evaluate_core_portfolio_sector_and_stock_caps(self):
        state = {
            "portfolio_equity": 500000.0,
            "cash": 200000.0,
            "active_positions": {
                # INFOSYS: 150,000 / 500,000 = 30% -> breaks 20% stock cap and 25% sector cap
                "INFY": {
                    "symbol": "INFY",
                    "market_value": 150000.0,
                    "unrealized_pnl": 5000.0,
                    "pnl_pct": 3.4,
                    "trailing_breakeven_triggered": True,
                },
                # TCS: 50,000 / 500,000 = 10%
                "TCS": {
                    "symbol": "TCS",
                    "market_value": 50000.0,
                    "unrealized_pnl": 2000.0,
                    "pnl_pct": 4.1,
                    "trailing_breakeven_triggered": False,
                },
                # HDFCBANK: 100,000 / 500,000 = 20%
                "HDFCBANK": {
                    "symbol": "HDFCBANK",
                    "market_value": 100000.0,
                    "unrealized_pnl": 1000.0,
                    "pnl_pct": 1.0,
                    "trailing_breakeven_triggered": False,
                },
            },
        }
        res = evaluate_core_portfolio(state, max_sector_pct=25.0, max_stock_pct=20.0)
        self.assertEqual(res["positions_count"], 3)
        self.assertEqual(res["risk_free_positions_count"], 1)
        self.assertAlmostEqual(res["risk_free_ratio_pct"], 33.3, places=1)

        # Total IT sector is 200,000 / 500,000 = 40% -> warning
        # INFY is 30% -> warning
        warnings_text = " ".join(res["warnings"])
        self.assertIn("Information Technology", warnings_text)
        self.assertIn("INFY", warnings_text)

    def test_format_core_portfolio_markdown(self):
        state = {
            "portfolio_equity": 500000.0,
            "cash": 400000.0,
            "active_positions": {
                "TCS": {
                    "symbol": "TCS",
                    "market_value": 100000.0,
                    "unrealized_pnl": 5000.0,
                    "pnl_pct": 5.0,
                    "trailing_breakeven_triggered": True,
                }
            },
        }
        review = evaluate_core_portfolio(state)
        md = format_core_portfolio_markdown(review)
        self.assertIn("Core Portfolio Weekly Review", md)
        self.assertIn("Information Technology", md)
        self.assertIn("Risk-Free (BE 🛡️)", md)

    @patch("scripts.telegram_notifier.TelegramNotifier")
    def test_run_core_portfolio_review_silent(self, mock_notifier_cls):
        mock_notifier = MagicMock()
        mock_notifier_cls.return_value = mock_notifier

        state = {
            "portfolio_equity": 500000.0,
            "cash": 500000.0,
            "active_positions": {},
        }
        self.state_file.write_text(json.dumps(state), encoding="utf-8")

        res = run_core_portfolio_review(
            state_file=self.state_file,
            send_telegram=False,
        )
        self.assertEqual(res["status"], "success")
        mock_notifier.send_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
