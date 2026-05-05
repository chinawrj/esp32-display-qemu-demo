# Day 19 - NEXT-004 lwIP Socket Proof Planning

**Date**: 2026-05-05  
**Branch**: main  

---

## Morning Planning

### Previous Work Review
- Day 17 clarified the Wi-Fi simulator architecture: public `esp_wifi_*` API/event simulation, not ESP32 Wi-Fi hardware register simulation.
- Day 18 answered the lwIP question: data-plane plumbing exists, but app-level TCP/UDP socket behavior is not accepted yet.
- Current worktree already contains uncommitted Day 17 and Day 18 documentation updates.

### Today Focus

Day 19 starts NEXT-004: prove lwIP socket traffic over QEMU virtual Wi-Fi.

The target is intentionally narrow: one firmware TCP socket request, one host response through `tools/wifi_packet_relay.py`, and one serial assertion such as `lwip probe ok:`.

### Today Goals
1. Add NEXT-004 to `BACKLOG.md` with concrete subtasks and acceptance criteria.
2. Inspect the current firmware/QEMU/relay interfaces before coding the socket probe.
3. Prepare the implementation path for a runtime test that starts mock wpa_supplicant, packet relay, host echo/HTTP server, and QEMU.

### Risks and Dependencies
- Runtime verification requires the project-local patched QEMU binary and built flash images.
- `tools/run-direct-demo.sh` must manage one more long-lived process (`wifi_packet_relay.py`) without leaving stale sockets.
- The relay may expose protocol bugs once real lwIP TCP handshakes are exercised.
- Keep the simulation boundary at the public API/event level; the private MMIO mailbox remains a transport, not a hardware register model.

### Acceptance Checkpoints
- [x] NEXT-004 backlog entry exists.
- [ ] Firmware socket probe design is finalized.
- [ ] Runtime test harness design is finalized.
- [ ] Focused non-runtime tests pass after changes.

---

## Initial Implementation Plan

1. Add Kconfig options:
   - `DEMO_LWIP_PROBE_ENABLE`
   - `DEMO_LWIP_PROBE_HOST` default `10.0.2.100`
   - `DEMO_LWIP_PROBE_PORT`

2. Add a small `main/lwip_probe.c` module:
   - runs after `IP_EVENT_STA_GOT_IP`;
   - opens a TCP socket with lwIP BSD sockets;
   - sends a small payload;
   - logs `lwip probe ok:` on expected response.

3. Update the demo/test harness:
   - start `tools/wifi_packet_relay.py` with a temporary Unix stream socket;
   - export `ESP_WIFI_PKT_SOCKET` before QEMU starts;
   - start a tiny host TCP server on localhost;
   - assert serial output contains `got ip:` and `lwip probe ok:`.

---

## Notes

- This work answers the user's Day 18 question with a real acceptance test instead of only a code-path inspection.
- NEXT-004 should remain small. MQTT, OTA, SoftAP, and UDP can be separate follow-up items after TCP is proven.
