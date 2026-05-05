# QEMU Virtual Wi-Fi — Architecture & Protocol Spec (NEXT-002)

Status: **Implemented** — NEXT-002 completed on Days 8-12; TCP/IP data-plane
support landed on Day 14; the LVGL + Wi-Fi integrated demo landed on Days
15-16.

---

## 1. Overview

NEXT-002 adds a virtual Wi-Fi STA device to the Espressif QEMU fork so that
ESP-IDF Wi-Fi applications can run in the emulator through the public
`esp_wifi_*` API. The simulator is intentionally implemented at the API/event
boundary: firmware calls `esp_wifi_init()`, `esp_wifi_connect()`, scan APIs,
and normal `esp_event` handlers; the QEMU component turns those operations into
a private firmware-to-QEMU command channel and host-side ctrl socket traffic.

```
    ESP-IDF application firmware
      │  public esp_wifi_* API calls + esp_event handlers
       ▼
    Component: esp_wifi_qemu API shim  (components/)
      │  private MMIO mailbox at 0x3ff75000
       ▼
  QEMU device: esp_wifi   (tools/qemu-src/hw/net/esp_wifi.c)
      │  Unix domain socket ctrl protocol (async, non-blocking)
       ▼
    Host ctrl daemon: real wpa_supplicant or tools/mock_wpa_supplicant.py
      │  optional packet relay for TCP/IP data plane
       ▼
    Host Wi-Fi NIC / mock AP
```

### Why this approach

- `DR_REG_WDEV_BASE = 0x3ff75000` is used as a stable mailbox address already
  present in ESP32 address space, so the firmware can communicate with QEMU
  without extra linker or MMU changes.
- The mailbox is a project-defined protocol, not an attempt to reproduce the
  ESP32 Wi-Fi hardware register map. Public `esp_wifi_*` behavior is the
  compatibility target.
- QEMU handles async ctrl-socket communication internally using QEMU's GLib
  main loop (same pattern as `esp_rgb_ws.c`); firmware observes normal ESP-IDF
  events such as `WIFI_EVENT_STA_CONNECTED` and `IP_EVENT_STA_GOT_IP`.
- `CONFIG_ESP_WIFI_QEMU=y` in sdkconfig redirects `esp_wifi_*` to our stub
  component at compile time; unmodified release firmware keeps using the real
  blob driver.

### Design boundary: API simulation, not register simulation

This project simulates Wi-Fi at the **ESP-IDF API level**. The virtual device
does not model the real ESP32 RF/MAC/PHY register interface, timing behavior,
or closed-source Wi-Fi firmware internals. Instead:

- Application code calls the same public `esp_wifi_*`, `esp_netif`, and
  `esp_event` surfaces it would use on hardware.
- `components/esp_wifi_qemu/` implements those public APIs and posts the same
  high-level events the application expects.
- The MMIO registers below are a private firmware-to-QEMU transport for commands,
  status, events, scan results, IP metadata, and DMA buffer pointers.
- Tests validate behavior at the application/event level, for example by
  asserting serial output contains `got ip:` rather than by inspecting mailbox
  register values.

---

## 2. Private MMIO Mailbox

Base address: `0x3ff75000` (`DR_REG_WDEV_BASE`)

All registers are 32-bit, little-endian.

