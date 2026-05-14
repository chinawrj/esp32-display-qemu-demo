# QEMU Wi-Fi Stock ESP-IDF Samples

Status: **Day 32 documentation freeze** for the basic STA/SCAN/AP release.

This guide covers the stock ESP-IDF Wi-Fi examples that are part of the formal
six-day release target. The goal is drop-in compatibility: ESP-IDF sample
`.c` and `.h` files stay unchanged. The helper scripts only add the QEMU Wi-Fi
component through generated wrapper CMake files and QEMU-specific sdkconfig
defaults.

## Supported Samples

| ESP-IDF sample | Verify profile | Expected runtime evidence |
|----------------|----------------|---------------------------|
| `examples/wifi/getting_started/station/` | `station` | `got ip:10.0.2.15` |
| `examples/wifi/scan/` | `scan` | `Total APs scanned = 1` and `SSID QEMU_TEST` |
| `examples/wifi/getting_started/softAP/` | `softap` | `wifi_init_softap finished` |
| `examples/wifi/fast_scan/` | `station` | `got ip:10.0.2.15` (Day 50 — see below) |
| `examples/wifi/power_save/` | `station` | `got ip:10.0.2.15` (Day 51 — see below) |
| `examples/protocols/sockets/tcp_client/` | `tcp_client` | `Received N bytes` (firmware dials `10.0.2.2:3333` → host echo — Day 60) |
| `examples/protocols/sockets/udp_client/` | `udp_client` | `Received N bytes` (firmware dials `10.0.2.2:3333` → host echo — Day 60) |

### Build-only coverage (Day 48)

The release smoke gate also builds the following samples to prove that the
QEMU Wi-Fi shim implements a wide enough subset of `esp_wifi.h` for them to
link with **zero source modification** (only `CMakeLists.txt` +
`sdkconfig.defaults` differ).  Their runtime is not exercised by the gate
because it depends on knobs the gate does not provision (sample-specific
console UART input).

