#!/usr/bin/env python3
"""
Account-Level Drawdown Circuit Breaker for Claude Trading Skills.

Evaluates account-level realized P&L, losing streaks, and drawdown velocity
to determine whether new trade risk is permitted today.

Rules Evaluated:
1. Max Daily Loss Limit (-2.0% of portfolio equity):
   If realized losses on trades closed today exceed 2% of equity, halts new buying until tomorrow.
2. Losing Streak Cooldown (2 consecutive stop-loss exits within 24h):
   Imposes a mandatory 24-hour timeout to prevent revenge trading.
3. Weekly Drawdown Halt (-5.0% of portfolio equity):
   If cumulative net losses over the past 7 days exceed 5% of equity, halts new entries until Monday.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def evaluate_drawdown_circuit_breaker(
    state: dict[str, Any],
    now: datetime | None = None,
    max_daily_loss_pct: float = 2.0,
    max_weekly_loss_pct: float = 5.0,
    losing_streak_threshold: int = 2,
) -> dict[str, Any]:
    """
    Evaluate account-level realized losses and losing streaks against circuit breaker thresholds.
    """
    current_time = now or datetime.now(IST)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=IST)

    today_str = current_time.strftime("%Y-%m-%d")
    portfolio_equity = float(state.get("portfolio_equity", state.get("cash", 500000.0)))
    if portfolio_equity <= 0:
        portfolio_equity = 500000.0

    closed_trades: list[dict[str, Any]] = state.get("closed_trades", [])

    daily_loss_cap = (max_daily_loss_pct / 100.0) * portfolio_equity
    weekly_loss_cap = (max_weekly_loss_pct / 100.0) * portfolio_equity

    # 1. Evaluate Daily Realized Losses (exited today)
    today_trades = [t for t in closed_trades if str(t.get("exit_date", "")).startswith(today_str)]
    today_realized_loss = sum(
        float(t.get("pnl", 0.0)) for t in today_trades if float(t.get("pnl", 0.0)) < 0
    )
    today_net_pnl = sum(float(t.get("pnl", 0.0)) for t in today_trades)

    # 2. Evaluate Weekly Realized Losses (exited in past 7 days)
    seven_days_ago = current_time - timedelta(days=7)
    weekly_trades = []
    for t in closed_trades:
        exit_str = str(t.get("exit_date", ""))
        try:
            exit_dt = datetime.strptime(exit_str[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
        except Exception:
            try:
                exit_dt = datetime.strptime(exit_str[:10], "%Y-%m-%d").replace(tzinfo=IST)
            except Exception:
                continue
        if exit_dt >= seven_days_ago:
            weekly_trades.append(t)

    weekly_realized_loss = sum(
        float(t.get("pnl", 0.0)) for t in weekly_trades if float(t.get("pnl", 0.0)) < 0
    )
    weekly_net_pnl = sum(float(t.get("pnl", 0.0)) for t in weekly_trades)

    # 3. Evaluate Recent Losing Streak (consecutive stop losses within 24h)
    consecutive_stops = 0
    twenty_four_hours_ago = current_time - timedelta(hours=24)
    # Check backwards through closed trades
    for t in reversed(closed_trades):
        reason = str(t.get("exit_reason", "")).upper()
        exit_str = str(t.get("exit_date", ""))
        try:
            exit_dt = datetime.strptime(exit_str[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
        except Exception:
            try:
                exit_dt = datetime.strptime(exit_str[:10], "%Y-%m-%d").replace(tzinfo=IST)
            except Exception:
                exit_dt = current_time

        if exit_dt >= twenty_four_hours_ago:
            if "STOP_LOSS" in reason:
                consecutive_stops += 1
            elif "TARGET" in reason or float(t.get("pnl", 0.0)) > 0:
                break
        else:
            break

    metrics = {
        "portfolio_equity": round(portfolio_equity, 2),
        "today_realized_loss": round(today_realized_loss, 2),
        "today_net_pnl": round(today_net_pnl, 2),
        "daily_loss_limit": round(daily_loss_cap, 2),
        "weekly_realized_loss": round(weekly_realized_loss, 2),
        "weekly_net_pnl": round(weekly_net_pnl, 2),
        "weekly_loss_limit": round(weekly_loss_cap, 2),
        "consecutive_stops_24h": consecutive_stops,
        "closed_trades_count": len(closed_trades),
    }

    # Rule 1: Daily Loss Limit
    if abs(today_realized_loss) >= daily_loss_cap:
        return {
            "is_allowed": False,
            "status": "HALTED_DAILY_LOSS",
            "reason": (
                f"Daily realized loss of ₹{abs(today_realized_loss):,.2f} reached "
                f"{max_daily_loss_pct:.1f}% limit (₹{daily_loss_cap:,.2f}). Trading halted until tomorrow."
            ),
            "metrics": metrics,
        }

    # Rule 2: Losing Streak Cooldown
    if consecutive_stops >= losing_streak_threshold:
        return {
            "is_allowed": False,
            "status": "COOLDOWN_LOSING_STREAK",
            "reason": (
                f"Losing streak threshold triggered ({consecutive_stops} consecutive stop losses within 24h). "
                f"Mandatory 24h cooldown active to prevent tilt."
            ),
            "metrics": metrics,
        }

    # Rule 3: Weekly Drawdown Halt
    if abs(weekly_realized_loss) >= weekly_loss_cap:
        return {
            "is_allowed": False,
            "status": "HALTED_WEEKLY_DRAWDOWN",
            "reason": (
                f"7-day realized drawdown of ₹{abs(weekly_realized_loss):,.2f} exceeded "
                f"{max_weekly_loss_pct:.1f}% weekly limit (₹{weekly_loss_cap:,.2f}). Trading halted until Monday."
            ),
            "metrics": metrics,
        }

    return {
        "is_allowed": True,
        "status": "CLEAR",
        "reason": "All circuit breaker rules clear. Account risk within safe parameters.",
        "metrics": metrics,
    }


def format_circuit_breaker_markdown(result: dict[str, Any]) -> str:
    """Format circuit breaker status into Markdown string."""
    m = result.get("metrics", {})
    allowed = result.get("is_allowed", True)
    status = result.get("status", "UNKNOWN")
    reason = result.get("reason", "")

    icon = "🟢" if allowed else "⛔"
    lines = [
        f"# {icon} Drawdown Circuit Breaker Status: `{status}`",
        f"**Buying Allowed:** {'YES' if allowed else 'NO (HALTED)'}",
        f"**Assessment:** {reason}\n",
        "## Risk Telemetry",
        f"- **Portfolio Equity:** ₹{m.get('portfolio_equity', 0.0):,.2f}",
        f"- **Today Realized Loss:** ₹{abs(m.get('today_realized_loss', 0.0)):,.2f} / ₹{m.get('daily_loss_limit', 0.0):,.2f} max",
        f"- **Today Net P&L:** ₹{m.get('today_net_pnl', 0.0):+,.2f}",
        f"- **7-Day Realized Loss:** ₹{abs(m.get('weekly_realized_loss', 0.0)):,.2f} / ₹{m.get('weekly_loss_limit', 0.0):,.2f} max",
        f"- **7-Day Net P&L:** ₹{m.get('weekly_net_pnl', 0.0):+,.2f}",
        f"- **Consecutive Stops (24h):** {m.get('consecutive_stops_24h', 0)}",
    ]
    return "\n".join(lines)
