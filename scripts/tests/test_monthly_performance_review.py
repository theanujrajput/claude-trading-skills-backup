"""Unit tests for the Monthly Performance Review module."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.monthly_performance_review import (
    evaluate_monthly_performance,
    format_monthly_review_markdown,
    run_monthly_performance_review,
)


class TestMonthlyPerformanceReview(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temp_dir.name) / "test_state.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_evaluate_monthly_performance_empty(self):
        state = {
            "portfolio_equity": 500000.0,
            "initial_capital": 500000.0,
            "cash": 500000.0,
            "closed_trades": [],
        }
        res = evaluate_monthly_performance(state, year=2026, month=11)
        self.assertEqual(res["total_trades"], 0)
        self.assertEqual(res["net_pnl"], 0.0)
        self.assertEqual(res["win_rate_pct"], 0.0)

    def test_evaluate_monthly_performance_metrics(self):
        state = {
            "portfolio_equity": 520000.0,
            "initial_capital": 500000.0,
            "cash": 520000.0,
            "closed_trades": [
                {
                    "symbol": "INFY",
                    "entry_date": "2026-11-01 10:00:00",
                    "exit_date": "2026-11-05 14:00:00",
                    "entry_price": 1000.0,
                    "exit_price": 1080.0,
                    "quantity": 100,
                    "initial_stop": 960.0,
                    "pnl": 8000.0,
                    "pnl_pct": 8.0,
                    "exit_reason": "TARGET_REACHED",
                },
                {
                    "symbol": "TCS",
                    "entry_date": "2026-11-03 10:00:00",
                    "exit_date": "2026-11-08 14:00:00",
                    "entry_price": 3000.0,
                    "exit_price": 3240.0,
                    "quantity": 50,
                    "initial_stop": 2880.0,
                    "pnl": 12000.0,
                    "pnl_pct": 8.0,
                    "exit_reason": "TARGET_REACHED",
                },
                {
                    "symbol": "RELIANCE",
                    "entry_date": "2026-11-10 10:00:00",
                    "exit_date": "2026-11-12 11:00:00",
                    "entry_price": 2500.0,
                    "exit_price": 2400.0,
                    "quantity": 20,
                    "initial_stop": 2400.0,
                    "pnl": -2000.0,
                    "pnl_pct": -4.0,
                    "exit_reason": "STOP_LOSS_HIT",
                },
            ],
        }
        res = evaluate_monthly_performance(state, year=2026, month=11)
        self.assertEqual(res["total_trades"], 3)
        self.assertEqual(res["winning_trades"], 2)
        self.assertEqual(res["losing_trades"], 1)
        self.assertAlmostEqual(res["win_rate_pct"], 66.7, places=1)
        self.assertEqual(res["gross_profit"], 20000.0)
        self.assertEqual(res["gross_loss"], -2000.0)
        self.assertEqual(res["net_pnl"], 18000.0)
        self.assertEqual(res["profit_factor"], 10.0)
        self.assertEqual(res["payoff_ratio"], 2.0)

    def test_format_monthly_review_markdown(self):
        state = {
            "portfolio_equity": 520000.0,
            "initial_capital": 500000.0,
            "cash": 520000.0,
            "closed_trades": [
                {
                    "symbol": "INFY",
                    "exit_date": "2026-11-05 14:00:00",
                    "entry_price": 1000.0,
                    "exit_price": 1080.0,
                    "quantity": 100,
                    "pnl": 8000.0,
                    "pnl_pct": 8.0,
                    "exit_reason": "TARGET_REACHED",
                }
            ],
        }
        review = evaluate_monthly_performance(state, year=2026, month=11)
        md = format_monthly_review_markdown(review)
        self.assertIn("Monthly Performance Review: November 2026", md)
        self.assertIn("Total Closed Trades", md)
        self.assertIn("Information Technology", md)

    @patch("scripts.telegram_notifier.TelegramNotifier")
    def test_run_monthly_performance_review_silent(self, mock_notifier_cls):
        mock_notifier = MagicMock()
        mock_notifier_cls.return_value = mock_notifier

        state = {
            "portfolio_equity": 500000.0,
            "initial_capital": 500000.0,
            "cash": 500000.0,
            "closed_trades": [],
        }
        self.state_file.write_text(json.dumps(state), encoding="utf-8")

        res = run_monthly_performance_review(
            state_file=self.state_file,
            year=2026,
            month=11,
            send_telegram=False,
        )
        self.assertEqual(res["status"], "success")
        mock_notifier.send_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