| ESP-IDF sample | What it proves builds clean |
|----------------|-----------------------------|
| `examples/wifi/softap_sta/` | Phase A + B + C + D-1 + D-2 link together for an APSTA-mode binary (only stock sample that drives both `WIFI_MODE_AP` and `WIFI_MODE_STA` simultaneously) — Day 49 |
| `examples/wifi/roaming/roaming_app/` | Phase A + IDF roaming-library glue (BSS Transition Management, RSSI threshold hooks) link clean on top of station mode — Day 49 |
| `examples/wifi/wps/` | WPS (PBC) state-machine link surface (`esp_wifi_wps_enable/start/disable`) — Day 52 |
| `examples/wifi/smart_config/` | ESPTOUCH provisioning entry-points (`esp_smartconfig_*`) — Day 52 |
| `examples/wifi/ftm/` | FTM (Fine Timing Measurement) initiator/responder API (`esp_wifi_ftm_*`) — Day 52 |
| `examples/wifi/espnow/` | ESP-NOW transport API (`esp_now_*`) link clean against the shim — Day 52 |
| `examples/wifi/wps_softap_registrar/` | WPS Registrar role on top of SoftAP — Day 52 |
| `examples/wifi/itwt/` | 802.11ax iTWT / TWT API (`esp_wifi_sta_itwt_setup`, `esp_wifi_sta_twt_config`) link clean as ESP_ERR_NOT_SUPPORTED stubs on the non-HE esp32 target — Day 52 |
| `examples/wifi/wifi_eap_fast/` | EAP-FAST 802.1X enterprise auth — link surface from `esp_wifi_sta_wpa2_ent_*` family + TLS material (`ca.pem`, `pac_file.pac`) embedded via `EMBED_TXTFILES` — Day 53 |
| `examples/wifi/wifi_enterprise/` | PEAP/TTLS 802.1X enterprise auth — link surface + TLS material (`ca.pem`, `client.crt`, `client.key`) embedded via `EMBED_TXTFILES` — Day 53 |
| `examples/protocols/sockets/tcp_client/` | lwIP-over-Wi-Fi BSD TCP-client socket API (`socket`, `connect`, `send`, `recv`) links clean on top of `example_connect()` — Day 54 (promoted to runtime Day 60) |
| `examples/protocols/sockets/tcp_server/` | BSD TCP-server socket API (`bind`, `listen`, `accept`) links clean on top of `example_connect()` — Day 54 |
| `examples/protocols/sockets/udp_client/` | BSD UDP-client socket API (`sendto`) links clean — Day 54 (promoted to runtime Day 60) |
| `examples/protocols/sockets/udp_server/` | BSD UDP-server socket API (`recvfrom`) links clean — Day 54 |
| `examples/protocols/http_request/` | lwIP DNS resolver + raw HTTP request over a BSD socket — Day 54 |
| `examples/protocols/sntp/` | LwIP SNTP client over Wi-Fi — Day 54 |
| `examples/protocols/mqtt/tcp/` | esp_mqtt_client public API end-to-end over plain TCP — Day 55 |
| `examples/protocols/https_request/` | TLS-secured HTTP GET with embedded CA / server certs — Day 55 (needs FB-028 INCLUDE_DIRS subdir propagation fix) |
| `examples/protocols/esp_http_client/` | esp_http_client API over plain HTTP + TLS — Day 56 (FB-027 probe-configure) |
| `examples/protocols/icmp_echo/` | RFC 792 ICMP echo client over Wi-Fi — Day 56 (implicit-all REQUIRES via probe build_components) |
| `examples/protocols/smtp_client/` | SMTP+TLS client with mbedtls — Day 56 (implicit-all + probe) |
| `examples/protocols/https_server/simple/` | esp_https_server TLS endpoint — Day 56 |
| `examples/protocols/https_server/wss_server/` | esp_https_server + WebSocket over TLS — Day 56 |
| `examples/protocols/modbus/serial/mb_master/` | Modbus master over UART — Day 56 |
| `examples/system/ota/simple_ota_example/` | OTA upgrade with embedded CA cert and custom mbedtls cert bundle — Day 56 (needs `${project_dir}` rewrite + `server_certs/` symlinking) |
| `examples/system/ota/advanced_https_ota/` | esp_https_ota with chunked download + image rollback — Day 56 |
| `examples/system/ota/native_ota_example/` | esp_ota_* native API over HTTPS — Day 56 |
| `examples/protocols/mqtt/ssl/` | esp_mqtt_client over TLS with project-level `target_add_binary_data` cert — Day 57 (FB-029) |
| `examples/protocols/mqtt/wss/` | esp_mqtt_client over WebSocket+TLS with project-level cert — Day 57 (FB-029) |
| `examples/protocols/mqtt/ssl_mutual_auth/` | esp_mqtt_client with mutual TLS (client cert+key + server cert) — Day 57 (FB-029, multi-asset `target_add_binary_data`) |
| `examples/protocols/https_x509_bundle/` | Custom mbedtls certificate bundle resolved via sdkconfig `CONFIG_MBEDTLS_CUSTOM_CERTIFICATE_BUNDLE_PATH="certs"` — Day 57 (via Day-56 sample-root data-dir symlinking) |
| `examples/protocols/mqtt/custom_outbox/` | C++ override of the mqtt component's outbox via project-level `idf_component_get_property` + `target_sources` — Day 58 (FB-031) |
| `examples/protocols/http_server/captive_portal/` | esp_http_server captive-portal with sample-local `dns_server` component — Day 58 (FB-030 `EXTRA_COMPONENT_DIRS`) |
| `examples/system/console/advanced/` | esp_console REPL with sample-local `cmd_system`/`cmd_nvs`/`cmd_wifi` components — Day 58 (FB-030) |
| `examples/system/console/basic/` | esp_console minimal REPL — Day 58 |
| `examples/protocols/esp_local_ctrl/` | esp_local_ctrl provisioning protocol over Wi-Fi — Day 58 |
| `examples/protocols/l2tap/` | L2 raw-ethernet socket tap — Day 58 |
| `examples/protocols/static_ip/` | Static IP configuration via `esp_netif_set_ip_info` — Day 58 |
| `examples/protocols/https_mbedtls/` | Raw mbedtls TLS handshake + GET — Day 58 |
| `examples/protocols/dns_over_https/` | DNS-over-HTTPS resolver — Day 58 |
| `examples/protocols/mqtt/ssl_psk/` | esp_mqtt_client over TLS-PSK — Day 58 |
| `examples/protocols/mqtt/ws/` | esp_mqtt_client over WebSocket (plain) — Day 58 |
| `examples/protocols/mqtt5/` | esp_mqtt5 (MQTT v5.0) client — Day 58 |
| `examples/protocols/http_server/simple/` | esp_http_server simple GET/POST endpoints — Day 58 |
| `examples/protocols/http_server/restful_server/` | esp_http_server RESTful API with SPIFFS frontend — Day 58 |
| `examples/protocols/http_server/ws_echo_server/` | esp_http_server WebSocket echo — Day 58 |
| `examples/protocols/http_server/persistent_sockets/` | esp_http_server per-socket session context — Day 58 |
| `examples/protocols/http_server/async_handlers/` | esp_http_server async request handlers — Day 58 |
| `examples/protocols/http_server/file_serving/` | esp_http_server static file serving from SPIFFS — Day 58 |
| `examples/protocols/sockets/non_blocking/` | BSD sockets with `fcntl(O_NONBLOCK)` + `select` — Day 58 |
| `examples/protocols/sockets/icmpv6_ping/` | ICMPv6 ping client over Wi-Fi — Day 58 |
| `examples/protocols/sockets/tcp_transport_client/` | esp-tls/esp_transport client — Day 58 |
| `examples/protocols/sockets/udp_multicast/` | IGMP join + UDP multicast send/recv — Day 58 |
| `examples/protocols/sockets/tcp_client_multi_net/` | TCP client with multi-netif routing — Day 58 |
| `examples/protocols/modbus/tcp/mb_tcp_master/` | Modbus TCP master — Day 58 |
| `examples/protocols/modbus/tcp/mb_tcp_slave/` | Modbus TCP slave — Day 58 |
| `examples/protocols/modbus/serial/mb_slave/` | Modbus serial slave — Day 58 |
| `examples/wifi/iperf/` | iperf2/3-compatible throughput tool — Day 58 |
| `examples/wifi/wifi_easy_connect/dpp-enrollee/` | Wi-Fi Easy Connect (DPP) enrollee — Day 58 |
| `examples/system/ota/otatool/` | otatool partition manipulation example — Day 58 |
| `examples/network/simple_sniffer/` | Wi-Fi promisc/Ethernet sniffer with pcap export — Day 59 |
| `examples/network/bridge/` | LWIP L2 bridge over wired+wireless — Day 59 |
| `examples/network/vlan_support/` | 802.1Q VLAN tagging demo — Day 59 |
| `examples/network/eth2ap/` | Ethernet ↔ Wi-Fi SoftAP NAT/bridge — Day 59 |
| `examples/protocols/http_server/advanced_tests/` | Advanced HTTPD test harness — Day 59 |
| `examples/wifi/roaming/roaming_11kvr/` | 802.11k/v/r roaming companion to roaming_app — Day 59 |
| `examples/wifi/wifi_aware/nan_console/` | Wi-Fi Aware (NAN) interactive console — Day 59 |
| `examples/wifi/wifi_aware/nan_publisher/` | Wi-Fi Aware (NAN) publisher — Day 59 |
| `examples/wifi/wifi_aware/nan_subscriber/` | Wi-Fi Aware (NAN) subscriber — Day 59 |
| `examples/system/base_mac_address/` | base MAC address API — Day 61 |
| `examples/system/esp_timer/` | high-resolution timer API — Day 61 |
| `examples/system/eventfd/` | POSIX-like eventfd integration with VFS — Day 61 |
| `examples/system/select/` | `select()` over VFS+lwIP sockets — Day 61 |
| `examples/system/startup_time/` | early-boot timing instrumentation — Day 61 |
| `examples/system/light_sleep/` | light-sleep entry/exit + wake sources — Day 61 |
| `examples/system/rt_mqueue/` | POSIX message queue (mqueue) API — Day 61 |
| `examples/system/deep_sleep/` | deep-sleep wake sources + RTC retention — Day 61 |
| `examples/system/efuse/` | eFuse read/burn API — Day 61 |
| `examples/system/perfmon/` | performance-counter (perfmon) demo — Day 61 |
| `examples/system/pthread/` | POSIX pthread API — Day 61 |
| `examples/system/freertos/real_time_stats/` | FreeRTOS runtime stats — Day 61 |
| `examples/system/heap_task_tracking/basic/` | per-task heap accounting (basic) — Day 61 |
| `examples/system/heap_task_tracking/advanced/` | per-task heap accounting (advanced) — Day 61 |
| `examples/system/esp_event/default_event_loop/` | esp_event default loop API — Day 61 |
| `examples/system/esp_event/user_event_loops/` | esp_event user-defined loops — Day 61 |

