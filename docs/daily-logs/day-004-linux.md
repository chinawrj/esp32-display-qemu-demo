# Day 4 (Linux) — 2026-05-02

Day 4 executes the first three NEXT-001 commits from the `docs/qemu-native-ws.md`
Day 4–6 ship plan: listener skeleton, `build-qemu.sh` wiring, and a pytest
that asserts the RFC 6455 handshake.

## 昨日回顾 (Day 3)

- ✅ Patched QEMU 9.2.2 confirmed (`tools/qemu-src/build/qemu-system-xtensa`).
- ✅ `pytest -q` 71 passed, 0 skipped, 0 failed.
- ✅ `docs/qemu-native-ws.md` design spike (220 LoC, wire protocol, Day 4–6
  ship plan, risk register).
- 📝 FB-008 (QEMU orphan after `timeout --foreground`) recorded.

## 今日目标 (Day 4)

1. **Goal 1 — WS listener skeleton + handshake.** Create
   `tools/qemu-src-patches/hw/display/esp_rgb_ws.c` and `esp_rgb_ws.h`.
2. **Goal 2 — Wire `ESP_RGB_WS_PORT` into `esp_rgb_init()` via `build-qemu.sh`.**
   Idempotent Python-heredoc patches add include + 3 hook calls to `esp_rgb.c`.
3. **Goal 3 — `tests/test_qemu_ws_handshake.py`.** Assert static markers +
   live RFC 6455 handshake. Target: ≥ 74 passed / 0 failed.

**Shipped at ef4dbf0** (2026-05-02, 3 commits).

## 完成状态 (evening review)

| Task | Status | Notes |
|---|---|---|
| `esp_rgb_ws.c` skeleton (listener + handshake, stubs for announce/broadcast) | ✅ | 186 LoC, `QIONetListener` + `QIOChannelWebsock`; closes channel after handshake in Day 4 |
| `esp_rgb_ws.h` public surface | ✅ | 3 hook declarations; includes `esp_rgb.h` |
| `build-qemu.sh` — install patch files + meson.build registration | ✅ | Idempotent `install -m 0644` + `sed` guard |
| `build-qemu.sh` — `esp_rgb.c` hook injection (Python heredoc, 4 sites) | ✅ | Marker `ESP_RGB_WS_PATCH`; skipped on subsequent runs |
| `run-demo.sh` + `run-qemu.sh` IDF PATH fix | ✅ | Source `export.sh` when `IDF_PATH` set but `idf.py` not on PATH |
| `tests/test_qemu_ws_handshake.py` (3 tests) | ✅ | Static marker checks + live WS handshake via `websockets.sync.client` |
| `pytest -q` baseline | ✅ | **74 passed, 0 failed, 0 skipped in 26.48 s** (Day 3 was 71+0+0) |

## Verification evidence

```
$ bash tools/build-qemu.sh 2>&1 | tail -5
[5/5] Linking target qemu-system-xtensa
[build-qemu] OK
QEMU emulator version 9.2.2

$ pytest tests/test_qemu_ws_handshake.py -v
tests/test_qemu_ws_handshake.py::test_esp_rgb_ws_patch_marker_in_source PASSED
tests/test_qemu_ws_handshake.py::test_esp_rgb_ws_source_files_installed PASSED
tests/test_qemu_ws_handshake.py::test_ws_handshake PASSED

$ pytest -q --tb=no 2>&1 | tail -2
======================== 74 passed, 1 warning in 26.48s ========================

$ git log --oneline -3
ef4dbf0 test: test_qemu_ws_handshake.py — assert WS listener + RFC 6455 handshake
1574632 feat(qemu): wire ESP_RGB_WS_PATCH into build-qemu.sh + fix IDF PATH detection
1aee4f4 feat(qemu): add esp_rgb_ws listener skeleton + handshake (no pixels yet)
```

## Key observations

- **QEMU WS port opens in ~15 ms** (device init fires before firmware boot).
  `QIONetListener` binds synchronously in `esp_rgb_ws_start()` which is called
  from `esp_rgb_init()` — a QEMU object-init callback, not a firmware callback.
  The WS test fixture `_wait_for_tcp_port()` with 15 s timeout was overkill;
  in practice the port is ready before Python's subprocess.Popen returns.
- **FB-008 (QEMU orphan) reproduced.** The `scope="module"` pytest fixture
  calls `proc.terminate()` then `proc.wait(timeout=5)`. With `-serial mon:stdio`,
  QEMU's monitor absorbs SIGTERM and keeps running. The orphan PID was visible
  in `ps aux`. Worked around by explicit `pkill -f qemu-system-xtensa` before
  each full suite run. Will fix in Day 5 by changing fixture to use SIGKILL
  or a different serial config.
- **`tools/qemu-src/` is gitignored.** All `esp_rgb.c` modifications must be
  encoded in `build-qemu.sh` as idempotent Python-heredoc patches; direct
  edits to the gitignored tree are not reproducible from a clean clone.

## 明日计划 (Day 5)

Per `docs/qemu-native-ws.md` §5 — Day 5: pixel fan-out:

1. Implement `esp_rgb_ws_announce_surface()` — build JSON header
   `{"w":W,"h":H,"format":"x8r8g8b8"}`, broadcast as WS text frame to all
   connected clients; reset per-client seq counters.
2. Implement `esp_rgb_ws_broadcast_frame()` — build 8-byte binary header
   `[u32 le seq][u32 le size]` + raw surface bytes; non-blocking write
   (drop on EAGAIN, increment `dropped_frames`); per-client seq counter.
3. Maintain a `QSLIST` of per-client state in `esp_rgb_ws.c`; no global
   single-client limit in v1.
4. Extend `tests/test_qemu_ws_handshake.py`:
   - New test `test_ws_json_header` — assert JSON header arrives as first
     text frame after connect.
   - New test `test_ws_first_pixel_frame` — assert at least one binary frame
     with 8-byte header + non-zero payload arrives within 3 s.
5. Fix QEMU orphan in the test fixture (FB-008 mitigation): use `SIGKILL`
   directly or pass `-serial null` to avoid the `mon:stdio` SIGTERM trap.

Stretch: decode the first pixel frame in Python, write to
`artifacts/qemu-ws-frame-001.png`, add `test_ws_frame_looks_like_lvgl`.

## 技术笔记

- `QIONetListener` + `QIOChannelWebsock` is the right QEMU-internal stack.
  `qio_channel_websock_handshake(wioc, callback, wioc, NULL)` triggers the
  RFC 6455 HTTP-Upgrade dance asynchronously; the callback fires on the
  main GMainLoop. No extra threads needed.
- Day 5 will add a `GList *clients` or `QSLIST` to `ESPRgbWsState` and
  store the post-handshake `QIOChannelWebsock *` there. `broadcast_frame()`
  will iterate the list, `qio_channel_write_all_full()` with `O_NONBLOCK`,
  drop on EAGAIN.
- `websockets.sync.client` (websockets ≥ 13) is available as v16.0 in the
  project `.venv`. The sync API is simpler than asyncio for pytest.
