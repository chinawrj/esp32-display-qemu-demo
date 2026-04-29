"""Shared fixtures for the QEMU verification test suite.

The QEMU run is expensive (~15 s wall-clock per invocation), so we reuse a
recent serial log when possible:

* If ``ESP32_QEMU_LOG`` env var is set, that log is used as-is (no boot).
* Otherwise we look at ``/tmp/esp32-qemu-serial.log``. If it exists and is
  fresher than ``MAX_LOG_AGE_S`` seconds, we reuse it.
* Otherwise we invoke ``bash tools/run-qemu.sh 45 verify`` once and use the
  resulting log for the whole session.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG = Path("/tmp/esp32-qemu-serial.log")
MAX_LOG_AGE_S = 30 * 60  # 30 minutes — firmware is deterministic, log can be reused


def _log_is_fresh(path: Path) -> bool:
    if not path.is_file():
        return False
    age = time.time() - path.stat().st_mtime
    return age <= MAX_LOG_AGE_S and path.stat().st_size > 0


@pytest.fixture(scope="session")
def qemu_log() -> Path:
    """Return a Path to a populated QEMU serial log.

    Reuses a recent log if available, else boots QEMU once for the whole
    session via ``tools/run-qemu.sh``.
    """
    override = os.environ.get("ESP32_QEMU_LOG")
    if override:
        path = Path(override)
        if not path.is_file():
            pytest.skip(f"ESP32_QEMU_LOG points to missing file: {path}")
        return path

    if _log_is_fresh(DEFAULT_LOG):
        return DEFAULT_LOG

    bin_path = PROJECT_ROOT / "build" / "esp32-display-qemu-demo.bin"
    if not bin_path.is_file():
        pytest.skip(
            f"Firmware not built ({bin_path} missing). Run 'idf.py build' first."
        )
    if not shutil.which("qemu-system-xtensa") and not os.environ.get("IDF_PATH"):
        pytest.skip(
            "qemu-system-xtensa not in PATH and IDF_PATH not set; "
            "source $IDF_PATH/export.sh first."
        )

    script = PROJECT_ROOT / "tools" / "run-qemu.sh"
    # 'verify' mode exits non-zero on failure; we still want the log either
    # way so individual tests can produce per-check failures.
    subprocess.run(
        ["bash", str(script), "75", "verify"],
        cwd=PROJECT_ROOT,
        check=False,
        timeout=180,
    )

    if not DEFAULT_LOG.is_file() or DEFAULT_LOG.stat().st_size == 0:
        pytest.fail(f"QEMU run produced no log at {DEFAULT_LOG}")
    return DEFAULT_LOG


@pytest.fixture(scope="session")
def qemu_log_text(qemu_log: Path) -> str:
    return qemu_log.read_text(errors="replace")
