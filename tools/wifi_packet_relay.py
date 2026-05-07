#!/usr/bin/env python3
"""
wifi_packet_relay.py — QEMU virtual Wi-Fi packet relay daemon.

Listens on a Unix STREAM socket (path from ESP_WIFI_PKT_SOCKET env var or
the first CLI argument).  QEMU's virtual Wi-Fi device connects to this socket
and exchanges raw Ethernet frames with a 4-byte big-endian length prefix.

Supported:
  * ARP (Ethertype 0x0806) — responds to Who-Has queries for gateway
  * IPv4/UDP (Protocol 17) — forwards to real destination and relays response
  * IPv4/TCP (Protocol 6)  — proxies via full asyncio stream relay
  * ICMP echo (Protocol 1) — relayed via raw socket if permitted; silently
                             dropped if not (most OS need root for raw ICMP).

Networking model (SLIRP-like, no root required):
  * Virtual gateway IP:  10.0.2.2  (GATEWAY_IP)
  * Virtual gateway MAC: 52:54:00:12:34:56 (GATEWAY_MAC)
  * Firmware IP:         dynamically detected from ARP sender field
  * DNS:                 forwarded to 8.8.8.8:53 by default
  * Host mapping:        10.0.2.100 → 127.0.0.1 (for local test servers)

Usage:
  python3 tools/wifi_packet_relay.py [socket_path]

  If socket_path is omitted, uses $ESP_WIFI_PKT_SOCKET.

Protocol:
  [4-byte BE length][raw Ethernet frame bytes]
  Both TX (QEMU→relay) and RX (relay→QEMU) use this framing.
"""

import asyncio
import os
import socket
import struct
import sys
import logging
import threading
import ipaddress
from typing import Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GATEWAY_IP  = "10.0.2.2"
GATEWAY_MAC = bytes.fromhex("525400123456")   # 52:54:00:12:34:56
GUEST_MAC   = bytes(6)                         # detected from first ARP

# IP addresses the relay handles directly (maps to 127.0.0.1)
LOCAL_HOST_MAP: Dict[str, str] = {
    "10.0.2.100": "127.0.0.1",
    "10.0.2.2":   "127.0.0.1",   # any TCP to gateway goes to localhost
}

DNS_SERVER = ("8.8.8.8", 53)

# Maximum payload size
MAX_FRAME = 1516

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [RELAY] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("relay")

# ---------------------------------------------------------------------------
# Ethernet / IP / ARP packet helpers (stdlib only, no scapy)
# ---------------------------------------------------------------------------

ETH_HDR_SIZE = 14
ARP_SIZE     = 28  # ARP for IPv4/Ethernet

ETHERTYPE_ARP  = 0x0806
ETHERTYPE_IPV4 = 0x0800

IP_PROTO_ICMP = 1
IP_PROTO_TCP  = 6
IP_PROTO_UDP  = 17


def parse_eth(frame: bytes) -> Optional[Tuple]:
    """Return (dst_mac, src_mac, ethertype, payload) or None."""
    if len(frame) < ETH_HDR_SIZE:
        return None
    dst = frame[0:6]
    src = frame[6:12]
    ethertype = struct.unpack("!H", frame[12:14])[0]
    payload = frame[14:]
    return dst, src, ethertype, payload


def build_eth(dst: bytes, src: bytes, ethertype: int, payload: bytes) -> bytes:
    return dst + src + struct.pack("!H", ethertype) + payload


def parse_arp(payload: bytes) -> Optional[dict]:
    """Parse IPv4/Ethernet ARP, return dict or None."""
    if len(payload) < ARP_SIZE:
        return None
    hw_type, proto, hw_size, proto_size, op = struct.unpack("!HHBBH", payload[:8])
    if hw_type != 1 or proto != 0x0800 or hw_size != 6 or proto_size != 4:
        return None
    sender_mac = payload[8:14]
    sender_ip  = socket.inet_ntoa(payload[14:18])
    target_mac = payload[18:24]
    target_ip  = socket.inet_ntoa(payload[24:28])
    return {
        "op": op,  # 1=request, 2=reply
        "sender_mac": sender_mac,
        "sender_ip":  sender_ip,
        "target_mac": target_mac,
        "target_ip":  target_ip,
    }