| Offset | Name                | RW | Description |
|--------|---------------------|----|-------------|
| 0x000  | `WIFI_VER`          | R  | `[31:16]` major, `[15:0]` minor. v1 = `0x00010000` |
| 0x004  | `WIFI_CMD`          | RW | Write a `CMD_*` code to issue a command (auto-clears). Read = 0 when idle, 1 when busy |
| 0x008  | `WIFI_STATUS`       | R  | Current device state (see `WIFI_STATE_*` enum) |
| 0x00c  | `WIFI_EVENT`        | R  | Pending event code (`EVT_*`). 0 = none. Write 0 to acknowledge (clears IRQ) |
| 0x010  | `WIFI_IRQ_ENABLE`   | RW | Bit mask of enabled events (bit N = enable `EVT_N`) |
| 0x014  | `WIFI_SSID_LEN`     | RW | SSID length (0–32) |
| 0x018  | `WIFI_SSID[0..7]`   | RW | SSID bytes, 4-byte words, offsets 0x018–0x034 (32 bytes total) |
| 0x038  | `WIFI_PASS_LEN`     | RW | Passphrase length (0–63) |
| 0x03c  | `WIFI_PASS[0..15]`  | RW | Passphrase bytes, 4-byte words, offsets 0x03c–0x07c (64 bytes total) |
| 0x080  | `WIFI_MAC[0]`       | R  | Host Wi-Fi MAC bytes 0–3 (LE) |
| 0x084  | `WIFI_MAC[1]`       | R  | Host Wi-Fi MAC bytes 4–5 in `[31:16]`, 0 in `[15:0]` |
| 0x088  | `WIFI_IP_ADDR`      | R  | Assigned IPv4 address (LE u32, populated after CONNECTED) |
| 0x08c  | `WIFI_IP_MASK`      | R  | Subnet mask (LE u32) |
| 0x090  | `WIFI_IP_GW`        | R  | Default gateway (LE u32) |
| 0x094  | `WIFI_SCAN_COUNT`   | R  | Number of scan results available (after `EVT_SCAN_DONE`) |
| 0x098  | `WIFI_SCAN_IDX`     | RW | Write index N to load result N into SCAN_BSSID/SSID/RSSI regs |
| 0x09c  | `WIFI_SCAN_RSSI`    | R  | RSSI of selected scan result (signed s8 in bits [7:0]) |
| 0x0a0  | `WIFI_SCAN_SSID_LEN`| R  | SSID length of selected scan result |
| 0x0a4  | `WIFI_SCAN_SSID[0..7]` | R | SSID bytes of selected scan result (offsets 0x0a4–0x0c0) |
| 0x0c4  | `WIFI_SCAN_BSSID[0..1]` | R | BSSID of selected scan result (6 bytes) |
| 0x0d0  | `WIFI_CTRL_SOCKET_LEN`| RW | Length of wpa_supplicant ctrl socket path |
| 0x0d4  | `WIFI_CTRL_SOCKET_PATH[0..15]` | RW | ctrl socket path bytes (64 bytes, offsets 0x0d4–0x114) |

Additional data-plane registers live through offset `0x120`; the complete
mailbox range intentionally stays below `DR_REG_WDEV_BASE + 0x144`, where the
ESP32 RNG device is mapped in QEMU.

---

## 3. Command Codes (`WIFI_CMD`)

Write to `WIFI_CMD` register; device sets CMD=1 (busy) while processing,
clears to 0 and sets `WIFI_EVENT` when done.

| Code | Name            | Description |
|------|-----------------|-------------|
| 0x01 | `CMD_INIT`      | Initialize device, open ctrl socket, attach to wpa_supplicant |
| 0x02 | `CMD_DEINIT`    | Detach, close socket |
| 0x03 | `CMD_SET_MODE_STA` | Set STA mode (currently the only supported mode) |
| 0x04 | `CMD_START`     | Start Wi-Fi subsystem |
| 0x05 | `CMD_STOP`      | Stop Wi-Fi subsystem |
| 0x06 | `CMD_CONNECT`   | Associate using SSID/PASS registers |
| 0x07 | `CMD_DISCONNECT`| Disconnect from current AP |
| 0x08 | `CMD_SCAN`      | Trigger background scan; `EVT_SCAN_DONE` fired on completion |
| 0x09 | `CMD_GET_MAC`   | Read host MAC into `WIFI_MAC[0..1]` |

---

## 4. Event Codes (`WIFI_EVENT`)

Set in `WIFI_EVENT` register by the device; firmware reads and writes 0 to
acknowledge (clears the register and de-asserts the virtual IRQ line).

| Code | Name                    | Notes |
|------|-------------------------|-------|
| 0x01 | `EVT_INIT_DONE`         | `CMD_INIT` completed OK |
| 0x02 | `EVT_INIT_FAIL`         | ctrl socket not found / attach refused |
| 0x03 | `EVT_START_DONE`        | `CMD_START` → `WIFI_EVENT_STA_START` |
| 0x04 | `EVT_STOP_DONE`         | `WIFI_EVENT_STA_STOP` |
| 0x05 | `EVT_CONNECTED`         | wpa_supplicant reported CONNECTED; IP registers populated |
| 0x06 | `EVT_DISCONNECTED`      | wpa_supplicant reported DISCONNECTED |
| 0x07 | `EVT_GOT_IP`            | DHCP complete; IP/mask/GW registers valid |
| 0x08 | `EVT_SCAN_DONE`         | Scan results ready; `WIFI_SCAN_COUNT` valid |
| 0x09 | `EVT_ERROR`             | Generic error (see `WIFI_STATUS` for details) |

