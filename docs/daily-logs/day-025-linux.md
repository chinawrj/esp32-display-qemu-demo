# Day 025 — 2025-01-26 (Linux)

## Goals
1. GAP-F: stub `esp_wifi_internal_*` symbols (netif glue)
2. GAP-A: add CSI stubs
3. Fix linker bug discovered while testing P0 scan sample
4. Run P0 scan sample in QEMU (zero source changes)
5. Add non-runtime test coverage for all new stubs
6. Re-verify P0 station after linker fix

## Summary

### 1. GAP-F — `esp_wifi_internal_*` stubs (NEW: `esp_wifi_internal.c`)

Created `components/esp_wifi_qemu/esp_wifi_internal.c` with 8 stubs:
- `esp_wifi_internal_reg_rxcb` → ESP_OK (QEMU uses MMIO path)
- `esp_wifi_internal_set_sta_ip` → ESP_OK (no-op, IP from mock STATUS)
- `esp_wifi_internal_free_rx_buffer` → void no-op
- `esp_wifi_internal_reg_netstack_buf_cb` → ESP_OK
- `esp_wifi_internal_tx` → 0 (no-op, MMIO handles TX)
- `esp_wifi_internal_update_mac_time` → ESP_OK
- `esp_wifi_internal_set_log_level` → ESP_OK
- `esp_wifi_internal_set_log_mod` → ESP_OK

### 2. GAP-A — CSI stubs (same file)

Three stubs all return `ESP_ERR_NOT_SUPPORTED`:
- `esp_wifi_set_csi_rx_cb`
- `esp_wifi_set_csi_config`
- `esp_wifi_set_csi`

### 3. Critical Linker Fix — `--whole-archive`

**Root cause**: `--allow-multiple-definition` alone was insufficient. The linker
only pulls in objects from a static library when there is a pending undefined
reference to a symbol in that object. If `libnet80211.a` was already processed
before our stubs were needed, `libnet80211` won, and our stub was silently
ignored.

**Symptom**: `esp_wifi_get_mac failed with 12289` in the scan sample. `nm` and
`.map` file confirmed libnet80211 providing the symbol at a different address.

**Fix** in `CMakeLists.txt`:
```cmake
target_link_options(${COMPONENT_LIB} INTERFACE
    "-Wl,--whole-archive"
    "$<TARGET_FILE:${COMPONENT_LIB}>"
    "-Wl,--no-whole-archive"
    "-Wl,--allow-multiple-definition")
```

`--whole-archive` forces ALL objects in our library into the link, so our stubs
win regardless of link order. Verified with `objdump -d` confirming our stub
code at the final linked address.

### 4. P0 Scan Sample — QEMU Run

```
Total APs scanned = 1, actual AP number ap_info holds = 1
SSID: QEMU_TEST
RSSI: -50
Channel: 1
```

Zero source code changes to the stock sample. Only wrapper CMakeLists.txt + sdkconfig.

`run-stock-qemu.sh` updated with `SKIP_CONNECTED=1` env var for scan-only samples.

### 5. P0 Station — Rebuilt with `--whole-archive`

Station rebuilt after CMakeLists.txt fix. Map file now shows our stub at
the final address (not libnet80211). `got ip:10.0.2.15` confirmed.

### 6. Test Coverage — `tests/test_stock_sample_build.py`

40 new non-runtime tests:
- Script existence (build-stock-sample.sh, run-stock-qemu.sh)
- CMakeLists.txt uses `--whole-archive` and `--allow-multiple-definition`
- All 6 source files registered in CMakeLists.txt
- GAP-A symbols present in esp_wifi_extras.c / esp_wifi_internal.c (22 symbols)
- GAP-F symbols present in esp_wifi_internal.c (7 symbols)
- Build artifact existence (ELF files, map files)
- Map file: non-zero address entry comes from libesp_wifi_qemu not libnet80211

**All 40 pass.** Full non-runtime suite: 127 passed, 17 skipped, 0 failed.

## Commit

`01d58d4` — feat(wifi): Day 25 — GAP-A/F stubs + --whole-archive linker fix + scan sample ✅

## Status

| Stock Sample | Build | QEMU Run | Notes |
|---|---|---|---|
| `wifi/getting_started/station` | ✅ | ✅ `got ip:10.0.2.15` | P0 — Day 24+25 |
| `wifi/scan` | ✅ | ✅ SSID: QEMU_TEST | P0 — Day 25 |
| `wifi/getting_started/softAP` | ❌ | ❌ | P1 — GAP-B missing |
| `protocols/sockets/tcp_client` | ❌ | ❌ | P1 — GAP-I (DHCP) |

## Day 26 Plan

- **GAP-B**: SoftAP mode — esp_wifi_ap_* stubs + DHCP server emulation in QEMU device
- **GAP-I**: DHCP server for tcp_client (relay needs to hand out IP to external clients)
- **P1**: Build + run `wifi/getting_started/softAP` with zero source changes
- **P1**: Build + run `protocols/sockets/tcp_client` basic connectivity test
