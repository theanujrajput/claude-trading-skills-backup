#!/usr/bin/env python3
"""
Trade Memory Loop for Claude Trading Skills.

Executes automated postmortems and lessons-learned logging on closed trades.
Triggered immediately whenever a trade is closed (profit target, stop-loss,
trailing break-even, or manual exit).

Evaluates:
1. R-Multiple achieved vs initial planned risk
2. Holding period duration
3. Root-cause classification (Thesis Quality, Execution, Regime, or Noise)
4. Actionable lesson/takeaway to prevent error repetition
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_STATE_FILE = ROOT_DIR / "state" / "paper_trading_state.json"
IST = ZoneInfo("Asia/Kolkata")


def evaluate_trade_postmortem(trade: dict[str, Any]) -> dict[str, Any]:
    """
    Perform root-cause analysis and calculate institutional postmortem metrics on a closed trade.
    """
    symbol = trade.get("symbol", "UNKNOWN").upper().replace(".NS", "")
    entry_price = float(trade.get("entry_price", 0.0))
    exit_price = float(trade.get("exit_price", entry_price))
    quantity = int(trade.get("quantity", 0))
    pnl = float(trade.get("pnl", (exit_price - entry_price) * quantity))
    pnl_pct = float(
        trade.get(
            "pnl_pct",
            ((exit_price - entry_price) / entry_price * 100.0) if entry_price > 0 else 0.0,
        )
    )
    exit_reason = str(trade.get("exit_reason", "MANUAL_EXIT")).upper()

    initial_stop = trade.get("initial_stop") or trade.get("stop_loss")
    if initial_stop:
        initial_risk_per_share = abs(entry_price - float(initial_stop))
    else:
        # Default 4% swing stop
        initial_risk_per_share = entry_price * 0.04

    if initial_risk_per_share > 0:
        r_multiple = round((exit_price - entry_price) / initial_risk_per_share, 2)
    else:
        r_multiple = 0.0

    # Calculate holding duration
    entry_date_str = str(trade.get("entry_date", ""))
    exit_date_str = str(trade.get("exit_date", ""))
    hold_days = 0
    try:
        e_dt = datetime.strptime(entry_date_str[:10], "%Y-%m-%d")
        x_dt = datetime.strptime(exit_date_str[:10], "%Y-%m-%d")
        hold_days = max(0, (x_dt - e_dt).days)
    except Exception:
        hold_days = 0

    # Root-cause classification & Lesson formulation
    if "PARTIAL_TARGET" in exit_reason:
        category = "PARTIAL_TARGET_LOCKED"
        lesson = (
            f"First target reached ({r_multiple:+.2f}R). 50% profit banked systematically; "
            f"runner position left open with progressive trailing stop."
        )
    elif "TRAILING_STOP" in exit_reason:
        category = "RUNNER_PROFIT_CAPTURED"
        lesson = (
            f"Runner captured extended move ({r_multiple:+.2f}R in {hold_days} days). "
            f"Progressive trailing stop locked in profit after breakout expansion."
        )
    elif "PROFIT_LOCK" in exit_reason:
        category = "PROFIT_LOCK_PRESERVED"
        lesson = (
            f"Intermediate Profit Lock ladder executed at {r_multiple:+.2f}R ({pnl_pct:+.2f}%). "
            f"Protected gains when move reversed after reaching +6% boundary."
        )
    elif exit_reason == "BREAKEVEN_STOP_TRIGGERED" or "BREAKEVEN" in exit_reason:
        category = "PROTECTED_CAPITAL"
        lesson = (
            "Trailing break-even stop successfully protected capital after reaching +4% gain; "
            "trade avoided downside reversal without realized loss."
        )
    elif "TARGET" in exit_reason or pnl_pct >= 6.0:
        category = "SETUP_EDGE_PLAYED_OUT"
        lesson = (
            f"Setup reached target ({r_multiple:+.2f}R in {hold_days} days). "
            f"Minervini breakout momentum validated; profit taken systematically."
        )
    elif pnl < 0:
        if abs(r_multiple) <= 1.2:
            category = "NORMAL_RISK_DISTRIBUTION"
            lesson = (
                f"Disciplined {abs(r_multiple):.1f}R stop loss executed as planned. "
                f"Risk strictly contained within 1% portfolio equity."
            )
        else:
            category = "EXECUTION_SLIPPAGE_BREACH"
            lesson = (
                f"Loss exceeded 1R boundary ({abs(r_multiple):.2f}R). "
                f"Investigate overnight gap-down or execution slippage."
            )
    else:
        category = "DISCRETIONARY_OR_PROFIT_SCRATCH"
        lesson = f"Position closed with {r_multiple:+.2f}R return ({pnl_pct:+.2f}%). Execution aligned with rules."

    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

    return {
        "symbol": symbol,
        "entry_date": entry_date_str,
        "exit_date": exit_date_str,
        "hold_days": hold_days,
        "entry_price": round(entry_price, 2),
        "exit_price": round(exit_price, 2),
        "quantity": quantity,
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "r_multiple": r_multiple,
        "exit_reason": exit_reason,
        "root_cause_category": category,
        "lesson": lesson,
        "evaluated_at": now_str,
    }


def format_postmortem_markdown(postmortem: dict[str, Any]) -> str:
    """Format single trade postmortem into clean markdown card."""
    p = postmortem
    pnl_sign = "+" if p["pnl"] >= 0 else ""
    return (
        f"### 📋 Trade Postmortem: #{p['symbol']} ({p['exit_date'][:10]})\n"
        f"- **Outcome:** ₹{p['pnl']:+,.2f} ({pnl_sign}{p['pnl_pct']}%) | **R-Multiple:** {p['r_multiple']:+.2f}R\n"
        f"- **Hold Period:** {p['hold_days']} days (Entry: ₹{p['entry_price']:,.2f} → Exit: ₹{p['exit_price']:,.2f})\n"
        f"- **Exit Trigger:** `{p['exit_reason']}`\n"
        f"- **Root Cause:** `{p['root_cause_category']}`\n"
        f"- **Key Takeaway:** *{p['lesson']}*\n"
    )


def run_trade_memory_audit(state_file: Path = DEFAULT_STATE_FILE) -> list[dict[str, Any]]:
    """
    Audit all closed trades in state file, ensure each has a postmortem attached,
    and persist updates back to the state file.
    """
    if not state_file.exists():
        print(f"State file not found at {state_file}", file=sys.stderr)
        return []

    with open(state_file, encoding="utf-8") as f:
        state = json.load(f)

    closed_trades = state.get("closed_trades", [])
    updated = False
    evaluated_records = []

    for t in closed_trades:
        if "postmortem" not in t or not t["postmortem"]:
            pm = evaluate_trade_postmortem(t)
            t["postmortem"] = pm
            evaluated_records.append(pm)
            updated = True
        else:
            evaluated_records.append(t["postmortem"])

    if updated:
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        print(f"Updated {len(evaluated_records)} trade postmortems in {state_file}")

    return evaluated_records


def parse_args():
    parser = argparse.ArgumentParser(description="Trade Memory Loop & Postmortem Analyzer.")
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_STATE_FILE,
        help="Path to paper trading state file",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    records = run_trade_memory_audit(state_file=args.state_file)
    print("=" * 60)
    print(" TRADE MEMORY POSTMORTEM AUDIT ")
    print("=" * 60)
    for r in records[-5:]:  # Show last 5
        print(format_postmortem_markdown(r))


if __name__ == "__main__":
    main()
