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
