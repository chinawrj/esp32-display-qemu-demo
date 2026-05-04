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

# ---------------------------------------------------------------------------
# 1. Locate QEMU binary — prefer local fork, fall back to IDF-managed.
#    Override with QEMU_BIN=... env or set USE_LOCAL_QEMU=0 to skip fork.
# ---------------------------------------------------------------------------
if [ -z "${QEMU_BIN:-}" ] && [ "${USE_LOCAL_QEMU:-1}" = "1" ]; then
    LOCAL_QEMU="$PROJECT_DIR/tools/qemu-src/build/qemu-system-xtensa"
    [ -x "$LOCAL_QEMU" ] && QEMU_BIN="$LOCAL_QEMU"
fi
if [ -z "${QEMU_BIN:-}" ]; then
    QEMU_BIN="$(find "$HOME/.espressif/tools/qemu-xtensa" -name 'qemu-system-xtensa' 2>/dev/null | sort | tail -1 || true)"
fi
if [ -z "${QEMU_BIN:-}" ] || [ ! -x "${QEMU_BIN}" ]; then
    echo "ERROR: qemu-system-xtensa not found. Build the local fork or install via idf_tools.py." >&2
    exit 2
fi
echo "[run-qemu] using QEMU: $QEMU_BIN"

# ---------------------------------------------------------------------------
# 2. Verify firmware binary exists.
# ---------------------------------------------------------------------------
if [ ! -f build/esp32-display-qemu-demo.bin ]; then
    echo "ERROR: build/esp32-display-qemu-demo.bin not found. Run 'idf.py build' first." >&2
    exit 2
fi

# ---------------------------------------------------------------------------
# 3. (Re)generate qemu_flash.bin if missing or stale.
# ---------------------------------------------------------------------------
if [ ! -f build/qemu_flash.bin ] || [ build/esp32-display-qemu-demo.bin -nt build/qemu_flash.bin ]; then
    echo "[run-qemu] Regenerating qemu_flash.bin..."
    IDF_PYTHON="$(find "$HOME/.espressif/python_env" -name python -path '*/idf5.5*/bin/python' 2>/dev/null | head -1 || true)"
    [ -z "${IDF_PYTHON:-}" ] && IDF_PYTHON="python3"
    (cd build && "$IDF_PYTHON" -m esptool --chip=esp32 merge_bin \
        --output=qemu_flash.bin --fill-flash-size=2MB @flash_args 2>&1 | tail -2)
fi

# ---------------------------------------------------------------------------
# 4. Generate qemu_efuse.bin if missing (124-byte default for ESP32 rev3).
# ---------------------------------------------------------------------------
if [ ! -f build/qemu_efuse.bin ]; then
    echo "[run-qemu] Generating default qemu_efuse.bin..."
    python3 -c "
import struct, sys
buf = bytearray(124)
buf[0x0d] = 0x80  # WR_DIS bit for chip rev
buf[0x11] = 0x10  # chip revision = 3
open('build/qemu_efuse.bin','wb').write(buf)
"
fi

# ---------------------------------------------------------------------------
# 5. Boot QEMU directly (no idf.py rebuild overhead).
# ---------------------------------------------------------------------------
echo "[run-qemu] Booting QEMU for ${DURATION}s, log -> ${LOG_FILE}"
# Clear any stale log so each run produces a clean, single-session file.
: > "${LOG_FILE}"

FLASH_BIN="${PROJECT_DIR}/build/qemu_flash.bin"
EFUSE_BIN="${PROJECT_DIR}/build/qemu_efuse.bin"

run_qemu() {
    "${QEMU_BIN}" \
        -M esp32 -m 4M \
        -drive "file=${FLASH_BIN},if=mtd,format=raw" \
        -drive "file=${EFUSE_BIN},if=none,format=raw,id=efuse" \
        -global driver=nvram.esp32.efuse,property=drive,value=efuse \
        -global driver=timer.esp32.timg,property=wdt_disable,value=true \
        -nic user,model=open_eth \
        -nographic -serial mon:stdio \
        "$@" 2>&1 | tee "$LOG_FILE" || true
}

if command -v timeout >/dev/null 2>&1; then
    # timeout wraps the entire qemu+tee pipeline; -k 5 force-kills stragglers.
    timeout --foreground -k 5 "${DURATION}" \
        bash -c '"$1" -M esp32 -m 4M \
            -drive "file=$2,if=mtd,format=raw" \
            -drive "file=$3,if=none,format=raw,id=efuse" \
            -global driver=nvram.esp32.efuse,property=drive,value=efuse \
            -global driver=timer.esp32.timg,property=wdt_disable,value=true \
            -nic user,model=open_eth \
            -nographic -serial mon:stdio 2>&1 | tee "$4"' \
        _ "${QEMU_BIN}" "${FLASH_BIN}" "${EFUSE_BIN}" "${LOG_FILE}" || true
else
    run_qemu &
    QEMU_PID=$!
    sleep "${DURATION}"
    kill "$QEMU_PID" 2>/dev/null || true
    sleep 1
    kill -9 "$QEMU_PID" 2>/dev/null || true
    pkill -9 -f qemu-system-xtensa 2>/dev/null || true
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
