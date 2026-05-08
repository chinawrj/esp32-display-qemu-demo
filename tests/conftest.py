"""Shared fixtures for the QEMU verification test suite.

The QEMU run is expensive (~15 s wall-clock per invocation), so we reuse a
recent serial log when possible:

* If ``ESP32_QEMU_LOG`` env var is set, that log is used as-is (no boot).
* Otherwise we look at ``/tmp/esp32-qemu-serial.log``. If it exists and is
  fresher than ``MAX_LOG_AGE_S`` seconds, we reuse it.
* Otherwise we invoke ``bash tools/run-qemu.sh 180 verify`` once and use the
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
DEFAULT_VRAM = Path("/tmp/esp32-rgb-vram.bin")
MAX_LOG_AGE_S = 30 * 60  # 30 minutes — firmware is deterministic, log can be reused
# Maximum allowed delta between the QEMU serial log mtime and the VRAM file
# mtime when reusing cached artifacts.  If the two files diverge by more than
# this many seconds, they came from different boots and pairwise tests like
# test_vram_snapshot_matches_uart_dump will produce confusing failures.  We
# rebuild both rather than risk a stale mismatch.
MAX_PAIR_SKEW_S = 5 * 60


def _log_is_fresh(path: Path) -> bool:
    if not path.is_file():
        return False
    age = time.time() - path.stat().st_mtime
    return age <= MAX_LOG_AGE_S and path.stat().st_size > 0


def _artifacts_paired(log: Path, vram: Path) -> bool:
    """Both artifacts present, fresh, and produced by the same boot.

    The VRAM file is much larger than the log and is closed later in the
    QEMU teardown sequence, so its mtime is normally a few seconds *after*
    the log's.  Allow a generous skew to absorb that.
    """
    if not (_log_is_fresh(log) and vram.is_file() and vram.stat().st_size > 0):
        return False
    skew = abs(vram.stat().st_mtime - log.stat().st_mtime)
    return skew <= MAX_PAIR_SKEW_S


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

    if _artifacts_paired(DEFAULT_LOG, DEFAULT_VRAM):
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
    # Day-34: The LVGL benchmark markers appear at firmware t≈11000ms.  At
    # nominal 18x slowdown that needs ~198 wall seconds.  Add a 56% margin
    # (300 s → 16 667 ms firmware) so variance in QEMU emulation speed does
    # not produce an incomplete log that conftest then caches as "fresh".
    #
    # Day-48: always export ESP_RGB_VRAM_FILE so the serial log and the
    # VRAM dump are produced by the SAME boot.  Without this, a previous
    # run that did set the env can leave a stale VRAM file alongside a
    # newer log, making test_vram_snapshot_matches_uart_dump fail with a
    # confusing pixel diff instead of skipping cleanly.
    env = os.environ.copy()
    env.setdefault("ESP_RGB_VRAM_FILE", str(DEFAULT_VRAM))
    # Drop the stale VRAM file so the next boot creates a fresh one whose
    # mtime is paired with the new log.
    try:
        DEFAULT_VRAM.unlink()
    except FileNotFoundError:
        pass
    subprocess.run(
        ["bash", str(script), "300", "verify"],
        cwd=PROJECT_ROOT,
        check=False,
        timeout=390,
        env=env,
    )

    if not DEFAULT_LOG.is_file() or DEFAULT_LOG.stat().st_size == 0:
        pytest.fail(f"QEMU run produced no log at {DEFAULT_LOG}")
    return DEFAULT_LOG


@pytest.fixture(scope="session")
def qemu_log_text(qemu_log: Path) -> str:
    return qemu_log.read_text(errors="replace")
