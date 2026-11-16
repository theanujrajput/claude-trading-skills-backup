#!/usr/bin/env python3
"""
JSON-Based Local Paper Trading Engine for Claude Trading Skills.

Adopts the lightweight JSON state management pattern (from trade-bot / algo-trade-bot)
to simulate swing trading on NSE / Indian equities without requiring OpenAlgo,
broker credentials, or external servers.

Features:
- State persistence in state/paper_trading_state.json
- Trade entry with cash balance verification and sizing
- Mark-to-market portfolio updates with live closing prices
- Automated Stop-Loss and Target hit detection
- Full closed trade ledger and realized P&L tracking
- Exportable Markdown & JSON portfolio summaries

Usage:
    # Initialize paper trading account with ₹5,00,000 capital
    python3 scripts/paper_trader.py init --capital 500000

    # Enter a trade (e.g. ATHERENERG from position-sizer plan)
    python3 scripts/paper_trader.py buy --symbol ATHERENERG --qty 71 --entry 1760.0 --stop 1690.0 --target 1900.0

    # View portfolio status
    python3 scripts/paper_trader.py status

    # Update open positions with latest closing prices & check stops/targets
    python3 scripts/paper_trader.py update

    # Close an active position manually
    python3 scripts/paper_trader.py close --symbol ATHERENERG --price 1850.0 --reason "DISCIPLINED_EXIT"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_STATE_FILE = ROOT_DIR / "state" / "paper_trading_state.json"


def load_state(state_file: Path = DEFAULT_STATE_FILE) -> dict[str, Any]:
    """Load paper trading state from JSON file or return default."""
    if state_file.exists():
        try:
            with open(state_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(
                f"Warning: Could not read {state_file} ({e}), initializing fresh state.",
                file=sys.stderr,
            )

    return {
        "initial_capital": 500000.0,
        "cash": 500000.0,
        "portfolio_equity": 500000.0,
        "active_positions": {},
        "closed_trades": [],
        "last_updated": datetime.today().strftime("%Y-%m-%d %H:%M:%S"),
    }


def save_state(state: dict[str, Any], state_file: Path = DEFAULT_STATE_FILE) -> None:
    """Save paper trading state to JSON file."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state["last_updated"] = datetime.today().strftime("%Y-%m-%d %H:%M:%S")
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=4)


