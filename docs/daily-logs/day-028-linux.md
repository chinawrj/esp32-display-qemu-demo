# Day 028 - 2026-05-05 (Linux)

## Morning Planning

### Yesterday Review

- Completed: GAP-I `tcp_client` support reached end-to-end QEMU runtime with `Echo: Message from ESP32`.
- Completed: Day 27 commit `1cec474 feat(wifi): add GAP-I tcp_client support`.
- Completed: Non-runtime suite reached 148 passed, 6 skipped.
- Remaining: `wifi/scan` runtime smoke looked ambiguous because the generic runner reported station-style checks against a scan sample.

### Manager Message

Formal release requested after 6 days. Scope is basic STA/SCAN/AP, with tests
and repeatable release procedure. The six-day plan is now tracked in
`BACKLOG.md` under the PRIMARY-TARGET section.

### Today Goals

1. GAP-J / SCAN: fix scan-only event ordering so `WIFI_CMD_SCAN` posts `WIFI_EVT_SCAN_DONE` instead of falling through to connect setup.
2. TEST: add non-runtime tests for scan-only QEMU command flow and sample-aware verification expectations.
3. Runtime: rebuild local QEMU and re-run stock `wifi/scan`, then re-check station and softAP smoke paths if time permits.

### Risks And Dependencies

- QEMU source under `tools/qemu-src/` is ignored; durable changes must land in `tools/qemu-src-patches/` and local runtime validation needs a rebuild.
- Runtime checks depend on the local patched `qemu-system-xtensa` binary and tmux build/test windows.
- The release target is intentionally narrow: STA/SCAN/AP only. Avoid pulling UDP/ESPNOW into the release gate today.

### Acceptance Checkpoints

- [x] `tools/qemu-src-patches/hw/net/esp_wifi.c` keeps scan-only and connect flows separate.
- [x] Non-runtime tests cover scan-only flow and pass.
- [x] Local QEMU rebuild succeeds.
- [x] Stock `wifi/scan` serial output includes `Total APs scanned` and `SSID` / `QEMU_TEST`.
- [x] Stock `wifi/getting_started/station` passes `VERIFY_PROFILE=station`.
- [x] Stock `wifi/getting_started/softAP` passes `VERIFY_PROFILE=softap`.
- [ ] `git status --short` is clean after commit.

## Execution Notes

### GAP-J / SCAN Fix

Root cause: `WIFI_CMD_SCAN` reused the connect scan state machine. After
`SCAN_RESULTS`, the QEMU device continued into `ADD_NETWORK` instead of
posting `WIFI_EVT_SCAN_DONE`, so the stock scan sample could hang before
printing AP records.

Fix: added `ESPWifiState.scan_only`. `WIFI_CMD_SCAN` sets it, and the
`WPA_CONN_SCAN_RESULTS_SENT` handler now posts `WIFI_EVT_SCAN_DONE` and
returns to idle for scan-only calls. `WIFI_CMD_CONNECT` still continues into
`ADD_NETWORK`.

### Runtime Smoke Results

| Sample | Command profile | Result |
|--------|-----------------|--------|
| `wifi/scan` | `VERIFY_PROFILE=scan` | `4 check(s) passed, 0 failed`; `Total APs scanned = 1`, `SSID QEMU_TEST` |
| `wifi/getting_started/station` | `VERIFY_PROFILE=station` | `5 check(s) passed, 0 failed`; `got ip:10.0.2.15` |
| `wifi/getting_started/softAP` | `VERIFY_PROFILE=softap` | `3 check(s) passed, 0 failed`; `wifi_init_softap finished` |

### Test Notes

- Focused non-runtime: `15 passed` for QEMU scan-flow tests and runner profile tests.
- One scan profile run before the final successful run did not reach scan results; keep watching for timing flake during the Day 30 regression-suite work.