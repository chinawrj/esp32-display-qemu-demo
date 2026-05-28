# Skill / Workflow Feedback

Running log of issues, gaps, and improvement ideas surfaced during the daily
iteration. Append-only — entries are not deleted once recorded.

This file is the canonical workflow-feedback log. Do not maintain duplicate
AI workflow feedback under `.copilot/` or `docs/`.

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
- **2026-05-28 update**: `.github/mcp.json` is now the only source; `.mcp.json`
  and `.vscode/mcp.json` are compatibility symlinks to it.
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

- **Priority**: medium

### FB-012 (2026-05-03)
- **Skill**: esp32-build-flash / QEMU VRAM read API
- **Category**: bug
- **Summary**: `address_space_rw(&s->vram_as, 0, ...)` returns all-zeros after `memory_region_add_subregion_overlap()` maps the same MemoryRegion into `sys_mem`.
- **Detail**: Day 6 first fix for blank WS frames used `address_space_rw(&s->vram_as, 0, MEMTXATTRS_UNSPECIFIED, pixels, pixel_size, false)`. Despite the VRAM file having content (15,120 nonzero pixels), this call returned all-zeros. Root cause: in `esp32.c`, `memory_region_add_subregion_overlap(sys_mem, 0x20000000, &s->rgb.vram, 0)` sets `s->vram->container = sys_mem` and triggers a QEMU-internal flatview invalidation for all address spaces that reference `s->vram`. The flatview for `s->vram_as` (whose root IS `s->vram`) gets invalidated; subsequent `address_space_rw()` calls recompute it with `s->vram` in a partially-added state, yielding zero-length or unmapped flatview entries. The result is a silent zero-fill of the read buffer. This is a QEMU API footgun: when a MemoryRegion is used as BOTH the root of a private AddressSpace AND a subregion of a container AddressSpace, the private flatview becomes unreliable after the container mapping.
- **Workaround**: Use `memory_region_get_ram_ptr(&s->vram)` + `memcpy()` to read VRAM. This bypasses address-space translation entirely and directly dereferences the host-side RAM pointer. Always valid for RAM regions created with `memory_region_init_ram()` or `memory_region_init_ram_from_file()`. The fix: `void *vram_raw = memory_region_get_ram_ptr(&s->vram); memcpy(pixels, vram_raw, pixel_size);`
- **Priority**: high

### FB-013 (2026-05-05)
- **Skill**: automated-testing / tools/run-stock-qemu.sh
- **Category**: improvement
- **Summary**: Stock scan smoke checks need sample-aware verification instead of station-only checks.
- **Detail**: During Day 27 regression, `wifi/scan` built and reached the QEMU mock scan path, but `run-stock-qemu.sh` still reported failures because its default verification expects STA connect/Got IP patterns in the QEMU serial log. For scan, the useful evidence is scan result handling (`QEMU_TEST` / AP records), and today that appeared in helper output rather than the serial-only `LOG_FILE` used by the verifier.
- **Workaround**: Treat scan runtime as a manual smoke check for now: inspect the full redirected log for `QEMU_TEST`, and use `SKIP_CONNECTED=1` when running scan. Long-term, add sample profiles or a verifier log that captures both QEMU serial and helper output.
- **Priority**: medium

