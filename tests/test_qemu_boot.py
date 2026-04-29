"""Verify the LVGL benchmark boots and renders inside QEMU.

Mirrors the 10 checks in tools/run-qemu.sh, one per pytest case so failures
show up individually in CI.
"""
from __future__ import annotations

import re

import pytest

# (test_id, human_label, regex)
CHECKS = [
    ("app_main_reached",            "app_main reached",                 r"esp32-display-qemu-demo starting"),
    ("lvgl_initialized",            "lvgl initialized log",             r"lvgl initialized: v[0-9]+\.[0-9]+"),
    ("lvgl_display_created",        "lvgl display created",             r"lvgl display created: [0-9]+x[0-9]+"),
    ("lvgl_flush_fired",            "lvgl flush callback fired",        r"lvgl flush #"),
    ("demo_started",                "demo started",                     r"lv_demo_benchmark started"),
    ("demo_rendered_30_flushes",    "demo rendered >=30 flushes",       r"lvgl flush total: ([3-9][0-9]|[1-9][0-9]{2,})"),
    ("fb_capture_begin_marker",     "framebuffer capture begin marker", r"<<<FB_BEGIN size=64800 w=240 h=135 fmt=RGB565>>>"),
    ("fb_capture_end_marker",       "framebuffer capture end marker",   r"<<<FB_END>>>"),
    ("demo_completion_banner",      "demo completion banner",           r"M3 LVGL benchmark demo complete"),
]


@pytest.mark.parametrize(
    ("label", "pattern"),
    [(label, pattern) for _id, label, pattern in CHECKS],
    ids=[cid for cid, _, _ in CHECKS],
)
def test_serial_marker(qemu_log_text: str, label: str, pattern: str) -> None:
    assert re.search(pattern, qemu_log_text), (
        f"Expected log marker not found: {label!r}\n  pattern: {pattern}"
    )


def test_framebuffer_payload_line_count(qemu_log_text: str) -> None:
    """64800 bytes / 3 * 4 / 60 chars per line == 1440 lines, prefixed FB=."""
    fb_lines = sum(1 for line in qemu_log_text.splitlines() if line.startswith("FB="))
    assert fb_lines == 1440, f"Expected 1440 FB= lines, got {fb_lines}"
