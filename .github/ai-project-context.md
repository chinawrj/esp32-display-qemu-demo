# AI Project Context

This file is the canonical short context for coding agents working in this
repository. Keep AI-facing project state under `.github/`; compatibility files
outside `.github/` should be symlinks or generated mirrors only.

## North Star

Any stock ESP-IDF Wi-Fi sample under `$IDF_PATH/examples/**` that uses
`esp_wifi_*`, `esp_now_*`, `esp_netif_*`, or lwIP networking should build, and
where supported run, on this QEMU Wi-Fi simulator without modifying upstream
`.c` or `.h` files.

Allowed deviations for stock samples:

- Generated wrapper `CMakeLists.txt` files.
- `sdkconfig.defaults` / `EXTRA_SDKCONFIG_DEFAULTS` overlays.
- QEMU simulator patches and the local `esp_wifi_qemu` component.

Do not solve stock-sample compatibility by patching upstream sample source.

## Current State

- Main app: LVGL benchmark in ESP32 QEMU, framebuffer capture, browser viewers,
  and QEMU-backed Wi-Fi status/data-plane demos.
- Wi-Fi shim: `components/esp_wifi_qemu`.
- QEMU patches: `tools/qemu-src-patches`.
- Stock sample wrapper: `tools/build-stock-sample.sh`.
- Stock smoke gate: `tools/run-basic-wifi-smoke.sh`.
- Current documented coverage: 90 stock samples in the smoke gate, including
  runtime coverage for station, scan, softAP, fast_scan, power_save,
  `tcp_client`, and `udp_client`.

## Required Working Rules

- Prefer `.venv/bin/python` / `.venv/bin/pytest` for Python commands.
- Keep `.github` as the only source of AI workflow content.
- Use `tools/sync-claude-mirror.sh` after adding or renaming agents, skills, or
  compatibility entrypoints.
- Use `tools/validate-ai-workflow.sh` after editing `.github/agents`,
  `.github/skills`, `.github/instructions`, `.github/mcp.json`, or mirror
  logic.
- Do not edit `tools/qemu-src/` directly; it is ignored and regenerated. Put
  tracked QEMU source additions in `tools/qemu-src-patches/` or encode
  idempotent patching in `tools/build-qemu.sh`.
- Before changing stock-sample wrapper behavior, inspect
  `tests/test_stock_sample_build.py` and update regression tests with the new
  invariant.

## Fast Verification

```bash
.venv/bin/pytest tests/test_dual_cli_parity.py -q
.venv/bin/pytest tests/test_stock_sample_build.py -q
bash tools/validate-ai-workflow.sh
```

Full ESP-IDF/QEMU runtime verification requires `IDF_PATH`, patched QEMU, and
the project Python environment:

```bash
LOG_DIR=/tmp/qemu-wifi-smoke bash tools/run-basic-wifi-smoke.sh 60
```

## Pointers

- Agent: `.github/agents/dev-workflow.agent.md`
- Skills: `.github/skills/*/SKILL.md`
- Path instructions: `.github/instructions/*.instructions.md`
- MCP config source: `.github/mcp.json`
- Workflow feedback log: `.github/workflow-feedback.md`
- Daily plan template: `.github/daily-plan-template.md`
- Historical and detailed roadmap: `BACKLOG.md`