### Day 61 — drop-in coverage extends into `examples/system/*`

Day 61 surveys `$IDF_PATH/examples/system/` for samples that link
clean against the QEMU Wi-Fi shim + lwIP stack with **zero source
diff** (only `CMakeLists.txt` + `sdkconfig` adjustments via the
wrap script).  Sixteen non-console samples qualify, taking total
stock-sample coverage from **74 → 90**.  The point of this sweep
is not Wi-Fi runtime per se — these samples don't exercise
`esp_wifi_*` — but rather to broaden the regression net protecting
the wrap script.  Every ESP-IDF Wi-Fi sample inherits from one or
more of these building blocks (event loops, timers, threads,
selectors, eventfd, mqueue), so proving the wrap script handles
them cleanly hardens the path the Wi-Fi-runtime samples depend on.

Added in Day 61:

- Timers / queues: `esp_timer`, `rt_mqueue`
- Events: `esp_event/default_event_loop`, `esp_event/user_event_loops`
- Threads: `pthread`, `freertos/real_time_stats`
- Low-power: `light_sleep`, `deep_sleep`
- VFS + selectors: `eventfd`, `select`
- Services: `base_mac_address`, `startup_time`, `efuse`, `perfmon`,
  `heap_task_tracking/{basic,advanced}`

Skipped this round (require esp_wifi_qemu / arch extensions):

- `task_watchdog` — links against `esp_task_wdt_*` (init / deinit /
  add / add_user / reset / reset_user / delete / delete_user /
  status).  Our project's sdkconfig elides the WDT component for
  the QEMU base build, so these symbols are unresolved.
- `ipc/ipc_isr/xtensa` — architecture-specific ASM dependency on
  `get_ps_other_cpu` / `extended_ipc_isr_asm` that the public IDF
  headers don't expose.

Both are tracked in the backlog as future-work; their inclusion
would require either component-level shims (task_watchdog) or
arch-port digging (ipc_isr) — out of scope for a wrap-script
generality sweep.  Day 61 leaves the wrap script unchanged: this
is pure coverage-expansion through SAMPLES additions.

Pinned by `test_basic_wifi_smoke_includes_day61_system_samples`
(asserts the 16 entries are present).

### Day 59 — conditional `protocol_examples_common` injection (FB-032)

Day 59 lands a single but high-leverage wrap-script fix and
takes total stock-sample coverage from **65 to 74** — pure
drop-in (zero `.c`/`.h` source diff to any of the 74 samples).

**FB-032 — conditional `protocol_examples_common` injection.**
The wrap script was unconditionally appending
`examples/common_components/protocol_examples_common` to
`EXTRA_COMPONENT_DIRS`.  This was fine for samples that
actually `#include "protocol_examples_common.h"` or call
`example_connect()`, but for samples whose `idf_component.yml`
pulls `examples/ethernet/basic/components/ethernet_init`, both
components redefine the same `EXAMPLE_USE_INTERNAL_ETHERNET` /
`EXAMPLE_USE_SPI_ETHERNET` / `EXAMPLE_USE_DM9051` /
`EXAMPLE_USE_W5500` Kconfig symbols.  kconfgen treats the
choice-symbol collision as fatal — blocking the entire
`examples/network/*` tree.

The fix gates the injection on
`grep -rqE 'protocol_examples_common|example_connect|example_disconnect|example_configure_stdin_stdout' ${SAMPLE_DIR}/main/`.
Samples that bring their own connection logic no longer pollute
the Kconfig namespace, while everything that used the helper
before still gets it.  Pinned by
`test_build_stock_sample_gates_protocol_examples_common_injection`.

Still deferred:
- `examples/network/sta2eth` — needs `tinyusb` USB-peripheral
  stack (hardware-only — no QEMU emulation).

### Day 60 — `tcp_client` + `udp_client` runtime promotion

Day 60 promotes the two P1 socket samples from **build_only** to
**full runtime** in the smoke gate.  Total stock-sample coverage is
unchanged at 74 (the same two entries flip mode), but the release
gate now exercises the GAP-I lwIP-over-QEMU-Wi-Fi data plane
end-to-end on every push — not just the link/build.

**Why this only needed glue.**  The heavy lifting landed on Day 27
(GAP-I): `esp_wifi_internal_tx` performs real MMIO TX via
`qemu_wifi_tx_raw`; the late `WIFI_EVENT_STA_CONNECTED` handler
assigns the static IP *after* IDF's DHCP-clearing default handler
(no more EHOSTUNREACH); `esp_wifi_internal_free_rx_buffer` actually
frees, removing the leak; `wifi_packet_relay.py` NATs firmware-side
`10.0.2.2:N` to host `127.0.0.1:N` (SLIRP-style); and the helper
echo servers `tools/tcp_echo_server.py` /
`tools/udp_echo_server.py` listen on `127.0.0.1:3333`.  The
project-wide `sdkconfig.qemu.wifi.defaults` already sets
`CONFIG_EXAMPLE_IPV4_ADDR="10.0.2.2"` + `CONFIG_EXAMPLE_PORT=3333`
— so the upstream sample, with zero source change, dials the right
target.  All that remained was wiring the smoke gate to flip those
two entries to `run`.

**The Day-60 glue.**

1. `tools/run-stock-qemu.sh`: when `VERIFY_PROFILE=tcp_client` (or
   `udp_client`), default `TCP_ECHO_PORT` (resp. `UDP_ECHO_PORT`) to
   `3333` if the caller didn't override.  This means a smoke-gate
   entry can express "run this sample, expect the matching echo" by
   profile name alone — no 6th env-var column needed in the SAMPLES
   array.  Override is still possible by exporting the env var
   explicitly.

