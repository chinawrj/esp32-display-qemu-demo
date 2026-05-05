# Day 030 - 2026-05-05 (Linux)

## Morning Planning

### Yesterday Review

- Completed: Day 29 hardened AP/APSTA start and stop event behavior.
- Completed: GAP-B tests expanded for APSTA and softAP verification profile.
- Completed: Stock softAP rebuild and runtime passed.

### Today Goals

1. Release regression: add one command that rebuilds and runs the basic STA/SCAN/AP stock samples.
2. TEST: add non-runtime coverage for the new release smoke gate.
3. Runtime: run the new gate through tmux and record station, scan, and softAP results.

### Risks And Dependencies

- The smoke gate runs multiple QEMU boots, so it is slower than the normal non-runtime suite.
- It depends on `IDF_PATH` or a local `~/esp-idf/export.sh` source step.
- Keep the gate scoped to basic release targets only: station, scan, and softAP.

### Acceptance Checkpoints

- [x] `tools/run-basic-wifi-smoke.sh` builds station, scan, and softAP stock wrappers.
- [x] The same command runs all three samples with `VERIFY_PROFILE=station|scan|softap`.
- [x] Non-runtime tests cover the smoke gate script.
- [x] Runtime smoke gate passes all three samples.
- [x] Full non-runtime suite passes.
- [ ] `git status --short` is clean after commit.

## Execution Notes

### Release Smoke Gate

Added `tools/run-basic-wifi-smoke.sh`, a narrow release gate for the basic
Wi-Fi scope. It builds and runs these stock samples:

| Sample | Verify profile |
|--------|----------------|
| `wifi/getting_started/station` | `station` |
| `wifi/scan` | `scan` |
| `wifi/getting_started/softAP` | `softap` |

Each sample writes separate build, run, and serial logs under `LOG_DIR`.

### Scan Robustness

The first smoke-gate run surfaced the known intermittent scan miss again:
station and softAP passed, but scan did not reach its AP-record print loop.
`esp_wifi_scan_start()` now handles blocking scans directly by polling both
`WIFI_EVT_SCAN_DONE` and `WIFI_REG_SCAN_COUNT`, so a populated MMIO scan table
can complete the stock blocking scan even if the single event register races.

### Results

- Focused smoke-gate tests: `4 passed`.
- Runtime smoke gate: `3 passed, 0 failed`.
- Full non-runtime suite: `158 passed, 6 skipped`.

Runtime command used:

```bash
LOG_DIR=/tmp/day30-basic-wifi-smoke2 bash tools/run-basic-wifi-smoke.sh 60
```