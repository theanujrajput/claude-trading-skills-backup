"""Unit tests for the weekly sector report, contenders, and backtest generator."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.weekly_sector_report import (
    build_enhanced_pdf,
    save_new_recommendations,
)


class TestWeeklySectorReport(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_pdf = Path(self.temp_dir.name) / "test_report.pdf"
        self.history_file = Path(self.temp_dir.name) / "test_history.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_save_and_build_enhanced_pdf(self):
        mock_sectors = [
            {
                "sector": "NIFTY IT",
                "close": 42000.0,
                "ret_1w": 2.5,
                "ret_1m": 15.2,
                "ret_3m": 3.8,
                "above_50_sma": True,
                "above_200_sma": True,
                "rs_vs_nifty": 14.0,
                "status": "LEADING",
            },
            {
                "sector": "NIFTY PHARMA",
                "close": 22500.0,
                "ret_1w": 0.8,
                "ret_1m": 3.1,
                "ret_3m": 2.1,
                "above_50_sma": True,
                "above_200_sma": True,
                "rs_vs_nifty": 2.5,
                "status": "LEADING",
            },
        ]
        mock_global = {
            "cycle_phase": "Mid-Cycle Expansion",
            "confidence": "Moderate",
            "risk_regime": "BALANCED",
            "regime_score": 53,
            "top_global_sectors": ["Energy", "Healthcare", "Technology"],
            "overbought": ["Energy"],
        }
        mock_bench = {"nifty_1m_return": 1.2}

        mock_eval = {
            "week_date": "2026-10-25",
            "leading_sector": "NIFTY IT",
            "win_rate": 66.7,
            "avg_return": 4.04,
            "total_picks": 3,
            "picks": [
                {
                    "symbol": "COFORGE",
                    "recommended_date": "2026-10-25",
                    "recommended_price": 1900.5,
                    "current_price": 2045.0,
                    "pnl_pct": 7.6,
                    "setup": "BREAKOUT",
                    "outcome": "ACTIVE (+7.6%)",
                },
                {
                    "symbol": "PERSISTENT",
                    "recommended_date": "2026-10-25",
                    "recommended_price": 5727.5,
                    "current_price": 6048.0,
                    "pnl_pct": 5.6,
                    "setup": "STAGE_2_UPTREND",
                    "outcome": "TRAILING BE (+5.6%)",
                },
            ],
        }

        mock_contenders = [
            {
                "symbol": "COFORGE",
                "current_price": 2045.0,
                "recommended_price": 2045.0,
                "stop_loss": 1963.2,
                "target": 2208.6,
                "pct_from_52w_high": 1.2,
                "rvol": 1.4,
                "rsi": 64.2,
                "setup": "BREAKOUT",
                "notes": "Stage 2 Breakout in Leading Sector",
            }
        ]

        # Test saving recommendations
        save_new_recommendations(
            week_date="2026-11-01",
            leading_sector="NIFTY IT",
            picks=mock_contenders,
            history_file=self.history_file,
        )
        self.assertTrue(self.history_file.exists())

        # Test building enhanced PDF
        pdf_path = build_enhanced_pdf(
            sector_results=mock_sectors,
            global_info=mock_global,
            benchmark_info=mock_bench,
            previous_eval=mock_eval,
            new_contenders=mock_contenders,
            leading_sector="NIFTY IT",
            output_path=self.output_pdf,
        )

        self.assertTrue(pdf_path.exists())
        self.assertGreater(pdf_path.stat().st_size, 2000)


if __name__ == "__main__":
    unittest.main()
