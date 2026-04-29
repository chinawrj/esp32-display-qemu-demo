"""Log-replay producer: parse a captured serial log and stream its FB frames.

This is the simplest possible bridge between "real ESP32/QEMU LVGL output" and
the Chrome viewer. It reuses the same FB_BEGIN/FB=/FB_END capture format that
`tools/decode-fb.py` already understands, so no firmware changes are required.

The serial-log producer is intentionally non-streaming: it parses the entire
log up front and emits every FB block it finds in a slow loop (default 1 fps),
re-cycling once exhausted. This is enough to render a real LVGL screenshot in
Chrome and prove the pipeline works end-to-end. Real-time push from a live
QEMU instance is a separate (later) milestone.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .protocol import FBInit, FBUpdate

_BEGIN_RE = re.compile(
    r"<<<FB_BEGIN\s+size=(?P<size>\d+)\s+w=(?P<w>\d+)\s+h=(?P<h>\d+)\s+fmt=(?P<fmt>\w+)>>>"
)
_END_MARK = "<<<FB_END>>>"
_PAYLOAD_RE = re.compile(r"^FB=([A-Za-z0-9+/=]+)\s*$")


@dataclass(frozen=True)
class LogFrame:
    width: int
    height: int
    fmt: str
    payload: bytes  # raw pixel bytes (RGB565 LE for fmt="RGB565")


def parse_log(text: str) -> list[LogFrame]:
    """Extract every complete FB_BEGIN..FB_END block from `text`.

    Lines between markers must each match ``FB=<base64>``. Lines that don't
    match are tolerated (e.g. interleaved ESP_LOG output) so this works on raw
    QEMU stdout. Incomplete trailing blocks (no FB_END) are skipped.
    """
    frames: list[LogFrame] = []
    cursor = 0
    while True:
        m = _BEGIN_RE.search(text, cursor)
        if not m:
            return frames
        body_start = m.end()
        end_idx = text.find(_END_MARK, body_start)
        if end_idx < 0:
            return frames
        body = text[body_start:end_idx]

        chunks = []
        for line in body.splitlines():
            pm = _PAYLOAD_RE.match(line.strip())
            if pm:
                chunks.append(pm.group(1))
        if chunks:
            try:
                raw = base64.b64decode("".join(chunks), validate=True)
            except (ValueError, base64.binascii.Error):
                cursor = end_idx + len(_END_MARK)
                continue
            w, h = int(m.group("w")), int(m.group("h"))
            expected = w * h * (2 if m.group("fmt") == "RGB565" else 4)
            if len(raw) == expected:
                frames.append(LogFrame(width=w, height=h, fmt=m.group("fmt"), payload=raw))
        cursor = end_idx + len(_END_MARK)


def parse_log_file(path: Path | str) -> list[LogFrame]:
    return parse_log(Path(path).read_text(errors="replace"))


def init_message_from_frame(frame: LogFrame) -> FBInit:
    return FBInit(width=frame.width, height=frame.height, format="RGB565")


def replay_frames(frames: list[LogFrame], period_s: float = 1.0) -> Iterator[FBUpdate]:
    """Yield each parsed frame as a full-screen FBUpdate, looping forever.

    Sleeps `period_s` between frames so the viewer can keep up and so a single
    captured screenshot is held visible long enough for a human (or Playwright)
    to look at it.
    """
    if not frames:
        raise ValueError("no FB frames found in log")
    import time
    while True:
        for f in frames:
            yield FBUpdate(
                x=0, y=0, w=f.width, h=f.height,
                payload=f.payload, format="RGB565", encoding="raw",
            )
            time.sleep(period_s)
