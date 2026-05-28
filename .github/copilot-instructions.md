# Repository Instructions for GitHub Copilot

Use `.github/ai-project-context.md` as the canonical project summary before
making changes. Keep all AI workflow source files in `.github`; root-level,
`.claude`, and `.vscode` AI files should be compatibility symlinks or generated
mirrors.

The primary goal is stock ESP-IDF sample compatibility on the QEMU Wi-Fi
simulator with zero upstream `.c` / `.h` source edits. Only wrapper CMake and
sdkconfig overlay channels are allowed for stock samples.

Follow the project agent and skills when relevant:

- `.github/agents/dev-workflow.agent.md`
- `.github/skills/tmux-multi-shell/SKILL.md`
- `.github/skills/esp32-build-flash/SKILL.md`
- `.github/skills/automated-testing/SKILL.md`

Use the repository virtualenv for Python:

```bash
.venv/bin/python
.venv/bin/pytest
```

Run focused validation after workflow edits:

```bash
bash tools/validate-ai-workflow.sh
```

Run focused stock-sample infrastructure tests after wrapper or smoke-gate edits:

```bash
.venv/bin/pytest tests/test_stock_sample_build.py -q
```
