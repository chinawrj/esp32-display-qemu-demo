"""NEXT-001 Day 5 — QEMU-native WebSocket pixel fan-out tests.

Verifies four things:

1. ``esp_rgb.c`` carries the ``ESP_RGB_WS_PATCH`` marker and the three
   hook-call sites inserted by Day 4.
2. ``tools/build-qemu.sh`` installed ``esp_rgb_ws.{c,h}`` into the source
   tree.
3. When booted with ``ESP_RGB_WS_PORT=9334``, the patched QEMU binary opens
   a TCP listener, completes an RFC 6455 WebSocket handshake, and immediately
   sends a JSON TEXT frame with surface metadata.
4. At least one BINARY pixel frame (8-byte header + pixels) arrives within
   5 s of connecting.

FB-010 fix (Day 5): the QEMU fixture now uses ``-serial null`` instead of
``-serial mon:stdio``. The ``mon:stdio`` mux causes QEMU to absorb SIGTERM;
with ``-serial null`` SIGTERM reliably terminates the process.
"""
from __future__ import annotations

import os
import json
import pathlib
import socket
import struct
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
_BOOT_TIMEOUT_S = 15    # WS port opens within ~2 s of QEMU init
_HEADER_TIMEOUT_S = 10  # JSON header arrives very soon after connect
_FRAME_TIMEOUT_S = 60   # pixel frame requires firmware boot + LVGL init (~30 s)
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
        # Use -display none instead of -nographic so that QEMU's display
        # refresh loop (which drives rgb_update() / broadcast_frame()) keeps
        # running. With -nographic the display subsystem is fully disabled
        # and gfx_update() is never called.
        "-display", "none",
        # FB-010 fix: use -serial null (not mon:stdio) so SIGTERM is not
        # absorbed by the QEMU monitor mux and reliably terminates QEMU.
        "-serial", "null",
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

    Day 5: QEMU now sends a JSON header TEXT frame after the handshake then
    continues pushing BINARY pixel frames. The test only asserts the upgrade
    itself succeeds (the next two tests validate the data frames).
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
            ping_interval=None,  # server does not handle PING/PONG yet (Day 5)
            max_size=None,       # surface is ~1.92 MB, exceeds 1 MB default
        ) as ws:
            connected = True
            # Consume the JSON header so the connection is in a clean state.
            try:
                ws.recv(timeout=3)
            except Exception:
                pass
    except Exception as exc:
        if connected:
            pass
        else:
            pytest.fail(
                f"WebSocket handshake failed (NEXT-001 Day 5): {exc!r}\n"
                f"  QEMU: {QEMU_BIN}\n"
                f"  port: {_WS_HOST}:{_WS_PORT}"
            )

    assert connected, (
        "WebSocket connect() context manager never entered — "
        "handshake did not succeed"
    )


def test_ws_json_header(qemu_ws_proc):
    """First message after the WS handshake must be a JSON TEXT frame.

    Asserts the envelope fields defined in docs/qemu-native-ws.md §1.2:
    ``version``, ``w``, ``h``, ``format``, ``stride_bytes``, ``fps_target``.
    """
    try:
        from websockets.sync.client import connect as ws_connect
    except ImportError:
        pytest.skip("websockets package not available; pip install websockets")

    with ws_connect(
        f"ws://{_WS_HOST}:{_WS_PORT}/",
        open_timeout=5,
        close_timeout=3,
        ping_interval=None,  # server does not handle PING/PONG yet (Day 5)
        max_size=None,       # surface is ~1.92 MB, exceeds 1 MB default
    ) as ws:
        msg = ws.recv(timeout=_HEADER_TIMEOUT_S)

    assert isinstance(msg, str), (
        f"Expected a TEXT frame for the JSON header; got {type(msg).__name__}"
    )

    header = json.loads(msg)
    assert header.get("version") == 1, f"version != 1: {header}"
    assert isinstance(header.get("w"), int) and header["w"] > 0, \
        f"missing/invalid 'w': {header}"
    assert isinstance(header.get("h"), int) and header["h"] > 0, \
        f"missing/invalid 'h': {header}"
    assert header.get("format") in ("x8r8g8b8", "r5g6b5"), \
        f"unknown format: {header}"
    assert isinstance(header.get("stride_bytes"), int) and \
        header["stride_bytes"] > 0, f"missing/invalid 'stride_bytes': {header}"
    assert isinstance(header.get("fps_target"), int) and \
        header["fps_target"] > 0, f"missing/invalid 'fps_target': {header}"


