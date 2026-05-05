# Day 029 - 2026-05-05 (Linux)

## Morning Planning

### Yesterday Review

- Completed: Day 28 fixed stock scan by separating scan-only QEMU flow from connect setup.
- Completed: Added sample-aware `run-stock-qemu.sh` verification profiles.
- Completed: Runtime gates passed for station, scan, and softAP.
- Remaining: AP support is still deliberately minimal; today should harden AP event behavior and tests for release confidence.

### Today Goals

1. GAP-B / AP: harden AP and APSTA start/stop event behavior without adding non-release features.
2. TEST: expand GAP-B non-runtime coverage for APSTA and verification profiles.
3. Runtime: re-run stock softAP and station/scan smoke checks if the AP event path changes.

### Risks And Dependencies

- Keep release scope narrow: basic STA/SCAN/AP only.
- AP client association, DHCP server, and `IP_EVENT_AP_STAIPASSIGNED` remain out of scope unless required by the stock softAP sample.
- Avoid changes that make stock samples depend on custom source edits.

### Acceptance Checkpoints

- [x] `esp_wifi_start()` emits AP start behavior for both `WIFI_MODE_AP` and `WIFI_MODE_APSTA`.
- [x] `esp_wifi_stop()` emits AP stop behavior for both `WIFI_MODE_AP` and `WIFI_MODE_APSTA`.
- [x] GAP-B tests cover APSTA event handling and softAP verification profile.
- [x] Non-runtime regression suite passes.
- [x] Stock softAP runtime still passes `VERIFY_PROFILE=softap`.
- [ ] `git status --short` is clean after commit.

## Execution Notes

### GAP-B / APSTA Hardening

`esp_wifi_start()` and `esp_wifi_stop()` now compute `ap_enabled` and
`sta_enabled` from the selected Wi-Fi mode. This keeps pure AP mode local to
the shim, while APSTA emits AP events and still starts/stops the QEMU STA
device path.

### Test Results

- Focused GAP-B: `18 passed, 1 skipped`.
- Full non-runtime suite: `153 passed, 6 skipped`.
- Stock softAP rebuild: `SOFTAP_BUILD:0`.
- Stock softAP runtime: `3 check(s) passed, 0 failed`; `wifi_init_softap finished`.

### Release Notes

AP client association and AP DHCP remain out of scope for the six-day basic
STA/SCAN/AP release. Today only hardens mode/event behavior needed for stock
softAP and APSTA compatibility.