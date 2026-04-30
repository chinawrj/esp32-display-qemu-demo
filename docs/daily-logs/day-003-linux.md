# Day 3 (Linux) — 2026-04-30 (evening)

Third Linux dev day. Day 2 cemented dual-CLI parity (Copilot CLI ↔ Claude
Code) at 67 → today's 71 green. Day 3 turns the page on **NEXT-001 — the
QEMU-native FB→Chrome WebSocket transport**: build the patched QEMU on
this Linux box, unblock the last 4 hardware-dependent tests, and write
the design spike that Days 4–6 will implement.

## 昨日回顾 (Day 2)

- ✅ Dual-CLI parity (1 agent + 7 skills + 2 MCP servers) shipped at b9f8b7f.
- ✅ `tests/test_dual_cli_parity.py` adds 19 assertions, 0.04 s.
- ✅ `pytest -q` 67 passed, **2 skipped, 0 failed** (down from 4 skipped — Day 14
  VRAM-file tests now wired through `tools/qemu-src`).
- 📝 FB-006 (`.mcp.json` needs `"type": "http"`) and FB-007 (Claude derives
  agent name from filename) recorded.

## 今日目标 (Day 3)

1. **Goal 1 — Build patched QEMU on this Linux box.** `bash tools/build-qemu.sh`
   from the tmux `build` window; verify
   `tools/qemu-src/build/qemu-system-xtensa --version`; re-run `pytest -q`,
   target ≥ 71 passed / 0 skipped.
2. **Goal 2 — Author `docs/qemu-native-ws.md`** (NEXT-001 design spike) with
   wire protocol, build-vs-host-bridge decision, annotated `esp_rgb.c`
   walkthrough, risk register, Day 4–6 ship plan.
3. **Goal 3 — Working-tree hygiene.** Decide fate of untracked files; update
   `.gitignore` for the Copilot-CLI npm noise; keep
   `docs/copilot-cli-issue-draft.md` tracked.

**Shipped at f4d6fd4** (2026-04-30 evening, single commit).

## 完成状态 (evening review)

| Task | Status | Notes |
|---|---|---|
| `bash tools/build-qemu.sh` (binary already up to date from a prior run) | ✅ | 0.633 s no-op rebuild via existing `tools/qemu-src/build/`. Patched QEMU 9.2.2 confirmed. |
| `qemu-system-xtensa --version` | ✅ | `QEMU emulator version 9.2.2` — `ESP_RGB_VRAM_FILE_PATCH` already in source. |
| `pytest -q` after Day-1's 4 skips | ✅ | **71 passed, 1 warning, 0 skipped, 0 failed in 25.82 s** — exactly the planned target. The 2 leftover Day-2 skips (`test_log_replay`, `test_log_producer`) cleared because the build window already had a fresh complete `/tmp/esp32-qemu-serial.log` (1535 lines, demo banner present). |
| `docs/qemu-native-ws.md` design spike | ✅ | 220 LoC, 6 sections: §1 wire protocol (WS frames `[u32 le seq][u32 le size][bytes]` + JSON header), §2 build-vs-host-bridge (chose A: WS server inside `esp_rgb.c`), §3 annotated `esp_rgb.c` callsites, §4 risk register, §5 Day 4–6 ship plan with named first-3-commits, §6 out of scope. |
| `.gitignore` cleanup | ✅ | Added `node_modules/`, `package.json`, `package-lock.json`, `sdkconfig.old`. |
| Track `docs/copilot-cli-issue-draft.md` | ⏸ | Pending the user-approved commit. The file is the deliverable from Day 2's FB-006/007 work and should ship; left untracked so it lands in today's commit message. |

## Verification evidence

```
$ tools/qemu-src/build/qemu-system-xtensa --version | head -2
QEMU emulator version 9.2.2
Copyright (c) 2003-2024 Fabrice Bellard and the QEMU Project developers

$ time pytest -q | tail -3
======================== 71 passed, 1 warning in 25.82s ========================
real    0m26.258s

$ git status --short
 M .gitignore
?? docs/copilot-cli-issue-draft.md
?? docs/daily-logs/day-003-linux.md
?? docs/qemu-native-ws.md
```

(After `.gitignore` was patched, `node_modules/`, `package.json`,
`package-lock.json`, `sdkconfig.old` no longer appear in `git status` —
the gitignore rules took effect.)

## Bugs / footguns surfaced today

- **`tools/run-qemu.sh` orphaned overnight.** When this Day 3 session
  started, three `qemu-system-xtensa` instances + their `bash run-qemu.sh
  90 verify` parents from yesterday were still running (8h+ ELAPSED).
  Rationale: `timeout --foreground -k 5 90 idf.py qemu …` runs `idf.py`
  (a Python script) under `timeout(1)`. On `SIGTERM`, the IDF wrapper
  exits but the QEMU child it spawned via `subprocess.Popen` becomes
  orphaned to PID 1 and never receives the signal. The `tee` and the
  shell pipeline exit, the `RUN_QEMU_SENTINEL` echoes, and the wall-clock
  appears to be 90 s — but a leaked QEMU keeps writing into
  `/tmp/esp32-rgb-vram.bin` indefinitely. **Recorded as FB-008.**

## 明日计划 (Day 4)

Per `docs/qemu-native-ws.md` §5 — three commits:

1. `feat(qemu): add esp_rgb_ws listener skeleton + handshake (no pixels yet)`
2. `feat(qemu): wire ESP_RGB_WS_PORT into esp_rgb_init via build-qemu patch`
3. `test: tests/test_qemu_ws_handshake.py — assert WS handshake + JSON header`

Stretch: if the listener-only skeleton lands by lunch, start `esp_rgb_ws_broadcast_frame()`
(the pixel fan-out path) and ship a smoke-test PNG into `artifacts/qemu-ws-frame-001.png`.

## 技术笔记

- **The chosen architecture is "WS server inside the QEMU device,"** not a
  host-side Python bridge. Rationale: we are already patching `esp_rgb.c`
  and building our own QEMU; adding ~250–350 LoC of `esp_rgb_ws.c` is
  consistent with that strategy and removes the host-side Python
  long-running process from the Quickstart path. Existing
  `ESP_RGB_VRAM_FILE` path stays for back-compat.
- **R1 (stalled-Chrome backpressure)** is the single most important risk in
  the design. Mitigation: `qio_channel_set_blocking(ioc, false, NULL)` on
  every accepted client, drop in-flight frames on `EAGAIN`, never queue
  more than one pending frame per client. seq still increments for
  non-stalled peers.
- **R5 (FB-005 unblock path)**: once `tests/cdp/test_qemu_direct_canvas.py`
  ships in Day 6, the legacy UART-base64 dependency in
  `tests/cdp/test_log_replay.py` and `tests/fb_server/test_log_producer.py`
  becomes optional — they get tagged `pytest.mark.legacy` so default
  `pytest -q` no longer needs `/tmp/esp32-qemu-serial.log` to be
  pre-warmed.
- **NEXT-001 v1 sends full frames.** ~55 MB/s loopback at the
  worst-case 800×600×4 @ 30 fps; for the actual 240×135 demo it's
  ~2 MB/s. Diff/JPEG is queued to v2.
