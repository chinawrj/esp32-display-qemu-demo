# NEXT-001 — QEMU-native WebSocket framebuffer export (design spike)

> **Status:** Design only. Day 3 (Linux) deliverable.
> **Owner:** chinawrj@gmail.com
> **Tracks BACKLOG.md item:** "★ NEXT-001 — QEMU-native framebuffer → Chrome
>   export (no firmware changes)"
> **Related prior art:** `docs/qemu-native-fb.md` (Days 18–23: file-mmap path
>   that is currently shipping), `tools/qemu-src/hw/display/esp_rgb.c`,
>   `tools/qemu-src/ui/vnc-ws.c`.

The current shipping path (`docs/qemu-native-fb.md`, Day 23) gets LVGL frames
into Chrome via a **firmware-cooperative** trick: the guest mirrors pixels into
`esp_rgb` VRAM at `0x20000000`, QEMU is told to back that VRAM with a shared
host file (`ESP_RGB_VRAM_FILE`), and a Python `fb_server` mmaps the same file
to push frames over WebSocket. It works, but it requires every demo app to
include `main/qemu_vram.c` and call `qemu_vram_mirror()` from `flush_cb`.

NEXT-001 moves the streaming responsibility **into the QEMU device itself**,
so any unmodified `esp_lcd_qemu_rgb`-based ESP-IDF app "just appears" in
Chrome. This document is the design that the implementation work in Days 4–6
will follow.

---

## 1. Wire protocol (v1)

The QEMU device opens **one** TCP listener on `127.0.0.1:9334` (configurable
via env `ESP_RGB_WS_PORT`, mirroring the existing `ESP_RGB_VRAM_FILE` knob).
It speaks RFC 6455 WebSocket. The path is `/`; no subprotocol negotiation.

### 1.1 Handshake

Standard RFC 6455 server handshake:

```
GET / HTTP/1.1
Host: localhost:9334
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Key: <base64 of 16 random bytes>
Sec-WebSocket-Version: 13
```

Response:

```
HTTP/1.1 101 Switching Protocols
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Accept: base64( SHA1( key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11" ) )
```

### 1.2 Header frame (one per connection, sent immediately after upgrade)

A single **text** frame containing JSON:

```json
{
  "version": 1,
  "w": 800,
  "h": 600,
  "format": "x8r8g8b8",
  "stride_bytes": 3200,
  "fps_target": 30
}
```

* `format` is `"x8r8g8b8"` for `BPP_32` (the default — see
  `esp_rgb.h:DEFAULT_BPP = BPP_32`) or `"r5g6b5"` for `BPP_16`. Both correspond
  exactly to the PIXMAN format used in `update_rgb_surface()` (esp_rgb.c:30-44).
* `w`/`h` reflect the **current** surface size, not the max. The frontend uses
  this to size the `<canvas>`. If the guest resizes (a `RGB_WIN_SIZE` write
  triggers `do_update_surface = true`), the device sends another header frame
  before the next pixel frame and resets `seq` to 0.
* `stride_bytes` is `w * (bpp/8)`, included so the client doesn't have to
  redo the multiplication.

### 1.3 Pixel frames (one per damaged-rect flush)

Each frame is a single **binary** WebSocket message:

```
offset  size  field
0       4     u32 LE  seq        # monotonic, starts at 0, wraps at 2^32
4       4     u32 LE  size       # number of pixel bytes that follow
8       size  bytes   pixels     # raw, in declared format, no padding
```

v1 sends **full frames** — no dirty-rect diffs. Justification:

* `update_display_area()` in `esp_rgb.c` already maintains a copy of the
  current surface (`surface_data(qemu_console_surface(s->con))`); we just
  re-emit the whole thing every time it changes. Cheap to implement, easy
  to verify in Chrome (single `ImageData` write per frame).
* Worst-case bandwidth at the documented `ESP_RGB_MAX_*` (800×600×4 @ 30 fps)
  is **~55 MB/s** loopback — well below TCP loopback throughput on any
  modern Linux. For the LVGL demo we actually run (240×135), it's
  ~2 MB/s, trivial.
* Diff/JPEG encoding is reserved for v2 (see §5).

