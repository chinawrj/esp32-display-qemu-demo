"""Phase-3 host slice: Chrome canvas pointer events → server /api/touches.

Verifies:
- Page wires pointer events on the canvas
- Click on the canvas at known CSS coords sends a structured WS touch
  message to the server
- Server records the event in its ring buffer and exposes it via
  /api/touches with correctly transformed device coordinates
- The UI shows the most recent touch ("last touch: down (x,y)")
"""
from __future__ import annotations

import time
import urllib.request
import json


def _get_touches(base_url: str) -> list[dict]:
    with urllib.request.urlopen(f"{base_url}/api/touches", timeout=10) as r:
        return json.loads(r.read())["touches"]


def _clear_touches(base_url: str) -> None:
    req = urllib.request.Request(f"{base_url}/api/touches/clear", method="POST")
    urllib.request.urlopen(req, timeout=10).read()


def test_canvas_click_recorded_by_server(fb_server, browser_page, artifacts_dir):
    page = browser_page
    base_url = fb_server["base_url"]
    ws_port = fb_server["ws_port"]
    page.goto(f"{base_url}/index.html?ws={ws_port}")
    page.wait_for_selector("#status.connected", timeout=5000)
    # Wait for fb_init so canvas has its real device-pixel dimensions
    page.wait_for_function(
        f"document.querySelector('#fb').width === {fb_server['width']}", timeout=5000)

    box = page.locator("#fb").bounding_box()
    assert box is not None
    # Click roughly in the centre — exact coords don't matter; we only
    # assert the server receives a sane event.
    cx = box["x"] + box["width"] / 2
    cy = box["y"] + box["height"] / 2
    page.mouse.click(cx, cy)

    # Allow the WS round-trip
    deadline = time.time() + 3.0
    touches: list[dict] = []
    while time.time() < deadline:
        touches = _get_touches(fb_server["base_url"])
        if any(t.get("event") == "down" for t in touches):
            break
        time.sleep(0.1)

    assert touches, "no touch events recorded by server"
    downs = [t for t in touches if t["event"] == "down"]
    ups = [t for t in touches if t["event"] == "up"]
    assert downs, f"no 'down' event in {touches}"
    assert ups, f"no 'up' event in {touches}"

    d = downs[0]
    assert 0 <= d["x"] < fb_server["width"], d
    assert 0 <= d["y"] < fb_server["height"], d
    # Centre click should land roughly mid-canvas (allow generous slack)
    assert abs(d["x"] - fb_server["width"] // 2) < fb_server["width"] // 4
    assert abs(d["y"] - fb_server["height"] // 2) < fb_server["height"] // 4

    # UI reflects the touch (latest event will be 'up' after a click)
    last_touch_text = page.locator("#last-touch").inner_text()
    assert "last touch" in last_touch_text, last_touch_text
    assert any(kw in last_touch_text for kw in ("down", "up")), last_touch_text

    page.screenshot(path=str(artifacts_dir / "cdp-touch-input.png"))


def test_drag_emits_move_events(fb_server, browser_page):
    page = browser_page
    base_url = fb_server["base_url"]
    ws_port = fb_server["ws_port"]
    page.goto(f"{base_url}/index.html?ws={ws_port}")
    page.wait_for_selector("#status.connected", timeout=5000)
    page.wait_for_function(
        f"document.querySelector('#fb').width === {fb_server['width']}", timeout=5000)

    # Clear any prior events from the previous test (ring is process-scoped).
    _clear_touches(fb_server["base_url"])

    box = page.locator("#fb").bounding_box()
    assert box is not None
    sx = box["x"] + box["width"] * 0.25
    sy = box["y"] + box["height"] * 0.5
    ex = box["x"] + box["width"] * 0.75
    ey = box["y"] + box["height"] * 0.5

    page.mouse.move(sx, sy)
    page.mouse.down()
    # several intermediate moves
    for f in (0.25, 0.5, 0.75, 1.0):
        page.mouse.move(sx + (ex - sx) * f, sy + (ey - sy) * f)
    page.mouse.up()

    deadline = time.time() + 3.0
    touches: list[dict] = []
    while time.time() < deadline:
        touches = _get_touches(fb_server["base_url"])
        if any(t.get("event") == "up" for t in touches):
            break
        time.sleep(0.1)

    moves = [t for t in touches if t["event"] == "move"]
    assert len(moves) >= 2, f"expected several move events, got {touches}"
    # X should increase across the drag
    xs = [m["x"] for m in moves]
    assert xs[-1] > xs[0], f"drag should increase x: {xs}"
