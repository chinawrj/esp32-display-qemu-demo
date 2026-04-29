#!/usr/bin/env bash
# tools/start-demo.sh — One-click "build + run + verify" the LVGL benchmark demo on QEMU.
#
# Usage:
#   ./tools/start-demo.sh           # build (if needed) + boot QEMU + verify
#   ./tools/start-demo.sh quick     # skip build, just run+verify (assume binary current)
#
# Exits 0 on full success (verify all green), non-zero on any failure.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

MODE="${1:-full}"

# --- Source ESP-IDF ---
if [ -z "${IDF_PATH:-}" ]; then
    # shellcheck disable=SC1091
    source /Users/rjwang/esp-idf/export.sh > /dev/null 2>&1
fi

if [ "$MODE" != "quick" ]; then
    echo "════════════════════════════════════════"
    echo " Step 1/2: Building project (idf.py build)"
    echo "════════════════════════════════════════"
    idf.py build | tail -8
    echo ""
fi

if [ ! -f build/esp32-display-qemu-demo.bin ]; then
    echo "ERROR: build/esp32-display-qemu-demo.bin missing — build failed?" >&2
    exit 2
fi

BIN_KB=$(($(stat -f%z build/esp32-display-qemu-demo.bin 2>/dev/null || stat -c%s build/esp32-display-qemu-demo.bin) / 1024))
echo "[start-demo] Built binary: ${BIN_KB} KB"

echo ""
echo "════════════════════════════════════════"
echo " Step 2/2: Booting QEMU + verifying demo"
echo "════════════════════════════════════════"
bash tools/run-qemu.sh 30 verify
RC=$?

if [ "$RC" -eq 0 ]; then
    echo ""
    echo "🎉 LVGL benchmark demo verified successfully on QEMU."
fi
exit $RC
