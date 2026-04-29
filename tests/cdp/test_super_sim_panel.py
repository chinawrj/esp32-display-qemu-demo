"""Phase-6 super-sim side-panel smoke tests.

Verifies that the side panel renders, the screenshot button creates a PNG
download, and that synthetic telemetry/log frames pushed over WebSocket are
displayed in the right slots.
"""
from __future__ import annotations


def test_sidepanel_renders(fb_server, browser_page):
    page = browser_page
    page.goto(f"{fb_server['base_url']}/index.html?ws={fb_server['ws_port']}")
    page.wait_for_selector("#status.connected", timeout=8000)
    # The four side-panel sections + their key DOM nodes must exist.
    for sel in ("#sidepanel", "#wifi-state", "#sys-heap", "#logs", "#btn-screenshot"):
        assert page.locator(sel).count() == 1, f"missing {sel}"


def test_screenshot_button_downloads_png(fb_server, browser_page, artifacts_dir):
    page = browser_page
    page.goto(f"{fb_server['base_url']}/index.html?ws={fb_server['ws_port']}")
    page.wait_for_selector("#status.connected", timeout=8000)
    page.wait_for_function(
        "() => { const c = document.getElementById('fb'); return c && c.width > 0; }",
        timeout=8000,
    )
    page.wait_for_function(
        "() => document.getElementById('last-update').textContent.includes('last update')",
        timeout=8000,
    )
    with page.expect_download(timeout=8000) as dl_info:
        page.evaluate("document.getElementById('btn-screenshot').click()")
    download = dl_info.value
    out = artifacts_dir / "cdp-super-sim-screenshot.png"
    download.save_as(out)
    assert out.stat().st_size > 100, "screenshot PNG too small"
    assert download.suggested_filename.endswith(".png")


def test_telemetry_and_log_frames_render(fb_server, browser_page):
    """Telemetry + log frames update the right side-panel slots."""
    page = browser_page
    page.goto(f"{fb_server['base_url']}/index.html?ws={fb_server['ws_port']}")
    page.wait_for_selector("#status.connected", timeout=8000)
    # Wait for the test hook exposed by main.js
    page.wait_for_function("() => !!(window.__superSim && window.__superSim.applyTelemetry)", timeout=5000)

    page.evaluate(
        """
        () => {
          const s = window.__superSim;
          s.applyTelemetry({
            wifi: {state:'STA_GOT_IP', ssid:'demo', ip:'10.0.0.7', rssi:-45},
            sys:  {heap:123456, uptime:42, tasks:17},
          });
          s.appendLog('I','app','boot ok');
          s.appendLog('W','wifi','weak signal');
        }
        """
    )

    assert page.locator("#wifi-state").inner_text() == "STA_GOT_IP"
    assert page.locator("#wifi-ip").inner_text() == "10.0.0.7"
    assert "dBm" in page.locator("#wifi-rssi").inner_text()
    assert "B" in page.locator("#sys-heap").inner_text()
    assert page.locator("#logs li").count() == 2
    assert page.locator("#logs li.log-W").count() == 1
