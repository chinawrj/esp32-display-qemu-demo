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
#   SUMMARY_FILE   TSV summary path (default: $LOG_DIR/summary.tsv)
#   QEMU_BIN       Optional qemu-system-xtensa override passed through to runner

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DURATION="${1:-60}"
LOG_DIR="${LOG_DIR:-/tmp/qemu-wifi-smoke}"
SUMMARY_FILE="${SUMMARY_FILE:-${LOG_DIR}/summary.tsv}"

if [ -z "${IDF_PATH:-}" ] && [ -f "${HOME}/esp-idf/export.sh" ]; then
    # shellcheck disable=SC1091
    source "${HOME}/esp-idf/export.sh" >/dev/null 2>&1
fi

if [ -z "${IDF_PATH:-}" ]; then
    echo "ERROR: IDF_PATH is not set and ${HOME}/esp-idf/export.sh was not found" >&2
    exit 2
fi

mkdir -p "$LOG_DIR"
printf "sample\tprofile\tbuild\trun\tbuild_log\trun_log\tserial_log\n" >"$SUMMARY_FILE"

SAMPLES=(
    "station|${IDF_PATH}/examples/wifi/getting_started/station|station|run"
    "scan|${IDF_PATH}/examples/wifi/scan|scan|run"
    "softAP|${IDF_PATH}/examples/wifi/getting_started/softAP|softap|run"
    # Day-50: fast_scan promoted from build-only to runtime.  The sample's
    # WIFI_FAST_SCAN method races esp_wifi_connect() (called from the
    # STA_START handler) against the firmware shim's housekeeping
    # startup-scan; the resulting CMD_SCAN-after-CMD_CONNECT order used
    # to leave scan_only=true on the device, short-circuiting
    # SCAN_RESULTS to SCAN_DONE and skipping ADD_NETWORK / SELECT_NETWORK
    # / GOT_IP.  Day-50 fixes both sides (post STA_START AFTER the
    # MMIO write, plus a device-side guard that drops a redundant
    # CMD_SCAN while a connect flow is in-flight).  The sample's
    # default SSID ("myssid") is overridden via the sdkconfig overlay
    # below to point at the mock supplicant's QEMU_TEST AP — the only
    # change a stock sample needs is the sdkconfig channel, no source
    # diff.
    "fast_scan|${IDF_PATH}/examples/wifi/fast_scan|station|run|${PROJECT_DIR}/tools/sample-overlays/fast_scan.sdkconfig"
    # Day-51: power_save promoted from build-only (Day 48) to runtime,
    # mirroring the Day-50 fast_scan playbook.  The sample's only
    # runtime blocker was the Kconfig-default SSID ("myssid"), which we
    # now override via the EXTRA_SDKCONFIG_DEFAULTS overlay channel to
    # point at the mock supplicant's QEMU_TEST AP.  EXAMPLE_GET_AP_INFO_
    # FROM_STDIN defaults to `n` (no console input needed) and Phase C
    # (esp_wifi_set_ps + esp_wifi_set_inactive_time round-trip) is
    # already implemented, so this gives us end-to-end runtime proof
    # that the Phase-C API surface is wide enough for the stock
    # esp_wifi.h consumer.  Source diff is still zero — only this
    # overlay file deviates from a real-hardware build.
    "power_save|${IDF_PATH}/examples/wifi/power_save|station|run|${PROJECT_DIR}/tools/sample-overlays/power_save.sdkconfig"
    # Day-49: softap_sta is the only stock wifi sample that exercises
    # APSTA mode (STA + SoftAP simultaneously) in a single binary.
    # Build success proves Phase A (connection AP record) + Phase B
    # (channel / auth / cipher) + Phase C (power-save) + Phase D-1/D-2
    # (real AP station table + IPASSIGNED) all link together cleanly
    # for the same firmware image. Runtime is gated on a configured
    # upstream STA SSID and on lwIP NAPT, neither of which the smoke
    # gate provisions.
    "softap_sta|${IDF_PATH}/examples/wifi/softap_sta|softap|build_only"
    # Day-49: roaming_app exercises the same Phase A surface as
    # getting_started/station but on top of the IDF roaming library
    # (esp_wifi_set_rssi_threshold, BSS Transition Management hooks),
    # which our shim provides as link-clean stubs. Build success here
    # is the cheapest proof that station-mode firmware can pull in the
    # roaming subsystem without unresolved symbols. Runtime would need
    # an 802.11k/v-capable AP cluster which neither the smoke gate nor
    # any single mock_wpa_supplicant can stand up today.
    "roaming_app|${IDF_PATH}/examples/wifi/roaming/roaming_app|station|build_only"
    # Day-52: a wide build-only sweep of the remaining stock IDF Wi-Fi
    # samples.  Each one builds clean against the QEMU shim today with
    # zero source diff, proving the link-time API surface is already
    # complete enough for these flagship Wi-Fi feature demos.  Runtime
    # promotion for each will need its own protocol-level mock (WPS-PBC
    # exchange, ESPTOUCH air-interface, FTM 11mc handshake, ESP-NOW
    # peer table, AP that advertises HE iTWT, WPS Registrar role) which
    # is multi-day work each.  Build coverage in the meantime is the
    # single strongest North-Star check: any future shim regression that
    # silently drops a public symbol will surface here as a link error.
    "wps|${IDF_PATH}/examples/wifi/wps|station|build_only"
    "smart_config|${IDF_PATH}/examples/wifi/smart_config|station|build_only"
    "ftm|${IDF_PATH}/examples/wifi/ftm|station|build_only"
    "espnow|${IDF_PATH}/examples/wifi/espnow|station|build_only"
    "wps_softap_registrar|${IDF_PATH}/examples/wifi/wps_softap_registrar|softap|build_only"
    # Day-52: itwt only links after the new HE/iTWT stubs added to
    # components/esp_wifi_qemu/esp_wifi_extras.c (esp_wifi_sta_itwt_setup
    # / esp_wifi_sta_twt_config returning ESP_ERR_NOT_SUPPORTED).  The
    # esp32 we emulate is not an 802.11ax part, so on real silicon
    # these symbols only exist in HE-capable targets (C5/C6 etc.); the
    # stub keeps the drop-in contract for esp32 builds.
    "itwt|${IDF_PATH}/examples/wifi/itwt|station|build_only"
    # Day-53: wifi_eap_fast and wifi_enterprise embed TLS material via
    # EMBED_TXTFILES.  The wrapper script gained EMBED_FILES /
    # EMBED_TXTFILES propagation today (Day 53), unblocking these final
    # two stock Wi-Fi samples and bringing build-only coverage to 15/15.
    # Runtime promotion would need a real 802.1X / EAP-FAST RADIUS
    # back-end, which the mock_wpa_supplicant does not provide.
    "wifi_eap_fast|${IDF_PATH}/examples/wifi/wifi_eap_fast|station|build_only"
    "wifi_enterprise|${IDF_PATH}/examples/wifi/wifi_enterprise|station|build_only"
    # Day-54: extend drop-in build-only coverage beyond examples/wifi/**.
    # Every sample below uses example_connect() (protocol_examples_common)
    # to bring up a Wi-Fi station via the QEMU shim and then opens
    # UDP/TCP sockets or HTTP/SNTP clients on top of the lwIP stack.
    # Build success here is the strongest evidence that the lwIP-over
    # QEMU-Wi-Fi data plane links cleanly for every common socket
    # family with zero source diff in the sample tree.  Day-54 also
    # fixed the wrap-script awk extractor (FB-026): on a continuation
    # line containing both a component keyword and a close-paren, the
    # extractor now stops at the keyword rather than at the paren so
    # multi-line idf_component_register clauses with CMake-variable
    # PRIV_REQUIRES (e.g. udp_client) extract correctly.
    # Day-60: tcp_client and udp_client are promoted from build_only to
    # full runtime — the QEMU Wi-Fi data plane (GAP-I, Day-27) is good
    # enough that the firmware dials 10.0.2.2:3333 (set in
    # sdkconfig.qemu.wifi.defaults), the wifi_packet_relay NATs it to
    # 127.0.0.1:3333, and our tools/{tcp,udp}_echo_server.py reply.
    # Profile-name `tcp_client` / `udp_client` auto-starts the matching
    # echo server inside run-stock-qemu.sh (Day-60), so no extra env
    # plumbing is needed in the SAMPLES entry.
    "tcp_client|${IDF_PATH}/examples/protocols/sockets/tcp_client|tcp_client|run"
    "tcp_server|${IDF_PATH}/examples/protocols/sockets/tcp_server|station|build_only"
    "udp_client|${IDF_PATH}/examples/protocols/sockets/udp_client|udp_client|run"
    "udp_server|${IDF_PATH}/examples/protocols/sockets/udp_server|station|build_only"
    "http_request|${IDF_PATH}/examples/protocols/http_request|station|build_only"
    "sntp|${IDF_PATH}/examples/protocols/sntp|station|build_only"
    # Day-55: continue extending into examples/protocols/**.  mqtt/tcp
    # exercises the esp_mqtt_client API over plain TCP and links clean
    # against the QEMU Wi-Fi shim with zero source diff.  https_request
    # is added once Day-55's FB-028 (INCLUDE_DIRS subdir propagation)
    # fix lands — the sample lists INCLUDE_DIRS "include" in its main/
    # CMakeLists.txt; until Day 55 the wrapper-project generator
    # silently dropped any non-"." entry, leaving main/include/*.h
    # unreachable from main/*.c at compile time.
    "mqtt_tcp|${IDF_PATH}/examples/protocols/mqtt/tcp|station|build_only"
    "https_request|${IDF_PATH}/examples/protocols/https_request|station|build_only"
    # Day-56 (FB-027): probe-configure helper runs `idf.py reconfigure`
    # on the unmodified sample and reads project_description.json to
    # obtain main's authoritative resolved REQUIRES / PRIV_REQUIRES.
    # This unlocks samples whose main/CMakeLists.txt uses ${var}
    # expansion (esp_http_client), declares managed deps only in
    # idf_component.yml (icmp_echo, smtp_client), or omits REQUIRES
    # entirely and relies on ESP-IDF's implicit-all-components rule
    # for main (the wrap now widens REQUIRES to the full probed
    # build_components list in that case).  Day-56 also adds CMake
    # variable substitution for ${project_dir}/${PROJECT_DIR} in
    # EMBED_FILES/EMBED_TXTFILES and symlinks sample-root data dirs
    # (server_certs/, etc.) into the wrap so sdkconfig keys that
    # resolve relative to PROJECT_DIR (e.g. MBEDTLS_CUSTOM_CERTIFICATE_
    # BUNDLE_PATH) land on the correct file.
    "esp_http_client|${IDF_PATH}/examples/protocols/esp_http_client|station|build_only"
    "icmp_echo|${IDF_PATH}/examples/protocols/icmp_echo|station|build_only"
    "smtp_client|${IDF_PATH}/examples/protocols/smtp_client|station|build_only"
    "https_server_simple|${IDF_PATH}/examples/protocols/https_server/simple|station|build_only"
    "https_server_wss|${IDF_PATH}/examples/protocols/https_server/wss_server|station|build_only"
    "modbus_mb_master|${IDF_PATH}/examples/protocols/modbus/serial/mb_master|station|build_only"
    "ota_advanced_https|${IDF_PATH}/examples/system/ota/advanced_https_ota|station|build_only"
    "ota_native|${IDF_PATH}/examples/system/ota/native_ota_example|station|build_only"
    "ota_simple|${IDF_PATH}/examples/system/ota/simple_ota_example|station|build_only"
    # Day-57 FB-029 — project-level target_add_binary_data propagation + cert-bundle data dir.
    "mqtt_ssl|${IDF_PATH}/examples/protocols/mqtt/ssl|station|build_only"
    "mqtt_wss|${IDF_PATH}/examples/protocols/mqtt/wss|station|build_only"
    "mqtt_ssl_mutual_auth|${IDF_PATH}/examples/protocols/mqtt/ssl_mutual_auth|station|build_only"
    "https_x509_bundle|${IDF_PATH}/examples/protocols/https_x509_bundle|station|build_only"
    # Day-58 FB-030 (sample-root components/ via EXTRA_COMPONENT_DIRS) +
    # FB-031 (generalized post-project() CMakeLists propagation w/ var subst).
    "mqtt_custom_outbox|${IDF_PATH}/examples/protocols/mqtt/custom_outbox|station|build_only"
    "http_server_captive_portal|${IDF_PATH}/examples/protocols/http_server/captive_portal|station|build_only"
    "console_advanced|${IDF_PATH}/examples/system/console/advanced|station|build_only"
    # Day-58 — additional drop-in coverage unlocked by the generalized wrap.
    "console_basic|${IDF_PATH}/examples/system/console/basic|station|build_only"
    "esp_local_ctrl|${IDF_PATH}/examples/protocols/esp_local_ctrl|station|build_only"
    "l2tap|${IDF_PATH}/examples/protocols/l2tap|station|build_only"
    "static_ip|${IDF_PATH}/examples/protocols/static_ip|station|build_only"
    "https_mbedtls|${IDF_PATH}/examples/protocols/https_mbedtls|station|build_only"
    "dns_over_https|${IDF_PATH}/examples/protocols/dns_over_https|station|build_only"
    "mqtt_ssl_psk|${IDF_PATH}/examples/protocols/mqtt/ssl_psk|station|build_only"
    "mqtt_ws|${IDF_PATH}/examples/protocols/mqtt/ws|station|build_only"
    "mqtt5|${IDF_PATH}/examples/protocols/mqtt5|station|build_only"
    "http_server_simple|${IDF_PATH}/examples/protocols/http_server/simple|station|build_only"
    "http_server_restful|${IDF_PATH}/examples/protocols/http_server/restful_server|station|build_only"
    "http_server_ws_echo|${IDF_PATH}/examples/protocols/http_server/ws_echo_server|station|build_only"
    "http_server_persistent|${IDF_PATH}/examples/protocols/http_server/persistent_sockets|station|build_only"
    "http_server_async|${IDF_PATH}/examples/protocols/http_server/async_handlers|station|build_only"
    "http_server_file_serving|${IDF_PATH}/examples/protocols/http_server/file_serving|station|build_only"
    "sockets_non_blocking|${IDF_PATH}/examples/protocols/sockets/non_blocking|station|build_only"
    "sockets_icmpv6_ping|${IDF_PATH}/examples/protocols/sockets/icmpv6_ping|station|build_only"
    "sockets_tcp_transport|${IDF_PATH}/examples/protocols/sockets/tcp_transport_client|station|build_only"
    "sockets_udp_multicast|${IDF_PATH}/examples/protocols/sockets/udp_multicast|station|build_only"
    "sockets_tcp_multi_net|${IDF_PATH}/examples/protocols/sockets/tcp_client_multi_net|station|build_only"
    "modbus_tcp_master|${IDF_PATH}/examples/protocols/modbus/tcp/mb_tcp_master|station|build_only"
    "modbus_tcp_slave|${IDF_PATH}/examples/protocols/modbus/tcp/mb_tcp_slave|station|build_only"
    "modbus_serial_slave|${IDF_PATH}/examples/protocols/modbus/serial/mb_slave|station|build_only"
    "wifi_iperf|${IDF_PATH}/examples/wifi/iperf|station|build_only"
    "wifi_dpp_enrollee|${IDF_PATH}/examples/wifi/wifi_easy_connect/dpp-enrollee|station|build_only"
    "ota_otatool|${IDF_PATH}/examples/system/ota/otatool|station|build_only"
    # Day-59 (FB-032) — gate protocol_examples_common injection on actual
    # source-level use so that samples pulling `ethernet_init` via
    # idf_component.yml stop colliding on duplicated EXAMPLE_USE_* Kconfig
    # symbols.  Unblocks the entire examples/network/* tree (modulo
    # sta2eth which still needs the tinyusb hardware-only stack).
    "net_simple_sniffer|${IDF_PATH}/examples/network/simple_sniffer|station|build_only"
    "net_bridge|${IDF_PATH}/examples/network/bridge|station|build_only"
    "net_vlan_support|${IDF_PATH}/examples/network/vlan_support|station|build_only"
    "net_eth2ap|${IDF_PATH}/examples/network/eth2ap|station|build_only"
    # Day-59 — additional drop-in coverage that just needed to be tried
    "http_server_advanced_tests|${IDF_PATH}/examples/protocols/http_server/advanced_tests|station|build_only"
    "wifi_roaming_11kvr|${IDF_PATH}/examples/wifi/roaming/roaming_11kvr|station|build_only"
    "wifi_aware_nan_console|${IDF_PATH}/examples/wifi/wifi_aware/nan_console|station|build_only"
    "wifi_aware_nan_publisher|${IDF_PATH}/examples/wifi/wifi_aware/nan_publisher|station|build_only"
    "wifi_aware_nan_subscriber|${IDF_PATH}/examples/wifi/wifi_aware/nan_subscriber|station|build_only"
    # Day-61 — survey examples/system/* for drop-in build_only candidates.
    # Sixteen non-console system samples link clean against the QEMU
    # Wi-Fi shim + lwIP stack with zero source diff, proving the wrap
    # script is general-purpose enough for ESP-IDF's system-services
    # examples (timers, events, threads, IPC, low-power, efuse, perf
    # counters).  Skipped: task_watchdog (needs esp_task_wdt_* symbols
    # that the QEMU build elides), ipc/ipc_isr (architecture-specific
    # ASM dependency on get_ps_other_cpu / extended_ipc_isr_asm).
    "sys_base_mac_address|${IDF_PATH}/examples/system/base_mac_address|station|build_only"
    "sys_esp_timer|${IDF_PATH}/examples/system/esp_timer|station|build_only"
    "sys_eventfd|${IDF_PATH}/examples/system/eventfd|station|build_only"
    "sys_select|${IDF_PATH}/examples/system/select|station|build_only"
    "sys_startup_time|${IDF_PATH}/examples/system/startup_time|station|build_only"
    "sys_light_sleep|${IDF_PATH}/examples/system/light_sleep|station|build_only"
    "sys_rt_mqueue|${IDF_PATH}/examples/system/rt_mqueue|station|build_only"
    "sys_deep_sleep|${IDF_PATH}/examples/system/deep_sleep|station|build_only"
    "sys_efuse|${IDF_PATH}/examples/system/efuse|station|build_only"
    "sys_perfmon|${IDF_PATH}/examples/system/perfmon|station|build_only"
    "sys_pthread|${IDF_PATH}/examples/system/pthread|station|build_only"
    "sys_freertos_real_time_stats|${IDF_PATH}/examples/system/freertos/real_time_stats|station|build_only"
    "sys_heap_task_tracking_basic|${IDF_PATH}/examples/system/heap_task_tracking/basic|station|build_only"
    "sys_heap_task_tracking_advanced|${IDF_PATH}/examples/system/heap_task_tracking/advanced|station|build_only"
    "sys_esp_event_default_loop|${IDF_PATH}/examples/system/esp_event/default_event_loop|station|build_only"
    "sys_esp_event_user_loops|${IDF_PATH}/examples/system/esp_event/user_event_loops|station|build_only"
)

