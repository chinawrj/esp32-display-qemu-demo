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

### FB-006 (2026-04-30)
- **Skill**: agent / .vscode/mcp.json template
- **Category**: documentation
- **Summary**: Claude Code's `.mcp.json` rejects URL-only entries silently — must include `"type": "http"` (or `sse`/`command`).
- **Detail**: The repo's existing `.vscode/mcp.json` (consumed by GitHub Copilot CLI / VS Code) lists MCP servers as `{"url": "https://…"}`. When mirrored verbatim into a top-level `.mcp.json` for Claude Code 2.1.123, `claude mcp list` shows nothing (no error, no warning). Adding `"type": "http"` to each entry made `claude mcp get` reach `Status: ✓ Connected`. The Copilot URL-only form is therefore not portable; the agent template should call out the explicit-type requirement.
- **Workaround**: Always include `"type": "http"` (or sse/stdio command) in `.mcp.json`. Repo now has both `.vscode/mcp.json` (Copilot-style) and `.mcp.json` (Claude-style) side by side; tests/test_dual_cli_parity.py enforces the type field.
- **Priority**: medium

### FB-007 (2026-04-30)
- **Skill**: agent / project-scaffolding (.github/agents naming)
- **Category**: improvement
- **Summary**: Copilot CLI's `<name>.agent.md` filename convention produces an ugly agent name on Claude Code (`dev-workflow.agent` instead of `dev-workflow`).
- **Detail**: Claude Code derives an agent's display name from the filename stem. `.github/agents/dev-workflow.agent.md` therefore registers as agent `dev-workflow.agent` rather than `dev-workflow`. We worked around this by symlinking `.claude/agents/dev-workflow.md → ../../.github/agents/dev-workflow.agent.md` (rename happens at the symlink), and by adding an explicit `name: dev-workflow` line to the source frontmatter. Both CLIs honour the explicit `name:` if present, which is a more robust default than relying on filename derivation.
- **Workaround**: Always set `name:` in agent frontmatter explicitly; new agents added to `.github/agents/<name>.agent.md` should also have `tools/sync-claude-mirror.sh` re-run to drop the `.agent` infix in the Claude mirror.
- **Priority**: low

### FB-008 (2026-04-30)
- **Skill**: tools/run-qemu.sh + tmux-multi-shell
- **Category**: bug
- **Summary**: `timeout --foreground -k 5 90 idf.py qemu …` does not actually kill the spawned `qemu-system-xtensa`; child becomes an orphan to PID 1 and survives indefinitely.
- **Detail**: When Day 3 started, three `bash tools/run-qemu.sh 90 verify` invocations from the previous evening were still running with their `qemu-system-xtensa` children — ELAPSED 8h+. Reason: `timeout(1)` sends `SIGTERM` to its direct child (`idf.py`, a Python wrapper). `idf.py` shells out to `qemu-system-xtensa` via `subprocess.Popen`; on receiving `SIGTERM` `idf.py` exits, but the QEMU child is not in `idf.py`'s process-group destruction path, so it reparents to PID 1 and keeps writing pixels into `/tmp/esp32-rgb-vram.bin` until killed manually. The `RUN_QEMU_SENTINEL` echoes promptly (the `tee` pipeline closes), so an Agent watching for the sentinel believes the run finished cleanly — the next pytest run sees stale state.
- **Workaround**: After every `tools/run-qemu.sh` invocation, run `pkill -f qemu-system-xtensa` defensively before any test that touches `/tmp/esp32-rgb-vram.bin`. Long-term fix: change `run-qemu.sh` to either (a) launch `qemu-system-xtensa` directly (bypassing `idf.py qemu`) so `timeout` can SIGKILL the actual emulator, or (b) wrap the `idf.py qemu` call in `setsid bash -c '… ; pkill -P $$ qemu-system-xtensa'` so the orphan is reaped by its session leader. The `tmux-multi-shell` skill should also document the "orphan-after-sentinel" hazard so Agents don't trust the sentinel as proof the underlying device shut down.
- **Priority**: medium

### FB-009 (2026-05-02)
- **Skill**: project-scaffolding / tools/build-qemu.sh
- **Category**: improvement
- **Summary**: `tools/qemu-src/` is gitignored; direct edits to source files there are lost on clean clone — all patches must go through `build-qemu.sh`.
- **Detail**: Day 4 initially edited `tools/qemu-src/hw/display/esp_rgb.c` directly to add WS hook calls, but `tools/qemu-src/` is listed in `.gitignore`. Those edits are not reproducible from a fresh clone. The correct pattern (already used for `ESP_RGB_VRAM_FILE_PATCH`) is to encode the change as an idempotent Python-heredoc block in `build-qemu.sh`, guarded by a marker string (`grep -q "ESP_RGB_WS_PATCH" hw/display/esp_rgb.c`). Large new source files (e.g. `esp_rgb_ws.c`) go into the tracked `tools/qemu-src-patches/` tree and are copied in by `build-qemu.sh`.
- **Workaround**: Encode all `esp_rgb.c` modifications in `build-qemu.sh`; put new .c/.h files in `tools/qemu-src-patches/` (tracked by git).
- **Priority**: medium

### FB-010 (2026-05-02)
- **Skill**: automated-testing / pytest fixtures
- **Category**: bug
- **Summary**: pytest `scope="module"` fixture calling `proc.terminate()` on QEMU with `-serial mon:stdio` does not reliably kill the process; orphan QEMU survives until `pkill`.
- **Detail**: The `qemu_ws_proc` fixture in `tests/test_qemu_ws_handshake.py` launches QEMU with `-serial mon:stdio` (required so the QEMU monitor is connected and the guest serial output flows through stdio). QEMU's built-in monitor absorbs SIGTERM, so `proc.terminate()` + `proc.wait(timeout=5)` leaves QEMU running. Post-test `ps aux | grep qemu-system-xtensa` revealed the orphan. SIGKILL in the `except TimeoutExpired` branch fires correctly, but only after 5 s delay. Using `-serial null` instead of `-serial mon:stdio` for WS-only tests would avoid the issue, since the test doesn't need the UART serial output.
- **Workaround**: Preemptively `pkill -f qemu-system-xtensa` before each full suite run. Day 5 fix: change the fixture to pass `-serial null` (or `/dev/null`) instead of `mon:stdio`; this removes the monitor mux and allows SIGTERM to land on the QEMU main loop directly.
- **Priority**: medium

### FB-011 (2026-05-02)
- **Skill**: automated-testing / websockets client configuration
- **Category**: bug
- **Summary**: Python `websockets` default `max_size=1_048_576` (1 MB) silently rejects frames larger than 1 MB with a `1009 message too big` close frame.
- **Detail**: Day 5 `test_ws_first_pixel_frame` kept timing out. QEMU logs showed `broadcast_frame()` successfully sending seq=0..20 frames (500ms apart), but Python closed the connection with status 1009 before reading the first frame. The QEMU `esp_rgb` default surface is 800×600×4 = 1,920,000 bytes; the WS frame payload is 1,920,008 bytes — 83% above the `websockets` default 1 MB limit. The root cause was invisible from the server side: QEMU's `write_all` succeeded (TCP buffer accepted the data), but Python's library sent a `1009` close frame immediately on receipt. The test saw a `ConnectionClosedError` at `recv()` rather than a timeout-style error, which was misleading.
- **Workaround**: Add `max_size=None` to all `ws_connect()` / `websockets.connect()` calls whenever the server may send frames > 1 MB. For production use, set `max_size` to a calculated upper bound (`w * h * bpp + 16`) rather than `None`.
- **Priority**: medium