### FB-014 (2026-05-08)
- **Skill**: esp32-build-flash / tools/build-stock-sample.sh
- **Category**: improvement
- **Summary**: Stock-sample builder lost extra component dependencies (`console`, `fatfs`, `esp_eth`, `app_trace`, `unity`, ...) and could not handle samples with custom `partitions_example.csv` referenced by relative path in `sdkconfig.defaults`.
- **Detail**: The wrapper-project generator hardcoded `REQUIRES esp_wifi esp_event esp_netif nvs_flash esp_wifi_qemu`, dropping every `PRIV_REQUIRES` listed in the sample's `main/CMakeLists.txt`. This worked for the four bare-WiFi samples (station/scan/softAP/tcp_client) but broke for `network/simple_sniffer`, `wifi/iperf`, and any sample that uses console/fatfs/etc. Additionally, `CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions_example.csv"` resolves relative to the wrapper-project root (not the sample dir), so custom partition CSVs were never visible to CMake.
- **Workaround**: Day-48 fix: extract `REQUIRES` + `PRIV_REQUIRES` from the sample's main `CMakeLists.txt` (multi-line tolerant awk), merge with our base set, de-dupe; symlink any `partitions*.csv` from sample root into the wrapper; symlink `idf_component.yml`; expose `EXTRA_SDKCONFIG_DEFAULTS` env var for sample-specific Kconfig overrides allowed by the zero-source-diff policy. Verified with a synthetic-sample pytest. Live `simple_sniffer` smoke now blocked only on offline `components-file.espressif.com` for the managed `pcap` dep.
- **Priority**: high

### FB-015 (2026-05-08)
- **Skill**: automated-testing / tests/conftest.py
- **Category**: bug
- **Summary**: `test_vram_snapshot_matches_uart_dump` could fail with a confusing pixel diff whenever the cached `/tmp/esp32-qemu-serial.log` and `/tmp/esp32-rgb-vram.bin` came from different boots (one with `ESP_RGB_VRAM_FILE` set, one without — or two boots minutes apart).
- **Detail**: The conftest's `qemu_log` fixture only managed the serial log's freshness and never exported `ESP_RGB_VRAM_FILE` itself, so the VRAM file at `/tmp/esp32-rgb-vram.bin` was a side-effect of whichever wrapper script the user happened to run last. When that side-effect came from a different boot than the cached log, the test compared apples to oranges and failed with a 2850-line pixel diff instead of a clean skip. This had been red across runs since at least Day 42.
- **Workaround**: Day-48 fix in `tests/conftest.py`: (1) define `DEFAULT_VRAM = /tmp/esp32-rgb-vram.bin`, (2) require both files exist + are fresh **and** their mtimes match within 5 min before reusing the cache (`_artifacts_paired` helper), (3) when conftest does boot QEMU itself, always export `ESP_RGB_VRAM_FILE` and unlink the stale VRAM first so the new pair is atomic. Plus a per-test stale-pairing guard in `test_qemu_vram_file.py` so externally-supplied `ESP32_QEMU_LOG` env values can't sneak a mismatch through. Full suite now 273 passed, 0 failed.
- **Priority**: medium

### FB-016 (2026-05-08)
- **Skill**: code-refactoring / Phase-E architecture
- **Category**: improvement
- **Summary**: Removing the last `ESP_ERR_NOT_SUPPORTED` in Phase E (`esp_wifi_80211_tx`) required factoring out a no-promisc TX helper to avoid double-tapping the sniffer callback. The pattern generalizes: any new Wi-Fi TX path must decide whether it is the *authoritative* frame (raw 802.11) or a *projection* (Ethernet wrap), and must not let both representations reach the sniffer for one logical TX.
- **Detail**: Naive implementation of `esp_wifi_80211_tx` would (a) deliver the raw 802.11 frame to `s_promisc_rx_cb`, then (b) decode DATA + LLC/SNAP into Ethernet and call `qemu_wifi_tx_raw()` to put it on the wire. But `qemu_wifi_tx_raw()` itself calls `qemu_promisc_deliver_eth()`, which fabricates a *new* 802.11 wrap around the same payload — sniffers would log every 80211_tx twice with different headers. Solution: introduce `qemu_wifi_tx_raw_no_promisc()` in `esp_wifi_netif.c`, exposed via `esp_wifi_private.h`, and have `80211_tx` use that for the Ethernet projection. Source-analysis test asserts the helper exists and does NOT call the deliver helper.
- **Workaround**: documented in BACKLOG Phase-E and in source comments above `qemu_wifi_tx_raw_no_promisc`.
- **Priority**: low

