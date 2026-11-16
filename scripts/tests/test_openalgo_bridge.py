"""Unit tests for the OpenAlgo bridge script."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from scripts.openalgo_bridge import (
    check_connection,
    convert_plan_to_openalgo_order,
    fetch_portfolio,
    format_portfolio_markdown,
    get_credentials,
    place_smart_order,
)


class TestOpenAlgoBridge(unittest.TestCase):
    def test_get_credentials_env(self):
        with patch.dict(
            "os.environ",
            {
                "OPENALGO_API_KEY": "test_key",  # pragma: allowlist secret
                "OPENALGO_HOST": "http://localhost:5001",
            },
        ):
            key, host = get_credentials()
            self.assertEqual(key, "test_key")
            self.assertEqual(host, "http://localhost:5001")

    def test_get_credentials_cli_override(self):
        with patch.dict("os.environ", {"OPENALGO_API_KEY": "env_key"}):  # pragma: allowlist secret
            key, host = get_credentials(cli_api_key="cli_key", cli_host="http://custom:5000")
            self.assertEqual(key, "cli_key")
            self.assertEqual(host, "http://custom:5000")

    def test_convert_plan_to_openalgo_order_basic(self):
        plan = {
            "symbol": "TCS",
            "qty": 15,
            "signal_entry": 3800.0,
            "worst_entry": 3810.0,
            "stop_loss": 3720.0,
            "take_profit": 3980.0,
        }
        order = convert_plan_to_openalgo_order(plan, exchange="NSE", product="CNC")
        self.assertEqual(order["symbol"], "TCS")
        self.assertEqual(order["action"], "BUY")
        self.assertEqual(order["exchange"], "NSE")
        self.assertEqual(order["product"], "CNC")
        self.assertEqual(order["quantity"], 15)
        self.assertEqual(order["price_type"], "LIMIT")
        self.assertEqual(order["price"], "3810.0")
        self.assertEqual(order["stoploss"], "3720.0")
        self.assertEqual(order["target"], "3980.0")

    def test_convert_plan_missing_symbol_raises(self):
        plan = {"qty": 10}
        with self.assertRaises(ValueError):
            convert_plan_to_openalgo_order(plan)

    def test_place_smart_order_blocked_without_confirm(self):
        client = MagicMock()
        order = {
            "strategy": "ClaudeTrading",
            "symbol": "INFY",
            "action": "BUY",
            "exchange": "NSE",
            "product": "CNC",
            "quantity": 10,
        }
        res = place_smart_order(client, order, confirm=False)
        self.assertEqual(res["status"], "blocked")
        client.placesmartorder.assert_not_called()

    def test_place_smart_order_executes_with_confirm(self):
        client = MagicMock()
        client.placesmartorder.return_value = {"status": "success", "order_id": "ORD123"}
        order = {
            "strategy": "ClaudeTrading",
            "symbol": "INFY",
            "action": "BUY",
            "exchange": "NSE",
            "product": "CNC",
            "quantity": 10,
            "price_type": "MARKET",
            "position_size": 10,
        }
        res = place_smart_order(client, order, confirm=True)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["order_id"], "ORD123")
        client.placesmartorder.assert_called_once()

    def test_check_connection_success(self):
        client = MagicMock()
        client.funds.return_value = {"status": "success", "data": {"available_cash": 100000}}
        client.positionbook.return_value = {"data": [{"symbol": "INFY"}]}
        client.holdings.return_value = {"data": [{"symbol": "TCS"}, {"symbol": "RELIANCE"}]}

        status = check_connection(client)
        self.assertEqual(status["status"], "connected")
        self.assertTrue(status["broker_connected"])
        self.assertEqual(status["positions_count"], 1)
        self.assertEqual(status["holdings_count"], 2)

    def test_fetch_portfolio_and_format_markdown(self):
        client = MagicMock()
        client.funds.return_value = {"data": {"availablecash": "50000"}}
        client.holdings.return_value = {
            "data": [
                {
                    "symbol": "TATASTEEL",
                    "quantity": 100,
                    "price": 140.0,
                    "current_value": 14500,
                    "pnl": 500,
                }
            ]
        }
        client.positionbook.return_value = {"data": []}

        portfolio = fetch_portfolio(client)
        md = format_portfolio_markdown(portfolio)
        self.assertIn("TATASTEEL", md)
        self.assertIn("Demat Holdings (1)", md)
        self.assertIn("No active intraday/F&O positions", md)


if __name__ == "__main__":
    unittest.main()
