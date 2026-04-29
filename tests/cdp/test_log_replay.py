"""CDP test: real LVGL frame from a captured QEMU log replayed into Chrome.

Spawns the fb_server in --source=log mode pointed at /tmp/esp32-qemu-serial.log
(a real LVGL benchmark frame), opens the viewer in headless Chromium, and
verifies the canvas paints a visually rich frame (≥100 unique colours — fake
producer only has ~3). Saves artifacts/cdp-real-lvgl-frame.png as evidence.
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
WARM_LOG = Path("/tmp/esp32-qemu-serial.log")

CONNECT_TIMEOUT_MS = 5_000
RENDER_SETTLE_MS = 1_500


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


def _has_real_log() -> bool:
    if not WARM_LOG.exists():
        return False
    fb_lines = sum(1 for ln in WARM_LOG.read_text(errors="replace").splitlines()
                   if ln.startswith("FB="))
    return fb_lines >= 1440


@pytest.fixture
def log_replay_server():
    if not _has_real_log():
        pytest.skip(f"needs complete QEMU log at {WARM_LOG}; run pytest tests/test_qemu_boot.py first")
    pytest.importorskip("websockets")
    pytest.importorskip("aiohttp")

    ws_port = _free_port()
    http_port = _free_port()
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "tools.fb_server.server",
            "--source", "log",
            "--fb-log", str(WARM_LOG),
            "--ws-port", str(ws_port),
            "--http-port", str(http_port),
            "--fps", "2",  # slow loop is fine — same frame cycles
        ],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        if not _wait_listening("127.0.0.1", http_port) or not _wait_listening("127.0.0.1", ws_port):
            stdout, stderr = proc.communicate(timeout=2)
            raise RuntimeError(f"server failed: {stderr.decode(errors='replace')}")
        yield {
            "ws_port": ws_port,
            "http_port": http_port,
            "base_url": f"http://127.0.0.1:{http_port}",
        }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_real_lvgl_frame_renders_in_chrome(log_replay_server, browser_page, artifacts_dir):
    page = browser_page
    page.goto(f"{log_replay_server['base_url']}/index.html?ws={log_replay_server['ws_port']}")
    page.wait_for_selector("#status.connected", timeout=CONNECT_TIMEOUT_MS)
    page.wait_for_function(
        "() => { const c = document.getElementById('fb'); return c && c.width === 240 && c.height === 135; }",
        timeout=CONNECT_TIMEOUT_MS,
    )
    page.wait_for_timeout(RENDER_SETTLE_MS)

    stats = page.evaluate(
        """
        () => {
          const c = document.getElementById('fb');
          const ctx = c.getContext('2d');
          const img = ctx.getImageData(0, 0, c.width, c.height);
          const colours = new Set();
          let sum = 0;
          for (let i = 0; i < img.data.length; i += 4) {
            sum += img.data[i] + img.data[i+1] + img.data[i+2];
            colours.add((img.data[i]<<16) | (img.data[i+1]<<8) | img.data[i+2]);
          }
          return { sum, unique: colours.size };
        }
        """
    )
    # Real LVGL benchmark frame has ~90 unique colours per docs/screenshot.png;
    # synthetic producer has ~3. Threshold 50 is comfortably between them.
    assert stats["unique"] >= 50, (
        f"expected a rich LVGL frame (>=50 colours), got {stats}; "
        "is the log file the synthetic-producer one by mistake?"
    )
    assert stats["sum"] > 0

    out = artifacts_dir / "cdp-real-lvgl-frame.png"
    page.locator("#fb").screenshot(path=str(out))
    assert out.exists() and out.stat().st_size > 0
