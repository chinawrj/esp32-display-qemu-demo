# Day 2 (Linux) — 2026-04-30 (evening)

Second Linux dev day. Day 1 brought the box up to baseline parity
(48 tests green); today widens the dev surface so the project's
custom workflow can be driven equally from **GitHub Copilot CLI**
and **Anthropic Claude Code CLI**.

## 昨日回顾 (Day 1)

- ✅ Linux toolchain + ESP-IDF + qemu-xtensa + Playwright bringup.
- ✅ Three bugs fixed and recorded as FB-003/004/005.
- ✅ `pytest -q` green (48 passed, 4 skipped, 0 failed).
- 🧱 4 skips remain — all "needs locally-built patched QEMU" (Day-14
  `esp_rgb` mmap export); will be unblocked by NEXT-001 on Day 3+.

## 今日目标 (Day 2)

1. **Dual-CLI parity**: make the 1 agent + 7 skills + 2 MCP servers
   discoverable by Claude Code 2.1.123 *without* duplicating sources.
2. **Lock the parity in CI**: add a pytest case that fails as soon as
   any mirror, frontmatter, or `.mcp.json` shape regresses.
3. **Document the dual-CLI workflow** in `README.md` so contributors
   know which root each CLI reads from.

## 完成状态 (evening review)

| Task | Status | Notes |
|---|---|---|
| `.claude/skills/` mirror | ✅ | 7 directory symlinks → `.github/skills/<name>` |
| `.claude/agents/` mirror | ✅ | `dev-workflow.md` symlink (drops `.agent` infix) |
| `.mcp.json` at repo root | ✅ | Required `"type": "http"` per Claude Code MCP spec |
| Backfill `name:` on agent frontmatter | ✅ | Added `name: dev-workflow` to canonical source |
| `tools/sync-claude-mirror.sh` | ✅ | Idempotent helper for new skills/agents |
| `README.md` "Dual-CLI" section | ✅ | Added before License with discovery commands |
| `tests/test_dual_cli_parity.py` | ✅ | 19 assertions; runs in 0.04 s |
| Live verification with `claude` CLI | ✅ | `claude agents` lists `dev-workflow`; `claude --print` lists 7 skills; `claude mcp get esp-component-registry` shows ✓ Connected |
| `pytest -q` | ✅ | 67 passed (was 48), 4 skipped, 0 failed |

## Verification evidence

```
$ claude agents
5 active agents
Project agents:
  dev-workflow · inherit
Built-in agents:
  Explore · haiku
  general-purpose · inherit
  Plan · inherit
  statusline-setup · sonnet

$ claude mcp get esp-component-registry
  Scope: Project config (shared via .mcp.json)
  Status: ✓ Connected
  Type: http
  URL: https://components.espressif.com/mcp

$ claude --print --permission-mode bypassPermissions \
    "Output exactly the names of project-level Skills, one per line"
tmux-multi-shell
environment-setup
daily-iteration
code-refactoring
project-scaffolding
esp32-build-flash
automated-testing
```

## Bugs / footguns surfaced today

- Claude Code's `.mcp.json` rejects URL-only entries silently — they
  parse but never connect. Must include `"type": "http"` (or `sse`,
  or `command` for stdio). The `.vscode/mcp.json` URL-only form that
  Copilot CLI accepts is not portable. **Recorded as FB-006.**
- Claude Code derives an agent's name from its filename. The
  Copilot-CLI convention `<name>.agent.md` produces `dev-workflow.agent`
  on Claude. Symlinking with renamed targets (`<name>.md`) sidesteps
  this without touching the canonical source name. **Recorded as FB-007.**

## 明日计划 (Day 3)

- Begin **NEXT-001** investigation: the QEMU-native FB→Chrome WebSocket
  transport that lets the live-canvas test (and 3 VRAM-file tests)
  run on Linux without a locally patched QEMU build. Day 3 = design
  spike + decision note in `docs/`; coding starts Day 4.
- Optional cleanup: gitignore for `node_modules/`, `package*.json`,
  `sdkconfig.old` (untracked since Day 1).

## 技术笔记

- The Agent Skills open standard (`name` + `description` frontmatter,
  Markdown body) is the **same** for both CLIs, so format-level porting
  cost is zero. All porting work was structural (paths + transport
  config + filename rename via symlink).
- Symlinks are committed verbatim by Git as mode 120000 blobs. They
  work transparently on Linux/macOS dev hosts. Windows contributors
  would need `git config core.symlinks true` + admin/dev mode (not in
  scope for this project).
- `tests/test_dual_cli_parity.py` adds **19 parametrised assertions**
  that take 0.04 s — cheap enough to keep alongside the boot/decoder
  suite and guarantee the mirror never silently rots.
