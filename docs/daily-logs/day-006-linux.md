# Day 6 — NEXT-001 QEMU-native WS: VRAM-direct, Canvas Viewer, LVGL Test

**Date**: 2026-05-03
**Branch**: main
**Commits**: c09fea8, f798616, 180eae5

---

## Goals vs Achieved

| Goal | Status |
|------|--------|
| `web/qemu-direct.html` canvas viewer | ✅ Done |
| `tests/cdp/test_qemu_direct_canvas.py` Playwright test | ✅ Done |
| `test_ws_frame_looks_like_lvgl` Python test | ✅ Done |
| LVGL content actually appears in WS frames | ✅ Done |

---

## Key Discovery: `address_space_rw` vs `memory_region_get_ram_ptr`

### Root Cause
The Day 5 `broadcast_frame()` used `qemu_console_surface()` which returned
all-zeros because `rgb_update()` (which copies VRAM → surface) never fires
with `-display none`.

Day 6 fix attempt: switched to `address_space_rw(&s->vram_as, 0, ...)`.
But this also returned all-zeros!

### Why `address_space_rw` failed
In `esp32.c`, the machine maps `s->vram` into the system address space:
```c
memory_region_add_subregion_overlap(sys_mem, 0x20000000, &s->rgb.vram, 0);
```
This sets `s->vram->container = sys_mem` and triggers a QEMU-internal
flatview invalidation.  The flatview cache for `s->vram_as` (which has
`s->vram` as its root) becomes stale.  Subsequent `address_space_rw()`
calls recompute the flatview and encounter an inconsistent state, returning
zeros for all reads.

### Fix
Use `memory_region_get_ram_ptr(&s->vram)` which bypasses address-space
traversal entirely and returns the host-side pointer to the RAM backing:
```c
void *vram_raw = memory_region_get_ram_ptr(&s->vram);
memcpy(pixels, vram_raw, pixel_size);
```
This gives the live pixels as written by `qemu_vram_mirror()`.

### Verification
After the fix, the first received WS frame contained:
- `nonzero=32400` (240×135 = all LVGL pixels)
- `unique=90` distinct RGB565 colours (LVGL benchmark scene)

---

## Deliverables

### `tools/qemu-src-patches/hw/display/esp_rgb_ws.c`
- `broadcast_frame()`: replaced `address_space_rw()` with
  `memory_region_get_ram_ptr() + memcpy()`
- Pixel format stays `r5g6b5`, `stride_bytes = w*2 = 1600`
- Frame size: `800*600*2 = 960,000 bytes`

### `web/qemu-direct.html`
- Standalone WS canvas viewer (no npm/build required)
- Connects to `ws://127.0.0.1:{port}/` (port from `?port=9334`)
- Handles TEXT (JSON header) → resizes canvas
- Handles BINARY → decodes r5g6b5 or x8r8g8b8 → `putImageData`
- FPS counter + status indicator

### `tests/cdp/test_qemu_direct_canvas.py`
- Playwright test boots QEMU + HTTP server, opens viewer, waits 8 s
- Asserts canvas has non-blank pixels (`unique >= 8`, `sum > 0`)
- Saves screenshot to `artifacts/cdp-qemu-direct.png`

### `tests/test_qemu_ws_handshake.py`
- Added `test_ws_frame_looks_like_lvgl`
- Changed frame reception to loop until non-blank (safety net for fast CI)

---

## Test Results

| Suite | Passed | Skipped | Failed |
|-------|--------|---------|--------|
| WS tests only | 6 | 0 | 0 |
| All non-CDP | 50 | 13 | 1 (pre-existing) |
| CDP tests | 12 | 2 | 0 |
| **Total** | **62** | **15** | **1 (pre-existing)** |

Pre-existing failure: `test_vram_snapshot_matches_uart_dump` — serial log
`/tmp/esp32-qemu-serial.log` lacks `FB=` lines (requires prior `test_qemu_boot`
run to populate it).

---

## LVGL Boot Timeline (verified)

```
t=0.000  QEMU starts, WS listener binds (GLib timer starts)
t=0.500  First timer tick — LVGL not booted yet → blank frame
t=2.538  Firmware: lvgl flush #0 → qemu_vram_mirror() writes to VRAM
t=3.000  WS frame contains LVGL pixels (nonzero=32400, unique=90)
```

---

## Day 7 Plan

- [ ] Investigate `test_ws_dual_cli_parity` and `test_qemu_dual_cli_parity`
- [ ] Consider adding a `?wait_for_content=true` URL param to `qemu-direct.html`
      for polling until non-blank frame appears
- [ ] FB-012 feedback → update `docs/skill-feedback.md` (done below)
