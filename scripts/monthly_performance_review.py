#!/usr/bin/env python3
"""
Monthly Performance Review Orchestrator for Claude Trading Skills.

Aggregates closed trades over a monthly window, analyzes performance metrics,
evaluates pattern-level postmortems, and formulates calibrated operating rules
for the upcoming month.

Cadence: Monthly (First weekend of each month, or on-demand).
"""

from __future__ import annotations

import argparse
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

from scripts.core_portfolio_weekly import get_sector_for_symbol
from scripts.trade_memory_loop import evaluate_trade_postmortem


def evaluate_monthly_performance(
    state: dict[str, Any],
    year: int | None = None,
    month: int | None = None,
) -> dict[str, Any]:
    """
    Compute comprehensive institutional performance metrics for the specified month.
    If year/month not specified, defaults to current month (or prior month if before day 5).
    """
    now = datetime.now(IST)
    if year is None or month is None:
        if now.day <= 5:
            # First 5 days of month: review prior month
            if now.month == 1:
                target_year = now.year - 1
                target_month = 12
            else:
                target_year = now.year
                target_month = now.month - 1
        else:
            target_year = now.year
            target_month = now.month
    else:
        target_year = year
        target_month = month

    month_str = f"{target_year:04d}-{target_month:02d}"
    month_display = datetime(target_year, target_month, 1).strftime("%B %Y")

    portfolio_equity = float(state.get("portfolio_equity", 500000.0))
    initial_capital = float(state.get("initial_capital", 500000.0))
    cash = float(state.get("cash", 0.0))

    closed_trades: list[dict[str, Any]] = state.get("closed_trades", [])
    month_trades = [t for t in closed_trades if str(t.get("exit_date", "")).startswith(month_str)]

    total_trades = len(month_trades)
    winning_trades = [t for t in month_trades if float(t.get("pnl", 0.0)) > 0]
    losing_trades = [t for t in month_trades if float(t.get("pnl", 0.0)) < 0]
    scratch_trades = [t for t in month_trades if float(t.get("pnl", 0.0)) == 0]

    wins_count = len(winning_trades)
    losses_count = len(losing_trades)
    scratches_count = len(scratch_trades)

    win_rate = (wins_count / total_trades * 100.0) if total_trades > 0 else 0.0

    gross_profit = sum(float(t.get("pnl", 0.0)) for t in winning_trades)
    gross_loss = sum(float(t.get("pnl", 0.0)) for t in losing_trades)
    net_pnl = gross_profit + gross_loss
    net_return_pct = (net_pnl / initial_capital) * 100.0 if initial_capital > 0 else 0.0

    if abs(gross_loss) > 0:
        profit_factor = round(gross_profit / abs(gross_loss), 2)
    elif gross_profit > 0:
        profit_factor = 999.0
    else:
        profit_factor = 0.0

    avg_win_pnl = (gross_profit / wins_count) if wins_count > 0 else 0.0
    avg_loss_pnl = (gross_loss / losses_count) if losses_count > 0 else 0.0

    avg_win_pct = (
        sum(float(t.get("pnl_pct", 0.0)) for t in winning_trades) / wins_count
        if wins_count > 0
        else 0.0
    )
    avg_loss_pct = (
        sum(float(t.get("pnl_pct", 0.0)) for t in losing_trades) / losses_count
        if losses_count > 0
        else 0.0
    )

    payoff_ratio = round(avg_win_pct / abs(avg_loss_pct), 2) if abs(avg_loss_pct) > 0 else 0.0

    # Postmortem enrichment & R-multiples
    r_multiples: list[float] = []
    hold_days_all: list[int] = []
    root_cause_counts: dict[str, int] = {}
    sector_performance: dict[str, dict[str, Any]] = {}

    for t in month_trades:
        pm = t.get("postmortem")
        if not pm:
            pm = evaluate_trade_postmortem(t)

        r_mult = float(pm.get("r_multiple", 0.0))
        r_multiples.append(r_mult)
        hold_days_all.append(int(pm.get("hold_days", 0)))

        cat = pm.get("root_cause_category", "UNKNOWN")
        root_cause_counts[cat] = root_cause_counts.get(cat, 0) + 1

        sec = get_sector_for_symbol(t.get("symbol", ""))
        if sec not in sector_performance:
            sector_performance[sec] = {"trades": 0, "net_pnl": 0.0, "wins": 0}
        sector_performance[sec]["trades"] += 1
        sector_performance[sec]["net_pnl"] += float(t.get("pnl", 0.0))
        if float(t.get("pnl", 0.0)) > 0:
            sector_performance[sec]["wins"] += 1

    avg_r_multiple = round(sum(r_multiples) / len(r_multiples), 2) if r_multiples else 0.0
    avg_hold_days = round(sum(hold_days_all) / len(hold_days_all), 1) if hold_days_all else 0.0

    # Rule changes & Next Month Operating Rules
    recommendations = []
    if total_trades == 0:
        recommendations.append("Zero trades closed this month. Maintain standard 1.0% risk rule.")
    else:
        if profit_factor >= 2.0 and win_rate >= 50.0:
            recommendations.append(
                f"Strategy edge is thriving (Profit Factor {profit_factor}, Win Rate {win_rate:.1f}%). "
                f"Maintain standard 1.0% risk sizing and 5 concurrent position limit."
            )
        elif win_rate < 40.0 or (profit_factor < 1.0 and total_trades >= 3):
            recommendations.append(
                f"Defensive regime required (Profit Factor {profit_factor}, Win Rate {win_rate:.1f}%). "
                f"Recommend reducing per-trade risk from 1.0% to 0.75% and capping concurrent slots at 3."
            )
        else:
            recommendations.append(
                f"Consistent baseline performance (Profit Factor {profit_factor}, Win Rate {win_rate:.1f}%). "
                f"Continue executing Minervini Stage 2 breakouts with strict trailing stops."
            )

        # Flag underperforming sectors
        losing_sectors = [
            (sec, data["net_pnl"])
            for sec, data in sector_performance.items()
            if data["net_pnl"] < -10000
        ]
        for sec, loss in losing_sectors:
            recommendations.append(
                f"Sector Caution: '{sec}' produced net loss of ₹{abs(loss):,.2f}. Require higher RVOL (>= 2.0) before entering."
            )

    return {
        "month_str": month_str,
        "month_display": month_display,
        "portfolio_equity": round(portfolio_equity, 2),
        "initial_capital": round(initial_capital, 2),
        "cash": round(cash, 2),
        "total_trades": total_trades,
        "winning_trades": wins_count,
        "losing_trades": losses_count,
        "scratch_trades": scratches_count,
        "win_rate_pct": round(win_rate, 1),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "net_pnl": round(net_pnl, 2),
        "net_return_pct": round(net_return_pct, 2),
        "profit_factor": profit_factor,
        "avg_win_pnl": round(avg_win_pnl, 2),
        "avg_loss_pnl": round(avg_loss_pnl, 2),
        "avg_win_pct": round(avg_win_pct, 2),
        "avg_loss_pct": round(avg_loss_pct, 2),
        "payoff_ratio": payoff_ratio,
        "avg_r_multiple": avg_r_multiple,
        "avg_hold_days": avg_hold_days,
        "root_cause_counts": root_cause_counts,
        "sector_performance": sector_performance,
        "recommendations": recommendations,
        "trades": month_trades,
    }


