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
| `examples/protocols/sockets/tcp_client/` | lwIP-over-Wi-Fi BSD TCP-client socket API (`socket`, `connect`, `send`, `recv`) links clean on top of `example_connect()` — Day 54 |
| `examples/protocols/sockets/tcp_server/` | BSD TCP-server socket API (`bind`, `listen`, `accept`) links clean on top of `example_connect()` — Day 54 |
| `examples/protocols/sockets/udp_client/` | BSD UDP-client socket API (`sendto`) links clean — Day 54 |
| `examples/protocols/sockets/udp_server/` | BSD UDP-server socket API (`recvfrom`) links clean — Day 54 |
| `examples/protocols/http_request/` | lwIP DNS resolver + raw HTTP request over a BSD socket — Day 54 |
| `examples/protocols/sntp/` | LwIP SNTP client over Wi-Fi — Day 54 |
| `examples/protocols/mqtt/tcp/` | esp_mqtt_client public API end-to-end over plain TCP — Day 55 |
| `examples/protocols/https_request/` | TLS-secured HTTP GET with embedded CA / server certs — Day 55 (needs FB-028 INCLUDE_DIRS subdir propagation fix) |

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