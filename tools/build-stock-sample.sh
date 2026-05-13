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
# Day-59 (FB-032): only expose protocol_examples_common when the sample's
# main/ actually references it. Forcing it in unconditionally collides with
# samples that pull `ethernet_init` via idf_component.yml, because both
# components redefine the same EXAMPLE_USE_* Kconfig symbols, causing
# kconfgen to fail with choice-symbol conflicts (network/simple_sniffer,
# network/sta2eth, network/bridge, network/vlan_support).
SAMPLE_MAIN_DIR_PROBE="${SAMPLE_DIR}/main"
if [ -d "${SAMPLE_MAIN_DIR_PROBE}" ] && \
   grep -rqE 'protocol_examples_common|example_connect|example_disconnect|example_configure_stdin_stdout' \
       "${SAMPLE_MAIN_DIR_PROBE}" 2>/dev/null; then
    EXTRA_COMPONENT_DIRS="${EXTRA_COMPONENT_DIRS};${IDF_PATH}/examples/common_components/protocol_examples_common"
fi
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
# Day-58 FB-030: surface the sample's own components/ subtree to ESP-IDF's
# component discovery so samples like protocols/http_server/captive_portal
# (which ships dns_server) and system/console/advanced (cmd_system) link.
# EXTRA_COMPONENT_DIRS must be set BEFORE project.cmake is included.
EXTRA_COMPONENT_DIRS_LINE=""
if [ -d "${SAMPLE_DIR}/components" ]; then
    EXTRA_COMPONENT_DIRS_LINE="list(APPEND EXTRA_COMPONENT_DIRS \"${SAMPLE_DIR}/components\")"
fi
cat > "${WRAP_DIR}/CMakeLists.txt" <<WRAP_EOF
# AUTO-GENERATED by tools/build-stock-sample.sh — NOT part of stock sample.
cmake_minimum_required(VERSION 3.16)
${EXTRA_COMPONENT_DIRS_LINE}
include(\$ENV{IDF_PATH}/tools/cmake/project.cmake)
project(${SAMPLE_PROJ_NAME})
WRAP_EOF

