#!/bin/bash
# build-script.sh - Build the ESP32 QEMU demo project
# This script sources ESP-IDF and builds the project

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ESP_IDF_PATH="${HOME}/esp-idf"

echo "=========================================="
echo "Building esp32-display-qemu-demo"
echo "=========================================="
echo "Project: $PROJECT_ROOT"
echo "ESP-IDF:  $ESP_IDF_PATH"
echo ""

# Verify ESP-IDF exists
if [ ! -f "$ESP_IDF_PATH/export.sh" ]; then
    echo "ERROR: ESP-IDF not found at $ESP_IDF_PATH"
    exit 1
fi

# Source ESP-IDF (with error suppression for stderr)
echo "[1/4] Sourcing ESP-IDF environment..."
source "$ESP_IDF_PATH/export.sh" > /dev/null 2>&1 || true

# Verify idf.py access
echo "[2/4] Verifying idf.py..."
if ! command -v idf.py &>/dev/null; then
    # Try direct Python invocation
    if ! python3 "$ESP_IDF_PATH/tools/idf.py" --version &>/dev/null; then
        echo "ERROR: Cannot find or execute idf.py"
        echo "Checking for Python dependencies..."
        python3 -c "import click; import pyyaml; import patchelf" 2>&1 || true
        exit 1
    fi
fi

cd "$PROJECT_ROOT"

# Set target to ESP32
echo "[3/4] Setting target to esp32..."
idf.py set-target esp32 > /dev/null 2>&1 || true

# Build the project
echo "[4/4] Compiling project (idf.py build)..."
echo ""
idf.py build

echo ""
echo "=========================================="
echo "✅ Build completed successfully"
echo "=========================================="
