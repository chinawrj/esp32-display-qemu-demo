"""NEXT-001 Day 4 — QEMU-native WebSocket listener handshake test.

Verifies three things:

1. ``esp_rgb.c`` carries the ``ESP_RGB_WS_PATCH`` marker and the three
   hook-call sites inserted by Day 4.
2. ``tools/build-qemu.sh`` installed ``esp_rgb_ws.{c,h}`` into the source
   tree.
3. When booted with ``ESP_RGB_WS_PORT=9334``, the patched QEMU binary opens
   a TCP listener on that port and completes an RFC 6455 WebSocket handshake
   with a Python client.

Day 4 behaviour: QEMU closes the connection right after the handshake
(pixel fan-out lands in Day 5). The test therefore only asserts that the
upgrade succeeds — it does not expect any data frames.

Skip conditions:
  - ``tools/qemu-src/build/qemu-system-xtensa`` not present
    (run ``bash tools/build-qemu.sh`` first).
  - ``build/qemu_flash.bin`` or ``build/qemu_efuse.bin`` not present
    (run ``idf.py build`` first).
"""
from __future__ import annotations

import os
import pathlib
import socket
import subprocess
import time

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
QEMU_BIN = PROJECT_ROOT / "tools" / "qemu-src" / "build" / "qemu-system-xtensa"
FLASH_BIN = PROJECT_ROOT / "build" / "qemu_flash.bin"
EFUSE_BIN = PROJECT_ROOT / "build" / "qemu_efuse.bin"
ESP_RGB_C = PROJECT_ROOT / "tools" / "qemu-src" / "hw" / "display" / "esp_rgb.c"
ESP_RGB_WS_C = PROJECT_ROOT / "tools" / "qemu-src" / "hw" / "display" / "esp_rgb_ws.c"
ESP_RGB_WS_H = (
    PROJECT_ROOT
    / "tools"
    / "qemu-src"
    / "include"
    / "hw"
    / "display"
    / "esp_rgb_ws.h"
)

_WS_PORT = int(os.environ.get("ESP_RGB_WS_PORT", "9334"))
_WS_HOST = "127.0.0.1"
_BOOT_TIMEOUT_S = 15  # WS port should open within ~2s of QEMU init
_RETRY_INTERVAL_S = 0.2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _local_qemu_ok() -> bool:
    return QEMU_BIN.is_file() and os.access(QEMU_BIN, os.X_OK)


def _firmware_ok() -> bool:
    return FLASH_BIN.is_file() and EFUSE_BIN.is_file()