2. `tools/run-basic-wifi-smoke.sh`: flip the two SAMPLES entries
   from `station|build_only` to `tcp_client|run` (resp.
   `udp_client|run`).

**End-to-end verification** (single sample, smoke-gate path):

```
. $IDF_PATH/export.sh
bash tools/build-stock-sample.sh $IDF_PATH/examples/protocols/sockets/tcp_client
VERIFY_PROFILE=tcp_client bash tools/run-stock-qemu.sh \
    $IDF_PATH/examples/protocols/sockets/tcp_client/build_qemu 60
# → "5 check(s) passed, 0 failed."  TCP-ECHO logs show the firmware
#   dialing 10.0.2.2:3333, payload "Message from ESP32 " round-trips,
#   ESP-IDF sample logs "Received 25 bytes from 10.0.2.2".
```

Pinned by `test_basic_wifi_smoke_promotes_{tcp,udp}_client_to_runtime`,
`test_run_stock_qemu_auto_launches_{tcp,udp}_echo_server`,
`test_sdkconfig_qemu_wifi_defaults_targets_relay_nat`.

### Day 58 — sample-root `components/` discovery (FB-030) + generalized post-`project()` propagation (FB-031)

Day 58 lands two complementary wrap-script generalizations and
takes total stock-sample coverage from **36 to 65** — pure
drop-in (zero `.c`/`.h` source diff to any of the 65 samples).

**FB-030 — sample-root `components/` discovery.**  Stock samples
that ship local components (e.g.
`protocols/http_server/captive_portal/components/dns_server`,
`system/console/advanced/components/cmd_system`) failed with
`Failed to resolve component '<comp>' required by component
'main': unknown name` because the wrap project's PROJECT_DIR is
the wrap dir, not the sample dir, and ESP-IDF's component
discovery only scans `<PROJECT_DIR>/components/` plus
`EXTRA_COMPONENT_DIRS`.  Day-56's data-dir symlink loop
explicitly skipped `components/` (correct — we don't want to
clone the component tree).  Day 58 emits
`list(APPEND EXTRA_COMPONENT_DIRS "${SAMPLE_DIR}/components")`
in the wrap CMakeLists.txt between `cmake_minimum_required(...)`
and `include($ENV{IDF_PATH}/tools/cmake/project.cmake)`, which
is the exact place ESP-IDF reads the variable during component
discovery.  Pinned by
`test_build_stock_sample_injects_extra_component_dirs`.

**FB-031 — generalized post-`project()` propagation.**  FB-029
only re-emitted `target_add_binary_data(...)` lines from the
sample's top-level CMakeLists.txt.  Other project-level calls
were silently dropped, e.g. `protocols/mqtt/custom_outbox`
which injects a C++ override into the system `mqtt` component
via four lines:

```cmake
idf_component_get_property(mqtt mqtt COMPONENT_LIB)
target_sources(${mqtt} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/main/custom_outbox.cpp)
idf_component_get_property(pthread pthread COMPONENT_LIB)
target_link_libraries(${mqtt} ${pthread})
```

Without these, the link fails with `undefined reference to
outbox_enqueue/outbox_dequeue/...`.  Day 58 widens the
propagation to *every non-blank, non-comment line strictly
after the original `project(...)` line*, with four CMake
variable refs rewritten to the literal `${SAMPLE_DIR}`
absolute path: `${CMAKE_CURRENT_SOURCE_DIR}`,
`${CMAKE_CURRENT_LIST_DIR}`, `${PROJECT_DIR}`, `${project_dir}`.
The Day-57 quoted-asset-path rewrite for
`target_add_binary_data` is preserved as a special case.
Pinned by
`test_build_stock_sample_substitutes_cmake_current_source_dir`.

**Coverage delta.**  Combined with a broader sweep of
candidates that newly pass after the FB-030/031 fixes, 29
build_only entries join the smoke gate.  Three trigger the new
fixes directly (`mqtt_custom_outbox`, `http_server_captive_portal`,
`console_advanced`); the rest are samples that were already
within reach of the Day-54..57 wrap and only needed to be
explicitly tried (six http_server variants, three additional
mqtt clients, five socket variants, three modbus variants,
several stand-alones).

Pinned by three regression tests:
`test_basic_wifi_smoke_includes_day58_fb030_fb031_samples`,
`test_build_stock_sample_injects_extra_component_dirs`, and
`test_build_stock_sample_substitutes_cmake_current_source_dir`.

Remaining deferred:
- `network/{sta2eth,bridge,vlan_support,simple_sniffer}` — fail
  at `kconfgen` time on Wi-Fi-AP/Ethernet hybrid config that the
  QEMU sdkconfig overlay does not yet cover.
- `protocols/mqtt/ssl_ds` — needs the Digital Signature
  peripheral (`esp_secure_cert_mgr`); hardware-only.

### Day 56 — probe-configure helper unlocks `${var}` expansion and implicit-all `main`

Day 56 lands a probe-configure step in `tools/build-stock-sample.sh`
and takes total stock-sample coverage from **23 to 32**.  The new
step runs `idf.py reconfigure` on the unmodified sample, parses
the generated `project_description.json`, and feeds main's
authoritative resolved REQUIRES / PRIV_REQUIRES lists back into the
wrap.  This closes FB-027 and unlocks three classes of samples that
the Day-54 textual `extract_requires_kw` could not handle:

1. **`${var}` expansion in PRIV_REQUIRES** (FB-027 primary trigger)
   `examples/protocols/esp_http_client/main/CMakeLists.txt`:
   ```cmake
   set(requires esp-tls nvs_flash esp_event esp_netif esp_http_client)
   list(APPEND requires protocol_examples_common)
   idf_component_register(... PRIV_REQUIRES ${requires})
   ```
   The textual extractor can only see the literal `${requires}` token;
   the probe-configure step sees the resolved `priv_reqs: [esp-tls,
   nvs_flash, esp_event, esp_netif, esp_http_client,
   protocol_examples_common]` and emits that list verbatim.

