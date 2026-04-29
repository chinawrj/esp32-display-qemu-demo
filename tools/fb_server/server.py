"""WebSocket framebuffer bridge + tiny static HTTP server.

Run::

    python -m tools.fb_server.server                # ws on 7788, http on 8080
    python -m tools.fb_server.server --width 320 --height 240

Then open http://127.0.0.1:8080 in Chrome — it connects to ws://127.0.0.1:7788
and renders the fake producer's animated framebuffer.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import sys
from collections import deque
from pathlib import Path

import websockets
from aiohttp import web

from .fake_producer import initial_clear, init_message, moving_rect_frames
from .log_producer import init_message_from_frame, parse_log_file, replay_frames

LOG = logging.getLogger("fb_server")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_ROOT / "web"

# Phase-3 host slice: ring buffer of recent touch events from connected
# Chrome clients. Exposed over HTTP at /api/touches for Playwright tests
# and host-side debugging until the firmware-side LVGL indev is wired up.
TOUCH_RING_MAX = 256
TOUCH_RING: "deque[dict]" = deque(maxlen=TOUCH_RING_MAX)


def record_touch(msg: dict, peer: str | None = None) -> None:
    entry = {**msg, "peer": peer}
    TOUCH_RING.append(entry)
    LOG.info("touch %s (%s,%s) id=%s peer=%s",
             msg.get("event"), msg.get("x"), msg.get("y"),
             msg.get("id"), peer)


async def fake_producer_loop(ws, width: int, height: int, fps: float) -> None:
    """Send fb_init then a stream of fb_update messages until the client disconnects."""
    await ws.send(init_message(width, height).to_json())
    LOG.info("fb_init sent (client=%s, %dx%d)", ws.remote_address, width, height)

    clear = initial_clear(width, height)
    await ws.send(clear.header_json())
    await ws.send(clear.payload)

    # fps=0 disables the generator's internal sleep so the asyncio loop can
    # service receiver_loop / HTTP handlers between frames.
    period = 1.0 / fps if fps > 0 else 0.0
    frames = moving_rect_frames(width=width, height=height, fps=0.0)
    try:
        for update in frames:
            update.validate()
            await ws.send(update.header_json())
            await ws.send(update.payload)
            if period > 0:
                await asyncio.sleep(period)
    except websockets.ConnectionClosed:
        LOG.info("client %s disconnected", ws.remote_address)


async def log_producer_loop(ws, log_path: Path, period_s: float) -> None:
    """Replay captured FB frames from a serial log file."""
    frames = parse_log_file(log_path)
    if not frames:
        LOG.error("no FB frames found in %s", log_path)
        await ws.close(code=1011, reason="no frames in log")
        return
    LOG.info("loaded %d frame(s) from %s", len(frames), log_path)

    init = init_message_from_frame(frames[0])
    await ws.send(init.to_json())
    LOG.info("fb_init sent (client=%s, %dx%d from log)",
             ws.remote_address, init.width, init.height)

    try:
        # period_s=0 disables generator sleep; we use asyncio.sleep instead.
        for update in replay_frames(frames, period_s=0.0):
            update.validate()
            await ws.send(update.header_json())
            await ws.send(update.payload)
            if period_s > 0:
                await asyncio.sleep(period_s)
    except websockets.ConnectionClosed:
        LOG.info("client %s disconnected", ws.remote_address)


async def receiver_loop(ws) -> None:
    """Drain incoming text messages from the client. Recognises {type:'touch',...}."""
    peer = f"{ws.remote_address[0]}:{ws.remote_address[1]}" if ws.remote_address else None
    try:
        async for raw in ws:
            if not isinstance(raw, str):
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                LOG.warning("bad json from %s: %s", peer, raw[:120])
                continue
            if msg.get("type") == "touch":
                record_touch(msg, peer)
            else:
                LOG.debug("unknown client msg from %s: %s", peer, msg.get("type"))
    except websockets.ConnectionClosed:
        pass


def make_ws_handler(args: argparse.Namespace):
    async def handler(ws):
        LOG.info("client connected: %s", ws.remote_address)
        recv_task = asyncio.create_task(receiver_loop(ws))
        try:
            if args.source == "log":
                period = 1.0 / args.fps if args.fps > 0 else 1.0
                await log_producer_loop(ws, Path(args.fb_log), period)
            else:
                await fake_producer_loop(ws, args.width, args.height, args.fps)
        except Exception as exc:  # pragma: no cover — visibility on bugs
            LOG.exception("producer crashed: %s", exc)
        finally:
            recv_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await recv_task

    return handler


async def serve_static(http_host: str, http_port: int) -> web.AppRunner:
    app = web.Application()

    async def touches_handler(_request):
        return web.json_response({"touches": list(TOUCH_RING)})

    async def touches_clear(_request):
        TOUCH_RING.clear()
        return web.json_response({"ok": True})

    app.router.add_get("/api/touches", touches_handler)
    app.router.add_post("/api/touches/clear", touches_clear)
    app.router.add_static("/", path=str(WEB_DIR), show_index=True, follow_symlinks=False)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, http_host, http_port)
    await site.start()
    LOG.info("HTTP serving %s on http://%s:%d", WEB_DIR, http_host, http_port)
    return runner


async def amain(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    handler = make_ws_handler(args)
    ws_server = await websockets.serve(handler, args.ws_host, args.ws_port)
    LOG.info("WebSocket serving on ws://%s:%d", args.ws_host, args.ws_port)

    runner = await serve_static(args.http_host, args.http_port)

    stop = asyncio.Event()
    try:
        await stop.wait()
    finally:
        ws_server.close()
        await ws_server.wait_closed()
        await runner.cleanup()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", choices=("fake", "log"), default="fake",
                   help="frame source: synthetic moving-rect (fake) or replay from a captured serial log (log)")
    p.add_argument("--fb-log", type=str, default=None,
                   help="serial log path (required when --source=log)")
    p.add_argument("--width", type=int, default=240)
    p.add_argument("--height", type=int, default=135)
    p.add_argument("--fps", type=float, default=30.0,
                   help="frames per second; for --source=log this is the loop rate (default 30, use ~1 for slow replay)")
    p.add_argument("--ws-host", default="127.0.0.1")
    p.add_argument("--ws-port", type=int, default=7788)
    p.add_argument("--http-host", default="127.0.0.1")
    p.add_argument("--http-port", type=int, default=8080)
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    if args.source == "log" and not args.fb_log:
        p.error("--source=log requires --fb-log <path>")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        asyncio.run(amain(args))
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
