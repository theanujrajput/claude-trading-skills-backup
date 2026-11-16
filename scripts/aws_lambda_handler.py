#!/usr/bin/env python3
"""
AWS Lambda Handler for Automated Daily Swing Trading Routine.

Coordinates:
1. Downloading paper_trading_state.json from Amazon S3.
2. Executing the daily post-market cycle (exits, screening, sizing, auto-entries).
3. Uploading the updated state back to Amazon S3.
4. Optional delivery of daily digest via Amazon SNS or Telegram.

Environment Variables:
    S3_BUCKET_NAME: S3 bucket name storing paper_trading_state.json (Required)
    S3_KEY: S3 object key (Default: "state/paper_trading_state.json")
    INITIAL_CAPITAL: Account initial capital if state file not found (Default: "500000.0")
    RISK_PCT: Risk percentage per trade (Default: "1.0")
    MAX_POSITIONS: Maximum concurrent positions (Default: "5")
    AUTO_BUY: Whether to enter new trades (Default: "true")
    SNS_TOPIC_ARN: Optional Amazon SNS topic ARN for email/SMS notifications
    TELEGRAM_BOT_TOKEN: Optional Telegram Bot Token
    TELEGRAM_CHAT_ID: Optional Telegram Chat ID
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    boto3 = None
    ClientError = Exception

from scripts.daily_swing_routine import run_daily_cycle
from scripts.paper_trader import init_account

LOCAL_TEMP_STATE = Path("/tmp/paper_trading_state.json")


def sync_from_s3(
    s3_client, bucket: str, key: str, local_path: Path, default_capital: float
) -> None:
    """Download state JSON from S3, or initialize fresh if it doesn't exist."""
    try:
        s3_client.download_file(bucket, key, str(local_path))
        print(f"Downloaded state from s3://{bucket}/{key}")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey"):
            print(f"No existing state at s3://{bucket}/{key}. Initializing fresh state.")
            init_account(default_capital, local_path)
        else:
            raise


def sync_to_s3(s3_client, local_path: Path, bucket: str, key: str) -> None:
    """Upload updated state JSON back to S3."""
    s3_client.upload_file(str(local_path), bucket, key)
    print(f"Uploaded updated state to s3://{bucket}/{key}")


def send_telegram_alert(token: str, chat_id: str, message: str) -> bool:
    """Send summary message via Telegram Bot API."""
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps(
            {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
        ).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"Telegram notification failed: {e}", file=sys.stderr)
        return False