### 1.4 No client → server messages in v1

Client sends nothing after the handshake. The server ignores any incoming
data frames. (PING/PONG control frames must be honored per RFC 6455; we'll
implement them.)

---

## 2. Build-vs-host-bridge: WS server inside `esp_rgb.c`

**Decision: put the WebSocket server inside the QEMU device itself.**

**Considered alternatives:**

| Option | Description | Verdict |
| --- | --- | --- |
| A — WS server inside `esp_rgb.c` (chosen) | New `*.c` file, called from `esp_rgb_init()`, fan-out from `update_display_area()` / `update_rgb_surface()` | Lowest latency (no extra `mmap` polling), one process, no on-disk state, trivial integration with existing `QIOChannel` infrastructure |
| B — Host-side bridge reading the existing `ESP_RGB_VRAM_FILE` | Keep the file-mmap path; add a Python (or C) daemon that watches the file and exposes WS | Already exists as `tools/fb_server/shmem_producer.py` — it's literally the *current* shipping path. Day 23's known weakness is that the firmware still has to *write* to the VRAM file in the first place. Doesn't solve the problem. |
| C — Use QEMU's built-in VNC server with a WebSocket transport (`-vnc :0,websocket`) | Free, RFC-clean | VNC frame format is RFB, not raw RGB. Chrome would need a noVNC-class JS client (~150 KB). Loses the "tiny custom canvas + 80 LoC JS" story that Phase 4 of the project was built around. |
| D — Sidecar process that QMP-subscribes to display updates | Use the QMP `screendump` or `display-update` events QEMU already exposes | `screendump` is a one-shot PPM/PNG dump — ~tens of ms per frame, not 30 fps. No event for "surface updated". |

The justification for A over the others is that we are already **building our
own QEMU** (Day 14 / `tools/build-qemu.sh`) and already **patching
`esp_rgb.c`** (the `ESP_RGB_VRAM_FILE_PATCH` block). Adding ~250–350 LoC of
WebSocket server in the same file (or a sibling `esp_rgb_ws.c` linked into
the same device) is consistent with the existing patching strategy and
avoids a second long-running process. The host stack collapses to "open the
HTML page in Chrome" — no `python -m tools.fb_server.server` required.

The existing `ESP_RGB_VRAM_FILE` path stays in the codebase (back-compat for
the Day 22/23 firmware) but becomes optional.

---

## 3. Annotated `esp_rgb.c` callsite walkthrough

Two functions are the integration points. Line numbers refer to
`tools/qemu-src/hw/display/esp_rgb.c` as it stands today (Day 3, after the
`ESP_RGB_VRAM_FILE_PATCH`).

### 3.1 `update_rgb_surface()` (lines 28–51) — emit header frame

```c
static void update_rgb_surface(ESPRgbState* s){
    DisplaySurface *surface;
    switch (s->bpp){
        case BPP_32:
            surface = qemu_create_displaysurface_from(
                s->width, s->height, PIXMAN_x8r8g8b8,
                s->width * 4, NULL);
            break;
        case BPP_16:
            surface= qemu_create_displaysurface_from(
                s->width, s->height, PIXMAN_r5g6b5,
                s->width * 2, NULL);
            break;
        ...
    }
    surface->flags = QEMU_ALLOCATED_FLAG;
    dpy_gfx_replace_surface(s->con, surface);
    /* >>> NEW: notify all WS clients that the surface format changed.
     *     Build the JSON header from (s->bpp, s->width, s->height) and
     *     broadcast as a TEXT frame. Reset per-client seq counters to 0. */
    esp_rgb_ws_announce_surface(s);  /* declared in esp_rgb_ws.h */
}
```

Triggered by:
* `esp_rgb_init()` (line 296) at device construction — sends the **first**
  header to any client that connects later (cached in WS state).
* `rgb_update()` (line 181) when the guest writes `RGB_WIN_SIZE` or
  `RGB_BPP_VALUE` (lines 140 / 163 set `do_update_surface = true`).

### 3.2 `rgb_update()` damaged-rect path (lines 176–239) — emit pixel frame

