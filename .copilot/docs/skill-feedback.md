# esp32-display-qemu-demo — Skill & Workflow Feedback

> This file is maintained by the AI Agent during daily development.
> Each item records a concrete observation about skills, workflows, or tools.
> These feedback items help improve the agent-builder for future projects.
>
> **Format**: Append new items at the bottom. Never delete existing items.

---

## Feedback Items

<!-- Example:
### FB-001 (2026-04-19)
- **Skill**: tmux-multi-shell
- **Category**: improvement
- **Summary**: Sentinel pattern should support custom timeout per command
- **Detail**: Long-running `idf.py build` sometimes exceeds the default 60s sentinel timeout. Need a way to specify per-command timeout in the sentinel pattern.
- **Workaround**: Manually set `TIMEOUT=300` before calling `tmux_exec`.
- **Priority**: medium
-->

<!-- AI: Append new feedback items below this line -->

### FB-001 (2026-04-29)
- **Skill**: environment-setup
- **Category**: bug
- **Summary**: Skill assumes ESP-IDF at `~/esp/esp-idf` but local setup uses `~/esp-idf`
- **Detail**: The environment-setup skill's example commands hardcode `~/esp/esp-idf/export.sh`. On this machine ESP-IDF lives at `/Users/rjwang/esp-idf` (no `esp/` subdir). The skill should detect via `$IDF_PATH` env var or probe both locations.
- **Workaround**: Override path manually in `.env.sh`: `source /Users/rjwang/esp-idf/export.sh`.
- **Priority**: medium

### FB-002 (2026-04-29)
- **Skill**: project-scaffolding
- **Category**: bug
- **Summary**: `INCLUDE_DIRS "include"` requires the directory to physically exist
- **Detail**: Generated `main/CMakeLists.txt` lists `INCLUDE_DIRS "include"` but doesn't create `main/include/`. CMake errors with confusing message about missing component. An empty `components/` directory also broke the build.
- **Workaround**: After scaffolding, create `main/include/.gitkeep`; remove empty `components/` dir if no custom components.
- **Priority**: high

### FB-003 (2026-04-29)
- **Skill**: project-scaffolding
- **Category**: improvement
- **Summary**: Generated `idf_component_register()` should NOT include explicit `REQUIRES esp_log esp_system`
- **Detail**: ESP-IDF v5.5 auto-links `esp_common` group; explicit `REQUIRES esp_log` causes "component esp_log not found" error. Empty REQUIRES works fine.
- **Workaround**: Remove `REQUIRES` line from main/CMakeLists.txt for Hello World projects.
- **Priority**: high

### FB-004 (2026-04-29)
- **Skill**: environment-setup
- **Category**: improvement
- **Summary**: First-time ESP-IDF setup needs explicit `install.sh` step
- **Detail**: Just sourcing `export.sh` is insufficient on a fresh checkout — Python deps (click, pyyaml, esptool, etc.) must be installed first via `~/esp-idf/install.sh esp32`. Without it, `idf.py` fails with `ModuleNotFoundError: No module named 'click'`.
- **Workaround**: Add a verification step: `python -c "import click" || run install.sh`.
- **Priority**: high

### FB-005 (2026-04-29)
- **Skill**: tmux-multi-shell
- **Category**: bug
- **Summary**: Sentinel sometimes matches stale buffer content from previous commands
- **Detail**: When the build pane has prior `_EXIT_N` patterns, `grep | tail -1` may return an old code from a different sentinel if the new command output hasn't appeared yet. Worse, `tail -5` piping HIDES errors and `${PIPESTATUS[0]}` is needed instead of `$?` to capture upstream exit codes.
- **Workaround**: (a) Use unique sentinel per command (timestamp); (b) `clear` pane before new command; (c) when piping, use `${PIPESTATUS[0]}` not `$?`.
- **Priority**: medium

### FB-006 (2026-04-29)
- **Skill**: esp32-build-flash (for QEMU workflow)
- **Category**: missing
- **Summary**: `idf_tools.py install qemu-xtensa` requires multiple brew libs (pixman, libgcrypt, glib...) on macOS
- **Detail**: ESP-IDF's bundled QEMU dynamically links Homebrew dylibs and removes itself if any are missing. The skill should warn users to `brew install qemu` (which pulls all transitive deps) before attempting QEMU verification, or install pixman + libgcrypt + glib + pcre2 + ... explicitly.
- **Workaround**: `brew install qemu` first, then `idf_tools.py install qemu-xtensa`.
- **Priority**: high

### FB-007 (2026-04-29)
- **Skill**: esp32-build-flash
- **Category**: documentation
- **Summary**: `idf.py qemu` CLI flags differ from documented examples
- **Detail**: ESP-IDF v5.5 `idf.py qemu` accepts `--graphics` as a boolean flag (no `--graphics=no` or `--graphics=off`). For headless serial-only runs use `--qemu-extra-args=-nographic`. Also: `idf.py qemu` re-runs CMake configure even when build is up-to-date — for short-timeout verify scripts pre-build first or budget ≥30 s.
- **Workaround**: Pre-build with `idf.py build` before `idf.py qemu`, and pass headless via `--qemu-extra-args=-nographic`. Use ≥30 s timeout in verify scripts.
- **Priority**: medium

