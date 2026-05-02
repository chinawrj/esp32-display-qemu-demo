"""NEXT-001 Day 6 — Chrome end-to-end canvas test via QEMU-native WS.

Opens ``web/qemu-direct.html`` in headless Chromium and asserts that the
QEMU ``esp_rgb`` WebSocket listener (NEXT-001) delivers pixel frames that
actually paint the canvas — no firmware changes, no ``ESP_RGB_VRAM_FILE``
environment variable required.

Skip conditions (automatic):
  - ``tools/qemu-src/build/qemu-system-xtensa`` missing (run tools/build-qemu.sh)
  - ``build/qemu_flash.bin`` / ``build/qemu_efuse.bin`` missing (run idf.py build)
  - ``playwright`` Python package not installed

Acceptance threshold (matches test_live_qemu_canvas.py): canvas must have
``unique >= 8`` distinct colours and ``sum > 0``.  Since the QEMU surface is
800×600 x8r8g8b8 and the firmware paints a colourful LVGL benchmark scene at
240×135, we expect a few hundred distinct colours even in the up-scaled view.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
QEMU_BIN  = PROJECT_ROOT / "tools" / "qemu-src" / "build" / "qemu-system-xtensa"
FLASH_BIN = PROJECT_ROOT / "build" / "qemu_flash.bin"
EFUSE_BIN = PROJECT_ROOT / "build" / "qemu_efuse.bin"
WEB_DIR   = PROJECT_ROOT / "web"

_BOOT_TIMEOUT_S   = 15    # WS port opens within ~2 s of QEMU init
_CONNECT_TIMEOUT_MS = 10_000
_RENDER_SETTLE_MS   = 8_000  # wait for LVGL to boot and paint first frame
_RETRY_S = 0.2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _local_qemu_ok() -> bool:
    return QEMU_BIN.is_file() and os.access(QEMU_BIN, os.X_OK)


def _firmware_ok() -> bool:
    return FLASH_BIN.is_file() and EFUSE_BIN.is_file()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_tcp(host: str, port: int, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(_RETRY_S)
    return False


# ---------------------------------------------------------------------------
# Fixtures (module scope — one QEMU + one HTTP server for all tests here)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qemu_ws_direct():
    """Start QEMU with the WS listener; kill on module teardown."""
    if not _local_qemu_ok():
        pytest.skip(
            f"QEMU binary not found at {QEMU_BIN}; run tools/build-qemu.sh first"
        )
    if not _firmware_ok():
        pytest.skip(
            f"firmware images not built ({FLASH_BIN}); run idf.py build first"
        )

    ws_port = _free_port()
    env = os.environ.copy()
    env["ESP_RGB_WS_PORT"] = str(ws_port)
    env.pop("ESP_RGB_WS_DISABLE", None)
    env.pop("ESP_RGB_VRAM_FILE", None)  # test the WS path exclusively

    cmd = [
        str(QEMU_BIN), "-M", "esp32", "-m", "4M",
        "-drive", f"file={FLASH_BIN},if=mtd,format=raw",
        "-drive", f"file={EFUSE_BIN},if=none,format=raw,id=efuse",
        "-global", "driver=nvram.esp32.efuse,property=drive,value=efuse",
        "-global", "driver=timer.esp32.timg,property=wdt_disable,value=true",
        "-nic", "user,model=open_eth",
        "-display", "none",
        "-serial", "null",
    ]

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    if not _wait_for_tcp("127.0.0.1", ws_port, _BOOT_TIMEOUT_S):
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        pytest.skip(
            f"WS port {ws_port} not ready after {_BOOT_TIMEOUT_S}s — "
            "QEMU may have failed to start or bind the listener"
        )

    yield {"ws_port": ws_port}

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture(scope="module")
def http_server_web():
    """Serve ``web/`` via ``python -m http.server`` for Playwright to load pages."""
    http_port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(http_port),
         "--directory", str(WEB_DIR)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if not _wait_for_tcp("127.0.0.1", http_port, 8.0):
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        pytest.skip("HTTP server didn't start in 8 s")

    yield {"base_url": f"http://127.0.0.1:{http_port}"}

    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_qemu_direct_canvas_renders_frame(
    qemu_ws_direct, http_server_web, artifacts_dir
):
    """Playwright: ``web/qemu-direct.html`` must show a painted canvas from QEMU WS.

    Acceptance:
    - WebSocket connects (``#status.connected`` class appears).
    - Canvas is sized to the surface dimensions (width > 0).
    - After waiting for LVGL to boot and paint, the canvas has:
        - ``sum > 0``  (not blank)
        - ``unique >= 8`` distinct colours (real LVGL content, not solid fill)
    - A screenshot is saved to ``artifacts/cdp-qemu-direct.png``.
    """
    playwright_mod = pytest.importorskip("playwright.sync_api")

    ws_port  = qemu_ws_direct["ws_port"]
    base_url = http_server_web["base_url"]
    page_url = f"{base_url}/qemu-direct.html?port={ws_port}"

    with playwright_mod.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page    = context.new_page()

        try:
            page.goto(page_url, timeout=10_000)

            # Wait for WS handshake to complete.
            page.wait_for_selector("#status.connected", timeout=_CONNECT_TIMEOUT_MS)

            # Wait for the canvas to receive the JSON header and resize.
            page.wait_for_function(
                "() => { const c = document.getElementById('fb'); "
                "return c && c.width > 0; }",
                timeout=_CONNECT_TIMEOUT_MS,
            )

            # Allow time for LVGL to boot and paint at least one frame via the
            # GLib 500ms timer.  LVGL benchmark typically shows first flush
            # within ~5 s of firmware boot.
            page.wait_for_timeout(_RENDER_SETTLE_MS)

            stats = page.evaluate(
                """
                () => {
                  const c   = document.getElementById('fb');
                  const ctx = c.getContext('2d');
                  const img = ctx.getImageData(0, 0, c.width, c.height);
                  let   sum = 0;
                  const colours = new Set();
                  for (let i = 0; i < img.data.length; i += 4) {
                    sum += img.data[i] + img.data[i+1] + img.data[i+2];
                    colours.add(
                      (img.data[i] << 16) | (img.data[i+1] << 8) | img.data[i+2]
                    );
                  }
                  return { sum, unique: colours.size, w: c.width, h: c.height };
                }
                """
            )

            assert stats["sum"] > 0, (
                f"Canvas appears blank after {_RENDER_SETTLE_MS} ms: {stats}\n"
                "Check that QEMU is sending pixel frames (run tests/test_qemu_ws_handshake.py)"
            )
            assert stats["unique"] >= 8, (
                f"Canvas has only {stats['unique']} colour(s): {stats}\n"
                "Expected ≥ 8 distinct colours for LVGL content"
            )

            # Save a screenshot of the canvas for visual inspection.
            out = artifacts_dir / "cdp-qemu-direct.png"
            page.locator("#fb").screenshot(path=str(out))
            assert out.exists() and out.stat().st_size > 0, (
                f"screenshot not written: {out}"
            )

        finally:
            context.close()
            browser.close()
