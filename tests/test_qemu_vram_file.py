"""Regression test for the Day-18 ``ESP_RGB_VRAM_FILE`` opt-in patch.

Verifies:

* The patched local QEMU binary (built via ``tools/build-qemu.sh``) carries
  the ``ESP_RGB_VRAM_FILE_PATCH`` marker in its source.
* When ``ESP_RGB_VRAM_FILE`` is unset, behaviour is unchanged (covered by the
  rest of the suite).
* When ``ESP_RGB_VRAM_FILE`` is set during a QEMU boot, the named file is
  created, sized to at least ``ESP_RGB_MAX_VRAM_SIZE = 800*600*4`` bytes
  (page-aligned), and survives the run as a regular file we can ``mmap``.

The boot is the expensive part, so we reuse the framebuffer dump that the
existing ``run-qemu.sh`` invocation produced (driven by ``conftest.py``).
The file-size check itself is fast: it just stats whatever VRAM file the
last invocation wrote.
"""
from __future__ import annotations

import os
import pathlib

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ESP_RGB_C = PROJECT_ROOT / "tools" / "qemu-src" / "hw" / "display" / "esp_rgb.c"
EXPECTED_MIN_SIZE = 800 * 600 * 4  # ESP_RGB_MAX_VRAM_SIZE


def test_esp_rgb_patch_marker_present():
    """``build-qemu.sh`` must idempotently inject the VRAM-file shim."""
    if not ESP_RGB_C.exists():
        pytest.skip("QEMU source not cloned — run tools/build-qemu.sh first")
    text = ESP_RGB_C.read_text()
    assert "ESP_RGB_VRAM_FILE_PATCH" in text, (
        "patch marker missing from esp_rgb.c — re-run tools/build-qemu.sh"
    )
    assert "memory_region_init_ram_from_file" in text


def test_vram_file_created_when_env_set():
    """If a prior boot was run with ``ESP_RGB_VRAM_FILE`` set, the file exists
    and is large enough to back the full 800x600x4 surface (mmap rounds up
    to the next host page)."""
    vram_path = os.environ.get("ESP_RGB_VRAM_FILE", "/tmp/esp32-rgb-vram.bin")
    p = pathlib.Path(vram_path)
    if not p.exists():
        pytest.skip(
            f"{vram_path} not present — run "
            "`ESP_RGB_VRAM_FILE=/tmp/esp32-rgb-vram.bin bash tools/run-qemu.sh 150 verify` first"
        )
    sz = p.stat().st_size
    assert sz >= EXPECTED_MIN_SIZE, (
        f"VRAM file too small: {sz} < {EXPECTED_MIN_SIZE}"
    )
    # Must be a regular file (not a tmpfs/special node) so host tools can mmap it.
    assert p.is_file()
    # Sanity: readable by the current user.
    with p.open("rb") as f:
        head = f.read(16)
    assert len(head) == 16


def test_vram_snapshot_matches_uart_dump():
    """Day-19: the firmware writes a frozen snapshot at y=200 on flush #80,
    mirroring exactly what the existing UART base64 path dumps. Bytes must
    match. This is the first end-to-end check that LVGL pixels reach the
    QEMU VRAM region."""
    import base64

    vram_path = pathlib.Path(os.environ.get("ESP_RGB_VRAM_FILE", "/tmp/esp32-rgb-vram.bin"))
    log_path = pathlib.Path(os.environ.get("ESP32_QEMU_LOG", "/tmp/esp32-qemu-serial.log"))
    if not vram_path.exists() or not log_path.exists():
        pytest.skip("VRAM file or QEMU log not present — run instrumented boot first")

    # Skip if the log has no FB= lines — it was produced by a run that either
    # predates fb_dump_base64() or did not use the correct firmware binary.
    # Checking here avoids a confusing assertion error later.
    log_text = log_path.read_text(errors="ignore")
    if "FB=" not in log_text:
        pytest.skip(
            f"Serial log {log_path} contains no 'FB=' lines — "
            "re-run with the current firmware: "
            "'ESP_RGB_VRAM_FILE=/tmp/esp32-rgb-vram.bin bash tools/run-qemu.sh 150 verify'"
        )

    W, H, STRIDE, SY = 240, 135, 800, 200
    raw = vram_path.read_bytes()
    snap = bytearray()
    for row in range(H):
        base = (SY + row) * STRIDE * 2
        snap += raw[base : base + W * 2]

    fb = bytearray()
    for line in log_path.read_text(errors="ignore").splitlines():
        if line.startswith("FB="):
            fb += base64.b64decode(line[3:].strip())

    assert len(snap) == W * H * 2 == len(fb), (len(snap), len(fb))
    assert bytes(fb) == bytes(snap), "UART-decoded framebuffer != VRAM snapshot region"
    assert any(b for b in snap), "snapshot region is all-zero — firmware mirror not running"
