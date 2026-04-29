# QEMU native framebuffer integration — investigation

Status: design / research note for `cdp-phase5-qemu-native-fb`. Host-side
slice for `qemu-fb-shmem-bridge` landed Day 16 (see "Concrete next slice").

## Background

Today (Day 13) the LVGL framebuffer reaches Chrome via two host-side paths:

1. **UART base64 dump** (`tools/decode-fb.py`) — single-shot snapshot
2. **Log-replay** (`tools/fb_server/log_producer.py`) — loops the same single
   capture into the WS bridge

Both go through the existing serial UART → host file → host parser stack. They
don't touch any actual QEMU display backend; the firmware is what generates
the bytes by reading LVGL's render buffer in `flush_cb`.

The next milestones diverge into two bridges:

| Bridge | Approach | Pros | Cons |
|---|---|---|---|
| `cdp-phase2b-realtime-push` | Firmware opens TCP/chardev to host; pushes dirty rects every flush | No QEMU change, works on prebuilt binaries | Adds firmware code; consumes guest CPU |
| `qemu-fb-shmem-bridge` | QEMU exposes the framebuffer memory to host via POSIX shm / memory-backend-file | Zero guest overhead, true peripheral emulation | Requires custom QEMU build (we have one in flight on Day 14) |
| `cdp-phase5-qemu-native-fb` (this doc) | Use upstream `esp_lcd_qemu_rgb` + QEMU's built-in display backend | Most "official" path | Requires upstream `esp_lcd_qemu_rgb` driver and a real LCD peripheral model in QEMU; current ESP32 model has none |

## Current QEMU display surface for ESP32

The Espressif fork of QEMU (branch `esp-develop-based-on-9.2.2`) does
include some display peripheral models for newer chips (e.g. ESP32-P4 RGB
panel) but **not for ESP32**. The ESP32 target has no LCD controller in QEMU
— our project sidesteps this by rendering LVGL into a plain RAM buffer and
shipping it out over UART. That's why screenshot capture is currently
firmware-driven.

Implications:
- `esp_lcd_qemu_rgb` is intended for chips whose QEMU model exposes a
  framebuffer device. ESP32 isn't one yet.
- A "native" path on ESP32 needs *either* a new device model in QEMU, *or*
  the firmware-side shmem trick described in `qemu-fb-shmem-bridge`.

## Recommended path

Short-term: **`qemu-fb-shmem-bridge`** wins because it requires only a small
QEMU patch (or even a chardev) to expose the LVGL buffer host-side — the
firmware doesn't have to do anything different from today.

Mid-term: **`cdp-phase2b-realtime-push`** as a pure-firmware fallback when
the user can't run our patched QEMU.

Long-term: **`cdp-phase5-qemu-native-fb`** when a real ESP32 LCD model lands
upstream. Track Espressif's QEMU roadmap; revisit when that materialises.

## Concrete next slice (host side: ✅ Day 16; QEMU device: deferred)

Once a custom QEMU is up (Day 14 build):

1. Add a tiny QEMU device "esp32-fb" backed by a `memory-backend-file`
2. Firmware writes the LVGL buffer to a fixed MMIO address each flush (no
   change to user code; happens inside `flush_cb`)
3. Host `fb_server` mmaps the same file and pushes dirty rects to Chrome
4. Update `tools/run-qemu.sh` to add `-object memory-backend-file,...`

### Wire format (frozen Day 16)

```
offset  size  field
0       4     u32 LE  frame_seq      # monotonic; producer reads when this changes
4       2     u16 LE  width          # pixels
6       2     u16 LE  height         # pixels
8       N     bytes   RGB565 LE pixels   # N == width * height * 2
```

The QEMU device patch (when written) and the firmware writer must match this
header exactly. It's only 8 bytes so the device model stays trivial.

### Implemented today (host side)

`tools/fb_server/shmem_producer.py` (+ `tests/fb_server/test_shmem_producer.py`,
7 cases passing) provides:

* `pack_frame(seq, w, h, payload)` / `parse_frame(buf)` — symmetric writer/reader
  helpers so a Python writer, a QEMU device, and the producer all agree on the
  layout.
* `read_latest(path)` — single-shot mmap read, returns `None` on missing /
  truncated files.
* `stream_frames(path, ...)` — polling generator that emits `(FBInit | None,
  FBUpdate, payload)` tuples as new frames appear; re-emits `FBInit` on
  resolution changes.

End-to-end demo without QEMU:

```bash
qemu-system-xtensa ... \
  -object memory-backend-file,id=fb0,mem-path=/tmp/esp32-fb,size=64K,share=on \
  -global esp32.fb-backend=fb0
```

```python
# Once the QEMU device patch lands, fb_server can stream live frames:
from pathlib import Path
from tools.fb_server.shmem_producer import stream_frames
for init, upd, payload in stream_frames(Path("/tmp/esp32-fb")):
    if init: ws.send_text(init.to_json())
    ws.send_text(upd.header_json()); ws.send_bytes(payload)
```

### Still deferred

* QEMU device model (`hw/misc/esp32_fb.c` or similar) — the deep work.
* Firmware MMIO writer in `flush_cb`.
* Wiring `tools/run-qemu.sh`'s `-object memory-backend-file` flag once the
  device exists.

This entire investigation is preserved here so future workdays don't have to
re-derive the trade-offs.
