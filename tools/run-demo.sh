#!/usr/bin/env bash
# tools/run-demo.sh — One-command live framebuffer pipeline.
#
# Boots QEMU with the esp_rgb VRAM mmap export enabled, starts the host
# fb_server in --source raw-vram mode, and prints the Chrome URL. Both
# processes run in the foreground until Ctrl-C; cleanup on exit is
# guaranteed by an EXIT trap.
#
# Usage:
#   ./tools/run-demo.sh                 # interactive: open the URL in Chrome yourself
#   ./tools/run-demo.sh --auto-test     # run a Playwright smoke check + screenshot, exit
#   ./tools/run-demo.sh --duration 60   # auto-stop QEMU after 60 s (default: until Ctrl-C)
#
# Environment overrides:
#   QEMU_BIN          path to qemu-system-xtensa (default: tools/qemu-src/build/...)
#   ESP_RGB_VRAM_FILE shared mmap path (default: /tmp/esp32-rgb-vram.bin)
#   FB_WS_PORT        WebSocket port (default: 7788)
#   FB_HTTP_PORT      HTTP port (default: 8080)

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

MODE="interactive"
DURATION=""
while [ $# -gt 0 ]; do
    case "$1" in
        --auto-test) MODE="auto-test" ;;
        --no-browser) MODE="no-browser" ;;
        --duration) shift; DURATION="${1:-}" ;;
        --duration=*) DURATION="${1#--duration=}" ;;
        -h|--help)
            sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
    esac
    shift
done

VRAM_FILE="${ESP_RGB_VRAM_FILE:-/tmp/esp32-rgb-vram.bin}"
WS_PORT="${FB_WS_PORT:-7788}"
HTTP_PORT="${FB_HTTP_PORT:-8080}"
VRAM_Y="${VRAM_Y:-0}"   # 0 = live mirror (every flush, Day-23 scene); 200 = frozen snapshot at flush #80
URL="http://127.0.0.1:${HTTP_PORT}/index.html?ws=${WS_PORT}"

QEMU_PID=""
SERVER_PID=""

cleanup() {
    local rc=$?
    set +e
    if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "[run-demo] stopping fb_server (pid=$SERVER_PID)"
        kill "$SERVER_PID" 2>/dev/null
        wait "$SERVER_PID" 2>/dev/null
    fi
    if [ -n "$QEMU_PID" ] && kill -0 "$QEMU_PID" 2>/dev/null; then
        echo "[run-demo] stopping QEMU (pid=$QEMU_PID)"
        kill "$QEMU_PID" 2>/dev/null
        wait "$QEMU_PID" 2>/dev/null
    fi
    exit "$rc"
}
trap cleanup EXIT INT TERM

# --- Sanity ---
if [ ! -f build/esp32-display-qemu-demo.bin ]; then
    echo "ERROR: build/esp32-display-qemu-demo.bin missing — run 'idf.py build' first" >&2
    exit 2
fi

if [ -z "${IDF_PATH:-}" ]; then
    # shellcheck disable=SC1091
    source "${IDF_PATH:-$HOME/esp-idf}/export.sh" > /dev/null 2>&1
fi

# --- 1. Boot QEMU in background with VRAM mmap export ---
rm -f "$VRAM_FILE"
QEMU_LOG="/tmp/run-demo-qemu.log"
echo "[run-demo] starting QEMU (VRAM file: $VRAM_FILE) -> $QEMU_LOG"
(
    export ESP_RGB_VRAM_FILE="$VRAM_FILE"
    DUR_ARG="${DURATION:-3600}"  # bash run-qemu requires a duration; default very long
    bash tools/run-qemu.sh "$DUR_ARG" run > "$QEMU_LOG" 2>&1
) &
QEMU_PID=$!

# Wait until VRAM file is created (means QEMU mapped the region).
echo "[run-demo] waiting for VRAM file to appear..."
for _ in $(seq 1 60); do
    [ -s "$VRAM_FILE" ] && break
    sleep 1
done
if [ ! -s "$VRAM_FILE" ]; then
    echo "ERROR: VRAM file never appeared. Last QEMU log:" >&2
    tail -30 "$QEMU_LOG" >&2
    exit 3
fi
echo "[run-demo] VRAM file ready ($(stat -f%z "$VRAM_FILE" 2>/dev/null || stat -c%s "$VRAM_FILE") bytes)"

# --- 2. Start fb_server in background (raw-vram source) ---
SERVER_LOG="/tmp/run-demo-fb-server.log"
echo "[run-demo] starting fb_server raw-vram on ws=$WS_PORT http=$HTTP_PORT"
.venv/bin/python -m tools.fb_server.server \
    --source raw-vram \
    --vram-path "$VRAM_FILE" \
    --vram-x 0 --vram-y "$VRAM_Y" --surface-w 800 \
    --width 240 --height 135 \
    --ws-port "$WS_PORT" --http-port "$HTTP_PORT" \
    --fps 30 > "$SERVER_LOG" 2>&1 &
SERVER_PID=$!

# Wait for HTTP port to be listening.
for _ in $(seq 1 30); do
    if (echo > "/dev/tcp/127.0.0.1/$HTTP_PORT") 2>/dev/null; then break; fi
    sleep 0.2
done

echo ""
echo "════════════════════════════════════════"
echo " 🟢 Live framebuffer pipeline running"
echo "════════════════════════════════════════"
echo "   QEMU pid=$QEMU_PID  log=$QEMU_LOG"
echo "   fb_server pid=$SERVER_PID  log=$SERVER_LOG"
echo "   Chrome URL: $URL"
echo "════════════════════════════════════════"

case "$MODE" in
    auto-test)
        echo "[run-demo] running auto-test (Playwright smoke check)..."
        FB_URL="$URL" .venv/bin/python tools/auto_test_canvas.py
        ;;
    no-browser)
        echo "[run-demo] no-browser mode; press Ctrl-C to stop"
        wait "$QEMU_PID"
        ;;
    interactive)
        if command -v open >/dev/null 2>&1; then
            open "$URL" || true
        fi
        echo "[run-demo] press Ctrl-C to stop"
        wait "$QEMU_PID"
        ;;
esac
