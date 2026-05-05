#!/usr/bin/env bash
# tools/build-stock-sample.sh
#
# Build any ESP-IDF Wi-Fi sample against the QEMU virtual Wi-Fi simulator
# WITHOUT modifying any source file (.c, .h, CMakeLists.txt, sdkconfig).
#
# Usage:
#   bash tools/build-stock-sample.sh <sample-dir> [extra-idf-args...]
#
# Examples:
#   bash tools/build-stock-sample.sh \
#       $IDF_PATH/examples/wifi/getting_started/station
#
#   bash tools/build-stock-sample.sh \
#       $IDF_PATH/examples/wifi/scan -- menuconfig
#
# Environment overrides:
#   IDF_PATH          path to ESP-IDF (required; sourced automatically if set)
#   QEMU_WIFI_DIR     path to esp32-display-qemu-demo repo (default: auto-detect)
#   BUILD_DIR         where to put build artifacts (default: <sample>/build_qemu)
#   TARGET            IDF target chip (default: esp32)
#
# PRIMARY TARGET: This script is the primary mechanism for running any stock
# ESP-IDF Wi-Fi sample on the QEMU Wi-Fi simulator with zero source changes.
# Only CMakeLists.txt / sdkconfig changes are permitted by policy; this
# script satisfies the requirement via build-system flags only.
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
QEMU_WIFI_DIR="${QEMU_WIFI_DIR:-$PROJECT_DIR}"

# ---------------------------------------------------------------------------
# Validate args
# ---------------------------------------------------------------------------
if [ $# -lt 1 ]; then
    echo "Usage: $0 <sample-dir> [extra-idf-args...]" >&2
    exit 1
fi
SAMPLE_DIR="$(cd "$1" && pwd)"
shift

if [ ! -f "${SAMPLE_DIR}/CMakeLists.txt" ]; then
    echo "Error: ${SAMPLE_DIR} does not contain a CMakeLists.txt" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# IDF environment
# ---------------------------------------------------------------------------
if [ -z "${IDF_PATH:-}" ]; then
    echo "Error: IDF_PATH is not set. Source ESP-IDF's export.sh first." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Build config
# ---------------------------------------------------------------------------
TARGET="${TARGET:-esp32}"
BUILD_DIR="${BUILD_DIR:-${SAMPLE_DIR}/build_qemu}"

EXTRA_COMPONENT_DIRS="${QEMU_WIFI_DIR}/components"
QEMU_SDKCONFIG="${QEMU_WIFI_DIR}/sdkconfig.qemu.wifi.defaults"

# Detect if sample already has a sdkconfig.defaults
if [ -f "${SAMPLE_DIR}/sdkconfig.defaults" ]; then
    SDKCONFIG_DEFAULTS="sdkconfig.defaults;${QEMU_SDKCONFIG}"
else
    SDKCONFIG_DEFAULTS="${QEMU_SDKCONFIG}"
fi

echo "═══════════════════════════════════════════════════════════════"
echo "  QEMU Wi-Fi Stock Sample Builder"
echo "  Sample   : ${SAMPLE_DIR}"
echo "  Build dir: ${BUILD_DIR}"
echo "  IDF_PATH : ${IDF_PATH}"
echo "  Components overlay: ${EXTRA_COMPONENT_DIRS}"
echo "═══════════════════════════════════════════════════════════════"

# ---------------------------------------------------------------------------
# Run idf.py build with QEMU Wi-Fi overlay injected via -D flags
# ---------------------------------------------------------------------------
cd "${SAMPLE_DIR}"
idf.py \
    --build-dir "${BUILD_DIR}" \
    -DIDF_TARGET="${TARGET}" \
    -DEXTRA_COMPONENT_DIRS="${EXTRA_COMPONENT_DIRS}" \
    -DSDKCONFIG_DEFAULTS="${SDKCONFIG_DEFAULTS}" \
    "$@" \
    build

echo ""
echo "✓ Build succeeded."
echo "  Flash image : ${BUILD_DIR}/merged_flash.bin (create with tools/merge-flash.sh)"
echo "  Boot in QEMU: set ESP_WIFI_CTRL_SOCKET and ESP_WIFI_PKT_SOCKET, then:"
echo "    bash ${QEMU_WIFI_DIR}/tools/run-stock-qemu.sh ${BUILD_DIR}"
