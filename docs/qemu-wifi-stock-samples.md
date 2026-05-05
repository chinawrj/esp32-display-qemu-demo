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