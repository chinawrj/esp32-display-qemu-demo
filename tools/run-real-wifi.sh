#!/usr/bin/env bash
# tools/run-real-wifi.sh — Run a stock ESP-IDF Wi-Fi sample in QEMU using the
# HOST's real wpa_supplicant daemon.
#
# In this mode the QEMU device bridges its ctrl interface directly to the
# host's running wpa_supplicant.  The guest's esp_wifi_set_config(ssid/pass)
# commands are forwarded to the real wpa_supplicant; the host WiFi card
# connects, and the guest receives the host's real DHCP-assigned IP.
#
# Packet relay: TCP/UDP are proxied via normal host sockets — any destination
# reachable from the host network is reachable from the guest.
#
# Usage:
#   bash tools/run-real-wifi.sh <build_dir> [duration_s]
#
# Environment (all optional):
#   WIFI_IFACE    WiFi interface name (default: auto-detect first wireless NIC)
#   WIFI_SUDO     1 = run QEMU under sudo when wpa_supplicant socket is
#                 root-only (default: auto-detect)
#   PKT_SOCKET    Unix socket path for packet relay
#                 (default: /tmp/real-wifi-pkt-relay)
#   LOG_FILE      QEMU serial log (default: /tmp/real-wifi-qemu.log)
#   VERIFY_PROFILE station | scan | softap | custom | none
#                 (default: station — checks for "got ip:")
#   EXPECT_PATTERN  override expected log regex (profile-specific default)
#
# Prerequisites:
#   wpa_supplicant must be running on the host (NetworkManager satisfies this).
#
#   If the wpa_supplicant socket is root-only, either:
#     a) Add your user to the 'netdev' group (recommended, survives reboots):
#            sudo adduser "$USER" netdev
#            # then log out and back in
#     b) Set WIFI_SUDO=1 to run QEMU under sudo.
#        In that case create a tmux window named 'sudo' for the privileged
#        process, e.g.:
#            tmux new-window -n sudo
#            WIFI_SUDO=1 bash tools/run-real-wifi.sh <build_dir>
#
# Notes:
#   - The guest's SSID/password are taken from sdkconfig / Kconfig defaults
#     compiled into the firmware (same as in mock mode).  The real wpa_supplicant
#     will attempt to connect the host WiFi card to that SSID.
#   - No mock_wpa_supplicant.py is started in this mode.
#   - DHCP is handled by the real wpa_supplicant + host network stack; the guest
#     receives whatever IP the real DHCP server assigns.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ---------------------------------------------------------------------------
# Arguments
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
VERIFY_PROFILE="${VERIFY_PROFILE:-station}"
EXPECT_PAT="${EXPECT_PATTERN:-}"
LOG_FILE="${LOG_FILE:-/tmp/real-wifi-qemu.log}"
PKT_SOCKET="${PKT_SOCKET:-/tmp/real-wifi-pkt-relay}"
WIFI_SUDO="${WIFI_SUDO:-}"   # empty = auto-detect

QEMU_BIN="${QEMU_BIN:-${PROJECT_DIR}/tools/qemu-src/build/qemu-system-xtensa}"

case "$VERIFY_PROFILE" in
    station)  EXPECT_PAT="${EXPECT_PAT:-got ip:[0-9]}" ;;
    scan)     EXPECT_PAT="${EXPECT_PAT:-Total APs scanned}" ;;
    softap)   EXPECT_PAT="${EXPECT_PAT:-wifi_init_softap finished}" ;;
    custom)   : ;;   # caller must set EXPECT_PATTERN
    none)     EXPECT_PAT="" ;;
    *)        echo "[run-real-wifi] Unknown VERIFY_PROFILE '$VERIFY_PROFILE'" >&2; exit 1 ;;
esac

# ---------------------------------------------------------------------------
# Sanity checks
# ---------------------------------------------------------------------------
if [ ! -x "$QEMU_BIN" ]; then
    echo "[run-real-wifi] ERROR: QEMU binary not found: $QEMU_BIN" >&2
    echo "                Run: bash tools/build-qemu.sh" >&2
    exit 2
