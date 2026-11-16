"""Unit tests for the Telegram trade alert notifier."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from scripts.telegram_notifier import TelegramNotifier


class TestTelegramNotifier(unittest.TestCase):
    def test_is_configured_false_when_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            notifier = TelegramNotifier()
            notifier.bot_token = None
            notifier.chat_id = None
            self.assertFalse(notifier.is_configured)
            self.assertFalse(notifier.notify_buy("INFY", 10, 1500.0, 1450.0))
            self.assertFalse(
                notifier.notify_sell("INFY", 10, 1500.0, 1600.0, 1000.0, 6.67, "TARGET")
            )

    @patch("urllib.request.urlopen")
    def test_notify_buy_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        notifier = TelegramNotifier()
        notifier.bot_token = "mock_token"  # pragma: allowlist secret
        notifier.chat_id = "12345678"

        ok = notifier.notify_buy(
            symbol="ATHERENERG",
            qty=71,
            entry_price=1760.0,
            stop_loss=1690.0,
            target=1900.0,
            total_cost=124960.0,
            cash_remaining=375040.0,
        )
        self.assertTrue(ok)
        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        data = json.loads(req.data.decode("utf-8"))
        self.assertIn("BUY ORDER EXECUTED", data["text"])
        self.assertIn("#ATHERENERG", data["text"])
        self.assertIn("₹1,760.00", data["text"])

    @patch("urllib.request.urlopen")
    def test_notify_sell_target_profit(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        notifier = TelegramNotifier()
        notifier.bot_token = "mock_token"  # pragma: allowlist secret
        notifier.chat_id = "12345678"

        ok = notifier.notify_sell(
            symbol="ATHERENERG",
            qty=71,
            entry_price=1760.0,
            exit_price=1900.0,
            pnl=9940.0,
            pnl_pct=7.95,
            reason="TARGET_REACHED",
            cash_balance=509940.0,
        )
        self.assertTrue(ok)
        req = mock_urlopen.call_args[0][0]
        data = json.loads(req.data.decode("utf-8"))
        self.assertIn("PROFIT EXIT", data["text"])
        self.assertIn("₹+9,940.00", data["text"])

    @patch("urllib.request.urlopen")
    def test_notify_eod_digest_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        notifier = TelegramNotifier()
        notifier.bot_token = "mock_token"  # pragma: allowlist secret
        notifier.chat_id = "12345678"

        mock_positions = {
            "MOTILALOFS": {
                "symbol": "MOTILALOFS",
                "quantity": 88,
                "entry_price": 1160.40,
                "current_price": 1220.00,
                "stop_loss": 1160.40,
                "target": 1253.23,
                "market_value": 107360.00,
                "unrealized_pnl": 5244.80,
                "pnl_pct": 5.14,
                "trailing_breakeven_triggered": True,
            }
        }
        mock_closed = [
            {
                "symbol": "PVRINOX",
                "exit_date": "2026-11-15 15:20:00",
                "exit_price": 1611.20,
                "pnl": 8019.90,
                "pnl_pct": 8.03,
                "exit_reason": "TARGET_REACHED",
            }
        ]

        ok = notifier.notify_eod_digest(
            date_str="2026-11-15",
            portfolio_equity=528684.70,
            initial_capital=500000.0,
            cash=5793.25,
            active_positions=mock_positions,
            closed_trades=mock_closed,
            max_positions=5,
        )
        self.assertTrue(ok)
        req = mock_urlopen.call_args[0][0]
        data = json.loads(req.data.decode("utf-8"))
        self.assertIn("DAILY EOD PORTFOLIO STATUS", data["text"])
        self.assertIn("#MOTILALOFS", data["text"])
        self.assertIn("#PVRINOX", data["text"])
        self.assertIn("Trailing BE", data["text"])
        self.assertIn("TARGET_REACHED", data["text"])


if __name__ == "__main__":
    unittest.main()
