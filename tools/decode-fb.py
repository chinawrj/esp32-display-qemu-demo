#!/usr/bin/env python3
"""Decode a framebuffer dumped by the firmware over UART into a PNG.

The firmware emits a block bracketed by sentinels:

    <<<FB_BEGIN size=64800 w=240 h=135 fmt=RGB565>>>
    FB=<base64 line 1>
    FB=<base64 line 2>
    ...
    <<<FB_END>>>

This script extracts the block, base64-decodes the payload, converts
RGB565 little-endian pixels to RGB888, and writes a PNG.

Usage:
    python3 tools/decode-fb.py <serial.log> <output.png>

Exit codes:
    0  success
    1  no FB block found
    2  payload size mismatch
    3  format mismatch (only RGB565 supported)
"""
from __future__ import annotations

import argparse
import base64
import re
import sys
from pathlib import Path

from PIL import Image

BEGIN_RE = re.compile(
    r"<<<FB_BEGIN\s+size=(?P<size>\d+)\s+w=(?P<w>\d+)\s+h=(?P<h>\d+)\s+fmt=(?P<fmt>\w+)>>>"
)
END_MARK = "<<<FB_END>>>"
PAYLOAD_RE = re.compile(r"^FB=([A-Za-z0-9+/=]+)\s*$")


def extract_block(text: str) -> tuple[dict, bytes]:
    m = BEGIN_RE.search(text)
    if not m:
        raise SystemExit("ERROR: no <<<FB_BEGIN ...>>> marker found")
    header = {
        "size": int(m.group("size")),
        "w": int(m.group("w")),
        "h": int(m.group("h")),
        "fmt": m.group("fmt"),
    }
    after = text[m.end():]
    end_idx = after.find(END_MARK)
    if end_idx < 0:
        raise SystemExit("ERROR: no <<<FB_END>>> marker found")
    body = after[:end_idx]

    chunks = []
    for line in body.splitlines():
        # Strip ESP-IDF UART prefix noise (e.g. "I (1234) tag:") if present
        m2 = PAYLOAD_RE.match(line.strip())
        if m2:
            chunks.append(m2.group(1))
    if not chunks:
        raise SystemExit("ERROR: no FB= payload lines between markers")
    raw = base64.b64decode("".join(chunks), validate=True)
    return header, raw


def rgb565_le_to_rgb888(raw: bytes, w: int, h: int) -> bytes:
    expected = w * h * 2
    if len(raw) != expected:
        raise SystemExit(
            f"ERROR: payload size {len(raw)} != expected {expected} (w={w} h={h})"
        )
    out = bytearray(w * h * 3)
    for i in range(w * h):
        lo = raw[2 * i]
        hi = raw[2 * i + 1]
        px = (hi << 8) | lo
        r5 = (px >> 11) & 0x1F
        g6 = (px >> 5) & 0x3F
        b5 = px & 0x1F
        # Bit-replication scaling (matches LVGL's reference conversion)
        out[3 * i + 0] = (r5 << 3) | (r5 >> 2)
        out[3 * i + 1] = (g6 << 2) | (g6 >> 4)
        out[3 * i + 2] = (b5 << 3) | (b5 >> 2)
    return bytes(out)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("log", type=Path, help="serial log containing FB block")
    p.add_argument("out", type=Path, help="output PNG path")
    p.add_argument("--scale", type=int, default=1, help="upscale factor (nearest)")
    args = p.parse_args()

    text = args.log.read_text(errors="replace")
    header, raw = extract_block(text)

    if header["fmt"] != "RGB565":
        print(f"ERROR: unsupported fmt {header['fmt']}", file=sys.stderr)
        return 3
    if header["size"] != len(raw):
        print(
            f"ERROR: header size {header['size']} != decoded {len(raw)}",
            file=sys.stderr,
        )
        return 2

    rgb = rgb565_le_to_rgb888(raw, header["w"], header["h"])
    img = Image.frombytes("RGB", (header["w"], header["h"]), rgb)
    if args.scale > 1:
        img = img.resize(
            (header["w"] * args.scale, header["h"] * args.scale),
            Image.Resampling.NEAREST,
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out, format="PNG", optimize=True)
    print(
        f"OK: decoded {header['w']}x{header['h']} {header['fmt']} "
        f"({len(raw)} bytes) -> {args.out} "
        f"({args.out.stat().st_size} bytes)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
