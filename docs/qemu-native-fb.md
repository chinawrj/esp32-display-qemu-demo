# QEMU native framebuffer integration — investigation

Status: design / research note for `cdp-phase5-qemu-native-fb`.

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

## Concrete next slice (deferred)

Once a custom QEMU is up (Day 14 build):

1. Add a tiny QEMU device "esp32-fb" backed by a `memory-backend-file`
2. Firmware writes the LVGL buffer to a fixed MMIO address each flush (no
   change to user code; happens inside `flush_cb`)
3. Host `fb_server` mmaps the same file and pushes dirty rects to Chrome
4. Update `tools/run-qemu.sh` to add `-object memory-backend-file,...`

Pseudo:

```bash
qemu-system-xtensa ... \
  -object memory-backend-file,id=fb0,mem-path=/tmp/esp32-fb,size=64K,share=on \
  -global esp32.fb-backend=fb0
```

```python
# tools/fb_server/shmem_producer.py (sketch)
import mmap, os
with open("/tmp/esp32-fb", "rb") as f:
    mm = mmap.mmap(f.fileno(), 64 * 1024, prot=mmap.PROT_READ)
    while True:
        rgb565 = bytes(mm[:240*135*2])
        yield FBUpdate(...)
```

This entire investigation is preserved here so future workdays don't have to
re-derive the trade-offs.
