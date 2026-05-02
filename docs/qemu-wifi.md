# QEMU Virtual Wi-Fi — Architecture & Protocol Spec (NEXT-002)

Status: **In progress** — Day 8 scaffold (protocol spec + component skeleton).
Full implementation target: Days 9–13.

---

## 1. Overview

NEXT-002 adds a virtual Wi-Fi STA device to the Espressif QEMU fork so that
ESP-IDF Wi-Fi applications run unmodified in the emulator.  The device bridges
QEMU's memory-mapped I/O (MMIO) interface with the host's
`wpa_supplicant` daemon via its Unix-domain ctrl socket.

```
  ESP-IDF firmware (unmodified)
       │  esp_wifi_* API calls
       ▼
  Component: esp_wifi_qemu  (this repo, components/)
       │  MMIO reads/writes to 0x3ff75000 (DR_REG_WDEV_BASE)
       ▼
  QEMU device: esp_wifi   (tools/qemu-src/hw/net/esp_wifi.c)
       │  Unix domain socket (async, non-blocking)
       ▼
  Host wpa_supplicant  (must be running; ctrl socket path configurable)
       │
       ▼
  Host Wi-Fi NIC  ←→  Access Point
```

### Why this approach

- `DR_REG_WDEV_BASE = 0x3ff75000` is the real ESP32 Wi-Fi peripheral base.
  Using the same address means the Xtensa MMU mapping in the firmware binary
  does not need to change.
- All I/O is synchronous from the firmware's perspective (MMIO reg read/write);
  the QEMU device handles async wpa_supplicant communication internally using
  QEMU's GLib main loop (same pattern as `esp_rgb_ws.c`).
- `CONFIG_ESP_WIFI_QEMU=y` in sdkconfig redirects `esp_wifi_*` to our stub
  component at compile time; unmodified release firmware keeps using the real
  blob driver.

---

## 2. MMIO Register Map

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

### Total MMIO size: 0x118 bytes

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
| `esp_wifi_set_config(IF_STA, cfg)` | Write SSID/PASS to MMIO registers |
| `esp_wifi_connect()` | Write `CMD_CONNECT`; wait `EVT_CONNECTED` |
| `esp_wifi_scan_start()` | Write `CMD_SCAN`; wait `EVT_SCAN_DONE` |
| `esp_wifi_scan_get_ap_records()` | Read `WIFI_SCAN_COUNT`, iterate `WIFI_SCAN_IDX` |
| `esp_wifi_get_mac()` | Write `CMD_GET_MAC`; read `WIFI_MAC` registers |
| `esp_wifi_deinit()` | Write `CMD_DEINIT` |
| `esp_wifi_stop()` | Write `CMD_STOP`; wait `EVT_STOP_DONE` |
| `esp_wifi_disconnect()` | Write `CMD_DISCONNECT`; wait `EVT_DISCONNECTED` |

IRQ delivery: the virtual device asserts `GPIO 0` (or a dedicated IRQ line —
TBD in Day 9 implementation) when `WIFI_EVENT ≠ 0` and the corresponding bit
in `WIFI_IRQ_ENABLE` is set.  The component ISR reads `WIFI_EVENT`, posts the
corresponding `esp_event_loop` event, then writes 0 to acknowledge.

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
| `components/esp_wifi_qemu/esp_wifi_shim.c` | `esp_wifi_*` API stubs |
| `sdkconfig.defaults` | `CONFIG_ESP_WIFI_QEMU=y` for QEMU builds |
| `tests/test_qemu_wifi_sta.py` | Automated integration test |
| `docs/qemu-wifi.md` | This document |

---

## 9. Acceptance Criteria

- [ ] `bash tools/build-qemu.sh` compiles `qemu-system-xtensa` with the
      `esp_wifi` device (zero errors, zero new warnings).
- [ ] `examples/wifi_sta/main/app_main.c` (copied from ESP-IDF examples,
      not modified) boots in QEMU and prints `got ip:`.
- [ ] `pytest -q tests/test_qemu_wifi_sta.py` passes on Linux with a
      running `wpa_supplicant` (skips otherwise).
- [ ] Full existing test suite (62 passed) has zero regressions.
- [ ] Real ESP32-C3/C6 build with `CONFIG_ESP_WIFI_QEMU=n` (default)
      introduces zero new code or binary size change.

---

## 10. Known Limitations (v1 scope)

- **STA mode only** (AP / SoftAP / Wi-Fi Direct deferred).
- **WPA2-Personal only**; WPA3-SAE, EAP enterprise deferred.
- IP is read from `wpa_supplicant STATUS` output — no in-QEMU DHCP.
- `lwIP` data-plane not emulated in v1; only control-plane events verified.
- Requires host `wpa_supplicant` running and reachable ctrl socket.
