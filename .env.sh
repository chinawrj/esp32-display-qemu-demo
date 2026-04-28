#!/bin/bash
# .env.sh - Project environment setup
# Source this script before development: source .env.sh

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Python venv
if [ -d "$PROJECT_ROOT/.venv" ]; then
    source "$PROJECT_ROOT/.venv/bin/activate"
fi

# ESP-IDF
ESP_IDF_PATH="$HOME/esp-idf"
if [ -f "$ESP_IDF_PATH/export.sh" ]; then
    source "$ESP_IDF_PATH/export.sh" > /dev/null 2>&1
    export IDF_PATH="$ESP_IDF_PATH"
fi

echo "✓ Project environment loaded from $PROJECT_ROOT/.env.sh"
