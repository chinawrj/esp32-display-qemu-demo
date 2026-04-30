"""CDP test for the ``--source raw-vram`` pipeline.

Boots ``tools.fb_server.server`` against a synthetic 32×16 RGB565 surface
file (mimicking the QEMU ``esp_rgb`` VRAM mmap), opens the framebuffer
viewer in headless Chromium via Playwright, and asserts:

  1. the canvas is painted with the expected solid colour from the surface;
  2. mutating the surface bytes triggers a fresh canvas update inside
     Chrome within a short window (round-trip latency check);
  3. a baseline canvas screenshot is saved to
     ``artifacts/cdp-raw-vram.png`` for visual regression.

This is the AI-friendly visual loop described in the original task book
(Phase 4): the firmware → VRAM mmap → fb_server → Chrome path is now
verified inside a real browser, not just a Python WS client.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"

# Tiny canvas so the test is fast and deterministic.
SURFACE_W, SURFACE_H = 32, 16
REGION_X, REGION_Y, REGION_W, REGION_H = 4, 2, 16, 8

CONNECT_TIMEOUT_MS = 6_000
RENDER_SETTLE_MS = 1_200


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_listening(host: str, port: int, timeout: float = 8.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            s.settimeout(0.2)
            try:
                s.connect((host, port))
                return True
            except OSError:
                time.sleep(0.1)
    return False


def _solid_surface(pixel: int) -> bytes:
    return pixel.to_bytes(2, "little") * (SURFACE_W * SURFACE_H)


def _rgb565_to_rgb888(pixel: int) -> tuple[int, int, int]:
    r5 = (pixel >> 11) & 0x1F
    g6 = (pixel >> 5) & 0x3F
    b5 = pixel & 0x1F
    return ((r5 << 3) | (r5 >> 2), (g6 << 2) | (g6 >> 4), (b5 << 3) | (b5 >> 2))


@pytest.fixture
def raw_vram_server(tmp_path):
    pytest.importorskip("websockets")
    pytest.importorskip("aiohttp")

    vram = tmp_path / "vram.bin"
    vram.write_bytes(_solid_surface(0xF800))  # all red

    ws_port = _free_port()
    http_port = _free_port()
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "tools.fb_server.server",
            "--source", "raw-vram",
            "--vram-path", str(vram),
            "--vram-x", str(REGION_X), "--vram-y", str(REGION_Y),
            "--surface-w", str(SURFACE_W),
            "--width", str(REGION_W), "--height", str(REGION_H),
            "--ws-port", str(ws_port), "--http-port", str(http_port),
            "--fps", "60",
        ],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        if not _wait_listening("127.0.0.1", ws_port) or not _wait_listening("127.0.0.1", http_port):
            stdout, stderr = proc.communicate(timeout=2)
            raise RuntimeError(
                f"fb_server didn't start.\nstdout: {stdout.decode(errors='replace')}\n"
                f"stderr: {stderr.decode(errors='replace')}"
            )
        yield {
            "ws_port": ws_port,
            "http_port": http_port,
            "base_url": f"http://127.0.0.1:{http_port}",
            "vram": vram,
            "width": REGION_W,
            "height": REGION_H,
        }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def _open_and_wait(page, info):
    page.goto(f"{info['base_url']}/index.html?ws={info['ws_port']}")
    page.wait_for_selector("#status.connected", timeout=CONNECT_TIMEOUT_MS)
    page.wait_for_function(
        "() => { const c = document.getElementById('fb'); return c && c.width > 0; }",
        timeout=CONNECT_TIMEOUT_MS,
    )


def _sample_center_pixel(page) -> tuple[int, int, int, int]:
    return tuple(page.evaluate(
        """
        () => {
          const c = document.getElementById('fb');
          const ctx = c.getContext('2d');
          const cx = (c.width / 2) | 0;
          const cy = (c.height / 2) | 0;
          const p = ctx.getImageData(cx, cy, 1, 1).data;
          return [p[0], p[1], p[2], p[3]];
        }
        """
    ))


def test_canvas_renders_red_surface(raw_vram_server, browser_page, artifacts_dir):
    _open_and_wait(browser_page, raw_vram_server)
    browser_page.wait_for_timeout(RENDER_SETTLE_MS)

    dims = browser_page.evaluate(
        "() => { const c = document.getElementById('fb'); return [c.width, c.height]; }"
    )
    assert dims == [REGION_W, REGION_H], dims

    r, g, b, a = _sample_center_pixel(browser_page)
    expected = _rgb565_to_rgb888(0xF800)
    # Allow ±2 codes for any 565→888 channel-replication rounding noise.
    assert all(abs(a_ - e) <= 2 for a_, e in zip((r, g, b), expected)), (
        f"got rgba=({r},{g},{b},{a}), expected ~{expected}"
    )
    assert a == 255

    out = artifacts_dir / "cdp-raw-vram.png"
    browser_page.locator("#fb").screenshot(path=str(out))
    assert out.exists() and out.stat().st_size > 0


def test_canvas_updates_when_surface_mutates(raw_vram_server, browser_page):
    _open_and_wait(browser_page, raw_vram_server)
    browser_page.wait_for_timeout(RENDER_SETTLE_MS)

    r1, g1, b1, _ = _sample_center_pixel(browser_page)
    # Mutate the source: now all blue.
    raw_vram_server["vram"].write_bytes(_solid_surface(0x001F))

    # Poll until the canvas reflects the new colour, with a generous budget.
    deadline = time.time() + 4.0
    expected = _rgb565_to_rgb888(0x001F)
    while time.time() < deadline:
        r2, g2, b2, _ = _sample_center_pixel(browser_page)
        if all(abs(a_ - e) <= 2 for a_, e in zip((r2, g2, b2), expected)):
            break
        browser_page.wait_for_timeout(100)
    else:
        pytest.fail(f"canvas never updated: still ({r2},{g2},{b2}), expected ~{expected}")

    # And, of course, the new pixel must differ from the original.
    assert (r1, g1, b1) != (r2, g2, b2)
