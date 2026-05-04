#!/usr/bin/env bash
# tools/run-wifi-sta.sh — Boot the wifi_sta example in QEMU with the mock
# wpa_supplicant and verify "got ip:" appears in serial output.
#
# Usage:
#   ./tools/run-wifi-sta.sh              # run 30s, verify
#   ./tools/run-wifi-sta.sh 60           # run 60s, verify
#   WIFI_SSID=myssid WIFI_PASS=mypass ./tools/run-wifi-sta.sh
#   LOG_FILE=/tmp/wifi-sta.log ./tools/run-wifi-sta.sh

set -euo pipefail

DURATION="${1:-30}"
LOG_FILE="${LOG_FILE:-/tmp/esp32-wifi-sta.log}"
MOCK_SOCKET="${ESP_WIFI_CTRL_SOCKET:-/tmp/mock-wpa-ctrl}"
WIFI_SSID="${WIFI_SSID:-QEMU_TEST}"
WIFI_PASS="${WIFI_PASS:-qemu1234}"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXAMPLE_DIR="${PROJECT_DIR}/examples/wifi_sta"
FIRMWARE="${EXAMPLE_DIR}/build/wifi_sta_example.bin"
BOOTLOADER="${EXAMPLE_DIR}/build/bootloader/bootloader.bin"
PARTITION_TABLE="${EXAMPLE_DIR}/build/partition_table/partition-table.bin"
FLASH_IMAGE="/tmp/esp32-wifi-sta-flash.bin"

# ── Sanity checks ─────────────────────────────────────────────────────────
if [ ! -f "$FIRMWARE" ]; then
    echo "ERROR: firmware not found: $FIRMWARE" >&2
    echo "       Run: cd examples/wifi_sta && idf.py build" >&2
    exit 2
fi

# ── Merge flash image ─────────────────────────────────────────────────────
IDF_PYTHON="$(ls ~/.espressif/python_env/idf*_env/bin/python3 2>/dev/null | sort | tail -1)"
IDF_PYTHON="${IDF_PYTHON:-python3}"
echo "[run-wifi-sta] Merging flash image -> ${FLASH_IMAGE}"
"$IDF_PYTHON" "${IDF_PATH}/components/esptool_py/esptool/esptool.py" \
    --chip esp32 merge_bin \
    --fill-flash-size 2MB --flash_mode dio --flash_freq 40m --flash_size 2MB \
    -o "$FLASH_IMAGE" \
    0x1000 "$BOOTLOADER" \
    0x8000 "$PARTITION_TABLE" \
    0x10000 "$FIRMWARE"

# ── Choose QEMU binary ─────────────────────────────────────────────────────
LOCAL_QEMU="${PROJECT_DIR}/tools/qemu-src/build/qemu-system-xtensa"
if [ -x "$LOCAL_QEMU" ]; then
    QEMU_BIN="$LOCAL_QEMU"
elif command -v qemu-system-xtensa >/dev/null 2>&1; then
    QEMU_BIN="qemu-system-xtensa"
else
    echo "ERROR: qemu-system-xtensa not found" >&2
    exit 2
fi
echo "[run-wifi-sta] QEMU: $QEMU_BIN"

# ── Start mock wpa_supplicant ──────────────────────────────────────────────
MOCK_PID=""
cleanup() {
    [ -n "$MOCK_PID" ] && kill "$MOCK_PID" 2>/dev/null || true
    rm -f "$MOCK_SOCKET"
}
trap cleanup EXIT INT TERM

# Activate venv to run Python mock
if [ -f "${PROJECT_DIR}/.venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "${PROJECT_DIR}/.venv/bin/activate"
fi

echo "[run-wifi-sta] Starting mock wpa_supplicant (socket: $MOCK_SOCKET, SSID: $WIFI_SSID)"
python3 "${PROJECT_DIR}/tools/mock_wpa_supplicant.py" \
    --socket "$MOCK_SOCKET" \
    --ssid   "$WIFI_SSID"   \
    --ip     "192.168.1.100" \
    --mask   "255.255.255.0" \
    --gw     "192.168.1.1" &
MOCK_PID=$!
sleep 1  # let socket appear

# ── Build QEMU command ─────────────────────────────────────────────────────
# The ESP32 machine creates net.esp.wifi internally; ctrl socket path is
# communicated via ESP_WIFI_CTRL_SOCKET environment variable.
export ESP_WIFI_CTRL_SOCKET="${MOCK_SOCKET}"

QEMU_ARGS=(
    -M esp32
    -m 4M
    -nographic
    -drive "file=${FLASH_IMAGE},if=mtd,format=raw"
    -global "driver=timer.esp32.timg,property=wdt_disable,value=true"
)

echo "[run-wifi-sta] Booting for ${DURATION}s, log -> ${LOG_FILE}"

# ── Run QEMU with timeout ──────────────────────────────────────────────────
if command -v timeout >/dev/null 2>&1; then
    timeout --foreground -k 5 "${DURATION}" "${QEMU_BIN}" "${QEMU_ARGS[@]}" \
        2>&1 | tee "$LOG_FILE" || true
else
    "${QEMU_BIN}" "${QEMU_ARGS[@]}" >"$LOG_FILE" 2>&1 &
    QEMU_PID=$!
    sleep "${DURATION}"
    kill "$QEMU_PID" 2>/dev/null || true
    wait "$QEMU_PID" 2>/dev/null || true
fi

echo ""
echo "[run-wifi-sta] === Serial log ==="
cat "$LOG_FILE"

echo ""
echo "[run-wifi-sta] === Verification ==="
PASS=0; FAIL=0
check() {
    local label="$1" pattern="$2"
    if grep -qE "$pattern" "$LOG_FILE"; then
        echo "  ✅ $label"
        PASS=$((PASS+1))
    else
        echo "  ❌ $label  (pattern: $pattern)"
        FAIL=$((FAIL+1))
    fi
}

check "QEMU Wi-Fi init"            "init \(QEMU virtual Wi-Fi\)"
check "STA connected"              "WIFI_EVENT_STA_CONNECTED|sta_connected|event 0x01"
check "Got IP"                     "got ip:[0-9]"
check "No crash"                   "Guru Meditation|abort\(\)" && FAIL=$((FAIL-1)) \
    || { grep -qE "Guru Meditation|abort\(\)" "$LOG_FILE" && echo "  ❌ Crash detected" && FAIL=$((FAIL+1)) || true; }

echo ""
echo "[run-wifi-sta] $PASS check(s) passed, $FAIL failed."
[ "$FAIL" -eq 0 ]
