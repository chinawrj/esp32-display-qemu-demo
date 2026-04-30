# Backlog

Tracked, implementation-ready next targets for this project. Items here are
**not yet started** — they're written so any contributor (especially on a
fresh Linux machine) can pick them up without re-deriving the design.

The headline target is at the top.

---

## ★ NEXT-001 — QEMU-native framebuffer → Chrome export (no firmware changes)

**Status:** Not started. Intended platform: **Linux** (macOS path is already
working via the file-mmap bridge below; do not block on it).

### Problem

Today, getting an LVGL/ESP-IDF app's frames into a Chrome page requires
**firmware-level cooperation**:

1. The firmware mmap's a magic MMIO region (`QEMU_RGB_VRAM_ADDR = 0x20000000`)
   inside the `esp_rgb` device's VRAM and writes RGB565 pixels into it
   every flush (see `main/qemu_vram.c` → `qemu_vram_mirror`).
2. QEMU is launched with `ESP_RGB_VRAM_FILE=/tmp/esp32-rgb-vram.bin` so that
   VRAM is `memory_region_init_ram_from_file(... RAM_SHARED ...)` instead of
   anonymous RAM (see `tools/qemu-src/hw/display/esp_rgb.c`, the
   `ESP_RGB_VRAM_FILE_PATCH` block around line 303).
3. A host-side Python `fb_server` (see `tools/fb_server/shmem_producer.py`)
   mmaps the same file and streams a slice of it to Chrome over a WebSocket.

That works (and is what `tools/run-demo.sh` does today), but it means **every
ESP-IDF app that wants Chrome viewing has to be modified** to do the
firmware-side mirror dance. We want any unmodified `esp_lcd_qemu_rgb`-based
app to "just appear" in Chrome.

### Desired architecture

Move the streaming responsibility **into the QEMU device itself**:

```
        before                                 after
        ──────                                 ─────
   ESP-IDF app ─┐                          ESP-IDF app ─┐
                │ (special MMIO writes)                 │ (normal LCD draw)
                ▼                                       ▼
   QEMU esp_rgb ─┐ (RAM-backed file)        QEMU esp_rgb ─┐ (DisplaySurface)
                ▼                                       │
            host file ───┐                              │  WebSocket / HTTP
                         ▼                              ▼
                   Python fb_server ───── WS ──── Chrome canvas
                                                    (direct)
```

The `esp_rgb` device already maintains a fully-rendered `DisplaySurface`
(updated via `update_rgb_surface()` and `dpy_gfx_replace_surface()` in
`tools/qemu-src/hw/display/esp_rgb.c`). That surface contains exactly the
pixels QEMU's GTK/SDL window would draw. We just need to push those pixels
out over a network socket Chrome can read.

### Concrete subtasks (in order)

1. **Spec the wire protocol.** Simplest viable design:
   - QEMU listens on `127.0.0.1:9334` (configurable via `-device esp_rgb,websocket-port=…` or the `ESP_RGB_WS_PORT` env var, mirroring the existing `ESP_RGB_VRAM_FILE` pattern).
   - On client connect, send a one-shot JSON header: `{ "w": W, "h": H, "format": "rgb565" | "x8r8g8b8" }`.
   - Then send raw frame bodies as binary WebSocket messages: `[u32 le seq][u32 le size][bytes pixels]`. One message = one frame. No diffs in v1.
   - Throttle to ~30 fps (reuse the existing `update_display_area()` / dirty-rect cadence inside `esp_rgb.c`).

2. **Implement the WebSocket server inside the device.**
   - Don't pull in libwebsockets unless trivial; QEMU already links
     libnice/glib + an HTTP-ish server for VNC. The cheapest route is
     probably `ws://` with a hand-rolled handshake (RFC 6455 frame format
     in <300 LoC C; reference: `qemu/ui/vnc-ws.c`).
   - Hook into the existing `update_display_area()` path so every time
     QEMU pushes a damaged region to its surface, we also push a frame to
     all connected clients. Use a `QIOChannel` non-blocking write so a
     stalled Chrome doesn't freeze the device.
   - Keep `ESP_RGB_VRAM_FILE` working for back-compat (don't remove the
     existing patch).

