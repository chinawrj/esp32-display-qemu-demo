"""Tests for the shmem framebuffer producer.

Exercises pack/parse round-trip and the ``stream_frames`` polling loop with
a synthetic writer (no QEMU required).
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from tools.fb_server.shmem_producer import (
    HEADER_SIZE,
    pack_frame,
    parse_frame,
    read_latest,
    stream_frames,
)


def _solid_rgb565(value: int, w: int, h: int) -> bytes:
    return value.to_bytes(2, "little") * (w * h)


def test_pack_parse_roundtrip():
    payload = _solid_rgb565(0xF800, 4, 3)  # red, 4x3 = 12 px
    blob = pack_frame(seq=42, width=4, height=3, payload=payload)
    assert len(blob) == HEADER_SIZE + 24
    f = parse_frame(blob)
    assert f.seq == 42
    assert f.width == 4
    assert f.height == 3
    assert f.payload == payload


def test_pack_rejects_wrong_size():
    with pytest.raises(ValueError):
        pack_frame(seq=0, width=2, height=2, payload=b"\x00" * 5)


def test_parse_truncated():
    blob = pack_frame(seq=1, width=2, height=2, payload=_solid_rgb565(0, 2, 2))
    with pytest.raises(ValueError):
        parse_frame(blob[:HEADER_SIZE + 3])


def test_read_latest_missing(tmp_path: Path):
    assert read_latest(tmp_path / "does-not-exist") is None


def test_read_latest_empty_file(tmp_path: Path):
    p = tmp_path / "empty.fb"
    p.write_bytes(b"")
    assert read_latest(p) is None


def test_read_latest_happy(tmp_path: Path):
    p = tmp_path / "fb"
    p.write_bytes(pack_frame(7, 8, 4, _solid_rgb565(0x07E0, 8, 4)))  # green
    f = read_latest(p)
    assert f is not None
    assert (f.seq, f.width, f.height) == (7, 8, 4)
    assert f.payload == _solid_rgb565(0x07E0, 8, 4)


def test_stream_frames_emits_init_then_updates(tmp_path: Path):
    p = tmp_path / "fb"
    # Pre-populate so the first poll succeeds immediately.
    p.write_bytes(pack_frame(1, 4, 2, _solid_rgb565(0x001F, 4, 2)))  # blue

    writer_done = threading.Event()

    def writer():
        # second frame, same dims, new seq
        time.sleep(0.05)
        p.write_bytes(pack_frame(2, 4, 2, _solid_rgb565(0xFFE0, 4, 2)))  # yellow
        time.sleep(0.05)
        # third frame, dims change → producer should emit a new FBInit
        p.write_bytes(pack_frame(3, 8, 4, _solid_rgb565(0xF81F, 8, 4)))  # magenta
        writer_done.set()

    t = threading.Thread(target=writer, daemon=True)
    t.start()

    frames = list(stream_frames(p, poll_interval_s=0.01, max_frames=3))
    assert writer_done.wait(timeout=2.0)

    # Frame 1: must include FBInit (first ever).
    init1, upd1, pay1 = frames[0]
    assert init1 is not None and (init1.width, init1.height) == (4, 2)
    assert (upd1.w, upd1.h) == (4, 2)
    assert pay1 == _solid_rgb565(0x001F, 4, 2)

    # Frame 2: same dims → no new FBInit.
    init2, upd2, pay2 = frames[1]
    assert init2 is None
    assert pay2 == _solid_rgb565(0xFFE0, 4, 2)

    # Frame 3: dims changed → FBInit re-emitted.
    init3, upd3, pay3 = frames[2]
    assert init3 is not None and (init3.width, init3.height) == (8, 4)
    assert (upd3.w, upd3.h) == (8, 4)
    assert pay3 == _solid_rgb565(0xF81F, 8, 4)
