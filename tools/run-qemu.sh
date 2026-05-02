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

DURATION="${1:-45}"
MODE="${2:-run}"
LOG_FILE="${LOG_FILE:-/tmp/esp32-qemu-serial.log}"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# Prefer locally-built QEMU if available (Day 14 work). Override via
# QEMU_BIN=... or set USE_LOCAL_QEMU=0 to force the IDF-managed binary.
if [ -z "${QEMU_BIN:-}" ] && [ "${USE_LOCAL_QEMU:-1}" = "1" ]; then
    LOCAL_QEMU="$PROJECT_DIR/tools/qemu-src/build/qemu-system-xtensa"
    [ -x "$LOCAL_QEMU" ] && QEMU_BIN="$LOCAL_QEMU"
fi
if [ -n "${QEMU_BIN:-}" ] && [ -x "${QEMU_BIN}" ]; then
    QEMU_BIN_DIR="$(dirname "$QEMU_BIN")"
    PATH="${QEMU_BIN_DIR}:${PATH}"
    export PATH
    echo "[run-qemu] using local QEMU: $QEMU_BIN"
fi

if [ ! -f build/esp32-display-qemu-demo.bin ]; then
    echo "ERROR: build/esp32-display-qemu-demo.bin not found. Run 'idf.py build' first." >&2
    exit 2
fi

# Ensure ESP-IDF env is sourced (also re-source if IDF_PATH is set but idf.py
# is not on PATH, e.g. after `source export.sh` in a parent shell that did not
# export the derived PATH to sub-processes).
if [ -z "${IDF_PATH:-}" ] || ! command -v idf.py >/dev/null 2>&1; then
    # shellcheck disable=SC1091
    source "${IDF_PATH:-$HOME/esp-idf}/export.sh" > /dev/null 2>&1
fi

echo "[run-qemu] Booting QEMU for ${DURATION}s, log -> ${LOG_FILE}"
# idf.py needs the ESP-IDF python (with `click` etc.); a project .venv on PATH
# shadows it. Strip the venv so the IDF environment wins.
if [ -n "${VIRTUAL_ENV:-}" ]; then
    PATH="$(echo "$PATH" | tr ':' '\n' | grep -vF "$VIRTUAL_ENV/bin" | paste -sd: -)"
    export PATH
    unset VIRTUAL_ENV PYTHONHOME 2>/dev/null || true
fi
# `idf.py qemu` (no --graphics) runs headless; serial output goes to stdio.
QEMU_CMD="idf.py qemu --qemu-extra-args=-nographic"
if command -v gtimeout >/dev/null 2>&1; then
    # -k 5: escalate to SIGKILL 5s after SIGTERM. Required on Linux where
    # QEMU's monitor on -serial mon:stdio absorbs SIGTERM and otherwise
    # never exits.
    gtimeout --foreground -k 5 "${DURATION}" $QEMU_CMD 2>&1 | tee "$LOG_FILE" || true
elif command -v timeout >/dev/null 2>&1; then
    timeout --foreground -k 5 "${DURATION}" $QEMU_CMD 2>&1 | tee "$LOG_FILE" || true
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
    check "framebuffer capture begin marker"  '<<<FB_BEGIN size=64800 w=240 h=135 fmt=RGB565>>>'
    check "framebuffer capture end marker"    '<<<FB_END>>>'
    check "demo completion banner"            'M3 LVGL benchmark demo complete'

    # Extra: validate base64 payload line count (64800 bytes / 3 * 4 / 60 chars = 1440 lines)
    fb_lines=$(grep -c '^FB=' "$LOG_FILE" || true)
    if [ "$fb_lines" = "1440" ]; then
        echo "  ✅ framebuffer payload size  (1440 base64 lines, expected 1440)"
        PASS=$((PASS+1))
    else
        echo "  ❌ framebuffer payload size  (got $fb_lines lines, expected 1440)"
        FAIL=$((FAIL+1))
    fi

    echo ""
    echo "[run-qemu] Result: ${PASS} passed, ${FAIL} failed"
    [ "$FAIL" -eq 0 ]
fi
