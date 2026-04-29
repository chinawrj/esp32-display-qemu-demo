"""End-to-end test for tools/decode-fb.py.

Decodes the captured serial log into a PNG and validates the result is a real
240x135 image with non-trivial content (not a single colour, splash-screen
guard).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DECODER = PROJECT_ROOT / "tools" / "decode-fb.py"


def test_decoder_produces_valid_png(qemu_log: Path, tmp_path: Path) -> None:
    pytest.importorskip("PIL", reason="Pillow required (pip install -r requirements.txt)")
    from PIL import Image

    out = tmp_path / "shot.png"
    result = subprocess.run(
        [sys.executable, str(DECODER), str(qemu_log), str(out)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"decode-fb.py exited {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert out.is_file() and out.stat().st_size > 0

    with Image.open(out) as im:
        assert im.size == (240, 135), f"Unexpected size: {im.size}"
        assert im.mode in ("RGB", "RGBA"), f"Unexpected mode: {im.mode}"
        unique = len({tuple(p) if isinstance(p, tuple) else p for p in im.getdata()})
        # Splash screen / single-colour frame -> reject. Real benchmark frame
        # historically has ~90 unique colours; require >= 16 to be safe.
        assert unique >= 16, (
            f"Decoded image has only {unique} unique colours — "
            "likely captured during splash, not benchmark."
        )


def test_decoder_scale_argument(qemu_log: Path, tmp_path: Path) -> None:
    pytest.importorskip("PIL")
    from PIL import Image

    out = tmp_path / "shot4x.png"
    result = subprocess.run(
        [sys.executable, str(DECODER), str(qemu_log), str(out), "--scale", "4"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    with Image.open(out) as im:
        assert im.size == (240 * 4, 135 * 4)