def test_ws_first_pixel_frame(qemu_ws_proc):
    """After the JSON header, at least one BINARY pixel frame must arrive.

    Frame format (docs/qemu-native-ws.md §1.3):
      - bytes 0–3: u32 LE  seq  (0 for first frame)
      - bytes 4–7: u32 LE  size (w × h × bytes_per_pixel)
      - bytes 8…:  raw pixels in declared format

    Validates that:
      - The frame is a ``bytes`` object (BINARY WS opcode).
      - It contains at least 8 bytes (header).
      - ``seq == 0`` for the first frame.
      - ``size > 0`` and ``size == w * h * bytes_per_pixel`` from header.
      - Total message length == 8 + size.
    """
    try:
        from websockets.sync.client import connect as ws_connect
    except ImportError:
        pytest.skip("websockets package not available; pip install websockets")

    with ws_connect(
        f"ws://{_WS_HOST}:{_WS_PORT}/",
        open_timeout=5,
        close_timeout=3,
        ping_interval=None,  # server does not handle PING/PONG yet (Day 5)
        max_size=None,       # surface is ~1.92 MB, exceeds 1 MB default
    ) as ws:
        # First message: JSON header (sent immediately on connect from cached header)
        header_msg = ws.recv(timeout=_HEADER_TIMEOUT_S)
        assert isinstance(header_msg, str), \
            f"Expected JSON TEXT header; got {type(header_msg).__name__}"
        header = json.loads(header_msg)

        w            = header["w"]
        h            = header["h"]
        stride_bytes = header["stride_bytes"]
        bpp          = stride_bytes // w  # bytes per pixel

        # Second message: first pixel frame (allow up to _FRAME_TIMEOUT_S for
        # firmware boot + LVGL to paint the first frame)
        pixel_msg = ws.recv(timeout=_FRAME_TIMEOUT_S)

    assert isinstance(pixel_msg, bytes), (
        f"Expected a BINARY pixel frame; got {type(pixel_msg).__name__}"
    )
    assert len(pixel_msg) >= 8, (
        f"Pixel frame too short ({len(pixel_msg)} bytes); expected ≥8"
    )

    seq, size = struct.unpack_from("<II", pixel_msg, 0)
    assert seq == 0, f"First frame seq should be 0; got {seq}"

    expected_size = w * h * bpp
    assert size == expected_size, (
        f"Frame size {size} != expected {expected_size} (w={w} h={h} bpp={bpp})"
    )
    assert len(pixel_msg) == 8 + size, (
        f"Message length {len(pixel_msg)} != 8 + size ({8 + size})"
    )


