#!/usr/bin/env bash
# tools/run-direct-demo.sh — QEMU-native WebSocket framebuffer viewer (NEXT-001/003).
#
# Boots the patched QEMU binary that includes the built-in esp_rgb WebSocket
# server.  The firmware's LVGL output is streamed directly from the QEMU
# device to the browser via ws://127.0.0.1:$PORT/ — no host-side fb_server
# or shared memory file required.
#
# Also starts mock_wpa_supplicant so the integrated Wi-Fi demo shows
# "got ip:192.168.1.100" in the LVGL label (NEXT-003).
#
# Usage:
#   bash tools/run-direct-demo.sh                    # open browser automatically
#   bash tools/run-direct-demo.sh --no-browser       # just start QEMU + print URL
#   bash tools/run-direct-demo.sh --port 9334        # override WS port (default: 9334)
#   bash tools/run-direct-demo.sh --duration 60      # auto-stop after 60 s
#   bash tools/run-direct-demo.sh --no-wifi          # skip mock Wi-Fi daemon
#   bash tools/run-direct-demo.sh --no-relay         # skip wifi_packet_relay (no lwIP probe)
#
# Environment overrides:
#   QEMU_BIN              path to qemu-system-xtensa (default: tools/qemu-src/build/...)
#   ESP_RGB_WS_PORT       WebSocket port (default: 9334)
#   HTTP_PORT             HTTP port for serving web/ (default: 8090)
#   WIFI_CTRL_SOCKET      mock wpa_supplicant socket path (default: /tmp/mock-wpa-demo)
#   MOCK_WIFI_IP          IP the mock AP assigns to firmware (default: 10.0.2.15, SLIRP)
#   LWIP_PROBE_PORT       TCP port for the host-side echo server (default: 9988)

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
MODE="browser"
DURATION=""
ENABLE_WIFI="1"
ENABLE_RELAY="1"
while [ $# -gt 0 ]; do
    case "$1" in
        --no-browser) MODE="no-browser" ;;
        --no-wifi)    ENABLE_WIFI="0" ;;
        --no-relay)   ENABLE_RELAY="0" ;;
        --port)       shift; ESP_RGB_WS_PORT="${1:-9334}" ;;
        --port=*)     ESP_RGB_WS_PORT="${1#--port=}" ;;
        --duration)   shift; DURATION="${1:-}" ;;
        --duration=*) DURATION="${1#--duration=}" ;;
        -h|--help)
            sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "[run-direct-demo] unknown arg: $1" >&2; exit 1 ;;
    esac
    shift
done

WS_PORT="${ESP_RGB_WS_PORT:-9334}"
HTTP_PORT="${HTTP_PORT:-8090}"
MOCK_SOCKET="${WIFI_CTRL_SOCKET:-/tmp/mock-wpa-demo}"
MOCK_IP="${MOCK_WIFI_IP:-10.0.2.15}"
PKT_SOCKET="${ESP_WIFI_PKT_SOCKET:-/tmp/pkt-relay-demo}"
LWIP_PORT="${LWIP_PROBE_PORT:-9988}"

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
MOCK_WPA_PID=""
PKT_RELAY_PID=""
ECHO_SRV_PID=""

