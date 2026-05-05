# Day 15 — NEXT-003 LVGL + Wi-Fi Integration Demo

**Date**: 2026-05-05  
**Branch**: main  
**Commit**: a80240c

---

## Goals

1. Integrate LVGL display and Wi-Fi into a single `main.c` demo (NEXT-003)
2. Show Wi-Fi connection status as an LVGL label overlay
3. Ensure firmware builds zero-warning with both LVGL + Wi-Fi subsystems active

---

## Work Done

### Architecture Decision: API-Level Wi-Fi Simulation

Key design principle reinforced: the `esp_wifi_qemu` component **simulates the public ESP-IDF Wi-Fi API** (`esp_wifi_init`, `esp_wifi_connect`, etc.), not the underlying ESP32 Wi-Fi hardware registers. The MMIO registers defined in `esp_wifi_qemu.h` at `WIFI_QEMU_BASE = 0x3ff75000` are our own invented firmware↔QEMU communication channel, deliberately constrained to offset `< 0x144` to avoid conflicting with the RNG device.

This means:
- Application code calls the same `esp_wifi_*` API as on real hardware
- Tests validate at the API/event level (`got ip:` in serial log)
- No attempt to replicate actual ESP32 Wi-Fi controller register behavior

### Files Changed

| File | Change |
|------|--------|
| `main/wifi_ui.c` | **NEW**: LVGL label overlay (`wifi_ui_init`, `wifi_ui_set_status`, `wifi_ui_tick`) |
| `main/include/wifi_ui.h` | **NEW**: Public API for wifi_ui module |
| `main/Kconfig.projbuild` | **NEW**: `DEMO_WIFI_SSID` (default `QEMU_TEST`) + `DEMO_WIFI_PASSWORD` |
| `main/main.c` | Added `demo_wifi_start()`, `demo_wifi_event_handler()`, `wifi_ui_init/tick` calls |
| `sdkconfig.defaults` | Added `CONFIG_ESP_WIFI_QEMU=y`, `CONFIG_DEMO_WIFI_SSID`, `CONFIG_DEMO_WIFI_PASSWORD` |
| `partitions.csv` | Custom partition table: 1.5 MB factory, 256 KB NVS |
| `sdkconfig` | Updated for custom partitions + Wi-Fi QEMU config |
| `components/esp_wifi_qemu/esp_wifi_shim.c` | Fix: `esp_wifi_start` timeout → `ESP_LOGW` + continue (not abort) |
| `tools/run-qemu.sh` | Added M3 banner check + FB payload verification |
| `tests/conftest.py` | Minor fixture cleanup |

### Wi-Fi Integration Flow

```
app_main()
  ├── lv_demo_benchmark()      ← runs for ~7s
  ├── wifi_ui_init()           ← creates LVGL label "Wi-Fi: connecting..."
  ├── LVGL loop (600 cycles)
  ├── demo_wifi_start()        ← esp_wifi_init + connect
  └── LVGL loop (100 cycles)   ← processes WIFI_EVENT/IP_EVENT callbacks
                                  wifi_ui_set_status("got ip:192.168.x.x")
```

### Key Fix: esp_wifi_start Timeout Handling

In QEMU without a live wpa_supplicant socket, `esp_wifi_start()` returns `ESP_ERR_TIMEOUT` (CMD_START takes 500ms, no device response). Changed from `ESP_ERROR_CHECK` (abort) to a `LOGW` + continue so the demo does not crash when run without network.

---

## Test Results

```
Build: idf.py build — zero warnings ✅
run-qemu.sh 75 verify: 10/10 checks pass ✅
pytest (non-CDP, non-QEMU-runtime): 65 passed, 15 skipped ✅
```

Baseline maintained: Day 14 had 94 passed (including QEMU-runtime wifi tests with IDF env); Day 15 same passing rate when IDF env is set.

---

## Tomorrow (Day 16)

Complete NEXT-003 acceptance criteria:

1. Create `tests/test_qemu_integrated_demo.py` — boots main firmware, mock wpa_supplicant, asserts `got ip:` + LVGL frame content
2. Update `tools/run-direct-demo.sh` — add mock-wpa-supplicant launch + `WIFI_CTRL_SOCKET` env
3. Mark NEXT-003 as DONE in `BACKLOG.md`
