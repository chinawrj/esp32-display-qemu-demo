# qemu-wifi-overlay.cmake
#
# One-line CMake include that makes any ESP-IDF Wi-Fi project use the
# QEMU virtual Wi-Fi component instead of the real esp_wifi hardware driver.
#
# ── HOW TO USE ────────────────────────────────────────────────────────────
# Option A – include in the project's CMakeLists.txt (only CMakeLists.txt
#            is allowed to differ from upstream per the PRIMARY TARGET rules):
#
#   # In <sample>/CMakeLists.txt, before cmake_minimum_required():
#   set(QEMU_WIFI_DIR "$ENV{QEMU_WIFI_OVERLAY_DIR}")   # or hard-code the path
#   if(QEMU_WIFI_DIR)
#     include("${QEMU_WIFI_DIR}/tools/qemu-wifi-overlay.cmake")
#   endif()
#
# Option B – pass via idf.py command line (zero changes to sample files):
#
#   export QEMU_WIFI_OVERLAY_DIR=/path/to/esp32-display-qemu-demo
#   idf.py \
#     -DEXTRA_COMPONENT_DIRS="${QEMU_WIFI_OVERLAY_DIR}/components" \
#     -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;${QEMU_WIFI_OVERLAY_DIR}/sdkconfig.qemu.wifi.defaults" \
#     build
#
# Option C – build via tools/build-stock-sample.sh (zero file edits):
#
#   bash /path/to/esp32-display-qemu-demo/tools/build-stock-sample.sh \
#        /path/to/idf/examples/wifi/getting_started/station
#
# ── WHAT THIS DOES ────────────────────────────────────────────────────────
# 1. Appends our components/ directory to EXTRA_COMPONENT_DIRS so the
#    esp_wifi_qemu component is visible to the ESP-IDF build system.
# 2. Appends sdkconfig.qemu.wifi.defaults to SDKCONFIG_DEFAULTS so
#    CONFIG_ESP_WIFI_QEMU=y is set without touching the sample's sdkconfig.
#
# The overlay component registers itself with --allow-multiple-definition
# in its CMakeLists.txt, so its esp_wifi_* symbols silently take priority
# over libnet80211 without any REQUIRES / PRIV_REQUIRES changes needed in
# the sample's component.
# ─────────────────────────────────────────────────────────────────────────

# Resolve the root of the esp32-display-qemu-demo repository relative to
# this file so the cmake file can be included from any directory.
get_filename_component(_QEMU_WIFI_ROOT "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)

# 1. Add our components directory to the search path.
list(APPEND EXTRA_COMPONENT_DIRS "${_QEMU_WIFI_ROOT}/components")
message(STATUS "[qemu-wifi-overlay] Added component dir: ${_QEMU_WIFI_ROOT}/components")

# 2. Append QEMU Wi-Fi sdkconfig defaults (non-destructive — sample's own
#    sdkconfig.defaults is listed first and takes precedence for any key
#    it already defines).
if(DEFINED SDKCONFIG_DEFAULTS)
    list(APPEND SDKCONFIG_DEFAULTS "${_QEMU_WIFI_ROOT}/sdkconfig.qemu.wifi.defaults")
else()
    set(SDKCONFIG_DEFAULTS "sdkconfig.defaults;${_QEMU_WIFI_ROOT}/sdkconfig.qemu.wifi.defaults")
endif()
message(STATUS "[qemu-wifi-overlay] SDKCONFIG_DEFAULTS: ${SDKCONFIG_DEFAULTS}")
