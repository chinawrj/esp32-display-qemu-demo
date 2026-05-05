# Day 17 — Post NEXT-003 Hardening: Wi-Fi API-Simulation Docs

**Date**: 2026-05-05  
**Branch**: main  

---

## Morning Planning

### Yesterday (Day 16) Review
- Completed NEXT-003: LVGL + Wi-Fi integrated demo in QEMU.
- Added `tests/test_qemu_integrated_demo.py` with 8 source checks plus runtime tests gated on QEMU prerequisites.
- Updated `tools/run-direct-demo.sh` to launch `tools/mock_wpa_supplicant.py` and export `ESP_WIFI_CTRL_SOCKET`.
- Marked NEXT-003 done in `BACKLOG.md` and committed the work.
- Key architecture reminder: Wi-Fi is simulated at the public `esp_wifi_*` API/event layer, not by modeling ESP32 Wi-Fi hardware registers.

### Today Goals
1. Document the API-level Wi-Fi simulation boundary in `docs/qemu-wifi.md`.
2. Re-run focused source tests for the integrated demo after documentation hardening.
3. Identify the next implementation target after NEXT-001/002/003 completion.

### Risks and Dependencies
- Runtime QEMU tests still depend on the project-local patched QEMU binary and built flash images.
- Documentation must not describe the private MMIO mailbox as real ESP32 Wi-Fi register compatibility.
- Next-feature planning should preserve the no-real-hardware validation loop.

### Acceptance Checkpoints
- [x] `docs/qemu-wifi.md` states API simulation, not register simulation.
- [x] Focused non-runtime tests pass.
- [x] Day 17 log captures next-step recommendation.

---

## Execution Log

### Documentation hardening
- Updated `docs/qemu-wifi.md` from the old Day 8 "in progress" scaffold to the completed Day 17 architecture.
- Clarified that `components/esp_wifi_qemu/` implements public `esp_wifi_*` APIs and posts normal ESP-IDF events.
- Reframed the MMIO map as a private firmware<->QEMU mailbox, not a model of ESP32 Wi-Fi hardware registers.
- Added the Day 14 raw Ethernet DMA data-plane summary.

### Test Notes
- `pytest -q tests/test_qemu_integrated_demo.py::TestIntegratedDemoSources` — 8 passed in 0.70 s.

---

## Next Candidate Work

Recommended Day 17 continuation: harden runtime integration so `TestIntegratedDemo` is easier to run in CI by adding a proper QEMU boot fixture and clearer runtime prerequisite checks.

Alternative feature candidates:
- Improve the integrated LVGL Wi-Fi status UI with scan/connect/IP states.
- Add a new backlog item for SoftAP/API simulation.
- Add an MQTT demo that uses the existing STA path and validates app-level network behavior.
