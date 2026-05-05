# Day 024 — Linux — P0 Stock Station Sample: Got IP ✅

**Date**: 2026-05-05
**Goal**: P0 stock station sample (`examples/wifi/getting_started/station/`) runs in QEMU without any source modifications. Verify `got ip:` in serial output.

---

## Morning Health Check

| Metric | Value | Status |
|--------|-------|--------|
| Compile warnings | 0 | ✅ |
| Non-runtime tests | 87 passed, 17 skipped | ✅ |
| TODO/FIXME count | <5 | ✅ |
| Last commit | 3d846d1 (Day 23) | ✅ |

---

## Tasks Completed

### GAP-G: Build System Injection (COMPLETE for P0)

**Problem**: `esp_wifi_qemu` component was never compiled into stock samples because nothing depends on it. `project_include.cmake` injection approaches all failed (too late in CMake pipeline).

**Solution**: Wrapper project approach in `build-stock-sample.sh`:
1. Generates `_qemu_wrap_<samplename>/` directory alongside the build dir
2. Creates `main/CMakeLists.txt` that lists stock sample `.c` files with ABSOLUTE paths
3. Adds `REQUIRES esp_wifi_qemu` — this is the critical injection point
4. Runs `idf.py` from the wrapper directory
5. Stock sample source files (`.c`/`.h`) are **never modified** — zero diff

**Key bug fixed**: `sdkconfig.defaults` was resolved as relative to wrapper dir instead of sample dir. Fixed by using absolute path.

**Verified**: `libesp_wifi_qemu.a` appears in build output at step 1013-1019/1029.

### run-stock-qemu.sh: Fixed Argument Names

Two bugs found and fixed:
1. `mock_wpa_supplicant.py` uses `--ctrl-path`, not `--socket`
2. `wifi_packet_relay.py` takes positional arg, not `--socket`

These caused `/tmp/stock-mock-wpa: No such file or directory` and QEMU state machine staying in UNINIT, causing `CMD_START in invalid state 0`.

### P0 Verification: `got ip:10.0.2.15` ✅

Stock station sample serial output (no source changes, only CMakeLists.txt wrapper):
```
I (3291) wifi_qemu: init (QEMU virtual Wi-Fi)
I (3291) wifi_qemu: start
I (4029) wifi_qemu: got ip:10.0.2.15
I (4039) esp_netif_handlers: sta ip: 10.0.2.15, mask: 255.255.255.0, gw: 10.0.2.2
I (4039) wifi station: got ip:10.0.2.15
I (4049) wifi station: connected to ap SSID:QEMU_TEST password:qemu1234
```

**Verification summary**: 4/5 checks pass (STA connected check improved to include "connected to ap" pattern).

### Non-critical Errors (GAP-F, non-blocking)

```
E wifi_netif: esp_wifi_internal_reg_rxcb for if=0 failed with 12289
E wifi_init_default: esp_wifi_internal_set_sta_ip failed with 12289
```
These are from the real wifi driver's `esp_wifi_internal_*` symbols being called. Return `ESP_ERR_NOT_SUPPORTED` (12289). Non-fatal — IP is delivered via MMIO path.

---

## PRIMARY TARGET Progress

| Sample | Status |
|--------|--------|
| `examples/wifi/getting_started/station/` | ✅ **got ip:10.0.2.15** |
| `examples/wifi/scan/` | 🔴 not tried |
| `examples/wifi/getting_started/softAP/` | 🔴 not tried (GAP-B) |

---

## Remaining Gaps (for Day 25+)

- **GAP-F**: `esp_wifi_internal_reg_rxcb` / `esp_wifi_internal_set_sta_ip` return 12289. These should be properly stubbed to avoid log noise. Could cause issues in more complex scenarios.
- **GAP-A remainder**: `esp_wifi_set_csi` / `_set_csi_config` / `_set_csi_rx_cb` not stubbed
- **GAP-B**: SoftAP mode entirely absent
- **GAP-I**: No DHCP server; static IP (10.0.2.15) injected by mock STATUS response

---

## Metrics

- Compile warnings: 0
- Non-runtime tests: 87 passed, 17 skipped, 0 failed
- P0 samples green: 1/2 (station ✅, scan pending)