### FB-017 (2026-05-08)
- **Skill**: automated-testing / release-smoke-gate
- **Category**: improvement
- **Summary**: Extended `tools/run-basic-wifi-smoke.sh` to support a `build_only` mode for samples whose runtime depends on Kconfig SSID overrides or console UART input that the gate does not provision. Added `wifi/fast_scan` and `wifi/power_save` as build-only release samples to prove Phase A/B/C API surface is wide enough for the stock `esp_wifi.h` consumers.
- **Detail**: `wifi/iperf` would be a natural Phase-C runtime sample but its `idf_component.yml` requires `https://components-file.espressif.com/`, which the development host blocks. `wifi/fast_scan` builds clean (proves Phase A connection AP record + Phase B channel/auth/cipher are linkable) but defaults to SSID `myssid` from Kconfig — overriding via gate-only env would require either patching the sample or a complex Kconfig cascade. `wifi/power_save` builds clean (proves Phase C `esp_wifi_set_ps`) but its `EXAMPLE_GET_AP_INFO_FROM_STDIN` path needs interactive UART input. Solution: 4-field SAMPLES entry (`name|sample_dir|profile|run_or_build_only`) where `build_only` records build success as PASS and skips the runtime stage. The release contract (`docs/qemu-wifi-stock-samples.md`) gains a "Build-only coverage" subsection so users know what each sample actually proves.
- **Workaround**: none needed — `build_only` is the supported solution.
- **Priority**: medium

### FB-018 (2026-05-08)
- **Skill**: automated-testing
- **Category**: bug
- **Summary**: A pytest test that reads a long-running subprocess via `proc.stdout.readline()` inside a deadline-bounded `while time.monotonic() < deadline` loop will block indefinitely past the deadline whenever the child goes silent — `readline()` only checks the deadline *after* it returns. `tests/test_qemu_lwip_probe.py::test_lwip_probe_ok_in_serial` regularly ran 20+ minutes against a 360s deadline because of this anti-pattern.
- **Detail**: Fix is `select.select([fd], [], [], min(remaining, 1.0))` with `os.read` and a manual line-split buffer, plus a hard `proc.kill()` immediately after the read loop exits (so the `finally`-block `terminate(); wait(timeout=5)` cannot stall on a guest that ignores SIGTERM). With the fix, the test passes in ~12 s and worst-case runtime is bounded by the deadline. Lesson: any test that streams a long-running subprocess **must** use a non-blocking read (select / asyncio / dedicated reader thread), never a bare `.readline()` inside a deadline loop.
- **Workaround**: none — the select-based pattern is the correct solution.
- **Priority**: high

### FB-019 (2026-05-09)
- **Skill**: project-scaffolding / esp32-build-flash
- **Category**: improvement
- **Summary**: `examples/wifi/softap_sta` is the only stock sample that drives APSTA mode (STA + SoftAP simultaneously). Treating it as the canonical "single-image link-coverage" probe in the release smoke gate gave us the strongest no-runtime confirmation that Phase A + B + C + D-1 + D-2 of the QEMU Wi-Fi shim are mutually compatible.
- **Detail**: The sample builds drop-in via `tools/build-stock-sample.sh` with **zero source diff** (binary 0x66dc0, 60% free). Runtime is gated on a real upstream STA SSID and on lwIP NAPT, which the smoke gate does not provision today, so the entry is `build_only`. Rationale for adding it even though we already have separate runtime coverage for getting_started/{station,softAP}: those each prove one mode at a time, leaving open the possibility of a regression where some Phase-A/B/C state symbol shadows a Phase-D AP table symbol (or vice versa) when the firmware imports both. softap_sta is the cheapest single-link probe for that class of regression.
- **Workaround**: none.
- **Priority**: medium

