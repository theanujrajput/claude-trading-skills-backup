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
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fpdf import FPDF

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
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


class PortfolioReportPDF(FPDF):
    def header(self):
        self.set_fill_color(26, 54, 93)  # Deep Navy
        self.rect(0, 0, 210, 10, "F")
        self.set_font("Helvetica", "B", 7.5)
        self.set_text_color(255, 255, 255)
        self.set_xy(10, 2.5)
        self.cell(0, 5, "CLAUDE TRADING SKILLS - CORE PORTFOLIO WEEKLY AUDIT", align="L")
        self.ln(10)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 7.5)
        self.set_text_color(160, 174, 192)
        self.cell(
            0,
            8,
            f"Automated Risk Governance & Allocation Audit | Page {self.page_no()}",
            align="C",
        )


def build_core_portfolio_pdf(review: dict[str, Any], output_path: Path) -> Path:
    """Build publication-grade Core Portfolio Weekly Review PDF."""
    pdf = PortfolioReportPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    date_str = review.get("date", datetime.today().strftime("%Y-%m-%d"))

    # Title & Metadata
    pdf.set_font("Helvetica", "B", 17)
    pdf.set_text_color(26, 54, 93)
    pdf.cell(0, 8, "Core Portfolio Weekly Review & Risk Audit", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(74, 85, 104)
    pdf.cell(
        0,
        5,
        f"Audit Date: {date_str} | Capital Allocation, Concentration Caps & Risk Protection",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(3)

    # 1. Summary Cards (4 columns)
    col_w = 47.5
    y_pos = pdf.get_y()
    pdf.set_fill_color(247, 250, 252)
    pdf.set_draw_color(226, 232, 240)

    cards = [
        ("Portfolio Equity", f"Rs. {review['portfolio_equity']:,.1f}"),
        ("Cash Reserves", f"Rs. {review['cash']:,.1f} ({review['cash_pct']}%)"),
        ("Active Positions", f"{review['positions_count']} Holdings"),
        ("Capital Protected", f"{review['risk_free_ratio_pct']}% Risk-Free"),
    ]
    for i, (label, val) in enumerate(cards):
        x = 10 + (i * col_w)
        pdf.rect(x, y_pos, col_w - 2, 14, "DF")
        pdf.set_xy(x + 2, y_pos + 1.5)
        pdf.set_font("Helvetica", "B", 7.5)
        pdf.set_text_color(113, 128, 150)
        pdf.cell(col_w - 4, 3.5, label)
        pdf.set_xy(x + 2, y_pos + 6.5)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(26, 54, 93)
        pdf.cell(col_w - 4, 5.5, val)

    pdf.set_y(y_pos + 18)

    # 2. Sector Concentration Matrix Table
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(26, 54, 93)
    pdf.cell(0, 6, "1. Sector Concentration Matrix (Max Cap: 25.0%)", new_x="LMARGIN", new_y="NEXT")

    headers = [
        ("Sector", 55),
        ("Market Value", 35),
        ("Weight (%)", 25),
        ("Cap Status", 35),
        ("Holdings", 40),
    ]
    pdf.set_fill_color(237, 242, 247)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(45, 55, 72)
    for title, width in headers:
        pdf.cell(width, 5.5, title, border=1, fill=True, align="C")
    pdf.ln(5.5)

    pdf.set_font("Helvetica", "", 8)
    for idx, (sec, data) in enumerate(review["sector_breakdown"].items()):
        row_bg = (248, 250, 252) if idx % 2 == 1 else (255, 255, 255)
        pdf.set_fill_color(*row_bg)
        weight = data["weight_pct"]
        is_over = weight > 25.0

        pdf.set_text_color(26, 54, 93)
        pdf.cell(55, 5.2, f"  {sec}", border=1, fill=True, align="L")
        pdf.cell(35, 5.2, f"Rs. {data['market_value']:,.1f}", border=1, fill=True, align="R")

        if is_over:
            pdf.set_text_color(220, 53, 69)
            pdf.cell(25, 5.2, f"{weight:.1f}%", border=1, fill=True, align="C")
            pdf.cell(35, 5.2, "OVERWEIGHT (>25%)", border=1, fill=True, align="C")
        else:
            pdf.set_text_color(40, 167, 69)
            pdf.cell(25, 5.2, f"{weight:.1f}%", border=1, fill=True, align="C")
            pdf.cell(35, 5.2, "WITHIN LIMIT", border=1, fill=True, align="C")

        pdf.set_text_color(74, 85, 104)
        syms_str = ", ".join(data["symbols"])
        pdf.cell(40, 5.2, syms_str[:22], border=1, fill=True, align="C")
        pdf.ln(5.2)

    pdf.ln(4)

    # 3. Single-Stock Holdings & Risk Status Table
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(26, 54, 93)
    pdf.cell(
        0,
        6,
        "2. Single-Stock Allocation & Risk Exposure (Max Cap: 20.0%)",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    stock_headers = [
        ("Stock", 30),
        ("Sector", 45),
        ("Market Value", 30),
        ("Weight (%)", 22),
        ("P&L (%)", 25),
        ("Protection Status", 38),
    ]
    pdf.set_fill_color(237, 242, 247)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(45, 55, 72)
    for title, width in stock_headers:
        pdf.cell(width, 5.5, title, border=1, fill=True, align="C")
    pdf.ln(5.5)

    pdf.set_font("Helvetica", "", 8)
    for idx, s in enumerate(review["stock_breakdown"]):
        row_bg = (248, 250, 252) if idx % 2 == 1 else (255, 255, 255)
        pdf.set_fill_color(*row_bg)

        pdf.set_text_color(26, 54, 93)
        pdf.cell(30, 5.2, f"  #{s['symbol']}", border=1, fill=True, align="L")
        pdf.set_text_color(74, 85, 104)
        pdf.cell(45, 5.2, s["sector"][:25], border=1, fill=True, align="L")
        pdf.cell(30, 5.2, f"Rs. {s['market_value']:,.1f}", border=1, fill=True, align="R")

        # Weight
        is_stock_over = s["weight_pct"] > 20.0
        if is_stock_over:
            pdf.set_text_color(220, 53, 69)
        else:
            pdf.set_text_color(45, 55, 72)
        pdf.cell(22, 5.2, f"{s['weight_pct']:.1f}%", border=1, fill=True, align="C")

        # P&L %
        pnl_val = s["pnl_pct"]
        if pnl_val >= 0:
            pdf.set_text_color(40, 167, 69)
            pnl_txt = f"+{pnl_val:.2f}%"
        else:
            pdf.set_text_color(220, 53, 69)
            pnl_txt = f"{pnl_val:.2f}%"
        pdf.cell(25, 5.2, pnl_txt, border=1, fill=True, align="C")

        # Risk Status
        if s["is_risk_free"]:
            pdf.set_text_color(40, 167, 69)
            pdf.cell(38, 5.2, "RISK-FREE (Trailing BE)", border=1, fill=True, align="C")
        else:
            pdf.set_text_color(214, 158, 46)
            pdf.cell(38, 5.2, "ACTIVE STOP LOSS", border=1, fill=True, align="C")
        pdf.ln(5.2)

    pdf.ln(5)

    # 4. Rebalance & Risk Recommendations Box
    pdf.set_fill_color(237, 242, 247)
    pdf.set_draw_color(49, 130, 206)
    pdf.set_line_width(0.6)

    box_y = pdf.get_y()
    pdf.rect(10, box_y, 190, 26, "DF")
    pdf.set_xy(14, box_y + 2)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(43, 108, 176)
    pdf.cell(0, 5, "REBALANCE & RISK AUDIT RECOMMENDATIONS", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(45, 55, 72)
    pdf.set_x(14)
    for rec in review["recommendations"][:3]:
        pdf.set_x(14)
        pdf.cell(0, 4.5, f"- {rec[:100]}", new_x="LMARGIN", new_y="NEXT")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))
    return output_path


def run_core_portfolio_review(
    state_file: Path = DEFAULT_STATE_FILE,
    output_dir: Path | None = None,
    send_telegram: bool = False,
) -> dict[str, Any]:
    """Execute weekly core portfolio audit, generate PDF and markdown reports."""
    if not state_file.exists():
        return {"status": "error", "message": f"State file not found at {state_file}"}

    with open(state_file, encoding="utf-8") as f:
        state = json.load(f)

    review = evaluate_core_portfolio(state)
    md_report = format_core_portfolio_markdown(review)

    target_dir = output_dir or (ROOT_DIR / "reports")
    target_dir.mkdir(parents=True, exist_ok=True)

    rep_path = target_dir / f"core_portfolio_weekly_{review['date']}.md"
    with open(rep_path, "w", encoding="utf-8") as f:
        f.write(md_report)

    pdf_path = target_dir / f"core_portfolio_weekly_{review['date']}.pdf"
    build_core_portfolio_pdf(review, pdf_path)

    telegram_delivered = False
    if send_telegram:
        try:
            from scripts.telegram_notifier import TelegramNotifier

            notifier = TelegramNotifier()
            if notifier.is_configured:
                # Build rich executive caption
                caption_lines = [
                    "🏛️ <b>CORE PORTFOLIO WEEKLY REVIEW & RISK AUDIT</b>",
                    f"<i>Audit Date: {review['date']}</i>",
                    "━━━━━━━━━━━━━━━━━━━━━",
                    f"• <b>Total Equity:</b> ₹{review['portfolio_equity']:,.2f}",
                    f"• <b>Cash Reserves:</b> ₹{review['cash']:,.2f} ({review['cash_pct']}%)",
                    f"• <b>Holdings:</b> {review['positions_count']} positions",
                    f"• <b>Capital Protection:</b> {review['risk_free_ratio_pct']}% risk-free 🛡️",
                    "",
                    "<b>Top Sectors:</b>",
                ]
                for sec, d in list(review["sector_breakdown"].items())[:3]:
                    caption_lines.append(f"• {sec}: <b>{d['weight_pct']}%</b>")
                if review["warnings"]:
                    caption_lines.append("\n⚠️ <b>Alerts:</b>")
                    for w in review["warnings"][:2]:
                        caption_lines.append(f"• {w}")
                caption_lines.append("\nDetailed allocation & risk matrix attached in PDF below 👇")

                telegram_delivered = notifier.send_document(
                    pdf_path, caption="\n".join(caption_lines)
                )
        except Exception as e:
            print(f"Warning: Failed to send Telegram core portfolio update: {e}")

    return {
        "status": "success",
        "review": review,
        "markdown": md_report,
        "pdf_path": str(pdf_path),
        "telegram_delivered": telegram_delivered,
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Core Portfolio Weekly Review & Audit.")
    parser.add_argument(
        "--state-file", type=Path, default=DEFAULT_STATE_FILE, help="Path to state file"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=None, help="Output directory for reports"
    )
    parser.add_argument("--send-telegram", action="store_true", help="Send PDF report via Telegram")
    return parser.parse_args()


if __name__ == "__main__":
    import argparse

    args = parse_args()
    res = run_core_portfolio_review(
        state_file=args.state_file,
        output_dir=args.output_dir,
        send_telegram=args.send_telegram,
    )
    if res.get("status") == "success":
        print(f"Core portfolio review generated: {res.get('pdf_path')}")
        if res.get("telegram_delivered"):
            print("PDF successfully delivered to Telegram!")
        print(res["markdown"])