def send_sns_alert(sns_client, topic_arn: str, subject: str, message: str) -> bool:
    """Publish summary message to an Amazon SNS Topic."""
    try:
        sns_client.publish(
            TopicArn=topic_arn,
            Subject=subject[:100],
            Message=message,
        )
        return True
    except Exception as e:
        print(f"SNS notification failed: {e}", file=sys.stderr)
        return False


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Main AWS Lambda invocation entry point."""
    print("Received EventBridge invocation event:", json.dumps(event))

    bucket_name = os.environ.get("S3_BUCKET_NAME")
    if not bucket_name:
        raise ValueError("Environment variable S3_BUCKET_NAME is required.")

    s3_key = os.environ.get("S3_KEY", "state/paper_trading_state.json")
    default_capital = float(os.environ.get("INITIAL_CAPITAL", "500000.0"))
    risk_pct = float(os.environ.get("RISK_PCT", "1.0"))
    max_positions = int(os.environ.get("MAX_POSITIONS", "5"))
    auto_buy = os.environ.get("AUTO_BUY", "true").lower() in ("true", "1", "yes")
    cooldown_days = int(os.environ.get("COOLDOWN_DAYS", "5"))

    check_market_hours = os.environ.get("CHECK_MARKET_HOURS", "true").lower() in (
        "true",
        "1",
        "yes",
    )

    s3_client = boto3.client("s3") if boto3 else None
    if not s3_client:
        raise RuntimeError("boto3 is not available in the execution environment.")

    # Check if this invocation is for the Weekly Sector Report (Saturdays 4:00 PM IST)
    if event.get("action") == "weekly_sector_report":
        print("Received Saturday 4:00 PM IST trigger: Running Weekly Sector Report...")
        from scripts.weekly_sector_report import run_weekly_sector_routine

        res = run_weekly_sector_routine(
            bucket_name=bucket_name,
            s3_client=s3_client,
            output_dir=Path("/tmp/reports"),
            send_telegram=True,
        )
        return {
            "statusCode": 200,
            "body": res,
        }

    # Check if this invocation is for the Daily EOD Portfolio Digest (Mon-Fri 3:45 PM IST)
    if event.get("action") == "eod_digest":
        print("Received EOD trigger: Running Daily End-of-Day Portfolio Digest...")
        sync_from_s3(s3_client, bucket_name, s3_key, LOCAL_TEMP_STATE, default_capital)

        from datetime import datetime
        from zoneinfo import ZoneInfo

        from scripts.paper_trader import update_market_prices
        from scripts.telegram_notifier import TelegramNotifier

        # Update market prices to capture official closing prices
        _, updated_state = update_market_prices(
            state_file=LOCAL_TEMP_STATE,
            auto_trigger_stops=True,
        )
        sync_to_s3(s3_client, LOCAL_TEMP_STATE, bucket_name, s3_key)

        notifier = TelegramNotifier()
        delivered = False
        today_ist = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
        if notifier.is_configured:
            delivered = notifier.notify_eod_digest(
                date_str=today_ist,
                portfolio_equity=updated_state.get("portfolio_equity", 0.0),
                initial_capital=updated_state.get("initial_capital", default_capital),
                cash=updated_state.get("cash", 0.0),
                active_positions=updated_state.get("active_positions", {}),
                closed_trades=updated_state.get("closed_trades", []),
                max_positions=max_positions,
            )

        return {
            "statusCode": 200,
            "body": {
                "status": "success",
                "action": "eod_digest",
                "date": today_ist,
                "telegram_delivered": delivered,
                "portfolio_equity": updated_state.get("portfolio_equity"),
                "active_positions_count": len(updated_state.get("active_positions", {})),
            },
        }

    # 1. Download state from S3
    sync_from_s3(s3_client, bucket_name, s3_key, LOCAL_TEMP_STATE, default_capital)

    # 2. Run trading cycle
    result = run_daily_cycle(
        strategy="breakout",
        risk_pct=risk_pct,
        max_positions=max_positions,
        auto_buy=auto_buy,
        check_market_hours=check_market_hours,
        cooldown_days=cooldown_days,
        state_file=LOCAL_TEMP_STATE,
    )

    # If skipped due to closed market hours, exit early
    if result.get("status") == "market_closed":
        print(f"Skipping cycle: {result.get('digest')}")
        return {
            "statusCode": 200,
            "body": {
                "status": "market_closed",
                "message": result.get("digest"),
            },
        }

    # 3. Upload state back to S3
    sync_to_s3(s3_client, LOCAL_TEMP_STATE, bucket_name, s3_key)

    # 4. Optional SNS broadcast
    sns_topic = os.environ.get("SNS_TOPIC_ARN")
    if sns_topic:
        sns_client = boto3.client("sns")
        send_sns_alert(
            sns_client=sns_client,
            topic_arn=sns_topic,
            subject=f"Daily Trade Report - {result['date']}",
            message=result["digest"],
        )

    return {
        "statusCode": 200,
        "body": {
            "date": result["date"],
            "portfolio_equity": result["equity"],
            "cash": result["cash"],
            "active_positions_count": result["active_positions_count"],
            "new_trades": result["new_trades"],
        },
    }


if __name__ == "__main__":
    # Local CLI testing of the Lambda handler
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        print("Testing Lambda Handler locally...")
        os.environ["S3_BUCKET_NAME"] = os.environ.get("S3_BUCKET_NAME", "local-test-bucket")
        # Run dummy event
        print(lambda_handler({}, None))