### FB-020 (2026-05-09)
- **Skill**: esp32-build-flash / tools/build-stock-sample.sh
- **Category**: bug
- **Summary**: ESP-IDF only consults `SDKCONFIG_DEFAULTS` to seed the *initial* `sdkconfig`; once the wrapper project's `sdkconfig` exists, later changes to overlay files (or to `EXTRA_SDKCONFIG_DEFAULTS`) are silently ignored on rebuild.
- **Detail**: Day-51 promoted `wifi/power_save` to runtime via a new `tools/sample-overlays/power_save.sdkconfig` that flips `CONFIG_PM_ENABLE=n`. The first build after wiping `build_qemu/` honoured the overlay, but a later run that only wiped `build_qemu/` (and not `_qemu_wrap_power_save/`) kept the prior `CONFIG_PM_ENABLE=y` and the sample crashed in `esp_light_sleep_start` again. Symptom is silent: build succeeds, runtime fails with the pre-overlay behaviour. Manually deleting `_qemu_wrap_<sample>/` fixes it. Generalises to any overlay change for any sample.
- **Workaround**: Day-51 fix in `tools/build-stock-sample.sh` — sha1-hash the resolved `SDKCONFIG_DEFAULTS` chain, store it next to the wrapper's `sdkconfig` as `.sdkconfig_defaults.sha1`, and on every invocation wipe `sdkconfig` + `build_qemu/` whenever the hash changes. Subsequent `idf.py reconfigure` then picks up the new chain.
- **Priority**: high

### FB-021 (2026-05-09)
- **Skill**: project-scaffolding / esp_wifi_qemu shim
- **Category**: bug
- **Summary**: `esp_wifi_set_inactive_time` previously rejected any `sec < 10` for **all** interfaces, but `esp_wifi.h` only requires `sec >= 10` for AP (`WIFI_IF_AP`); for STA the threshold is `sec >= 3`. The wrong threshold caused stock `wifi/power_save` to abort on boot (`CONFIG_EXAMPLE_WIFI_BEACON_TIMEOUT` defaults to 6s, Kconfig range 6..30).
- **Detail**: When porting an ESP-IDF API into the QEMU shim, **always read the official validation rules in `esp_wifi.h` carefully** — uniform thresholds across interfaces are a code smell and frequently violate the spec. Day-51 fix: read the per-interface min from a local `(ifx == WIFI_IF_AP) ? 10 : 3` ternary and only reject below that. Source-analysis test in `tests/test_qemu_wifi_sta.py::test_phase_c_inactive_time_per_interface_storage` now asserts the per-interface min is enforced.
- **Workaround**: documented in source comments above `esp_wifi_set_inactive_time`.
- **Priority**: medium

### FB-022 (2026-05-09)
- **Skill**: project-scaffolding / esp_wifi_qemu coverage
- **Category**: missing-feature
- **Summary**: QEMU does not model the ESP32 RTC / DPORT registers needed by `esp_light_sleep_start` → `rtc_sleep_pd` → `rtc_sleep_init`. Any stock sample that enables `CONFIG_PM_ENABLE` + `CONFIG_FREERTOS_USE_TICKLESS_IDLE` will trip a `LoadStorePIFAddrError` in the idle task as soon as `vApplicationSleep` lands.
- **Detail**: Day-51 found this while promoting `wifi/power_save` (whose `sdkconfig.defaults` enables PM + tickless idle + light sleep) to runtime in the smoke gate. Workaround for now is to disable PM in the per-sample sdkconfig overlay — this preserves zero source diff because the overlay channel is allowed by the policy, and the `esp_wifi_set_ps()` API (the Wi-Fi-side knob the sample is actually meant to demonstrate) still exercises end-to-end. Long-term, modelling the ESP32 RTC peripheral well enough for `rtc_sleep_pd` to no-op (or stub `esp_light_sleep_start` directly) would let any stock light-sleep sample run unmodified. Track as a Phase-F item if a stock sample explicitly needs it.
- **Workaround**: per-sample `CONFIG_PM_ENABLE=n` + `CONFIG_FREERTOS_USE_TICKLESS_IDLE=n` overlay.
- **Priority**: low

