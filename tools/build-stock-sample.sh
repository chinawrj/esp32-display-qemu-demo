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
#   EXTRA_SDKCONFIG_DEFAULTS
#                     extra sdkconfig.defaults file appended after sample +
#                     QEMU overlay (semicolon-separated; absolute paths).
#                     Useful when a sample defaults to features unavailable
#                     in QEMU (e.g. SD card, JTAG App Trace) and only the
#                     allowed sdkconfig channel can override them.
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
# Expose protocol_examples_common specifically (not the whole common_components dir,
# because some siblings like protocol_examples_tapif_io are linux-only and error on esp32).
EXTRA_COMPONENT_DIRS="${EXTRA_COMPONENT_DIRS};${IDF_PATH}/examples/common_components/protocol_examples_common"
QEMU_SDKCONFIG="${QEMU_WIFI_DIR}/sdkconfig.qemu.wifi.defaults"

# Detect if sample already has a sdkconfig.defaults
if [ -f "${SAMPLE_DIR}/sdkconfig.defaults" ]; then
    SDKCONFIG_DEFAULTS="${SAMPLE_DIR}/sdkconfig.defaults;${QEMU_SDKCONFIG}"
else
    SDKCONFIG_DEFAULTS="${QEMU_SDKCONFIG}"
fi

# Optional caller-supplied overlay (last → highest precedence). Allowed by
# our zero-source-diff policy because it goes through the sdkconfig channel.
if [ -n "${EXTRA_SDKCONFIG_DEFAULTS:-}" ]; then
    SDKCONFIG_DEFAULTS="${SDKCONFIG_DEFAULTS};${EXTRA_SDKCONFIG_DEFAULTS}"
fi

echo "═══════════════════════════════════════════════════════════════"
echo "  QEMU Wi-Fi Stock Sample Builder"
echo "  Sample   : ${SAMPLE_DIR}"
echo "  Build dir: ${BUILD_DIR}"
echo "  IDF_PATH : ${IDF_PATH}"
echo "  Components overlay: ${EXTRA_COMPONENT_DIRS}"
echo "═══════════════════════════════════════════════════════════════"

# ---------------------------------------------------------------------------
# Create a thin wrapper project that adds esp_wifi_qemu to main's REQUIRES.
# The wrapper is generated into BUILD_DIR/../_qemu_wrap_<name>/ and is
# recreated on every invocation.  The stock sample's .c/.h files are NEVER
# modified — only the generated wrapper CMakeLists files change.
# ---------------------------------------------------------------------------

WRAP_DIR="$(dirname "${BUILD_DIR}")/_qemu_wrap_$(basename "${SAMPLE_DIR}")"
WRAP_MAIN_DIR="${WRAP_DIR}/main"
mkdir -p "${WRAP_MAIN_DIR}"

# Day-51: invalidate the wrapper's persisted sdkconfig whenever the
# resolved SDKCONFIG_DEFAULTS chain changes (sample defaults, QEMU
# overlay, or caller-supplied EXTRA_SDKCONFIG_DEFAULTS).  ESP-IDF only
# consults SDKCONFIG_DEFAULTS to seed `sdkconfig` the first time; once
# the file exists, subsequent builds keep the previously-saved values
# even if a new overlay would have flipped them.  This caused power_save
# to ignore CONFIG_PM_ENABLE=n in its overlay on rebuild.  We hash the
# defaults chain and store it next to the wrapper's sdkconfig; if the
# hash changes we wipe sdkconfig (and the build dir) so the next idf.py
# reconfigure picks up the new chain.
SDKCONFIG_HASH=$(printf '%s' "${SDKCONFIG_DEFAULTS}" | sha1sum | awk '{print $1}')
HASH_FILE="${WRAP_DIR}/.sdkconfig_defaults.sha1"
if [ -f "${WRAP_DIR}/sdkconfig" ]; then
    PREV_HASH="$(cat "${HASH_FILE}" 2>/dev/null || true)"
    if [ "${PREV_HASH}" != "${SDKCONFIG_HASH}" ]; then
        echo "[build-stock-sample] SDKCONFIG_DEFAULTS chain changed; wiping stale sdkconfig"
        rm -f "${WRAP_DIR}/sdkconfig"
        rm -rf "${BUILD_DIR}"
    fi
