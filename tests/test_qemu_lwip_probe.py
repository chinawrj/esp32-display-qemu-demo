"""NEXT-004 — lwIP TCP socket proof over QEMU virtual Wi-Fi.

Validates the full data-plane chain:
    firmware lwIP (lwip_probe.c)
        → QEMU esp_wifi DMA registers (0x3ff75000)
            → QEMU device (hw/net/esp_wifi.c)
                → Unix socket (ESP_WIFI_PKT_SOCKET)
                    → wifi_packet_relay.py (SLIRP NAT)
                        → 127.0.0.1:LWIP_PORT (echo_server.py)
                            → response: "PONG"

Acceptance criteria (NEXT-004):
    serial output contains BOTH "got ip:" AND "lwip probe ok:"

Non-runtime tests (fast, always run) validate source structure.
Runtime tests require the QEMU binary and built flash images.
"""
from __future__ import annotations

import os
import pathlib
import socket
import subprocess
import sys
import threading
import time

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
QEMU_BIN = PROJECT_ROOT / "tools" / "qemu-src" / "build" / "qemu-system-xtensa"
FLASH_BIN = PROJECT_ROOT / "build" / "qemu_flash.bin"
EFUSE_BIN = PROJECT_ROOT / "build" / "qemu_efuse.bin"

_MOCK_SOCKET   = "/tmp/mock-wpa-lwip-probe"
_PKT_SOCKET    = "/tmp/pkt-relay-lwip-probe"
_MOCK_IP       = "10.0.2.15"
_MOCK_SSID     = "QEMU_TEST"
_LWIP_PORT     = int(os.environ.get("LWIP_PROBE_PORT", "9988"))

# Day-33: QEMU ESP32 emulation runs ~18x slower than real-time.
# LVGL benchmark + WiFi connect + TCP probe need ~260 wall-seconds.
_BOOT_TIMEOUT_S = 360


# ---------------------------------------------------------------------------
# Skip helpers
# ---------------------------------------------------------------------------

def _has_qemu() -> bool:
    return QEMU_BIN.is_file() and os.access(str(QEMU_BIN), os.X_OK)


def _has_flash_images() -> bool:
    return FLASH_BIN.is_file() and EFUSE_BIN.is_file()


def _qemu_has_wifi_device() -> bool:
    if not _has_qemu():
        return False
    result = subprocess.run(
        ["strings", str(QEMU_BIN)],
        capture_output=True, text=True, timeout=10,
    )
    return "net.esp.wifi" in result.stdout


_REASON_NO_QEMU    = "QEMU binary not found (run bash tools/build-qemu.sh first)"
_REASON_NO_IMAGES  = "Flash images not found (run idf.py build first)"
_REASON_NO_WIFI_DEV = (
    "QEMU binary lacks esp_wifi device "
    "(run bash tools/build-qemu.sh after implementing esp_wifi.c)"
)


# ---------------------------------------------------------------------------
# Source / scaffold tests (fast, no runtime)
# ---------------------------------------------------------------------------