### FB-023 (2026-05-10)
- **Skill**: tools/build-stock-sample.sh
- **Category**: bug
- **Summary**: After Day-51's SDKCONFIG_DEFAULTS-hash invalidator runs `rm -rf "${BUILD_DIR}"`, the next file write to `${BUILD_DIR}/../_qemu_wrap_<sample>/.sdkconfig_defaults.sha1` fails with "No such file or directory".
- **Detail**: WRAP_DIR was defined as `${BUILD_DIR}/../_qemu_wrap_<sample>`. Linux resolves path components left-to-right at the open(2) call, so once `build_qemu/` no longer exists the kernel can't traverse `build_qemu/..` to reach the sibling wrap dir, even though `..` is purely lexical to humans. Symptom on Day 52 was that any sample whose overlay had changed since the previous build (fast_scan, power_save, softap_sta, roaming_app) failed at the hash-write step with no further explanation.
- **Workaround**: define `WRAP_DIR="$(dirname "${BUILD_DIR}")/_qemu_wrap_<sample>"` so the path is purely lexical and never includes the deleted intermediate component.
- **Priority**: medium

### FB-024 (2026-05-10) — RESOLVED 2026-05-11 (Day 53)
- **Skill**: tools/build-stock-sample.sh
- **Category**: missing-feature
- **Summary**: The wrapper-project generator does not propagate `EMBED_FILES` / `EMBED_TXTFILES` into the synthetic `main/` dir, blocking any stock sample whose `main/CMakeLists.txt` embeds binary blobs (currently `wifi/wifi_eap_fast/`, `wifi/wifi_enterprise/`).
- **Detail**: Day 52 sweep found both samples error at CMake parse time: "Cannot find source file: .../_qemu_wrap_<sample>/main/ca.pem". The current wrapper only symlinks the .c/.h sources from the original `main/` and forwards `INCLUDE_DIRS`, so CMake looks for the cert/PAC files relative to the wrap dir and fails. Same pattern would block any future sample that embeds binary assets via the build system.
- **Workaround**: enhance the awk pass that copies the original `main/CMakeLists.txt`'s component clauses to also symlink every `EMBED_*` argument into `WRAP_MAIN_DIR/`. Keep the original argument list verbatim so `idf_component_register` finds them at the same relative path.
- **Resolution (Day 53)**: extended the existing `extract_requires_kw` awk helper with two extra invocations (`EMBED_FILES`, `EMBED_TXTFILES`) and re-emit the clauses in the generated wrap CMakeLists with **absolute** paths back to the sample's real `main/`.  Absolute paths bypass the relative-to-component-CMakeLists resolution entirely, so no symlinking is needed.  Both EAP samples now build clean and were promoted into the basic-wifi smoke gate, finishing 15/15 build-only coverage of `examples/wifi/**`.
- **Priority**: low

### FB-025 (2026-05-11)
- **Skill**: tools/build-stock-sample.sh
- **Category**: convention
- **Summary**: When propagating component-register clauses into the wrap component, prefer absolute paths over symlinks for any path-valued argument (EMBED_FILES, EMBED_TXTFILES, KCONFIG, KCONFIG_PROJBUILD, ...).
- **Detail**: ESP-IDF's `idf_component_register` resolves relative path arguments against the component's own `CMakeLists.txt`, so a symlink would have to live in the wrap component's `main/` and CMake's `target_sources` / `EmbedTextFiles` would still re-resolve through the symlink — fine on Linux but adds a layer of indirection that breaks if tooling later inspects the component manifest.  Absolute paths emitted directly into the wrap CMakeLists are simpler, idempotent across `rm -rf BUILD_DIR` cycles, and match how `INCLUDE_DIRS "${SAMPLE_MAIN_DIR}"` already works in the same script.
- **Workaround**: continue to use `"${SAMPLE_MAIN_DIR}/${file}"` form for all path-valued component clauses introduced in the future (e.g. LDFRAGMENTS, WHOLE_ARCHIVE files).
- **Priority**: low

