"""Unit tests for fb_server touch event ring buffer."""
from tools.fb_server.server import TOUCH_RING, record_touch


def test_record_touch_appends_entry():
    TOUCH_RING.clear()
    record_touch({"type": "touch", "event": "down", "x": 10, "y": 20, "id": 1}, peer="p1")
    assert len(TOUCH_RING) == 1
    e = TOUCH_RING[-1]
    assert e["event"] == "down"
    assert e["x"] == 10 and e["y"] == 20
    assert e["peer"] == "p1"


def test_ring_is_bounded():
    TOUCH_RING.clear()
    for i in range(400):
        record_touch({"type": "touch", "event": "move", "x": i, "y": i, "id": 0})
    assert len(TOUCH_RING) == TOUCH_RING.maxlen
    # Newest is the last one inserted
    assert TOUCH_RING[-1]["x"] == 399