PASS=0
FAIL=0

run_one() {
    local name="$1"
    local sample_dir="$2"
    local profile="$3"
    local mode="${4:-run}"           # run | build_only
    local overlay="${5:-}"           # optional EXTRA_SDKCONFIG_DEFAULTS path
    local build_dir="${sample_dir}/build_qemu"
    local build_log="${LOG_DIR}/${name}-build.log"
    local run_log="${LOG_DIR}/${name}-run.log"
    local serial_log="${LOG_DIR}/${name}-serial.log"
    local build_status="fail"
    local run_status="skipped"

    echo "[basic-wifi-smoke] === ${name}: build ==="
    if EXTRA_SDKCONFIG_DEFAULTS="$overlay" \
        bash "${PROJECT_DIR}/tools/build-stock-sample.sh" "$sample_dir" >"$build_log" 2>&1; then
        echo "[basic-wifi-smoke] ${name}: build ok"
        build_status="ok"
    else
        echo "[basic-wifi-smoke] ${name}: build failed (log: ${build_log})"
        FAIL=$((FAIL + 1))
        printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
            "$name" "$profile" "$build_status" "$run_status" \
            "$build_log" "$run_log" "$serial_log" >>"$SUMMARY_FILE"
        return
    fi

    if [ "$mode" = "build_only" ]; then
        echo "[basic-wifi-smoke] ${name}: run skipped (build_only)"
        run_status="build_only"
        PASS=$((PASS + 1))
        printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
            "$name" "$profile" "$build_status" "$run_status" \
            "$build_log" "$run_log" "$serial_log" >>"$SUMMARY_FILE"
        return
    fi

    echo "[basic-wifi-smoke] === ${name}: run (${profile}) ==="
    if VERIFY_PROFILE="$profile" LOG_FILE="$serial_log" \
        bash "${PROJECT_DIR}/tools/run-stock-qemu.sh" "$build_dir" "$DURATION" >"$run_log" 2>&1; then
        echo "[basic-wifi-smoke] ${name}: run ok"
        run_status="ok"
        PASS=$((PASS + 1))
    else
        echo "[basic-wifi-smoke] ${name}: run failed (log: ${run_log})"
        run_status="fail"
        FAIL=$((FAIL + 1))
    fi

    printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
        "$name" "$profile" "$build_status" "$run_status" \
        "$build_log" "$run_log" "$serial_log" >>"$SUMMARY_FILE"
}

echo "[basic-wifi-smoke] IDF_PATH=${IDF_PATH}"
echo "[basic-wifi-smoke] LOG_DIR=${LOG_DIR}"
echo "[basic-wifi-smoke] SUMMARY_FILE=${SUMMARY_FILE}"
echo "[basic-wifi-smoke] DURATION=${DURATION}"

for entry in "${SAMPLES[@]}"; do
    IFS='|' read -r name sample_dir profile mode overlay <<<"$entry"
    run_one "$name" "$sample_dir" "$profile" "${mode:-run}" "${overlay:-}"
done

echo ""
echo "[basic-wifi-smoke] Summary: ${PASS} passed, ${FAIL} failed"
echo "[basic-wifi-smoke] Logs: ${LOG_DIR}"
echo "[basic-wifi-smoke] Summary file: ${SUMMARY_FILE}"

[ "$FAIL" -eq 0 ]