---

## 5. Device State Machine (`WIFI_STATUS`)

```
  UNINIT ──(CMD_INIT OK)──► IDLE
    │
    └──(CMD_INIT FAIL)──► ERROR

  IDLE ──(CMD_SET_MODE_STA + CMD_START)──► STARTED
    │
  STARTED ──(CMD_CONNECT)──► CONNECTING
    │                            │
    │             (wpa CONNECTED)▼
    │                       CONNECTED ──(CMD_DISCONNECT / EVT_DISCONNECTED)──► STARTED
    │
  STARTED ──(CMD_STOP)──► IDLE
```

| Code | Name         |
|------|--------------|
| 0x00 | `STATE_UNINIT`   |
| 0x01 | `STATE_IDLE`     |
| 0x02 | `STATE_STARTED`  |
| 0x03 | `STATE_CONNECTING` |
| 0x04 | `STATE_CONNECTED`  |
| 0x10 | `STATE_ERROR`    |

---

## 6. wpa_supplicant Integration

The QEMU device communicates with `wpa_supplicant` via its ctrl socket.
The default path is `/var/run/wpa_supplicant/<iface>` where `<iface>` is
the first Wi-Fi interface found by scanning `/var/run/wpa_supplicant/`.
Override via `ESP_WIFI_CTRL_SOCKET` environment variable or by writing the
path to `WIFI_CTRL_SOCKET_*` registers before `CMD_INIT`.

### wpa_supplicant command sequence for connect

```
ATTACH                          → "OK\n"
SCAN                            → "OK\n" (wait for CTRL-EVENT-SCAN-RESULTS)
SCAN_RESULTS                    → tab-delimited BSSID / freq / signal / flags / ssid
ADD_NETWORK                     → "<id>\n"
SET_NETWORK <id> ssid "<ssid>"  → "OK\n"
SET_NETWORK <id> psk "<pass>"   → "OK\n"  (or key_mgmt NONE for open)
SELECT_NETWORK <id>             → "OK\n"
                                (wait for CTRL-EVENT-CONNECTED)
STATUS                          → ip_address=... / address=...
DETACH                          → "OK\n"
```

All socket I/O runs on QEMU's GLib main loop using `QIOChannelSocket` +
`g_io_add_watch()` — same pattern used in `esp_rgb_ws.c`.  The firmware
vCPU thread never blocks on wpa_supplicant I/O.

---

## 7. ESP-IDF Component (`esp_wifi_qemu`)

Located at `components/esp_wifi_qemu/`.

### Kconfig option

`CONFIG_ESP_WIFI_QEMU` (bool, default n). Enabled automatically in
`sdkconfig.defaults` for the QEMU target. When `y`, the component's
`esp_wifi_*` stubs are compiled and the real Wi-Fi blob driver is excluded.

### API mapping

| ESP-IDF API | Component action |
|---|---|
| `esp_wifi_init()` | Write `CMD_INIT` to MMIO; poll `EVT_INIT_DONE` |
| `esp_wifi_set_mode(WIFI_MODE_STA)` | Write `CMD_SET_MODE_STA` |
| `esp_wifi_start()` | Write `CMD_START`; wait `EVT_START_DONE`; post `WIFI_EVENT_STA_START` |
| `esp_wifi_set_config(IF_STA, cfg)` | Write SSID/PASS to mailbox registers |
| `esp_wifi_connect()` | Write `CMD_CONNECT`; return immediately; async task posts connect/IP events |
| `esp_wifi_scan_start()` | Write `CMD_SCAN`; optionally wait for `EVT_SCAN_DONE` |
| `esp_wifi_scan_get_ap_records()` | Read `WIFI_SCAN_COUNT`, iterate `WIFI_SCAN_IDX` |
| `esp_wifi_get_mac()` | Write `CMD_GET_MAC`; read `WIFI_MAC` registers |
| `esp_wifi_deinit()` | Write `CMD_DEINIT` |
| `esp_wifi_stop()` | Write `CMD_STOP`; wait `EVT_STOP_DONE` |
| `esp_wifi_disconnect()` | Write `CMD_DISCONNECT`; wait `EVT_DISCONNECTED` |

