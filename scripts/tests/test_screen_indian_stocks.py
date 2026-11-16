"""Unit tests for the NSE / Indian stock screener script."""

from __future__ import annotations

import math
import unittest

from scripts.screen_indian_stocks import (
    analyze_symbol_bars,
    calculate_ema,
    calculate_rsi,
    calculate_sma,
    evaluate_stage_2_trend_template,
    format_screener_markdown,
)


class TestScreenIndianStocks(unittest.TestCase):
    def test_calculate_sma(self):
        series = [10.0, 20.0, 30.0, 40.0, 50.0]
        sma3 = calculate_sma(series, 3)
        self.assertTrue(math.isnan(sma3[0]))
        self.assertTrue(math.isnan(sma3[1]))
        self.assertAlmostEqual(sma3[2], 20.0)
        self.assertAlmostEqual(sma3[3], 30.0)
        self.assertAlmostEqual(sma3[4], 40.0)

    def test_calculate_ema(self):
        series = [10.0, 10.0, 10.0, 20.0, 30.0]
        ema3 = calculate_ema(series, 3)
        self.assertTrue(math.isnan(ema3[0]))
        self.assertTrue(math.isnan(ema3[1]))
        self.assertAlmostEqual(ema3[2], 10.0)
        # Next: (20 * 0.5) + (10 * 0.5) = 15.0
        self.assertAlmostEqual(ema3[3], 15.0)

    def test_calculate_rsi_uptrend(self):
        # Monotonically increasing sequence should produce very high RSI
        series = [float(i) for i in range(1, 30)]
        rsi = calculate_rsi(series, 14)
        self.assertEqual(rsi, 100.0)

    def test_evaluate_stage_2_trend_template_passes(self):
        is_stage_2, passed, checks = evaluate_stage_2_trend_template(
            close=1000.0,
            sma_50=950.0,
            sma_150=880.0,
            sma_200=850.0,
            sma_200_20d_ago=820.0,
            high_52w=1050.0,
            low_52w=600.0,
        )
        self.assertTrue(is_stage_2)
        self.assertEqual(passed, 7)
        self.assertEqual(len(checks), 7)

    def test_evaluate_stage_2_trend_template_fails(self):
        is_stage_2, passed, checks = evaluate_stage_2_trend_template(
            close=500.0,
            sma_50=600.0,
            sma_150=700.0,
            sma_200=800.0,
            sma_200_20d_ago=820.0,
            high_52w=1000.0,
            low_52w=480.0,
        )
        self.assertFalse(is_stage_2)
        self.assertLess(passed, 6)

    def test_analyze_symbol_bars(self):
        # Generate 250 bars of an advancing stock
        n = 250
        dates = [f"2026-01-{i % 28 + 1:02d}" for i in range(n)]
        # Price rising from 500 to 1200
        closes = [500.0 + (i * 2.8) for i in range(n)]
        highs = [c + 5.0 for c in closes]
        lows = [c - 5.0 for c in closes]
        volumes = [100000.0 + (i * 100) for i in range(n)]

        res = analyze_symbol_bars("TATASTEEL", dates, closes, volumes, highs, lows)
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res["symbol"], "TATASTEEL")
        self.assertTrue(res["is_stage_2"])
        self.assertIn("BREAKOUT", res["setup"])

    def test_format_screener_markdown(self):
        results = [
            {
                "symbol": "INFY",
                "close": 1550.0,
                "sma_50": 1500.0,
                "sma_200": 1420.0,
                "pct_from_52w_high": 2.5,
                "rvol": 1.8,
                "rsi": 62.4,
                "trend_template_score": "7/7",
                "setup": "BREAKOUT",
            }
        ]
        md = format_screener_markdown(results, strategy="breakout")
        self.assertIn("INFY", md)
        self.assertIn("₹1550.00", md)
        self.assertIn("BREAKOUT", md)

    def test_breakout_detection(self):
        # 250 bars with high volume breakout near 52W high
        n = 250
        dates = [f"2026-01-{i % 28 + 1:02d}" for i in range(n)]
        closes = [500.0 + (i * 2.5) for i in range(n)]
        highs = [c + 5.0 for c in closes]
        lows = [c - 5.0 for c in closes]
        volumes = [100000.0 for _ in range(n)]
        # Last bar high volume breakout
        volumes[-1] = 250000.0

        res = analyze_symbol_bars("BREAKOUTSTOCK", dates, closes, volumes, highs, lows)
        self.assertIsNotNone(res)
        assert res is not None
        self.assertTrue(res["is_stage_2"])
        self.assertEqual(res["setup"], "BREAKOUT")


if __name__ == "__main__":
    unittest.main()
