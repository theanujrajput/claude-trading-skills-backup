#!/usr/bin/env python3
"""
Telegram Notification Engine for Claude Trading Skills.

Adopts the lightweight notification pattern from trade-bot / algo-trade-bot.
Sends notifications ONLY when an order execution occurs (BUY or SELL/EXIT).
No spam or neutral heartbeats when no trade actions are taken.

Configuration:
    Set via environment variables or .env file:
    TELEGRAM_BOT_TOKEN="your_bot_token"
    TELEGRAM_CHAT_ID="your_chat_id"
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]


def load_env(env_path: Path = ROOT_DIR / ".env") -> dict[str, str]:
    """Load key-value pairs from .env file if present."""
    env_vars = {}
    if env_path.exists():
        try:
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        env_vars[k.strip()] = v.strip().strip("'").strip('"')
        except Exception:
            pass
    return env_vars


class TelegramNotifier:
    """Telegram Notifier for Trade Executions."""

    def __init__(self, env_path: Path = ROOT_DIR / ".env"):
        env = load_env(env_path)
        self.bot_token = os.environ.get("TELEGRAM_BOT_TOKEN") or env.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID") or env.get("TELEGRAM_CHAT_ID")

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send_message(self, html_text: str) -> bool:
        """Send HTML-formatted message to Telegram."""
        if not self.is_configured:
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": html_text,
            "parse_mode": "HTML",
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

        try:
            # Use unverified context to bypass local macOS certificate store issues
            context = ssl._create_unverified_context()
            with urllib.request.urlopen(req, context=context, timeout=10) as response:
                res = json.loads(response.read().decode("utf-8"))
                if res.get("ok"):
                    print("Telegram notification delivered successfully.")
                    return True
                print(f"Telegram API Error: {res}", file=sys.stderr)
                return False
        except Exception as e:
            print(f"Failed to send Telegram message: {e}", file=sys.stderr)
            return False

    def send_document(self, file_path: Path, caption: str = "") -> bool:
        """Send a document/PDF file to Telegram."""
        if not self.is_configured:
            return False
        if not file_path.exists():
            print(f"File not found: {file_path}", file=sys.stderr)
            return False

        import uuid

        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
        filename = file_path.name
        file_bytes = file_path.read_bytes()

        parts = [
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n'
                f"{self.chat_id}\r\n"
            ).encode()
        ]
        if caption:
            parts.append(
                (
                    f'--{boundary}\r\nContent-Disposition: form-data; name="caption"\r\n\r\n'
                    f"{caption}\r\n"
                ).encode()
            )
            parts.append(
                (
                    f'--{boundary}\r\nContent-Disposition: form-data; name="parse_mode"\r\n\r\n'
                    "HTML\r\n"
                ).encode()
            )

        parts.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{filename}"\r\n'
                "Content-Type: application/pdf\r\n\r\n"
            ).encode()
        )
        parts.append(file_bytes)
        parts.append(f"\r\n--{boundary}--\r\n".encode())

        body = b"".join(parts)
        url = f"https://api.telegram.org/bot{self.bot_token}/sendDocument"
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
            },
        )
        try:
            context = ssl._create_unverified_context()
            with urllib.request.urlopen(req, context=context, timeout=30) as response:
                res = json.loads(response.read().decode("utf-8"))
                if res.get("ok"):
                    print(f"Telegram document '{filename}' delivered successfully.")
                    return True
                print(f"Telegram API Error: {res}", file=sys.stderr)
                return False
        except Exception as e:
            print(f"Failed to send Telegram document: {e}", file=sys.stderr)
            return False

    def notify_buy(
        self,
        symbol: str,
        qty: int,
        entry_price: float,
        stop_loss: float,
        target: float | None = None,
        total_cost: float | None = None,
        cash_remaining: float | None = None,
        notes: str = "",
    ) -> bool:
        """Send notification when a BUY position is entered."""
        if not self.is_configured:
            return False

        cost = total_cost if total_cost is not None else qty * entry_price
        stop_pct = ((stop_loss - entry_price) / entry_price) * 100.0 if entry_price > 0 else 0.0
        tgt_pct = (
            ((target - entry_price) / entry_price) * 100.0 if (target and entry_price > 0) else 0.0
        )

        lines = [
            "🟢 <b>BUY ORDER EXECUTED (PAPER)</b>",
            "",
            f"<b>Stock:</b> #{symbol.upper()}",
            f"<b>Quantity:</b> {qty:,} shares",
            f"<b>Entry Price:</b> ₹{entry_price:,.2f}",
            f"<b>Stop Loss:</b> ₹{stop_loss:,.2f} ({stop_pct:+.2f}%)",
        ]

        if target:
            lines.append(f"<b>Target (2R):</b> ₹{target:,.2f} ({tgt_pct:+.2f}%)")

        lines.append(f"<b>Position Value:</b> ₹{cost:,.2f}")

        if cash_remaining is not None:
            lines.append(f"<b>Remaining Cash:</b> ₹{cash_remaining:,.2f}")

        if notes:
            lines.append(f"\n<i>Rationale: {notes}</i>")

        return self.send_message("\n".join(lines))

    def notify_sell(
        self,
        symbol: str,
        qty: int,
        entry_price: float,
        exit_price: float,
        pnl: float,
        pnl_pct: float,
        reason: str,
        cash_balance: float | None = None,
        postmortem: dict[str, Any] | None = None,
    ) -> bool:
        """Send notification when a SELL / EXIT position is closed."""
        if not self.is_configured:
            return False

        if "PARTIAL_TARGET" in reason:
            header = "🎯 <b>PARTIAL TARGET REACHED (+8% 50% BOOKED)</b>"
        elif "TRAILING_STOP" in reason:
            header = "📈 <b>RUNNER TRAILING STOP EXIT (EXTENDED PROFIT)</b>"
        elif reason == "BREAKEVEN_STOP_TRIGGERED":
            header = "🛡️ <b>BREAK-EVEN EXIT (CAPITAL PROTECTED)</b>"
        elif pnl >= 0:
            header = "🟢 <b>PROFIT EXIT / TARGET REACHED</b>"
        else:
            header = "🔴 <b>STOP LOSS TRIGGERED / EXIT</b>"

        lines = [
            header,
            "",
            f"<b>Stock:</b> #{symbol.upper()}",
            f"<b>Quantity:</b> {qty:,} shares",
            f"<b>Entry Price:</b> ₹{entry_price:,.2f}",
            f"<b>Exit Price:</b> ₹{exit_price:,.2f}",
            f"<b>Realized P&L:</b> ₹{pnl:+,.2f} ({pnl_pct:+.2f}%)",
            f"<b>Exit Reason:</b> <code>{reason}</code>",
        ]

        if postmortem:
            r_mult = postmortem.get("r_multiple")
            if r_mult is not None:
                lines.append(f"<b>R-Multiple:</b> {r_mult:+.2f}R")
            category = postmortem.get("root_cause_category")
            if category:
                lines.append(f"<b>Root Cause:</b> <code>{category}</code>")
            lesson = postmortem.get("lesson")
            if lesson:
                lines.append(f"\n<i>Takeaway: {lesson}</i>")

        if cash_balance is not None:
            lines.append(f"\n<b>Updated Cash:</b> ₹{cash_balance:,.2f}")

        return self.send_message("\n".join(lines))

    def notify_eod_digest(
        self,
        date_str: str,
        portfolio_equity: float,
        initial_capital: float,
        cash: float,
        active_positions: dict[str, Any],
        closed_trades: list[dict[str, Any]],
        max_positions: int = 10,
    ) -> bool:
        """Send comprehensive End-of-Day (EOD) portfolio status digest."""
        if not self.is_configured:
            return False

        total_pnl = portfolio_equity - initial_capital
        total_pnl_pct = (total_pnl / initial_capital) * 100.0 if initial_capital > 0 else 0.0

        pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
        active_count = len(active_positions)
        invested = sum(
            pos.get("market_value", pos.get("quantity", 0) * pos.get("current_price", 0.0))
            for pos in active_positions.values()
        )
        total_unrealized = sum(pos.get("unrealized_pnl", 0.0) for pos in active_positions.values())

        lines = [
            "📊 <b>DAILY EOD PORTFOLIO STATUS</b>",
            f"<i>Date: {date_str} | Post-Market Digest</i>",
            "━━━━━━━━━━━━━━━━━━━━━",
            "💰 <b>ACCOUNT OVERVIEW</b>",
            f"• <b>Portfolio Equity:</b> ₹{portfolio_equity:,.2f}",
            f"• <b>Overall Return:</b> <b>₹{total_pnl:+,.2f} ({total_pnl_pct:+.2f}%)</b> {pnl_emoji}",
            f"• <b>Available Cash:</b> ₹{cash:,.2f}",
            f"• <b>Invested Capital:</b> ₹{invested:,.2f}",
            f"• <b>Active Holdings:</b> <b>{active_count}/{max_positions} stocks</b>",
            "",
            f"📈 <b>OPEN POSITIONS ({active_count})</b>",
        ]

        if not active_positions:
            lines.append("• <i>No open positions currently held (100% Cash).</i>")
        else:
            for sym, pos in active_positions.items():
                qty = pos.get("quantity", 0)
                entry_p = pos.get("entry_price", 0.0)
                ltp = pos.get("current_price", entry_p)
                pnl = pos.get("unrealized_pnl", 0.0)
                pnl_pct = pos.get("pnl_pct", 0.0)
                stop_p = pos.get("stop_loss", 0.0)
                target_p = pos.get("target")

                be_tag = " 🛡️ [Trailing BE]" if pos.get("trailing_breakeven_triggered") else ""
                stock_emoji = "🟢" if pnl >= 0 else "🔴"

                lines.append(f"• <b>#{sym}</b> ({qty:,} shares)")
                lines.append(f"  Entry: ₹{entry_p:,.2f} | LTP: ₹{ltp:,.2f}")
                lines.append(f"  P&L: <b>₹{pnl:+,.2f} ({pnl_pct:+.2f}%)</b> {stock_emoji}")
                tgt_str = f" | Tgt: ₹{target_p:,.2f}" if target_p else ""
                lines.append(f"  Stop: ₹{stop_p:,.2f}{be_tag}{tgt_str}")

        lines.extend(
            [
                "━━━━━━━━━━━━━━━━━━━━━",
                f"💵 <b>Total Unrealized P&L:</b> <b>₹{total_unrealized:+,.2f}</b>",
                "",
            ]
        )

        # Filter trades closed today
        closed_today = [t for t in closed_trades if t.get("exit_date", "").startswith(date_str)]

        if closed_today:
            realized_today = sum(t.get("pnl", 0.0) for t in closed_today)
            lines.append(f"🎯 <b>TODAY'S CLOSED TRADES ({len(closed_today)})</b>")
            for t in closed_today:
                t_sym = t.get("symbol", "")
                t_exit = t.get("exit_price", 0.0)
                t_pnl = t.get("pnl", 0.0)
                t_pct = t.get("pnl_pct", 0.0)
                t_reason = t.get("exit_reason", "")
                r_emoji = (
                    "🎯" if "TARGET" in t_reason else ("🛡️" if "BREAKEVEN" in t_reason else "🛑")
                )
                lines.append(
                    f"• <b>#{t_sym}</b>: Exit @ ₹{t_exit:,.2f} | P&L: <b>₹{t_pnl:+,.2f} ({t_pct:+.2f}%)</b> [{t_reason} {r_emoji}]"
                )
            lines.append(f"• <b>Today's Realized P&L:</b> <b>₹{realized_today:+,.2f}</b>")
        else:
            lines.append("🎯 <b>TODAY'S CLOSED TRADES</b>")
            lines.append("• <i>No trades closed today (Positions held for swing continuation).</i>")

        lines.append("━━━━━━━━━━━━━━━━━━━━━")
        return self.send_message("\n".join(lines))