3. **Frontend page.** Add `web/qemu-direct.html` (sibling to the existing
   `web/index.html`): a single `<canvas>` + a tiny JS that opens
   `ws://localhost:9334/`, reads the header, then `decodeRGB565()`s each
   message into ImageData. ~80 LoC. Reuse `web/main.js`'s existing
   `decodeRGB565` helper.

4. **Acceptance test.** Add `tests/cdp/test_qemu_direct_canvas.py`:
   - Start QEMU with `ESP_RGB_WS_PORT=9334` against the existing built
     firmware (no firmware change required).
   - Open `web/qemu-direct.html` in Playwright.
   - Poll the canvas for `unique >= 8 && sum > 0` (same threshold as
     `tests/cdp/test_live_qemu_canvas.py`).
   - Assert that **`ESP_RGB_VRAM_FILE` is unset** for this test, so we
     prove the new path is independent of the old one.

5. **Package.** Add a `tools/run-direct-demo.sh` (or just an `--engine
   qemu-direct` flag to `tools/run-demo.sh`) that boots QEMU + opens the
   new page. Update README's Quickstart to offer both paths.

6. **Optional v2.** Multi-client broadcast, simple JPEG encoding for
   bandwidth, an HTTP `GET /` that serves the static page so Chrome
   doesn't need a separate `python -m http.server`.

### Files this work will touch

| Area | Path |
| --- | --- |
| Device source | `tools/qemu-src/hw/display/esp_rgb.c` |
| Device header | `tools/qemu-src/include/hw/display/esp_rgb.h` |
| WebSocket reference | `tools/qemu-src/ui/vnc-ws.c` |
| QEMU build (rebuild after edits) | `bash tools/build-qemu.sh` |
| Frontend | `web/qemu-direct.html`, reuses `web/main.js` `decodeRGB565` |
| Test | `tests/cdp/test_qemu_direct_canvas.py` |
| Launcher | `tools/run-direct-demo.sh` (new) or extend `tools/run-demo.sh` |
| Docs | `docs/qemu-native-fb.md` (Day 26+ section), README Quickstart |

### Acceptance criteria

- [ ] `bash tools/build-qemu.sh` produces a `qemu-system-xtensa` with the
      new device feature.
- [ ] Launching that QEMU against the **unmodified** ESP-IDF firmware
      (`main/main.c` not touched) and visiting `web/qemu-direct.html`
      shows the LVGL benchmark animating in Chrome at ~30 fps.
- [ ] `pytest -q tests/cdp/test_qemu_direct_canvas.py` passes with
      `ESP_RGB_VRAM_FILE` **unset**.
- [ ] The existing `pytest -q` suite (50 passed, 2 skipped) still passes
      — no regressions in the file-mmap path.
- [ ] No new firmware-side knobs; `main/qemu_vram.c`'s direct-VRAM
      gradient and `mirror_to_qemu_vram` calls remain functional but
      become **optional** (the new app developer simply doesn't do them).

### Why not on macOS?

The existing locally-built QEMU on macOS 12 is already pinned to a
patched 9.2.2 (`tools/build-qemu.sh`). Adding a network listener on
that build is doable but the test path is heavier (Apple Clang,
no `setsockopt(SO_REUSEPORT)` quirks, etc.). On Linux the upstream
QEMU build path is uncomplicated, and `qemu/ui/vnc-ws.c` compiles
out-of-the-box. **Develop on Linux first**; macOS support is a
follow-up if anyone wants it.

### Pointers / prior art inside this repo

- `tools/qemu-src/hw/display/esp_rgb.c` — device today; `update_rgb_surface()`,
  `update_display_area()`, the `ESP_RGB_VRAM_FILE_PATCH` block.
- `tools/qemu-src/include/hw/display/esp_rgb.h` — `ESPRgbState` fields,
  `ESP_RGB_MAX_*` constants.
- `tools/fb_server/shmem_producer.py` — host-side equivalent of what the
  new in-QEMU server should produce. Read its frame layout for inspiration.
- `web/main.js` (`decodeRGB565`) — frontend already knows how to decode
  RGB565 to a canvas.
- `tests/cdp/test_live_qemu_canvas.py` — pattern for the new
  acceptance test (Playwright + canvas polling).
- `docs/qemu-native-fb.md` — the design notebook from Days 18-23, has
  the full backstory of why we ended up where we are.

---

## Other backlog items (lower priority)

(none yet — add new entries above this line)