fi

MERGED_IMAGE="${BUILD_DIR}/flash_image.bin"
if [ ! -f "$MERGED_IMAGE" ]; then
    echo "[run-real-wifi] ERROR: merged flash image not found: $MERGED_IMAGE" >&2
    echo "                Run: bash tools/build-stock-sample.sh <sample_path>" >&2
    exit 2
fi

# ---------------------------------------------------------------------------
# Detect WiFi interface
# ---------------------------------------------------------------------------
if [ -n "${WIFI_IFACE:-}" ]; then
    echo "[run-real-wifi] WiFi interface: ${WIFI_IFACE} (from env)"
else
    # Prefer interfaces starting with wl, then wlan
    WIFI_IFACE=$(ip -o link show | awk -F': ' '{print $2}' | grep -E '^wl' | head -1 || true)
    if [ -z "${WIFI_IFACE:-}" ]; then
        echo "[run-real-wifi] ERROR: Could not detect a wireless interface." >&2
        echo "                Set WIFI_IFACE=wlan0 (or your interface name)." >&2
        exit 2
    fi
    echo "[run-real-wifi] WiFi interface: ${WIFI_IFACE} (auto-detected)"
fi

# ---------------------------------------------------------------------------
# Locate wpa_supplicant ctrl socket
# ---------------------------------------------------------------------------
WPA_SOCK="/var/run/wpa_supplicant/${WIFI_IFACE}"
if [ ! -S "$WPA_SOCK" ]; then
    echo "[run-real-wifi] ERROR: wpa_supplicant socket not found: $WPA_SOCK" >&2
    echo "                Ensure wpa_supplicant (or NetworkManager) is running." >&2
    echo "                systemctl status NetworkManager   # NetworkManager approach" >&2
    echo "                systemctl status wpa_supplicant   # standalone approach" >&2
    exit 2
fi
echo "[run-real-wifi] wpa_supplicant socket: $WPA_SOCK"

# ---------------------------------------------------------------------------
# Check socket accessibility; decide whether sudo is needed
# ---------------------------------------------------------------------------
if [ -z "$WIFI_SUDO" ]; then
    if [ -r "$WPA_SOCK" ] && [ -w "$WPA_SOCK" ]; then
        WIFI_SUDO=0
    else
        echo "[run-real-wifi] wpa_supplicant socket not accessible as '$USER'."
        echo "[run-real-wifi] Tip: sudo adduser \$USER netdev  (then re-login)"
        echo "[run-real-wifi] Falling back to WIFI_SUDO=1 for this run."
        WIFI_SUDO=1
    fi
fi

if [ "${WIFI_SUDO}" = "1" ]; then
    echo "[run-real-wifi] Running QEMU under sudo (WIFI_SUDO=1)."
    echo "[run-real-wifi] Recommend: create a tmux window named 'sudo' for this."
    QEMU_PREFIX="sudo"
else
    QEMU_PREFIX=""
fi

# ---------------------------------------------------------------------------
# Get real gateway IP from host routing table
# ---------------------------------------------------------------------------
GATEWAY_IP=$(ip route show default dev "${WIFI_IFACE}" 2>/dev/null \
    | awk '/^default/ {print $3; exit}' || true)
if [ -z "${GATEWAY_IP:-}" ]; then
    # Fallback: any default route
    GATEWAY_IP=$(ip route show default 2>/dev/null | awk '/^default/ {print $3; exit}' || true)
fi
if [ -z "${GATEWAY_IP:-}" ]; then
    echo "[run-real-wifi] WARNING: Could not detect gateway IP. ARP proxy will be disabled." >&2
    GATEWAY_IP=""
fi
echo "[run-real-wifi] Gateway IP: ${GATEWAY_IP:-<unknown>}"

