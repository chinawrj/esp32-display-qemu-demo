# Skill / Workflow Feedback

Running log of issues, gaps, and improvement ideas surfaced during the daily
iteration. Append-only — entries are not deleted once recorded.

### FB-001 (2026-04-30)
- **Skill**: tools/run-qemu.sh + daily-iteration
- **Category**: improvement
- **Summary**: `idf.py qemu` always re-runs build action; first run after a
  source touch can blow past a 75 s timeout.
- **Detail**: `run-qemu.sh 75 verify` failed cold today because `idf.py qemu`
  triggered a CMake reconfigure and consumed the whole budget before QEMU
  even started. Existing `conftest.py` already uses 180 s for the first
  boot, which works.
- **Workaround**: invoke `run-qemu.sh 150 verify` (or higher) when running
  manually after source/sdkconfig touches; tests are unaffected.
- **Priority**: low

### FB-002 (2026-04-30)
- **Skill**: workflow / firmware-design
- **Category**: documentation
- **Summary**: Re-invoking lv_demo_benchmark() after end_cb is unsafe — corrupts TLSF heap.
- **Detail**: Day 23 attempt to keep LVGL pipeline live by re-calling lv_demo_benchmark() in a loop crashed in lv_free/get_prop_core. Even creating a fresh screen via lv_screen_load(lv_obj_create(NULL)) after end_cb led to dangling-pointer panics on subsequent lv_label_set_text / lv_bar_set_value calls. The benchmark's deferred teardown timers continue running inside lv_timer_handler post end_cb. Worked around by painting RGB565 directly into the QEMU VRAM mmap (bypasses LVGL entirely).
- **Workaround**: Direct VRAM writes via QEMU_RGB_VRAM_ADDR pointer; no LVGL calls post end_cb.
- **Priority**: medium

### FB-003 (2026-04-30)
- **Skill**: tools/run-demo.sh + project-scaffolding
- **Category**: bug
- **Summary**: `for arg in "$@"; do … shift; done` arg-parser silently drops the next token.
- **Detail**: `tools/run-demo.sh` originally parsed `--duration 90` with a `for` loop and called `shift` inside the body. `for` iterates over a snapshot of `$@` taken at loop entry, so `shift` does not advance the iterator — the body sees `--duration` as `$1` for both iterations and `DURATION` ended up as the literal string `--duration`. The bug was masked on macOS because tests were green there for unrelated reasons, and only surfaced on Linux Day 1. Replaced with `while [ $# -gt 0 ]; do case "$1" in …; esac; shift; done`.
- **Workaround**: Use the while-loop pattern above; never combine `for arg in "$@"` with in-body `shift`.
- **Priority**: medium

### FB-004 (2026-04-30)
- **Skill**: tools/run-qemu.sh + daily-iteration
- **Category**: bug
- **Summary**: `timeout --foreground "$DUR" idf.py qemu …` did not terminate QEMU on Linux within the budget.
- **Detail**: On Linux Day 1 `bash tools/run-qemu.sh 45 verify` ran for 4+ minutes past the 45 s window because QEMU absorbed SIGTERM (likely via its monitor on `-serial mon:stdio`) and `timeout` does not escalate to SIGKILL without `-k`. Fix: pass `-k 5` so a hard signal fires 5 s after SIGTERM. macOS' BSD `gtimeout` behaves the same — fixed both branches.
- **Workaround**: `timeout --foreground -k 5 "$DUR" …` (now applied in run-qemu.sh).
- **Priority**: medium

### FB-005 (2026-04-30)
- **Skill**: tests/cdp/test_live_qemu_canvas.py + environment-setup
- **Category**: bug
- **Summary**: Skip predicate accepted IDF-managed qemu-xtensa, which lacks the project-local `esp_rgb` VRAM-file patch.
- **Detail**: `_qemu_available()` returned True if `shutil.which("qemu-system-xtensa")` succeeded. On Linux Day 1 the IDF-managed qemu-xtensa is on `PATH` after sourcing `export.sh`, so the live-canvas test ran but `/tmp/esp32-rgb-vram.bin` was never created (Day 14 mmap export only exists in `tools/qemu-src/`), and the test failed by timeout. Tightened the predicate to require `tools/qemu-src/build/qemu-system-xtensa` specifically. Once NEXT-001 (QEMU-native FB→Chrome WebSocket) lands, this constraint can be relaxed.
- **Workaround**: Skip predicate now requires the locally-built patched binary.
- **Priority**: low (correct skip behavior restored)
