# Day 033 - 2026-05-06 (Linux)

## Morning Planning

### Yesterday Review

- Completed: Day 32 documentation freeze — `docs/qemu-wifi-stock-samples.md` covering station, scan, softAP.
- Completed: Non-runtime test coverage for documentation contract (4 new tests).
- Completed: Runtime smoke gate `3 passed, 0 failed` for station + scan + softAP.
- Completed: Full non-runtime suite `165 passed, 6 skipped`.

### Health Check

| Metric | Value | Threshold | Status |
|--------|-------|-----------|--------|
| Compile warnings | 0 | ≥3 | ✅ |
| Largest file (`esp_wifi_extras.c`) | 348 lines | 300 | ⚠️ Refactor trigger |
| `esp_wifi_shim.c` | 270 lines | 250 | ⚠️ Near warning |
| TODO/FIXME count | 0 | ≥5 | ✅ |
| Non-runtime tests collected | 217 | — | ✅ |

**Refactor trigger fired**: `esp_wifi_extras.c` is 348 lines. Split off `esp_wifi_ap.c`-adjacent extras and any scan-related helpers.

### PRIMARY TARGET Check

> Any step must get closer to stock ESP-IDF Wi-Fi sample drop-in compat.

| Sample | Status |
|--------|--------|
| P0 `wifi/getting_started/station/` | ✅ DONE (Day 24) |
| P0 `wifi/scan/` | ✅ DONE (Day 25) |
| P1 `wifi/getting_started/softAP/` | ✅ DONE (Day 26) |
| P1 `protocols/sockets/tcp_client/` | ✅ DONE (Day 27) — built, verify exists |
| **P1 `protocols/sockets/udp_client/`** | ❌ **TODAY** |
| P2 `wifi/iperf/` | 🔲 Not started |
| P2 `wifi/power_save/` | 🔲 Not started |
| P2 `wifi/espnow/` | 🔲 Not started |

### Today Goals

1. **Refactor `esp_wifi_extras.c`** (348 lines → split, zero-warning, tests still green).
2. **P1 udp_client**: Build `$IDF_PATH/examples/protocols/sockets/udp_client/` via QEMU Wi-Fi component.
3. **P1 udp_client**: `udp_echo_server.py` + `udp_client` verify profile + tests + smoke gate entry.

### Risks And Dependencies

- UDP in QEMU user-net: QEMU `-nic user` SLIRP stack supports UDP (`sendto`/`recvfrom`), so socket-level UDP should work without QEMU changes.
- `udp_client` connects to `10.0.2.2:<port>` (QEMU gateway) — same pattern as tcp_client. QEMU SLIRP routes this to host port via `hostfwd=udp`.
- Refactor must be zero-functionality-change (only split file).

### Acceptance Checkpoints

- [ ] `esp_wifi_extras.c` ≤ 300 lines after refactor, zero compile warnings.
- [ ] `udp_client` builds without source modification (only `CMakeLists.txt` wrapper + sdkconfig defaults).
- [ ] `VERIFY_PROFILE=udp_client bash tools/run-stock-qemu.sh $IDF_PATH/examples/protocols/sockets/udp_client/build_qemu 60` passes.
- [ ] New tests in `test_gap_i_tcp.py` (or `test_gap_i_udp.py`) cover the verify profile and echo server.
- [ ] `run-basic-wifi-smoke.sh` extended (or new `run-p1-wifi-smoke.sh`) includes udp_client.
- [ ] Full non-runtime suite passes (target: ≥165 passed).
- [ ] Day 33 wrap-up commit on `main`.

## Execution Notes

<!-- filled in during the day -->

## Verification

<!-- filled in at end of day -->

## Wrap-up

<!-- filled in at end of day -->