def init_account(capital: float, state_file: Path = DEFAULT_STATE_FILE) -> dict[str, Any]:
    """Initialize or reset account with specified capital."""
    state = {
        "initial_capital": float(capital),
        "cash": float(capital),
        "portfolio_equity": float(capital),
        "active_positions": {},
        "closed_trades": [],
        "last_updated": datetime.today().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_state(state, state_file)
    return state


def enter_position(
    symbol: str,
    qty: int,
    entry_price: float,
    stop_loss: float,
    target: float | None = None,
    notes: str = "",
    state_file: Path = DEFAULT_STATE_FILE,
) -> tuple[bool, str, dict[str, Any]]:
    """Enter a new paper trade position."""
    state = load_state(state_file)
    symbol = symbol.upper().replace(".NS", "")
    cost = qty * entry_price

    if cost > state["cash"]:
        msg = f"Insufficient cash (Required: ₹{cost:,.2f}, Available: ₹{state['cash']:,.2f})"
        return False, msg, state

    if symbol in state["active_positions"]:
        msg = f"Position in {symbol} already open. Use 'close' or separate ledger to modify."
        return False, msg, state

    state["cash"] -= cost
    now_str = datetime.today().strftime("%Y-%m-%d %H:%M:%S")

    position = {
        "symbol": symbol,
        "entry_date": now_str,
        "entry_price": float(entry_price),
        "quantity": int(qty),
        "stop_loss": float(stop_loss),
        "initial_stop_loss": float(stop_loss),
        "target": float(target) if target else None,
        "current_price": float(entry_price),
        "highest_price": float(entry_price),
        "market_value": round(cost, 2),
        "unrealized_pnl": 0.0,
        "pnl_pct": 0.0,
        "trailing_breakeven_triggered": False,
        "profit_lock_triggered": False,
        "partial_target_hit": False,
        "is_runner": False,
        "notes": notes,
    }

    state["active_positions"][symbol] = position

    # Recalculate portfolio equity
    total_pos_value = sum(p["market_value"] for p in state["active_positions"].values())
    state["portfolio_equity"] = round(state["cash"] + total_pos_value, 2)

    save_state(state, state_file)
    msg = f"Bought {qty} shares of {symbol} @ ₹{entry_price:,.2f} (Total: ₹{cost:,.2f}, Remaining Cash: ₹{state['cash']:,.2f})"

    # Send Telegram notification if configured (Buy action only)
    try:
        from scripts.telegram_notifier import TelegramNotifier

        notifier = TelegramNotifier()
        if notifier.is_configured:
            notifier.notify_buy(
                symbol=symbol,
                qty=qty,
                entry_price=entry_price,
                stop_loss=stop_loss,
                target=target,
                total_cost=cost,
                cash_remaining=state["cash"],
                notes=notes,
            )
    except Exception as e:
        print(f"Warning: Failed to dispatch Telegram buy notification: {e}", file=sys.stderr)

    return True, msg, state


def close_position(
    symbol: str,
    exit_price: float,
    qty_to_close: int | None = None,
    reason: str = "MANUAL_EXIT",
    state_file: Path = DEFAULT_STATE_FILE,
    state: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Close an active position (full or partial) and record realized P&L."""
    if state is None:
        state = load_state(state_file)
    symbol = symbol.upper().replace(".NS", "")

    if symbol not in state["active_positions"]:
        return False, f"No active position found for {symbol}.", state

    pos = state["active_positions"][symbol]
    total_qty = pos["quantity"]
    qty = qty_to_close if qty_to_close is not None and 0 < qty_to_close < total_qty else total_qty
    is_partial = qty < total_qty

    entry_price = pos["entry_price"]
    gross_proceeds = qty * exit_price
    cost = qty * entry_price
    pnl = gross_proceeds - cost
    pnl_pct = (pnl / cost) * 100.0 if cost > 0 else 0.0

    state["cash"] += gross_proceeds

    closed_trade = {
        "symbol": symbol,
        "entry_date": pos["entry_date"],
        "exit_date": datetime.today().strftime("%Y-%m-%d %H:%M:%S"),
        "entry_price": entry_price,
        "exit_price": float(exit_price),
        "quantity": qty,
        "cost": round(cost, 2),
        "proceeds": round(gross_proceeds, 2),
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "exit_reason": reason,
        "initial_stop": pos.get("initial_stop_loss", pos.get("stop_loss")),
        "initial_target": pos.get("target"),
        "is_partial": is_partial,
    }

    # Trade Memory Loop: evaluate immediate postmortem
    try:
        from scripts.trade_memory_loop import evaluate_trade_postmortem

        closed_trade["postmortem"] = evaluate_trade_postmortem(closed_trade)
    except Exception as e:
        print(f"Warning: Failed to generate trade postmortem: {e}", file=sys.stderr)
        closed_trade["postmortem"] = None

    state["closed_trades"].append(closed_trade)

    if is_partial:
        pos["quantity"] -= qty
        pos["market_value"] = round(pos["quantity"] * float(exit_price), 2)
        pos["partial_target_hit"] = True
        pos["is_runner"] = True
        msg = (
            f"Partial Profit Booked: {qty}/{total_qty} shares of {symbol} @ ₹{exit_price:,.2f} | "
            f"P&L: ₹{pnl:,.2f} ({pnl_pct:+.2f}%) [{reason}] | Runner: {pos['quantity']} shares"
        )
    else:
        state["active_positions"].pop(symbol)
        msg = (
            f"Closed {symbol} @ ₹{exit_price:,.2f} | P&L: ₹{pnl:,.2f} ({pnl_pct:+.2f}%) "
            f"[{reason}] | New Cash: ₹{state['cash']:,.2f}"
        )

    total_pos_value = sum(p["market_value"] for p in state["active_positions"].values())
    state["portfolio_equity"] = round(state["cash"] + total_pos_value, 2)

    save_state(state, state_file)

    # Send Telegram notification if configured (Sell/Exit action only)
    try:
        from scripts.telegram_notifier import TelegramNotifier

        notifier = TelegramNotifier()
        if notifier.is_configured:
            notifier.notify_sell(
                symbol=symbol,
                qty=qty,
                entry_price=entry_price,
                exit_price=exit_price,
                pnl=pnl,
                pnl_pct=pnl_pct,
                reason=reason,
                cash_balance=state["cash"],
                postmortem=closed_trade.get("postmortem"),
            )
    except Exception as e:
        print(f"Warning: Failed to dispatch Telegram sell notification: {e}", file=sys.stderr)

    return True, msg, state


def update_market_prices(
    state_file: Path = DEFAULT_STATE_FILE,
    auto_trigger_stops: bool = True,
) -> tuple[list[str], dict[str, Any]]:
    """Fetch live closing prices via yfinance, update MTM, and evaluate stops/targets."""
    import yfinance as yf

    state = load_state(state_file)
    positions = state["active_positions"]
    events = []

    if not positions:
        return ["No active positions to update."], state

    symbols = list(positions.keys())
    yf_tickers = [f"{s}.NS" for s in symbols]

    try:
        df = yf.download(yf_tickers, period="5d", progress=False)

        for sym in list(state["active_positions"].keys()):
            yf_sym = f"{sym}.NS"
            pos = state["active_positions"].get(sym)
            if not pos:
                continue
            try:
                if yf_sym in df["Close"]:
                    series = df["Close"][yf_sym].dropna()
                elif hasattr(df["Close"], "squeeze"):
                    series = df["Close"].squeeze().dropna()
                else:
                    series = df["Close"].dropna()

                if series.empty:
                    continue

                val = series.iloc[-1]
                if hasattr(val, "item"):
                    latest_close = float(val.item())
                elif hasattr(val, "iloc"):
                    latest_close = float(val.iloc[0])
                else:
                    latest_close = float(val)

                pos["current_price"] = round(latest_close, 2)
                pos["highest_price"] = max(
                    pos.get("highest_price", pos["entry_price"]), latest_close
                )
                pos["market_value"] = round(pos["quantity"] * latest_close, 2)
                cost = pos["quantity"] * pos["entry_price"]
                pnl = pos["market_value"] - cost
                pos["unrealized_pnl"] = round(pnl, 2)
                pos["pnl_pct"] = round((pnl / cost) * 100.0 if cost > 0 else 0.0, 2)

                # 1. Trailing Stop to Break-Even at +4% gain
                if pos.get("entry_price") and pos["pnl_pct"] >= 4.0:
                    entry_p = pos["entry_price"]
                    current_sl = pos.get("stop_loss", 0.0)
                    if current_sl < entry_p:
                        pos["stop_loss"] = entry_p
                        pos["trailing_breakeven_triggered"] = True
                        events.append(
                            f"🛡️ Trailing Stop moved to Break-Even for {sym}: "
                            f"New Stop Loss = ₹{entry_p:,.2f} (Gain reached {pos['pnl_pct']:+.2f}%)"
                        )

                # 2. Stage 2: Profit Lock Ladder at +6% gain -> Lock in +3% profit
                if pos.get("entry_price") and pos["pnl_pct"] >= 6.0:
                    lock_stop = round(pos["entry_price"] * 1.03, 2)
                    current_sl = pos.get("stop_loss", 0.0)
                    if current_sl < lock_stop:
                        pos["stop_loss"] = lock_stop
                        pos["profit_lock_triggered"] = True
                        events.append(
                            f"🔒 Profit Lock Ladder Activated for {sym}: "
                            f"Stop Loss raised to ₹{lock_stop:,.2f} (+3.0% profit locked on {pos['pnl_pct']:+.2f}% gain)"
                        )

                # 3. Hybrid Profit Booking at +8% Target: Book 50%, trail remaining 50%
                if (
                    auto_trigger_stops
                    and pos.get("target")
                    and latest_close >= pos["target"]
                    and not pos.get("partial_target_hit", False)
                ):
                    if pos["quantity"] > 1:
                        qty_to_book = max(1, pos["quantity"] // 2)
                        _, close_msg, state = close_position(
                            symbol=sym,
                            exit_price=latest_close,
                            qty_to_close=qty_to_book,
                            reason="PARTIAL_TARGET_50PCT",
                            state_file=state_file,
                            state=state,
                        )
                        events.append(f"🎯 {close_msg}")
                        # Re-reference active position and configure runner
                        pos = state["active_positions"][sym]
                        pos["partial_target_hit"] = True
                        pos["is_runner"] = True
                        pos["highest_price"] = max(
                            pos.get("highest_price", pos["entry_price"]), latest_close
                        )
                        # Initial trailing stop: 4% below peak (locks in profit!)
                        pos["stop_loss"] = round(pos["highest_price"] * 0.96, 2)
                        save_state(state, state_file)
                        events.append(
                            f"🏃 Runner Active for {sym}: Remaining {pos['quantity']} shares with Trailing Stop at ₹{pos['stop_loss']:,.2f}"
                        )
                    else:
                        # Only 1 share, cannot split, close in full
                        _, close_msg, state = close_position(
                            symbol=sym,
                            exit_price=latest_close,
                            reason="TARGET_REACHED",
                            state_file=state_file,
                            state=state,
                        )
                        events.append(f"🟢 {close_msg}")
                        continue

                # 4. Progressive Trailing Stop for Active Runner: ratchet stop upward with new highs
                if pos.get("is_runner"):
                    candidate_stop = round(pos["highest_price"] * 0.96, 2)
                    current_sl = pos.get("stop_loss", 0.0)
                    if candidate_stop > current_sl:
                        pos["stop_loss"] = candidate_stop
                        events.append(
                            f"📈 Runner Trailing Stop Ratcheted Up for {sym}: "
                            f"₹{current_sl:,.2f} → ₹{candidate_stop:,.2f} (Peak: ₹{pos['highest_price']:,.2f})"
                        )

                # 5. Check Stop Loss / Trailing Stop Trigger
                if auto_trigger_stops and pos.get("stop_loss") and latest_close <= pos["stop_loss"]:
                    if pos.get("is_runner"):
                        reason = "TRAILING_STOP_TRIGGERED"
                    elif pos.get("profit_lock_triggered"):
                        reason = "PROFIT_LOCK_STOP_TRIGGERED"
                    elif pos.get("trailing_breakeven_triggered"):
                        reason = "BREAKEVEN_STOP_TRIGGERED"
                    else:
                        reason = "STOP_LOSS_TRIGGERED"

                    _, close_msg, state = close_position(
                        symbol=sym,
                        exit_price=latest_close,
                        reason=reason,
                        state_file=state_file,
                        state=state,
                    )
                    events.append(f"🔴 {close_msg}")
                    continue

                events.append(
                    f"Updated {sym}: ₹{latest_close:,.2f} | Unrealized P&L: ₹{pos['unrealized_pnl']:,.2f} ({pos['pnl_pct']:+.2f}%)"
                )
            except Exception as e:
                events.append(f"Failed to update {sym}: {e}")

    except Exception as e:
        events.append(f"Price update error: {e}")

    total_pos_value = sum(p["market_value"] for p in state["active_positions"].values())
    state["portfolio_equity"] = round(state["cash"] + total_pos_value, 2)
    save_state(state, state_file)

    return events, state


def format_status_markdown(state: dict[str, Any]) -> str:
    """Format full portfolio status into clean markdown."""
    initial = state.get("initial_capital", 500000.0)
    cash = state.get("cash", initial)
    equity = state.get("portfolio_equity", initial)
    total_pnl = equity - initial
    total_pnl_pct = (total_pnl / initial) * 100.0 if initial > 0 else 0.0

    lines = [
        "# Paper Trading Portfolio Status",
        f"**Last Updated:** {state.get('last_updated', 'N/A')}\n",
        "## Account Summary",
        "| Initial Capital | Cash Balance | Total Portfolio Equity | Total Return (₹) | Total Return (%) |",
        "|---|---|---|---|---|",
        f"| ₹{initial:,.2f} | ₹{cash:,.2f} | ₹{equity:,.2f} | ₹{total_pnl:+,.2f} | {total_pnl_pct:+.2f}% |\n",
    ]

    # Active Positions
    active = state.get("active_positions", {})
    lines.append(f"## Open Positions ({len(active)})")
    if active:
        lines.append(
            "| Symbol | Qty | Entry Price | Current Price | Stop Loss | Target | Value | Unrealized P&L |"
        )
        lines.append("|---|---|---|---|---|---|---|---|")
        for sym, p in active.items():
            tgt_str = f"₹{p['target']:,.2f}" if p.get("target") else "—"
            stop_str = f"₹{p['stop_loss']:,.2f}" if p.get("stop_loss") else "—"
            qty = p.get("quantity", 0)
            entry_p = p.get("entry_price", 0.0)
            curr_p = p.get("current_price", entry_p)
            val = p.get("market_value", qty * curr_p)
            unreal_pnl = p.get("unrealized_pnl", 0.0)
            pnl_p = p.get("pnl_pct", 0.0)

            badge = ""
            if p.get("is_runner"):
                badge = " 🏃 (Runner)"
                tgt_str = "Trailing"
            elif p.get("profit_lock_triggered"):
                badge = " 🔒 (+3% Lock)"
            elif p.get("trailing_breakeven_triggered"):
                badge = " 🛡️ (BE)"

            lines.append(
                f"| **{sym}**{badge} | {qty} | ₹{entry_p:,.2f} | ₹{curr_p:,.2f} | "
                f"{stop_str} | {tgt_str} | ₹{val:,.2f} | ₹{unreal_pnl:+,.2f} ({pnl_p:+.2f}%) |"
            )
    else:
        lines.append("*No open positions.*")

    lines.append("")

    # Closed Trades
    closed = state.get("closed_trades", [])
    lines.append(f"## Closed Trades Ledger ({len(closed)})")
    if closed:
        wins = sum(1 for c in closed if c["pnl"] > 0)
        win_rate = (wins / len(closed)) * 100.0 if closed else 0.0
        total_realized = sum(c["pnl"] for c in closed)
        lines.append(
            f"**Win Rate:** {win_rate:.1f}% ({wins}/{len(closed)}) | **Realized P&L:** ₹{total_realized:+,.2f}\n"
        )
        lines.append(
            "| Symbol | Entry Date | Exit Date | Entry | Exit | Qty | Realized P&L | Reason |"
        )
        lines.append("|---|---|---|---|---|---|---|---|")
        for c in reversed(closed[-10:]):  # Show latest 10
            lines.append(
                f"| **{c['symbol']}** | {c['entry_date'][:10]} | {c['exit_date'][:10]} | ₹{c['entry_price']:,.2f} | "
                f"₹{c['exit_price']:,.2f} | {c['quantity']} | ₹{c['pnl']:+,.2f} ({c['pnl_pct']:+.2f}%) | `{c['exit_reason']}` |"
            )
    else:
        lines.append("*No closed trades recorded yet.*")

    return "\n".join(lines)


def parse_args():
    parser = argparse.ArgumentParser(
        description="JSON-based Paper Trading Engine for Claude Trading Skills."
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_STATE_FILE,
        help="Path to paper trading state JSON file",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: init
    init_parser = subparsers.add_parser("init", help="Initialize or reset account")
    init_parser.add_argument("--capital", type=float, default=500000.0, help="Initial cash in ₹")

    # Subcommand: buy
    buy_parser = subparsers.add_parser("buy", help="Enter a paper trade position")
    buy_parser.add_argument(
        "--symbol", type=str, required=True, help="Stock ticker (e.g. ATHERENERG)"
    )
    buy_parser.add_argument("--qty", type=int, required=True, help="Number of shares")
    buy_parser.add_argument("--entry", type=float, required=True, help="Execution entry price in ₹")
    buy_parser.add_argument("--stop", type=float, required=True, help="Stop loss level in ₹")
    buy_parser.add_argument("--target", type=float, default=None, help="Target price in ₹")
    buy_parser.add_argument("--notes", type=str, default="", help="Trade notes / rationale")

    # Subcommand: status
    status_parser = subparsers.add_parser("status", help="View current portfolio status")
    status_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")

    # Subcommand: update
    update_parser = subparsers.add_parser("update", help="Update closing prices and check stops")
    update_parser.add_argument(
        "--no-auto-stops", action="store_true", help="Do not auto-close positions on stop/target"
    )

    # Subcommand: close
    close_parser = subparsers.add_parser("close", help="Close an active position manually")
    close_parser.add_argument("--symbol", type=str, required=True, help="Stock ticker to exit")
    close_parser.add_argument("--price", type=float, required=True, help="Exit price in ₹")
    close_parser.add_argument("--reason", type=str, default="MANUAL_EXIT", help="Reason for exit")

    return parser.parse_args()


def main():
    args = parse_args()

    if args.command == "init":
        state = init_account(args.capital, args.state_file)
        print(f"Initialized paper trading account with ₹{args.capital:,.2f} at {args.state_file}")

    elif args.command == "buy":
        ok, msg, _ = enter_position(
            symbol=args.symbol,
            qty=args.qty,
            entry_price=args.entry,
            stop_loss=args.stop,
            target=args.target,
            notes=args.notes,
            state_file=args.state_file,
        )
        print(msg)
        if not ok:
            sys.exit(1)

    elif args.command == "status":
        state = load_state(args.state_file)
        if args.format == "json":
            print(json.dumps(state, indent=4))
        else:
            print(format_status_markdown(state))

    elif args.command == "update":
        print("Fetching latest closing prices and evaluating Stop/Target triggers...")
        events, _ = update_market_prices(
            state_file=args.state_file,
            auto_trigger_stops=not args.no_auto_stops,
        )
        for ev in events:
            print(ev)

    elif args.command == "close":
        ok, msg, _ = close_position(
            symbol=args.symbol,
            exit_price=args.price,
            reason=args.reason,
            state_file=args.state_file,
        )
        print(msg)
        if not ok:
            sys.exit(1)


if __name__ == "__main__":
    main()
