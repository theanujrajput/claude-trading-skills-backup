"""Unit tests for the Drawdown Circuit Breaker module."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from scripts.drawdown_circuit_breaker import (
    evaluate_drawdown_circuit_breaker,
    format_circuit_breaker_markdown,
)

IST = ZoneInfo("Asia/Kolkata")


class TestDrawdownCircuitBreaker(unittest.TestCase):
    def setUp(self):
        self.fixed_now = datetime(2026, 11, 16, 15, 30, tzinfo=IST)

    def test_evaluate_drawdown_clear_when_no_trades(self):
        state = {
            "portfolio_equity": 500000.0,
            "cash": 500000.0,
            "active_positions": {},
            "closed_trades": [],
        }
        res = evaluate_drawdown_circuit_breaker(state, now=self.fixed_now)
        self.assertTrue(res["is_allowed"])
        self.assertEqual(res["status"], "CLEAR")

    def test_evaluate_drawdown_halts_on_daily_loss_limit(self):
        # 2% of 500,000 is 10,000. Let's create a trade closed today with loss of -12,000
        state = {
            "portfolio_equity": 500000.0,
            "cash": 488000.0,
            "active_positions": {},
            "closed_trades": [
                {
                    "symbol": "LOSER1",
                    "exit_date": "2026-11-16 11:30:00",
                    "pnl": -12000.0,
                    "pnl_pct": -4.0,
                    "exit_reason": "STOP_LOSS_HIT",
                }
            ],
        }
        res = evaluate_drawdown_circuit_breaker(state, now=self.fixed_now, max_daily_loss_pct=2.0)
        self.assertFalse(res["is_allowed"])
        self.assertEqual(res["status"], "HALTED_DAILY_LOSS")
        self.assertIn("Daily realized loss", res["reason"])

    def test_evaluate_drawdown_halts_on_losing_streak(self):
        # 2 consecutive stop losses within past 24 hours (even if total loss < 2%)
        t1 = (self.fixed_now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
        t2 = (self.fixed_now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")

        state = {
            "portfolio_equity": 500000.0,
            "cash": 494000.0,
            "active_positions": {},
            "closed_trades": [
                {
                    "symbol": "STOP1",
                    "exit_date": t1,
                    "pnl": -3000.0,
                    "exit_reason": "STOP_LOSS_HIT",
                },
                {
                    "symbol": "STOP2",
                    "exit_date": t2,
                    "pnl": -3000.0,
                    "exit_reason": "STOP_LOSS_HIT",
                },
            ],
        }
        res = evaluate_drawdown_circuit_breaker(
            state, now=self.fixed_now, losing_streak_threshold=2
        )
        self.assertFalse(res["is_allowed"])
        self.assertEqual(res["status"], "COOLDOWN_LOSING_STREAK")
        self.assertIn("Losing streak threshold triggered", res["reason"])

    def test_evaluate_drawdown_halts_on_weekly_drawdown(self):
        # 5% of 500,000 is 25,000. Let's create losses totaling -30,000 over the past 4 days
        t1 = (self.fixed_now - timedelta(days=4)).strftime("%Y-%m-%d %H:%M:%S")
        t2 = (self.fixed_now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")

        state = {
            "portfolio_equity": 500000.0,
            "cash": 470000.0,
            "active_positions": {},
            "closed_trades": [
                {
                    "symbol": "WEEK1",
                    "exit_date": t1,
                    "pnl": -15000.0,
                    "exit_reason": "STOP_LOSS_HIT",
                },
                {
                    "symbol": "WEEK2",
                    "exit_date": t2,
                    "pnl": -15000.0,
                    "exit_reason": "STOP_LOSS_HIT",
                },
            ],
        }
        # Note: t2 was 2 days ago, so consecutive stops within 24h will be 0
        res = evaluate_drawdown_circuit_breaker(state, now=self.fixed_now, max_weekly_loss_pct=5.0)
        self.assertFalse(res["is_allowed"])
        self.assertEqual(res["status"], "HALTED_WEEKLY_DRAWDOWN")
        self.assertIn("7-day realized drawdown", res["reason"])

    def test_format_circuit_breaker_markdown(self):
        result = {
            "is_allowed": True,
            "status": "CLEAR",
            "reason": "All good",
            "metrics": {
                "portfolio_equity": 500000.0,
                "today_realized_loss": 0.0,
                "daily_loss_limit": 10000.0,
                "today_net_pnl": 5000.0,
                "weekly_realized_loss": 0.0,
                "weekly_loss_limit": 25000.0,
                "weekly_net_pnl": 5000.0,
                "consecutive_stops_24h": 0,
            },
        }
        md = format_circuit_breaker_markdown(result)
        self.assertIn("Drawdown Circuit Breaker Status: `CLEAR`", md)
        self.assertIn("**Buying Allowed:** YES", md)


if __name__ == "__main__":
    unittest.main()