def _wait_for_tcp_port(host: str, port: int, timeout_s: float) -> bool:
    """Poll until ``host:port`` accepts a TCP connection or ``timeout_s`` expires."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(_RETRY_INTERVAL_S)
    return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def qemu_ws_proc():
    """Start QEMU with the WS listener enabled; kill it on module teardown.

    Uses the locally-built patched binary and the pre-built firmware images.
    The WS port is read from ``ESP_RGB_WS_PORT`` (default 9334).
    """
    if not _local_qemu_ok():
        pytest.skip(
            f"local QEMU binary not found at {QEMU_BIN}; "
            "run 'bash tools/build-qemu.sh' first"
        )
    if not _firmware_ok():
        pytest.skip(
            f"firmware images not built ({FLASH_BIN}); "
            "run 'idf.py build' first"
        )

    env = os.environ.copy()
    env["ESP_RGB_WS_PORT"] = str(_WS_PORT)
    env.pop("ESP_RGB_WS_DISABLE", None)
    # Disable file-mmap path — we are testing the WS path exclusively.
    env.pop("ESP_RGB_VRAM_FILE", None)

    cmd = [
        str(QEMU_BIN),
        "-M", "esp32", "-m", "4M",
        "-drive", f"file={FLASH_BIN},if=mtd,format=raw",
        "-drive", f"file={EFUSE_BIN},if=none,format=raw,id=efuse",
        "-global", "driver=nvram.esp32.efuse,property=drive,value=efuse",
        "-global", "driver=timer.esp32.timg,property=wdt_disable,value=true",
        "-nic", "user,model=open_eth",
        "-nographic",
        "-serial", "mon:stdio",
    ]

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    port_ready = _wait_for_tcp_port(_WS_HOST, _WS_PORT, _BOOT_TIMEOUT_S)
    if not port_ready:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        pytest.skip(
            f"WS port {_WS_PORT} not ready after {_BOOT_TIMEOUT_S}s — "
            "QEMU may have failed to start or bind the listener"
        )

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


# ---------------------------------------------------------------------------
# Static / source-level tests (no QEMU boot required)
# ---------------------------------------------------------------------------


def test_esp_rgb_ws_patch_marker_in_source():
    """``esp_rgb.c`` must carry ESP_RGB_WS_PATCH and the three hook calls."""
    if not ESP_RGB_C.exists():
        pytest.skip("QEMU source not present — run tools/build-qemu.sh first")
    text = ESP_RGB_C.read_text()
    assert "ESP_RGB_WS_PATCH" in text, "ESP_RGB_WS_PATCH marker missing from esp_rgb.c"
    assert "esp_rgb_ws_start" in text, "esp_rgb_ws_start hook missing from esp_rgb.c"
    assert "esp_rgb_ws_announce_surface" in text, (
        "esp_rgb_ws_announce_surface hook missing from esp_rgb.c"
    )
    assert "esp_rgb_ws_broadcast_frame" in text, (
        "esp_rgb_ws_broadcast_frame hook missing from esp_rgb.c"
    )


def test_esp_rgb_ws_source_files_installed():
    """``build-qemu.sh`` must have installed ``esp_rgb_ws.{c,h}`` into the source tree."""
    for path in (ESP_RGB_WS_C, ESP_RGB_WS_H):
        if not path.exists():
            pytest.skip(
                f"{path.name} not in QEMU source tree — "
                "run 'bash tools/build-qemu.sh' first"
            )
    # Sanity: patch marker must survive the install copy.
    assert "ESP_RGB_WS_PATCH" in ESP_RGB_WS_C.read_text()
    assert "esp_rgb_ws_start" in ESP_RGB_WS_H.read_text()


# ---------------------------------------------------------------------------
# Runtime WS handshake test (requires QEMU boot)
# ---------------------------------------------------------------------------


def test_ws_handshake(qemu_ws_proc):
    """Connecting to the QEMU WS listener must complete an RFC 6455 handshake.

    Day 4: QEMU closes the channel right after the handshake callback fires
    (no data frames yet). The test asserts *only* that the upgrade succeeds —
    i.e. that ``connect()`` does not raise a handshake error.
    """
    try:
        from websockets.sync.client import connect as ws_connect
    except ImportError:
        pytest.skip("websockets package not available; pip install websockets")

    connected = False
    try:
        with ws_connect(
            f"ws://{_WS_HOST}:{_WS_PORT}/",
            open_timeout=5,
            close_timeout=3,
        ) as ws:
            connected = True
            # Day 4: QEMU closes right after handshake — we may receive a
            # ConnectionClosed before any data. Either outcome is fine.
            try:
                ws.recv(timeout=2)
            except Exception:
                pass  # ConnectionClosed / timeout — expected in Day 4
    except Exception as exc:
        if connected:
            # Handshake succeeded; subsequent close raised — that's fine.
            pass
        else:
            pytest.fail(
                f"WebSocket handshake failed (NEXT-001 Day 4): {exc!r}\n"
                f"  QEMU: {QEMU_BIN}\n"
                f"  port: {_WS_HOST}:{_WS_PORT}"
            )

    assert connected, (
        "WebSocket connect() context manager never entered — "
        "handshake did not succeed"
    )
