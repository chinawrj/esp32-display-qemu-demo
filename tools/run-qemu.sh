#!/usr/bin/env bash
# tools/run-qemu.sh — Boot the built ESP32 image in QEMU and capture serial output.
#
# Prerequisites:
#   - qemu-system-xtensa available (either in PATH or installed via
#     `python $IDF_PATH/tools/idf_tools.py install qemu-xtensa` after `brew install qemu`).
#   - Project already built: `idf.py build`
#
# Usage:
#   ./tools/run-qemu.sh                # run for 8 seconds, print serial output
#   ./tools/run-qemu.sh 20             # run for 20 seconds
#   ./tools/run-qemu.sh 8 verify       # run + grep for LVGL init markers, exit 0/1

set -euo pipefail

DURATION="${1:-8}"
MODE="${2:-run}"
LOG_FILE="${LOG_FILE:-/tmp/esp32-qemu-serial.log}"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

if [ ! -f build/esp32-display-qemu-demo.bin ]; then
    echo "ERROR: build/esp32-display-qemu-demo.bin not found. Run 'idf.py build' first." >&2
    exit 2
fi

# Ensure ESP-IDF env is sourced
if [ -z "${IDF_PATH:-}" ]; then
    # shellcheck disable=SC1091
    source /Users/rjwang/esp-idf/export.sh > /dev/null 2>&1
fi

echo "[run-qemu] Booting QEMU for ${DURATION}s, log -> ${LOG_FILE}"
# `idf.py qemu` (no --graphics) runs headless; serial output goes to stdio.
QEMU_CMD="idf.py qemu --qemu-extra-args=-nographic"
if command -v gtimeout >/dev/null 2>&1; then
    gtimeout --foreground "${DURATION}" $QEMU_CMD 2>&1 | tee "$LOG_FILE" || true
elif command -v timeout >/dev/null 2>&1; then
    timeout --foreground "${DURATION}" $QEMU_CMD 2>&1 | tee "$LOG_FILE" || true
else
    : > "$LOG_FILE"
    $QEMU_CMD > "$LOG_FILE" 2>&1 &
    QEMU_PID=$!
    sleep "${DURATION}"
    kill "$QEMU_PID" 2>/dev/null || true
    sleep 1
    kill -9 "$QEMU_PID" 2>/dev/null || true
    QPIDS=$(ps -o pid= -o comm= | awk '/qemu-system-xtensa/ {print $1}')
    [ -n "$QPIDS" ] && kill $QPIDS 2>/dev/null || true
    wait "$QEMU_PID" 2>/dev/null || true
fi

echo ""
echo "[run-qemu] === Serial log captured (${LOG_FILE}) ==="

if [ "$MODE" = "verify" ]; then
    echo ""
    echo "[run-qemu] === Verification ==="
    PASS=0; FAIL=0
    check() {
        local label="$1"; shift
        if grep -qE "$*" "$LOG_FILE"; then
            echo "  ✅ $label"
            PASS=$((PASS+1))
        else
            echo "  ❌ $label  (pattern: $*)"
            FAIL=$((FAIL+1))
        fi
    }
    check "app_main reached"                  'esp32-display-qemu-demo starting'
    check "lvgl initialized log"              'lvgl initialized: v[0-9]+\.[0-9]+'
    check "lvgl display created"              'lvgl display created: [0-9]+x[0-9]+'
    check "lvgl flush callback fired"         'lvgl flush #'
    check "demo started"                      'lv_demo_benchmark started'
    check "demo rendered ≥30 flushes (≥1s)"   'lvgl flush total: ([3-9][0-9]|[1-9][0-9]{2,})'
    check "demo completion banner"            'M3 LVGL benchmark demo complete'

    echo ""
    echo "[run-qemu] Result: ${PASS} passed, ${FAIL} failed"
    [ "$FAIL" -eq 0 ]
fi