# Day-57 FB-029 + Day-58 FB-031: re-emit every non-trivial line from the
# stock sample's top-level CMakeLists.txt that comes AFTER project(...) so
# that project-level calls — target_add_binary_data(), idf_component_get_
# property() + target_sources(), partition_table_get_partition_info(), etc.
# — apply to the wrap's project target.  Two rewrites:
#   1. ${CMAKE_CURRENT_SOURCE_DIR} / ${CMAKE_CURRENT_LIST_DIR} /
#      ${project_dir} / ${PROJECT_DIR}   →  ${SAMPLE_DIR}  (literal absolute
#      path), because the wrap dir is NOT the sample dir.
#   2. target_add_binary_data(... "<relative>" ...)'s asset-path argument is
#      additionally rewritten to absolute under ${SAMPLE_DIR}, because
#      target_add_binary_data resolves relative paths against PROJECT_DIR
#      (= the wrap dir, where the asset isn't).
SAMPLE_TOP_CMAKE="${SAMPLE_DIR}/CMakeLists.txt"
if [ -f "$SAMPLE_TOP_CMAKE" ]; then
    PROPAGATED=$(awk -v sdir="$SAMPLE_DIR" '
        BEGIN { in_post = 0 }
        # Mark everything strictly after project(...) as "post"
        /^[[:space:]]*project[[:space:]]*\(/ { in_post = 1; next }
        in_post == 0 { next }
        # Drop blank and comment-only lines
        /^[[:space:]]*$/ { next }
        /^[[:space:]]*#/ { next }
        {
            line = $0
            # Substitute project-dir-ish CMake variable refs to SAMPLE_DIR.
            gsub(/\$\{CMAKE_CURRENT_SOURCE_DIR\}/, sdir, line)
            gsub(/\$\{CMAKE_CURRENT_LIST_DIR\}/,   sdir, line)
            gsub(/\$\{PROJECT_DIR\}/,              sdir, line)
            gsub(/\$\{project_dir\}/,              sdir, line)
            # target_add_binary_data: additionally rewrite the first quoted
            # arg from a relative path to absolute under SAMPLE_DIR.
            if (line ~ /target_add_binary_data[[:space:]]*\(/) {
                n = index(line, "\"")
                if (n != 0) {
                    tail = substr(line, n+1)
                    m = index(tail, "\"")
                    if (m != 0) {
                        path = substr(tail, 1, m-1)
                        if (substr(path,1,1) != "/" && index(path, "${") == 0) {
                            line = substr(line, 1, n) sdir "/" path substr(tail, m)
                        }
                    }
                }
            }
            print line
        }
    ' "$SAMPLE_TOP_CMAKE")
    if [ -n "$PROPAGATED" ]; then
        {
            echo ""
            echo "# Day-57/58 (FB-029, FB-031): propagated from stock sample's project CMakeLists.txt"
            echo "$PROPAGATED"
        } >> "${WRAP_DIR}/CMakeLists.txt"
    fi
fi

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
# Day-56: symlink sample-root data subdirectories that sdkconfig keys
# may resolve relative to PROJECT_DIR (e.g. CONFIG_MBEDTLS_CUSTOM_CERTI-
# FICATE_BUNDLE_PATH="server_certs/ca_cert.pem" in system/ota/simple_ota_
# example).  We skip well-known build/component dirs to avoid recursing
# back into the wrap.
for dir in "${SAMPLE_DIR}"/*/; do
    name="$(basename "$dir")"
    case "$name" in
        main|build|build_*|_qemu_wrap_*|managed_components|components|test|tests) continue ;;
    esac
    ln -sfn "$dir" "${WRAP_DIR}/${name}"
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
                # Day-54 FB-026: check keyword boundary BEFORE close-paren.
                # A continuation line like `INCLUDE_DIRS ".")` matches
                # both regexes; if we strip from `)` first we leak the
                # other keyword value into the current argument list
                # (which broke protocols/sockets/udp_client whose
                # main/CMakeLists.txt has PRIV_REQUIRES ${priv_requires}
                # then INCLUDE_DIRS "." on consecutive lines).
                if (line ~ /(SRCS|INCLUDE_DIRS|PRIV_INCLUDE_DIRS|REQUIRES|PRIV_REQUIRES|EMBED_FILES|EMBED_TXTFILES|KCONFIG|KCONFIG_PROJBUILD|LDFRAGMENTS|WHOLE_ARCHIVE)[[:space:]]/) {
                    # next keyword reached
                    sub(/(SRCS|INCLUDE_DIRS|PRIV_INCLUDE_DIRS|REQUIRES|PRIV_REQUIRES|EMBED_FILES|EMBED_TXTFILES|KCONFIG|KCONFIG_PROJBUILD|LDFRAGMENTS|WHOLE_ARCHIVE).*$/, "", line)
                    print line
                    exit
                }
                # stop at close paren
                if (line ~ /\)/) {
                    sub(/\).*$/, "", line)
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
                # Day-54 FB-026: same ordering fix as continuation
                # branch above (keyword boundary before close-paren).
                if (line ~ /(SRCS|INCLUDE_DIRS|PRIV_INCLUDE_DIRS|REQUIRES|PRIV_REQUIRES|EMBED_FILES|EMBED_TXTFILES|KCONFIG|KCONFIG_PROJBUILD|LDFRAGMENTS|WHOLE_ARCHIVE)[[:space:]]/) {
                    sub(/(SRCS|INCLUDE_DIRS|PRIV_INCLUDE_DIRS|REQUIRES|PRIV_REQUIRES|EMBED_FILES|EMBED_TXTFILES|KCONFIG|KCONFIG_PROJBUILD|LDFRAGMENTS|WHOLE_ARCHIVE).*$/, "", line)
                    print line
                    exit
                }
                if (line ~ /\)/) {
                    sub(/\).*$/, "", line)
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
SAMPLE_EMBED_FILES=""
SAMPLE_EMBED_TXTFILES=""
if [ -f "$SAMPLE_CMAKE" ]; then
    SAMPLE_REQUIRES="$(extract_requires_kw REQUIRES "$SAMPLE_CMAKE")"
    SAMPLE_PRIV_REQUIRES="$(extract_requires_kw PRIV_REQUIRES "$SAMPLE_CMAKE")"
    # Day-53: propagate EMBED_FILES / EMBED_TXTFILES.  These are how
    # stock samples (wifi_enterprise, wifi_eap_fast, ...) bake binary
    # blobs (TLS certs, EAP-FAST PAC) into the firmware image; without
    # propagation CMake would fail at parse time looking for the file
    # inside the synthetic wrap dir's main/.
    SAMPLE_EMBED_FILES="$(extract_requires_kw EMBED_FILES "$SAMPLE_CMAKE")"
    SAMPLE_EMBED_TXTFILES="$(extract_requires_kw EMBED_TXTFILES "$SAMPLE_CMAKE")"
    # Day-55 (FB-028): propagate INCLUDE_DIRS subdirs.  The original
    # sample may list `INCLUDE_DIRS "include"` or similar to expose
    # main/include/<headers>.h to its .c sources; until Day 55 the
    # wrap silently overwrote INCLUDE_DIRS with just SAMPLE_MAIN_DIR,
    # leaving any sample whose sources `#include "<subdir-header>.h"`
    # (e.g. https_request -> time_sync.h in main/include/) unable to
    # find its own headers at compile time.
    SAMPLE_INCLUDE_DIRS="$(extract_requires_kw INCLUDE_DIRS "$SAMPLE_CMAKE")"
fi

# ── Day-56 (FB-027): probe-configure the unmodified sample with `idf.py
#    reconfigure` and read project_description.json to obtain the
#    authoritative resolved list of main's REQUIRES / PRIV_REQUIRES.
#    This handles cases the textual awk extract cannot:
#      • `${var}` references in PRIV_REQUIRES (e.g. esp_http_client uses
#        `set(requires …); list(APPEND requires …); PRIV_REQUIRES ${requires}`)
#      • managed-component dependencies declared only in
#        main/idf_component.yml (e.g. icmp_echo, smtp_client)
#      • main's special transitive priv-reqs treatment that exposes a
#        dep's own priv_reqs to main's compile units (e.g. icmp_echo's
#        main pulls `console` headers transitively through
#        protocol_examples_common)
#    The probe is cached on a content hash of main/CMakeLists.txt +
#    main/idf_component.yml so repeated builds skip it.  If the probe
#    fails (e.g. stubbed idf.py in unit tests, no IDF on PATH), we fall
#    back silently to the textual extract — keeping existing behaviour
#    intact.
PROBE_DIR="${WRAP_DIR}/.probe"
PROBE_CACHE="${WRAP_DIR}/.probe_reqs.cache"
PROBE_HASH_INPUTS="${SAMPLE_CMAKE}"
[ -f "${SAMPLE_MAIN_DIR}/idf_component.yml" ] && \
    PROBE_HASH_INPUTS="${PROBE_HASH_INPUTS} ${SAMPLE_MAIN_DIR}/idf_component.yml"
PROBE_HASH=$(cat $PROBE_HASH_INPUTS 2>/dev/null | sha1sum | awk '{print $1}')

PROBED_REQUIRES=""
PROBED_PRIV_REQUIRES=""
PROBED_BUILD_COMPONENTS=""
PROBE_USED=0
if [ -f "${PROBE_CACHE}" ]; then
    CACHED_HASH="$(sed -n '1p' "${PROBE_CACHE}" 2>/dev/null || true)"
    if [ "${CACHED_HASH}" = "${PROBE_HASH}" ]; then
        PROBED_REQUIRES="$(sed -n '2p' "${PROBE_CACHE}" 2>/dev/null || true)"
        PROBED_PRIV_REQUIRES="$(sed -n '3p' "${PROBE_CACHE}" 2>/dev/null || true)"
        PROBED_BUILD_COMPONENTS="$(sed -n '4p' "${PROBE_CACHE}" 2>/dev/null || true)"
        PROBE_USED=1
    fi
fi

if [ "${PROBE_USED}" -eq 0 ] && command -v idf.py >/dev/null 2>&1; then
    echo "[build-stock-sample] probing sample deps via idf.py reconfigure …"
    rm -rf "${PROBE_DIR}"
    if idf.py -C "${SAMPLE_DIR}" -B "${PROBE_DIR}" \
            -DIDF_TARGET="${TARGET}" reconfigure >/dev/null 2>&1 \
       && [ -f "${PROBE_DIR}/project_description.json" ]; then
        PROBE_OUT="$(python3 - "${PROBE_DIR}/project_description.json" <<'PY' || true
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    m = d.get("build_component_info", {}).get("main", {})
    print(" ".join(m.get("reqs", []) or []))
    print(" ".join(m.get("priv_reqs", []) or []))
    # Day-56: if the sample's main has no explicit REQUIRES/PRIV_REQUIRES,
    # ESP-IDF treats main as implicitly requiring ALL components.  Once
    # our wrap registers a non-empty REQUIRES list (we always add
    # esp_wifi_qemu), that implicit-all behaviour is lost.  Emit the
    # full build_components list as a third line so the bash side can
    # decide whether to fall back to it.
    bc = [c for c in (d.get("build_components") or []) if c and c != "main"]
    print(" ".join(bc))
except Exception:
    pass
PY
)"
        if [ -n "${PROBE_OUT}" ]; then
            PROBED_REQUIRES="$(printf '%s\n' "${PROBE_OUT}" | sed -n '1p')"
            PROBED_PRIV_REQUIRES="$(printf '%s\n' "${PROBE_OUT}" | sed -n '2p')"
            PROBED_BUILD_COMPONENTS="$(printf '%s\n' "${PROBE_OUT}" | sed -n '3p')"
            {
                printf '%s\n' "${PROBE_HASH}"
                printf '%s\n' "${PROBED_REQUIRES}"
                printf '%s\n' "${PROBED_PRIV_REQUIRES}"
                printf '%s\n' "${PROBED_BUILD_COMPONENTS}"
            } > "${PROBE_CACHE}"
            PROBE_USED=1
        fi
    fi
    rm -rf "${PROBE_DIR}"
fi

if [ "${PROBE_USED}" -eq 1 ]; then
    # Probe wins: it knows about ${var} expansion and managed deps.
    SAMPLE_REQUIRES="${PROBED_REQUIRES}"
    SAMPLE_PRIV_REQUIRES="${PROBED_PRIV_REQUIRES}"
    # Day-56: if the original sample's main/CMakeLists.txt declares
    # neither REQUIRES nor PRIV_REQUIRES, ESP-IDF grants main implicit
    # access to every built component.  Reproduce that by widening the
    # wrap's REQUIRES to the entire build_components list from the
    # probe.  Examples: icmp_echo (uses esp_console.h via console),
    # smtp_client (uses mbedtls/platform.h via mbedtls).
    ORIG_HAS_REQUIRES=0
    if grep -qE '(^|[^A-Z_])(REQUIRES|PRIV_REQUIRES)[[:space:]]' "$SAMPLE_CMAKE" 2>/dev/null; then
        ORIG_HAS_REQUIRES=1
    fi
    if [ "${ORIG_HAS_REQUIRES}" -eq 0 ] && [ -n "${PROBED_BUILD_COMPONENTS// /}" ]; then
        SAMPLE_PRIV_REQUIRES="${SAMPLE_PRIV_REQUIRES} ${PROBED_BUILD_COMPONENTS}"
    fi
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
    # Day-55 (FB-028): re-emit INCLUDE_DIRS with absolute paths.  Every
    # entry in the original sample's INCLUDE_DIRS list is mapped to
    # `${SAMPLE_MAIN_DIR}/${entry}`, with `.` mapping to SAMPLE_MAIN_DIR
    # itself.  This preserves the original sample's main/include/
    # layout (e.g. https_request) without symlinking anything.
    # SAMPLE_MAIN_DIR is always included to keep the existing
    # behaviour for samples that omit INCLUDE_DIRS entirely (e.g.
    # icmp_echo).
    printf '    INCLUDE_DIRS "%s"\n' "${SAMPLE_MAIN_DIR}"
    if [ -n "${SAMPLE_INCLUDE_DIRS// /}" ]; then
        for d in $SAMPLE_INCLUDE_DIRS; do
            [ -z "$d" ] && continue
            case "$d" in
                .|"${SAMPLE_MAIN_DIR}") continue ;;  # already emitted
                /*) printf '        "%s"\n' "$d" ;;   # absolute, pass through
                *)  printf '        "%s"\n' "${SAMPLE_MAIN_DIR}/${d}" ;;
            esac
        done
    fi
    [ -f "${SAMPLE_MAIN_DIR}/Kconfig.projbuild" ] && \
        echo "    KCONFIG_PROJBUILD \"${SAMPLE_MAIN_DIR}/Kconfig.projbuild\""
    [ -f "${SAMPLE_MAIN_DIR}/Kconfig" ] && \
        echo "    KCONFIG \"${SAMPLE_MAIN_DIR}/Kconfig\""
    # Day-53: re-emit EMBED_FILES / EMBED_TXTFILES with absolute paths
    # back to the sample's main/.  Using absolute paths avoids the need
    # to symlink each blob into WRAP_MAIN_DIR/ and matches how ESP-IDF
    # treats EMBED_FILES (path is taken verbatim and resolved relative
    # to the component's CMakeLists.txt — but absolute paths bypass
    # that).
    if [ -n "${SAMPLE_EMBED_FILES// /}" ]; then
        echo "    EMBED_FILES"
        for f in $SAMPLE_EMBED_FILES; do
            [ -z "$f" ] && continue
            # Day-56: resolve common CMake variables relative to the
            # sample so EMBED_TXTFILES ${project_dir}/certs/foo.pem
            # (e.g. system/ota/*) lands on the correct absolute path.
            f="${f//\$\{project_dir\}/${SAMPLE_DIR}}"
            f="${f//\$\{PROJECT_DIR\}/${SAMPLE_DIR}}"
            f="${f//\$\{CMAKE_CURRENT_LIST_DIR\}/${SAMPLE_MAIN_DIR}}"
            f="${f//\$\{CMAKE_CURRENT_SOURCE_DIR\}/${SAMPLE_MAIN_DIR}}"
            case "$f" in
                /*) echo "        \"${f}\"" ;;
                *)  echo "        \"${SAMPLE_MAIN_DIR}/${f}\"" ;;
            esac
        done
    fi
    if [ -n "${SAMPLE_EMBED_TXTFILES// /}" ]; then
        echo "    EMBED_TXTFILES"
        for f in $SAMPLE_EMBED_TXTFILES; do
            [ -z "$f" ] && continue
            f="${f//\$\{project_dir\}/${SAMPLE_DIR}}"
            f="${f//\$\{PROJECT_DIR\}/${SAMPLE_DIR}}"
            f="${f//\$\{CMAKE_CURRENT_LIST_DIR\}/${SAMPLE_MAIN_DIR}}"
            f="${f//\$\{CMAKE_CURRENT_SOURCE_DIR\}/${SAMPLE_MAIN_DIR}}"
            case "$f" in
                /*) echo "        \"${f}\"" ;;
                *)  echo "        \"${SAMPLE_MAIN_DIR}/${f}\"" ;;
            esac
        done
    fi
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

# Day-54: produce a flashable merged_flash.bin alongside the build so
# downstream consumers (run-stock-qemu.sh, GAP-I/GAP-B unit tests) do
# not have to re-invoke a separate merge step.  The merge logic is
# identical to the one previously embedded in tools/run-stock-qemu.sh,
# but pre-generating it here keeps the "build artifact" abstraction
# complete: after build-stock-sample.sh exits cleanly, build_qemu/
# contains a self-contained flash image.
FLASH_IMAGE="${BUILD_DIR}/merged_flash.bin"
IDF_PYTHON="$(ls ~/.espressif/python_env/idf*_env/bin/python3 2>/dev/null | sort | tail -1 || echo python3)"
"$IDF_PYTHON" - <<'PYEOF' "$BUILD_DIR" "$FLASH_IMAGE" "$IDF_PATH" || true
import json, sys, subprocess, pathlib
build_dir = pathlib.Path(sys.argv[1])
out_img   = sys.argv[2]
idf_path  = pathlib.Path(sys.argv[3])
esptool   = idf_path / "components" / "esptool_py" / "esptool" / "esptool.py"
flasher = build_dir / "flasher_args.json"
if not flasher.is_file():
    # No flasher_args.json — likely a stubbed idf.py in tests, or the
    # underlying build was a no-op.  Skip merge silently; downstream
    # gates already check merged_flash.bin existence per-sample.
    sys.exit(0)
with open(flasher) as f:
    fargs = json.load(f)
flash_files = fargs.get("flash_files", {})
cmd = [sys.executable, str(esptool),
       "--chip", "esp32", "merge_bin",
       "--fill-flash-size", "2MB",
       "--flash_mode", "dio", "--flash_freq", "40m", "--flash_size", "2MB",
       "-o", out_img]
for offset, rel_path in sorted(flash_files.items(), key=lambda x: int(x[0], 16)):
    cmd += [offset, str(build_dir / rel_path)]
subprocess.check_call(cmd, stdout=subprocess.DEVNULL)
PYEOF

echo "  Flash image : ${BUILD_DIR}/merged_flash.bin"
echo "  Boot in QEMU: set ESP_WIFI_CTRL_SOCKET and ESP_WIFI_PKT_SOCKET, then:"
echo "    bash ${QEMU_WIFI_DIR}/tools/run-stock-qemu.sh ${BUILD_DIR}"
