"""Live end-to-end smoke test — drives ``tools/run-demo.sh --auto-test``.

This is the most complete test in the suite: it boots QEMU with the
VRAM mmap export, starts the host fb_server in raw-vram mode, opens
real Chromium via Playwright, and asserts the canvas shows actual LVGL
content (≥ 8 distinct colours, matching the Day-19 frozen snapshot).

Skipped automatically when ``IDF_PATH`` is not set or the QEMU binary
is missing — the rest of the suite still runs.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_DEMO = PROJECT_ROOT / "tools" / "run-demo.sh"
ARTIFACT = PROJECT_ROOT / "artifacts" / "run-demo-canvas.png"


def _qemu_available() -> bool:
    if not os.environ.get("IDF_PATH"):
        return False
    if shutil.which("qemu-system-xtensa"):
        return True
    local = PROJECT_ROOT / "tools" / "qemu-src" / "build" / "qemu-system-xtensa"
    return local.exists() and os.access(local, os.X_OK)


@pytest.mark.skipif(not _qemu_available(), reason="qemu-system-xtensa or IDF_PATH missing")
def test_run_demo_auto_test_succeeds():
    if not (PROJECT_ROOT / "build" / "esp32-display-qemu-demo.bin").exists():
        pytest.skip("project not built — run 'idf.py build' first")
    pytest.importorskip("playwright.sync_api")

    if ARTIFACT.exists():
        ARTIFACT.unlink()

    result = subprocess.run(
        ["bash", str(RUN_DEMO), "--auto-test", "--duration", "90"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        env={**os.environ, "LOG_FILE": "/tmp/run-demo-serial.log"},
    )
    combined = result.stdout + "\n" + result.stderr
    assert result.returncode == 0, f"run-demo.sh failed:\n{combined}"
    assert "[auto-test]" in combined, combined
    assert "FAIL" not in combined, combined
    assert ARTIFACT.exists() and ARTIFACT.stat().st_size > 0
