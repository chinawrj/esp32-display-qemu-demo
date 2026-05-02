#!/usr/bin/env python3
"""
Mock wpa_supplicant ctrl daemon for QEMU esp_wifi device testing.

Usage:
    python3 tools/mock-wpa-supplicant.py [options]
    python3 tools/mock-wpa-supplicant.py --ctrl-path /tmp/mock-wpa-ctrl --ssid TestAP --ip 192.168.1.100

The daemon creates a Unix DGRAM socket and responds to the subset of
wpa_supplicant ctrl commands used by the QEMU esp_wifi device:
  ATTACH, DETACH, SCAN, SCAN_RESULTS, ADD_NETWORK, SET_NETWORK,
  SELECT_NETWORK, STATUS, DISABLE_NETWORK.
"""

import argparse
import os
import signal
import socket
import sys
import threading
import time


class MockWpaSupplicant:
    """Minimal wpa_supplicant ctrl socket mock."""

    def __init__(self, ctrl_path, ssid="TestAP", password="testpass",
                 ip="192.168.1.100", mac="02:00:00:00:00:01",
                 scan_delay=0.1, connect_delay=0.3):
        self.ctrl_path    = ctrl_path
        self.ssid         = ssid
        self.password     = password
        self.ip           = ip
        self.mac          = mac
        self.scan_delay   = scan_delay
        self.connect_delay = connect_delay

        self._sock        = None
        self._running     = False
        self._thread      = None
        self._net_counter = 0
        self._networks    = {}
        # set of client paths that have sent ATTACH
        self._attached_clients: set = set()

    # ------------------------------------------------------------------

    def start(self):
        """Create socket, start background thread."""
        if os.path.exists(self.ctrl_path):
            os.unlink(self.ctrl_path)
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self._sock.bind(self.ctrl_path)
        os.chmod(self.ctrl_path, 0o666)
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True,
                                         name="mock-wpa")
        self._thread.start()
        print(f"[mock-wpa] listening on {self.ctrl_path}", flush=True)

    def stop(self):
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        if os.path.exists(self.ctrl_path):
            try:
                os.unlink(self.ctrl_path)
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=2)
        print("[mock-wpa] stopped", flush=True)

    # ------------------------------------------------------------------

    def _send_to(self, client_path, msg: str):
        try:
            self._sock.sendto(msg.encode(), client_path)
        except OSError as e:
            print(f"[mock-wpa] send to {client_path}: {e}", flush=True)

    def _broadcast_event(self, event: str):
        """Send an unsolicited event to all attached clients."""
        for cpath in list(self._attached_clients):
            self._send_to(cpath, event)

    def _delayed_event(self, delay: float, event: str):
        def _fire():
            time.sleep(delay)
            if self._running:
                self._broadcast_event(event)
        threading.Thread(target=_fire, daemon=True).start()

    # ------------------------------------------------------------------

    def _handle(self, cmd: str, client_path):
        """Dispatch a single command, return (response, schedule_event)."""
        cmd = cmd.strip()
        print(f"[mock-wpa] <- '{cmd}' from {client_path}", flush=True)

        if cmd == "ATTACH":
            self._attached_clients.add(client_path)
            return "OK\n"

        if cmd == "DETACH":
            self._attached_clients.discard(client_path)
            return "OK\n"

        if cmd == "SCAN":
            self._delayed_event(self.scan_delay, "<3>CTRL-EVENT-SCAN-RESULTS \n")
            return "OK\n"

        if cmd == "SCAN_RESULTS":
            # Return a single fake AP
            return (
                "bssid / frequency / signal level / flags / ssid\n"
                f"aa:bb:cc:dd:ee:ff\t2412\t-50\t[WPA2-PSK-CCMP]\t{self.ssid}\n"
            )

        if cmd == "ADD_NETWORK":
            net_id = self._net_counter
            self._net_counter += 1
            self._networks[net_id] = {}
            return f"{net_id}\n"

        if cmd.startswith("SET_NETWORK "):
            # SET_NETWORK <id> <key> <value>
            parts = cmd.split(" ", 3)
            if len(parts) >= 4:
                try:
                    net_id = int(parts[1])
                except ValueError:
                    return "FAIL\n"
                key = parts[2]
                val = parts[3].strip('"')
                if net_id in self._networks:
                    self._networks[net_id][key] = val
                    return "OK\n"
            return "FAIL\n"

        if cmd.startswith("SELECT_NETWORK "):
            event = (
                f"<3>CTRL-EVENT-CONNECTED - Connection to aa:bb:cc:dd:ee:ff "
                f"completed [id=0 id_str=]\n"
            )
            self._delayed_event(self.connect_delay, event)
            return "OK\n"

        if cmd == "STATUS":
            return (
                f"bssid=aa:bb:cc:dd:ee:ff\n"
                f"ssid={self.ssid}\n"
                f"id=0\n"
                f"mode=station\n"
                f"ip_address={self.ip}\n"
                f"address={self.mac}\n"
                f"wpa_state=COMPLETED\n"
            )

        if cmd.startswith("DISABLE_NETWORK ") or cmd.startswith("REMOVE_NETWORK "):
            return "OK\n"

        print(f"[mock-wpa] unknown command: '{cmd}'", flush=True)
        return "FAIL\n"

    # ------------------------------------------------------------------

    def _run(self):
        while self._running:
            try:
                data, addr = self._sock.recvfrom(4096)
            except OSError:
                break
            cmd = data.decode(errors="replace")
            response = self._handle(cmd, addr)
            if response:
                print(f"[mock-wpa] -> '{response.strip()}' to {addr}",
                      flush=True)
                self._send_to(addr, response)


# ======================================================================


def main():
    parser = argparse.ArgumentParser(description="Mock wpa_supplicant ctrl socket")
    parser.add_argument("--ctrl-path", default="/tmp/mock-wpa-ctrl",
                        help="Path for the Unix DGRAM socket (default: /tmp/mock-wpa-ctrl)")
    parser.add_argument("--ssid",     default="TestAP",       help="Fake AP SSID")
    parser.add_argument("--password", default="testpass",     help="Fake AP password")
    parser.add_argument("--ip",       default="192.168.1.100",help="Fake assigned IP")
    parser.add_argument("--mac",      default="02:00:00:00:00:01",
                        help="Fake NIC MAC address")
    parser.add_argument("--scan-delay",    type=float, default=0.1,
                        help="Seconds before SCAN-RESULTS event (default 0.1)")
    parser.add_argument("--connect-delay", type=float, default=0.3,
                        help="Seconds before CONNECTED event (default 0.3)")
    args = parser.parse_args()

    daemon = MockWpaSupplicant(
        ctrl_path=args.ctrl_path,
        ssid=args.ssid,
        password=args.password,
        ip=args.ip,
        mac=args.mac,
        scan_delay=args.scan_delay,
        connect_delay=args.connect_delay,
    )

    def _sig(signum, frame):
        print("\n[mock-wpa] signal received, shutting down …", flush=True)
        daemon.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _sig)
    signal.signal(signal.SIGTERM, _sig)

    daemon.start()
    # Block main thread
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