```c
static void rgb_update(void* opaque)
{
    ESPRgbState* s = (ESPRgbState*) opaque;

    if (s->con && s->do_update_surface) {
        update_rgb_surface(s);                 /* announces header above */
        s->do_update_surface = false;
    }

    if (s->con && s->update_area) {
        ...
        /* Existing dma_memory_read loop fills surface_data(...) */
        for (int i = 0; i < height; i++) {
            dma_memory_read(src_as, src, dest, width * bytes_per_pixel, MEMTXATTRS_UNSPECIFIED);
            dest += s->width * bytes_per_pixel;
            src  += width * bytes_per_pixel;
        }

        dpy_gfx_update(s->con, s->from_x, s->from_y, width, height);

        /* >>> NEW: after the surface is up to date, fan out to WS clients.
         *     Read pointer is surface_data(qemu_console_surface(s->con));
         *     length is s->width * s->height * bytes_per_pixel; format is
         *     known from s->bpp. The pixel-frame header is built once and
         *     written + the body is queued via QIOChannel non-blocking
         *     writev. seq++ is per-client (so a freshly connected client
         *     starts at 0 with a fresh header). */
        esp_rgb_ws_broadcast_frame(s);
        ...
    }
}
```

This is the hot path. Two important properties:

* It's invoked by QEMU's display refresh thread (the `GraphicHwOps.gfx_update`
  callback registered at `esp_rgb_init()` line 294 via `graphic_console_init`).
  This thread already drives the GTK/SDL window at the QEMU display rate
  (~60 Hz default; we'll throttle to 30 fps inside the WS layer if the
  guest paints faster than that).
* It runs under the QEMU global mutex (BQL). All `QIOChannel` writes must be
  non-blocking (`QIO_CHANNEL_WRITE_FLAG_*` or by `qio_channel_set_blocking`),
  otherwise a stalled Chrome stalls the *guest*.

### 3.3 `rgb_invalidate()` (lines 242–252) — currently no WS hook needed

This zeroes the surface on QEMU-side invalidation. The very next
`rgb_update()` will fan out the all-black surface, so no separate WS hook is
required.

### 3.4 `esp_rgb_init()` (lines 278–321) — start the listener

```c
static void esp_rgb_init(Object *obj)
{
    ...
    /* ESP_RGB_VRAM_FILE_PATCH block remains untouched. */

    /* >>> NEW: start the WS listener once per device instance.
     *     - Pulls port from getenv("ESP_RGB_WS_PORT"), default 9334.
     *     - getenv("ESP_RGB_WS_DISABLE") set => skip entirely (back-compat).
     *     - Uses qio_net_listener_new() + qio_net_listener_set_client_func()
     *       so accept happens in QEMU's main loop, no extra threads. */
    esp_rgb_ws_start(s);

    address_space_init(&s->vram_as, &s->vram, "esp.rgb.vram_as");
}
```

### 3.5 New file layout (preview for Day 4)

```
tools/qemu-src/
  hw/display/
    esp_rgb.c            # add 3 hook calls + #include "esp_rgb_ws.h"
    esp_rgb_ws.c         # NEW — listener, handshake, encode, broadcast
    meson.build          # NEW — add esp_rgb_ws.c to esp_rgb sources list
  include/hw/display/
    esp_rgb_ws.h         # NEW — public surface for the 3 hooks above
```

`tools/build-qemu.sh` already idempotently patches `esp_rgb.c`; the Day 4
patch will idempotently *append* the three `esp_rgb_ws_*()` calls and drop
in the new file. Marker comment: `ESP_RGB_WS_PATCH`.

---

## 4. Risk register

| # | Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- | --- |
| R1 | **Stalled Chrome backpressure freezes the guest.** A client that stops reading would, with blocking writes, jam the BQL-holding `rgb_update()` callback. | High (any laptop sleep, any DevTools pause) | Critical (guest hangs) | Use `qio_channel_set_blocking(ioc, false, NULL)` on every accepted client; on `EAGAIN`/short write, **drop the in-flight frame** for that client and increment a `dropped_frames` counter. seq still increments for non-stalled clients. We never queue more than one pending frame per client. |
| R2 | **Hand-rolled WS framing has bugs.** ~250–350 LoC including SHA-1 handshake (use `qcrypto_hash_*`), base64 (use `g_base64_encode`), header parsing, frame encode. | Medium | Medium (debug effort) | Mirror the structure of `qemu/ui/vnc-ws.c` (150 LoC, same building blocks) and `qemu/io/channel-websock.c` if it exists in the fork. Add a pytest that opens the socket with the `websockets` Python package and asserts handshake + a pixel frame round-trip — this becomes `tests/cdp/test_qemu_direct_canvas.py` per BACKLOG. |
| R3 | **libwebsockets vs hand-rolled.** Pulling in libwebsockets means a new `meson` dep, a build matrix change for the QEMU clone, and a new submodule story. | Low (we choose) | Medium | **Do not pull in libwebsockets.** Hand-roll. Reasons: (1) the Espressif QEMU fork has no libwebsockets dep today; (2) `qcrypto_hash_*` + `g_base64_encode` + a 64-line frame encoder is enough; (3) keeps the patch reviewable for upstreaming later. |
| R4 | **Multi-client correctness.** Two Chrome tabs would each need an independent header + seq counter. | Medium (DevTools refresh creates a 2nd client transiently) | Low (cosmetic, frame ordering) | v1 supports N clients with per-client state (seq, last_acked, ws_state). Broadcast loop iterates `QSLIST_FOREACH(client, &s->ws_clients, next)`. v2 may add a max-clients cap. |
| R5 | **FB-005 — `idf.py` not directly invokable by `timeout(1)` because the script uses `#!/usr/bin/env python` and `timeout` skips PATH PATH-resolution oddities.** Already filed; blocks pytest in some flows. | Already happening | Medium (test flakiness) | Out of scope for this design but the WS path eliminates the need for `tools/run-qemu.sh 90 verify` to pre-populate `/tmp/esp32-qemu-serial.log` — the WS test will boot QEMU on its own, capture stdout, and assert via the WS handshake instead of via `grep` on a serial log. Once the WS test lands, the dependency chain in `tests/cdp/test_log_replay.py` and `tests/fb_server/test_log_producer.py` (the two currently-skipped tests) goes away. |
| R6 | **DisplaySurface byte order on big-endian hosts.** `update_rgb_surface()` uses `PIXMAN_x8r8g8b8` which is host-endian. | Low (we ship Linux x86_64 + macOS arm64; both LE) | Low | Document `format: "x8r8g8b8"` as **host-LE** in the JSON header. Frontend `decodeRGB565()`-style helper for x8r8g8b8 takes BGRA→RGBA in the LE case (32-bit `0xAARRGGBB` reads as `BB GG RR AA`). |

### FB-005 unblock path (R5 expanded)

The two pytest skips today are:

```
tests/cdp/test_log_replay.py::test_log_replay
  SKIPPED: needs complete QEMU log at /tmp/esp32-qemu-serial.log;
           run pytest tests/test_qemu_boot.py first
tests/fb_server/test_log_producer.py
  SKIPPED: needs a complete /tmp/esp32-qemu-serial.log (1440 FB= lines)
```

Both are testing the **legacy UART-base64 path**. NEXT-001 makes that path
optional, and the new `tests/cdp/test_qemu_direct_canvas.py` becomes the
canonical "frames reach Chrome" test. We don't have to *delete* the legacy
tests immediately — we just stop making them gating. Concretely:

1. Land NEXT-001 (Day 4–6) with `test_qemu_direct_canvas.py` passing.
2. Day 7: mark the two log-dependent tests as `pytestmark =
   pytest.mark.legacy` and add `--strict-markers` config so they only run
   with `pytest -m legacy`.
3. Day 8+: when the firmware drops the `main/fb_dump.c` UART base64 dumper
   (deferred — no consumer left), delete those two tests outright.

Net: pytest defaults go from "13 fail (env-dep) + 2 skip + 56 pass" to
"~58 pass + 0 skip + 0 fail" once NEXT-001 lands.

---

## 5. Day 4–6 ship plan

### Day 4 — listener + handshake (no pixels yet)

