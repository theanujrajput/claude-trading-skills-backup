#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Zero-Docker AWS CLI Deployment for Claude Trading Skills (Indian Stock Market)
# ==============================================================================
# Deploys Lambda + EventBridge (every 15 min 09:15-15:30 IST) + S3 state store.
#
# Usage:
#   ./scripts/deploy_zip_aws.sh --bucket <your-s3-bucket-name> [--region ap-south-1]
#
# Environment variables (.env file is automatically loaded if present):
#   S3_CODE_BUCKET
#   AWS_REGION (default: ap-south-1)
#   STACK_NAME (default: claude-trading-bot)
#   TELEGRAM_BOT_TOKEN
#   TELEGRAM_CHAT_ID
# ==============================================================================

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Load local .env if available
if [ -f ".env" ]; then
    echo "Loading environment variables from .env..."
    # shellcheck disable=SC2046
    export $(grep -v '^#' .env | xargs)
fi

# Default parameters
AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-south-1}}"
STACK_NAME="${STACK_NAME:-claude-trading-bot}"
S3_BUCKET="${S3_CODE_BUCKET:-}"
SKIP_BUILD=false
INITIAL_CAPITAL="${INITIAL_CAPITAL:-500000}"
RISK_PCT="${RISK_PCT:-1.0}"
MAX_POSITIONS="${MAX_POSITIONS:-5}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"

# Parse CLI arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --bucket)
            S3_BUCKET="$2"
            shift 2
            ;;
        --region)
            AWS_REGION="$2"
            shift 2
            ;;
        --stack-name)
            STACK_NAME="$2"
            shift 2
            ;;
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 --bucket <s3-bucket-name> [--region ap-south-1] [--stack-name claude-trading-bot] [--skip-build]"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 --bucket <s3-bucket-name> [--region ap-south-1]"
            exit 1
            ;;
    esac
done

echo "=========================================================="
echo " AWS Serverless Deployment (Zero Docker - AWS CLI + ZIP)  "
echo "=========================================================="

# 1. Verify AWS CLI
if ! command -v aws &> /dev/null; then
    echo "ERROR: AWS CLI is not installed or not in PATH."
    echo ""
    echo "To install AWS CLI on macOS:"
    echo "  brew install awscli"
    echo "Or using pip inside virtualenv:"
    echo "  .venv/bin/pip install awscli"
    echo ""
    echo "Then configure your AWS credentials:"
    echo "  aws configure"
    exit 1
fi

# 2. Check AWS credentials
echo "[1/5] Checking AWS credentials..."
if ! aws sts get-caller-identity --region "$AWS_REGION" > /dev/null 2>&1; then
    echo "ERROR: AWS CLI credentials check failed."
    echo "Please configure credentials with: aws configure"
    exit 1
fi
ACCOUNT_ID=$(aws sts get-caller-identity --query "Account" --output text --region "$AWS_REGION")
echo "  Authenticated AWS Account: $ACCOUNT_ID (Region: $AWS_REGION)"

# 3. Determine or create S3 Bucket
if [ -z "$S3_BUCKET" ]; then
    S3_BUCKET="claude-trading-code-${ACCOUNT_ID}-${AWS_REGION}"
    echo "[2/5] No --bucket provided. Using default bucket name: $S3_BUCKET"
fi

if ! aws s3api head-bucket --bucket "$S3_BUCKET" 2>/dev/null; then
    echo "  Bucket $S3_BUCKET does not exist. Creating..."
    if [ "$AWS_REGION" = "us-east-1" ]; then
        aws s3api create-bucket --bucket "$S3_BUCKET" --region "$AWS_REGION"
    else
        aws s3api create-bucket --bucket "$S3_BUCKET" --region "$AWS_REGION" \
            --create-bucket-configuration LocationConstraint="$AWS_REGION"
    fi
    echo "  Created S3 bucket: s3://$S3_BUCKET"
else
    echo "[2/5] Verified existing S3 bucket: s3://$S3_BUCKET"
fi

# 4. Build ZIP Package (without Docker)
if [ "$SKIP_BUILD" = false ]; then
    echo "[3/5] Building Lambda deployment ZIP (Zero Docker)..."
    ./scripts/package_zip_lambda.sh
else
    echo "[3/5] Skipping build (using existing function.zip)..."
    if [ ! -f "function.zip" ]; then
        echo "ERROR: function.zip not found! Run without --skip-build first."
        exit 1
    fi
fi

# 5. Upload ZIP to S3
S3_KEY="deploy/function.zip"
echo "[4/5] Uploading function.zip to s3://$S3_BUCKET/$S3_KEY..."
aws s3 cp function.zip "s3://$S3_BUCKET/$S3_KEY" --region "$AWS_REGION"

# 6. Deploy CloudFormation Stack
echo "[5/5] Deploying CloudFormation Stack: $STACK_NAME..."
aws cloudformation deploy \
    --template-file aws/template_zip.yaml \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" \
    --parameter-overrides \
        S3CodeBucket="$S3_BUCKET" \
        S3CodeKey="$S3_KEY" \
        InitialCapital="$INITIAL_CAPITAL" \
        RiskPct="$RISK_PCT" \
        MaxPositions="$MAX_POSITIONS" \
        TelegramBotToken="$TELEGRAM_BOT_TOKEN" \
        TelegramChatId="$TELEGRAM_CHAT_ID" \
    --capabilities CAPABILITY_IAM

echo "=========================================================="
echo " DEPLOYMENT SUCCESSFUL! "
echo "=========================================================="
echo ""
echo "Deployed Stack Resources:"
aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" \
    --query "Stacks[0].Outputs" \
    --output table

LAMBDA_NAME=$(aws cloudformation describe-stack-resources \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" \
    --logical-resource-id DailySwingTradingFunction \
    --query "StackResources[0].PhysicalResourceId" \
    --output text 2>/dev/null || echo "")

echo ""
echo "To manually trigger a test run immediately:"
echo "  aws lambda invoke --function-name $LAMBDA_NAME --payload '{}' response.json --region $AWS_REGION && cat response.json"
echo ""
echo "EventBridge will run automatically every 15 minutes during Indian market hours (09:15-15:30 IST, Mon-Fri)."
echo "Telegram notifications are sent ONLY when BUY or SELL orders are executed."