2. **Implicit-all-components rule for `main`** (icmp_echo, smtp_client)
   When a sample's `main/CMakeLists.txt` declares NO REQUIRES /
   PRIV_REQUIRES at all, ESP-IDF implicitly grants `main` access to
   every component in the build.  `icmp_echo` relies on this to reach
   `esp_console.h` and `smtp_client` to reach `mbedtls/platform.h`,
   even though only `protocol_examples_common` is declared (via
   `idf_component.yml`).  Our wrap always emits a non-empty REQUIRES
   list (esp_wifi + esp_wifi_qemu + ...), which suppresses the
   implicit-all behaviour.  Day 56 detects this case by checking the
   original `main/CMakeLists.txt` for any REQUIRES / PRIV_REQUIRES
   keyword; if absent, the wrap widens REQUIRES to the full probed
   `build_components` list so every transitively-built component is
   directly available to main.

3. **`${project_dir}` references in EMBED_FILES / EMBED_TXTFILES + sample-root data dirs**
   System-level OTA samples embed certificate material via
   `EMBED_TXTFILES ${project_dir}/server_certs/ca_cert.pem` and rely
   on sdkconfig keys (e.g. `CONFIG_MBEDTLS_CUSTOM_CERTIFICATE_BUNDLE_PATH`)
   that the build system resolves relative to `PROJECT_DIR`.  Day 56
   substitutes `${project_dir}` / `${PROJECT_DIR}` /
   `${CMAKE_CURRENT_LIST_DIR}` / `${CMAKE_CURRENT_SOURCE_DIR}` in
   the extracted EMBED clauses, treats absolute paths as pass-through,
   and symlinks every sample-root subdirectory (server_certs/, certs/,
   data/, …) into the wrap dir so the cert-bundle build step finds
   `server_certs/ca_cert.pem` relative to the wrap project root.

The probe result is cached on a content hash of
`main/CMakeLists.txt` + `main/idf_component.yml`, so repeated
builds skip the ~4 s reconfigure overhead unless those files
change.  If the probe fails (e.g. stubbed `idf.py` in unit tests),
Day 56 silently falls back to the Day-54 textual extractor —
keeping existing behaviour intact.

Pinned by three regression tests in `tests/test_stock_sample_build.py`:
`test_basic_wifi_smoke_includes_day56_protocol_samples`,
`test_build_stock_sample_resolves_project_dir_in_embed_txtfiles`,
and `test_build_stock_sample_symlinks_sample_root_data_dirs`.

Remaining deferred:
- `protocols/mqtt/ssl_ds` — requires the Digital Signature
  peripheral (`esp_secure_cert_mgr`) which is hardware-only;
  not in scope for QEMU.

### Day 57 — project-level `target_add_binary_data` propagation (FB-029)

Day 57 closes FB-029 and takes total stock-sample coverage from
**32 to 36**.  Stock TLS-bearing samples in `protocols/mqtt/**`
wire their cert assets at the *project* CMakeLists.txt level via
`target_add_binary_data(<proj>.elf "main/<cert>.pem" TEXT)` rather
than inside `idf_component_register(... EMBED_TXTFILES ...)`.
The Day-54..56 wrap script only inspected `main/CMakeLists.txt`,
so the `_binary_<name>_start` symbol the source references was
never produced and link failed.

`tools/build-stock-sample.sh` now scans the stock sample's
top-level `CMakeLists.txt` for `target_add_binary_data(...)`
lines and re-emits them in the wrap's CMakeLists.txt after the
`project(...)` line.  The first double-quoted argument (the
asset path) is rewritten from a relative path into an absolute
path under `${SAMPLE_DIR}`; CMake-variable refs (e.g.
`${CMAKE_PROJECT_NAME}.elf`) and already-absolute paths pass
through unchanged.  Since the wrap reuses
`project(${SAMPLE_PROJ_NAME})`, hardcoded `<proj>.elf` target
names resolve to the same elf in the wrap — no target rewrite
needed.

Combined with Day-56's sample-root data-dir symlinking (which
alone unblocks `https_x509_bundle`'s sdkconfig-relative `certs/`
lookup), four more samples join the basic-wifi smoke gate:

- `protocols/mqtt/ssl` — single TLS cert via `target_add_binary_data`
- `protocols/mqtt/wss` — single TLS cert (WebSocket+TLS transport)
- `protocols/mqtt/ssl_mutual_auth` — three assets propagated
  (`client.crt`, `client.key`, `mosquitto.org.crt`)
- `protocols/https_x509_bundle` — custom mbedtls certificate
  bundle resolved via `CONFIG_MBEDTLS_CUSTOM_CERTIFICATE_BUNDLE_PATH="certs"`

Pinned by two regression tests in `tests/test_stock_sample_build.py`:
`test_build_stock_sample_propagates_project_target_add_binary_data`
and `test_basic_wifi_smoke_includes_day57_fb029_samples`.

### Day 55 — drop-in coverage advances further into `examples/protocols/**`

Day 55 lands two more samples in the basic-wifi smoke gate, taking
total stock-sample coverage from 21 to **23**:

- `protocols/mqtt/tcp` already linked clean against the QEMU shim
  with zero source diff — direct promotion.
- `protocols/https_request` was blocked because its
  `main/CMakeLists.txt` lists `INCLUDE_DIRS "include"` to expose
  `main/include/time_sync.h` to its `*.c` siblings.  Until Day 55
  the wrapper-project generator overwrote the original INCLUDE_DIRS
  with just `${SAMPLE_MAIN_DIR}`, silently dropping any non-`.`
  entry and leaving `time_sync.h` unreachable from `time_sync.c`.

Day 55 closes FB-028 by adding a second `extract_requires_kw`
invocation for INCLUDE_DIRS and a re-emission loop in the wrap
component CMakeLists: every entry of the original list is mapped
to an absolute path under `${SAMPLE_MAIN_DIR}` (with `.` collapsed
back to `${SAMPLE_MAIN_DIR}` to avoid duplication), and the default
`${SAMPLE_MAIN_DIR}` entry is preserved so samples that omit
INCLUDE_DIRS entirely (icmp_echo, smtp_client, ...) keep working.
Pinned by `test_build_stock_sample_propagates_include_dirs_subdirs`
in `tests/test_stock_sample_build.py`.

Other Day-55 probe outcomes (deferred):
- `protocols/esp_http_client` — blocked by FB-027 (uses
  `PRIV_REQUIRES ${requires}` built via `list(APPEND requires
  esp-tls ...)`; the textual awk extractor cannot evaluate the
  variable).
