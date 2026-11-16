#!/usr/bin/env python3
"""
NSE / Indian Stock Market Screener for Claude Trading Skills.

Screens Indian equities (Nifty Smallcap 250, Nifty 50, Nifty Next 50, or
custom watchlists) for Mark Minervini's Stage 2 Trend Template, Volume
Breakouts, and Pullback-to-Moving-Average setups.

Data is fetched directly from Yahoo Finance in parallel batches — no manual CSV
downloads required.

Usage:
    # Screen NIFTY SMALLCAP 250 for Breakouts
    python3 scripts/screen_indian_stocks.py --universe niftysmallcap250 --strategy breakout

    # Screen NIFTY SMALLCAP 250 for Pullbacks with limit of 50
    python3 scripts/screen_indian_stocks.py --universe niftysmallcap250 --strategy pullback --limit 50

    # Screen specific symbols
    python3 scripts/screen_indian_stocks.py --symbols ATHERENERG BEML ANANDRATHI
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any

# ==============================================================================
# CONSTITUENT UNIVERSES (Directly embedded - no CSV downloads required)
# ==============================================================================

NIFTY_50_TICKERS = [
    "ADANIENT",
    "ADANIPORTS",
    "APOLLOHOSP",
    "ASIANPAINT",
    "AXISBANK",
    "BAJAJ-AUTO",
    "BAJFINANCE",
    "BAJAJFINSV",
    "BEL",
    "BPCL",
    "BHARTIARTL",
    "BRITANNIA",
    "CIPLA",
    "COALINDIA",
    "DRREDDY",
    "EICHERMOT",
    "GRASIM",
    "HCLTECH",
    "HDFCBANK",
    "HDFCLIFE",
    "HEROMOTOCO",
    "HINDALCO",
    "HINDUNILVR",
    "ICICIBANK",
    "ITC",
    "INDUSINDBK",
    "INFY",
    "JSWSTEEL",
    "KOTAKBANK",
    "LT",
    "M&M",
    "MARUTI",
    "NTPC",
    "NESTLEIND",
    "ONGC",
    "POWERGRID",
    "RELIANCE",
    "SBILIFE",
    "SHRIRAMFIN",
    "SBIN",
    "SUNPHARMA",
    "TCS",
    "TATACONSUM",
    "TATAMOTORS",
    "TATASTEEL",
    "TECHM",
    "TITAN",
    "TRENT",
    "ULTRACEMCO",
    "WIPRO",
]

NIFTY_NEXT_50_TICKERS = [
    "ABB",
    "ADANIENSOL",
    "ADANIGREEN",
    "AMBUJACEM",
    "BANKBARODA",
    "BOSCHLTD",
    "CANBK",
    "CHOLAFIN",
    "COLPAL",
    "DLF",
    "GAIL",
    "GODREJCP",
    "HAL",
    "HAVELLS",
    "ICICIGI",
    "ICICIPRULI",
    "IOC",
    "IRCTC",
    "IRFC",
    "JINDALSTEL",
    "JIOFIN",
    "LICI",
    "LTIM",
    "MOTHERSON",
    "NAUKRI",
    "PIDILITIND",
    "PFC",
    "PNB",
    "RECLTD",
    "SIEMENS",
    "TORNTPHARM",
    "TVSMOTOR",
    "UNITDSPR",
    "VBL",
    "ZOMATO",
]

# Official 249 constituents of the NIFTY SMALLCAP 250 index
NIFTY_SMALLCAP_250_TICKERS = [
    "ACC",
    "ACMESOLAR",
    "AWL",
    "AADHARHFC",
    "AARTIIND",
    "AAVAS",
    "ACE",
    "ACUTAAS",
    "ABREL",
    "ABSLAMC",
    "CPPLUS",
    "AEGISLOG",
    "AEGISVOPAK",
    "AETHER",
    "AFCONS",
    "AFFLE",
    "ABDL",
    "AMBER",
    "ANANDRATHI",
    "ANANTRAJ",
    "ANGELONE",
    "ANURAS",
    "APOLLOTYRE",
    "APTUS",
    "ASAHIINDIA",
    "ATHERENERG",
    "ATUL",
    "AVANTIFEED",
    "AZAD",
    "BEML",
    "BLS",
    "BAGMANE",
    "BALRAMCHIN",
    "BANDHANBNK",
    "BATAINDIA",
    "BELRISE",
    "BHARATCOAL",
    "BSOFT",
    "BBOX",
    "FIRSTCRY",
    "BLUESTARCO",
    "BRIGADE",
    "CCL",
    "CESC",
    "CGCL",
    "CIEINDIA",
    "CRISIL",
    "CAMPUS",
    "CAMS",
    "CANFINHOME",
    "CASTROLIND",
    "CEATLTD",
    "CENTURYPLY",
    "CENTURYTEX",
    "CERA",
    "CHALET",
    "CHAMBLFERT",
    "CHOLAHLDNG",
    "CLEAN",
    "COCHINSHIP",
    "COHANCE",
    "COROMANDEL",
    "CREDITACC",
    "CROMPTON",
    "CUB",
    "CUPID",
    "CYIENT",
    "DATAPATTNS",
    "DEEPAKFERT",
    "DEEPAKNTR",
    "DELHIVERY",
    "DEVYANI",
    "DOMS",
    "EIDPARRY",
    "EIHOTEL",
    "EMAMILTD",
    "EMKAYTOOLS",
    "EMMVEE",
    "ENDURANCE",
    "ENGINERSIN",
    "EQUITASBNK",
    "ERIS",
    "ESCORTS",
    "EXIDEIND",
    "FDC",
    "FINCABLES",
    "FINPIPE",
    "FSL",
    "FORTIS",
    "GRINFRA",
    "GALLANTT",
    "GICRE",
    "GILLETTE",
    "GLAXO",
    "GLENMARK",
    "MEDANTA",
    "GODFRYPHLP",
    "GODREJIND",
    "GRINDWELL",
    "GRSE",
    "GSFC",
    "GSPL",
    "GUJGASLTD",
    "GNFC",
    "HBLPOWER",
    "HGINFRA",
    "HAPPSTMNDS",
    "HINDCOPPER",
    "HINDOILEXP",
    "HOMEFIRST",
    "HONASA",
    "HUDCO",
    "IDBI",
    "IDFCFIRSTB",
    "IFCI",
    "IIFL",
    "IEX",
    "INDGN",
    "INDIACEM",
    "INDIAMART",
    "INDIASHLTR",
    "INOXINDIA",
    "INOXWIND",
    "INTELLECT",
    "IONEXCHANG",
    "IPCALAB",
    "IRB",
    "IRCON",
    "ITI",
    "JBCHEPHARM",
    "JKCEMENT",
    "JKLAKSHMI",
    "JKTYRE",
    "JMFINANCIL",
    "JSWINFRA",
    "JTEKTINDIA",
    "JUBLFOOD",
    "JUBLINGREA",
    "JUBLPHARMA",
    "JUNIPER",
    "JYOTHYLAB",
    "KNRCON",
    "KPITTECH",
    "KALYANKJIL",
    "KARURVYSYA",
    "KAYNES",
    "KEC",
    "KEI",
    "KFINTECH",
    "KIRLOSENG",
    "KIMS",
    "KIMS",
    "LALPATHLAB",
    "LEMONTREE",
    "LLOYDSENGG",
    "M&MFIN",
    "MMTC",
    "MRF",
    "MSUMI",
    "MAHINDCIE",
    "MANAPPURAM",
    "MAPMYINDIA",
    "METROPOLIS",
    "MINDACORP",
    "MOTILALOFS",
    "NATCOPHARM",
    "NBCC",
    "NCC",
    "NETWORK18",
    "NH",
    "NIACL",
    "NLCINDIA",
    "NUVOCO",
    "OFSS",
    "OIL",
    "OLECTRA",
    "PAYTM",
    "PCBL",
    "PGHL",
    "PNBHOUSING",
    "PNCINFRA",
    "PVRINOX",
    "POLYMED",
    "POONAWALLA",
    "PRESTIGE",
    "PRINCEPIPE",
    "RBLBANK",
    "RITES",
    "RADICO",
    "RAILTEL",
    "RAMCOCEM",
    "RAYMOND",
    "REDINGTON",
    "RPOWER",
    "ROUTE",
    "SAFARI",
    "SAIL",
    "SBICARD",
    "SCHNEIDER",
    "SHOPERSTOP",
    "SHYAMMETL",
    "SOBHA",
    "SOLARINDS",
    "SONACOMS",
    "STARHEALTH",
    "SUNDARMFIN",
    "SUNDRMFAST",
    "SUNTV",
    "SUPREMEIND",
    "SUZLON",
    "SWANENERGY",
    "SYMPHONY",
    "SYRMA",
    "TCIEXP",
    "TDPOWERSYS",
    "TRITURBINE",
    "TATACHEM",
    "TATACOMM",
    "TATAELXSI",
    "TATATECH",
    "TENNIND",
    "THERMAX",
    "TIMKEN",
    "TRIDENT",
    "TRITURBINE",
    "TIINDIA",
    "UCOBANK",
    "UJJIVANSFB",
    "USHAMART",
    "UTIAMC",
    "VGUARD",
    "VIPIND",
    "VTL",
    "VAIBHAVGBL",
    "VARROC",
    "VEDL",
    "VEDPOWER",
    "VIJAYA",
    "VOLTAS",
    "WELCORP",
    "WELSPUNLIV",
    "WHIRLPOOL",
    "WOCKPHARMA",
    "ZFCVINDIA",
    "ZEEL",
    "ZENTEC",
    "ZENSARTECH",
    "ZYDUSWELL",
    "ECLERX",
]


def calculate_sma(series: list[float], window: int) -> list[float]:
    """Calculate Simple Moving Average."""
    sma = []
    for i in range(len(series)):
        if i + 1 < window:
            sma.append(float("nan"))
        else:
            sma.append(sum(series[i + 1 - window : i + 1]) / window)
    return sma


def calculate_ema(series: list[float], window: int) -> list[float]:
    """Calculate Exponential Moving Average."""
    if len(series) < window:
        return [float("nan")] * len(series)

    k = 2.0 / (window + 1)
    ema = [float("nan")] * (window - 1)
    first_sma = sum(series[:window]) / window
    ema.append(first_sma)

    for i in range(window, len(series)):
        current_ema = (series[i] * k) + (ema[-1] * (1 - k))
        ema.append(current_ema)

    return ema


def calculate_rsi(series: list[float], window: int = 14) -> float:
    """Calculate the Relative Strength Index of the latest bar."""
    if len(series) <= window:
        return 50.0

    gains = []
    losses = []
    for i in range(1, len(series)):
        delta = series[i] - series[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    avg_gain = sum(gains[:window]) / window
    avg_loss = sum(losses[:window]) / window

    for i in range(window, len(gains)):
        avg_gain = (avg_gain * (window - 1) + gains[i]) / window
        avg_loss = (avg_loss * (window - 1) + losses[i]) / window

    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def evaluate_stage_2_trend_template(
    close: float,
    sma_50: float,
    sma_150: float,
    sma_200: float,
    sma_200_20d_ago: float,
    high_52w: float,
    low_52w: float,
) -> tuple[bool, int, list[str]]:
    """Minervini 7-point Trend Template criteria for Stage 2 Uptrend."""
    passed_rules = 0
    checks = []

    if close > sma_150 and close > sma_200:
        passed_rules += 1
        checks.append("Price > 150 & 200 SMA")

    if sma_150 > sma_200:
        passed_rules += 1
        checks.append("150 SMA > 200 SMA")

    if sma_200 > sma_200_20d_ago:
        passed_rules += 1
        checks.append("200 SMA trending up")

    if sma_50 > sma_150 and sma_50 > sma_200:
        passed_rules += 1
        checks.append("50 SMA > 150 & 200 SMA")

    if close > sma_50:
        passed_rules += 1
        checks.append("Price > 50 SMA")

    if low_52w > 0 and (close - low_52w) / low_52w >= 0.30:
        passed_rules += 1
        checks.append(">= 30% above 52w low")

    if high_52w > 0 and (high_52w - close) / high_52w <= 0.25:
        passed_rules += 1
        checks.append("Within 25% of 52w high")

    is_stage_2 = passed_rules >= 6
    return is_stage_2, passed_rules, checks


def analyze_symbol_bars(
    symbol: str,
    dates: list[str],
    closes: list[float],
    volumes: list[float],
    highs: list[float],
    lows: list[float],
) -> dict[str, Any] | None:
    """Analyze OHLCV bars for a single stock."""
    n = len(closes)
    if n < 200:
        return None

    current_close = closes[-1]
    current_volume = volumes[-1]

    sma_50_series = calculate_sma(closes, 50)
    sma_150_series = calculate_sma(closes, 150)
    sma_200_series = calculate_sma(closes, 200)
    vol_sma_20_series = calculate_sma(volumes, 20)

    sma_50 = sma_50_series[-1]
    sma_150 = sma_150_series[-1]
    sma_200 = sma_200_series[-1]
    sma_200_prev = sma_200_series[-20] if len(sma_200_series) >= 20 else sma_200
    avg_vol_20 = vol_sma_20_series[-1] if vol_sma_20_series[-1] > 0 else 1.0

    rvol = current_volume / avg_vol_20 if avg_vol_20 > 0 else 1.0

    lookback = min(n, 250)
    high_52w = max(highs[-lookback:])
    low_52w = min(lows[-lookback:])

    pct_from_52w_high = ((high_52w - current_close) / high_52w) * 100.0 if high_52w > 0 else 0.0
    pct_above_52w_low = ((current_close - low_52w) / low_52w) * 100.0 if low_52w > 0 else 0.0

    rsi = calculate_rsi(closes, 14)
    ema_20_series = calculate_ema(closes, 20)
    ema_20 = ema_20_series[-1]

    is_stage_2, passed_rules, checks = evaluate_stage_2_trend_template(
        close=current_close,
        sma_50=sma_50,
        sma_150=sma_150,
        sma_200=sma_200,
        sma_200_20d_ago=sma_200_prev,
        high_52w=high_52w,
        low_52w=low_52w,
    )

    is_breakout = (
        is_stage_2
        and (pct_from_52w_high <= 8.0)
        and (rvol >= 1.2 or current_close >= high_52w * 0.98)
    )
    is_pullback = (
        is_stage_2
        and (current_close > sma_200)
        and (abs(current_close - ema_20) / ema_20 <= 0.03 or (40.0 <= rsi <= 55.0))
    )

    setup_tag = "NEUTRAL"
    if is_breakout:
        setup_tag = "BREAKOUT"
    elif is_pullback:
        setup_tag = "PULLBACK"
    elif is_stage_2:
        setup_tag = "STAGE_2_UPTREND"

    return {
        "symbol": symbol,
        "date": dates[-1] if dates else datetime.today().strftime("%Y-%m-%d"),
        "close": round(current_close, 2),
        "sma_50": round(sma_50, 2),
        "sma_200": round(sma_200, 2),
        "52w_high": round(high_52w, 2),
        "pct_from_52w_high": round(pct_from_52w_high, 2),
        "pct_above_52w_low": round(pct_above_52w_low, 2),
        "rvol": round(rvol, 2),
        "rsi": round(rsi, 1),
        "is_stage_2": is_stage_2,
        "trend_template_score": f"{passed_rules}/7",
        "setup": setup_tag,
        "checks": checks,
    }


def fetch_and_analyze_batch(symbols: list[str], chunk_size: int = 40) -> list[dict[str, Any]]:
    """
    Fetch 1 year of daily bars from Yahoo Finance in parallel chunked batches.
    Chunking prevents HTTP timeouts and socket dropouts when scanning 250+ symbols.
    """
    import yfinance as yf

    results = []
    # Deduplicate while preserving order
    clean_symbols = list(dict.fromkeys(s.replace(".NS", "").upper() for s in symbols if s))

    # Split into chunks of 40 symbols for robust downloads
    for i in range(0, len(clean_symbols), chunk_size):
        chunk = clean_symbols[i : i + chunk_size]
        yf_tickers = [f"{s}.NS" for s in chunk]

        try:
            df = yf.download(yf_tickers, period="1y", progress=False)
            if df.empty or "Close" not in df:
                continue

            for sym in chunk:
                yf_sym = f"{sym}.NS"
                try:
                    if yf_sym in df["Close"]:
                        series = df["Close"][yf_sym].dropna()
                        if len(series) < 200:
                            continue
                        closes = series.tolist()
                        volumes = df["Volume"][yf_sym].loc[series.index].tolist()
                        highs = df["High"][yf_sym].loc[series.index].tolist()
                        lows = df["Low"][yf_sym].loc[series.index].tolist()
                        dates = [d.strftime("%Y-%m-%d") for d in series.index]
                    else:
                        # Fallback when only a single ticker was returned
                        series = df["Close"].dropna()
                        if len(series) < 200:
                            continue
                        closes = series.tolist()
                        volumes = df["Volume"].dropna().tolist()
                        highs = df["High"].dropna().tolist()
                        lows = df["Low"].dropna().tolist()
                        dates = [d.strftime("%Y-%m-%d") for d in series.index]

                    analysis = analyze_symbol_bars(sym, dates, closes, volumes, highs, lows)
                    if analysis:
                        results.append(analysis)
                except Exception:
                    continue

        except Exception as e:
            print(f"Warning: Chunk download error: {e}", file=sys.stderr)

    return results


def run_screener(
    symbols: list[str],
    strategy: str = "breakout",
) -> list[dict[str, Any]]:
    """Screen the symbol universe and return ranked candidates based on pure technical price and volume action."""
    all_analyzed = fetch_and_analyze_batch(symbols)
    results = []

    for res in all_analyzed:
        if strategy == "breakout":
            if res["setup"] in ("BREAKOUT", "STAGE_2_UPTREND"):
                results.append(res)
        elif strategy == "pullback":
            if res["setup"] in ("PULLBACK", "STAGE_2_UPTREND"):
                results.append(res)
        elif strategy == "all":
            results.append(res)

    # Ranking:
    # 1. Highest trend template score (if scanning all)
    # 2. Closeness to 52-week high (pure technical relative strength)
    if strategy == "all":
        results.sort(
            key=lambda x: (
                -int(x["trend_template_score"].split("/")[0]),
                x["pct_from_52w_high"],
            )
        )
    else:
        results.sort(key=lambda x: x["pct_from_52w_high"])

    return results


def format_screener_markdown(
    results: list[dict[str, Any]], strategy: str, universe_name: str = "NSE"
) -> str:
    """Generate markdown report of screened results."""
    date_str = datetime.today().strftime("%Y-%m-%d")
    lines = [
        f"# {universe_name} Screener Report ({strategy.upper()})",
        f"**Date:** {date_str} | **Candidates Found:** {len(results)}\n",
        "| Symbol | Close (₹) | 50 SMA | 200 SMA | % From 52W High | RVOL | RSI | Trend Score | Setup |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    for r in results:
        lines.append(
            f"| **{r['symbol']}** | ₹{r['close']:.2f} | ₹{r['sma_50']:.2f} | ₹{r['sma_200']:.2f} | "
            f"{r['pct_from_52w_high']:.1f}% | {r['rvol']:.2f}x | {r['rsi']:.1f} | "
            f"{r['trend_template_score']} | `{r['setup']}` |"
        )

    if not results:
        lines.append("\n*No stocks currently passed the strict Stage 2 / Breakout filters.*")

    return "\n".join(lines)


def parse_args():
    parser = argparse.ArgumentParser(
        description="NSE / Indian Stock Market Screener for Claude Trading Skills."
    )
    parser.add_argument(
        "--universe",
        choices=["niftysmallcap250", "niftysmallcap", "nifty50", "niftynext50", "nifty100"],
        default="niftysmallcap250",
        help="Predefined ticker universe to scan (default: niftysmallcap250)",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        help="Custom list of NSE stock symbols (e.g. ATHERENERG BEML ANANDRATHI)",
    )
    parser.add_argument(
        "--strategy",
        choices=["breakout", "pullback", "all"],
        default="breakout",
        help="Screening filter strategy (default: breakout)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of stocks to scan (e.g. --limit 50)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Optional directory to save Markdown & JSON reports (e.g. reports/)",
    )
    parser.add_argument(
        "--format",
        choices=["table", "json", "markdown"],
        default="table",
        help="Output format (default: table)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.symbols:
        symbols = args.symbols
        universe_label = "Custom Watchlist"
    elif args.universe in ("niftysmallcap250", "niftysmallcap"):
        symbols = NIFTY_SMALLCAP_250_TICKERS
        universe_label = "NIFTY SMALLCAP 250"
    elif args.universe == "nifty50":
        symbols = NIFTY_50_TICKERS
        universe_label = "NIFTY 50"
    elif args.universe == "niftynext50":
        symbols = NIFTY_NEXT_50_TICKERS
        universe_label = "NIFTY NEXT 50"
    elif args.universe == "nifty100":
        symbols = NIFTY_50_TICKERS + NIFTY_NEXT_50_TICKERS
        universe_label = "NIFTY 100"
    else:
        symbols = NIFTY_SMALLCAP_250_TICKERS
        universe_label = "NIFTY SMALLCAP 250"

    if args.limit and args.limit > 0:
        symbols = symbols[: args.limit]

    print(
        f"Scanning {len(symbols)} stocks from {universe_label} for '{args.strategy}' setups directly from Yahoo Finance..."
    )
    candidates = run_screener(symbols, strategy=args.strategy)

    output = format_screener_markdown(
        candidates, strategy=args.strategy, universe_name=universe_label
    )
    if args.format == "json":
        print(json.dumps(candidates, indent=2))
    else:
        print("\n" + output)

    if args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)
        timestamp = datetime.today().strftime("%Y-%m-%d_%H%M%S")
        prefix = f"{args.universe}_{args.strategy}_{timestamp}"
        md_path = os.path.join(args.output_dir, f"{prefix}.md")
        json_path = os.path.join(args.output_dir, f"{prefix}.json")

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(output)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(candidates, f, indent=2)

        print(f"\nSaved reports to:\n- {md_path}\n- {json_path}")


if __name__ == "__main__":
    main()
