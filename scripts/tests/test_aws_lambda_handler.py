"""Unit tests for the AWS Lambda handler script."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.aws_lambda_handler import lambda_handler, sync_from_s3, sync_to_s3


class TestAWSLambdaHandler(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.local_state = Path(self.temp_dir.name) / "paper_state.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_sync_from_s3_success(self):
        s3_mock = MagicMock()
        sync_from_s3(s3_mock, "test-bucket", "state.json", self.local_state, 500000.0)
        s3_mock.download_file.assert_called_once_with(
            "test-bucket", "state.json", str(self.local_state)
        )

    def test_sync_to_s3_success(self):
        s3_mock = MagicMock()
        self.local_state.write_text("{}", encoding="utf-8")
        sync_to_s3(s3_mock, self.local_state, "test-bucket", "state.json")
        s3_mock.upload_file.assert_called_once_with(
            str(self.local_state), "test-bucket", "state.json"
        )

    @patch("scripts.aws_lambda_handler.boto3")
    @patch("scripts.aws_lambda_handler.run_daily_cycle")
    @patch("scripts.aws_lambda_handler.sync_to_s3")
    @patch("scripts.aws_lambda_handler.sync_from_s3")
    def test_lambda_handler_full_flow(self, mock_from_s3, mock_to_s3, mock_cycle, mock_boto3):
        mock_cycle.return_value = {
            "date": "2026-11-01",
            "equity": 500000.0,
            "cash": 400000.0,
            "active_positions_count": 1,
            "new_trades": ["ATHERENERG"],
            "digest": "All good",
        }

        with patch.dict("os.environ", {"S3_BUCKET_NAME": "test-trading-bucket"}):
            resp = lambda_handler({"source": "aws.events"}, None)
            self.assertEqual(resp["statusCode"], 200)
            self.assertEqual(resp["body"]["new_trades"], ["ATHERENERG"])
            mock_from_s3.assert_called_once()
            mock_cycle.assert_called_once()
            mock_to_s3.assert_called_once()

    def test_cloudformation_template_zip_valid(self):
        import yaml

        template_path = Path(__file__).resolve().parents[2] / "aws" / "template_zip.yaml"
        self.assertTrue(template_path.exists())
        with open(template_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.assertIn("Resources", data)
        self.assertIn("DailySwingTradingFunction", data["Resources"])
        fn = data["Resources"]["DailySwingTradingFunction"]["Properties"]
        self.assertEqual(fn["PackageType"], "Zip")
        self.assertEqual(fn["Runtime"], "python3.11")
        self.assertIn("MarketScheduleRule", data["Resources"])
        self.assertIn("WeeklySectorScheduleRule", data["Resources"])
        self.assertIn("DailyEODScheduleRule", data["Resources"])
        self.assertIn("MonthlyPerformanceScheduleRule", data["Resources"])

    @patch("scripts.aws_lambda_handler.boto3")
    @patch("scripts.weekly_sector_report.run_weekly_sector_routine")
    def test_lambda_handler_weekly_sector_action(self, mock_routine, mock_boto3):
        mock_routine.return_value = {
            "status": "success",
            "leading_sector": "NIFTY IT",
            "contenders_count": 3,
            "telegram_delivered": True,
        }
        with patch.dict("os.environ", {"S3_BUCKET_NAME": "test-trading-bucket"}):
            resp = lambda_handler({"action": "weekly_sector_report"}, None)
            self.assertEqual(resp["statusCode"], 200)
            self.assertEqual(resp["body"]["leading_sector"], "NIFTY IT")
            mock_routine.assert_called_once()

    @patch("scripts.aws_lambda_handler.boto3")
    @patch("scripts.telegram_notifier.TelegramNotifier.notify_eod_digest")
    @patch("scripts.paper_trader.update_market_prices")
    @patch("scripts.aws_lambda_handler.sync_to_s3")
    @patch("scripts.aws_lambda_handler.sync_from_s3")
    def test_lambda_handler_eod_digest_action(
        self, mock_from_s3, mock_to_s3, mock_update, mock_eod_notify, mock_boto3
    ):
        mock_update.return_value = (
            ["Prices updated ok"],
            {
                "portfolio_equity": 528000.0,
                "initial_capital": 500000.0,
                "cash": 10000.0,
                "active_positions": {"STOCKA": {}},
                "closed_trades": [],
            },
        )
        mock_eod_notify.return_value = True

        with patch.dict(
            "os.environ",
            {
                "S3_BUCKET_NAME": "test-trading-bucket",
                "TELEGRAM_BOT_TOKEN": "mock_token",
                "TELEGRAM_CHAT_ID": "12345",
            },
        ):
            resp = lambda_handler({"action": "eod_digest"}, None)
            self.assertEqual(resp["statusCode"], 200)
            self.assertEqual(resp["body"]["action"], "eod_digest")
            self.assertTrue(resp["body"]["telegram_delivered"])
            self.assertEqual(resp["body"]["active_positions_count"], 1)

    @patch("scripts.aws_lambda_handler.boto3")
    @patch("scripts.core_portfolio_weekly.run_core_portfolio_review")
    @patch("scripts.aws_lambda_handler.sync_from_s3")
    def test_lambda_handler_core_portfolio_review_action(
        self, mock_from_s3, mock_review, mock_boto3
    ):
        mock_review.return_value = {
            "status": "success",
            "review": {
                "date": "2026-11-16",
                "portfolio_equity": 500000.0,
                "cash": 500000.0,
                "positions_count": 0,
            },
        }
        with patch.dict("os.environ", {"S3_BUCKET_NAME": "test-trading-bucket"}):
            resp = lambda_handler({"action": "core_portfolio_review"}, None)
            self.assertEqual(resp["statusCode"], 200)
            self.assertEqual(resp["body"]["action"], "core_portfolio_review")
            self.assertFalse(resp["body"]["telegram_delivered"])
            mock_review.assert_called_once_with(
                state_file=Path("/tmp/paper_trading_state.json"),
                output_dir=Path("/tmp/reports"),
                send_telegram=False,
            )

    @patch("scripts.aws_lambda_handler.boto3")
    @patch("scripts.monthly_performance_review.run_monthly_performance_review")
    @patch("scripts.aws_lambda_handler.sync_from_s3")
    def test_lambda_handler_monthly_performance_review_action(
        self, mock_from_s3, mock_monthly, mock_boto3
    ):
        mock_monthly.return_value = {
            "status": "success",
            "review": {
                "month_str": "2026-11",
                "net_pnl": 15000.0,
                "profit_factor": 3.0,
            },
        }
        with patch.dict("os.environ", {"S3_BUCKET_NAME": "test-trading-bucket"}):
            resp = lambda_handler(
                {"action": "monthly_performance_review", "year": 2026, "month": 11},
                None,
            )
            self.assertEqual(resp["statusCode"], 200)
            self.assertEqual(resp["body"]["action"], "monthly_performance_review")
            self.assertFalse(resp["body"]["telegram_delivered"])
            mock_monthly.assert_called_once_with(
                state_file=Path("/tmp/paper_trading_state.json"),
                year=2026,
                month=11,
                output_dir=Path("/tmp/reports"),
                send_telegram=False,
            )


if __name__ == "__main__":
    unittest.main()