class TestLwipProbeSource:
    """Verify NEXT-004 source files are in place and correctly structured."""

    def test_lwip_probe_c_exists(self):
        """main/lwip_probe.c must be present."""
        assert (PROJECT_ROOT / "main" / "lwip_probe.c").is_file(), (
            "main/lwip_probe.c missing — run NEXT-004 scaffold"
        )

    def test_lwip_probe_h_exists(self):
        """main/include/lwip_probe.h must be present."""
        assert (PROJECT_ROOT / "main" / "include" / "lwip_probe.h").is_file(), (
            "main/include/lwip_probe.h missing"
        )

    def test_lwip_probe_c_has_ok_log(self):
        """main/lwip_probe.c must contain the 'lwip probe ok:' log line."""
        src = (PROJECT_ROOT / "main" / "lwip_probe.c").read_text()
        assert "lwip probe ok:" in src, (
            "main/lwip_probe.c does not log 'lwip probe ok:' — "
            "add ESP_LOGI(TAG, \"lwip probe ok: ...\") on successful connect"
        )

    def test_lwip_probe_c_uses_lwip_sockets(self):
        """main/lwip_probe.c must include lwip/sockets.h."""
        src = (PROJECT_ROOT / "main" / "lwip_probe.c").read_text()
        assert "lwip/sockets.h" in src, (
            "main/lwip_probe.c does not include lwip/sockets.h"
        )

    def test_kconfig_has_probe_options(self):
        """main/Kconfig.projbuild must define all three DEMO_LWIP_PROBE_* options."""
        kconfig = (PROJECT_ROOT / "main" / "Kconfig.projbuild").read_text()
        for key in ("DEMO_LWIP_PROBE_ENABLE", "DEMO_LWIP_PROBE_HOST", "DEMO_LWIP_PROBE_PORT"):
            assert key in kconfig, f"Kconfig.projbuild missing {key}"

    def test_main_cmake_includes_lwip_probe(self):
        """main/CMakeLists.txt must list lwip_probe.c as a source."""
        cmake = (PROJECT_ROOT / "main" / "CMakeLists.txt").read_text()
        assert "lwip_probe.c" in cmake, (
            "main/CMakeLists.txt does not include lwip_probe.c in SRCS"
        )

    def test_main_c_calls_lwip_probe_start(self):
        """main/main.c must call lwip_probe_start()."""
        main_c = (PROJECT_ROOT / "main" / "main.c").read_text()
        assert "lwip_probe_start" in main_c, (
            "main/main.c does not call lwip_probe_start() — "
            "add call after demo_wifi_start()"
        )

    def test_main_c_includes_lwip_probe_h(self):
        """main/main.c must include lwip_probe.h (possibly conditionally)."""
        main_c = (PROJECT_ROOT / "main" / "main.c").read_text()
        assert "lwip_probe.h" in main_c, (
            "main/main.c does not include lwip_probe.h"
        )

    def test_echo_server_script_exists(self):
        """tools/echo_server.py must be present."""
        assert (PROJECT_ROOT / "tools" / "echo_server.py").is_file(), (
            "tools/echo_server.py missing — needed by run-direct-demo.sh and pytest"
        )

    def test_run_direct_demo_starts_relay(self):
        """tools/run-direct-demo.sh must reference wifi_packet_relay.py."""
        script = (PROJECT_ROOT / "tools" / "run-direct-demo.sh").read_text()
        assert "wifi_packet_relay.py" in script, (
            "tools/run-direct-demo.sh does not start wifi_packet_relay.py"
        )
        assert "ESP_WIFI_PKT_SOCKET" in script, (
            "tools/run-direct-demo.sh does not export ESP_WIFI_PKT_SOCKET"
        )

    def test_run_direct_demo_starts_echo_server(self):
        """tools/run-direct-demo.sh must start echo_server.py."""
        script = (PROJECT_ROOT / "tools" / "run-direct-demo.sh").read_text()
        assert "echo_server.py" in script, (
            "tools/run-direct-demo.sh does not start echo_server.py"
        )


# ---------------------------------------------------------------------------
# Echo server smoke-test (no QEMU needed)
# ---------------------------------------------------------------------------

