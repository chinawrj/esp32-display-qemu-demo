"""CDP-driven UI verification of the framebuffer Chrome viewer.

Spawns the WebSocket+HTTP fb_server, opens the page in headless Chromium via
Playwright, and asserts that:
  1. the page reports `connected` status
  2. the canvas dimensions match the fb_init message
  3. the canvas has actually been painted (non-zero pixel sum, non-trivial colour count)
  4. successive screenshots differ (the moving rect producer animates)

A baseline screenshot is saved to artifacts/cdp-framebuffer.png for visual inspection.
"""
from __future__ import annotations

import hashlib
import time

import pytest

CONNECT_TIMEOUT_MS = 5_000
RENDER_SETTLE_MS = 1_500


def _wait_status_connected(page, ws_port: int, base_url: str) -> None:
    page.goto(f"{base_url}/index.html?ws={ws_port}")
    page.wait_for_selector("#status.connected", timeout=CONNECT_TIMEOUT_MS)


def test_page_reports_connected(fb_server, browser_page):
    _wait_status_connected(browser_page, fb_server["ws_port"], fb_server["base_url"])
    status_text = browser_page.locator("#status").inner_text()
    assert "connected" in status_text.lower()


def test_canvas_dimensions_match_fb_init(fb_server, browser_page):
    _wait_status_connected(browser_page, fb_server["ws_port"], fb_server["base_url"])
    browser_page.wait_for_function(
        "() => { const c = document.getElementById('fb'); return c && c.width > 0; }",
        timeout=CONNECT_TIMEOUT_MS,
    )
    dims = browser_page.evaluate(
        "() => { const c = document.getElementById('fb'); return [c.width, c.height]; }"
    )
    assert dims == [fb_server["width"], fb_server["height"]], dims


def test_canvas_has_painted_pixels(fb_server, browser_page, artifacts_dir):
    _wait_status_connected(browser_page, fb_server["ws_port"], fb_server["base_url"])
    browser_page.wait_for_timeout(RENDER_SETTLE_MS)

    stats = browser_page.evaluate(
        """
        () => {
          const c = document.getElementById('fb');
          const ctx = c.getContext('2d');
          const img = ctx.getImageData(0, 0, c.width, c.height);
          let sum = 0;
          const colours = new Set();
          for (let i = 0; i < img.data.length; i += 4) {
            sum += img.data[i] + img.data[i+1] + img.data[i+2];
            colours.add((img.data[i]<<16) | (img.data[i+1]<<8) | img.data[i+2]);
          }
          return { sum, unique: colours.size, w: c.width, h: c.height };
        }
        """
    )
    assert stats["sum"] > 0, f"canvas appears blank: {stats}"
    assert stats["unique"] >= 2, f"canvas has only {stats['unique']} colour(s): {stats}"

    # Save baseline screenshot of the canvas only (page-level shot would include UI chrome).
    canvas = browser_page.locator("#fb")
    out = artifacts_dir / "cdp-framebuffer.png"
    canvas.screenshot(path=str(out))
    assert out.exists() and out.stat().st_size > 0


def test_canvas_animates_over_time(fb_server, browser_page):
    _wait_status_connected(browser_page, fb_server["ws_port"], fb_server["base_url"])
    browser_page.wait_for_timeout(500)

    def pixel_digest() -> str:
        b64 = browser_page.evaluate(
            """
            () => {
              const c = document.getElementById('fb');
              const ctx = c.getContext('2d');
              const img = ctx.getImageData(0, 0, c.width, c.height);
              // hash a stride to keep payload small
              let s = '';
              for (let i = 0; i < img.data.length; i += 64) s += img.data[i].toString(16);
              return s;
            }
            """
        )
        return hashlib.md5(b64.encode()).hexdigest()

    first = pixel_digest()
    browser_page.wait_for_timeout(800)
    second = pixel_digest()
    assert first != second, "canvas content unchanged across 800 ms — producer not animating?"
