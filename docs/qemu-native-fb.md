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

---

## Day 18 update — `ESP_RGB_VRAM_FILE` opt-in patch landed

While re-reading the fork's QEMU source (`chinawrj/qemu @
esp-develop-based-on-9.2.2`) we discovered it **already includes** a virtual
RGB display device — `hw/display/esp_rgb.c`, type `display.esp.rgb` — wired
into the ESP32 board at:

| Region | Guest address | Size |
| --- | --- | --- |
| Control regs | `DR_REG_FRAMEBUF_BASE = 0x21000000` | `ESP_RGB_IO_SIZE` |
| VRAM         | `0x20000000`                        | `ESP_RGB_MAX_VRAM_SIZE = 800·600·4 = 1 920 000 B` |

Crucially, those addresses match exactly the constants used by Espressif's
managed component **`espressif/esp_lcd_qemu_rgb @ 1.0.2`**
(`0x21000000` regs / `0x20000000` framebuffer). The component declares
`idf: ">=5.3"` with no target restriction → it works on plain ESP32, not
just S3. This unblocks the long-deferred Path B (firmware → real LVGL →
`esp_lcd_qemu_rgb` → QEMU device → host) end-to-end.

### What landed today (Path A, infrastructure only)

`tools/build-qemu.sh` now idempotently patches `hw/display/esp_rgb.c` so the
device's VRAM can be backed by a shared host file when env
`ESP_RGB_VRAM_FILE` is set:

```c
/* ESP_RGB_VRAM_FILE_PATCH */
const char *vram_file = getenv("ESP_RGB_VRAM_FILE");
if (vram_file && vram_file[0]) {
    memory_region_init_ram_from_file(&s->vram, OBJECT(s),
        "esp-rgb-vram", ESP_RGB_MAX_VRAM_SIZE, 0,
        RAM_SHARED, vram_file, 0, &error_abort);
} else {
    memory_region_init_ram(&s->vram, OBJECT(s),
        "esp-rgb-vram", ESP_RGB_MAX_VRAM_SIZE, &error_abort);
}
```

Default behaviour is unchanged (env unset → plain anonymous RAM). With env
set, QEMU `mmap`s the named file with `MAP_SHARED`, so any host process can
`mmap` the same file and observe live VRAM mutations from the guest.

### Verification

```bash
ESP_RGB_VRAM_FILE=/tmp/esp32-rgb-vram.bin \
  QEMU_BIN="$(pwd)/tools/qemu-src/build/qemu-system-xtensa" \
  bash tools/run-qemu.sh 150 verify
