#!/usr/bin/env python3
"""
OpenAlgo Integration Bridge for Claude Trading Skills.

Connects Claude Trading Skills workflows (trade planning, position sizing,
and portfolio review) to the OpenAlgo execution layer and multi-broker gateway.

Safety & Governance:
    In alignment with the repository's 'first for self, open for others' and
    disciplined trading philosophy, this bridge implements human-in-the-loop
    confirmation gates. Unattended execution without explicit confirmation
    (--confirm) is blocked by design.

Usage:
    # Test connection and check funds/broker status
    python3 scripts/openalgo_bridge.py check-connection

    # Fetch holdings and positions
    python3 scripts/openalgo_bridge.py portfolio --format markdown

    # Convert a trade plan JSON to OpenAlgo SmartOrder format
    python3 scripts/openalgo_bridge.py convert-plan --plan trade_plan.json --exchange NSE --product CNC

    # Place an order (requires --confirm)
    python3 scripts/openalgo_bridge.py place-order --symbol INFY --action BUY --exchange NSE --qty 10 --price-type LIMIT --price 1500.0 --confirm
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


def get_credentials(
    cli_api_key: str | None = None,
    cli_host: str | None = None,
) -> tuple[str, str]:
    """Retrieve OpenAlgo credentials from CLI args or environment variables."""
    api_key = cli_api_key or os.environ.get("OPENALGO_API_KEY", "").strip()
    host = cli_host or os.environ.get("OPENALGO_HOST", "http://127.0.0.1:5000").strip()

    return api_key, host


def get_client(api_key: str, host: str):
    """Instantiate and return the OpenAlgo API client."""
    if not api_key:
        raise ValueError(
            "OpenAlgo API key is missing. Set OPENALGO_API_KEY environment variable "
            "or pass --api-key <key>."
        )

    try:
        from openalgo import api
    except ImportError as exc:
        raise ImportError(
            "The 'openalgo' package is not installed in the current environment.\n"
            "Install it using: uv pip install openalgo"
        ) from exc

    return api(api_key=api_key, host=host)


def check_connection(client) -> dict[str, Any]:
    """Verify connectivity to the OpenAlgo instance and inspect broker status."""
    result: dict[str, Any] = {
        "status": "error",
        "host": getattr(client, "host", "unknown"),
        "broker_connected": False,
        "funds": None,
        "positions_count": 0,
        "holdings_count": 0,
        "messages": [],
    }

    try:
        funds_resp = client.funds()
        result["funds"] = funds_resp
        if isinstance(funds_resp, dict) and funds_resp.get("status") == "success":
            result["broker_connected"] = True
            result["status"] = "connected"
        elif isinstance(funds_resp, dict) and funds_resp.get("error"):
            result["messages"].append(f"Funds error: {funds_resp.get('error')}")
    except Exception as e:
        result["messages"].append(f"Failed to fetch funds: {e}")

    try:
        pos_resp = client.positionbook()
        if isinstance(pos_resp, dict) and "data" in pos_resp:
            positions = pos_resp.get("data", [])
            result["positions_count"] = len(positions) if isinstance(positions, list) else 0
    except Exception as e:
        result["messages"].append(f"Failed to fetch positions: {e}")

    try:
        holdings_resp = client.holdings()
        if isinstance(holdings_resp, dict) and "data" in holdings_resp:
            holdings = holdings_resp.get("data", [])
            result["holdings_count"] = len(holdings) if isinstance(holdings, list) else 0
    except Exception as e:
        result["messages"].append(f"Failed to fetch holdings: {e}")

    return result


def fetch_portfolio(client) -> dict[str, Any]:
    """Fetch live holdings and positions from the broker via OpenAlgo."""
    holdings_resp = client.holdings()
    positions_resp = client.positionbook()
    funds_resp = client.funds()

    return {
        "funds": funds_resp,
        "holdings": holdings_resp.get("data", []) if isinstance(holdings_resp, dict) else [],
        "positions": positions_resp.get("data", []) if isinstance(positions_resp, dict) else [],
    }


def convert_plan_to_openalgo_order(
    plan: dict[str, Any],
    exchange: str = "NSE",
    product: str = "CNC",
    strategy: str = "ClaudeTrading",
) -> dict[str, Any]:
    """
    Convert a trade plan (from breakout-trade-planner or position-sizer)
    into an OpenAlgo SmartOrder payload.
    """
    symbol = plan.get("symbol") or plan.get("ticker")
    if not symbol:
        raise ValueError("Trade plan must specify 'symbol' or 'ticker'.")

    # Quantities and sizing
    qty = int(plan.get("qty") or plan.get("quantity") or plan.get("shares") or 1)
    action = (plan.get("side") or plan.get("action") or "BUY").upper()

    order: dict[str, Any] = {
        "strategy": strategy,
        "symbol": symbol.upper(),
        "action": action,
        "exchange": exchange.upper(),
        "product": product.upper(),
        "quantity": qty,
        "position_size": qty if action == "BUY" else 0,
    }

    # Price levels
    entry = plan.get("signal_entry") or plan.get("entry_price") or plan.get("price")
    limit_entry = plan.get("worst_entry") or plan.get("limit_price")
    stop_loss = plan.get("stop_loss") or plan.get("stop_price")
    take_profit = plan.get("take_profit") or plan.get("target")

    if limit_entry or entry:
        order["price_type"] = "LIMIT"
        order["price"] = str(limit_entry or entry)
    else:
        order["price_type"] = "MARKET"

    if stop_loss:
        order["stoploss"] = str(stop_loss)

    if take_profit:
        order["target"] = str(take_profit)

    return order


def place_smart_order(
    client,
    order_payload: dict[str, Any],
    confirm: bool = False,
) -> dict[str, Any]:
    """
    Place a smart order through OpenAlgo with strict confirmation enforcement.
    """
    if not confirm:
        return {
            "status": "blocked",
            "message": "Order blocked by Pre-Trade Discipline Gate: explicit confirmation (--confirm) required.",
            "dry_run_payload": order_payload,
        }

    # Extract kwargs
    kwargs = {
        k: v
        for k, v in order_payload.items()
        if k
        not in (
            "strategy",
            "symbol",
            "action",
            "exchange",
            "price_type",
            "product",
            "quantity",
            "position_size",
        )
    }

    response = client.placesmartorder(
        strategy=order_payload.get("strategy", "ClaudeTrading"),
        symbol=order_payload["symbol"],
        action=order_payload["action"],
        exchange=order_payload["exchange"],
        price_type=order_payload.get("price_type", "MARKET"),
        product=order_payload.get("product", "CNC"),
        quantity=order_payload.get("quantity", 1),
        position_size=order_payload.get("position_size", 1),
        **kwargs,
    )
    return response


def format_portfolio_markdown(portfolio_data: dict[str, Any]) -> str:
    """Format portfolio holdings and positions into a clean Markdown table."""
    lines = ["# OpenAlgo Broker Portfolio Snapshot\n"]

    # Funds
    funds = portfolio_data.get("funds", {})
    if isinstance(funds, dict) and "data" in funds:
        lines.append("## Available Capital / Margins")
        lines.append(f"```json\n{json.dumps(funds['data'], indent=2)}\n```\n")

    # Holdings
    holdings = portfolio_data.get("holdings", [])
    lines.append(f"## Demat Holdings ({len(holdings)})")
    if holdings:
        lines.append("| Symbol | Qty | Avg Price | Current Value | PnL |")
        lines.append("|---|---|---|---|---|")
        for h in holdings:
            sym = h.get("symbol", "N/A")
            qty = h.get("quantity", h.get("holdings_qty", 0))
            avg = h.get("price", h.get("average_price", 0.0))
            val = h.get("current_value", "N/A")
            pnl = h.get("pnl", "N/A")
            lines.append(f"| {sym} | {qty} | {avg} | {val} | {pnl} |")
    else:
        lines.append("*No open holdings found.*")

    lines.append("")

    # Positions
    positions = portfolio_data.get("positions", [])
    lines.append(f"## Open Derivatives / Intraday Positions ({len(positions)})")
    if positions:
        lines.append("| Symbol | Product | Net Qty | Buy Avg | Sell Avg | Realized PnL |")
        lines.append("|---|---|---|---|---|---|")
        for p in positions:
            sym = p.get("symbol", "N/A")
            prod = p.get("product", "MIS")
            qty = p.get("net_qty", p.get("quantity", 0))
            b_avg = p.get("buy_avg", "0.0")
            s_avg = p.get("sell_avg", "0.0")
            rpnl = p.get("realized_pnl", p.get("pnl", "0.0"))
            lines.append(f"| {sym} | {prod} | {qty} | {b_avg} | {s_avg} | {rpnl} |")
    else:
        lines.append("*No active intraday/F&O positions.*")

    return "\n".join(lines)


def parse_args():
    parser = argparse.ArgumentParser(
        description="OpenAlgo Execution Bridge for Claude Trading Skills."
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="OpenAlgo API key (or set OPENALGO_API_KEY env var)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="OpenAlgo Host URL (default: http://127.0.0.1:5000 or OPENALGO_HOST env var)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: check-connection
    subparsers.add_parser("check-connection", help="Test connection to OpenAlgo host")

    # Subcommand: portfolio
    port_parser = subparsers.add_parser("portfolio", help="Fetch broker holdings and positions")
    port_parser.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="json",
        help="Output format (json or markdown)",
    )
    port_parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Optional file path to write the output",
    )

    # Subcommand: convert-plan
    conv_parser = subparsers.add_parser(
        "convert-plan", help="Convert trade plan JSON to OpenAlgo SmartOrder"
    )
    conv_parser.add_argument("--plan", type=str, required=True, help="Path to trade plan JSON")
    conv_parser.add_argument(
        "--exchange", type=str, default="NSE", help="Exchange code (e.g. NSE, BSE, NFO)"
    )
    conv_parser.add_argument(
        "--product", type=str, default="CNC", help="Product type (CNC, MIS, NRML)"
    )
    conv_parser.add_argument(
        "--strategy", type=str, default="ClaudeTrading", help="Strategy tag name"
    )

    # Subcommand: place-order
    order_parser = subparsers.add_parser("place-order", help="Place order via OpenAlgo SmartOrder")
    order_parser.add_argument(
        "--symbol", type=str, required=True, help="Trading symbol (e.g. INFY, RELIANCE)"
    )
    order_parser.add_argument(
        "--action", type=str, required=True, choices=["BUY", "SELL"], help="Order action"
    )
    order_parser.add_argument(
        "--exchange", type=str, default="NSE", help="Exchange code (NSE, BSE, NFO, MCX)"
    )
    order_parser.add_argument(
        "--product", type=str, default="CNC", help="Product type (CNC, MIS, NRML)"
    )
    order_parser.add_argument(
        "--price-type",
        type=str,
        default="LIMIT",
        choices=["MARKET", "LIMIT", "SL", "SL-M"],
        help="Order type",
    )
    order_parser.add_argument("--qty", type=int, default=1, help="Order quantity")
    order_parser.add_argument("--price", type=float, default=None, help="Limit price")
    order_parser.add_argument("--stoploss", type=float, default=None, help="Stop loss price")
    order_parser.add_argument("--target", type=float, default=None, help="Target price")
    order_parser.add_argument(
        "--confirm", action="store_true", help="Explicit human confirmation to place order"
    )

    return parser.parse_args()


def main():
    args = parse_args()
    api_key, host = get_credentials(args.api_key, args.host)

    if args.command == "convert-plan":
        # Offline plan conversion doesn't require live API credentials
        try:
            with open(args.plan, encoding="utf-8") as f:
                plan_data = json.load(f)
        except Exception as e:
            print(f"Error reading plan file '{args.plan}': {e}", file=sys.stderr)
            sys.exit(1)

        payload = convert_plan_to_openalgo_order(
            plan=plan_data,
            exchange=args.exchange,
            product=args.product,
            strategy=args.strategy,
        )
        print(json.dumps(payload, indent=2))
        return

    # Commands below require the client
    if not api_key:
        print(
            "ERROR: OpenAlgo API key not found.\n"
            "Set OPENALGO_API_KEY environment variable or pass --api-key.\n"
            "Example: export OPENALGO_API_KEY='your_openalgo_api_key'",  # pragma: allowlist secret
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        client = get_client(api_key, host)
    except Exception as e:
        print(f"Error initializing OpenAlgo client: {e}", file=sys.stderr)
        sys.exit(1)

    if args.command == "check-connection":
        print(f"Connecting to OpenAlgo at {host}...")
        status = check_connection(client)
        print(json.dumps(status, indent=2))

    elif args.command == "portfolio":
        portfolio_data = fetch_portfolio(client)
        if args.format == "markdown":
            formatted = format_portfolio_markdown(portfolio_data)
        else:
            formatted = json.dumps(portfolio_data, indent=2)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(formatted)
            print(f"Portfolio saved to {args.output}")
        else:
            print(formatted)

    elif args.command == "place-order":
        payload = {
            "strategy": "ClaudeTrading",
            "symbol": args.symbol.upper(),
            "action": args.action.upper(),
            "exchange": args.exchange.upper(),
            "product": args.product.upper(),
            "price_type": args.price_type.upper(),
            "quantity": args.qty,
            "position_size": args.qty if args.action.upper() == "BUY" else 0,
        }
        if args.price is not None:
            payload["price"] = str(args.price)
        if args.stoploss is not None:
            payload["stoploss"] = str(args.stoploss)
        if args.target is not None:
            payload["target"] = str(args.target)

        result = place_smart_order(client, payload, confirm=args.confirm)
        print(json.dumps(result, indent=2))
        if not args.confirm:
            print(
                "\n[SAFETY NOTICE]: Order was NOT submitted to the broker because --confirm was not specified.\n"
                "Review the order parameters above and re-run with --confirm to execute.",
                file=sys.stderr,
            )


if __name__ == "__main__":
    main()