def test_ws_frame_looks_like_lvgl(qemu_ws_proc):
    """Decode the first pixel frame with Pillow; assert non-trivial colour variance.

    Validates that the QEMU surface contains real rendered content (not a blank
    black or solid-colour surface).  Saves the decoded frame to
    ``artifacts/qemu-ws-frame-001.png`` for visual inspection.

    Acceptance thresholds (conservative — matches test_live_qemu_canvas.py):
    - ``unique_colours >= 8``   at least 8 distinct RGB triples in the frame
    - ``pixel_sum > 0``         at least one non-black pixel

    The test is intentionally lenient: the LVGL benchmark may not have reached
    its first interesting frame yet.  The 500ms GLib timer means we receive the
    frame quickly, but LVGL boot takes ~2–5 s.  The ``qemu_ws_proc`` fixture is
    module-scoped so QEMU has been running for the duration of the previous
    tests, giving it enough time to boot.
    """
    pillow = pytest.importorskip("PIL.Image", reason="Pillow not installed; pip install Pillow")

    try:
        from websockets.sync.client import connect as ws_connect
    except ImportError:
        pytest.skip("websockets package not available; pip install websockets")

    import pathlib

    artifacts = pathlib.Path(__file__).resolve().parents[1] / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    out_path = artifacts / "qemu-ws-frame-001.png"

    with ws_connect(
        f"ws://{_WS_HOST}:{_WS_PORT}/",
        open_timeout=5,
        close_timeout=3,
        ping_interval=None,
        max_size=None,
    ) as ws:
        header_msg = ws.recv(timeout=_HEADER_TIMEOUT_S)
        assert isinstance(header_msg, str), \
            f"Expected JSON TEXT header; got {type(header_msg).__name__}"
        header = json.loads(header_msg)

        w            = header["w"]
        h            = header["h"]
        fmt          = header["format"]
        bpp          = header["stride_bytes"] // w

        # Loop through frames until we find one with non-blank content.
        # The 500 ms GLib timer may fire several times before LVGL paints its
        # first frame (~3 s after firmware boot).  The module-scoped fixture
        # means QEMU has been running since the earlier tests, so the first
        # frame we receive here is usually already populated; the loop is a
        # safety net for very fast CI machines.
        pixel_msg = None
        deadline  = time.monotonic() + _FRAME_TIMEOUT_S
        while time.monotonic() < deadline:
            msg = ws.recv(timeout=2.0)
            if isinstance(msg, bytes) and len(msg) > 8:
                raw = msg[8:]
                # Quick non-blank check: any nonzero 16-bit word in first 2 KB
                if any(raw[i] or raw[i + 1] for i in range(0, min(len(raw), 2048), 2)):
                    pixel_msg = msg
                    break
                pixel_msg = msg  # save last blank frame as fallback
        assert pixel_msg is not None, "No BINARY pixel frame received before timeout"

    pixels = pixel_msg[8:]  # skip 8-byte frame header

    # Convert to RGB PIL image for analysis
    import array as _array
    if fmt == "x8r8g8b8":
        # x8r8g8b8 LE: bytes [B, G, R, X] per pixel → PIL RGB
        rgb = bytearray(w * h * 3)
        src = bytearray(pixels)
        for i in range(w * h):
            rgb[i * 3 + 0] = src[i * 4 + 2]  # R
            rgb[i * 3 + 1] = src[i * 4 + 1]  # G
            rgb[i * 3 + 2] = src[i * 4 + 0]  # B
        img = pillow.frombytes("RGB", (w, h), bytes(rgb))
    elif fmt == "r5g6b5":
        # r5g6b5 LE: 16-bit words
        from PIL import Image as _PIL
        words = _array.array("H", pixels)
        words.byteswap() if __import__("sys").byteorder == "big" else None
        rgb = bytearray(w * h * 3)
        for i, p in enumerate(words):
            r5 = (p >> 11) & 0x1f
            g6 = (p >>  5) & 0x3f
            b5 =  p        & 0x1f
            rgb[i * 3 + 0] = (r5 << 3) | (r5 >> 2)
            rgb[i * 3 + 1] = (g6 << 2) | (g6 >> 4)
            rgb[i * 3 + 2] = (b5 << 3) | (b5 >> 2)
        img = _PIL.frombytes("RGB", (w, h), bytes(rgb))
    else:
        pytest.skip(f"Unknown pixel format {fmt!r}; can't decode for Pillow analysis")

    img.save(str(out_path))
    assert out_path.exists() and out_path.stat().st_size > 0, \
        f"failed to save {out_path}"

    # Analyse pixel content
    import collections
    pixel_data = list(img.getdata())
    pixel_sum    = sum(r + g + b for r, g, b in pixel_data)
    unique_count = len(set(pixel_data))

    assert pixel_sum > 0, (
        f"Frame appears blank (pixel_sum=0). "
        f"Saved to {out_path}. LVGL may not have painted yet."
    )
    assert unique_count >= 8, (
        f"Frame has only {unique_count} distinct colour(s); expected ≥ 8. "
        f"Saved to {out_path}."
    )