- `protocols/icmp_echo`, `protocols/smtp_client` — sample's
  `main/CMakeLists.txt` declares **no** `PRIV_REQUIRES` but uses
  components (`esp_console`, `mbedtls`) that normally reach `main`
  via the implicit-all rule.  Our wrap always emits a non-empty
  REQUIRES list (esp_wifi + ...), which disables that implicit-all
  privilege.  Deferred until we add a probe-configure helper that
  dumps the original sample's resolved component graph.
- `protocols/mqtt/ssl` — uses `target_add_binary_data(target ...)`
  at the **project** CMakeLists.txt level (not at the
  `idf_component_register` level), which the wrap script does not
  propagate.  Tracked as FB-029.

### Day 54 — drop-in coverage extends beyond `examples/wifi/**`

Day 54 begins the second phase of the North-Star push: with stock
`examples/wifi/**` now at 15/15 build-only coverage, the natural
next target is every other Wi-Fi-dependent IDF subtree
(`examples/protocols/**`, `examples/system/ota/**`,
`examples/wifi_provisioning/**`) — all ~40 of which call
`example_connect()` and then layer sockets / TLS / HTTP / MQTT on
top of the QEMU Wi-Fi shim.  Day 54 promotes six already-link-clean
P1 samples from `examples/protocols/**` into the basic-wifi smoke
gate (above table), taking total stock-sample coverage from 15 to
**21**.  The gate now proves, on every CI run, that the lwIP /
BSD-socket / DNS surfaces wired on top of the QEMU Wi-Fi shim are
strong enough to build every common socket family with **zero
source diff**.

Day 54 also closes FB-026, a long-standing latent bug in the
wrapper-script awk extractor: the `\)` strip regex used to fire
before the keyword-boundary regex, so any `idf_component_register`
clause whose continuation line contained both another keyword and
the terminating `)` (e.g. `udp_client/main/CMakeLists.txt`'s
`INCLUDE_DIRS "."`) leaked one argument list into the previous one.
Reordering both branches of the extractor to check keyword
boundaries first unblocks `udp_client` and any future sample with
the same CMake shape; pinned by a new
`tests/test_stock_sample_build.py::test_build_stock_sample_keyword_before_close_paren`
regression.

As a side benefit, `tools/build-stock-sample.sh` now also generates
`merged_flash.bin` (the 2 MB QEMU-flashable image) at the end of
every successful build.  The merge logic was previously embedded in
`tools/run-stock-qemu.sh` and only triggered at runtime; lifting it
into the build step keeps the "build artifact" abstraction
self-contained and makes every smoke-gate sample one step closer to
being directly QEMU-bootable.  This is also what lets the existing
GAP-I unit tests in `tests/test_gap_i_tcp.py` activate the
`TestTcpClientBuild::test_merged_flash_exists` assertion as soon
as the smoke gate builds `tcp_client`.

Samples that need CMake-variable expansion in `PRIV_REQUIRES`
(e.g. `protocols/http_server/simple`, `protocols/https_server/simple`,
several `protocols/mqtt/*`, `protocols/ota/*`) are deferred to a
future day; see FB-027.

### Day 53 — finish 100% build-only coverage of `examples/wifi/**`

Day 53 closes the last gap from the Day-52 sweep (FB-024) and brings
build-only coverage of stock `examples/wifi/**` to **15/15** — every
ESP-IDF Wi-Fi sample now links against the QEMU shim with **zero
source diff**, the strongest possible regression gate against silent
shim public-symbol drops.

The two remaining samples — `wifi_eap_fast/` and `wifi_enterprise/` —
were blocked at CMake parse time because their `main/CMakeLists.txt`
embeds TLS material via `EMBED_TXTFILES ca.pem client.crt …`, and
the wrapper-project generator in `tools/build-stock-sample.sh` was
stripping every component-register clause it didn't explicitly
re-emit.  Day 53 extends the existing awk-based extractor with two
extra invocations (`EMBED_FILES`, `EMBED_TXTFILES`) and re-emits the
clauses in the wrap component using **absolute paths** back to the
sample's real `main/`.  Absolute paths bypass component-relative
resolution, so no symlinking is needed — the same shape as the
existing `INCLUDE_DIRS "${SAMPLE_MAIN_DIR}"` line.  See FB-025 for
the convention going forward.

Runtime promotion of either sample would need a real 802.1X / EAP
RADIUS back-end, which the mock_wpa_supplicant does not provide
(and is unlikely to ever provide cheaply).  Build-only coverage is
the right level of investment for these two.



Day 52 doubles the build-only sample count to nine by running the
existing `tools/build-stock-sample.sh` against every remaining
`examples/wifi/**` sample and promoting every one that links clean.
Five (`wps`, `smart_config`, `ftm`, `espnow`, `wps_softap_registrar`)
already linked against the shim with zero source diff and zero shim
work — the build success itself is the strongest currently-available
proof that those flagship feature subsystems' public-symbol surface is
already covered.  A sixth (`itwt`) needed two new link-clean stubs
(`esp_wifi_sta_itwt_setup` / `esp_wifi_sta_twt_config`) returning
`ESP_ERR_NOT_SUPPORTED`, since 802.11ax (HE) is only present on
ESP32-C5/C6/... — never on the esp32 part the QEMU shim emulates.

Two samples remained blocked at end of Day 52 behind a wrapper-script
enhancement (`wifi_eap_fast/`, `wifi_enterprise/` both use
`idf_component_register EMBED_TXTFILES ca.pem ...` whose paths the
Day-52 wrap-script generator did not propagate).  Day 53 closed that
gap (FB-024 → resolved); see the Day-53 section above.

Day 52 also fixes a path-resolution bug in
`tools/build-stock-sample.sh`: `WRAP_DIR` used to be defined as
`${BUILD_DIR}/../_qemu_wrap_<sample>`, which after `rm -rf
${BUILD_DIR}` left a non-canonical path component (`build_qemu/..`)
that the kernel could not traverse on the next write.  `WRAP_DIR`
is now computed via `dirname` so the path is purely lexical.

### Day 51 — `power_save` runtime promotion