def build_arp_reply(src_mac: bytes, src_ip: str,
                    dst_mac: bytes, dst_ip: str) -> bytes:
    """Build an ARP reply (op=2)."""
    payload = struct.pack("!HHBBH", 1, 0x0800, 6, 4, 2)  # hw/proto/sizes/op
    payload += src_mac + socket.inet_aton(src_ip)
    payload += dst_mac + socket.inet_aton(dst_ip)
    return build_eth(dst_mac, src_mac, ETHERTYPE_ARP, payload)


def ip_checksum(header: bytes) -> int:
    if len(header) % 2:
        header += b'\x00'
    total = 0
    for i in range(0, len(header), 2):
        word = (header[i] << 8) + header[i + 1]
        total += word
    while total >> 16:
        total = (total & 0xffff) + (total >> 16)
    return ~total & 0xffff


def parse_ipv4(payload: bytes) -> Optional[dict]:
    """Parse IPv4 header, return dict or None."""
    if len(payload) < 20:
        return None
    ihl = (payload[0] & 0x0f) * 4
    if len(payload) < ihl:
        return None
    ttl, proto = payload[8], payload[9]
    src_ip = socket.inet_ntoa(payload[12:16])
    dst_ip = socket.inet_ntoa(payload[16:20])
    total_len = struct.unpack("!H", payload[2:4])[0]
    data = payload[ihl:total_len] if total_len <= len(payload) else payload[ihl:]
    return {
        "ihl": ihl, "ttl": ttl, "proto": proto,
        "src_ip": src_ip, "dst_ip": dst_ip,
        "data": data, "raw": payload[:total_len],
    }


def build_ipv4(src_ip: str, dst_ip: str, proto: int, payload: bytes) -> bytes:
    total_len = 20 + len(payload)
    hdr = struct.pack("!BBHHHBBH4s4s",
                      0x45, 0, total_len, 0, 0,
                      64, proto, 0,
                      socket.inet_aton(src_ip),
                      socket.inet_aton(dst_ip))
    csum = ip_checksum(hdr)
    hdr = hdr[:10] + struct.pack("!H", csum) + hdr[12:]
    return hdr + payload


def parse_udp(data: bytes) -> Optional[dict]:
    if len(data) < 8:
        return None
    src_port, dst_port, length, _ = struct.unpack("!HHHH", data[:8])
    return {"src_port": src_port, "dst_port": dst_port,
            "payload": data[8:length]}


def build_udp(src_port: int, dst_port: int, payload: bytes) -> bytes:
    length = 8 + len(payload)
    return struct.pack("!HHHH", src_port, dst_port, length, 0) + payload


def parse_tcp(data: bytes) -> Optional[dict]:
    if len(data) < 20:
        return None
    src_port, dst_port = struct.unpack("!HH", data[0:4])
    seq, ack_seq = struct.unpack("!II", data[4:12])
    data_offset = (data[12] >> 4) * 4
    flags = data[13]
    window = struct.unpack("!H", data[14:16])[0]
    payload = data[data_offset:]
    return {
        "src_port": src_port, "dst_port": dst_port,
        "seq": seq, "ack_seq": ack_seq,
        "data_offset": data_offset, "flags": flags,
        "window": window, "payload": payload,
    }


