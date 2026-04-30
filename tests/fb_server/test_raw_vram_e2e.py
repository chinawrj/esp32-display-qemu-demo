"""End-to-end test for the ``--source raw-vram`` server mode.

Spawns ``tools.fb_server.server`` against a synthetic headerless RGB565
surface file (mimicking the QEMU ``esp_rgb`` VRAM mmap), connects a
WebSocket client, asserts handshake + that the bytes streamed to the
client match the requested sub-rect, and finally that the server emits
a fresh fb_update only after the surface bytes change.
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


def _solid_surface(surface_w: int, surface_h: int, pixel: int) -> bytes:
    return pixel.to_bytes(2, "little") * (surface_w * surface_h)


@pytest.fixture
def vram_server(tmp_path):
    pytest.importorskip("websockets")
    pytest.importorskip("aiohttp")

    SW, SH = 32, 16  # tiny surface
    W, H = 8, 4      # streamed sub-rect
    X, Y = 4, 2

    vram = tmp_path / "vram.bin"
    vram.write_bytes(_solid_surface(SW, SH, 0xF800))  # all red

    ws_port = _free_port()
    http_port = _free_port()
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "tools.fb_server.server",
            "--source", "raw-vram",
            "--vram-path", str(vram),
            "--vram-x", str(X), "--vram-y", str(Y),
            "--surface-w", str(SW),
            "--width", str(W), "--height", str(H),
            "--ws-port", str(ws_port), "--http-port", str(http_port),
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
        yield {
            "ws_port": ws_port, "http_port": http_port,
            "vram": vram, "SW": SW, "SH": SH, "W": W, "H": H, "X": X, "Y": Y,
        }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_raw_vram_streams_subrect_and_reacts_to_change(vram_server):
    import websockets

    info = vram_server
    W, H = info["W"], info["H"]

    async def go():
        uri = f"ws://127.0.0.1:{info['ws_port']}"
        async with websockets.connect(uri) as ws:
            init = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
            assert init["type"] == "fb_init"
            assert init["width"] == W and init["height"] == H

            hdr = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
            payload = await asyncio.wait_for(ws.recv(), timeout=3)
            assert hdr["type"] == "fb_update"
            assert hdr["w"] == W and hdr["h"] == H
            assert isinstance(payload, (bytes, bytearray))
            assert len(payload) == W * H * 2
            # All red — client must receive exactly that.
            assert bytes(payload) == (0xF800).to_bytes(2, "little") * (W * H)

            # Now mutate the source: rewrite the surface to all blue.
            new_surface = (0x001F).to_bytes(2, "little") * (info["SW"] * info["SH"])
            info["vram"].write_bytes(new_surface)

            # Server should detect the change and push a new update.
            hdr2 = json.loads(await asyncio.wait_for(ws.recv(), timeout=4))
            payload2 = await asyncio.wait_for(ws.recv(), timeout=4)
            assert hdr2["type"] == "fb_update"
            assert bytes(payload2) == (0x001F).to_bytes(2, "little") * (W * H)

    asyncio.run(go())
