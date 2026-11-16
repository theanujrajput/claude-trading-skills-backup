"""Unit tests for the NIFTY 50 Daily Market Regime Analyzer."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from scripts.market_regime_daily import (
    calculate_sma,
    evaluate_nifty_regime,
    format_market_regime_markdown,
    get_current_market_regime,
)


class TestMarketRegimeDaily(unittest.TestCase):
    def test_calculate_sma(self):
        series = [10.0, 20.0, 30.0, 40.0, 50.0]
        sma3 = calculate_sma(series, 3)
        self.assertTrue(pd.isna(sma3[0]))
        self.assertTrue(pd.isna(sma3[1]))
        self.assertAlmostEqual(sma3[2], 20.0)
        self.assertAlmostEqual(sma3[3], 30.0)
        self.assertAlmostEqual(sma3[4], 40.0)

    def test_evaluate_nifty_regime_insufficient_data(self):
        closes = [100.0] * 100
        dates = [f"2026-01-{i:02d}" for i in range(1, 101)]
        res = evaluate_nifty_regime(dates, closes)
        self.assertEqual(res["status"], "INSUFFICIENT_DATA")
        self.assertEqual(res["posture"], "RESTRICT")
        self.assertEqual(res["max_positions_cap"], 2)

    def test_evaluate_nifty_regime_confirmed_uptrend(self):
        # 260 days of steadily ascending prices
        closes = [100.0 + i * 0.5 for i in range(260)]
        dates = [f"day_{i}" for i in range(260)]
        res = evaluate_nifty_regime(dates, closes)

        self.assertEqual(res["status"], "CONFIRMED_UPTREND")
        self.assertEqual(res["posture"], "ALLOW")
        self.assertEqual(res["max_positions_cap"], 5)
        self.assertTrue(res["metrics"]["above_50_sma"])
        self.assertTrue(res["metrics"]["above_200_sma"])
        self.assertTrue(res["metrics"]["sma_50_above_200"])
        self.assertTrue(res["metrics"]["sma_200_trending_up"])

    def test_evaluate_nifty_regime_uptrend_under_pressure(self):
        # 260 days where price was ascending up to 240, then drops below 50 SMA but stays above 200 SMA
        # 200 SMA will be around ~150, 50 SMA around ~210, current price at 190
        closes = [100.0 + i * 0.5 for i in range(240)]  # ends at 219.5
        # add 20 days of drop
        closes.extend([190.0] * 20)
        dates = [f"day_{i}" for i in range(260)]

        res = evaluate_nifty_regime(dates, closes)
        self.assertEqual(res["status"], "UPTREND_UNDER_PRESSURE")
        self.assertEqual(res["posture"], "RESTRICT")
        self.assertEqual(res["max_positions_cap"], 2)
        self.assertFalse(res["metrics"]["above_50_sma"])
        self.assertTrue(res["metrics"]["above_200_sma"])

    def test_evaluate_nifty_regime_market_correction(self):
        # 260 days where price plunges below 200 SMA
        closes = [200.0] * 200 + [100.0] * 60
        dates = [f"day_{i}" for i in range(260)]

        res = evaluate_nifty_regime(dates, closes)
        self.assertEqual(res["status"], "MARKET_CORRECTION")
        self.assertEqual(res["posture"], "CASH_PRIORITY")
        self.assertEqual(res["max_positions_cap"], 0)
        self.assertFalse(res["metrics"]["above_200_sma"])

    def test_format_market_regime_markdown(self):
        regime = {
            "status": "CONFIRMED_UPTREND",
            "posture": "ALLOW",
            "reason": "Strong Bullish Alignment",
            "max_positions_cap": 5,
            "metrics": {
                "date": "2026-11-16",
                "nifty_close": 24500.0,
                "sma_50": 24100.0,
                "sma_200": 23200.0,
                "above_50_sma": True,
                "above_200_sma": True,
                "sma_50_above_200": True,
                "sma_200_trending_up": True,
                "pct_from_52w_high": 1.2,
                "ret_5d_pct": 0.8,
            },
        }
        md = format_market_regime_markdown(regime)
        self.assertIn("NIFTY 50 Daily Market Regime", md)
        self.assertIn("CONFIRMED_UPTREND", md)
        self.assertIn("24,500.00", md)

    @patch("scripts.market_regime_daily.fetch_nifty_daily_bars")
    def test_get_current_market_regime_live_mock(self, mock_fetch):
        dates = [f"2026-01-{i:02d}" for i in range(1, 261)]
        closes = [100.0 + i * 0.5 for i in range(260)]
        volumes = [1000000.0] * 260
        mock_fetch.return_value = (dates, closes, volumes)

        res = get_current_market_regime()
        self.assertIn(
            res["status"], ["CONFIRMED_UPTREND", "UPTREND_UNDER_PRESSURE", "MARKET_CORRECTION"]
        )
        self.assertIn("metrics", res)


if __name__ == "__main__":
    unittest.main()
