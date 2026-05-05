#!/usr/bin/env bash
# tools/run-stock-qemu.sh — Run any stock ESP-IDF Wi-Fi sample in QEMU.
#
# Works with samples built by tools/build-stock-sample.sh (artifacts land in
# <sample>/build_qemu/).  Starts mock_wpa_supplicant + wifi_packet_relay then
# boots QEMU; verifies the expected log line (default: "got ip:").
#
# Usage:
#   bash tools/run-stock-qemu.sh <build_dir> [duration_s]
#
# Examples:
#   bash tools/run-stock-qemu.sh \
#       $IDF_PATH/examples/wifi/getting_started/station/build_qemu
#
#   bash tools/run-stock-qemu.sh \
#       $IDF_PATH/examples/wifi/getting_started/station/build_qemu 60
#
# Environment:
#   WIFI_SSID          SSID the mock AP advertises (default: QEMU_TEST)
#   WIFI_PASS          password (default: qemu1234, mock ignores it anyway)
#   MOCK_WIFI_IP       IP assigned to firmware STA (default: 10.0.2.15)
#   EXPECT_PATTERN     log pattern to verify (default: "got ip:[0-9]")
#   LOG_FILE           where to write QEMU serial output (default: /tmp/stock-qemu.log)
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------
if [ $# -lt 1 ]; then
    echo "Usage: $0 <build_dir> [duration_s]" >&2
    exit 1
fi
BUILD_DIR="$(cd "$1" && pwd)"
DURATION="${2:-60}"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
WIFI_SSID="${WIFI_SSID:-QEMU_TEST}"
WIFI_PASS="${WIFI_PASS:-qemu1234}"
MOCK_IP="${MOCK_WIFI_IP:-10.0.2.15}"
EXPECT_PAT="${EXPECT_PATTERN:-got ip:[0-9]}"
LOG_FILE="${LOG_FILE:-/tmp/stock-qemu.log}"
MOCK_SOCKET="${ESP_WIFI_CTRL_SOCKET:-/tmp/stock-mock-wpa}"
PKT_SOCKET="${ESP_WIFI_PKT_SOCKET:-/tmp/stock-pkt-relay}"

QEMU_BIN="${QEMU_BIN:-${PROJECT_DIR}/tools/qemu-src/build/qemu-system-xtensa}"

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
if [ ! -x "$QEMU_BIN" ]; then
    echo "ERROR: QEMU binary not found: $QEMU_BIN" >&2
    echo "  Run: bash tools/build-qemu.sh" >&2
    exit 2
fi

# Find the flash partitions from flash_args or flasher_args.json
if [ ! -f "$BUILD_DIR/flasher_args.json" ]; then
    echo "ERROR: ${BUILD_DIR}/flasher_args.json not found — did the build succeed?" >&2
    exit 2
fi

# ---------------------------------------------------------------------------
# Merge flash image
# ---------------------------------------------------------------------------
FLASH_IMAGE="${BUILD_DIR}/merged_flash.bin"
IDF_PYTHON="$(ls ~/.espressif/python_env/idf*_env/bin/python3 2>/dev/null | sort | tail -1 || echo python3)"
IDF_PATH_RESOLVED="${IDF_PATH:-${HOME}/esp-idf}"

# Parse offsets from flasher_args.json using python
echo "[run-stock-qemu] Merging flash image..."
"$IDF_PYTHON" - <<'PYEOF' "$BUILD_DIR" "$FLASH_IMAGE" "$IDF_PATH_RESOLVED"
import json, sys, subprocess, pathlib
build_dir = pathlib.Path(sys.argv[1])
out_img   = sys.argv[2]
idf_path  = pathlib.Path(sys.argv[3])
esptool   = idf_path / "components" / "esptool_py" / "esptool" / "esptool.py"

with open(build_dir / "flasher_args.json") as f:
    fargs = json.load(f)

flash_files = fargs.get("flash_files", {})
cmd = [sys.executable, str(esptool),
       "--chip", "esp32", "merge_bin",
       "--fill-flash-size", "2MB",
       "--flash_mode", "dio", "--flash_freq", "40m", "--flash_size", "2MB",
       "-o", out_img]
for offset, rel_path in sorted(flash_files.items(), key=lambda x: int(x[0], 16)):
    cmd += [offset, str(build_dir / rel_path)]

print("[merge_bin]", " ".join(cmd[5:]))
subprocess.check_call(cmd)
print("[merge_bin] Done:", out_img)
PYEOF

EFUSE_BIN="${PROJECT_DIR}/build/qemu_efuse.bin"
if [ ! -f "$EFUSE_BIN" ]; then
    EFUSE_BIN="${BUILD_DIR}/qemu_efuse.bin"
    dd if=/dev/zero bs=1 count=1024 2>/dev/null | tr '\0' '\377' > "$EFUSE_BIN"
fi

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
MOCK_PID=""
RELAY_PID=""

cleanup() {
    [ -n "$MOCK_PID"  ] && kill "$MOCK_PID"  2>/dev/null || true
    [ -n "$RELAY_PID" ] && kill "$RELAY_PID" 2>/dev/null || true
    rm -f "$MOCK_SOCKET" "$PKT_SOCKET"
}
trap cleanup EXIT INT TERM

# Activate venv
[ -f "${PROJECT_DIR}/.venv/bin/activate" ] && source "${PROJECT_DIR}/.venv/bin/activate"

# ---------------------------------------------------------------------------
# Start mock wpa_supplicant
# ---------------------------------------------------------------------------
echo "[run-stock-qemu] Starting mock_wpa_supplicant (SSID=${WIFI_SSID}, IP=${MOCK_IP})"
python3 "${PROJECT_DIR}/tools/mock_wpa_supplicant.py" \
    --ctrl-path "$MOCK_SOCKET" \
    --ssid      "$WIFI_SSID"   \
    --ip        "$MOCK_IP" \
    --gateway   "10.0.2.2" \
    --netmask   "255.255.255.0" &
MOCK_PID=$!
sleep 1

# ---------------------------------------------------------------------------
# Start wifi_packet_relay.py
# ---------------------------------------------------------------------------
echo "[run-stock-qemu] Starting wifi_packet_relay.py (socket=${PKT_SOCKET})"
python3 "${PROJECT_DIR}/tools/wifi_packet_relay.py" \
    "$PKT_SOCKET" &
RELAY_PID=$!
sleep 1

# ---------------------------------------------------------------------------
# Boot QEMU
# ---------------------------------------------------------------------------
export ESP_WIFI_CTRL_SOCKET="${MOCK_SOCKET}"
export ESP_WIFI_PKT_SOCKET="${PKT_SOCKET}"

QEMU_ARGS=(
    -M  esp32
    -m  4M
    -nographic
    -drive "file=${FLASH_IMAGE},if=mtd,format=raw"
    -drive "file=${EFUSE_BIN},if=none,format=raw,id=efuse"
    -global "driver=nvram.esp32.efuse,property=drive,value=efuse"
    -global "driver=timer.esp32.timg,property=wdt_disable,value=true"
)

echo "[run-stock-qemu] Booting QEMU for ${DURATION}s, log -> ${LOG_FILE}"
timeout --foreground -k 5 "${DURATION}" "${QEMU_BIN}" "${QEMU_ARGS[@]}" \
    2>&1 | tee "$LOG_FILE" || true

# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------
echo ""
echo "[run-stock-qemu] === Verification ==="
PASS=0; FAIL=0
check() {
    local label="$1" pattern="$2" negate="${3:-0}"
    if grep -qE "$pattern" "$LOG_FILE"; then
        if [ "$negate" -eq 0 ]; then
            echo "  ✅ $label"
            PASS=$((PASS+1))
        else
            echo "  ❌ $label (should NOT be present)"
            FAIL=$((FAIL+1))
        fi
    else
        if [ "$negate" -eq 0 ]; then
            echo "  ❌ $label  (pattern: $pattern)"
            FAIL=$((FAIL+1))
        else
            echo "  ✅ $label (not present, as expected)"
            PASS=$((PASS+1))
        fi
    fi
}

check "QEMU Wi-Fi init"  "QEMU virtual Wi-Fi|wifi_qemu_init|esp_wifi_qemu"
check "STA started"      "WIFI_EVENT_STA_START|wifi.*start|sta_start"
# STA connected check is optional — scan samples don't connect; skip with SKIP_CONNECTED=1
if [ "${SKIP_CONNECTED:-0}" != "1" ]; then
    check "STA connected"    "CONNECTED|sta_connected|WIFI_EVENT_STA_CONNECTED|connected to ap"
fi
check "Got IP"           "$EXPECT_PAT"
check "No crash"         "Guru Meditation|abort\(\)" 1

echo ""
echo "[run-stock-qemu] $PASS check(s) passed, $FAIL failed."
[ "$FAIL" -eq 0 ]