cleanup() {
    local rc=$?
    set +e
    if [ -n "$MOCK_WPA_PID" ] && kill -0 "$MOCK_WPA_PID" 2>/dev/null; then
        echo "[run-direct-demo] stopping mock-wpa-supplicant (pid=$MOCK_WPA_PID)"
        kill "$MOCK_WPA_PID" 2>/dev/null
        wait "$MOCK_WPA_PID" 2>/dev/null
    fi
    if [ -n "$PKT_RELAY_PID" ] && kill -0 "$PKT_RELAY_PID" 2>/dev/null; then
        echo "[run-direct-demo] stopping wifi_packet_relay (pid=$PKT_RELAY_PID)"
        kill "$PKT_RELAY_PID" 2>/dev/null
        wait "$PKT_RELAY_PID" 2>/dev/null
    fi
    if [ -n "$ECHO_SRV_PID" ] && kill -0 "$ECHO_SRV_PID" 2>/dev/null; then
        echo "[run-direct-demo] stopping echo server (pid=$ECHO_SRV_PID)"
        kill "$ECHO_SRV_PID" 2>/dev/null
        wait "$ECHO_SRV_PID" 2>/dev/null
    fi
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
# Start mock Wi-Fi daemon (NEXT-003: API-level Wi-Fi simulation)
# Simulates wpa_supplicant ctrl socket so firmware gets 'got ip:' without
# real hardware. Disabled with --no-wifi or if python3 unavailable.
# ---------------------------------------------------------------------------
if [ "$ENABLE_WIFI" = "1" ] && command -v python3 >/dev/null 2>&1; then
    # Clean up stale socket
    rm -f "$MOCK_SOCKET"
    echo "[run-direct-demo] starting mock-wpa-supplicant (socket=$MOCK_SOCKET, ip=$MOCK_IP)..."
    python3 "$PROJECT_DIR/tools/mock_wpa_supplicant.py" \
        --ctrl-path "$MOCK_SOCKET" \
        --ip "$MOCK_IP" \
        --ssid "QEMU_TEST" \
        </dev/null >/tmp/mock-wpa-demo.log 2>&1 &
    MOCK_WPA_PID=$!
    # Wait up to 2 s for socket to appear
    for i in $(seq 1 20); do
        [ -S "$MOCK_SOCKET" ] && break
        sleep 0.1
    done
    if [ -S "$MOCK_SOCKET" ]; then
        echo "[run-direct-demo] mock-wpa-supplicant ready."
        export ESP_WIFI_CTRL_SOCKET="$MOCK_SOCKET"
    else
        echo "[run-direct-demo] WARN: mock-wpa socket did not appear; continuing without Wi-Fi mock." >&2
        MOCK_WPA_PID=""
    fi
else
    echo "[run-direct-demo] Wi-Fi mock disabled (--no-wifi or python3 unavailable)"
fi

# ---------------------------------------------------------------------------
# Start wifi_packet_relay.py + host echo server (NEXT-004: lwIP data plane)
# The relay bridges QEMU DMA packets to real TCP/UDP via SLIRP NAT.
# The echo server listens on LWIP_PORT; firmware's lwip_probe.c connects to
# 10.0.2.100:LWIP_PORT, which the relay maps to 127.0.0.1:LWIP_PORT.
# ---------------------------------------------------------------------------
if [ "$ENABLE_WIFI" = "1" ] && [ "$ENABLE_RELAY" = "1" ] && command -v python3 >/dev/null 2>&1; then
    rm -f "$PKT_SOCKET"

    # Start the relay daemon
    echo "[run-direct-demo] starting wifi_packet_relay (socket=$PKT_SOCKET)..."
    export ESP_WIFI_PKT_SOCKET="$PKT_SOCKET"
    python3 "$PROJECT_DIR/tools/wifi_packet_relay.py" "$PKT_SOCKET" \
        </dev/null >/tmp/pkt-relay-demo.log 2>&1 &
    PKT_RELAY_PID=$!

    # Start a minimal TCP echo server on LWIP_PORT
    echo "[run-direct-demo] starting TCP echo server on port $LWIP_PORT..."
    python3 "$PROJECT_DIR/tools/echo_server.py" "$LWIP_PORT" \
        </dev/null >/tmp/echo-srv-demo.log 2>&1 &
    ECHO_SRV_PID=$!

    # Wait up to 2 s for relay socket to appear
    for i in $(seq 1 20); do
        [ -S "$PKT_SOCKET" ] && break
        sleep 0.1
    done
    if [ -S "$PKT_SOCKET" ]; then
        echo "[run-direct-demo] wifi_packet_relay ready."
    else
        echo "[run-direct-demo] WARN: pkt-relay socket did not appear; lwIP probe may fail." >&2
        PKT_RELAY_PID=""
    fi
else
    echo "[run-direct-demo] packet relay disabled (--no-relay, --no-wifi, or python3 unavailable)"
    unset ESP_WIFI_PKT_SOCKET
fi

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
echo "│  QEMU LVGL + Wi-Fi Integration Demo (NEXT-001/003)              │"
echo "│                                                                  │"
echo "│  Open in Chrome:  $PAGE_URL"
echo "│                                                                  │"
echo "│  LVGL content appears ~3 s after boot.                          │"
echo "│  Wi-Fi label updates to 'got ip:$MOCK_IP' ~15 s.    │"
echo "│  Ctrl-C to stop.                                                 │"
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
