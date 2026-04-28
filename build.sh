#!/bin/bash
set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ESP_IDF_PATH="${HOME}/esp-idf"

source "$ESP_IDF_PATH/export.sh" > /dev/null 2>&1

cd "$PROJECT_ROOT"
echo "Building ESP32 project..."
idf.py build
