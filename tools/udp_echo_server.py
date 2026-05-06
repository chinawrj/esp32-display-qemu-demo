#!/usr/bin/env python3
"""
tools/udp_echo_server.py - Simple UDP echo server for QEMU Wi-Fi tests.

Listens on 127.0.0.1:<port> (default 3333) and echoes back every received
datagram with a "Echo: " prefix.  Used by udp_client QEMU integration tests
where the firmware sends datagrams to 10.0.2.2:<port> and the relay maps
that to 127.0.0.1:<port>.

Usage:
  python3 tools/udp_echo_server.py [port]
  python3 tools/udp_echo_server.py 3333

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
    format="%(asctime)s [UDP-ECHO] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("udp_echo")


class UdpEchoProtocol(asyncio.DatagramProtocol):
    def __init__(self):
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        log.info("Received %d bytes from %s: %r", len(data), addr, data[:80])
        reply = b"Echo: " + data
        self.transport.sendto(reply, addr)
        log.info("Sent %d bytes back to %s", len(reply), addr)

    def error_received(self, exc):
        log.warning("Error: %s", exc)

    def connection_lost(self, exc):
        log.info("Connection closed")


async def run_server(host: str, port: int):
    loop = asyncio.get_running_loop()

    transport, protocol = await loop.create_datagram_endpoint(
        UdpEchoProtocol,
        local_addr=(host, port),
    )
    log.info("UDP echo server listening on %s:%d", host, port)

    stop_event = asyncio.Event()

    def _stop():
        log.info("Shutting down...")
        stop_event.set()

    loop.add_signal_handler(signal.SIGTERM, _stop)
    loop.add_signal_handler(signal.SIGINT, _stop)

    try:
        await stop_event.wait()
    finally:
        transport.close()


def main():
    parser = argparse.ArgumentParser(description="UDP echo server for QEMU Wi-Fi tests")
    parser.add_argument("port", nargs="?", type=int,
                        default=int(os.environ.get("UDP_ECHO_PORT", "3333")),
                        help="Port to listen on (default: 3333)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Host to bind (default: 127.0.0.1)")
    args = parser.parse_args()
    log.info("Starting UDP echo server on %s:%d", args.host, args.port)
    asyncio.run(run_server(args.host, args.port))


if __name__ == "__main__":
    main()
