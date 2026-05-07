# Release Notes — v1.0.0-qemu-wifi-basic

**Release date:** 2026-05-07  
**Tag:** `v1.0.0-qemu-wifi-basic`  
**Scope:** Basic STA / SCAN / SoftAP simulator release

---

## What this release is

`esp32-display-qemu-demo` contains a patched QEMU Wi-Fi device and an
ESP-IDF component shim (`esp_wifi_qemu`) that together let stock ESP-IDF
Wi-Fi samples run inside QEMU without any `.c` or `.h` source changes.
This release establishes the first stable, tested, and documented baseline
for the **station**, **scan**, and **softAP** modes.

---

## Supported stock ESP-IDF samples (zero source changes)

| Sample path | Runtime evidence | QEMU run command |
|-------------|-----------------|------------------|
| `examples/wifi/getting_started/station/` | `got ip:10.0.2.15` | `VERIFY_PROFILE=station bash tools/run-stock-qemu.sh` |
| `examples/wifi/scan/` | `Total APs scanned = 1` + `SSID QEMU_TEST` | `VERIFY_PROFILE=scan bash tools/run-stock-qemu.sh` |
| `examples/wifi/getting_started/softAP/` | `wifi_init_softap finished` | `VERIFY_PROFILE=softap bash tools/run-stock-qemu.sh` |

Data-plane bonus (beyond this release's formal scope, but included):

| Sample path | Runtime evidence |
|-------------|-----------------|
| `examples/protocols/sockets/tcp_client/` | `Echo: Message from ESP32` |
| `examples/protocols/sockets/udp_client/` | `Echo (UDP): Hello from ESP32` |

---

## Prerequisites

- ESP-IDF v5.5+ (`IDF_PATH` set, `source ~/esp-idf/export.sh` run)
- Patched QEMU binary at `tools/qemu-src/build/qemu-system-xtensa` (build with `bash tools/build-qemu.sh`)
- Project Python venv: `source .venv/bin/activate`

---

## One-command release gate

```bash
LOG_DIR=/tmp/qemu-wifi-smoke bash tools/run-basic-wifi-smoke.sh 90
cat /tmp/qemu-wifi-smoke/summary.tsv
```

All three rows must show `PASS`.

---

## Key commits in this release

| Commit | Description |
|--------|-------------|
| `c023b73` | fix(wifi): stabilize stock scan verification (Day 28) |
| `d3ed6a6` | fix(wifi): harden APSTA event handling (Day 29) |
| `9bef799` | test(wifi): add basic stock sample smoke gate (Day 30) |
| `c78fde5` | test(wifi): add smoke gate summary artifact (Day 31) |
| `2708c6f` | docs(wifi): freeze stock sample release guide (Day 32) |
| `7d98937` | feat(day-33): refactor extras→promisc, P1 udp_client, lwip_probe (Day 33) |
| `87619ca` | fix(day-34): fix wifi_ui dangling label, transmit_wrap NULL, ARP relay miss (Day 34) |
| `c15abf5` | fix(wifi): event-task race, wpa_ctrl fd leak, nographic serial (Day 35) |

---

## Architecture summary

```
ESP-IDF application (stock, unmodified)
        │  esp_wifi_* / esp_netif_* API
        ▼
 esp_wifi_qemu component (shim)
   esp_wifi_shim.c    — lifecycle API, event task, mode, static IP
   esp_wifi_netif.c   — lwIP MMIO TX/RX driver
   esp_wifi_extras.c  — no-op stubs for ps/bandwidth/country/restore/…
        │  MMIO registers (0x3FF69000 + offsets)
        ▼
 QEMU patched device (hw/net/esp_wifi.c)
   — command interpreter (INIT, SET_MODE, SET_CONFIG, START, SCAN, CONNECT…)
   — wpa_supplicant ctrl socket bridge (→ mock_wpa_supplicant.py)
   — packet relay socket bridge (→ wifi_packet_relay.py)
        │  Unix domain socket / UDP socket
        ▼
 Host Python daemons
   tools/mock_wpa_supplicant.py  — simulates wpa_supplicant state machine
   tools/wifi_packet_relay.py    — bridges ARP/IP frames to host network
```

---

## Known limitations (not in this release scope)

- **No ESPNOW** (`esp_now_*` APIs unimplemented)
- **No WPS / SmartConfig**
- **No DNS proxy** (hostname resolution fails)
- **No IPv6**
- **No real outbound NAT** (only `10.0.2.2` and `10.0.2.100` are routed)
- **No DHCP server** (IP assigned statically via wpa_supplicant STATUS mock)
- **softAP client association** is simulated (no real clients can connect)
- `esp_wifi_ap_get_sta_list` returns an empty list (GC'd by linker)
- `WIFI_REG_EVENT` is single-value (events can be overwritten under load)

---

## Running the non-runtime test suite

```bash
source .venv/bin/activate
python -m pytest tests/ \
  --ignore=tests/test_qemu_boot.py \
  --ignore=tests/test_qemu_ws_handshake.py \
  --ignore=tests/test_qemu_integrated_demo.py \
  --ignore=tests/test_qemu_vram_file.py \
  --ignore=tests/test_qemu_lwip_probe.py \
  -q
# Expected: 186 passed, 6 skipped
```