def udp_checksum(src_ip: str, dst_ip: str, udp_seg: bytes) -> int:
    """Compute UDP checksum with pseudo-header."""
    pseudo = (socket.inet_aton(src_ip) + socket.inet_aton(dst_ip) +
              struct.pack("!BBH", 0, IP_PROTO_UDP, len(udp_seg)))
    data = pseudo + udp_seg
    if len(data) % 2:
        data += b'\x00'
    total = 0
    for i in range(0, len(data), 2):
        total += (data[i] << 8) + data[i + 1]
    while total >> 16:
        total = (total & 0xffff) + (total >> 16)
    result = ~total & 0xffff
    return result if result != 0 else 0xffff


# ---------------------------------------------------------------------------
# Relay state
# ---------------------------------------------------------------------------

class RelayState:
    """Shared mutable state for the relay session."""
    def __init__(self):
        self.guest_mac: bytes = bytes(6)
        self.guest_ip: str = ""
        self.send_lock = asyncio.Lock()
        self.tcp_conns: Dict[Tuple, "TCPProxyConn"] = {}  # (src_ip,src_port,dst_ip,dst_port)


# ---------------------------------------------------------------------------
# TCP proxy connection
# ---------------------------------------------------------------------------

class TCPProxyConn:
    """Manages one TCP connection between firmware and a real server."""

    FLAG_FIN = 0x01
    FLAG_SYN = 0x02
    FLAG_RST = 0x04
    FLAG_ACK = 0x10
    FLAG_PSH = 0x08

    def __init__(self, state: RelayState, writer_fn,
                 fw_ip: str, fw_port: int,
                 srv_ip: str, srv_port: int):
        self.state = state
        self.writer_fn = writer_fn  # coroutine: send frame to QEMU
        self.fw_ip    = fw_ip
        self.fw_port  = fw_port
        self.srv_ip   = srv_ip
        self.srv_port = srv_port
        self.srv_reader: Optional[asyncio.StreamReader] = None
        self.srv_writer: Optional[asyncio.StreamWriter] = None
        self.fw_seq   = 0        # seq for frames sent TO firmware
        self.fw_ack   = 0        # last ack received FROM firmware (= next fw_seq)
        self.srv_seq  = 0        # initial seq sent to server (arbitrary)
        self.connected = False
        self.task: Optional[asyncio.Task] = None

    def build_tcp_seg(self, flags: int, payload: bytes, seq: int, ack: int) -> bytes:
        data_offset = 5  # 20 bytes, no options
        seg = struct.pack("!HHIIBBHHH",
                          self.srv_port, self.fw_port,
                          seq, ack,
                          (data_offset << 4), flags, 65535, 0, 0)
        return seg + payload

    def tcp_checksum(self, src_ip: str, dst_ip: str, tcp_seg: bytes) -> int:
        pseudo = (socket.inet_aton(src_ip) + socket.inet_aton(dst_ip) +
                  struct.pack("!BBH", 0, IP_PROTO_TCP, len(tcp_seg)))
        data = pseudo + tcp_seg
        if len(data) % 2:
            data += b'\x00'
        total = 0
        for i in range(0, len(data), 2):
            total += (data[i] << 8) + data[i + 1]
        while total >> 16:
            total = (total & 0xffff) + (total >> 16)
        result = ~total & 0xffff
        return result if result != 0 else 0xffff

    def inject_csum(self, tcp_seg: bytes, src_ip: str, dst_ip: str) -> bytes:
        csum = self.tcp_checksum(src_ip, dst_ip, tcp_seg)
        return tcp_seg[:16] + struct.pack("!H", csum) + tcp_seg[18:]

    async def send_tcp_to_fw(self, flags: int, payload: bytes):
        """Send a TCP segment from server-side (srv_ip) to firmware."""
        seg = self.build_tcp_seg(flags, payload, self.fw_seq, self.fw_ack)
        seg = self.inject_csum(seg, self.srv_ip, self.fw_ip)
        ip_pkt = build_ipv4(self.srv_ip, self.fw_ip, IP_PROTO_TCP, seg)
        eth_frame = build_eth(self.state.guest_mac, GATEWAY_MAC,
                              ETHERTYPE_IPV4, ip_pkt)
        await self.writer_fn(eth_frame)
        self.fw_seq += len(payload)
        if flags & (self.FLAG_SYN | self.FLAG_FIN):
            self.fw_seq += 1

    async def connect(self):
        """Connect to the real server and send SYN-ACK to firmware."""
        real_ip = LOCAL_HOST_MAP.get(self.srv_ip, self.srv_ip)
        log.info(f"TCP connect {self.fw_ip}:{self.fw_port} → "
                 f"{self.srv_ip}:{self.srv_port} (real={real_ip}:{self.srv_port})")
        try:
            self.srv_reader, self.srv_writer = await asyncio.open_connection(
                real_ip, self.srv_port)
        except Exception as e:
            log.warning(f"TCP connect failed: {e}")
            await self.send_tcp_to_fw(self.FLAG_RST | self.FLAG_ACK, b"")
            return

        self.connected = True
        await self.send_tcp_to_fw(self.FLAG_SYN | self.FLAG_ACK, b"")
        # Start forwarding server→firmware
        self.task = asyncio.ensure_future(self._srv_to_fw())

    async def _srv_to_fw(self):
        """Background task: forward data from server to firmware."""
        try:
            while True:
                data = await self.srv_reader.read(1460)
                if not data:
                    # Server closed connection
                    await self.send_tcp_to_fw(self.FLAG_FIN | self.FLAG_ACK, b"")
                    break
                await self.send_tcp_to_fw(self.FLAG_PSH | self.FLAG_ACK, data)
        except Exception as e:
            log.debug(f"srv→fw task ended: {e}")
        finally:
            if self.srv_writer:
                try:
                    self.srv_writer.close()
                except Exception:
                    pass

    def handle_fw_tcp(self, tcp: dict):
        """Handle a TCP segment from firmware (called from main loop)."""
        flags = tcp["flags"]
        payload = tcp["payload"]
        self.fw_ack = tcp["seq"] + len(payload)
        if flags & self.FLAG_SYN:
            self.fw_ack = tcp["seq"] + 1

        # Queue connection or data forwarding
        loop = asyncio.get_event_loop()

        if flags & self.FLAG_SYN and not self.connected:
            loop.create_task(self.connect())
            return

        if payload and self.connected and self.srv_writer:
            try:
                self.srv_writer.write(payload)
                loop.create_task(self.srv_writer.drain())
            except Exception as e:
                log.warning(f"forward to server failed: {e}")

        if flags & self.FLAG_FIN:
            if self.srv_writer:
                try:
                    self.srv_writer.close()
                except Exception:
                    pass

    def close(self):
        if self.task:
            self.task.cancel()
        if self.srv_writer:
            try:
                self.srv_writer.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Main relay session handler
