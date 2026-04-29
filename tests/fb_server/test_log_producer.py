"""Tests for the log-replay framebuffer producer.

Verifies:
1. parse_log() extracts FB blocks from a representative serial-log snippet
2. Replaying a frame produces correctly-sized FBUpdate messages
3. End-to-end: server in log mode delivers fb_init + a real LVGL frame
"""
from __future__ import annotations

import asyncio
import base64
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WARM_LOG = Path("/tmp/esp32-qemu-serial.log")


# ---------------------------------------------------------------------------
# Unit tests for parse_log
# ---------------------------------------------------------------------------

def _make_synthetic_log(w: int, h: int, fmt: str = "RGB565") -> tuple[str, bytes]:
    """Build an FB_BEGIN/FB=/FB_END block carrying w*h*2 known bytes."""
    payload = bytes((i & 0xff for i in range(w * h * 2)))
    b64 = base64.b64encode(payload).decode()
    # split into 60-char lines like firmware does
    lines = [b64[i:i + 60] for i in range(0, len(b64), 60)]
    body = "\n".join(f"FB={ln}" for ln in lines)
    log = (
        f"<<<FB_BEGIN size={w*h*2} w={w} h={h} fmt={fmt}>>>\n"
        f"{body}\n<<<FB_END>>>\n"
    )
    return log, payload


def test_parse_log_extracts_block():
    from tools.fb_server.log_producer import parse_log
    text, payload = _make_synthetic_log(8, 4)
    frames = parse_log(text)
    assert len(frames) == 1
    f = frames[0]
    assert (f.width, f.height, f.fmt) == (8, 4, "RGB565")
    assert f.payload == payload


def test_parse_log_skips_garbled_block():
    from tools.fb_server.log_producer import parse_log
    text, _ = _make_synthetic_log(8, 4)
    # corrupt one base64 char with `!` and ensure parse_log skips it cleanly
    bad = text.replace("FB=A", "FB=!", 1)
    # The corrupted block should be skipped (no exception, empty list)
    assert parse_log(bad) == []


def test_parse_log_finds_multiple_blocks():
    from tools.fb_server.log_producer import parse_log
    a, _ = _make_synthetic_log(8, 4)
    b, _ = _make_synthetic_log(16, 8)
    text = a + "some unrelated log\n" + b
    frames = parse_log(text)
    assert [(f.width, f.height) for f in frames] == [(8, 4), (16, 8)]


# ---------------------------------------------------------------------------
# End-to-end: server in --source=log mode against a real captured log
# ---------------------------------------------------------------------------

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


@pytest.fixture
def synthetic_log_path(tmp_path):
    text, _ = _make_synthetic_log(32, 16)
    p = tmp_path / "fb-synthetic.log"
    p.write_text(text)
    return p


def test_log_mode_serves_frame(synthetic_log_path):
    """Spawn server with --source=log against a synthetic log; assert client sees it."""
    pytest.importorskip("websockets")

    ws_port = _free_port()
    http_port = _free_port()
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "tools.fb_server.server",
            "--source", "log",
            "--fb-log", str(synthetic_log_path),
            "--ws-port", str(ws_port),
            "--http-port", str(http_port),
            "--fps", "30",
        ],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        if not _wait_listening("127.0.0.1", ws_port):
            stdout, stderr = proc.communicate(timeout=2)
            raise RuntimeError(f"server failed: {stderr.decode(errors='replace')}")

        import websockets

        async def go():
            async with websockets.connect(f"ws://127.0.0.1:{ws_port}") as ws:
                init = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
                assert init == {"type": "fb_init", "width": 32, "height": 16,
                                "format": "RGB565", "rotation": 0}
                hdr = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
                payload = await asyncio.wait_for(ws.recv(), timeout=3)
                assert hdr["type"] == "fb_update"
                assert (hdr["w"], hdr["h"]) == (32, 16)
                assert len(payload) == 32 * 16 * 2

        asyncio.run(go())
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.mark.skipif(
    not WARM_LOG.exists() or sum(1 for ln in WARM_LOG.read_text(errors="replace").splitlines()
                                  if ln.startswith("FB=")) < 1440,
    reason="needs a complete /tmp/esp32-qemu-serial.log (1440 FB= lines); run pytest tests/test_qemu_boot.py first",
)
def test_log_mode_with_real_qemu_log(tmp_path):
    """Smoke-test against the real warm QEMU log if available."""
    from tools.fb_server.log_producer import parse_log_file
    frames = parse_log_file(WARM_LOG)
    assert len(frames) == 1
    f = frames[0]
    assert (f.width, f.height, f.fmt) == (240, 135, "RGB565")
    assert len(f.payload) == 240 * 135 * 2
