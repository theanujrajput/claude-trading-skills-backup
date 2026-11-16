#!/usr/bin/env bash
set -euo pipefail

# Package Lambda without Docker for AWS deployment
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BUILD_DIR="build_lambda"
OUTPUT_ZIP="function.zip"

echo "=========================================================="
echo " Packaging AWS Lambda (Zero Docker - Pure Python/Wheels) "
echo "=========================================================="

rm -rf "$BUILD_DIR" "$OUTPUT_ZIP"
mkdir -p "$BUILD_DIR"

# Check Python / pip availability
PYTHON_BIN="python3"
if [ -f ".venv/bin/python3" ]; then
    PYTHON_BIN=".venv/bin/python3"
fi

# 1. Download and install precompiled manylinux2014_x86_64 wheels for Python 3.11
echo "[1/4] Downloading Linux x86_64 precompiled dependencies..."
"$PYTHON_BIN" -m pip install \
    --platform manylinux2014_x86_64 \
    --target "$BUILD_DIR" \
    --implementation cp \
    --python-version 3.11 \
    --only-binary=:all: \
    -r scripts/requirements-lambda.txt

# 2. Copy scripts package into build directory
echo "[2/4] Bundling application source code..."
mkdir -p "$BUILD_DIR/scripts"
cp scripts/__init__.py "$BUILD_DIR/scripts/"
cp scripts/aws_lambda_handler.py "$BUILD_DIR/scripts/"
cp scripts/daily_swing_routine.py "$BUILD_DIR/scripts/"
cp scripts/paper_trader.py "$BUILD_DIR/scripts/"
cp scripts/screen_indian_stocks.py "$BUILD_DIR/scripts/"
cp scripts/telegram_notifier.py "$BUILD_DIR/scripts/"

# 3. Clean up non-essential files to minimize ZIP size
echo "[3/4] Stripping unnecessary files and caches..."
find "$BUILD_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
find "$BUILD_DIR" -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR" -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true

# 4. Create ZIP archive
echo "[4/4] Creating $OUTPUT_ZIP..."
(cd "$BUILD_DIR" && zip -r -q "../$OUTPUT_ZIP" .)

ZIP_SIZE=$(du -h "$OUTPUT_ZIP" | awk '{print $1}')
echo "=========================================================="
echo " Successfully created $OUTPUT_ZIP (Size: $ZIP_SIZE)"
echo " Ready to upload to S3 and deploy via AWS CLI!"
echo "=========================================================="