### FB-008 (2026-04-29)
- **Skill**: project-scaffolding (LVGL component integration)
- **Category**: missing-feature
- **Summary**: LVGL demo callback signatures + Kconfig dependencies aren't surfaced
- **Detail**: To use `lv_demo_benchmark`, you must:
  (a) `CONFIG_LV_USE_DEMO_BENCHMARK=y` in sdkconfig.defaults,
  (b) bump `CONFIG_LV_MEM_SIZE_KILOBYTES` from default 64 to ≥128,
  (c) enable Montserrat 12/16/24 fonts (the demo uses them),
  (d) `lv_demo_benchmark_set_end_cb` takes `void(*)(const lv_demo_benchmark_summary_t*)`, NOT `void(*)(void)` — easy mis-write.
  A "drop-in LVGL demo" recipe in the skill would save iteration time.
- **Workaround**: see commit c87b131 sdkconfig.defaults + main.c for working template.
- **Priority**: medium

### FB-009 (2026-04-29)
- **Skill**: tmux-multi-shell
- **Category**: improvement
- **Summary**: `capture-pane -p -S -1000` truncates very long ESP-IDF build output (≥1800 lines)
- **Detail**: A clean ESP-IDF build with LVGL has 1835 ninja steps. `-S -1000` only shows the tail. Skill should recommend `-S -3000` minimum for ESP-IDF + LVGL builds, or write to file (`-S - > /tmp/build.log`) for forensic analysis on failure.
- **Workaround**: `tmux capture-pane -t SESS:WIN -p -S -8000` for first-time LVGL builds; `-S -3000` for incremental.
- **Priority**: low

### FB-010 (2026-04-29)
- **Skill**: project-scaffolding (LVGL config)
- **Category**: bug
- **Summary**: ESP32 has only ~180KB DRAM bss budget; a 64KB static framebuffer overflows `dram0_0_seg`
- **Detail**: Putting `static lv_color_t s_fb[240*135]` (≈64KB RGB565) in .bss alongside default LVGL static heap (LV_MEM_SIZE_KILOBYTES=128) caused linker error "section .dram0.bss will not fit in region dram0_0_seg". The skill should explicitly recommend heap_caps_malloc for large display buffers on ESP32 (not -S3/-P4 with PSRAM).
- **Workaround**: `heap_caps_malloc(DISP_BYTES, MALLOC_CAP_DEFAULT | MALLOC_CAP_8BIT)` in app_main; release with free() if needed.
- **Priority**: high

### FB-011 (2026-04-29)
- **Skill**: automated-testing
- **Category**: missing-feature
- **Summary**: No standard pattern for "capture LVGL framebuffer over UART for visual diff/snapshot test"
- **Detail**: For QEMU-only projects (no real LCD), the only way to get a screenshot is firmware-driven UART dump. Skill could codify: (a) FULL render mode + single buffer, (b) base64 sentinel-bracketed payload, (c) 60-char-per-line for log line atomicity, (d) host decoder. Reusable across LVGL projects.
- **Workaround**: see commit 6aa7fb1 (main.c dump_framebuffer_base64 + run-qemu.sh extraction).
- **Priority**: medium

### FB-012 (2026-04-29)
- **Skill**: esp32-build-flash
- **Category**: documentation
- **Summary**: Stale "FAILED:" lines in tmux scrollback can mislead build-status detection
- **Detail**: When grepping `tmux capture-pane -S -3000` for FAILED/error, output from a previous (failed) build remains in scroll history and gets matched. Sentinel-based exit-code detection (`__BUILD_EXIT_$?__`) is the only reliable signal, not text grep. Skill already advocates sentinels but should explicitly warn against grep-based status checks.
- **Workaround**: always trust sentinel exit code, treat grep matches as advisory only.
- **Priority**: low

### FB-013 (2026-04-29)
- **Skill**: project-scaffolding / environment-setup
- **Category**: missing-feature
- **Summary**: Project lacked `requirements.txt` + venv bootstrap docs from day 1.
- **Detail**: Day 5 was the first time we used Python tooling (Pillow). Had to create `.venv` and `requirements.txt` ad-hoc. Should be part of initial scaffold so all agents know where Python deps belong.
- **Workaround**: Created `requirements.txt` and committed; added Pillow 12.2.0.
- **Priority**: medium

### FB-014 (2026-04-29)
- **Skill**: tmux-multi-shell
- **Category**: bug
- **Summary**: Long sentinel strings can be wrapped by tmux at column boundary, splitting the marker.
- **Detail**: Sent `__RUN_1777428138___EXIT_$?` and tmux line-wrapped it as `__RUN_1777428138___\nEXIT_0`. grep for the joined form fails. Mitigation: prefer compact sentinels (≤16 chars including suffix) or grep with multiline awareness.
- **Workaround**: Fell back to checking command output file existence + size + exit-code-via-`__SENTINEL_EXIT_N` substring.
- **Priority**: low

### FB-015 (2026-04-29)
- **Skill**: automated-testing
- **Category**: improvement
- **Summary**: RGB565 LE → RGB888 needs bit-replication, not naive shift, to match LVGL's reference output.
- **Detail**: Day 4's quick decoder used `(r5 << 3)` (zero-fills LSBs); proper conversion is `(r5 << 3) | (r5 >> 2)` to preserve full 0..255 range. Diff was max 7 / mean 3.5 per channel — visually identical but byte-mismatch breaks any visual-regression hash test. Document the canonical conversion in the skill.
- **Workaround**: Decoder uses bit-replication; baseline screenshot regenerated from this.
- **Priority**: medium
