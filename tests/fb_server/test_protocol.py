"""Protocol unit tests."""
from __future__ import annotations

import json

import pytest

from tools.fb_server.protocol import FBInit, FBUpdate


def test_fb_init_json():
    msg = json.loads(FBInit(width=240, height=135).to_json())
    assert msg == {
        "type": "fb_init",
        "width": 240,
        "height": 135,
        "format": "RGB565",
        "rotation": 0,
    }


def test_fb_update_header_and_stride():
    upd = FBUpdate(x=10, y=20, w=30, h=15, payload=b"\x00" * 30 * 15 * 2)
    header = json.loads(upd.header_json())
    assert header == {
        "type": "fb_update",
        "x": 10, "y": 20, "w": 30, "h": 15,
        "format": "RGB565",
        "stride": 60,
        "encoding": "raw",
    }
    assert upd.expected_payload_size() == 30 * 15 * 2
    upd.validate()


def test_fb_update_validate_rejects_bad_payload():
    upd = FBUpdate(x=0, y=0, w=10, h=10, payload=b"\x00" * 5)
    with pytest.raises(ValueError, match="payload size"):
        upd.validate()
