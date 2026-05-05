# components/esp_wifi_qemu/project_include.cmake
#
# This file is automatically included by ESP-IDF's build system for every
# project that has esp_wifi_qemu in its component search path.
#
# When CONFIG_ESP_WIFI_QEMU=y, we inject esp_wifi_qemu into
# COMPONENT_REQUIRES_COMMON so it is linked into every application without
# any explicit REQUIRES in the project's CMakeLists.txt.  This is the
# mechanism that allows stock ESP-IDF Wi-Fi samples to use our QEMU shim
# with ZERO source-file changes (only EXTRA_COMPONENT_DIRS + sdkconfig).
#
# The companion --allow-multiple-definition linker flag (set in
# CMakeLists.txt as an INTERFACE option of the esp_wifi_qemu target) then
# propagates to all consumers, letting the linker prefer our symbols over
# the real libnet80211 implementations.

# This component is ONLY added to EXTRA_COMPONENT_DIRS when building for QEMU.
# We use cmake_language(DEFER) to inject ourselves as a link dependency AFTER
# all component targets and the ELF target have been created.  This avoids
# the timing issue where __COMPONENT_REQUIRES_COMMON is read before
# project_include.cmake is processed.
# esp_wifi_qemu/project_include.cmake
#
# This file is processed by the ESP-IDF build system for projects that have
# esp_wifi_qemu in their component list (i.e., projects built via
# tools/build-stock-sample.sh which generates a wrapper main/CMakeLists.txt
# that explicitly REQUIRES esp_wifi_qemu).
#
# Currently this file is intentionally minimal — the component injection is
# handled by the generated wrapper CMakeLists.txt (REQUIRES esp_wifi_qemu).
# The --allow-multiple-definition linker flag is propagated from the component
# CMakeLists.txt via INTERFACE target_link_options.

