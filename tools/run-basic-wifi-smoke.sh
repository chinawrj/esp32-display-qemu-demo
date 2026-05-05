#!/usr/bin/env bash
# tools/run-basic-wifi-smoke.sh
#
# Build and run the basic Wi-Fi release gate: stock station, scan, and softAP.
# This script is intentionally narrow for the six-day release target.
#
# Usage:
#   bash tools/run-basic-wifi-smoke.sh [duration_s]
#
# Environment:
#   IDF_PATH       ESP-IDF checkout path (auto-sources ~/esp-idf/export.sh if unset)
#   LOG_DIR        Directory for per-sample logs (default: /tmp/qemu-wifi-smoke)
#   QEMU_BIN       Optional qemu-system-xtensa override passed through to runner

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DURATION="${1:-60}"
LOG_DIR="${LOG_DIR:-/tmp/qemu-wifi-smoke}"

if [ -z "${IDF_PATH:-}" ] && [ -f "${HOME}/esp-idf/export.sh" ]; then
    # shellcheck disable=SC1091
    source "${HOME}/esp-idf/export.sh" >/dev/null 2>&1
fi

if [ -z "${IDF_PATH:-}" ]; then
    echo "ERROR: IDF_PATH is not set and ${HOME}/esp-idf/export.sh was not found" >&2
    exit 2
fi

mkdir -p "$LOG_DIR"

SAMPLES=(
    "station|${IDF_PATH}/examples/wifi/getting_started/station|station"
    "scan|${IDF_PATH}/examples/wifi/scan|scan"
    "softAP|${IDF_PATH}/examples/wifi/getting_started/softAP|softap"
)

PASS=0
FAIL=0

run_one() {
    local name="$1"
    local sample_dir="$2"
    local profile="$3"
    local build_dir="${sample_dir}/build_qemu"
    local build_log="${LOG_DIR}/${name}-build.log"
    local run_log="${LOG_DIR}/${name}-run.log"
    local serial_log="${LOG_DIR}/${name}-serial.log"

    echo "[basic-wifi-smoke] === ${name}: build ==="
    if bash "${PROJECT_DIR}/tools/build-stock-sample.sh" "$sample_dir" >"$build_log" 2>&1; then
        echo "[basic-wifi-smoke] ${name}: build ok"
    else
        echo "[basic-wifi-smoke] ${name}: build failed (log: ${build_log})"
        FAIL=$((FAIL + 1))
        return
    fi

    echo "[basic-wifi-smoke] === ${name}: run (${profile}) ==="
    if VERIFY_PROFILE="$profile" LOG_FILE="$serial_log" \
        bash "${PROJECT_DIR}/tools/run-stock-qemu.sh" "$build_dir" "$DURATION" >"$run_log" 2>&1; then
        echo "[basic-wifi-smoke] ${name}: run ok"
        PASS=$((PASS + 1))
    else
        echo "[basic-wifi-smoke] ${name}: run failed (log: ${run_log})"
        FAIL=$((FAIL + 1))
    fi
}

echo "[basic-wifi-smoke] IDF_PATH=${IDF_PATH}"
echo "[basic-wifi-smoke] LOG_DIR=${LOG_DIR}"
echo "[basic-wifi-smoke] DURATION=${DURATION}"

for entry in "${SAMPLES[@]}"; do
    IFS='|' read -r name sample_dir profile <<<"$entry"
    run_one "$name" "$sample_dir" "$profile"
done

echo ""
echo "[basic-wifi-smoke] Summary: ${PASS} passed, ${FAIL} failed"
echo "[basic-wifi-smoke] Logs: ${LOG_DIR}"

[ "$FAIL" -eq 0 ]