Event delivery is implemented by a FreeRTOS task in `esp_wifi_shim.c` polling
`WIFI_REG_EVENT`. It posts the corresponding `esp_event_loop` events and then
acknowledges the mailbox event by writing 0.

### TCP/IP data plane

Day 14 added a raw Ethernet data path between ESP-IDF lwIP and the QEMU Wi-Fi
device. Firmware registers static DRAM TX/RX buffers with QEMU through
`WIFI_REG_TX_ADDR` and `WIFI_REG_RX_ADDR`; writes to `WIFI_REG_TX_LEN` trigger
QEMU to read a frame from guest memory, and `WIFI_EVT_RX_READY` tells firmware
that QEMU wrote a received frame into the RX buffer. `esp_wifi_netif.c` installs
an `esp_netif` transmit callback and injects RX frames with `esp_netif_receive()`.

Current status: the lwIP data-plane plumbing is present, but app-level TCP/UDP
traffic is not yet covered by an end-to-end runtime test. `tools/wifi_packet_relay.py`
can relay ARP, UDP, TCP, and limited ICMP through `ESP_WIFI_PKT_SOCKET`, but
the main integrated demo currently starts only the mock wpa_supplicant ctrl
socket. Treat socket-level networking as **implemented but not accepted** until
the demo/test harness starts the packet relay and proves an lwIP socket request
from firmware reaches a host service.

---

## 8. Files

| Path | Description |
|---|---|
| `tools/qemu-src-patches/hw/net/esp_wifi.c` | QEMU device implementation |
| `tools/qemu-src-patches/include/hw/net/esp_wifi.h` | Device header |
| `tools/build-qemu.sh` | Must copy + rebuild after `esp_wifi.c` is added |
| `components/esp_wifi_qemu/CMakeLists.txt` | Component build |
| `components/esp_wifi_qemu/Kconfig.projbuild` | `CONFIG_ESP_WIFI_QEMU` |
| `components/esp_wifi_qemu/include/esp_wifi_qemu.h` | Internal header |
| `components/esp_wifi_qemu/esp_wifi_shim.c` | Lifecycle API, command helper, event task |
| `components/esp_wifi_qemu/esp_wifi_config.c` | Config, connect/disconnect, MAC APIs |
| `components/esp_wifi_qemu/esp_wifi_scan.c` | Scan APIs |
| `components/esp_wifi_qemu/esp_wifi_netif.c` | lwIP data-plane driver |
| `tools/mock_wpa_supplicant.py` | Test/demo ctrl-socket daemon for API-level Wi-Fi simulation |
| `tools/wifi_packet_relay.py` | Host-side packet relay for TCP/IP data-plane testing |
| `sdkconfig.defaults` | `CONFIG_ESP_WIFI_QEMU=y` for QEMU builds |
| `tests/test_qemu_wifi_sta.py` | Automated integration test |
| `docs/qemu-wifi.md` | This document |

---

## 9. Acceptance Criteria

- [x] `bash tools/build-qemu.sh` compiles `qemu-system-xtensa` with the
      `esp_wifi` device (zero errors, zero new warnings).
- [x] `examples/wifi_sta/main/app_main.c` (copied from ESP-IDF examples,
      not modified) boots in QEMU and prints `got ip:`.
- [x] `pytest -q tests/test_qemu_wifi_sta.py` passes on Linux with a
  reachable ctrl socket or skips when runtime prerequisites are absent.
- [x] Full existing test suite has zero regressions.
- [x] The integrated LVGL + Wi-Fi demo boots in QEMU with
  `tools/mock_wpa_supplicant.py` and prints `got ip:` without real Wi-Fi
  hardware.
- [x] Real hardware builds keep `CONFIG_ESP_WIFI_QEMU=n` by default, so the
  shim stays out of normal firmware.

---

## 10. Known Limitations (v1 scope)

- **STA mode only** (AP / SoftAP / Wi-Fi Direct deferred).
- **WPA2-Personal only**; WPA3-SAE, EAP enterprise deferred.
- IP is read from `wpa_supplicant STATUS` output — no in-QEMU DHCP.
- TCP/IP data-plane forwarding is raw Ethernet over DMA buffers; it is not an
  RF/MAC/PHY simulation.
- Runtime tests need either a real host `wpa_supplicant` ctrl socket or
  `tools/mock_wpa_supplicant.py`.
- Only the ESP-IDF APIs used by the current demos/tests are implemented.