def format_monthly_review_markdown(review: dict[str, Any]) -> str:
    """Format monthly review into an institutional markdown document."""
    r = review
    pnl_sign = "+" if r["net_pnl"] >= 0 else ""
    lines = [
        f"# Monthly Performance Review: {r['month_display']}",
        f"**Net Realized P&L:** ₹{r['net_pnl']:+,.2f} ({pnl_sign}{r['net_return_pct']}%) | **Profit Factor:** {r['profit_factor']}\n",
        "## Performance Scorecard",
        f"- **Total Closed Trades:** {r['total_trades']} ({r['winning_trades']}W / {r['losing_trades']}L / {r['scratch_trades']}BE)",
        f"- **Win Rate:** {r['win_rate_pct']}%",
        f"- **Average Winner:** +{r['avg_win_pct']}% (₹{r['avg_win_pnl']:,.2f})",
        f"- **Average Loser:** {r['avg_loss_pct']}% (₹{r['avg_loss_pnl']:,.2f})",
        f"- **Win/Loss Payoff Ratio:** {r['payoff_ratio']}x",
        f"- **Average Expectancy:** {r['avg_r_multiple']:+.2f}R per trade",
        f"- **Average Holding Duration:** {r['avg_hold_days']} days\n",
        "## Root-Cause Postmortem Breakdown",
        "| Category | Occurrences | Description |",
        "|---|---|---|",
    ]
    for cat, count in r["root_cause_counts"].items():
        lines.append(f"| `{cat}` | {count} | Trade memory classification |")

    lines.extend(
        [
            "\n## Sector Realized P&L",
            "| Sector | Trades | Win Rate | Realized P&L (₹) |",
            "|---|---|---|---|",
        ]
    )
    for sec, data in r["sector_performance"].items():
        sec_wr = (data["wins"] / data["trades"] * 100.0) if data["trades"] > 0 else 0.0
        lines.append(f"| **{sec}** | {data['trades']} | {sec_wr:.1f}% | ₹{data['net_pnl']:+,.2f} |")

    lines.append("\n## Operating Rules & Adjustments for Next Month")
    for rec in r["recommendations"]:
        lines.append(f"- 📌 {rec}")

    return "\n".join(lines)


