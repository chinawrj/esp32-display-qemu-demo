"""Wire protocol for the framebuffer WebSocket bridge.

Each WebSocket message is one of:

* ``fb_init``  — JSON only (text frame)
* ``fb_update`` — JSON header (text frame) immediately followed by a binary
  frame containing the raw pixel payload.

This keeps the framing trivial for the JS client (alternating text/binary).

JSON shapes::

    {"type": "fb_init",   "width": 240, "height": 135,
     "format": "RGB565",  "rotation": 0}

    {"type": "fb_update", "x": 0, "y": 0, "w": 240, "h": 135,
     "format": "RGB565",  "stride": 480, "encoding": "raw"}
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

PixelFormat = Literal["RGB565"]
Encoding = Literal["raw"]


@dataclass(frozen=True)
class FBInit:
    width: int
    height: int
    format: PixelFormat = "RGB565"
    rotation: int = 0

    def to_json(self) -> str:
        return json.dumps(
            {
                "type": "fb_init",
                "width": self.width,
                "height": self.height,
                "format": self.format,
                "rotation": self.rotation,
            }
        )


@dataclass(frozen=True)
class FBUpdate:
    x: int
    y: int
    w: int
    h: int
    payload: bytes
    format: PixelFormat = "RGB565"
    encoding: Encoding = "raw"

    @property
    def stride(self) -> int:
        bpp = 2 if self.format == "RGB565" else 4
        return self.w * bpp

    def header_json(self) -> str:
        return json.dumps(
            {
                "type": "fb_update",
                "x": self.x,
                "y": self.y,
                "w": self.w,
                "h": self.h,
                "format": self.format,
                "stride": self.stride,
                "encoding": self.encoding,
            }
        )

    def expected_payload_size(self) -> int:
        return self.h * self.stride

    def validate(self) -> None:
        if len(self.payload) != self.expected_payload_size():
            raise ValueError(
                f"payload size {len(self.payload)} != expected "
                f"{self.expected_payload_size()} (w={self.w} h={self.h} fmt={self.format})"
            )
