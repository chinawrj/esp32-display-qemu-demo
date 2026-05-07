# Day 034 — 2026-05-07 Linux

## Goal

Fix all runtime test regressions introduced by Day 33 work.  Three bugs were
outstanding at the start of the session; all three were root-caused and fixed.

---

## Bugs fixed

### 1. `wifi_ui_tick()` — dangling `s_label` pointer (LoadProhibited crash)

**Symptom** `test_got_ip_with_mock_ap` showed the QEMU device receiving 28+
ATTACH→STATUS→DETACH cycles; addr2line decoded the crash to:

```
0x400d9992: wifi_ui_tick at main/wifi_ui.c:34
  -> lv_label_set_text -> lv_free -> lv_tlsf_block_size -> LoadProhibited
EXCVADDR: 0x00000060  (NULL + 0x60 dereference)
```

**Root cause** `s_label` is created as a child of `lv_screen_active()` inside
`wifi_ui_init()`.  The LVGL benchmark (`lv_demo_benchmark()`) eventually
destroys the active screen's children.  The post-benchmark 100-cycle LVGL loop
in `app_main` continued calling `wifi_ui_tick()` → `lv_label_set_text(s_label,
…)` on the now-dangling pointer.

**Fix** `main/wifi_ui.c`:
- `lv_obj_null_on_delete(&s_label)` in `wifi_ui_init()` — LVGL registers a
  DELETE event that automatically sets `s_label = NULL` when the object is
  freed.
- `s_label &&` guard in `wifi_ui_tick()` — now a clean NULL-check suffices.

### 2. `low_level_output` — NULL `driver_transmit_wrap` (InstrFetchProhibited)

**Symptom** After the LoadProhibited fix, a second crash appeared:

```
PC: 0x00000000, A10: 0xdeadbeef
low_level_output -> esp_netif_transmit_wrap -> (NULL)()
```

**Root cause** `esp_netif_transmit_wrap()` (IDF lwIP netif glue) unconditionally
calls `esp_netif->driver_transmit_wrap(...)`.  Our `s_driver_cfg` had
`.transmit_wrap = NULL`.  The moment lwIP tried to TX a packet (TCP SYN from
the lwip_probe task), it crashed.

**Fix** `components/esp_wifi_qemu/esp_wifi_netif.c`:
- Added `qemu_wifi_transmit_wrap()` — thin wrapper that calls
  `qemu_wifi_transmit()` ignoring the `pbuf` argument.
- Set `.transmit_wrap = qemu_wifi_transmit_wrap` in `s_driver_cfg`.

### 3. `wifi_packet_relay.py` — ARP ignored for `10.0.2.100` (probe connect hangs)

**Symptom** `test_lwip_probe_ok_in_serial` timed out at 360 s; "lwip probe ok:"
never appeared.  `got_ip=True` confirmed the control plane worked; the probe
task's `connect()` blocked indefinitely.

**Root cause** The relay's `handle_arp()` only replied to ARP Who-Has queries
for `GATEWAY_IP = "10.0.2.2"`.  The probe target `10.0.2.100` is in the same
`/24` subnet as the firmware (`10.0.2.15/24`), so lwIP ARPs directly for
`10.0.2.100` rather than routing via the gateway.  That ARP was silently
dropped; `connect()` never received a SYN-ACK.

**Fix** `tools/wifi_packet_relay.py`:
- `handle_arp()` now also responds to ARP requests for any IP present in
  `LOCAL_HOST_MAP` (which includes `10.0.2.100`).

---

## Test results

```
213 passed, 18 skipped, 0 failed  (198 s)
```

Includes `test_qemu_lwip_probe.py::TestLwipProbeRuntime::test_lwip_probe_ok_in_serial`
which previously timed out at 360 s; now passes in ~12 s.

---

## Files changed

| File | Change |
|------|--------|
| `main/wifi_ui.c` | `lv_obj_null_on_delete` + NULL guard in `wifi_ui_tick` |
| `components/esp_wifi_qemu/esp_wifi_netif.c` | `qemu_wifi_transmit_wrap` + wire into `s_driver_cfg` |
| `tools/wifi_packet_relay.py` | ARP reply for `LOCAL_HOST_MAP` IPs |
| `tests/conftest.py` | timeout 250 → 300 s (from Day 33 session, uncommitted) |
| `tests/test_qemu_integrated_demo.py` | Popen+readline + `-nographic` (from Day 33 session, uncommitted) |
