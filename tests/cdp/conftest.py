"""Fixtures for CDP/Playwright tests.

Spawns tools.fb_server.server in a subprocess (mirrors tests/fb_server pattern)
and exposes ws_port + http_port + base http URL for the test to drive Chromium
through Playwright.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"

FB_WIDTH = 240
FB_HEIGHT = 135


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_listening(host: str, port: int, timeout: float = 8.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            s.settimeout(0.2)
            try:
                s.connect((host, port))
                return True
            except OSError:
                time.sleep(0.1)
    return False


@pytest.fixture(scope="session")
def artifacts_dir() -> Path:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    return ARTIFACTS_DIR


@pytest.fixture
def fb_server():
    pytest.importorskip("websockets")
    pytest.importorskip("aiohttp")

    ws_port = _free_port()
    http_port = _free_port()
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "tools.fb_server.server",
            "--ws-port", str(ws_port),
            "--http-port", str(http_port),
            "--width", str(FB_WIDTH),
            "--height", str(FB_HEIGHT),
            "--fps", "30",
        ],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        if not _wait_listening("127.0.0.1", http_port) or not _wait_listening("127.0.0.1", ws_port):
            stdout, stderr = proc.communicate(timeout=2)
            raise RuntimeError(
                f"fb_server didn't start.\nstdout: {stdout.decode(errors='replace')}\n"
                f"stderr: {stderr.decode(errors='replace')}"
            )
        yield {
            "ws_port": ws_port,
            "http_port": http_port,
            "base_url": f"http://127.0.0.1:{http_port}",
            "width": FB_WIDTH,
            "height": FB_HEIGHT,
        }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture
def browser_page():
    """Boot Chromium headless, yield (browser, context, page); cleanup on teardown."""
    playwright_mod = pytest.importorskip("playwright.sync_api")
    sync_playwright = playwright_mod.sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1024, "height": 600})
        page = context.new_page()
        try:
            yield page
        finally:
            context.close()
            browser.close()