`examples/wifi/power_save/` was originally part of the Day-48 build-only
set because (a) its default Kconfig SSID `myssid` does not match the AP
fabricated by `tools/mock_wpa_supplicant.py`, (b) the QEMU Wi-Fi shim's
`esp_wifi_set_inactive_time` rejected any value below 10s — but the
sample's `EXAMPLE_WIFI_BEACON_TIMEOUT` defaults to 6 (Kconfig range
6..30), so `ESP_ERROR_CHECK(esp_wifi_set_inactive_time(WIFI_IF_STA, 6))`
aborted on boot, and (c) the sample's `sdkconfig.defaults` enables
`CONFIG_PM_ENABLE` + tickless idle + light sleep, which on QEMU trips a
`LoadStorePIFAddrError` in `rtc_sleep_pd` because the RTC peripheral
register space is not modelled.

Day 51 closes all three blockers without modifying the sample's `.c`
or `.h`:

1. **Per-interface inactive-time minimum** — the IDF docs in
   `esp_wifi.h` actually say `ESP_ERR_INVALID_ARG` when STA `sec < 3`
   and AP `sec < 10`.  The shim previously enforced `sec < 10`
   uniformly, which falsely rejected the sample's STA-side default of
   6s.  `esp_wifi_set_inactive_time` now uses the spec'd
   per-interface threshold.

2. **Power management overlay** — `tools/sample-overlays/power_save.sdkconfig`
   sets `CONFIG_PM_ENABLE=n` and `CONFIG_FREERTOS_USE_TICKLESS_IDLE=n`
   so the firmware never calls into `esp_light_sleep_start`.  The
   `esp_wifi_set_ps()` path itself (the API surface this sample is
   meant to prove) still runs end-to-end.

3. **SSID overlay** — same pattern as Day 50 fast_scan:
   `CONFIG_EXAMPLE_WIFI_SSID="QEMU_TEST"` /
   `CONFIG_EXAMPLE_WIFI_PASSWORD="qemu1234"` via the
   `EXTRA_SDKCONFIG_DEFAULTS` channel.

Day 51 also hardens `tools/build-stock-sample.sh` to invalidate the
wrapper's persisted `sdkconfig` whenever the resolved
`SDKCONFIG_DEFAULTS` chain changes (sha1 hash stored next to it),
fixing a class of bugs where a new overlay file would be silently
ignored on a rebuild because ESP-IDF only consults the defaults to
seed an initial sdkconfig.

The runtime evidence is `got ip:10.0.2.15` on the serial log within
the smoke gate's duration.

### Day 50 — `fast_scan` runtime promotion

`examples/wifi/fast_scan/` was originally part of the Day-48 build-only set
because (a) its default Kconfig SSID `myssid` does not match the AP fabricated
by `tools/mock_wpa_supplicant.py` (which advertises `QEMU_TEST`), and (b) the
sample's `WIFI_FAST_SCAN` method exposed a startup-scan-vs-`CMD_CONNECT`
race in the firmware shim that the `getting_started/station` example
happened to step around by virtue of slightly different task timing.

Day 50 closes both blockers, so the gate now runs the sample end-to-end:

1. **Firmware shim ordering** — `esp_wifi_start` now MMIO-writes the
   housekeeping `CMD_SCAN` *before* posting `WIFI_EVENT_STA_START`.  The
   event task runs at `tskIDLE_PRIORITY+2` and can preempt the caller as
   soon as `esp_event_post` returns; previously the app's `STA_START`
   handler could call `esp_wifi_connect()` (issuing `CMD_CONNECT`) on the
   device before our own `CMD_SCAN` had been written, which left
   `scan_only=true` on top of an in-flight connect flow.

2. **Device-side defensive guard** — `WIFI_CMD_SCAN` is now dropped when
   `s->status == WIFI_STATE_STARTED && s->conn_state` is anything other
   than `WPA_CONN_NONE` / `WPA_CONN_IDLE`.  This makes the device robust
   against any future caller pattern that issues `CMD_SCAN` while a
   connect is in flight.

3. **`EXTRA_SDKCONFIG_DEFAULTS` overlay channel** — the smoke gate now
   accepts a 5th `SAMPLES` entry field that points at a per-sample
   sdkconfig fragment.  `tools/sample-overlays/fast_scan.sdkconfig`
   provisions `CONFIG_EXAMPLE_WIFI_SSID="QEMU_TEST"` /
   `CONFIG_EXAMPLE_WIFI_PASSWORD="qemu1234"` so the example aims at the
   mock supplicant's AP.  This stays inside the zero-source-diff
   contract — only the sdkconfig channel is touched.

The runtime evidence is the same as `getting_started/station`:
`got ip:10.0.2.15` on the serial log within the smoke gate's duration.

## Prerequisites

- ESP-IDF v5.5 or newer is installed and `IDF_PATH` points to it.
- The project Python virtual environment exists at `.venv/`.
- The patched QEMU binary exists at `tools/qemu-src/build/qemu-system-xtensa`.
- The release helpers are run from this repository checkout.

Typical setup:

```bash
cd /path/to/esp32-display-qemu-demo
. ~/esp-idf/export.sh
source .venv/bin/activate
bash tools/build-qemu.sh
```

## One-command Release Smoke Gate

Use this as the release readiness command for the basic Wi-Fi scope:

```bash
LOG_DIR=/tmp/qemu-wifi-smoke bash tools/run-basic-wifi-smoke.sh 60
```

The gate builds and runs station, scan, and softAP. It writes per-sample logs
and a TSV summary:

```text
/tmp/qemu-wifi-smoke/summary.tsv
/tmp/qemu-wifi-smoke/station-build.log
/tmp/qemu-wifi-smoke/station-run.log
/tmp/qemu-wifi-smoke/station-serial.log
/tmp/qemu-wifi-smoke/scan-build.log
/tmp/qemu-wifi-smoke/scan-run.log
/tmp/qemu-wifi-smoke/scan-serial.log
/tmp/qemu-wifi-smoke/softAP-build.log
/tmp/qemu-wifi-smoke/softAP-run.log
/tmp/qemu-wifi-smoke/softAP-serial.log
```

Expected summary shape:

```text
sample	profile	build	run	build_log	run_log	serial_log
station	station	ok	ok	...
scan	scan	ok	ok	...
softAP	softap	ok	ok	...
```

