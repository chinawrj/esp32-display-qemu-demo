"""End-to-end test: spawn the WebSocket server and verify the client handshake.

Boots tools.fb_server.server in a subprocess, connects with `websockets`
client, validates fb_init message + first few fb_update header/payload pairs.
"""
from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
def fb_server_proc(tmp_path):
    websockets = pytest.importorskip("websockets")
    pytest.importorskip("aiohttp")

    ws_port = _free_port()
    http_port = _free_port()
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "tools.fb_server.server",
            "--ws-port", str(ws_port),
            "--http-port", str(http_port),
            "--width", "32", "--height", "16",  # tiny, so payloads stay small
            "--fps", "60",
        ],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        if not _wait_listening("127.0.0.1", ws_port):
            stdout, stderr = proc.communicate(timeout=2)
            raise RuntimeError(
                f"fb_server didn't start.\nstdout: {stdout.decode(errors='replace')}\n"
                f"stderr: {stderr.decode(errors='replace')}"
            )
        yield ws_port, http_port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_handshake_and_first_frames(fb_server_proc):
    import websockets

    ws_port, _ = fb_server_proc
    width, height = 32, 16

    async def go():
        uri = f"ws://127.0.0.1:{ws_port}"
        async with websockets.connect(uri) as ws:
            # 1. fb_init (text)
            init_raw = await asyncio.wait_for(ws.recv(), timeout=2)
            assert isinstance(init_raw, str)
            init = json.loads(init_raw)
            assert init == {
                "type": "fb_init", "width": width, "height": height,
                "format": "RGB565", "rotation": 0,
            }

            # 2. initial clear: header (text) + payload (binary)
            header_raw = await asyncio.wait_for(ws.recv(), timeout=2)
            payload = await asyncio.wait_for(ws.recv(), timeout=2)
            assert isinstance(header_raw, str)
            assert isinstance(payload, (bytes, bytearray))
            header = json.loads(header_raw)
            assert header["type"] == "fb_update"
            assert header["x"] == 0 and header["y"] == 0
            assert header["w"] == width and header["h"] == height
            assert header["format"] == "RGB565"
            assert header["encoding"] == "raw"
            assert len(payload) == width * height * 2

            # 3. several update frames from the moving rect producer
            for _ in range(4):
                h_raw = await asyncio.wait_for(ws.recv(), timeout=2)
                p = await asyncio.wait_for(ws.recv(), timeout=2)
                hdr = json.loads(h_raw)
                assert hdr["type"] == "fb_update"
                assert len(p) == hdr["h"] * hdr["stride"]

    asyncio.run(go())


def test_http_serves_index(fb_server_proc):
    import urllib.request
    _, http_port = fb_server_proc
    with urllib.request.urlopen(f"http://127.0.0.1:{http_port}/index.html", timeout=3) as r:
        body = r.read().decode()
    assert "<canvas" in body and "main.js" in body
