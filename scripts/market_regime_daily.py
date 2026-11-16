#!/usr/bin/env python3
"""
Market Regime Daily Analyzer for Indian Equities (NSE).

Evaluates the macro health and trend template of the benchmark index (NIFTY 50 - ^NSEI)
before allowing new swing trade capital deployment.

Classifies market posture into:
- CONFIRMED_UPTREND (ALLOW): Full deployment (up to 5 positions, 100% capacity).
- UPTREND_UNDER_PRESSURE (RESTRICT): Defensive posture (cap positions at 2, require RVOL >= 1.5).
- MARKET_CORRECTION (CASH_PRIORITY): Zero new buys allowed; protect open trades and preserve cash.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
BENCHMARK_TICKER = "^NSEI"


def calculate_sma(series: list[float], window: int) -> list[float]:
    """Calculate Simple Moving Average."""
    sma = []
    for i in range(len(series)):
        if i < window - 1:
            sma.append(float("nan"))
        else:
            window_slice = series[i - window + 1 : i + 1]
            sma.append(sum(window_slice) / window)
    return sma


def evaluate_nifty_regime(
    dates: list[str],
    closes: list[float],
    volumes: list[float] | None = None,
) -> dict[str, Any]:
    """
    Evaluate NIFTY 50 trend template and classify the daily market regime.
    """
    n = len(closes)
    if n < 200:
        return {
            "status": "INSUFFICIENT_DATA",
            "posture": "RESTRICT",
            "reason": f"Insufficient bars ({n} < 200) to evaluate 200 SMA regime",
            "max_positions_cap": 2,
            "metrics": {},
        }

    current_close = closes[-1]
    sma_50_series = calculate_sma(closes, 50)
    sma_200_series = calculate_sma(closes, 200)

    sma_50 = sma_50_series[-1]
    sma_200 = sma_200_series[-1]
    sma_200_20d_ago = sma_200_series[-21] if n >= 221 else sma_200_series[0]

    high_52w = max(closes[-250:]) if n >= 250 else max(closes)
    pct_from_52w_high = ((high_52w - current_close) / high_52w) * 100.0 if high_52w > 0 else 0.0

    ret_5d = (
        ((current_close - closes[-6]) / closes[-6]) * 100.0 if n >= 6 and closes[-6] > 0 else 0.0
    )
    sma_200_slope_positive = (
        (sma_200 >= sma_200_20d_ago) if not math.isnan(sma_200_20d_ago) else True
    )
    above_50_sma = current_close > sma_50
    above_200_sma = current_close > sma_200
    sma_50_above_200 = sma_50 > sma_200

    metrics = {
        "date": dates[-1] if dates else datetime.now(IST).strftime("%Y-%m-%d"),
        "nifty_close": round(current_close, 2),
        "sma_50": round(sma_50, 2),
        "sma_200": round(sma_200, 2),
        "above_50_sma": above_50_sma,
        "above_200_sma": above_200_sma,
        "sma_50_above_200": sma_50_above_200,
        "sma_200_trending_up": sma_200_slope_positive,
        "pct_from_52w_high": round(pct_from_52w_high, 2),
        "ret_5d_pct": round(ret_5d, 2),
    }

    # Classification Logic
    if above_50_sma and above_200_sma and sma_50_above_200 and sma_200_slope_positive:
        return {
            "status": "CONFIRMED_UPTREND",
            "posture": "ALLOW",
            "reason": "NIFTY 50 trading above rising 50 SMA and 200 SMA (Strong Bullish Alignment)",
            "max_positions_cap": 5,
            "metrics": metrics,
        }
    elif above_200_sma:
        return {
            "status": "UPTREND_UNDER_PRESSURE",
            "posture": "RESTRICT",
            "reason": (
                "NIFTY 50 below 50 SMA or moving average slope flattening; "
                "defensive posture (capped at 2 positions, require high RVOL)"
            ),
            "max_positions_cap": 2,
            "metrics": metrics,
        }
    else:
        return {
            "status": "MARKET_CORRECTION",
            "posture": "CASH_PRIORITY",
            "reason": "NIFTY 50 broke below 200 SMA (Severe Correction / Bearish Distribution)",
            "max_positions_cap": 0,
            "metrics": metrics,
        }


def format_market_regime_markdown(regime: dict[str, Any]) -> str:
    """Format market regime status into Markdown."""
    m = regime.get("metrics", {})
    status = regime.get("status", "UNKNOWN")
    posture = regime.get("posture", "UNKNOWN")
    reason = regime.get("reason", "")
    cap = regime.get("max_positions_cap", 0)

    lines = [
        "# NIFTY 50 Daily Market Regime",
        f"**Status:** `{status}` | **Posture:** `{posture}` | **Max Slots Cap:** {cap}",
        f"**Reason:** {reason}\n",
        "## Key Trend Indicators",
        f"- **NIFTY Close:** ₹{m.get('nifty_close', 0.0):,.2f}",
        f"- **50-Day SMA:** ₹{m.get('sma_50', 0.0):,.2f} ({'Above' if m.get('above_50_sma') else 'Below'})",
        f"- **200-Day SMA:** ₹{m.get('sma_200', 0.0):,.2f} ({'Above' if m.get('above_200_sma') else 'Below'})",
        f"- **SMA 50 vs 200:** {'Golden Cross (50 > 200)' if m.get('sma_50_above_200') else 'Death Cross (50 < 200)'}",
        f"- **200 SMA Slope:** {'Rising' if m.get('sma_200_trending_up') else 'Falling / Flat'}",
        f"- **From 52-Week High:** -{m.get('pct_from_52w_high', 0.0):.2f}%",
        f"- **5-Day Return:** {m.get('ret_5d_pct', 0.0):+.2f}%",
    ]
    return "\n".join(lines)


def fetch_nifty_daily_bars(period: str = "1y") -> tuple[list[str], list[float], list[float]]:
    """Fetch benchmark daily bars from Yahoo Finance."""
    import yfinance as yf

    df = yf.download(BENCHMARK_TICKER, period=period, progress=False)
    if df.empty or "Close" not in df:
        return [], [], []

    series = df["Close"].dropna()
    dates = [d.strftime("%Y-%m-%d") for d in series.index]
    closes = series.tolist()
    volumes = df["Volume"].dropna().tolist() if "Volume" in df else []
    return dates, closes, volumes


def get_current_market_regime() -> dict[str, Any]:
    """Fetch live NIFTY 50 data and evaluate the current market regime."""
    try:
        dates, closes, volumes = fetch_nifty_daily_bars()
        if not closes:
            return {
                "status": "FETCH_ERROR",
                "posture": "RESTRICT",
                "reason": "Unable to fetch NIFTY 50 data from market data provider",
                "max_positions_cap": 2,
                "metrics": {},
            }
        return evaluate_nifty_regime(dates, closes, volumes)
    except Exception as e:
        return {
            "status": "ERROR",
            "posture": "RESTRICT",
            "reason": f"Market regime evaluation error: {e}",
            "max_positions_cap": 2,
            "metrics": {},
        }


if __name__ == "__main__":
    regime = get_current_market_regime()
    print("=" * 60)
    print(" NIFTY 50 MARKET REGIME DAILY REPORT ")
    print("=" * 60)
    print(f"Status:       {regime['status']} ({regime['posture']})")
    print(f"Reason:       {regime['reason']}")
    print(f"Position Cap: {regime['max_positions_cap']} slots")
    if regime.get("metrics"):
        m = regime["metrics"]
        print(
            f"NIFTY Close:  {m.get('nifty_close')} | 50 SMA: {m.get('sma_50')} | 200 SMA: {m.get('sma_200')}"
        )
        print(
            f"5-Day Ret:    {m.get('ret_5d_pct'):+.2f}% | From 52W High: {m.get('pct_from_52w_high'):.2f}%"
        )
