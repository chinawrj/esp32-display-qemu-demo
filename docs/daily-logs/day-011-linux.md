# Day 11 — ESP-IDF Event Dispatch & esp_netif Binding

**Date**: 2025-07-17  
**Session**: Day 11  
**Milestone**: NEXT-002 (QEMU Wi-Fi STA support)  
**Commit**: f14e3aa

---

## Goals for Today

- [x] Fix CONNECTED/GOT_IP race condition in QEMU device (g_timeout_add 300ms)
- [x] Implement `wifi_event_task()` for async ESP-IDF event dispatch
- [x] `esp_wifi_start/stop` post `WIFI_EVENT_STA_START/STOP` events
- [x] `esp_wifi_connect/disconnect` made non-blocking (fire & forget)
- [x] `esp_wifi_init` spawns event task; `esp_wifi_deinit` deletes it
- [x] GOT_IP handler sets `esp_netif` IP info and posts `IP_EVENT_STA_GOT_IP`
- [x] `examples/wifi_sta/` created with official station example (app_main.c unmodified)
- [x] QEMU rebuilt (ninja incremental, 0 errors)
- [x] Firmware builds with zero warnings
- [x] 65 passed, 15 skipped, 0 failed

---

## What Was Done

### QEMU Device Fix (tools/qemu-src-patches/hw/net/esp_wifi.c)

Added `esp_wifi_post_got_ip_cb()` forward declaration and changed
`WPA_CONN_GETTING_STATUS` handler to post CONNECTED immediately, then schedule
GOT_IP via `g_timeout_add(300, ...)`. This prevents GOT_IP from immediately
overwriting the CONNECTED event register before firmware can ACK it.

### Shim Updates (components/esp_wifi_qemu/esp_wifi_shim.c)

Added `wifi_event_task()` FreeRTOS task that polls `WIFI_REG_EVENT` every 50ms:

| Event | ESP-IDF posting |
|-------|----------------|
| `WIFI_EVT_CONNECTED` | `WIFI_EVENT_STA_CONNECTED` with ssid/auth info |
| `WIFI_EVT_GOT_IP` | reads MMIO IP/mask/gw, sets netif, posts `IP_EVENT_STA_GOT_IP` |
| `WIFI_EVT_DISCONNECTED` | `WIFI_EVENT_STA_DISCONNECTED` with reason |
| `WIFI_EVT_SCAN_DONE` | `WIFI_EVENT_SCAN_DONE` |

API changes:
- `esp_wifi_init()`: starts `wifi_evt` task after INIT_DONE
- `esp_wifi_deinit()`: deletes task before DEINIT
- `esp_wifi_start()`: posts `WIFI_EVENT_STA_START` after START_DONE
- `esp_wifi_stop()`: posts `WIFI_EVENT_STA_STOP` after STOP_DONE
- `esp_wifi_connect()`: non-blocking, writes CMD, returns ESP_OK immediately
- `esp_wifi_disconnect()`: non-blocking, writes CMD, returns ESP_OK immediately

### Example (examples/wifi_sta/)

Copied the official `examples/wifi/getting_started/station/main/station_example_main.c`
verbatim as `examples/wifi_sta/main/app_main.c`. Created CMakeLists.txt files
and `sdkconfig.defaults` enabling `CONFIG_ESP_WIFI_QEMU=y`.

---

## Test Results

```
65 passed, 15 skipped, 0 failed in 27.60s
```

Baseline maintained. No regressions.

---

## NEXT-002 Remaining Criteria

- [ ] End-to-end test: `examples/wifi_sta` built + run in QEMU + prints `got ip:` (requires
  building the example project separately with esp_wifi_qemu component in scope)
- [ ] `pytest -q tests/test_qemu_wifi_sta.py` with live wpa_supplicant or mock daemon
  (currently 1 test skipped due to `WIFI_SSID` env var)

## Tomorrow (Day 12)

1. Build `examples/wifi_sta/` and run it in QEMU with the mock wpa_supplicant
2. Update `tests/test_qemu_wifi_sta.py` to use mock daemon for `test_qemu_wifi_sta_got_ip`
3. Close NEXT-002 once `got ip:` appears in QEMU serial output
