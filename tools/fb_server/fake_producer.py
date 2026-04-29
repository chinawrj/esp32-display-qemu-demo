"""Synthetic framebuffer producer for development.

Generates a stream of ``FBUpdate`` messages animating a moving rectangle on a
solid background. Used by the WebSocket server when no real device transport is
attached, so the Chrome frontend can be developed and tested standalone.
"""
from __future__ import annotations

import struct
import time
from typing import Iterator

from .protocol import FBInit, FBUpdate


def rgb565(r: int, g: int, b: int) -> int:
    """Pack 8-bit RGB into RGB565 (little-endian on the wire)."""
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def solid_rect(w: int, h: int, color: int) -> bytes:
    """Return a w*h block of RGB565 pixels (little-endian) of one colour."""
    return struct.pack("<H", color) * (w * h)


def init_message(width: int, height: int) -> FBInit:
    return FBInit(width=width, height=height)


def initial_clear(width: int, height: int, bg: int = 0x0000) -> FBUpdate:
    """Full-screen clear to the given RGB565 colour (default black)."""
    return FBUpdate(x=0, y=0, w=width, h=height, payload=solid_rect(width, height, bg))


def moving_rect_frames(
    width: int = 240,
    height: int = 135,
    rect_w: int = 30,
    rect_h: int = 30,
    speed_px: int = 4,
    bg: int = rgb565(20, 20, 30),
    fg: int = rgb565(0xFF, 0x80, 0x20),
    fps: float = 30.0,
) -> Iterator[FBUpdate]:
    """Yield FBUpdate messages animating a rectangle bouncing horizontally.

    Each frame emits TWO updates: one to repaint the previous rect with bg,
    one to draw the new rect — exercising dirty-rect handling on the client.
    Yields forever; consumer controls timing.
    """
    x = 0
    direction = 1
    y = (height - rect_h) // 2
    bg_block = solid_rect(rect_w, rect_h, bg)
    fg_block = solid_rect(rect_w, rect_h, fg)
    period = 1.0 / fps if fps > 0 else 0.0

    prev_x = x
    while True:
        # Erase previous
        yield FBUpdate(x=prev_x, y=y, w=rect_w, h=rect_h, payload=bg_block)
        # Draw current
        yield FBUpdate(x=x, y=y, w=rect_w, h=rect_h, payload=fg_block)
        prev_x = x
        x += speed_px * direction
        if x + rect_w >= width:
            x = width - rect_w
            direction = -1
        elif x <= 0:
            x = 0
            direction = 1
        if period > 0:
            time.sleep(period)
