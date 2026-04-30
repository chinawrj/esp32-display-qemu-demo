# Day 1 (Linux) — 2026-04-30

First development day on Linux (Ubuntu 24.04, kernel 6.17). Prior days were on
macOS 12; everything up through `2642796 docs: add BACKLOG.md` was produced
there. The headline backlog item **NEXT-001 (QEMU-native FB→Chrome)** is
explicitly scoped to Linux, so today is the bringup day that unblocks it.

## 昨日回顾 (last macOS commit)
- ✅ macOS pipeline shipped: file-mmap VRAM bridge, fb_server raw-vram mode,
  CDP smoke test, run-demo.sh one-command live demo, BACKLOG.md authored.
- 🚚 Switched host: macOS 12 → Linux (Ubuntu 24.04, x86_64).

## 今日目标 (Day 1 Linux bringup)

1. **Install host build deps + ESP-IDF v5.5+** at `$HOME/esp-idf` (matches
   `.env.sh`'s `ESP_IDF_PATH`).
2. **Reach baseline parity**: `idf.py build` zero-warning + `tools/run-qemu.sh
   45 verify` 10/10 + `pytest -q` green (≥50 passed) on Linux.
3. **Stand up tmux session** per project rules and confirm the build/flash/
   monitor windows work end-to-end.

NEXT-001 design work stays in BACKLOG until baseline is green — no new
features today.

## 风险与依赖
- ESP-IDF v5.5 install size (~2 GB) + first-time toolchain download.
- Playwright chromium (~100 MB) needed for CDP tests.
- `tools/build-qemu.sh` is *not* required on Linux (IDF-managed `qemu-xtensa`
  works); skip unless NEXT-001 needs source patches.

## 验收检查点
- [x] apt deps installed
- [x] `.venv/` populated, `playwright install chromium` done
- [x] `$HOME/esp-idf` ready, `idf.py --version` works after `. export.sh`
- [x] tmux session `esp32-display-qemu-demo` with 6 windows
- [x] `idf.py build` clean, zero warnings (798,912 byte binary)
- [x] `bash tools/run-qemu.sh 45 verify` → 10/10
- [x] `pytest -q` → 48 passed, 4 skipped, 0 failed
- [x] Day 1 log committed

## Day 1 回顾 (Evening Review)

### 完成状态
| Task | Status | Notes |
|------|--------|-------|
| apt deps + ESP-IDF v5.5.4 + qemu-xtensa | ✅ | One-time toolchain fetch ~30 min |
| Python `.venv` + Playwright Chromium | ✅ | Parallel with ESP-IDF clone |
| tmux session bringup | ✅ | 6 windows: edit/build/flash/monitor/setup/idf-install |
| `idf.py set-target esp32` + `idf.py build` | ✅ | 632 s for set-target (component manager fetch); zero warnings |
| `bash tools/run-qemu.sh 45 verify` | ✅ | 10/10 markers green |
| `pytest -q` | ✅ | 48 passed, 4 skipped — full parity (the 4 skips are all the locally-built-QEMU-only tests) |

### Bugs found & fixed
- **`tools/run-demo.sh` arg parser** — `for arg in "$@"; do … shift; done` is broken; replaced with `while [ $# -gt 0 ]; do … shift; done`. Recorded as FB-003.
- **`tools/run-qemu.sh` timeout grace** — `timeout --foreground` did not terminate QEMU on Linux because QEMU absorbs SIGTERM via `-serial mon:stdio`. Added `-k 5` so the hard signal fires after a 5 s grace. Recorded as FB-004.
- **`tests/cdp/test_live_qemu_canvas.py` skip predicate** — accepted any `qemu-system-xtensa` on PATH but the test actually requires the project-local patched build (Day 14 `esp_rgb` VRAM mmap export). Tightened predicate to require `tools/qemu-src/build/qemu-system-xtensa`. Recorded as FB-005. Will relax once NEXT-001 lands.

### Lessons / 技术笔记
- ESP-IDF first-time `set-target` is a long one-shot (component manager pulls lvgl + esp_lcd_qemu_rgb). Plan for ~10 min, not 1 min.
- Linux `timeout` and macOS `gtimeout` both need `-k <secs>` to kill processes that swallow SIGTERM.
- Strict sentinel regex `^SENTINEL_[0-9]+\s*$` avoids false hits when the typed command echoes back into the tmux pane.
- `bash` `for arg in "$@"` + body `shift` is a silent footgun — use `while [ $# -gt 0 ]` instead.

### 明日计划 (Day 2)
- Begin **NEXT-001**: design QEMU-native FB→Chrome path (WebSocket inside `esp_rgb` device or host-side reader compatible with IDF-managed qemu-xtensa). Goal: relax the FB-005 skip so all 52 tests run on Linux without rebuilding QEMU from source.
- Capture a short design note in `docs/` and a feasibility spike before touching code.
