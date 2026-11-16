#!/usr/bin/env python3
"""
Core Portfolio Weekly Review for Indian Equities.

Evaluates overall portfolio health, asset allocation, sector/single-stock
concentration caps, and generates rebalance actions.

Guidelines Enforced:
1. Sector Concentration Cap: Max 25% of total portfolio value in any single sector.
2. Single-Stock Concentration Cap: Max 20% of total portfolio value in any single stock.
3. Risk Protection Audit: Measures percentage of open positions protected by trailing break-even stops.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_STATE_FILE = ROOT_DIR / "state" / "paper_trading_state.json"
IST = ZoneInfo("Asia/Kolkata")

# Primary sector mapping for standard NSE stocks
NSE_SECTOR_MAP = {
    "SONACOMS": "Auto Components",
    "ATHERENERG": "Automobiles & EV",
    "BAJAJ-AUTO": "Automobiles",
    "HEROMOTOCO": "Automobiles",
    "M&M": "Automobiles",
    "MARUTI": "Automobiles",
    "TVSMOTOR": "Automobiles",
    "PVRINOX": "Media & Entertainment",
    "ANANDRATHI": "Financial Services",
    "MOTILALOFS": "Financial Services",
    "ANGELONE": "Financial Services",
    "HDFCBANK": "Banking",
    "ICICIBANK": "Banking",
    "SBIN": "Banking",
    "AXISBANK": "Banking",
    "KOTAKBANK": "Banking",
    "INFY": "Information Technology",
    "TCS": "Information Technology",
    "COFORGE": "Information Technology",
    "TECHM": "Information Technology",
    "PERSISTENT": "Information Technology",
    "CYIENT": "Information Technology",
    "LTTS": "Information Technology",
    "DLF": "Realty",
    "LODHA": "Realty",
    "PHOENIXLTD": "Realty",
    "SUNPHARMA": "Pharma & Healthcare",
    "GLENMARK": "Pharma & Healthcare",
    "CIPLA": "Pharma & Healthcare",
    "DRREDDY": "Pharma & Healthcare",
    "TATASTEEL": "Metals & Mining",
    "JSWSTEEL": "Metals & Mining",
    "HINDALCO": "Metals & Mining",
    "SHYAMMETL": "Metals & Mining",
    "RELIANCE": "Energy & Conglomerate",
    "ONGC": "Energy & Oil",
    "BPCL": "Energy & Oil",
    "IOC": "Energy & Oil",
    "LT": "Capital Goods & Infra",
    "BEL": "Defense & Capital Goods",
    "BEML": "Defense & Capital Goods",
    "HAL": "Defense & Aerospace",
}


def get_sector_for_symbol(symbol: str) -> str:
    """Lookup sector for an NSE symbol with sensible default."""
    sym = symbol.upper().replace(".NS", "")
    return NSE_SECTOR_MAP.get(sym, "Diversified / General")


def evaluate_core_portfolio(
    state: dict[str, Any],
    max_sector_pct: float = 25.0,
    max_stock_pct: float = 20.0,
) -> dict[str, Any]:
    """
    Perform deep-dive allocation and risk audit on current portfolio state.
    """
    equity = float(state.get("portfolio_equity", 500000.0))
    cash = float(state.get("cash", 0.0))
    positions = state.get("active_positions", {})

    invested_value = sum(float(p.get("market_value", 0.0)) for p in positions.values())
    cash_pct = (cash / equity) * 100.0 if equity > 0 else 0.0
    invested_pct = (invested_value / equity) * 100.0 if equity > 0 else 0.0

    # Sector Concentration
    sector_breakdown: dict[str, dict[str, Any]] = {}
    for sym, pos in positions.items():
        sec = get_sector_for_symbol(sym)
        mv = float(pos.get("market_value", 0.0))
        if sec not in sector_breakdown:
            sector_breakdown[sec] = {"market_value": 0.0, "symbols": [], "weight_pct": 0.0}
        sector_breakdown[sec]["market_value"] += mv
        sector_breakdown[sec]["symbols"].append(sym)

    warnings = []
    for sec, data in sector_breakdown.items():
        weight = (data["market_value"] / equity) * 100.0 if equity > 0 else 0.0
        data["weight_pct"] = round(weight, 2)
        if weight > max_sector_pct:
            warnings.append(
                f"Sector '{sec}' is overweight at {weight:.1f}% of total portfolio (Max cap: {max_sector_pct:.1f}%)."
            )

    # Single-Stock Concentration
    stock_breakdown: list[dict[str, Any]] = []
    for sym, pos in positions.items():
        mv = float(pos.get("market_value", 0.0))
        weight = (mv / equity) * 100.0 if equity > 0 else 0.0
        is_risk_free = bool(pos.get("trailing_breakeven_triggered", False))
        stock_breakdown.append(
            {
                "symbol": sym,
                "sector": get_sector_for_symbol(sym),
                "market_value": round(mv, 2),
                "weight_pct": round(weight, 2),
                "pnl": round(float(pos.get("unrealized_pnl", 0.0)), 2),
                "pnl_pct": round(float(pos.get("pnl_pct", 0.0)), 2),
                "is_risk_free": is_risk_free,
            }
        )
        if weight > max_stock_pct:
            warnings.append(
                f"Position '{sym}' is overweight at {weight:.1f}% of total portfolio (Max cap: {max_stock_pct:.1f}%)."
            )

    stock_breakdown.sort(key=lambda x: x["weight_pct"], reverse=True)

    # Risk Exposure Summary
    risk_free_count = sum(1 for s in stock_breakdown if s["is_risk_free"])
    active_risk_count = len(stock_breakdown) - risk_free_count
    risk_free_pct = (risk_free_count / len(stock_breakdown)) * 100.0 if stock_breakdown else 100.0

    # Actionable Rebalance Recommendations
    recommendations = []
    if warnings:
        recommendations.extend(warnings)
    else:
        recommendations.append(
            "Portfolio is well-diversified. All sector and single-stock caps are respected."
        )

    if cash_pct < 5.0 and len(stock_breakdown) >= 5:
        recommendations.append(
            "Portfolio is at 95%+ utilization. Consider holding cash on next target exit."
        )

    return {
        "date": datetime.now(IST).strftime("%Y-%m-%d"),
        "portfolio_equity": round(equity, 2),
        "cash": round(cash, 2),
        "cash_pct": round(cash_pct, 1),
        "invested_pct": round(invested_pct, 1),
        "positions_count": len(positions),
        "risk_free_positions_count": risk_free_count,
        "active_risk_positions_count": active_risk_count,
        "risk_free_ratio_pct": round(risk_free_pct, 1),
        "sector_breakdown": sector_breakdown,
        "stock_breakdown": stock_breakdown,
        "warnings": warnings,
        "recommendations": recommendations,
    }


def format_core_portfolio_markdown(review: dict[str, Any]) -> str:
    """Format core portfolio review into markdown string."""
    lines = [
        "# Core Portfolio Weekly Review",
        f"**Date:** {review['date']} | **Equity:** ₹{review['portfolio_equity']:,.2f} | **Cash:** {review['cash_pct']}%\n",
        "## Asset Allocation",
        f"- **Invested Assets:** ₹{review['portfolio_equity'] - review['cash']:,.2f} ({review['invested_pct']}%)",
        f"- **Cash Reserves:** ₹{review['cash']:,.2f} ({review['cash_pct']}%)",
        f"- **Capital Protection:** {review['risk_free_positions_count']}/{review['positions_count']} positions risk-free ({review['risk_free_ratio_pct']}% protected)\n",
        "## Sector Concentration",
        "| Sector | Exposure (₹) | Weight | Holdings |",
        "|---|---|---|---|",
    ]
    for sec, data in review["sector_breakdown"].items():
        syms = ", ".join(f"`{s}`" for s in data["symbols"])
        lines.append(
            f"| **{sec}** | ₹{data['market_value']:,.2f} | {data['weight_pct']}% | {syms} |"
        )

    lines.extend(
        [
            "\n## Single-Stock Allocation",
            "| Stock | Sector | Market Value (₹) | Weight | P&L (%) | Risk Status |",
            "|---|---|---|---|---|---|",
        ]
    )
    for s in review["stock_breakdown"]:
        risk_tag = "🟢 Risk-Free (BE 🛡️)" if s["is_risk_free"] else "🟡 Active Stop"
        lines.append(
            f"| **#{s['symbol']}** | {s['sector']} | ₹{s['market_value']:,.2f} | {s['weight_pct']}% | "
            f"{s['pnl_pct']:+.2f}% | {risk_tag} |"
        )

    lines.append("\n## Rebalance & Risk Recommendations")
    for r in review["recommendations"]:
        lines.append(f"- {r}")

    return "\n".join(lines)


def run_core_portfolio_review(
    state_file: Path = DEFAULT_STATE_FILE,
    output_dir: Path | None = None,
    send_telegram: bool = False,
) -> dict[str, Any]:
    """Execute weekly core portfolio audit."""
    if not state_file.exists():
        return {"status": "error", "message": f"State file not found at {state_file}"}

    with open(state_file, encoding="utf-8") as f:
        state = json.load(f)

    review = evaluate_core_portfolio(state)
    md_report = format_core_portfolio_markdown(review)

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        rep_path = output_dir / f"core_portfolio_weekly_{review['date']}.md"
        with open(rep_path, "w", encoding="utf-8") as f:
            f.write(md_report)

    if send_telegram:
        try:
            from scripts.telegram_notifier import TelegramNotifier

            notifier = TelegramNotifier()
            if notifier.is_configured:
                # Send compact summary
                lines = [
                    "🏛️ <b>CORE PORTFOLIO WEEKLY REVIEW</b>",
                    f"<i>Date: {review['date']}</i>",
                    "━━━━━━━━━━━━━━━━━━━━━",
                    f"• <b>Equity:</b> ₹{review['portfolio_equity']:,.2f}",
                    f"• <b>Cash:</b> ₹{review['cash']:,.2f} ({review['cash_pct']}%)",
                    f"• <b>Holdings:</b> {review['positions_count']} positions",
                    f"• <b>Risk-Free Ratio:</b> {review['risk_free_ratio_pct']}% protected 🛡️",
                    "",
                    "<b>Top Sector Allocations:</b>",
                ]
                for sec, d in list(review["sector_breakdown"].items())[:4]:
                    lines.append(f"• {sec}: <b>{d['weight_pct']}%</b>")
                if review["warnings"]:
                    lines.append("\n⚠️ <b>Concentration Alerts:</b>")
                    for w in review["warnings"]:
                        lines.append(f"• {w}")
                lines.append("━━━━━━━━━━━━━━━━━━━━━")
                notifier.send_message("\n".join(lines))
        except Exception as e:
            print(f"Warning: Failed to send Telegram core portfolio update: {e}")

    return {
        "status": "success",
        "review": review,
        "markdown": md_report,
    }


if __name__ == "__main__":
    res = run_core_portfolio_review(send_telegram=False)
    if res.get("status") == "success":
        print(res["markdown"])
