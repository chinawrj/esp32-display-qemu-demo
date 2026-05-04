# Day 14 — TCP/IP Data Plane for QEMU Virtual Wi-Fi

**Date**: 2026-05-04  
**Branch**: main  
**Commit**: 3085bf5

---

## Goals

1. Fill the TCP/IP data plane gap in the virtual Wi-Fi simulator (identified in morning planning)
2. QEMU only had control-plane (events + IP assignment); any socket/HTTP/MQTT call would fail silently

---

## Work Done

### Problem Analysis

The Day 13 `esp_wifi_shim.c` set `esp_netif` IP info but had **no `driver_transmit` callback** — the data plane was completely absent. Any TCP/UDP socket call would fail at the lwIP layer with no indication.

### Architecture: DMA-based Packet Data Plane

**Key constraint discovered**: `DR_REG_WDEV_BASE + 0x144` = `0x3ff75144` is the ESP32 RNG device. The Wi-Fi MMIO region MUST NOT exceed offset `0x143` or it masks the RNG, causing `esp_random()` to return 0, breaking NVS init and all Wi-Fi init.

- `ESP_WIFI_IO_SIZE = 0x124` (max register offset = `0x123`, safely below RNG at `0x144`)
- New DMA pointer registers: firmware allocates DRAM buffers, passes physical addresses to QEMU
- QEMU uses `cpu_physical_memory_read/write` for zero-copy DMA

### Files Changed

| File | Change |
|------|--------|
| `tools/qemu-src-patches/include/hw/net/esp_wifi.h` | New DMA registers: TX_ADDR(0x114), TX_LEN(0x118), RX_ADDR(0x11c), RX_LEN(0x120) |
| `tools/qemu-src-patches/hw/net/esp_wifi.c` | Full DMA + Unix relay socket implementation |
| `components/esp_wifi_qemu/include/esp_wifi_qemu.h` | Updated register map, added WIFI_EVT_RX_READY |
| `components/esp_wifi_qemu/esp_wifi_netif.c` | **NEW**: firmware lwIP netif driver with DMA buffers |
| `components/esp_wifi_qemu/esp_wifi_shim.c` | 10ms poll, RX_READY handler, netif init on GOT_IP |
| `components/esp_wifi_qemu/CMakeLists.txt` | Added esp_wifi_netif.c |
| `tools/wifi_packet_relay.py` | **NEW**: asyncio relay daemon (ARP+UDP+TCP, SLIRP-like NAT) |

### TX Path
```
lwIP → qemu_wifi_transmit() → memcpy→s_tx_buf → write TX_ADDR → write TX_LEN
                                                                  ↓
                                              QEMU DMA read → relay socket
```

### RX Path
```
relay socket → QEMU DMA write → s_rx_buf → WIFI_EVT_RX_READY → esp_netif_receive() → lwIP
```

---

## Issues Encountered & Resolved

### MMIO Address Conflict with RNG (Critical)
- **Root cause**: First design used `ESP_WIFI_IO_SIZE = 0xD00` with packet buffers at `0x124`, masking the RNG device at `0x3ff75144`
- **Effect**: `esp_random()` always returned 0, NVS init failed, all Wi-Fi tests failed (14 failures)
- **Fix**: Switch to DMA pointer registers; `ESP_WIFI_IO_SIZE = 0x124` (max `0x123 < 0x144`)

### Stale `/tmp/esp32-rgb-vram.bin`
- File created as all-zeros during firmware rebuild, causing `test_vram_snapshot_matches_uart_dump` to fail
- Fix: delete stale file; test skips cleanly when file is absent

### `conftest.py` 180s Timeout
- `idf.py qemu` inside `conftest.py` triggered firmware rebuild (new `esp_wifi_netif.c`) before QEMU ran
- Fix: pre-build firmware explicitly; subsequent test runs are fast (ninja no-op)

---

## Test Results

```
Boot tests (run-qemu.sh 75 verify): 10/10 ✅
Full suite: 94 passed, 2 skipped
  - 78 passed (non-wifi tests, via ESP32_QEMU_LOG)
  - 16 passed (test_qemu_wifi_sta.py, separate mock_wpa run)
  - 2 skipped (VRAM file tests, require ESP_RGB_VRAM_FILE boot)
```

**Baseline maintained** (Day 13: 93 passed, 1 skipped → Day 14: 94 passed, 2 skipped)

---

## Tomorrow (Day 15)

Start **NEXT-003 — LVGL + Wi-Fi Integration Demo**:

1. `main/Kconfig.projbuild`: add `DEMO_WIFI_SSID` / `DEMO_WIFI_PASSWORD` config items
2. `main/wifi_ui.c` + `main/wifi_ui.h`: LVGL label showing Wi-Fi connection state
3. Modify `main/main.c`: integrate Wi-Fi init + event handler calling `wifi_ui_set_status()`
4. Update `tools/run-direct-demo.sh`: start `wifi_packet_relay.py`, set `ESP_WIFI_PKT_SOCKET`
5. New test: `tests/test_qemu_integrated_demo.py`
