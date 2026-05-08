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

### Build-only coverage (Day 48)

The release smoke gate also builds the following samples to prove that the
QEMU Wi-Fi shim implements a wide enough subset of `esp_wifi.h` for them to
link with **zero source modification** (only `CMakeLists.txt` +
`sdkconfig.defaults` differ).  Their runtime is not exercised by the gate
because it depends on knobs the gate does not provision (sample-specific
Kconfig SSID / console UART input).

| ESP-IDF sample | What it proves builds clean |
|----------------|-----------------------------|
| `examples/wifi/fast_scan/` | Phase A connection AP record + Phase B channel / authmode / cipher tracking |
| `examples/wifi/power_save/` | Phase C `esp_wifi_set_ps` / `esp_wifi_get_ps` round-trip |
| `examples/wifi/softap_sta/` | Phase A + B + C + D-1 + D-2 link together for an APSTA-mode binary (only stock sample that drives both `WIFI_MODE_AP` and `WIFI_MODE_STA` simultaneously) — Day 49 |

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