# ---------------------------------------------------------------------------

async def handle_qemu_session(reader: asyncio.StreamReader,
                              writer: asyncio.StreamWriter,
                              sock_path: str):
    """Handle one QEMU connection."""
    log.info("QEMU connected")
    state = RelayState()
    send_lock = asyncio.Lock()

    async def send_frame(frame: bytes):
        """Send a frame back to QEMU (length-prefixed)."""
        if len(frame) > MAX_FRAME:
            return
        hdr = struct.pack("!I", len(frame))
        async with send_lock:
            writer.write(hdr + frame)
            await writer.drain()

    # Frame receive state machine
    hdr_buf = bytearray()
    data_buf = bytearray()
    expected = 0

    try:
        while True:
            # Read until we have a complete frame
            if len(hdr_buf) < 4:
                chunk = await reader.read(4 - len(hdr_buf))
                if not chunk:
                    break
                hdr_buf.extend(chunk)
                continue

            if expected == 0:
                expected = struct.unpack("!I", bytes(hdr_buf[:4]))[0]
                if expected == 0 or expected > MAX_FRAME:
                    log.warning(f"Bad frame length from QEMU: {expected}")
                    break
                data_buf = bytearray()

            remaining = expected - len(data_buf)
            chunk = await reader.read(remaining)
            if not chunk:
                break
            data_buf.extend(chunk)

            if len(data_buf) < expected:
                continue

            # Complete frame received
            frame = bytes(data_buf)
            hdr_buf = bytearray()
            expected = 0

            await process_frame(frame, state, send_frame)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        log.error(f"Session error: {e}")
    finally:
        log.info("QEMU disconnected")
        for conn in list(state.tcp_conns.values()):
            conn.close()
        writer.close()


