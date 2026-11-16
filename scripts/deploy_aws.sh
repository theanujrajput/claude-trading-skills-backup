#!/usr/bin/env bash
# Deploy Serverless Indian Stock Market Swing Trading Routine to AWS
# Architecture: AWS EventBridge (Mon-Fri 16:00 IST) -> AWS Lambda (Container) -> S3 (State JSON)

set -euo pipefail

AWS_REGION="${AWS_REGION:-ap-south-1}"  # Default: Mumbai region
STACK_NAME="${STACK_NAME:-claude-trading-bot}"
ECR_REPO_NAME="claude-trading-lambda"

echo "=== Deploying Serverless Swing Trading Bot to AWS ==="
echo "Region:     $AWS_REGION"
echo "Stack Name: $STACK_NAME"

# 1. Check prerequisites
if ! command -v aws >/dev/null 2>&1; then
    echo "ERROR: AWS CLI is not installed."
    echo "Install via Homebrew: brew install awscli"
    echo "Then configure credentials: aws configure"
    exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: Docker is not installed or not running."
    echo "Please launch Docker Desktop before deploying."
    exit 1
fi

ACCOUNT_ID=$(aws sts get-caller-identity --query "Account" --output text --region "$AWS_REGION")
echo "AWS Account ID: $ACCOUNT_ID"

# 2. Ensure ECR repository exists
echo "\n[1/4] Ensuring ECR repository exists..."
aws ecr describe-repositories --repository-names "$ECR_REPO_NAME" --region "$AWS_REGION" >/dev/null 2>&1 || \
aws ecr create-repository --repository-name "$ECR_REPO_NAME" --region "$AWS_REGION" >/dev/null

ECR_URI="$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO_NAME"
IMAGE_TAG="$(date +%Y%m%d%H%M%S)"
FULL_IMAGE_URI="$ECR_URI:$IMAGE_TAG"

# 3. Authenticate Docker with ECR
echo "\n[2/4] Logging into AWS ECR..."
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_URI"

# 4. Build and Push Container Image
echo "\n[3/4] Building and pushing Lambda container image..."
docker build -f Dockerfile.lambda -t "$FULL_IMAGE_URI" .
docker tag "$FULL_IMAGE_URI" "$ECR_URI:latest"
docker push "$FULL_IMAGE_URI"
docker push "$ECR_URI:latest"

# 5. Deploy CloudFormation Stack
echo "\n[4/4] Deploying CloudFormation Stack ($STACK_NAME)..."
aws cloudformation deploy \
    --template-file aws/template.yaml \
    --stack-name "$STACK_NAME" \
    --parameter-overrides ImageUri="$FULL_IMAGE_URI" \
    --capabilities CAPABILITY_IAM \
    --region "$AWS_REGION"

echo "\n=== Deployment Completed Successfully ==="
aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs" \
    --output table \
    --region "$AWS_REGION"
