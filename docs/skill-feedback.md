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
