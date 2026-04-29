"""Shared-memory framebuffer producer.

Host-side reader for the ``qemu-fb-shmem-bridge`` path described in
``docs/qemu-native-fb.md``. The eventual goal is a custom QEMU device that
writes the LVGL framebuffer into a ``memory-backend-file`` region; the host
mmaps the same file and forwards frames to Chrome through the existing
``fb_server`` WebSocket pipeline.

The QEMU device model patch is deferred future work. This module implements
the host slice today so the wire path is testable end-to-end:

* a writer (firmware-side or test) appends an 8-byte little-endian header
  ``[u32 frame_seq][u16 width][u16 height]`` followed by ``width*height*2``
  bytes of RGB565 pixel data into the shmem file;
* this producer ``mmap``-reads the same file, emits an ``FBInit`` once per
  resolution change, and then yields an ``FBUpdate`` + payload tuple for every
  new ``frame_seq``.

The header layout is local to this project — the QEMU patch (when written)
must match. It's small on purpose so the device model is trivial.
"""
from __future__ import annotations

import mmap
import os
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .protocol import FBInit, FBUpdate

# Header: u32 seq | u16 width | u16 height (little-endian, 8 bytes)
_HEADER = struct.Struct("<IHH")
HEADER_SIZE = _HEADER.size


@dataclass(frozen=True)
class ShmemFrame:
    seq: int
    width: int
    height: int
    payload: bytes  # raw RGB565 LE


def pack_frame(seq: int, width: int, height: int, payload: bytes) -> bytes:
    """Build a writer-side blob: header + pixel bytes.

    ``len(payload)`` must equal ``width * height * 2`` (RGB565).
    """
    expected = width * height * 2
    if len(payload) != expected:
        raise ValueError(f"payload size {len(payload)} != {expected} (w*h*2)")
    return _HEADER.pack(seq, width, height) + payload


def parse_frame(buf: bytes) -> ShmemFrame:
    """Inverse of :func:`pack_frame`. Raises ``ValueError`` on truncation."""
    if len(buf) < HEADER_SIZE:
        raise ValueError(f"buffer too small ({len(buf)} < {HEADER_SIZE})")
    seq, w, h = _HEADER.unpack_from(buf, 0)
    expected = w * h * 2
    if len(buf) < HEADER_SIZE + expected:
        raise ValueError(
            f"buffer truncated: have {len(buf)} bytes, need {HEADER_SIZE + expected}"
        )
    payload = bytes(buf[HEADER_SIZE : HEADER_SIZE + expected])
    return ShmemFrame(seq=seq, width=w, height=h, payload=payload)


def read_latest(path: Path | str) -> ShmemFrame | None:
    """Read whatever frame currently sits in the shmem file. Returns ``None``
    if the file is empty / missing / truncated."""
    p = Path(path)
    if not p.exists() or p.stat().st_size < HEADER_SIZE:
        return None
    with p.open("rb") as f:
        size = os.fstat(f.fileno()).st_size
        if size == 0:
            return None
        with mmap.mmap(f.fileno(), size, prot=mmap.PROT_READ) as mm:
            try:
                return parse_frame(bytes(mm))
            except ValueError:
                return None


def stream_frames(
    path: Path | str,
    poll_interval_s: float = 0.05,
    max_frames: int | None = None,
) -> Iterator[tuple[FBInit | None, FBUpdate, bytes]]:
    """Poll the shmem file and yield new frames as they appear.

    Yields ``(fb_init_or_None, fb_update, payload)`` tuples. ``fb_init`` is
    populated only on the first frame and whenever the resolution changes;
    callers should send it down the WS once per change.

    Stops after ``max_frames`` (useful for tests); pass ``None`` to run
    forever.
    """
    last_seq: int | None = None
    last_dims: tuple[int, int] | None = None
    emitted = 0
    while True:
        frame = read_latest(path)
        if frame is not None and frame.seq != last_seq:
            init: FBInit | None = None
            dims = (frame.width, frame.height)
            if dims != last_dims:
                init = FBInit(width=frame.width, height=frame.height)
                last_dims = dims
            update = FBUpdate(
                x=0,
                y=0,
                w=frame.width,
                h=frame.height,
                payload=frame.payload,
            )
            yield init, update, frame.payload
            last_seq = frame.seq
            emitted += 1
            if max_frames is not None and emitted >= max_frames:
                return
        time.sleep(poll_interval_s)