class TestEchoServer:
    """Verify tools/echo_server.py works correctly in isolation."""

    def test_echo_server_responds_pong(self):
        """echo_server.py must respond with 'PONG\\n' to any TCP connect."""
        port = _LWIP_PORT + 1000   # use offset to avoid collisions
        proc = subprocess.Popen(
            [sys.executable, str(PROJECT_ROOT / "tools" / "echo_server.py"), str(port)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            # Wait for the server to bind
            deadline = time.monotonic() + 5.0
            connected = False
            while time.monotonic() < deadline:
                try:
                    s = socket.create_connection(("127.0.0.1", port), timeout=0.5)
                    connected = True
                    break
                except OSError:
                    time.sleep(0.1)

            assert connected, f"echo_server.py did not bind on port {port} within 5 s"
            s.sendall(b"PING\n")
            response = s.recv(16)
            s.close()
            assert response == b"PONG\n", f"expected PONG\\n, got {response!r}"
        finally:
            proc.terminate()
            proc.wait(timeout=3)


# ---------------------------------------------------------------------------
# Runtime integration test (requires QEMU binary + built flash images)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _has_qemu(), reason=_REASON_NO_QEMU)
@pytest.mark.skipif(not _has_flash_images(), reason=_REASON_NO_IMAGES)
@pytest.mark.skipif(not _qemu_has_wifi_device(), reason=_REASON_NO_WIFI_DEV)
class TestLwipProbeRuntime:
    """End-to-end test: firmware lwIP probe over QEMU virtual Wi-Fi data plane.

    Setup:
    1. Start tools/echo_server.py on localhost:_LWIP_PORT
    2. Start tools/wifi_packet_relay.py (SLIRP NAT: 10.0.2.100 → 127.0.0.1)
    3. Start mock_wpa_supplicant (ctrl plane → got ip)
    4. Boot QEMU with main firmware
    5. Assert serial contains "got ip:" and "lwip probe ok:"
    """

    def _start_echo_server(self, port: int) -> subprocess.Popen:
        return subprocess.Popen(
            [sys.executable, str(PROJECT_ROOT / "tools" / "echo_server.py"), str(port)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def _start_pkt_relay(self, sock_path: str) -> subprocess.Popen:
        env = os.environ.copy()
        env["ESP_WIFI_PKT_SOCKET"] = sock_path
        return subprocess.Popen(
            [sys.executable, str(PROJECT_ROOT / "tools" / "wifi_packet_relay.py"), sock_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env,
        )

    def _start_mock_wpa(self, sock_path: str) -> subprocess.Popen:
        return subprocess.Popen(
            [
                sys.executable,
                str(PROJECT_ROOT / "tools" / "mock_wpa_supplicant.py"),
                "--ctrl-path", sock_path,
                "--ip", _MOCK_IP,
                "--ssid", _MOCK_SSID,
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )

    def _wait_for_socket(self, path: str, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if os.path.exists(path):
                return True
            time.sleep(0.1)
        return False

    def test_lwip_probe_ok_in_serial(self):
        """Firmware must print 'got ip:' and 'lwip probe ok:' within timeout.

        Both lines must appear, proving:
          - Control plane: mock_wpa_supplicant → got ip
          - Data plane:    lwIP TCP → wifi_packet_relay → echo_server → PONG
        """
        procs: list[subprocess.Popen] = []
        serial_output: list[str] = []

        for stale in (_MOCK_SOCKET, _PKT_SOCKET):
            if os.path.exists(stale):
                os.unlink(stale)

        try:
            # 1. Echo server
            echo_proc = self._start_echo_server(_LWIP_PORT)
            procs.append(echo_proc)
            # Quick bind check
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                try:
                    socket.create_connection(("127.0.0.1", _LWIP_PORT), timeout=0.3).close()
                    break
                except OSError:
                    time.sleep(0.1)

            # 2. Packet relay
            relay_proc = self._start_pkt_relay(_PKT_SOCKET)
            procs.append(relay_proc)
            assert self._wait_for_socket(_PKT_SOCKET), (
                f"wifi_packet_relay socket did not appear at {_PKT_SOCKET}"
            )

            # 3. mock wpa_supplicant
            mock_proc = self._start_mock_wpa(_MOCK_SOCKET)
            procs.append(mock_proc)
            assert self._wait_for_socket(_MOCK_SOCKET), (
                f"mock_wpa_supplicant socket did not appear at {_MOCK_SOCKET}"
            )

            # 4. Boot QEMU
            qemu_env = os.environ.copy()
            qemu_env["ESP_WIFI_CTRL_SOCKET"] = _MOCK_SOCKET
            qemu_env["ESP_WIFI_PKT_SOCKET"]  = _PKT_SOCKET
            qemu_env.pop("ESP_RGB_WS_PORT", None)
            qemu_env["ESP_RGB_WS_DISABLE"] = "1"

            qemu_proc = subprocess.Popen(
                [
                    str(QEMU_BIN),
                    "-machine", "esp32",
                    "-drive", f"file={FLASH_BIN},if=mtd,format=raw",
                    "-drive", f"file={EFUSE_BIN},if=none,format=raw,id=efuse",
                    "-global", "driver=nvram.esp32.efuse,property=drive,value=efuse",
                    "-global", "driver=timer.esp32.timg,property=wdt_disable,value=true",
                    # Day-34: -serial stdio + stdin=DEVNULL kills serial output.
                    # Use -nographic so guest serial always goes to stdout.
                    "-nographic",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=qemu_env,
                stdin=subprocess.DEVNULL,
            )
            procs.append(qemu_proc)

            # 5. Collect serial output until both markers appear or timeout
            got_ip     = False
            probe_ok   = False
            deadline   = time.monotonic() + _BOOT_TIMEOUT_S

            assert qemu_proc.stdout is not None
            while time.monotonic() < deadline:
                line = qemu_proc.stdout.readline()
                if not line:
                    if qemu_proc.poll() is not None:
                        break
                    continue
                decoded = line.decode("utf-8", errors="replace").rstrip()
                serial_output.append(decoded)
                if "got ip:" in decoded:
                    got_ip = True
                if "lwip probe ok:" in decoded:
                    probe_ok = True
                if got_ip and probe_ok:
                    break

            excerpt = "\n".join(serial_output[-40:])
            assert got_ip, (
                f"'got ip:' not found in serial output within {_BOOT_TIMEOUT_S}s.\n"
                f"Last lines:\n{excerpt}"
            )
            assert probe_ok, (
                f"'lwip probe ok:' not found in serial output within {_BOOT_TIMEOUT_S}s.\n"
                f"(got_ip={got_ip})\n"
                f"Last lines:\n{excerpt}"
            )

        finally:
            for p in reversed(procs):
                try:
                    p.terminate()
                    p.wait(timeout=5)
                except Exception:
                    pass
