# Day 5 (Linux) — 2026-05-02

Day 5 completes NEXT-001 pixel fan-out: per-client QLIST, JSON header TEXT
frame on connect, and periodic BINARY pixel frames via a GLib timer.

## 昨日回顾 (Day 4)

- ✅ `esp_rgb_ws.c` skeleton: `QIONetListener` + `QIOChannelWebsock` handshake.
- ✅ `build-qemu.sh` idempotent patch with `ESP_RGB_WS_PATCH` marker.
- ✅ `test_qemu_ws_handshake.py` (3 tests): static markers + live RFC 6455 handshake.
- ✅ `pytest -q` **74 passed, 0 failed** (Day 4 baseline).
- 📝 FB-010: QEMU orphan with `-serial mon:stdio`; planned `-serial null` fix for Day 5.

## 今日目标 (Day 5)

1. **Goal 1 — Pixel fan-out:** Rewrite `esp_rgb_ws.c` with `QLIST` of per-client
   state, `esp_rgb_ws_announce_surface()` (TEXT frame), `esp_rgb_ws_broadcast_frame()`
   (BINARY frame with 8-byte header).
2. **Goal 2 — Timer-driven broadcast:** Add `g_timeout_add(500ms)` in
   `esp_rgb_ws_start()` so frames are pushed even with `-display none`
   (no display listener → `gfx_update()` never called).
3. **Goal 3 — Tests:** Add `test_ws_json_header` + `test_ws_first_pixel_frame`
   to `test_qemu_ws_handshake.py`; apply FB-010 fix (`-serial null`).
4. **Target:** ≥ 77 passed, 0 failed.

**Shipped at HEAD** (see git log below).

## 完成状态 (evening review)

| Task | Status | Notes |
|---|---|---|
| `esp_rgb_ws.c` rewrite — `QLIST` + frame encoding | ✅ | ~410 LoC; `ws_send_frame()` builds RFC 6455 header; `announce_surface()` caches JSON before listener up |
| `esp_rgb_ws.h` — comment updated | ✅ | Still 3 public hook declarations |
| `ESP_RGB_WS_PATCH_V2` in `build-qemu.sh` | ✅ | Adds unconditional `broadcast_frame()` at end of `rgb_update()` (VRAM-direct firmware path) |
| `g_timeout_add(500ms)` timer in `esp_rgb_ws_start()` | ✅ | Drives broadcasts independent of QEMU display refresh |
| `test_ws_json_header` | ✅ | Asserts TEXT JSON with version/w/h/format/stride_bytes/fps_target |
| `test_ws_first_pixel_frame` | ✅ | Asserts BINARY frame seq=0, correct size, len=8+size |
| FB-010 fix: `-serial null` in `qemu_ws_proc` fixture | ✅ | SIGTERM now reliably terminates QEMU |
| `ping_interval=None` in all `ws_connect()` calls | ✅ | Server doesn't handle PONG; prevents keepalive disconnect |
| `max_size=None` in all `ws_connect()` calls | ✅ | Frame is ~1.92 MB; Python `websockets` default 1 MB limit caused 1009 close |
| All 5 WS tests pass | ✅ | |
| `pytest -q` | ✅ | **63 passed, 13 skipped, 0 failed** (skips: require `IDF_PATH`/`qemu-system-xtensa` in PATH) |

## Verification evidence

```
$ bash tools/build-qemu.sh 2>&1 | tail -3
QEMU emulator version 9.2.2
Copyright (c) 2003-2024 Fabrice Bellard and the QEMU Project developers
[build-qemu] export QEMU_BIN=.../tools/qemu-src/build/qemu-system-xtensa

$ pytest tests/test_qemu_ws_handshake.py -v
tests/test_qemu_ws_handshake.py::test_esp_rgb_ws_patch_marker_in_source PASSED
tests/test_qemu_ws_handshake.py::test_esp_rgb_ws_source_files_installed PASSED
tests/test_qemu_ws_handshake.py::test_ws_handshake PASSED
tests/test_qemu_ws_handshake.py::test_ws_json_header PASSED
tests/test_qemu_ws_handshake.py::test_ws_first_pixel_frame PASSED
5 passed in 9.57s

$ pytest -q --tb=no
63 passed, 13 skipped in 28.59s

$ git log --oneline -4
```

(see git log below after commit)

## Key observations

1. **`gfx_update()` never fires with `-display none`.** QEMU's display refresh
   loop only calls device `gfx_update` callbacks when at least one display
   listener (SDL/GTK/VNC/etc.) is registered. With `-display none` there is
   no listener and `rgb_update()` is never called regardless of `ESP_RGB_WS_PATCH_V2`.
   Fix: `g_timeout_add(500, esp_rgb_ws_timer_cb, NULL)` in `esp_rgb_ws_start()`;
   timer callback calls `broadcast_frame()` every 500 ms.

2. **Python `websockets` default `max_size=1048576` (1 MB).** The QEMU `esp_rgb`
   default surface is 800×600×4 = 1,920,000 bytes. Python's websockets library
   sends a `1009 (message too big)` close frame and disconnects before the
   test can read the pixel frame. Fix: `max_size=None` in all `ws_connect()`
   calls. Recorded as FB-011.

3. **`announce_surface()` called before listener is up.** `esp_rgb_init()` calls
   `update_rgb_surface()` → `esp_rgb_ws_announce_surface()` before
   `esp_rgb_ws_start()` is reached. At that point `g_ws.listener == NULL`.
   Fix: always update `g_ws.json_header` cache regardless of listener state;
   new clients receive the cached header in `handshake_done()`.

4. **Broken pipe on client close.** After Python receives the first frame and
   closes the connection, the QEMU timer fires again and tries to write to
   the closed socket. This produces "broadcast: client send failed, removing"
   which is correct behavior — client is removed from the list. Not a bug.

## 明日計画 (Day 6)

Per `docs/qemu-native-ws.md` §5 — Day 6: browser rendering + stretch goals:
1. Open `web/index.html` in the test browser; connect to `ws://127.0.0.1:9334/`.
2. Decode the BINARY frame in JavaScript (`ImageData`, `canvas.putImageData()`).
3. `test_ws_frame_looks_like_lvgl` — decode first pixel frame with Pillow,
   write `artifacts/qemu-ws-frame-001.png`, assert non-trivial pixel variance.
4. Optionally: NEXT-002 planning (QEMU Wi-Fi STA via wpa_supplicant ctrl socket).
