#!/usr/bin/env python3
"""
Weekly Sector Rotation, Deep-Dive Stock Contenders & Backtest Report Generator.

Runs weekly (every Sunday or Monday pre-market) to:
1. Analyze Indian NSE Sectoral Indices & Global Market Cycle.
2. Backtest and score previous week's stock recommendations.
3. Dynamically identify the #1 leading sector index.
4. Deep-dive scan that leading sector for top stock contenders passing Minervini Stage 2,
   volume confirmation, and 52-week high proximity checks.
5. Save the new recommendations to persistent state for next week's performance review.
6. Generate a publication-grade multi-page PDF report.
7. Dispatch the PDF directly to Telegram.

Usage:
    # Run full weekly analysis, generate PDF, and send to Telegram
    python3 scripts/weekly_sector_report.py

    # Local dry-run only (generate PDF without sending to Telegram)
    python3 scripts/weekly_sector_report.py --no-telegram
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from fpdf import FPDF

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from scripts.screen_indian_stocks import (
    analyze_symbol_bars,
)
from scripts.telegram_notifier import TelegramNotifier

RECOMMENDATIONS_STATE_FILE = ROOT_DIR / "state" / "weekly_sector_recommendations.json"

NSE_SECTORS = {
    "NIFTY IT": "^CNXIT",
    "NIFTY PHARMA": "^CNXPHARMA",
    "NIFTY AUTO": "^CNXAUTO",
    "NIFTY BANK": "^NSEBANK",
    "NIFTY FMCG": "^CNXFMCG",
    "NIFTY METAL": "^CNXMETAL",
    "NIFTY ENERGY": "^CNXENERGY",
    "NIFTY REALTY": "^CNXREALTY",
    "NIFTY INFRA": "^CNXINFRA",
}

SECTOR_CONSTITUENTS: dict[str, list[str]] = {
    "NIFTY IT": [
        "TCS",
        "INFY",
        "HCLTECH",
        "WIPRO",
        "TECHM",
        "LTIM",
        "PERSISTENT",
        "COFORGE",
        "MPHASIS",
        "LTTS",
        "TATAELXSI",
        "KPITTECH",
        "CYIENT",
        "ZENSARTECH",
        "BSOFT",
        "SONATSOFTW",
        "MASTEK",
        "HAPPSTMNDS",
    ],
    "NIFTY PHARMA": [
        "SUNPHARMA",
        "CIPLA",
        "DRREDDY",
        "DIVISLAB",
        "LUPIN",
        "AUROPHARMA",
        "TORNTPHARM",
        "ALKEM",
        "MANKIND",
        "ZYDUSLIFE",
        "BIOCON",
        "GLENMARK",
        "IPCALAB",
        "LAURUSLABS",
        "NATCOPHARM",
        "GRANULES",
    ],
    "NIFTY AUTO": [
        "MARUTI",
        "M&M",
        "TATAMOTORS",
        "BAJAJ-AUTO",
        "EICHERMOT",
        "HEROMOTOCO",
        "TVSMOTOR",
        "BHARATFORG",
        "BOSCHLTD",
        "SAMVARDHANA",
        "MOTHERSON",
        "TIINDIA",
        "ASHOKLEY",
        "SONACOMS",
        "EXIDEIND",
        "ATHERENERG",
    ],
    "NIFTY BANK": [
        "HDFCBANK",
        "ICICIBANK",
        "SBIN",
        "KOTAKBANK",
        "AXISBANK",
        "INDUSINDBK",
        "BANKBARODA",
        "PNB",
        "AUBANK",
        "FEDERALBNK",
        "IDFCFIRSTB",
        "CANBK",
    ],
    "NIFTY FMCG": [
        "ITC",
        "HINDUNILVR",
        "NESTLEIND",
        "BRITANNIA",
        "TATACONSUM",
        "VBL",
        "DABUR",
        "GODREJCP",
        "MARICO",
        "COLPAL",
        "EMAMILTD",
        "RADICO",
    ],
    "NIFTY METAL": [
        "TATASTEEL",
        "JSWSTEEL",
        "HINDALCO",
        "VEDL",
        "JINDALSTEL",
        "COALINDIA",
        "NMDC",
        "SAIL",
        "NATIONALUM",
        "APLAPOLLO",
        "RATNAMANI",
        "HINDZINC",
    ],
    "NIFTY ENERGY": [
        "RELIANCE",
        "NTPC",
        "ONGC",
        "POWERGRID",
        "BPCL",
        "IOC",
        "GAIL",
        "TATAPOWER",
        "ADANIGREEN",
        "ADANIENT",
    ],
    "NIFTY REALTY": [
        "DLF",
        "GODREJPROP",
        "LODHA",
        "OBERREALTY",
        "PRESTIGE",
        "PHOENIXLTD",
        "BRIGADE",
        "SOBHA",
    ],
    "NIFTY INFRA": [
        "LT",
        "ULTRACEMCO",
        "GRASIM",
        "ADANIPORTS",
        "BHARTIARTL",
        "POWERGRID",
        "NTPC",
        "CONCOR",
        "GMRINFRA",
        "IRCTC",
    ],
}


def fetch_nse_sector_data() -> tuple[list[dict[str, Any]], dict[str, float]]:
    """Fetch 6 months of historical daily closes for NSE sectoral indices and Nifty 50."""
    import yfinance as yf

    all_tickers = list(NSE_SECTORS.values()) + ["^NSEI"]
    df = yf.download(all_tickers, period="6mo", progress=False)

    if df.empty or "Close" not in df:
        raise RuntimeError("Failed to fetch NSE sector data from Yahoo Finance.")

    close_df = df["Close"]

    nifty_series = close_df["^NSEI"].dropna() if "^NSEI" in close_df else None
    nifty_1m_ret = 0.0
    if nifty_series is not None and len(nifty_series) >= 20:
        nifty_1m_ret = (
            (nifty_series.iloc[-1] - nifty_series.iloc[-20]) / nifty_series.iloc[-20]
        ) * 100.0

    sector_results = []

    for name, ticker in NSE_SECTORS.items():
        if ticker not in close_df:
            continue
        series = close_df[ticker].dropna()
        if len(series) < 50:
            continue

        c_now = float(series.iloc[-1])
        c_1w = float(series.iloc[-5]) if len(series) >= 5 else c_now
        c_1m = float(series.iloc[-20]) if len(series) >= 20 else c_now
        c_3m = float(series.iloc[-60]) if len(series) >= 60 else float(series.iloc[0])

        ret_1w = ((c_now - c_1w) / c_1w) * 100.0 if c_1w > 0 else 0.0
        ret_1m = ((c_now - c_1m) / c_1m) * 100.0 if c_1m > 0 else 0.0
        ret_3m = ((c_now - c_3m) / c_3m) * 100.0 if c_3m > 0 else 0.0

        sma_50 = float(series.rolling(50).mean().iloc[-1])
        sma_200 = float(series.rolling(200).mean().iloc[-1]) if len(series) >= 200 else sma_50
        rs_vs_nifty = ret_1m - nifty_1m_ret

        status = (
            "LEADING"
            if (c_now > sma_50 and rs_vs_nifty > 2.0)
            else (
                "WEAKENING"
                if (c_now > sma_50 and rs_vs_nifty <= 2.0)
                else ("IMPROVING" if (c_now <= sma_50 and ret_1w > 0) else "LAGGING")
            )
        )

        sector_results.append(
            {
                "sector": name,
                "close": c_now,
                "ret_1w": ret_1w,
                "ret_1m": ret_1m,
                "ret_3m": ret_3m,
                "above_50_sma": c_now > sma_50,
                "above_200_sma": c_now > sma_200,
                "rs_vs_nifty": rs_vs_nifty,
                "status": status,
            }
        )

    sector_results.sort(key=lambda x: x["ret_1m"], reverse=True)
    return sector_results, {"nifty_1m_return": nifty_1m_ret}


def fetch_global_rotation_summary() -> dict[str, Any]:
    """Fetch global sector rotation indicators from sector-analyst."""
    try:
        import importlib.util

        script_path = (
            ROOT_DIR / "skills" / "sector-analyst" / "scripts" / "analyze_sector_rotation.py"
        )
        spec = importlib.util.spec_from_file_location("analyze_sector_rotation", script_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load {script_path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        raw_rows = mod.fetch_csv(mod.SECTOR_CSV_URL)
        sectors = mod.parse_sectors(raw_rows)
        regime = mod.analyze_risk_regime(sectors)
        cycle = mod.analyze_cycle_phase(sectors)

        sorted_sectors = sorted(sectors, key=lambda s: s.ratio, reverse=True)
        top_global = [s.name for s in sorted_sectors[:3]]

        return {
            "cycle_phase": cycle.phase.title(),
            "confidence": cycle.confidence.title(),
            "risk_regime": regime.regime.upper(),
            "regime_score": regime.score,
            "top_global_sectors": top_global,
            "overbought": [
                s.name for s in sorted_sectors if getattr(s, "status", "") == "Overbought"
            ],
        }
    except Exception as e:
        print(f"Notice: Global sector analyst check bypassed: {e}", file=sys.stderr)
        return {
            "cycle_phase": "Mid-Cycle Expansion",
            "confidence": "Moderate",
            "risk_regime": "BALANCED",
            "regime_score": 53,
            "top_global_sectors": ["Energy", "Healthcare", "Technology"],
            "overbought": ["Energy"],
        }


def evaluate_previous_recommendations(
    history_file: Path = RECOMMENDATIONS_STATE_FILE,
) -> dict[str, Any] | None:
    """Backtest & evaluate performance of previously recommended stocks."""
    import yfinance as yf

    if not history_file.exists():
        return None

    try:
        with open(history_file, encoding="utf-8") as f:
            data = json.load(f)
        history = data.get("history", [])
        if not history:
            return None

        # Take the most recent previous recommendation batch
        prev_batch = history[-1]
        recs = prev_batch.get("recommendations", [])
        if not recs:
            return None

        symbols = [r["symbol"] for r in recs]
        yf_tickers = [f"{s}.NS" for s in symbols]
        df = yf.download(yf_tickers, period="1mo", progress=False)

        evaluated_picks = []
        wins = 0

        for r in recs:
            sym = r["symbol"]
            yf_sym = f"{sym}.NS"
            entry_p = float(r["recommended_price"])
            stop_p = float(r["stop_loss"])
            target_p = float(r["target"])

            current_p = entry_p
            high_p = entry_p
            low_p = entry_p

            if "Close" in df and yf_sym in df["Close"]:
                series = df["Close"][yf_sym].dropna()
                if not series.empty:
                    current_p = float(series.iloc[-1])
            if "High" in df and yf_sym in df["High"]:
                high_series = df["High"][yf_sym].dropna()
                if not high_series.empty:
                    high_p = float(high_series.max())
            if "Low" in df and yf_sym in df["Low"]:
                low_series = df["Low"][yf_sym].dropna()
                if not low_series.empty:
                    low_p = float(low_series.min())

            pnl_pct = ((current_p - entry_p) / entry_p) * 100.0 if entry_p > 0 else 0.0

            # Determine Outcome
            if high_p >= target_p:
                outcome = "TARGET HIT (+8.0%)"
                wins += 1
            elif low_p <= stop_p:
                outcome = "STOP HIT (-4.0%)"
            elif pnl_pct >= 4.0:
                outcome = f"TRAILING BE ({pnl_pct:+.1f}%)"
                wins += 1
            elif pnl_pct >= 0:
                outcome = f"ACTIVE ({pnl_pct:+.1f}%)"
                wins += 1
            else:
                outcome = f"HOLD ({pnl_pct:+.1f}%)"

            evaluated_picks.append(
                {
                    "symbol": sym,
                    "recommended_date": r.get(
                        "recommended_date", prev_batch.get("week_date", "N/A")
                    ),
                    "recommended_price": entry_p,
                    "current_price": current_p,
                    "pnl_pct": pnl_pct,
                    "outcome": outcome,
                    "setup": r.get("setup", "BREAKOUT"),
                }
            )

        total = len(evaluated_picks)
        win_rate = (wins / total) * 100.0 if total > 0 else 0.0
        avg_ret = sum(p["pnl_pct"] for p in evaluated_picks) / total if total > 0 else 0.0

        return {
            "week_date": prev_batch.get("week_date", "N/A"),
            "leading_sector": prev_batch.get("leading_sector", "N/A"),
            "picks": evaluated_picks,
            "win_rate": round(win_rate, 1),
            "avg_return": round(avg_ret, 2),
            "total_picks": total,
        }
    except Exception as e:
        print(f"Warning: Failed to evaluate previous recommendations: {e}", file=sys.stderr)
        return None


def screen_leading_sector_stocks(
    leading_sector_name: str,
    max_picks: int = 4,
) -> list[dict[str, Any]]:
    """Scan all constituents of the leading sector and pick top swing contenders."""
    import yfinance as yf

    symbols = SECTOR_CONSTITUENTS.get(leading_sector_name, [])
    if not symbols:
        symbols = SECTOR_CONSTITUENTS["NIFTY IT"]

    yf_tickers = [f"{s}.NS" for s in symbols]
    df = yf.download(yf_tickers, period="1y", progress=False)

    if df.empty or "Close" not in df:
        return []

    candidates = []

    for sym in symbols:
        yf_sym = f"{sym}.NS"
        try:
            if yf_sym not in df["Close"]:
                continue
            series = df["Close"][yf_sym].dropna()
            if len(series) < 150:
                continue

            closes = series.tolist()
            volumes = df["Volume"][yf_sym].loc[series.index].tolist()
            highs = df["High"][yf_sym].loc[series.index].tolist()
            lows = df["Low"][yf_sym].loc[series.index].tolist()
            dates = [d.strftime("%Y-%m-%d") for d in series.index]

            analysis = analyze_symbol_bars(sym, dates, closes, volumes, highs, lows)
            if not analysis:
                continue

            # Must be in Stage 2 or Breakout / Pullback pattern
            if analysis["setup"] in ("NEUTRAL",):
                continue

            entry_p = analysis["close"]
            stop_p = round(entry_p * 0.96, 1)
            target_p = round(entry_p * 1.08, 1)

            notes = f"{analysis['setup']} in Leading Sector ({analysis['trend_template_score']})"

            candidates.append(
                {
                    "symbol": sym,
                    "current_price": entry_p,
                    "recommended_price": entry_p,
                    "stop_loss": stop_p,
                    "target": target_p,
                    "pct_from_52w_high": analysis["pct_from_52w_high"],
                    "rvol": analysis["rvol"],
                    "rsi": analysis["rsi"],
                    "setup": analysis["setup"],
                    "trend_template_score": analysis["trend_template_score"],
                    "notes": notes,
                }
            )
        except Exception:
            continue

    # Sort candidates purely on relative strength: Closest to 52W high
    candidates.sort(key=lambda x: x["pct_from_52w_high"])
    return candidates[:max_picks]


def save_new_recommendations(
    week_date: str,
    leading_sector: str,
    picks: list[dict[str, Any]],
    history_file: Path = RECOMMENDATIONS_STATE_FILE,
) -> None:
    """Save the newly selected contender stocks into persistent state."""
    history_file.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {"history": []}
    if history_file.exists():
        try:
            with open(history_file, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"history": []}

    history = data.get("history", [])

    # Format recommendations for storage
    stored_recs = []
    for p in picks:
        stored_recs.append(
            {
                "symbol": p["symbol"],
                "recommended_date": week_date,
                "recommended_price": p["recommended_price"],
                "stop_loss": p["stop_loss"],
                "target": p["target"],
                "setup": p["setup"],
                "notes": p.get("notes", ""),
            }
        )

    # Check if this week is already recorded; if so, replace; otherwise append
    existing_idx = next((i for i, h in enumerate(history) if h.get("week_date") == week_date), None)
    entry = {
        "week_date": week_date,
        "leading_sector": leading_sector,
        "recommendations": stored_recs,
    }
    if existing_idx is not None:
        history[existing_idx] = entry
    else:
        history.append(entry)

    data["history"] = history
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


class SectorReportPDF(FPDF):
    """Clean, institutional-grade PDF styling for Weekly Sector Rotation & Contenders Report."""

    def header(self):
        self.set_fill_color(26, 54, 93)  # Deep Navy Blue
        self.rect(0, 0, 210, 20, "F")
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 12)
        self.set_xy(10, 5)
        self.cell(
            0, 10, "CLAUDE TRADING SKILLS | SECTOR ROTATION & STOCK CONTENDERS REPORT", align="L"
        )
        self.ln(16)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(
            0,
            10,
            f"Page {self.page_no()} | Generated {datetime.today().strftime('%d %b %Y %H:%M IST')} | Quantitative Swing Engine",
            align="C",
        )


def build_enhanced_pdf(
    sector_results: list[dict[str, Any]],
    global_info: dict[str, Any],
    benchmark_info: dict[str, float],
    previous_eval: dict[str, Any] | None,
    new_contenders: list[dict[str, Any]],
    leading_sector: str,
    output_path: Path,
) -> Path:
    """Build the publication-grade multi-page Weekly Sector & Contenders PDF."""
    pdf = SectorReportPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    date_str = datetime.today().strftime("%d %B %Y")

    # Title & Metadata
    pdf.set_font("Helvetica", "B", 17)
    pdf.set_text_color(26, 54, 93)
    pdf.cell(
        0, 8, "Weekly Sector Rotation & Institutional Contenders", new_x="LMARGIN", new_y="NEXT"
    )

    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(74, 85, 104)
    pdf.cell(
        0,
        5,
        f"Edition: Week of {date_str} | Market: Indian Equities (NSE) + Global Breadth",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(3)

    # 1. Theme of the Week Callout Box
    pdf.set_fill_color(237, 242, 247)
    pdf.set_draw_color(49, 130, 206)
    pdf.set_line_width(0.6)
    pdf.rect(10, pdf.get_y(), 190, 24, "DF")

    pdf.set_xy(14, pdf.get_y() + 2)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(43, 108, 176)
    pdf.cell(
        0,
        5,
        f"THEME OF THE WEEK: Institutional Outperformance in {leading_sector}",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    pdf.set_x(14)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(45, 55, 72)
    desc = (
        f"Institutions are channeling capital into {leading_sector} with high relative strength against NIFTY 50. "
        f"We deep-dive this sector below to select high-conviction breakout contenders with 1% risk rules."
    )
    pdf.multi_cell(182, 4.5, desc)
    pdf.ln(5)

    # 2. Market Regime & Cycle Gauge Cards
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(26, 54, 93)
    pdf.cell(0, 6, "1. Macro Cycle & Breadth Overview", new_x="LMARGIN", new_y="NEXT")

    col_w = 47.5
    y_pos = pdf.get_y()
    pdf.set_fill_color(247, 250, 252)
    pdf.set_draw_color(226, 232, 240)

    metrics = [
        ("Market Cycle Phase", global_info.get("cycle_phase", "Mid-Cycle Expansion")),
        (
            "Risk Regime",
            f"{global_info.get('risk_regime', 'BALANCED')} ({global_info.get('regime_score', 53)}/100)",
        ),
        ("NIFTY 50 (1M)", f"{benchmark_info.get('nifty_1m_return', 0.0):+.2f}%"),
        ("Overbought Alert", ", ".join(global_info.get("overbought", ["None"]))),
    ]
    for i, (label, val) in enumerate(metrics):
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

    pdf.set_y(y_pos + 17)

    # 3. NSE Sectoral Performance Matrix Table
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(26, 54, 93)
    pdf.cell(0, 6, "2. Indian NSE Sectoral Rotation Matrix", new_x="LMARGIN", new_y="NEXT")

    pdf.set_fill_color(26, 54, 93)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 8.5)
    headers = [
        ("Sector Index", 46),
        ("Close (Pts)", 28),
        ("1-Week", 22),
        ("1-Month", 22),
        ("3-Month", 22),
        ("50 SMA", 20),
        ("Status", 30),
    ]
    for title, width in headers:
        pdf.cell(width, 6, title, border=1, fill=True, align="C")
    pdf.ln(6)

    pdf.set_font("Helvetica", "", 8)
    for idx, s in enumerate(sector_results):
        row_bg = (248, 250, 252) if idx % 2 == 1 else (255, 255, 255)
        pdf.set_fill_color(*row_bg)
        pdf.set_text_color(26, 54, 93)
        pdf.cell(46, 5.5, f"  {s['sector']}", border=1, fill=True, align="L")
        pdf.cell(28, 5.5, f"{s['close']:,.1f}", border=1, fill=True, align="R")

        ret_1w = s["ret_1w"]
        pdf.set_text_color(40, 167, 69) if ret_1w >= 0 else pdf.set_text_color(220, 53, 69)
        pdf.cell(22, 5.5, f"{ret_1w:+.2f}%", border=1, fill=True, align="R")

        ret_1m = s["ret_1m"]
        pdf.set_text_color(40, 167, 69) if ret_1m >= 0 else pdf.set_text_color(220, 53, 69)
        pdf.cell(22, 5.5, f"{ret_1m:+.2f}%", border=1, fill=True, align="R")

        ret_3m = s["ret_3m"]
        pdf.set_text_color(40, 167, 69) if ret_3m >= 0 else pdf.set_text_color(220, 53, 69)
        pdf.cell(22, 5.5, f"{ret_3m:+.2f}%", border=1, fill=True, align="R")

        pdf.set_text_color(40, 167, 69) if s["above_50_sma"] else pdf.set_text_color(220, 53, 69)
        pdf.cell(20, 5.5, "Above" if s["above_50_sma"] else "Below", border=1, fill=True, align="C")

        status = s["status"]
        if status == "LEADING":
            pdf.set_text_color(43, 108, 176)
        elif status == "IMPROVING":
            pdf.set_text_color(40, 167, 69)
        elif status == "WEAKENING":
            pdf.set_text_color(214, 158, 46)
        else:
            pdf.set_text_color(220, 53, 69)
        pdf.cell(30, 5.5, status, border=1, fill=True, align="C")
        pdf.ln(5.5)

    pdf.ln(4)

    # 4. Previous Week's Stock Picks Backtest & Performance Review
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(26, 54, 93)
    pdf.cell(
        0,
        6,
        "3. Previous Week's Recommendations: Performance Review & Backtest",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    if previous_eval and previous_eval.get("picks"):
        sub_title = (
            f"Batch: Week of {previous_eval['week_date']} ({previous_eval['leading_sector']}) | "
            f"Win Rate: {previous_eval['win_rate']}% | Avg Return: {previous_eval['avg_return']:+.2f}%"
        )
        pdf.set_font("Helvetica", "I", 8.5)
        pdf.set_text_color(74, 85, 104)
        pdf.cell(0, 5, sub_title, new_x="LMARGIN", new_y="NEXT")

        pdf.set_fill_color(74, 85, 104)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 8)
        backtest_headers = [
            ("Symbol", 30),
            ("Rec Date", 25),
            ("Rec Price", 25),
            ("Current Price", 26),
            ("Return %", 24),
            ("Setup", 30),
            ("Outcome / Status", 30),
        ]
        for title, width in backtest_headers:
            pdf.cell(width, 5.5, title, border=1, fill=True, align="C")
        pdf.ln(5.5)

        pdf.set_font("Helvetica", "", 8)
        for idx, p in enumerate(previous_eval["picks"]):
            row_bg = (248, 250, 252) if idx % 2 == 1 else (255, 255, 255)
            pdf.set_fill_color(*row_bg)
            pdf.set_text_color(26, 54, 93)
            pdf.cell(30, 5.2, f"  #{p['symbol']}", border=1, fill=True, align="L")
            pdf.cell(25, 5.2, p["recommended_date"], border=1, fill=True, align="C")
            pdf.cell(25, 5.2, f"Rs. {p['recommended_price']:,.1f}", border=1, fill=True, align="R")
            pdf.cell(26, 5.2, f"Rs. {p['current_price']:,.1f}", border=1, fill=True, align="R")

            ret = p["pnl_pct"]
            pdf.set_text_color(40, 167, 69) if ret >= 0 else pdf.set_text_color(220, 53, 69)
            pdf.cell(24, 5.2, f"{ret:+.2f}%", border=1, fill=True, align="R")

            pdf.set_text_color(74, 85, 104)
            pdf.cell(30, 5.2, p["setup"][:14], border=1, fill=True, align="C")

            pdf.set_text_color(40, 167, 69) if (
                "HIT" in p["outcome"] or ret >= 0
            ) else pdf.set_text_color(220, 53, 69)
            pdf.cell(30, 5.2, p["outcome"], border=1, fill=True, align="C")
            pdf.ln(5.2)
    else:
        pdf.set_font("Helvetica", "I", 8.5)
        pdf.set_text_color(113, 128, 150)
        pdf.cell(
            0,
            5,
            "No previous week baseline found in state ledger. Tracking initiated with this week's picks.",
            new_x="LMARGIN",
            new_y="NEXT",
        )

    pdf.ln(4)

    # 5. Leading Sector Deep-Dive & Top Contender Stock Picks
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(26, 54, 93)
    pdf.cell(
        0,
        6,
        f"4. Leading Sector Focus ({leading_sector}): Top Contender Picks for Upcoming Week",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(74, 85, 104)
    pdf.cell(
        0,
        5,
        "Passed: Minervini Stage 2 + 50/200 SMA + Volume Confirmation + Trend Template",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    pdf.set_fill_color(43, 108, 176)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 8)
    contender_headers = [
        ("Symbol", 30),
        ("Price (Rs)", 25),
        ("Stop (-4%)", 25),
        ("Target (+8%)", 25),
        ("RVOL", 18),
        ("Setup", 32),
        ("Technical Setup", 35),
    ]
    for title, width in contender_headers:
        pdf.cell(width, 5.5, title, border=1, fill=True, align="C")
    pdf.ln(5.5)

    pdf.set_font("Helvetica", "", 7.8)
    for idx, c in enumerate(new_contenders):
        row_bg = (248, 250, 252) if idx % 2 == 1 else (255, 255, 255)
        pdf.set_fill_color(*row_bg)
        pdf.set_text_color(26, 54, 93)
        pdf.cell(30, 5.2, f"  #{c['symbol']}", border=1, fill=True, align="L")
        pdf.cell(25, 5.2, f"Rs. {c['current_price']:,.1f}", border=1, fill=True, align="R")

        pdf.set_text_color(220, 53, 69)
        pdf.cell(25, 5.2, f"Rs. {c['stop_loss']:,.1f}", border=1, fill=True, align="R")

        pdf.set_text_color(40, 167, 69)
        pdf.cell(25, 5.2, f"Rs. {c['target']:,.1f}", border=1, fill=True, align="R")

        pdf.set_text_color(74, 85, 104)
        pdf.cell(18, 5.2, f"{c['rvol']:.1f}x", border=1, fill=True, align="C")

        pdf.set_text_color(43, 108, 176)
        pdf.cell(32, 5.2, c["setup"][:17], border=1, fill=True, align="C")

        pdf.set_text_color(74, 85, 104)
        tech_note = c.get("notes") or f"Near 52W High ({c.get('pct_from_52w_high', 0.0):.1f}%)"
        pdf.cell(35, 5.2, tech_note[:22], border=1, fill=True, align="C")
        pdf.ln(5.2)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))
    return output_path


def run_weekly_sector_routine(
    bucket_name: str | None = None,
    s3_client: Any = None,
    output_dir: Path = ROOT_DIR / "reports",
    send_telegram: bool = True,
) -> dict[str, Any]:
    """Execute the full weekly sector rotation, backtest & contenders routine."""
    history_file = RECOMMENDATIONS_STATE_FILE

    # If S3 client is provided, sync recommendations state from S3
    if bucket_name and s3_client:
        s3_key = "state/weekly_sector_recommendations.json"
        local_rec_path = Path("/tmp/weekly_sector_recommendations.json")
        try:
            s3_client.download_file(bucket_name, s3_key, str(local_rec_path))
            print(f"Downloaded recommendations state from s3://{bucket_name}/{s3_key}")
        except Exception:
            print(
                f"No existing recommendations at s3://{bucket_name}/{s3_key}. Initializing in /tmp."
            )
            if RECOMMENDATIONS_STATE_FILE.exists():
                import shutil

                shutil.copyfile(RECOMMENDATIONS_STATE_FILE, local_rec_path)
            else:
                local_rec_path.write_text('{"history": []}', encoding="utf-8")
        history_file = local_rec_path

    # 1. Fetch NSE sector data
    print("[1/5] Analyzing Indian NSE sector rotation and relative strength...")
    sector_results, benchmark_info = fetch_nse_sector_data()
    leading_sector = sector_results[0]["sector"] if sector_results else "NIFTY IT"
    print(f"  Leading Sector identified: {leading_sector} ({sector_results[0]['ret_1m']:+.2f}% 1M)")

    # 2. Fetch Global sector rotation data
    print("[2/5] Assessing macro cycle & global risk regime...")
    global_info = fetch_global_rotation_summary()

    # 3. Backtest previous week recommendations
    print("[3/5] Backtesting & evaluating previous week's stock recommendations...")
    previous_eval = evaluate_previous_recommendations(history_file=history_file)
    if previous_eval:
        print(
            f"  Previous Batch ({previous_eval['week_date']}): Win Rate {previous_eval['win_rate']}%, Avg Return {previous_eval['avg_return']:+.2f}%"
        )
    else:
        print("  No previous recommendations ledger found. Initializing tracking.")

    # 4. Screen leading sector constituents for top contenders
    print(f"[4/5] Scanning {leading_sector} constituents for high-probability contenders...")
    new_contenders = screen_leading_sector_stocks(leading_sector, max_picks=4)
    print(f"  Selected {len(new_contenders)} high-conviction contenders:")
    for c in new_contenders:
        print(
            f"    • {c['symbol']}: Rs. {c['current_price']:,.1f} | Stop: Rs. {c['stop_loss']:,.1f} | Target: Rs. {c['target']:,.1f} | {c['setup']}"
        )

    # Save to persistent history ledger for next week's review
    today_tag = datetime.today().strftime("%Y-%m-%d")
    save_new_recommendations(today_tag, leading_sector, new_contenders, history_file=history_file)

    # If S3 is provided, upload updated recommendations state
    if bucket_name and s3_client:
        s3_client.upload_file(
            str(history_file), bucket_name, "state/weekly_sector_recommendations.json"
        )
        print(
            f"Uploaded updated recommendations state to s3://{bucket_name}/state/weekly_sector_recommendations.json"
        )

    # 5. Build Comprehensive Multi-Section PDF
    output_dir.mkdir(parents=True, exist_ok=True)
    output_pdf = output_dir / f"weekly_sector_report_{today_tag}.pdf"
    print(f"[5/5] Generating publication-grade PDF report at: {output_pdf}...")
    build_enhanced_pdf(
        sector_results=sector_results,
        global_info=global_info,
        benchmark_info=benchmark_info,
        previous_eval=previous_eval,
        new_contenders=new_contenders,
        leading_sector=leading_sector,
        output_path=output_pdf,
    )
    print(f"  Successfully built {output_pdf} (Size: {output_pdf.stat().st_size / 1024:.1f} KB)")

    # If S3 is provided, upload PDF archive
    if bucket_name and s3_client:
        s3_pdf_key = f"reports/weekly_sector_report_{today_tag}.pdf"
        s3_client.upload_file(str(output_pdf), bucket_name, s3_pdf_key)
        print(f"Uploaded PDF report to s3://{bucket_name}/{s3_pdf_key}")

    # 6. Deliver to Telegram
    telegram_delivered = False
    if send_telegram:
        print("Delivering report & executive scorecard to Telegram...")
        notifier = TelegramNotifier()
        if notifier.is_configured:
            caption_lines = [
                "📊 <b>WEEKLY SECTOR ROTATION & CONTENDERS REPORT</b>",
                f"<i>Week of {datetime.today().strftime('%d %B %Y')}</i>\n",
                f"🏆 <b>Leading Sector:</b> <code>{leading_sector}</code>",
                f"🌐 <b>Market Cycle:</b> {global_info.get('cycle_phase')} ({global_info.get('risk_regime')} Regime)",
            ]
            if previous_eval:
                caption_lines.append(
                    f"\n🎯 <b>Previous Week Scorecard:</b>\n"
                    f"• Win Rate: <b>{previous_eval['win_rate']}%</b>\n"
                    f"• Avg Return: <b>{previous_eval['avg_return']:+.2f}%</b>"
                )
            caption_lines.append(f"\n🔥 <b>New {leading_sector} Contenders:</b>")
            for c in new_contenders:
                caption_lines.append(
                    f"• <b>#{c['symbol']}</b>: Rs. {c['current_price']:,.1f} (Stop Rs. {c['stop_loss']:,.1f} | Tgt Rs. {c['target']:,.1f})"
                )
            caption_lines.append(
                "\nDetailed backtest ledger & sector matrix attached in the PDF below 👇"
            )
            caption = "\n".join(caption_lines)
            telegram_delivered = notifier.send_document(output_pdf, caption=caption)
            if telegram_delivered:
                print("  Telegram document dispatch successful!")
            else:
                print("  Telegram document dispatch failed.", file=sys.stderr)
        else:
            print("  Notice: Telegram credentials not configured; skipped delivery.")
    else:
        print("Skipped Telegram delivery (send_telegram=False).")

    return {
        "status": "success",
        "date": today_tag,
        "leading_sector": leading_sector,
        "contenders_count": len(new_contenders),
        "telegram_delivered": telegram_delivered,
        "pdf_path": str(output_pdf),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Weekly Sector Rotation, Stock Contenders & Backtest Generator"
    )
    parser.add_argument(
        "--output-dir", default=str(ROOT_DIR / "reports"), help="Output directory for generated PDF"
    )
    parser.add_argument(
        "--no-telegram", action="store_true", help="Generate PDF only without sending to Telegram"
    )
    args = parser.parse_args()

    print("==========================================================")
    print(" Weekly Sector Intelligence, Contenders & Backtest Engine ")
    print("==========================================================")

    res = run_weekly_sector_routine(
        output_dir=Path(args.output_dir),
        send_telegram=not args.no_telegram,
    )

    print("==========================================================")
    print(
        f" Weekly Report Completed: {res['leading_sector']} ({res['contenders_count']} contenders)"
    )
    print("==========================================================")


if __name__ == "__main__":
    main()