async def process_frame(frame: bytes, state: RelayState, send_fn):
    """Dispatch an Ethernet frame received from QEMU firmware."""
    eth = parse_eth(frame)
    if eth is None:
        return
    dst_mac, src_mac, ethertype, payload = eth

    # Remember guest MAC
    if src_mac != bytes(6) and src_mac != GATEWAY_MAC:
        state.guest_mac = src_mac

    if ethertype == ETHERTYPE_ARP:
        await handle_arp(payload, src_mac, send_fn)

    elif ethertype == ETHERTYPE_IPV4:
        ip = parse_ipv4(payload)
        if ip is None:
            return
        state.guest_ip = ip["src_ip"]
        await handle_ipv4(ip, src_mac, state, send_fn)


async def handle_arp(payload: bytes, src_mac: bytes, send_fn):
    """Handle ARP Who-Has — reply for gateway IP and any locally-mapped IP."""
    arp = parse_arp(payload)
    if arp is None:
        return
    log.debug(f"ARP op={arp['op']} who-has {arp['target_ip']} tell {arp['sender_ip']}")

    if arp["op"] == 1:  # ARP request
        target = arp["target_ip"]
        if target == GATEWAY_IP or target in LOCAL_HOST_MAP:
            reply = build_arp_reply(GATEWAY_MAC, target,
                                    arp["sender_mac"], arp["sender_ip"])
            await send_fn(reply)
            log.debug(f"ARP reply: {target} is at {GATEWAY_MAC.hex(':')}")


async def handle_ipv4(ip: dict, src_mac: bytes, state: RelayState, send_fn):
    """Route IPv4 packets."""
    if ip["proto"] == IP_PROTO_UDP:
        await handle_udp(ip, state, send_fn)
    elif ip["proto"] == IP_PROTO_TCP:
        await handle_tcp(ip, state, send_fn)
    # ICMP and others: silently dropped


async def handle_udp(ip: dict, state: RelayState, send_fn):
    """Forward UDP packet to real destination and relay response."""
    udp = parse_udp(ip["data"])
    if udp is None:
        return

    real_dst_ip = LOCAL_HOST_MAP.get(ip["dst_ip"], ip["dst_ip"])

    log.debug(f"UDP {ip['src_ip']}:{udp['src_port']} → "
              f"{ip['dst_ip']}:{udp['dst_port']} ({len(udp['payload'])} bytes)")

    try:
        loop = asyncio.get_event_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)

        await loop.sock_sendto(sock, udp["payload"],
                               (real_dst_ip, udp["dst_port"]))

        try:
            resp_data, _ = await asyncio.wait_for(
                loop.sock_recvfrom(sock, 65535), timeout=2.0)
        except asyncio.TimeoutError:
            log.debug("UDP response timeout")
            return
        finally:
            sock.close()

        # Build response: from dst_ip:dst_port → src_ip:src_port
        resp_udp = build_udp(udp["dst_port"], udp["src_port"], resp_data)
        # Fix checksum
        csum = udp_checksum(ip["dst_ip"], ip["src_ip"], resp_udp)
        resp_udp = resp_udp[:6] + struct.pack("!H", csum) + resp_udp[8:]
        resp_ip  = build_ipv4(ip["dst_ip"], ip["src_ip"], IP_PROTO_UDP, resp_udp)
        resp_eth = build_eth(state.guest_mac, GATEWAY_MAC,
                             ETHERTYPE_IPV4, resp_ip)
        await send_fn(resp_eth)
        log.debug(f"UDP response {len(resp_data)} bytes")

    except Exception as e:
        log.warning(f"UDP relay error: {e}")


