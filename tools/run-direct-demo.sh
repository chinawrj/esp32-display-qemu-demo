#!/usr/bin/env bash
# tools/run-direct-demo.sh — QEMU-native WebSocket framebuffer viewer (NEXT-001).
#
# Boots the patched QEMU binary that includes the built-in esp_rgb WebSocket
# server.  The firmware's LVGL output is streamed directly from the QEMU
# device to the browser via ws://127.0.0.1:$PORT/ — no host-side fb_server
# or shared memory file required.
#
# Usage:
#   bash tools/run-direct-demo.sh                    # open browser automatically
#   bash tools/run-direct-demo.sh --no-browser       # just start QEMU + print URL
#   bash tools/run-direct-demo.sh --port 9334        # override WS port (default: 9334)
#   bash tools/run-direct-demo.sh --duration 60      # auto-stop after 60 s
#
# Environment overrides:
#   QEMU_BIN          path to qemu-system-xtensa (default: tools/qemu-src/build/...)
#   ESP_RGB_WS_PORT   WebSocket port (default: 9334)
#   HTTP_PORT         HTTP port for serving web/ (default: 8090)

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
MODE="browser"
DURATION=""
while [ $# -gt 0 ]; do
    case "$1" in
        --no-browser) MODE="no-browser" ;;
        --port)       shift; ESP_RGB_WS_PORT="${1:-9334}" ;;
        --port=*)     ESP_RGB_WS_PORT="${1#--port=}" ;;
        --duration)   shift; DURATION="${1:-}" ;;
        --duration=*) DURATION="${1#--duration=}" ;;
        -h|--help)
            sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "[run-direct-demo] unknown arg: $1" >&2; exit 1 ;;
    esac
    shift
done

WS_PORT="${ESP_RGB_WS_PORT:-9334}"
HTTP_PORT="${HTTP_PORT:-8090}"

# ---------------------------------------------------------------------------
# Locate QEMU binary and firmware
# ---------------------------------------------------------------------------
QEMU_BIN="${QEMU_BIN:-$PROJECT_DIR/tools/qemu-src/build/qemu-system-xtensa}"
FLASH_BIN="$PROJECT_DIR/build/qemu_flash.bin"
EFUSE_BIN="$PROJECT_DIR/build/qemu_efuse.bin"

if [ ! -x "$QEMU_BIN" ]; then
    echo "[run-direct-demo] ERROR: QEMU binary not found at $QEMU_BIN" >&2
    echo "  Run 'bash tools/build-qemu.sh' to build it." >&2
    exit 1
fi
if [ ! -f "$FLASH_BIN" ] || [ ! -f "$EFUSE_BIN" ]; then
    echo "[run-direct-demo] ERROR: firmware not built ($FLASH_BIN missing)" >&2
    echo "  Run 'idf.py build' to build the firmware." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Process management
# ---------------------------------------------------------------------------
QEMU_PID=""
HTTP_PID=""

cleanup() {
    local rc=$?
    set +e
    if [ -n "$HTTP_PID" ] && kill -0 "$HTTP_PID" 2>/dev/null; then
        echo "[run-direct-demo] stopping HTTP server (pid=$HTTP_PID)"
        kill "$HTTP_PID" 2>/dev/null
        wait "$HTTP_PID" 2>/dev/null
    fi
    if [ -n "$QEMU_PID" ] && kill -0 "$QEMU_PID" 2>/dev/null; then
        echo "[run-direct-demo] stopping QEMU (pid=$QEMU_PID)"
        kill "$QEMU_PID" 2>/dev/null
        wait "$QEMU_PID" 2>/dev/null
    fi
    exit "$rc"
}
trap cleanup EXIT INT TERM

# ---------------------------------------------------------------------------
# Start QEMU (WebSocket listener on $WS_PORT)
# ---------------------------------------------------------------------------
echo "[run-direct-demo] starting QEMU (WS port $WS_PORT)..."
export ESP_RGB_WS_PORT="$WS_PORT"
unset ESP_RGB_WS_DISABLE
unset ESP_RGB_VRAM_FILE   # use anonymous VRAM — WS path does not need the file

"$QEMU_BIN" \
    -machine esp32 \
    -drive "file=$FLASH_BIN,if=mtd,format=raw" \
    -drive "file=$EFUSE_BIN,if=none,format=raw,id=efuse" \
    -global "driver=nvram.esp32.efuse,property=drive,value=efuse" \
    -global "driver=timer.esp32.timg,property=wdt_disable,value=true" \
    -display none \
    -serial null \
    2>&1 &
QEMU_PID=$!

# Wait up to 5 s for the WS port to open
echo "[run-direct-demo] waiting for WS listener on port $WS_PORT..."
READY=0
for i in $(seq 1 25); do
    if python3 -c "import socket; s=socket.create_connection(('127.0.0.1',$WS_PORT),0.2); s.close()" 2>/dev/null; then
        READY=1; break
    fi
    sleep 0.2
done
if [ "$READY" -eq 0 ]; then
    echo "[run-direct-demo] ERROR: WS port $WS_PORT did not open in 5 s" >&2
    exit 1
fi
echo "[run-direct-demo] QEMU WS listener ready."

# ---------------------------------------------------------------------------
# Start a tiny HTTP server to serve web/qemu-direct.html
# ---------------------------------------------------------------------------
python3 -m http.server "$HTTP_PORT" --directory "$PROJECT_DIR/web" \
    --bind 127.0.0.1 </dev/null >/dev/null 2>&1 &
HTTP_PID=$!
sleep 0.3  # let the HTTP server bind

PAGE_URL="http://127.0.0.1:${HTTP_PORT}/qemu-direct.html?port=${WS_PORT}"
echo ""
echo "┌─────────────────────────────────────────────────────────────────┐"
echo "│  QEMU-native WebSocket canvas viewer (NEXT-001)                 │"
echo "│                                                                  │"
echo "│  Open in Chrome:  $PAGE_URL"
echo "│                                                                  │"
echo "│  LVGL content appears ~3 s after boot.  Ctrl-C to stop.         │"
echo "└─────────────────────────────────────────────────────────────────┘"
echo ""

if [ "$MODE" = "browser" ]; then
    # Try to open the browser (Linux: xdg-open, macOS: open)
    if command -v xdg-open &>/dev/null; then
        xdg-open "$PAGE_URL" 2>/dev/null || true
    elif command -v open &>/dev/null; then
        open "$PAGE_URL" 2>/dev/null || true
    fi
fi

# ---------------------------------------------------------------------------
# Wait for duration or user interrupt
# ---------------------------------------------------------------------------
if [ -n "$DURATION" ]; then
    echo "[run-direct-demo] auto-stop in ${DURATION}s..."
    sleep "$DURATION"
else
    # Block until Ctrl-C or QEMU exits
    wait "$QEMU_PID" 2>/dev/null || true
fi