### FB-026 (2026-05-11) — RESOLVED Day 54
- **Skill**: tools/build-stock-sample.sh
- **Category**: bug
- **Summary**: In `extract_requires_kw`'s awk pass, the `\)`-strip regex fires before the keyword-boundary regex, leaking the next keyword's value into the previous keyword's argument list when a continuation line contains both.
- **Detail**: A real-world trigger is `examples/protocols/sockets/udp_client/main/CMakeLists.txt`, whose `idf_component_register(...)` looks like `SRCS "udp_client.c"\n                       INCLUDE_DIRS ".")`. Captured under `SRCS`, the continuation line first matches the `\)` regex; awk strips from `)` onward but the prior side-effects already printed the leading whitespace + `INCLUDE_DIRS "."`. Net result: `INCLUDE_DIRS .` leaks into `SRCS`. Same shape would corrupt any sample where a multi-line clause's terminal line bears another keyword.
- **Resolution (Day 54)**: in both branches of the extractor (continuation `in_kw=1` and initial-match), reorder so the keyword-boundary regex test runs first; only after no keyword match does the `\)` strip fire. Apostrophes were removed from in-line awk comments to keep the script embeddable inside bash single quotes. Pinned by a new regression test `test_build_stock_sample_keyword_before_close_paren` in `tests/test_stock_sample_build.py`.
- **Priority**: medium

### FB-027 (2026-05-11) — RESOLVED Day 56
- **Skill**: tools/build-stock-sample.sh
- **Category**: missing-feature
- **Summary**: The textual awk extractor cannot evaluate CMake variable expansion, so any sample whose `idf_component_register` references `PRIV_REQUIRES ${requires}` (with `list(APPEND requires ...)` earlier in the file) loses its requires list.
- **Detail**: Concretely blocked `protocols/esp_http_client` (uses `set(requires …); list(APPEND requires …); PRIV_REQUIRES ${requires}`), plus the closely-related implicit-all-on-`main` case used by `protocols/icmp_echo` and `protocols/smtp_client` (no REQUIRES declared at all; samples reach `esp_console.h` / `mbedtls/platform.h` because ESP-IDF grants `main` access to every built component when no REQUIRES list is given — a privilege our wrap suppresses by always emitting a non-empty REQUIRES list).
- **Resolution (Day 56)**: introduce a probe-configure helper that runs `idf.py -C <sample> -B <wrap>/.probe -DIDF_TARGET=<t> reconfigure` on the unmodified sample and parses `project_description.json` (`build_component_info.main.{reqs,priv_reqs}` plus the top-level `build_components` list).  The probe result overrides the textual extract.  When the original sample's `main/CMakeLists.txt` declares no REQUIRES/PRIV_REQUIRES, the wrap widens REQUIRES to the full probed `build_components` list to reproduce implicit-all.  Cached on a content hash of `main/CMakeLists.txt + main/idf_component.yml`.  Silently falls back to textual extraction when `idf.py` is unavailable or the probe fails (preserves unit-test behaviour with stubbed `idf.py`).  Pinned by `test_basic_wifi_smoke_includes_day56_protocol_samples`, `test_build_stock_sample_resolves_project_dir_in_embed_txtfiles`, `test_build_stock_sample_symlinks_sample_root_data_dirs`.
- **Priority**: medium

### FB-028 (2026-05-13) — RESOLVED Day 55
- **Skill**: tools/build-stock-sample.sh
- **Category**: bug
- **Summary**: The wrapper-project generator silently dropped any non-`.` entry in the original sample's `INCLUDE_DIRS` keyword list, leaving samples whose `main/CMakeLists.txt` lists `INCLUDE_DIRS "include"` (e.g. `protocols/https_request`) unable to find headers under `main/include/` from sibling `main/*.c`.
- **Detail**: Day-54 wrap emitted a single hard-coded `INCLUDE_DIRS "${SAMPLE_MAIN_DIR}"` line, regardless of what the original sample listed.  `https_request/main/CMakeLists.txt` has `INCLUDE_DIRS "include"`, and `main/time_sync.c:#include "time_sync.h"` lives at `main/include/time_sync.h`; the wrap saw no `include/` entry and the compile failed at `time_sync.c:27: fatal error: time_sync.h: No such file or directory`.  Same shape would block any future stock sample that uses a `main/include/` subdir layout.
- **Resolution (Day 55)**: extend the existing `extract_requires_kw` helper with an INCLUDE_DIRS pass, then re-emit each entry in the wrap component CMakeLists with an absolute path under `${SAMPLE_MAIN_DIR}`.  `.` and `${SAMPLE_MAIN_DIR}` are deduplicated against the default entry; absolute paths in the original list pass through unchanged.  Pinned by `test_build_stock_sample_propagates_include_dirs_subdirs`.
- **Priority**: medium