1. **Commit 1:** Add `tools/qemu-src/include/hw/display/esp_rgb_ws.h` and
   `tools/qemu-src/hw/display/esp_rgb_ws.c` skeleton with three public
   functions: `esp_rgb_ws_start(s)`, `esp_rgb_ws_announce_surface(s)`,
   `esp_rgb_ws_broadcast_frame(s)`. Today they no-op except for `_start`,
   which opens `127.0.0.1:9334` via `qio_net_listener_new()`, accepts
   clients, and replies with the RFC 6455 handshake. On accept it logs
   `info_report("esp_rgb: WS client %d/%d connected", n, max)`. Update
   `tools/build-qemu.sh` to install the new files (idempotent — same
   Python heredoc pattern as the `ESP_RGB_VRAM_FILE_PATCH`).
2. **Commit 2:** Hook `esp_rgb_ws_start()` into `esp_rgb_init()` behind the
   `ESP_RGB_WS_PORT` env. Add `ESP_RGB_WS_DISABLE` opt-out for the legacy
   tests. Marker: `ESP_RGB_WS_PATCH`.
3. **Commit 3:** New `tests/test_qemu_ws_handshake.py` (pytest + Python
   `websockets`). Boots QEMU with `ESP_RGB_WS_PORT=9334` against the
   already-built firmware, asserts the handshake completes and the JSON
   header arrives. Skip if `qemu-system-xtensa` isn't on PATH. Aim:
   one new passing test, zero regressions.

### Day 5 — pixel fan-out

1. Implement `esp_rgb_ws_announce_surface()` (build the JSON, broadcast as
   a text frame) and `esp_rgb_ws_broadcast_frame()` (build the 8-byte
   pixel header + write the surface bytes via `qio_channel_writev_all` in
   non-blocking mode). Add per-client `dropped_frames` and `seq` counters.
2. Smoke-test from Python: open a connection, decode the first pixel
   frame, write it to a PNG, eyeball the resulting `artifacts/qemu-ws-frame-001.png`.
3. Extend `tests/test_qemu_ws_handshake.py` with a "first pixel frame
   non-empty" assertion.

### Day 6 — Chrome end-to-end + acceptance test

1. Add `web/qemu-direct.html` (single `<canvas>` + ~80 LoC JS — opens
   `ws://localhost:9334/`, decodes header, decodes pixel frames, paints
   `ImageData`). Reuse `web/main.js` `decodeRGB565` for the BPP_16 case;
   add a tiny `decodeXRGB8888` helper for BPP_32.
2. Add `tests/cdp/test_qemu_direct_canvas.py` per BACKLOG acceptance:
   Playwright opens `web/qemu-direct.html`, polls canvas for `unique >=
   8 && sum > 0` (matches the existing `test_live_qemu_canvas.py`
   threshold). **Crucially** it asserts `ESP_RGB_VRAM_FILE` is unset, so
   it proves the new path is independent of the file-mmap one.
3. Update `tools/run-demo.sh` to take `--engine {file-mmap,ws}`
   (default still `file-mmap` for now; flip in a follow-up commit once
   we're confident).
4. README Quickstart: add the WS path as the recommended option.

### Tomorrow's first 3 commits look like

1. `feat(qemu): add esp_rgb_ws listener skeleton + handshake (no pixels yet)`
2. `feat(qemu): wire ESP_RGB_WS_PORT into esp_rgb_init via build-qemu patch`
3. `test: tests/test_qemu_ws_handshake.py — assert WS handshake + JSON header`

If the listener-only Day 4 stretches into Day 5 (likely — first time
touching `qio_net_listener_*`), pixel fan-out slides to Day 6 and Chrome
e2e to Day 7. NEXT-001 is a 4-day slice in the optimistic case, 5–6 days
realistically.

---

## 6. Out of scope for v1

* Multi-engine selection in `tools/run-demo.sh` beyond `--engine ws|file-mmap`.
* macOS support (NEXT-001 BACKLOG explicitly says "Develop on Linux first").
* JPEG / dirty-rect compression (queued for v2).
* Authentication. Listener binds `127.0.0.1` only; that's the security boundary.
* HTTP `GET /` static-page-serving from QEMU. Chrome opens
  `web/qemu-direct.html` from disk or via `python -m http.server` (the
  existing test fixture pattern).
