#!/usr/bin/env python3
"""Tiny standalone Playwright smoke check used by ``run-demo.sh --auto-test``.

Reads the URL from ``$FB_URL``, opens it in headless Chromium, waits for
the canvas to be painted (non-zero pixel sum, ≥2 distinct colours), saves
``artifacts/run-demo-canvas.png``, and exits 0 on success.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

URL = os.environ.get("FB_URL", "http://127.0.0.1:8080/index.html?ws=7788")
ARTIFACT = Path(__file__).resolve().parents[1] / "artifacts" / "run-demo-canvas.png"
ARTIFACT.parent.mkdir(parents=True, exist_ok=True)


def main() -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_context(viewport={"width": 1024, "height": 600}).new_page()
        try:
            page.goto(URL)
            page.wait_for_selector("#status.connected", timeout=8_000)
            page.wait_for_function(
                "() => { const c = document.getElementById('fb');"
                " return c && c.width > 0 && c.height > 0; }",
                timeout=8_000,
            )

            # Poll up to ~30 s for real LVGL content to land. The frozen-
            # snapshot region (y=200) only gets written once, on flush #80,
            # which happens a few seconds into the benchmark.
            import time as _t
            deadline = _t.time() + 30.0
            stats = None
            while _t.time() < deadline:
                stats = page.evaluate(
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
                if stats["sum"] > 0 and stats["unique"] >= 8:
                    break
                page.wait_for_timeout(500)
            assert stats is not None
            print(f"[auto-test] canvas {stats['w']}x{stats['h']}  sum={stats['sum']}  unique={stats['unique']}")
            if stats["sum"] <= 0 or stats["unique"] < 8:
                print(f"[auto-test] FAIL: canvas not showing real LVGL content: {stats}", file=sys.stderr)
                return 1

            page.locator("#fb").screenshot(path=str(ARTIFACT))
            print(f"[auto-test] saved {ARTIFACT}")
            return 0
        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