class MonthlyReportPDF(FPDF):
    def header(self):
        self.set_fill_color(26, 54, 93)  # Deep Navy
        self.rect(0, 0, 210, 10, "F")
        self.set_font("Helvetica", "B", 7.5)
        self.set_text_color(255, 255, 255)
        self.set_xy(10, 2.5)
        self.cell(0, 5, "CLAUDE TRADING SKILLS - MONTHLY PERFORMANCE REVIEW", align="L")
        self.ln(10)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 7.5)
        self.set_text_color(160, 174, 192)
        self.cell(
            0,
            8,
            f"Institutional Trade Memory & Performance Calibration | Page {self.page_no()}",
            align="C",
        )


def build_monthly_performance_pdf(review: dict[str, Any], output_path: Path) -> Path:
    """Build publication-grade Monthly Performance Review PDF."""
    pdf = MonthlyReportPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    r = review

    # Title & Metadata
    pdf.set_font("Helvetica", "B", 17)
    pdf.set_text_color(26, 54, 93)
    pdf.cell(
        0, 8, f"Monthly Performance Review: {r['month_display']}", new_x="LMARGIN", new_y="NEXT"
    )

    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(74, 85, 104)
    pdf.cell(
        0,
        5,
        f"Period: {r['month_str']} | System Audit, Trade Postmortems & Rule Calibration",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(3)

    # 1. Summary Cards (4 columns)
    col_w = 47.5
    y_pos = pdf.get_y()
    pdf.set_fill_color(247, 250, 252)
    pdf.set_draw_color(226, 232, 240)

    pnl_sign = "+" if r["net_pnl"] >= 0 else ""
    cards = [
        ("Net Realized P&L", f"Rs. {r['net_pnl']:+,.1f} ({pnl_sign}{r['net_return_pct']}%)"),
        ("Win Rate", f"{r['win_rate_pct']}% ({r['winning_trades']}W / {r['losing_trades']}L)"),
        ("Profit Factor", f"{r['profit_factor']}"),
        ("Payoff Ratio", f"{r['payoff_ratio']}x ({r['avg_r_multiple']:+.2f}R)"),
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

    # 2. Performance Breakdown Sub-Metrics
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(26, 54, 93)
    pdf.cell(0, 6, "1. Executive Performance Metrics", new_x="LMARGIN", new_y="NEXT")

    sub_metrics = [
        (
            "Gross Profit",
            f"Rs. {r['gross_profit']:,.1f}",
            "Average Winner",
            f"+{r['avg_win_pct']:.2f}% (Rs. {r['avg_win_pnl']:,.1f})",
        ),
        (
            "Gross Loss",
            f"Rs. {r['gross_loss']:,.1f}",
            "Average Loser",
            f"{r['avg_loss_pct']:.2f}% (Rs. {r['avg_loss_pnl']:,.1f})",
        ),
        (
            "Total Trades",
            f"{r['total_trades']} closed",
            "Average Hold Time",
            f"{r['avg_hold_days']} days",
        ),
    ]
    pdf.set_font("Helvetica", "", 8.5)
    for m1, v1, m2, v2 in sub_metrics:
        pdf.set_text_color(74, 85, 104)
        pdf.cell(35, 5, f"  - {m1}:", align="L")
        pdf.set_text_color(26, 54, 93)
        pdf.cell(50, 5, v1, align="L")

        pdf.set_text_color(74, 85, 104)
        pdf.cell(40, 5, f"- {m2}:", align="L")
        pdf.set_text_color(26, 54, 93)
        pdf.cell(60, 5, v2, align="L")
        pdf.ln(5)

    pdf.ln(3)

    # 3. Sector Realized P&L Table
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(26, 54, 93)
    pdf.cell(0, 6, "2. Sector Realized Performance", new_x="LMARGIN", new_y="NEXT")

    sec_headers = [
        ("Sector", 70),
        ("Closed Trades", 30),
        ("Win Rate (%)", 35),
        ("Realized P&L", 55),
    ]
    pdf.set_fill_color(237, 242, 247)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(45, 55, 72)
    for title, width in sec_headers:
        pdf.cell(width, 5.5, title, border=1, fill=True, align="C")
    pdf.ln(5.5)

    pdf.set_font("Helvetica", "", 8)
    for idx, (sec, data) in enumerate(r["sector_performance"].items()):
        row_bg = (248, 250, 252) if idx % 2 == 1 else (255, 255, 255)
        pdf.set_fill_color(*row_bg)
        sec_wr = (data["wins"] / data["trades"] * 100.0) if data["trades"] > 0 else 0.0
        sec_pnl = data["net_pnl"]

        pdf.set_text_color(26, 54, 93)
        pdf.cell(70, 5.2, f"  {sec}", border=1, fill=True, align="L")
        pdf.set_text_color(74, 85, 104)
        pdf.cell(30, 5.2, str(data["trades"]), border=1, fill=True, align="C")
        pdf.cell(35, 5.2, f"{sec_wr:.1f}%", border=1, fill=True, align="C")

        if sec_pnl >= 0:
            pdf.set_text_color(40, 167, 69)
            pnl_str = f"+Rs. {sec_pnl:,.1f}"
        else:
            pdf.set_text_color(220, 53, 69)
            pnl_str = f"-Rs. {abs(sec_pnl):,.1f}"
        pdf.cell(55, 5.2, pnl_str, border=1, fill=True, align="R")
        pdf.ln(5.2)

    pdf.ln(3)

    # 4. Root-Cause Postmortem Breakdown
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(26, 54, 93)
    pdf.cell(0, 6, "3. Root-Cause Postmortem Classifications", new_x="LMARGIN", new_y="NEXT")

    rc_headers = [("Category", 65), ("Occurrences", 30), ("Percentage", 35), ("System Impact", 60)]
    pdf.set_fill_color(237, 242, 247)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(45, 55, 72)
    for title, width in rc_headers:
        pdf.cell(width, 5.5, title, border=1, fill=True, align="C")
    pdf.ln(5.5)

    pdf.set_font("Helvetica", "", 8)
    for idx, (cat, count) in enumerate(r["root_cause_counts"].items()):
        row_bg = (248, 250, 252) if idx % 2 == 1 else (255, 255, 255)
        pdf.set_fill_color(*row_bg)
        pct = (count / r["total_trades"] * 100.0) if r["total_trades"] > 0 else 0.0

        pdf.set_text_color(26, 54, 93)
        pdf.cell(65, 5.2, f"  {cat}", border=1, fill=True, align="L")
        pdf.set_text_color(74, 85, 104)
        pdf.cell(30, 5.2, str(count), border=1, fill=True, align="C")
        pdf.cell(35, 5.2, f"{pct:.1f}%", border=1, fill=True, align="C")

        if cat == "SETUP_EDGE_PLAYED_OUT":
            impact = "Positive edge extraction (+2R)"
            pdf.set_text_color(40, 167, 69)
        elif cat == "PROTECTED_CAPITAL":
            impact = "Downside prevented via trailing stop"
            pdf.set_text_color(43, 108, 176)
        else:
            impact = "Risk strictly contained (-1R stop)"
            pdf.set_text_color(214, 158, 46)
        pdf.cell(60, 5.2, impact, border=1, fill=True, align="L")
        pdf.ln(5.2)

    pdf.ln(4)

    # 5. Calibrated Operating Rules Box for Next Month
    pdf.set_fill_color(237, 242, 247)
    pdf.set_draw_color(49, 130, 206)
    pdf.set_line_width(0.6)

    box_y = pdf.get_y()
    pdf.rect(10, box_y, 190, 26, "DF")
    pdf.set_xy(14, box_y + 2)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(43, 108, 176)
    pdf.cell(0, 5, "CALIBRATED OPERATING RULES FOR NEXT MONTH", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(45, 55, 72)
    for rec in r["recommendations"][:3]:
        pdf.set_x(14)
        pdf.cell(0, 4.5, f"- {rec[:100]}", new_x="LMARGIN", new_y="NEXT")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))
    return output_path


def run_monthly_performance_review(
    state_file: Path = DEFAULT_STATE_FILE,
    year: int | None = None,
    month: int | None = None,
    output_dir: Path | None = None,
    send_telegram: bool = False,
) -> dict[str, Any]:
    """Execute monthly review cycle, persist report, and optionally notify via Telegram."""
    if not state_file.exists():
        return {"status": "error", "message": f"State file not found at {state_file}"}

    with open(state_file, encoding="utf-8") as f:
        state = json.load(f)

    review = evaluate_monthly_performance(state, year=year, month=month)
    md_report = format_monthly_review_markdown(review)

    target_dir = output_dir or (ROOT_DIR / "reports")
    target_dir.mkdir(parents=True, exist_ok=True)

    rep_path = target_dir / f"monthly_review_{review['month_str']}.md"
    with open(rep_path, "w", encoding="utf-8") as f:
        f.write(md_report)

    pdf_path = target_dir / f"monthly_performance_review_{review['month_str']}.pdf"
    build_monthly_performance_pdf(review, pdf_path)

    telegram_delivered = False
    if send_telegram:
        try:
            from scripts.telegram_notifier import TelegramNotifier

            notifier = TelegramNotifier()
            if notifier.is_configured:
                pnl_emoji = "🟢" if review["net_pnl"] >= 0 else "🔴"
                pnl_sign = "+" if review["net_pnl"] >= 0 else ""
                caption_lines = [
                    f"📊 <b>MONTHLY PERFORMANCE REVIEW ({review['month_display'].upper()})</b>",
                    "━━━━━━━━━━━━━━━━━━━━━",
                    f"{pnl_emoji} <b>Net Realized P&L:</b> ₹{review['net_pnl']:+,.2f} ({pnl_sign}{review['net_return_pct']}%)",
                    f"• <b>Win Rate:</b> {review['win_rate_pct']}% ({review['winning_trades']}W / {review['losing_trades']}L)",
                    f"• <b>Profit Factor:</b> {review['profit_factor']}",
                    f"• <b>Expectancy:</b> {review['avg_r_multiple']:+.2f}R | <b>Payoff:</b> {review['payoff_ratio']}x",
                    f"• <b>Avg Hold Time:</b> {review['avg_hold_days']} days",
                    "",
                    "<b>Calibrated Operating Rules:</b>",
                ]
                for rec in review["recommendations"][:2]:
                    caption_lines.append(f"• <i>{rec}</i>")
                caption_lines.append(
                    "\nDetailed institutional monthly report attached in PDF below 👇"
                )

                telegram_delivered = notifier.send_document(
                    pdf_path, caption="\n".join(caption_lines)
                )
        except Exception as e:
            print(f"Warning: Failed to dispatch Telegram monthly review: {e}")

    return {
        "status": "success",
        "review": review,
        "markdown": md_report,
        "pdf_path": str(pdf_path),
        "telegram_delivered": telegram_delivered,
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Monthly Trading Performance Review.")
    parser.add_argument(
        "--state-file", type=Path, default=DEFAULT_STATE_FILE, help="Path to state file"
    )
    parser.add_argument("--year", type=int, default=None, help="Year (e.g. 2026)")
    parser.add_argument("--month", type=int, default=None, help="Month (1-12)")
    parser.add_argument("--output-dir", type=Path, default=None, help="Directory to save report")
    parser.add_argument("--send-telegram", action="store_true", help="Send Telegram digest")
    return parser.parse_args()


def main():
    args = parse_args()
    res = run_monthly_performance_review(
        state_file=args.state_file,
        year=args.year,
        month=args.month,
        output_dir=args.output_dir,
        send_telegram=args.send_telegram,
    )
    if res.get("status") == "success":
        print(res["markdown"])


if __name__ == "__main__":
    main()