async def handle_tcp(ip: dict, state: RelayState, send_fn):
    """Handle TCP: create or lookup a TCPProxyConn."""
    tcp = parse_tcp(ip["data"])
    if tcp is None:
        return

    key = (ip["src_ip"], tcp["src_port"], ip["dst_ip"], tcp["dst_port"])

    conn = state.tcp_conns.get(key)
    if conn is None:
        conn = TCPProxyConn(state, send_fn,
                            ip["src_ip"], tcp["src_port"],
                            ip["dst_ip"],  tcp["dst_port"])
        state.tcp_conns[key] = conn

    conn.handle_fw_tcp(tcp)

    # Cleanup closed connections
    to_del = [k for k, c in state.tcp_conns.items()
              if not c.connected and c.fw_seq > 0 and
              (tcp["flags"] & TCPProxyConn.FLAG_RST)]
    for k in to_del:
        state.tcp_conns.pop(k, None)


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

async def run_server(sock_path: str):
    """Listen on Unix socket and handle QEMU connections."""
    if os.path.exists(sock_path):
        os.unlink(sock_path)

    server = await asyncio.start_unix_server(
        lambda r, w: handle_qemu_session(r, w, sock_path),
        path=sock_path,
    )
    log.info(f"Listening on {sock_path}")
    async with server:
        await server.serve_forever()


def main():
    import argparse as _argparse
    parser = _argparse.ArgumentParser(
        description="QEMU ESP32 Wi-Fi packet relay daemon",
        formatter_class=_argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Mock mode (default):\n"
            "  wifi_packet_relay.py /tmp/pkt-relay\n\n"
            "Real-WiFi passthrough mode:\n"
            "  wifi_packet_relay.py /tmp/pkt-relay --gateway-ip 192.168.1.1 --no-local-map\n"
            "  (point ESP_WIFI_CTRL_SOCKET at the real wpa_supplicant socket)"
        ),
    )
    parser.add_argument(
        "socket_path", nargs="?", default=None,
        help="Unix socket path (overrides $ESP_WIFI_PKT_SOCKET)",
    )
    parser.add_argument(
        "--gateway-ip", metavar="IP", default=None,
        help=(
            "Override gateway IP the relay responds to for ARP. "
            "Default: 10.0.2.2 (SLIRP mock mode). "
            "Set to your real router IP for real-WiFi passthrough mode."
        ),
    )
    parser.add_argument(
        "--no-local-map", action="store_true",
        help=(
            "Disable local-host IP mapping (10.0.2.x → 127.0.0.1). "
            "Required for real-WiFi passthrough mode so packets are "
            "forwarded to real destinations instead of localhost."
        ),
    )
    args = parser.parse_args()

    sock_path = args.socket_path or os.environ.get("ESP_WIFI_PKT_SOCKET", "")
    if not sock_path:
        parser.error("socket_path argument or $ESP_WIFI_PKT_SOCKET required")

    # Apply real-WiFi overrides before the event loop starts
    global GATEWAY_IP, LOCAL_HOST_MAP
    if args.gateway_ip:
        GATEWAY_IP = args.gateway_ip
        log.info(f"Gateway IP overridden to {GATEWAY_IP}")
    if args.no_local_map:
        LOCAL_HOST_MAP = {}
        log.info("Local-host IP mapping disabled (real-WiFi passthrough mode)")

    log.info(f"Starting Wi-Fi packet relay on {sock_path}")
    asyncio.run(run_server(sock_path))


if __name__ == "__main__":
    main()
