#!/usr/bin/env python3
"""
echo_server.py — minimal TCP echo server for NEXT-004 lwIP probe tests.

Listens on 127.0.0.1:<PORT>, responds to any recv() with "PONG\n".
Used by tools/run-direct-demo.sh and pytest fixtures so the firmware's
lwip_probe task can prove end-to-end TCP data-plane connectivity.

Usage:
    python3 tools/echo_server.py <port>
"""
import socket
import sys
import threading


def _handle(conn: socket.socket) -> None:
    try:
        data = conn.recv(64)
        if data:
            conn.sendall(b"PONG\n")
    except OSError:
        pass
    finally:
        conn.close()


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <port>", file=sys.stderr)
        sys.exit(1)

    port = int(sys.argv[1])
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(8)
    print(f"[echo_server] listening on 127.0.0.1:{port}", flush=True)

    while True:
        conn, addr = srv.accept()
        threading.Thread(target=_handle, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
