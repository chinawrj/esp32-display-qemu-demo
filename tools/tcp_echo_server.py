#!/usr/bin/env python3
"""
tools/tcp_echo_server.py - Simple TCP echo server for QEMU Wi-Fi tests.

Listens on 127.0.0.1:<port> (default 3333) and echoes back every received
message with a "Echo: " prefix.  Used by tcp_client QEMU integration tests
where the firmware connects to 10.0.2.2:<port> and the relay maps that to
127.0.0.1:<port>.

Usage:
  python3 tools/tcp_echo_server.py [port]
  python3 tools/tcp_echo_server.py 3333

The server runs until killed (Ctrl-C or SIGTERM).
"""

import argparse
import asyncio
import logging
import os
import signal
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [TCP-ECHO] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("tcp_echo")


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    addr = writer.get_extra_info("peername")
    log.info("Client connected from %s", addr)
    try:
        while True:
            data = await reader.read(4096)
            if not data:
                break
            log.info("Received %d bytes: %r", len(data), data[:80])
            reply = b"Echo: " + data
            writer.write(reply)
            await writer.drain()
            log.info("Sent %d bytes back", len(reply))
    except (asyncio.IncompleteReadError, ConnectionResetError):
        pass
    finally:
        log.info("Client %s disconnected", addr)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def run_server(host: str, port: int):
    server = await asyncio.start_server(handle_client, host, port)
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets)
    log.info("TCP echo server listening on %s", addrs)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _stop():
        log.info("Shutting down...")
        stop_event.set()

    loop.add_signal_handler(signal.SIGTERM, _stop)
    loop.add_signal_handler(signal.SIGINT, _stop)

    async with server:
        await stop_event.wait()


def main():
    parser = argparse.ArgumentParser(description="TCP echo server for QEMU Wi-Fi tests")
    parser.add_argument("port", nargs="?", type=int,
                        default=int(os.environ.get("TCP_ECHO_PORT", "3333")),
                        help="Port to listen on (default: 3333)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Host to bind (default: 127.0.0.1)")
    args = parser.parse_args()
    log.info("Starting TCP echo server on %s:%d", args.host, args.port)
    asyncio.run(run_server(args.host, args.port))


if __name__ == "__main__":
    main()