## Build And Run One Sample

Build a stock sample with the QEMU Wi-Fi component overlay:

```bash
bash tools/build-stock-sample.sh "$IDF_PATH/examples/wifi/getting_started/station"
bash tools/build-stock-sample.sh "$IDF_PATH/examples/wifi/scan"
bash tools/build-stock-sample.sh "$IDF_PATH/examples/wifi/getting_started/softAP"
```

Run each built sample with the matching verifier profile:

```bash
VERIFY_PROFILE=station \
  bash tools/run-stock-qemu.sh "$IDF_PATH/examples/wifi/getting_started/station/build_qemu" 60

VERIFY_PROFILE=scan \
  bash tools/run-stock-qemu.sh "$IDF_PATH/examples/wifi/scan/build_qemu" 60

VERIFY_PROFILE=softap \
  bash tools/run-stock-qemu.sh "$IDF_PATH/examples/wifi/getting_started/softAP/build_qemu" 60
```

The runner starts `tools/mock_wpa_supplicant.py` and
`tools/wifi_packet_relay.py`, boots QEMU, captures serial output, and checks the
profile-specific log pattern.

## Expected Logs

Station:

```text
WIFI_EVENT_STA_START
WIFI_EVENT_STA_CONNECTED
got ip:10.0.2.15
```

Scan:

```text
WIFI_EVENT_STA_START
Total APs scanned = 1
SSID QEMU_TEST
```

softAP:

```text
WIFI_EVENT_AP_START
wifi_init_softap finished
```

## Known Limits

- The release scope is basic STA, scan, and softAP only.
- softAP currently posts AP lifecycle events and exposes AP config/station-list
  APIs, but it does not yet accept real external stations.
- ESPNOW, WPS, SmartConfig, WPA2-Enterprise, promiscuous/sniffer mode, IPv6,
  DNS proxying, DHCP server behavior, and external internet NAT are out of
  scope for this release.
- Socket data-plane samples such as `tcp_client` are useful confidence tests,
  but they are not part of the basic STA/SCAN/AP release gate.

## Troubleshooting

- If `IDF_PATH` is missing, run `. ~/esp-idf/export.sh` or export the correct
  ESP-IDF checkout path.
- If QEMU is missing, run `bash tools/build-qemu.sh` from this repository.
- If a single sample fails, inspect its `*-build.log`, `*-run.log`, and
  `*-serial.log` paths from `summary.tsv`.
- If scan output is missing, rerun the smoke gate and inspect
  `scan-serial.log` for `Total APs scanned` and `SSID QEMU_TEST`.

---

## Real Wi-Fi Passthrough Mode (Day 37+)

In addition to the default mock mode, the simulator supports a
**real wpa_supplicant passthrough** mode where the QEMU device bridges its
ctrl interface directly to the host's running `wpa_supplicant` daemon.

### How it works

| Layer | Mock mode | Real-WiFi mode |
|-------|-----------|----------------|
| Ctrl plane | `mock_wpa_supplicant.py` simulates AP | Host's real `wpa_supplicant` connects actual WiFi card |
| IP assignment | Static `10.0.2.15` (mock injects via STATUS) | Real DHCP IP assigned by actual router |
| Packet relay | SLIRP: TCP/UDP to localhost only | TCP/UDP proxied via host sockets → any real destination |
| ARP replies | Relay responds for `10.0.2.2` | Relay responds for real gateway IP |
| Needs sudo? | No | Only if wpa_supplicant socket is root-only |

### Prerequisites

1. `wpa_supplicant` or `NetworkManager` must be running on the host.
2. Identify your wireless interface name:
   ```bash
   ip -o link show | grep '^[0-9]*:.*wl'
   ```
3. Grant your user access to the wpa_supplicant ctrl socket (recommended):
   ```bash
   sudo adduser "$USER" netdev
   # log out and back in — or use WIFI_SUDO=1 for a one-off run
   ```

### Run a stock sample with real WiFi

```bash
# Build the sample first (same as mock mode):
bash tools/build-stock-sample.sh \
    "$IDF_PATH/examples/wifi/getting_started/station"

# Then run with the real wpa_supplicant:
bash tools/run-real-wifi.sh \
    "$IDF_PATH/examples/wifi/getting_started/station/build_qemu"
```

The QEMU guest will:
1. Call `esp_wifi_scan()` → real scan results from the host adapter.
2. Call `esp_wifi_connect()` with the SSID/password baked into the firmware.
3. The host WiFi card connects to that SSID.
4. The guest receives the real DHCP IP (e.g. `192.168.1.x`).
5. TCP/UDP traffic is proxied via the host's normal network stack.

### Sudo for root-only wpa_supplicant sockets

If the socket is not accessible to your user:

```bash
# Option A: use WIFI_SUDO=1 for this run
WIFI_SUDO=1 bash tools/run-real-wifi.sh <build_dir>

# In tmux, create a 'sudo' window for the privileged QEMU process:
tmux new-window -n sudo
# Then inside that window:
WIFI_SUDO=1 bash tools/run-real-wifi.sh <build_dir>

# Option B: grant permanent access (preferred)
sudo adduser "$USER" netdev   # then re-login
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WIFI_IFACE` | auto-detect | Wireless interface name (e.g. `wlan0`) |
| `WIFI_SUDO` | auto-detect | `1` = run QEMU under sudo |
| `PKT_SOCKET` | `/tmp/real-wifi-pkt-relay` | Unix socket for packet relay |
| `VERIFY_PROFILE` | `station` | `station` \| `scan` \| `softap` \| `none` |
| `LOG_FILE` | `/tmp/real-wifi-qemu.log` | QEMU serial output log |

### Known limits in real-WiFi mode

- The guest's SSID/password are compiled into the firmware; change them in
  `menuconfig` and rebuild if you want to connect to a different network.
- The host's existing WiFi connection may be briefly interrupted while
  `wpa_supplicant` switches to the new network.
- DHCP is handled by the real DHCP server; the guest IP is whatever it assigns.
- ICMP (ping) may require root for raw socket access; it falls back silently.
- softAP passthrough is not meaningful in this mode (AP mode creates a
  virtual AP on the host, which the current relay does not bridge).