# ---------------------------------------------------------------------------
# Activate Python venv
# ---------------------------------------------------------------------------
if [ -f "${PROJECT_DIR}/.venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "${PROJECT_DIR}/.venv/bin/activate"
fi

# ---------------------------------------------------------------------------
# Cleanup on exit
# ---------------------------------------------------------------------------
RELAY_PID=""
cleanup() {
    [ -n "$RELAY_PID" ] && kill "$RELAY_PID" 2>/dev/null || true
    rm -f "$PKT_SOCKET"
}
trap cleanup EXIT INT TERM

# ---------------------------------------------------------------------------
# Start wifi_packet_relay in real-WiFi mode
# ---------------------------------------------------------------------------
RELAY_ARGS=("${PROJECT_DIR}/tools/wifi_packet_relay.py" "$PKT_SOCKET")
if [ -n "$GATEWAY_IP" ]; then
    RELAY_ARGS+=(--gateway-ip "$GATEWAY_IP")
fi
RELAY_ARGS+=(--no-local-map)

echo "[run-real-wifi] Starting packet relay (gateway=${GATEWAY_IP:-none}, no-local-map)"
python3 "${RELAY_ARGS[@]}" &
RELAY_PID=$!
sleep 0.5   # let socket appear

# ---------------------------------------------------------------------------
# Build QEMU command
# ---------------------------------------------------------------------------
# The QEMU device picks up ESP_WIFI_CTRL_SOCKET for the ctrl socket path.
# In sudo mode the socket is still accessible because sudo inherits the env.
export ESP_WIFI_CTRL_SOCKET="${WPA_SOCK}"
export ESP_WIFI_PKT_SOCKET="${PKT_SOCKET}"

EFUSE_BIN="${BUILD_DIR}/efuse.bin"
QEMU_ARGS=(
    -M esp32
    -m 4M
    -nographic
    -drive "file=${MERGED_IMAGE},if=mtd,format=raw"
    -global "driver=timer.esp32.timg,property=wdt_disable,value=true"
)
if [ -f "$EFUSE_BIN" ]; then
    QEMU_ARGS+=(
        -drive "file=${EFUSE_BIN},if=none,format=raw,id=efuse"
        -global "driver=nvram.esp32.efuse,property=drive,value=efuse"
    )
fi

# ---------------------------------------------------------------------------
# Run QEMU
# ---------------------------------------------------------------------------
echo "[run-real-wifi] Booting for ${DURATION}s → ${LOG_FILE}"
echo "[run-real-wifi] QEMU: $QEMU_BIN"
echo "[run-real-wifi] ctrl socket: $WPA_SOCK"
echo ""

if command -v timeout >/dev/null 2>&1; then
    # shellcheck disable=SC2086
    timeout --foreground -k 5 "${DURATION}" \
        ${QEMU_PREFIX} "${QEMU_BIN}" "${QEMU_ARGS[@]}" \
        2>&1 | tee "$LOG_FILE" || true
else
    # shellcheck disable=SC2086
    ${QEMU_PREFIX} "${QEMU_BIN}" "${QEMU_ARGS[@]}" >"$LOG_FILE" 2>&1 &
    QEMU_PID=$!
    sleep "${DURATION}"
    kill "$QEMU_PID" 2>/dev/null || true
    wait "$QEMU_PID" 2>/dev/null || true
fi

echo ""
echo "[run-real-wifi] === Serial log ==="
cat "$LOG_FILE"

# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
if [ -z "$EXPECT_PAT" ]; then
    echo "[run-real-wifi] No verification pattern (VERIFY_PROFILE=none or EXPECT_PATTERN unset)."
    exit 0
fi

echo ""
echo "[run-real-wifi] === Verification (profile: ${VERIFY_PROFILE}) ==="
if grep -qE "$EXPECT_PAT" "$LOG_FILE"; then
    echo "  ✅ PASS — found: $EXPECT_PAT"
    exit 0
else
    echo "  ❌ FAIL — pattern not found: $EXPECT_PAT"
    exit 1
fi