### FB-029 (2026-05-13) — RESOLVED Day 57
- **Skill**: tools/build-stock-sample.sh
- **Category**: missing-feature
- **Summary**: Stock samples that embed binary blobs via `target_add_binary_data(<target> ...)` at the project CMakeLists.txt level (not via `EMBED_FILES`/`EMBED_TXTFILES` inside `idf_component_register`) lose their assets because the wrap-script only inspects `main/CMakeLists.txt`.
- **Detail**: Day-55 probe found `protocols/mqtt/ssl` failing at link with `undefined reference to '_binary_mqtt_eclipseprojects_io_pem_start'`.  Its project `CMakeLists.txt` calls `target_add_binary_data(mqtt_ssl.elf "main/mqtt_eclipseprojects_io.pem" TEXT)` — the asset is wired against the *project* target, not the component.  Our wrap project has a different elf name (`<sample>.elf` via `project(<sample>)`) and never re-emits the binary-data call, so the symbol the source references is never produced.  Same pattern likely blocks several other TLS-bearing samples in `protocols/mqtt/**` and `protocols/https_*/**`.
- **Resolution (Day 57)**: After emitting `project(${SAMPLE_PROJ_NAME})` in the wrap's top-level CMakeLists.txt, the script greps the original sample's CMakeLists.txt for `target_add_binary_data(...)` lines and re-emits them verbatim with one rewrite: the first double-quoted argument (the asset path) is rewritten from a relative path into an absolute path under `${SAMPLE_DIR}`.  CMake variable refs (e.g. `${CMAKE_PROJECT_NAME}.elf`) and already-absolute paths pass through unchanged.  Since the wrap uses the same `project(<sample_proj_name>)` as the stock sample, hardcoded `<proj>.elf` target names resolve to the same elf — no target rewrite needed.  Pinned by `test_build_stock_sample_propagates_project_target_add_binary_data`.  Unlocked `mqtt_ssl`, `mqtt_wss`, `mqtt_ssl_mutual_auth`, and (via Day-56 data-dir symlinking) `https_x509_bundle` — 32→36 smoke entries.  Day-58 FB-031 generalized this from "only target_add_binary_data" to "every non-trivial line after project()".
- **Priority**: medium

### FB-030 (2026-05-14) — RESOLVED Day 58
- **Skill**: tools/build-stock-sample.sh
- **Category**: missing-feature
- **Summary**: Stock samples that ship local components under `<sample>/components/<comp_name>/` (e.g. `protocols/http_server/captive_portal` ships `dns_server`, `system/console/advanced` ships `cmd_system`/`cmd_nvs`/`cmd_wifi`) fail to configure with `Failed to resolve component '<comp>' required by component 'main': unknown name`.  ESP-IDF's component discovery only scans the project's own directory by default, and the wrap's project dir is NOT the sample dir.
- **Detail**: ESP-IDF reads `<project>/components/*/` plus any extras listed in the CMake `EXTRA_COMPONENT_DIRS` variable (which must be set BEFORE `include($ENV{IDF_PATH}/tools/cmake/project.cmake)` because the variable is consumed during component discovery).  Day-54..57 wrap script never set this, so anything the sample's main lists in PRIV_REQUIRES that lives under `<sample>/components/` was invisible.  Day-56's sample-root data-dir symlink loop explicitly skipped `components/` — correct (we don't want to *clone* the sample's component tree into the wrap), but we still needed to tell ESP-IDF where to find it.
- **Resolution (Day 58)**: When `${SAMPLE_DIR}/components/` exists, the script emits `list(APPEND EXTRA_COMPONENT_DIRS "${SAMPLE_DIR}/components")` in the wrap's top-level CMakeLists.txt between `cmake_minimum_required(...)` and `include(...)`.  This makes ESP-IDF discover the sample's local components without copying or symlinking them.  Pinned by `test_build_stock_sample_injects_extra_component_dirs`.  Unlocked `protocols/http_server/captive_portal` and `system/console/advanced` (plus opportunistic broader sweep additions).
- **Priority**: medium

