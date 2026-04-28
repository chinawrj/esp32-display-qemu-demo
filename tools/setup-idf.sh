#!/bin/bash
# setup-idf.sh - Initialize ESP-IDF for this project

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ESP_IDF_PATH="${HOME}/esp-idf"

echo "=== Setting up ESP-IDF for project ==="
echo "Project root: $PROJECT_ROOT"
echo "ESP-IDF path: $ESP_IDF_PATH"

if [ ! -f "$ESP_IDF_PATH/export.sh" ]; then
    echo "❌ ESP-IDF not found at $ESP_IDF_PATH"
    exit 1
fi

# Source ESP-IDF
source "$ESP_IDF_PATH/export.sh" > /dev/null 2>&1

# Verify idf.py
if ! command -v idf.py &>/dev/null; then
    echo "❌ idf.py not in PATH after sourcing ESP-IDF"
    exit 1
fi

echo "✓ ESP-IDF environment loaded"
echo "✓ idf.py: $(which idf.py)"

# Set target to esp32
cd "$PROJECT_ROOT"
echo ""
echo "Setting target to esp32..."
idf.py set-target esp32

echo ""
echo "✅ Setup complete!"
echo "Next: run 'idf.py build' to compile"
