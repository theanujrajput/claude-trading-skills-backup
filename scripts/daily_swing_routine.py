#!/usr/bin/env python3
"""
Automated Daily Swing Trading Orchestrator for Claude Trading Skills.

Executes the automated end-to-end post-market cycle:
1. Mark-to-Market & Exits: Updates existing active positions with today's close,
   automatically triggering stops or profit targets.
2. Risk & Capacity Gate: Evaluates available cash and maximum active position slots.
3. Post-Market Scan: Scans the NIFTY SMALLCAP 250 universe for Minervini Stage 2 Breakouts.
4. Position Sizing & Auto-Entry: Calculates exact share count (1% risk rule) and
   enters the top candidate into the paper trading portfolio.
5. Emits daily digest report.

Usage:
    # Run the full daily post-market cycle
    python3 scripts/daily_swing_routine.py --auto-buy

    # Dry-run scan & portfolio check without placing new buys
    python3 scripts/daily_swing_routine.py
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from scripts.paper_trader import (
    DEFAULT_STATE_FILE,
    enter_position,
    format_status_markdown,
    save_state,
    update_market_prices,
)
from scripts.screen_indian_stocks import (
    NIFTY_SMALLCAP_250_TICKERS,
    run_screener,
)

IST = ZoneInfo("Asia/Kolkata")


def is_market_hours(now: datetime | None = None) -> tuple[bool, str]:
    """Check if Indian market (NSE) is currently open (Mon-Fri 09:15 to 15:30 IST)."""
    current_ist = now or datetime.now(IST)
    if current_ist.tzinfo is None:
        current_ist = current_ist.replace(tzinfo=IST)

    # Weekend check (0 = Mon, 4 = Fri, 5 = Sat, 6 = Sun)
    if current_ist.weekday() >= 5:
        day_name = current_ist.strftime("%A")
        return False, f"Market closed today ({day_name} - Weekend)"

    open_time = current_ist.replace(hour=9, minute=15, second=0, microsecond=0)
    close_time = current_ist.replace(hour=15, minute=30, second=0, microsecond=0)

    if current_ist < open_time:
        time_str = current_ist.strftime("%H:%M:%S")
        return False, f"Pre-market: Market opens at 09:15 IST (Current: {time_str} IST)"
    if current_ist > close_time:
        time_str = current_ist.strftime("%H:%M:%S")
        return False, f"Post-market: Market closed at 15:30 IST (Current: {time_str} IST)"

    time_str = current_ist.strftime("%H:%M:%S")
    return True, f"Market open (Current: {time_str} IST)"


def run_daily_cycle(
    universe_symbols: list[str] = NIFTY_SMALLCAP_250_TICKERS,
    strategy: str = "breakout",
    risk_pct: float = 1.0,
    max_positions: int = 5,
    auto_buy: bool = True,
    scan_limit: int | None = None,
    check_market_hours: bool = False,
    force_full_scan: bool = False,
    cooldown_days: int = 5,
    state_file: Path = DEFAULT_STATE_FILE,
) -> dict[str, Any]:
    """Execute the full automated trading cycle."""
    date_str = datetime.now(IST).strftime("%Y-%m-%d")

    if check_market_hours:
        is_open, reason = is_market_hours()
        if not is_open:
            return {
                "date": date_str,
                "status": "market_closed",
                "equity": 0.0,
                "cash": 0.0,
                "active_positions_count": 0,
                "new_trades": [],
                "digest": f"Skipped 15-minute cycle: {reason}",
            }

    cycle_log = [
        f"=== TRADING CYCLE INITIATED ({date_str} {datetime.now(IST).strftime('%H:%M:%S')} IST) ==="
    ]

    # ---------------------------------------------------------
    # STEP 1: Mark-to-Market & Automated Exits
    # ---------------------------------------------------------
    cycle_log.append("\n[Step 1: Updating Open Positions & Checking Exits]")
    update_events, state = update_market_prices(
        state_file=state_file,
        auto_trigger_stops=True,
    )
    cycle_log.extend(update_events)

    # ---------------------------------------------------------
    # STEP 2: Risk, Slots, and Capital Check
    # ---------------------------------------------------------
    cycle_log.append("\n[Step 2: Portfolio Capacity & Risk Gate]")
    active_count = len(state.get("active_positions", {}))
    available_cash = state.get("cash", 0.0)
    portfolio_equity = state.get("portfolio_equity", available_cash)
    open_slots = max(0, max_positions - active_count)

    cycle_log.append(
        f"Active Positions: {active_count}/{max_positions} | Available Slots: {open_slots} | "
        f"Available Cash: ₹{available_cash:,.2f} | Total Equity: ₹{portfolio_equity:,.2f}"
    )

    new_trades_placed = []

    if open_slots <= 0:
        cycle_log.append(
            "Portfolio is at maximum capacity (5/5 slots filled). Skipping new entries."
        )
    elif available_cash < 5000:
        cycle_log.append(f"Insufficient cash (₹{available_cash:,.2f}) to enter new trades.")
    else:
        # ---------------------------------------------------------
        # STEP 3: Screening & Daily Watchlist Caching
        # ---------------------------------------------------------
        cached_date = state.get("watchlist_date")
        cached_watchlist = state.get("daily_watchlist", [])

        # Tier 2: If today's watchlist is already built, monitor only the cached watchlist (fast: < 1.5s)
        if cached_date == date_str and cached_watchlist and not force_full_scan:
            cycle_log.append(f"\n[Step 3: Fast Watchlist Monitor ({len(cached_watchlist)} stocks)]")
            cycle_log.append(f"Using cached daily watchlist from {cached_date} morning scan.")
            candidates = cached_watchlist
        else:
            # Tier 1: Full 249-stock universe scan (runs once daily at open or when forced)
            cycle_log.append(
                f"\n[Step 3: Full Universe Scan for '{strategy.upper()}' & Earnings Momentum]"
            )
            symbols_to_scan = universe_symbols[:scan_limit] if scan_limit else universe_symbols
            candidates = run_screener(symbols_to_scan, strategy=strategy)
            cycle_log.append(
                f"Screened {len(symbols_to_scan)} stocks. Candidates found: {len(candidates)}"
            )
            # Cache top 10 candidates for today's subsequent 15-minute runs
            state["watchlist_date"] = date_str
            state["daily_watchlist"] = candidates[:10]
            save_state(state, state_file)

        # Determine symbols in post-exit cooldown (closed within last `cooldown_days`)
        now_date = datetime.now(IST).date()
        cooldown_symbols: dict[str, int] = {}
        for trade in state.get("closed_trades", []):
            sym = trade.get("symbol")
            exit_date_str = trade.get("exit_date", "")
            if sym and exit_date_str:
                try:
                    exit_d = datetime.strptime(exit_date_str[:10], "%Y-%m-%d").date()
                    days_since = (now_date - exit_d).days
                    if 0 <= days_since < cooldown_days:
                        if sym not in cooldown_symbols or days_since < cooldown_symbols[sym]:
                            cooldown_symbols[sym] = days_since
                except Exception:
                    continue

        if cooldown_symbols:
            cooldown_desc = ", ".join(
                f"{s} ({d}d ago)" for s, d in sorted(cooldown_symbols.items())
            )
            cycle_log.append(
                f"Post-Exit Cooldown Active ({cooldown_days}d requirement): {cooldown_desc}"
            )

        # Filter out:
        # 1. Stocks already in active positions
        # 2. Stocks in post-exit cooldown (prevents immediately re-buying at extended highs)
        existing_symbols = set(state.get("active_positions", {}).keys())
        eligible_candidates = []
        for c in candidates:
            sym = c["symbol"]
            if sym in existing_symbols:
                continue
            if sym in cooldown_symbols:
                cycle_log.append(
                    f"Skipping {sym}: In {cooldown_days}-day post-exit cooldown (closed {cooldown_symbols[sym]}d ago)"
                )
                continue
            eligible_candidates.append(c)

        # Ensure cached daily watchlist does not hold active or cooldown stocks
        if "daily_watchlist" in state:
            state["daily_watchlist"] = [
                w
                for w in state["daily_watchlist"]
                if w.get("symbol") not in existing_symbols
                and w.get("symbol") not in cooldown_symbols
            ]
            save_state(state, state_file)

        # ---------------------------------------------------------
        # STEP 4: Position Sizing & Order Placement
        # ---------------------------------------------------------
        if not eligible_candidates:
            cycle_log.append("No new eligible candidates available for entry today.")
        else:
            cycle_log.append("\n[Step 4: Evaluating & Sizing Top Candidates]")
            # Take top candidates up to open slots
            candidates_to_enter = eligible_candidates[:open_slots]

            for cand in candidates_to_enter:
                sym = cand["symbol"]
                entry_price = cand["close"]

                # 4% swing stop loss (or 50 SMA / low support)
                stop_loss = round(entry_price * 0.96, 2)
                # 8% target (2R reward-to-risk)
                target = round(entry_price * 1.08, 2)
                risk_per_share = entry_price - stop_loss

                # Sizing: risk_pct of total portfolio equity
                max_risk_amount = (risk_pct / 100.0) * portfolio_equity
                calculated_qty = int(max_risk_amount / risk_per_share) if risk_per_share > 0 else 0

                # Max position size cap: 20% of equity
                max_capital_per_pos = portfolio_equity / max_positions
                if (calculated_qty * entry_price) > max_capital_per_pos:
                    calculated_qty = int(max_capital_per_pos / entry_price)

                total_cost = calculated_qty * entry_price

                if calculated_qty <= 0 or total_cost > available_cash:
                    cycle_log.append(
                        f"Skipping {sym}: Insufficient capital (Cost: ₹{total_cost:,.2f}, Available: ₹{available_cash:,.2f})"
                    )
                    continue

                trade_notes = f"Auto-entry from NIFTY Smallcap 250 {cand['setup']} scan (Score: {cand['trend_template_score']})"

                if auto_buy:
                    ok, msg, state = enter_position(
                        symbol=sym,
                        qty=calculated_qty,
                        entry_price=entry_price,
                        stop_loss=stop_loss,
                        target=target,
                        notes=trade_notes,
                        state_file=state_file,
                    )
                    cycle_log.append(f"✔ Executed New Trade: {msg}")
                    new_trades_placed.append(sym)
                    available_cash = state["cash"]
                    # Remove entered symbol from daily watchlist
                    if "daily_watchlist" in state:
                        state["daily_watchlist"] = [
                            w for w in state["daily_watchlist"] if w.get("symbol") != sym
                        ]
                        save_state(state, state_file)
                else:
                    cycle_log.append(
                        f"[Preview Buy] {sym}: {calculated_qty} shares @ ₹{entry_price:,.2f} | "
                        f"Stop: ₹{stop_loss:,.2f} | Target: ₹{target:,.2f} | Cost: ₹{total_cost:,.2f} | {trade_notes}"
                    )

    # ---------------------------------------------------------
    # STEP 5: Final Digest Report
    # ---------------------------------------------------------
    cycle_log.append("\n[Step 5: Final Account Status]")
    cycle_log.append(format_status_markdown(state))
    cycle_log.append("\n=== DAILY CYCLE COMPLETED ===")

    digest_text = "\n".join(cycle_log)
    return {
        "date": date_str,
        "equity": state.get("portfolio_equity", 0.0),
        "cash": state.get("cash", 0.0),
        "active_positions_count": len(state.get("active_positions", {})),
        "new_trades": new_trades_placed,
        "digest": digest_text,
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Automated Daily Swing Trading Orchestrator for Indian Equities."
    )
    parser.add_argument(
        "--strategy",
        choices=["breakout", "pullback", "all"],
        default="breakout",
        help="Screening filter strategy (default: breakout)",
    )
    parser.add_argument(
        "--force-full-scan",
        action="store_true",
        help="Force a full 249-stock universe scan even if today's watchlist is cached",
    )
    parser.add_argument(
        "--auto-buy",
        action="store_true",
        help="Automatically enter sized positions for top breakout candidates",
    )
    parser.add_argument(
        "--risk-pct",
        type=float,
        default=1.0,
        help="Risk percentage per trade (default: 1.0%)",
    )
    parser.add_argument(
        "--max-positions",
        type=int,
        default=5,
        help="Maximum concurrent active positions (default: 5)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of universe symbols to scan (for testing)",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_STATE_FILE,
        help="Path to paper trading state file",
    )
    parser.add_argument(
        "--check-market-hours",
        action="store_true",
        help="Skip execution if Indian market (NSE) is currently closed (09:15-15:30 IST Mon-Fri)",
    )
    parser.add_argument(
        "--cooldown-days",
        type=int,
        default=5,
        help="Lockout cooldown days before re-entering a recently closed stock (default: 5)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Optional directory to save daily cycle report",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    result = run_daily_cycle(
        strategy=args.strategy,
        risk_pct=args.risk_pct,
        max_positions=args.max_positions,
        auto_buy=args.auto_buy,
        scan_limit=args.limit,
        check_market_hours=args.check_market_hours,
        force_full_scan=args.force_full_scan,
        cooldown_days=args.cooldown_days,
        state_file=args.state_file,
    )

    print(result["digest"])

    if args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)
        timestamp = datetime.today().strftime("%Y-%m-%d_%H%M%S")
        report_path = os.path.join(args.output_dir, f"daily_cycle_{timestamp}.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(result["digest"])
        print(f"\nSaved daily digest to: {report_path}")


if __name__ == "__main__":
    main()