# -> 10/10 boot checks pass; /tmp/esp32-rgb-vram.bin is 1 921 024 B
#    (1 920 000 rounded to next 4 KiB host page).
```

`tests/test_qemu_vram_file.py` is the new regression: it asserts the patch
marker is present in the source and that any VRAM file from a prior boot is
≥ 1 920 000 B and `mmap`-able.

Today the file content stays all-zero, because the firmware still pushes
pixels through LVGL `flush_cb` → UART, **not** through the QEMU `esp_rgb`
MMIO. That switch is the next workday's deliverable.

### Next step (Path B, firmware switch)

1. Add managed dep `espressif/esp_lcd_qemu_rgb: "^1.0.2"` to `main/idf_component.yml`.
2. Replace the `flush_cb` UART path with `esp_lcd_panel_qemu_rgb_new(...)` +
   LVGL `set_draw_buffers()` against the panel-owned framebuffer.
3. Run with `ESP_RGB_VRAM_FILE=…` and update `shmem_producer.py` with a
   "headerless mode" that reads the first `240·135·2` bytes of the file as
   RGB565, repacks them into the existing `<IHH` frame header, and streams
   to Chrome.
4. Drop the UART base64 dump path entirely.

## Day 19 update — firmware writes pixels into VRAM ✅

Wired LVGL `flush_cb` to mirror frames into the QEMU `esp_rgb` VRAM at guest
`0x20000000` while keeping the existing UART base64 dump path intact.

* `mirror_to_qemu_vram(px_map, dst_y)` writes 240×135 RGB565 with stride 800 px
  via a `volatile uint16_t *` direct store.
* Every flush mirrors at `y=0` (live preview region).
* Flush #80 (`CAPTURE_FLUSH_INDEX`) also writes a frozen snapshot at `y=200`,
  mirroring exactly what the UART path captures.
* New test `tests/test_qemu_vram_file.py::test_vram_snapshot_matches_uart_dump`
  asserts byte-equality between the snapshot region and the base64-decoded
  UART payload — confirming no byte-order / stride / cache surprises.
* Decoded snapshot saved to `artifacts/qemu-vram-snapshot.png`.
* Suite: 44/44 pass (added 1, was 43).

This unblocks Day 20: a host-side reader for the VRAM mmap file (already
prototyped via `tools/fb_server/shmem_producer.py`) can stream live frames
to the Chrome canvas without touching the firmware again.

## Day 20 update — host streamer wired, Chrome can render live frames ✅

The host slice that was missing on Day 19 is now in place. No firmware change.

* `tools/fb_server/shmem_producer.py` gained `read_raw_region()` and
  `stream_raw_frames()` for **headerless** RGB565 surface files (the
  `esp_rgb` VRAM mmap has no header — it's just `surface_w * surface_h * 2`
  bytes at offset 0). Change detection is content-hash based since the
  device exposes no sequence counter.
* `tools/fb_server/server.py` accepts `--source raw-vram` plus
  `--vram-path / --vram-x / --vram-y / --surface-w` and async-polls the
  VRAM region, emitting `fb_init` once and `fb_update` only when the
  region's bytes change.
* New tests:
  * `tests/fb_server/test_shmem_producer.py` — 4 new cases (subrect read,
    missing/short file, change-driven streaming).
  * `tests/fb_server/test_raw_vram_e2e.py` — boots the server in
    raw-vram mode against a synthetic surface, asserts handshake,
    payload bytes, and reaction to surface mutation.
* Suite: **49/49** (was 44/44).

### Live pipeline cookbook

```bash
# 1) Boot QEMU with the VRAM mmap export (firmware mirrors LVGL frames).
ESP_RGB_VRAM_FILE=/tmp/esp32-rgb-vram.bin \
  QEMU_BIN=$(pwd)/tools/qemu-src/build/qemu-system-xtensa \
  bash tools/run-qemu.sh 150 verify

# 2) Stream live VRAM frames to Chrome on http://127.0.0.1:8080
.venv/bin/python -m tools.fb_server.server \
  --source raw-vram \
  --vram-path /tmp/esp32-rgb-vram.bin \
  --vram-x 0 --vram-y 0 --surface-w 800 \
  --width 240 --height 135 --fps 30
```

This is the first end-to-end firmware → host → browser frame pipeline
in the project that doesn't depend on the UART base64 dump.

## Day 21 update — visual verification loop closed in real Chrome ✅

Added `tests/cdp/test_raw_vram_canvas.py`, a Playwright-driven test that
spawns `fb_server --source raw-vram` against a synthetic 32×16 surface,
opens the framebuffer viewer in headless Chromium, and asserts:

* the canvas centre pixel matches the expected RGB565→RGB888 conversion
  (within ±2 LSBs to allow for channel-replication rounding);
* mutating the surface bytes (red → blue) is reflected on the canvas
  within a 4-second budget — i.e. the host-poll → WS → JS → ImageData
  round trip works end-to-end inside a real browser;
* a baseline canvas screenshot is captured to `artifacts/cdp-raw-vram.png`.

Suite: **51/51** with `IDF_PATH` sourced (was 49/49).

This is the AI-friendly visual loop from the original task book Phase 4:
```
generate UI code → build → QEMU → VRAM mmap → fb_server → Chrome → CDP
                                                                    ↓
                                                           AI / pytest checks
```
Together with Day 20's CLI cookbook, the whole pipeline now has a single
pytest invocation that exercises every layer except the QEMU instance
itself (which the older `tests/test_qemu_vram_file.py` snapshot test
already covers).