fi
printf '%s\n' "${SDKCONFIG_HASH}" > "${HASH_FILE}"

SAMPLE_MAIN_DIR="${SAMPLE_DIR}/main"
if [ ! -d "$SAMPLE_MAIN_DIR" ]; then
    echo "Error: ${SAMPLE_DIR}/main directory not found" >&2
    exit 1
fi

# Detect project name from sample's top-level CMakeLists.txt
SAMPLE_PROJ_NAME=$(grep -m1 "^project(" "${SAMPLE_DIR}/CMakeLists.txt" 2>/dev/null \
    | sed 's/project(\([^ )]*\).*/\1/' || true)
[ -z "$SAMPLE_PROJ_NAME" ] && SAMPLE_PROJ_NAME="$(basename "${SAMPLE_DIR}")"

# ── Generate wrapper top-level CMakeLists.txt ─────────────────────────────
cat > "${WRAP_DIR}/CMakeLists.txt" <<WRAP_EOF
# AUTO-GENERATED by tools/build-stock-sample.sh — NOT part of stock sample.
cmake_minimum_required(VERSION 3.16)
include(\$ENV{IDF_PATH}/tools/cmake/project.cmake)
project(${SAMPLE_PROJ_NAME})
WRAP_EOF

# ── Symlink sample-root assets that sdkconfig may reference by relative
#    path (custom partition CSVs, etc.).  The wrapper IS the project root
#    from CMake's perspective, so anything resolved via
#    CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions_example.csv" must
#    sit alongside the wrapper CMakeLists.txt.
shopt -s nullglob
for asset in "${SAMPLE_DIR}"/partitions*.csv "${SAMPLE_DIR}"/*.csv; do
    name="$(basename "$asset")"
    ln -sf "$asset" "${WRAP_DIR}/${name}"
done
shopt -u nullglob

# ── Generate wrapper main/CMakeLists.txt ─────────────────────────────────

# Detect extra REQUIRES: add protocol_examples_common if any source uses it
EXTRA_REQUIRES=""
if grep -rl "protocol_examples_common" "${SAMPLE_MAIN_DIR}" >/dev/null 2>&1; then
    EXTRA_REQUIRES="protocol_examples_common"
fi

# Pull the sample's own component dependency lists out of its main/CMakeLists.txt.
# This is the only way to support samples that need extra components like
# `console`, `fatfs`, `esp_eth`, `app_trace`, `unity`, ... without modifying
# any source file.  We extract REQUIRES and PRIV_REQUIRES (multi-line
# tolerant) and merge them with our base set; duplicates are de-duped.
extract_requires_kw() {
    # $1 = keyword (REQUIRES|PRIV_REQUIRES); $2 = file
    awk -v kw="$1" '
        BEGIN { in_kw=0 }
        {
            line=$0
            # strip line comments
            sub(/#.*$/, "", line)
            if (in_kw) {
                # stop at next keyword or close paren
                if (line ~ /\)/) {
                    sub(/\).*$/, "", line)
                    print line
                    exit
                }
                if (line ~ /(SRCS|INCLUDE_DIRS|PRIV_INCLUDE_DIRS|REQUIRES|PRIV_REQUIRES|EMBED_FILES|EMBED_TXTFILES|KCONFIG|KCONFIG_PROJBUILD|LDFRAGMENTS|WHOLE_ARCHIVE)[[:space:]]/) {
                    # next keyword reached
                    sub(/(SRCS|INCLUDE_DIRS|PRIV_INCLUDE_DIRS|REQUIRES|PRIV_REQUIRES|EMBED_FILES|EMBED_TXTFILES|KCONFIG|KCONFIG_PROJBUILD|LDFRAGMENTS|WHOLE_ARCHIVE).*$/, "", line)
                    print line
                    exit
                }
                print line
                next
            }
            # match KEYWORD followed by space (so REQUIRES does not match PRIV_REQUIRES)
            re = "(^|[^A-Z_])" kw "[[:space:]]"
            if (line ~ re) {
                in_kw=1
                sub(".*" kw "[[:space:]]", "", line)
                if (line ~ /\)/) {
                    sub(/\).*$/, "", line)
                    print line
                    exit
                }
                if (line ~ /(SRCS|INCLUDE_DIRS|PRIV_INCLUDE_DIRS|REQUIRES|PRIV_REQUIRES|EMBED_FILES|EMBED_TXTFILES|KCONFIG|KCONFIG_PROJBUILD|LDFRAGMENTS|WHOLE_ARCHIVE)[[:space:]]/) {
                    sub(/(SRCS|INCLUDE_DIRS|PRIV_INCLUDE_DIRS|REQUIRES|PRIV_REQUIRES|EMBED_FILES|EMBED_TXTFILES|KCONFIG|KCONFIG_PROJBUILD|LDFRAGMENTS|WHOLE_ARCHIVE).*$/, "", line)
                    print line
                    exit
                }
                print line
            }
        }
    ' "$2" | tr -s ' \t\n"' ' '
}

SAMPLE_CMAKE="${SAMPLE_MAIN_DIR}/CMakeLists.txt"
SAMPLE_REQUIRES=""
SAMPLE_PRIV_REQUIRES=""
if [ -f "$SAMPLE_CMAKE" ]; then
    SAMPLE_REQUIRES="$(extract_requires_kw REQUIRES "$SAMPLE_CMAKE")"
    SAMPLE_PRIV_REQUIRES="$(extract_requires_kw PRIV_REQUIRES "$SAMPLE_CMAKE")"
fi

# Merge: base + sample's REQUIRES + sample's PRIV_REQUIRES + esp_wifi_qemu
# Note: we promote the sample's PRIV_REQUIRES into REQUIRES so that
# esp_wifi_qemu's INTERFACE link options (--whole-archive) propagate
# correctly via the wrapper main target.
MERGED_REQUIRES="esp_wifi esp_event esp_netif nvs_flash esp_wifi_qemu ${SAMPLE_REQUIRES} ${SAMPLE_PRIV_REQUIRES}${EXTRA_REQUIRES:+ $EXTRA_REQUIRES}"
# De-duplicate while preserving order
DEDUPED_REQUIRES="$(printf '%s\n' $MERGED_REQUIRES | awk '!seen[$0]++' | tr '\n' ' ')"

{
    echo "# AUTO-GENERATED by tools/build-stock-sample.sh"
    echo "idf_component_register("
    echo "    SRCS"
    find "${SAMPLE_MAIN_DIR}" -maxdepth 1 -name "*.c" | sort | while read -r src; do
        # Skip IPv6-only source files; our sdkconfig.qemu.wifi.defaults sets
        # CONFIG_EXAMPLE_IPV4=y; including *_v6.c files causes compile errors
        # because IPv6 code paths declare stack variables inside #if guards that
        # are then referenced unconditionally.
        case "$(basename "$src")" in
            *_v6.c) continue ;;
        esac
        echo "        \"$src\""
    done
    echo "    INCLUDE_DIRS \"${SAMPLE_MAIN_DIR}\""
    [ -f "${SAMPLE_MAIN_DIR}/Kconfig.projbuild" ] && \
        echo "    KCONFIG_PROJBUILD \"${SAMPLE_MAIN_DIR}/Kconfig.projbuild\""
    [ -f "${SAMPLE_MAIN_DIR}/Kconfig" ] && \
        echo "    KCONFIG \"${SAMPLE_MAIN_DIR}/Kconfig\""
    echo "    REQUIRES ${DEDUPED_REQUIRES}"
    echo ")"
} > "${WRAP_MAIN_DIR}/CMakeLists.txt"

# Symlink the sample's idf_component.yml (managed components manifest) so
# that any component-manager dependencies (e.g. console, sdmmc, fatfs) the
# sample lists are honored without copying it.
if [ -f "${SAMPLE_MAIN_DIR}/idf_component.yml" ]; then
    ln -sf "${SAMPLE_MAIN_DIR}/idf_component.yml" "${WRAP_MAIN_DIR}/idf_component.yml"
fi

echo "  Wrapper  : ${WRAP_DIR}"

cd "${WRAP_DIR}"
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