### FB-031 (2026-05-14) — RESOLVED Day 58
- **Skill**: tools/build-stock-sample.sh
- **Category**: missing-feature
- **Summary**: FB-029 only propagated `target_add_binary_data()` lines from the sample's top-level CMakeLists.txt.  Other project-level calls — `idf_component_get_property` + `target_sources`, `target_link_libraries`, `partition_table_get_partition_info`, etc. — were silently dropped.
- **Detail**: `protocols/mqtt/custom_outbox` injects a C++ override into the system `mqtt` component via four project-level CMake lines:
    ```cmake
    idf_component_get_property(mqtt mqtt COMPONENT_LIB)
    target_sources(${mqtt} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/main/custom_outbox.cpp)
    idf_component_get_property(pthread pthread COMPONENT_LIB)
    target_link_libraries(${mqtt} ${pthread})
    ```
  Without these, the link fails with `undefined reference to outbox_enqueue/outbox_dequeue/...`.  Same pattern likely blocks any sample that uses the project-level override hooks documented in the ESP-IDF build system guide.
- **Resolution (Day 58)**: Generalized FB-029's propagation block from "only `target_add_binary_data` lines" to "every non-blank, non-comment line strictly AFTER `project(...)` in the sample's top-level CMakeLists.txt".  Each propagated line has these CMake-variable refs rewritten to the literal `${SAMPLE_DIR}` absolute path: `${CMAKE_CURRENT_SOURCE_DIR}`, `${CMAKE_CURRENT_LIST_DIR}`, `${PROJECT_DIR}`, `${project_dir}` — because the wrap dir is NOT the sample dir.  The Day-57 quoted-asset-path rewrite for `target_add_binary_data` is preserved as a special case.  Pinned by `test_build_stock_sample_substitutes_cmake_current_source_dir`.  Unlocked `protocols/mqtt/custom_outbox`.
- **Priority**: medium

### FB-032 (2026-05-13) — RESOLVED Day 59
- **Skill**: tools/build-stock-sample.sh
- **Category**: bug
- **Summary**: `protocol_examples_common` was unconditionally injected into `EXTRA_COMPONENT_DIRS`, but for samples whose `idf_component.yml` pulls in `examples/ethernet/basic/components/ethernet_init`, the two components redefine the same `EXAMPLE_USE_INTERNAL_ETHERNET` / `EXAMPLE_USE_SPI_ETHERNET` / `EXAMPLE_USE_DM9051` / `EXAMPLE_USE_W5500` Kconfig symbols.  kconfgen treats the choice-symbol collision as fatal: "default selection EXAMPLE_USE_W5500 of <choice EXAMPLE_ETHERNET_TYPE> is not contained in the choice".  This blocked the entire `examples/network/*` tree (simple_sniffer, bridge, vlan_support, eth2ap).
- **Detail**: The duplicate-symbol issue is intentional in upstream ESP-IDF — both components want to be usable standalone, and a project picks at most one.  Our wrap script forced both visible at once.
- **Resolution (Day 59)**: Gate the `protocol_examples_common` injection on actual source-level use: only append it to `EXTRA_COMPONENT_DIRS` when `grep -rqE 'protocol_examples_common|example_connect|example_disconnect|example_configure_stdin_stdout' ${SAMPLE_DIR}/main/` matches.  Samples that bring their own networking stack (ethernet_init, manual provisioning, etc.) no longer collide.  Pinned by `test_build_stock_sample_gates_protocol_examples_common_injection`.  Unlocked 4 network samples plus 5 opportunistic additions (http_server/advanced_tests, roaming_11kvr, three wifi_aware/nan_*) — 65→74 smoke entries.
- **Priority**: medium
