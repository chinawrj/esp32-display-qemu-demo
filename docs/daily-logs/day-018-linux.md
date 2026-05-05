# Day 18 — lwIP Data-Plane Verification Plan

**Date**: 2026-05-05  
**Branch**: main  

---

## Morning Planning

### Previous Work Review
- Day 17 opened the post-NEXT-003 hardening track and updated `docs/qemu-wifi.md` to state the key architecture boundary: Wi-Fi is simulated at the public `esp_wifi_*` API/event layer, not as ESP32 Wi-Fi register emulation.
- The repository still has uncommitted documentation changes from Day 17.
- User question for Day 18: does lwIP over this virtual Wi-Fi network work now?

### Answer Snapshot

Short answer: **not accepted yet**.

The low-level data-plane plumbing exists:
- `components/esp_wifi_qemu/esp_wifi_netif.c` installs an `esp_netif` transmit path and injects RX frames into lwIP.
- `tools/qemu-src-patches/hw/net/esp_wifi.c` has DMA registers and connects to `ESP_WIFI_PKT_SOCKET`.
- `tools/wifi_packet_relay.py` implements a SLIRP-like relay for ARP, UDP, TCP, and limited ICMP.

But the current accepted tests mostly prove control plane (`got ip:`) rather than app-level socket traffic. `tools/run-direct-demo.sh` starts `tools/mock_wpa_supplicant.py`, but it does not start `tools/wifi_packet_relay.py` or export `ESP_WIFI_PKT_SOCKET`, so lwIP socket traffic is not part of the normal demo path yet.

### Today Goals
1. Clarify lwIP data-plane status in `docs/qemu-wifi.md`.
2. Re-run focused Wi-Fi source/mock tests to confirm control-plane coverage still passes.
3. Define the next acceptance slice: firmware socket client + host echo/HTTP server + packet relay + pytest runtime check.

### Risks and Dependencies
- Runtime validation needs the project-local patched QEMU binary and built firmware images.
- The packet relay may need protocol fixes once real lwIP TCP handshakes are exercised.
- Demo startup should manage both ctrl socket and packet socket processes cleanly.

### Acceptance Checkpoints
- [x] Docs distinguish implemented data-plane plumbing from accepted lwIP socket behavior.
- [x] Focused Wi-Fi source/mock tests pass.
- [x] Next implementation slice is explicit enough to execute.

---

## Test Notes

- `pytest -q tests/test_qemu_wifi_sta.py::TestSourceFiles tests/test_qemu_wifi_sta.py::TestMockWpaSupplicant` — 14 passed in 11.90 s.

---

## Proposed Next Slice

Add an app-level lwIP proof test:

1. Add a small firmware-side socket client path after `IP_EVENT_STA_GOT_IP`.
2. Start a host TCP echo or HTTP server bound to `127.0.0.1`.
3. Start `tools/wifi_packet_relay.py` and export `ESP_WIFI_PKT_SOCKET` before QEMU boots.
4. From firmware, connect to `10.0.2.100:<port>` and log a successful response.
5. Add pytest runtime assertion for that serial log line.

This would turn the answer from "plumbing exists" into "lwIP over virtual Wi-Fi is verified end to end".
