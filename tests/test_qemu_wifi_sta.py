"""NEXT-002 — QEMU virtual Wi-Fi STA integration tests (Day 8 scaffold).

Tests validate the full chain:
    firmware (esp_wifi_qemu component)
        → QEMU esp_wifi device (MMIO)
            → host wpa_supplicant ctrl socket
                → host Wi-Fi NIC → AP → DHCP → got ip

Skips are aggressively used so the test suite never fails on CI
environments that lack Wi-Fi hardware or wpa_supplicant.

Day 8 status: skeleton only.  Tests are not expected to pass until
the QEMU device and component are fully implemented (Days 9–13).
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import time
from typing import Generator

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
QEMU_BIN = PROJECT_ROOT / "tools" / "qemu-src" / "build" / "qemu-system-xtensa"
FLASH_BIN = PROJECT_ROOT / "build" / "qemu_flash.bin"
EFUSE_BIN = PROJECT_ROOT / "build" / "qemu_efuse.bin"
ESP_WIFI_C = (
    PROJECT_ROOT / "tools" / "qemu-src" / "hw" / "net" / "esp_wifi.c"
)
ESP_WIFI_H = (
    PROJECT_ROOT / "tools" / "qemu-src" / "include" / "hw" / "net" / "esp_wifi.h"
)

_WIFI_CTRL_SOCKET = os.environ.get(
    "WIFI_CTRL_SOCKET",
    "/var/run/wpa_supplicant/wlo1",
)
_BOOT_TIMEOUT_S = 30    # time to get ip after QEMU boot

# ---------------------------------------------------------------------------
# Skip helpers
# ---------------------------------------------------------------------------

def _has_qemu() -> bool:
    return QEMU_BIN.is_file() and os.access(str(QEMU_BIN), os.X_OK)


def _has_flash_images() -> bool:
    return FLASH_BIN.is_file() and EFUSE_BIN.is_file()


def _has_wpa_supplicant_ctrl() -> bool:
    """True only if wpa_supplicant is running and its ctrl socket exists."""
    try:
        return pathlib.Path(_WIFI_CTRL_SOCKET).exists()
    except PermissionError:
        # The socket exists but we lack stat permission (e.g. managed by
        # NetworkManager/root). Treat as available; wpa_cli will fail later
        # if the process actually can't communicate with it.
        return True


def _has_wpa_cli() -> bool:
    return shutil.which("wpa_cli") is not None


def _qemu_has_wifi_device() -> bool:
    """True if the QEMU binary was built with the esp_wifi device.

    SysBusDevices instantiated as machine children don't appear in
    '-device help'. We check the binary's string table for the QEMU
    type name 'net.esp.wifi' which is unconditionally embedded when
    the device is compiled in.
    """
    if not _has_qemu():
        return False
    result = subprocess.run(
        ["strings", str(QEMU_BIN)],
        capture_output=True, text=True, timeout=10,
    )
    return "net.esp.wifi" in result.stdout


# Shared skip condition for all integration tests
_REASON_NO_QEMU = "QEMU binary not found (run bash tools/build-qemu.sh first)"
_REASON_NO_IMAGES = "Flash images not found (run idf.py build first)"
_REASON_NO_CTRL = (
    f"wpa_supplicant ctrl socket not found at {_WIFI_CTRL_SOCKET}. "
    "Start wpa_supplicant or set WIFI_CTRL_SOCKET env var."
)
_REASON_NO_WIFI_DEV = (
    "QEMU binary lacks esp_wifi device (run bash tools/build-qemu.sh "
    "after implementing tools/qemu-src-patches/hw/net/esp_wifi.c)"
)


# ---------------------------------------------------------------------------
# Source / patch presence tests (no runtime, fast)
# ---------------------------------------------------------------------------


class TestSourceFiles:
    """Verify that required source files exist (Day 8 scaffold checks)."""

    def test_qemu_wifi_patch_file_exists(self):
        """esp_wifi.c patch file must be present in qemu-src-patches."""
        patch_path = (
            PROJECT_ROOT
            / "tools"
            / "qemu-src-patches"
            / "hw"
            / "net"
            / "esp_wifi.c"
        )
        assert patch_path.is_file(), (
            f"Missing QEMU device patch: {patch_path}. "
            "Create tools/qemu-src-patches/hw/net/esp_wifi.c (Day 9 task)."
        )

    def test_qemu_wifi_header_exists(self):
        """esp_wifi.h patch header must be present in qemu-src-patches."""
        header_path = (
            PROJECT_ROOT
            / "tools"
            / "qemu-src-patches"
            / "include"
            / "hw"
            / "net"
            / "esp_wifi.h"
        )
        assert header_path.is_file(), f"Missing QEMU device header: {header_path}"

    def test_qemu_binary_contains_wifi_type(self):
        """QEMU binary must contain the 'net.esp.wifi' type string."""
        if not _has_qemu():
            pytest.skip(_REASON_NO_QEMU)
        result = subprocess.run(
            ["strings", str(QEMU_BIN)],
            capture_output=True, text=True, timeout=10,
        )
        assert "net.esp.wifi" in result.stdout, (
            "QEMU binary does not contain 'net.esp.wifi'. "
            "Run: bash tools/build-qemu.sh"
        )

    def test_component_cmake_exists(self):
        """esp_wifi_qemu CMakeLists.txt must be present."""
        cmake = PROJECT_ROOT / "components" / "esp_wifi_qemu" / "CMakeLists.txt"
        assert cmake.is_file(), f"Missing: {cmake}"

    def test_component_kconfig_exists(self):
        """esp_wifi_qemu Kconfig.projbuild must define CONFIG_ESP_WIFI_QEMU.

        In Kconfig syntax the CONFIG_ prefix is implicit; we check for the
        bare symbol name 'ESP_WIFI_QEMU' (which becomes CONFIG_ESP_WIFI_QEMU
        in generated sdkconfig / C headers).
        """
        kconfig = (
            PROJECT_ROOT / "components" / "esp_wifi_qemu" / "Kconfig.projbuild"
        )
        assert kconfig.is_file(), f"Missing: {kconfig}"
        text = kconfig.read_text()
        # Kconfig uses bare symbol names; CONFIG_ prefix is added by the build
        assert "ESP_WIFI_QEMU" in text, (
            "Kconfig.projbuild does not define ESP_WIFI_QEMU symbol"
        )

    def test_shim_source_exists(self):
        """esp_wifi_shim.c must be present."""
        shim = (
            PROJECT_ROOT / "components" / "esp_wifi_qemu" / "esp_wifi_shim.c"
        )
        assert shim.is_file(), f"Missing: {shim}"

    def test_shim_guards_config_esp_wifi_qemu(self):
        """esp_wifi_shim.c must compile only when CONFIG_ESP_WIFI_QEMU=y."""
        shim = (
            PROJECT_ROOT / "components" / "esp_wifi_qemu" / "esp_wifi_shim.c"
        )
        text = shim.read_text()
        assert "#if CONFIG_ESP_WIFI_QEMU" in text, (
            "esp_wifi_shim.c must be wrapped in #if CONFIG_ESP_WIFI_QEMU"
        )

    def test_protocol_doc_exists(self):
        """docs/qemu-wifi.md must be present."""
        doc = PROJECT_ROOT / "docs" / "qemu-wifi.md"
        assert doc.is_file(), f"Missing protocol spec: {doc}"


# ---------------------------------------------------------------------------
# QEMU device integration tests (require runtime environment)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _has_qemu(), reason=_REASON_NO_QEMU)
@pytest.mark.skipif(not _has_flash_images(), reason=_REASON_NO_IMAGES)
class TestQemuWifiDevice:
    """Tests that require a running QEMU with the esp_wifi device."""

    @pytest.mark.skipif(not _qemu_has_wifi_device(), reason=_REASON_NO_WIFI_DEV)
    def test_qemu_enumerates_wifi_device(self):
        """QEMU binary string table must contain 'net.esp.wifi' type name.

        SysBusDevices instantiated as machine children are not listed in
        '-device help'; we use 'strings' to verify the type is compiled in.
        """
        result = subprocess.run(
            ["strings", str(QEMU_BIN)],
            capture_output=True, text=True, timeout=10,
        )
        assert "net.esp.wifi" in result.stdout, (
            "esp_wifi device type 'net.esp.wifi' not found in QEMU binary. "
            f"Run bash tools/build-qemu.sh. Binary: {QEMU_BIN}"
        )

    @pytest.mark.skipif(not _has_wpa_supplicant_ctrl(), reason=_REASON_NO_CTRL)
    @pytest.mark.skipif(not _qemu_has_wifi_device(), reason=_REASON_NO_WIFI_DEV)
    def test_qemu_wifi_sta_got_ip(
        self, wifi_ssid: str, wifi_password: str
    ):
        """QEMU boots, connects to Wi-Fi, and serial log shows 'got ip:'.

        Requires pytest fixtures wifi_ssid and wifi_password to be provided
        via environment variables WIFI_SSID and WIFI_PASSWORD.
        """
        pytest.skip(
            "Full end-to-end test deferred to Day 13 "
            "(QEMU device + component not yet implemented)"
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def wifi_ssid() -> str:
    ssid = os.environ.get("WIFI_SSID", "")
    if not ssid:
        pytest.skip("WIFI_SSID env var not set")
    return ssid


@pytest.fixture
def wifi_password() -> str:
    return os.environ.get("WIFI_PASSWORD", "")


# ---------------------------------------------------------------------------
# Mock wpa_supplicant unit tests (no real hardware needed)
# ---------------------------------------------------------------------------

MOCK_CTRL_PATH = "/tmp/mock-wpa-ctrl-test"
MOCK_CLIENT_PATH = "/tmp/mock-wpa-ctrl-test-client"
MOCK_IP = "192.168.99.1"
MOCK_SSID = "MockAP"


@pytest.fixture
def mock_wpa():
    """Start a mock wpa_supplicant daemon, yield, then stop it."""
    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    from mock_wpa_supplicant import MockWpaSupplicant  # type: ignore

    daemon = MockWpaSupplicant(
        ctrl_path=MOCK_CTRL_PATH,
        ssid=MOCK_SSID,
        ip=MOCK_IP,
        scan_delay=0.05,
        connect_delay=0.1,
    )
    daemon.start()
    yield daemon
    daemon.stop()
    for p in (MOCK_CTRL_PATH, MOCK_CLIENT_PATH):
        try:
            os.unlink(p)
        except OSError:
            pass


def _client_socket() -> socket.socket:
    """Create and bind a Unix DGRAM client socket."""
    import socket as _s
    sock = _s.socket(_s.AF_UNIX, _s.SOCK_DGRAM)
    sock.settimeout(3)
    try:
        os.unlink(MOCK_CLIENT_PATH)
    except OSError:
        pass
    sock.bind(MOCK_CLIENT_PATH)
    return sock


# Import socket at module level so fixtures can use it
import socket


class TestMockWpaSupplicant:
    """Unit tests for the mock wpa_supplicant ctrl daemon (no QEMU needed)."""

    def test_mock_script_exists(self):
        """mock-wpa-supplicant.py must be present in tools/."""
        script = PROJECT_ROOT / "tools" / "mock-wpa-supplicant.py"
        assert script.is_file(), f"Missing: {script}"
        assert os.access(str(script), os.X_OK), f"Not executable: {script}"

    def test_mock_wpa_attach(self, mock_wpa):
        """ATTACH command must return OK."""
        sock = _client_socket()
        sock.connect(MOCK_CTRL_PATH)
        sock.send(b"ATTACH")
        resp = sock.recv(64)
        sock.close()
        assert resp.startswith(b"OK"), f"Expected OK, got: {resp!r}"

    def test_mock_wpa_scan_results(self, mock_wpa):
        """SCAN_RESULTS must return our configured fake SSID."""
        sock = _client_socket()
        sock.connect(MOCK_CTRL_PATH)
        sock.send(b"SCAN_RESULTS")
        resp = sock.recv(512).decode()
        sock.close()
        assert MOCK_SSID in resp, (
            f"Expected SSID '{MOCK_SSID}' in SCAN_RESULTS, got: {resp!r}"
        )

    def test_mock_wpa_add_network(self, mock_wpa):
        """ADD_NETWORK must return a numeric network ID."""
        sock = _client_socket()
        sock.connect(MOCK_CTRL_PATH)
        sock.send(b"ADD_NETWORK")
        resp = sock.recv(64).decode().strip()
        sock.close()
        assert resp.isdigit(), f"Expected numeric ID, got: {resp!r}"

    def test_mock_wpa_status_returns_ip(self, mock_wpa):
        """STATUS response must contain ip_address=<configured IP>."""
        sock = _client_socket()
        sock.connect(MOCK_CTRL_PATH)
        sock.send(b"STATUS")
        resp = sock.recv(512).decode()
        sock.close()
        assert f"ip_address={MOCK_IP}" in resp, (
            f"Expected ip_address={MOCK_IP} in STATUS, got: {resp!r}"
        )

    def test_mock_wpa_full_connect_flow(self, mock_wpa):
        """Exercise the complete connection sequence used by the QEMU device.

        ATTACH → SCAN (wait for event) → SCAN_RESULTS → ADD_NETWORK
        → SET_NETWORK ssid → SET_NETWORK psk → SELECT_NETWORK
        → wait CTRL-EVENT-CONNECTED → STATUS → assert ip_address present.
        """
        import socket as _s

        # Use a fresh socket that is NOT connected (so we receive events
        # via recvfrom which returns the sender's address too)
        if os.path.exists(MOCK_CLIENT_PATH):
            os.unlink(MOCK_CLIENT_PATH)
        client = _s.socket(_s.AF_UNIX, _s.SOCK_DGRAM)
        client.settimeout(5)
        client.bind(MOCK_CLIENT_PATH)

        def cmd(c: str) -> str:
            client.sendto(c.encode(), MOCK_CTRL_PATH)
            data, _ = client.recvfrom(4096)
            return data.decode().strip()

        try:
            assert cmd("ATTACH").startswith("OK")
            assert cmd("SCAN").startswith("OK")

            # Wait for CTRL-EVENT-SCAN-RESULTS
            scan_done = client.recvfrom(256)[0].decode()
            assert "SCAN-RESULTS" in scan_done, (
                f"Expected CTRL-EVENT-SCAN-RESULTS, got: {scan_done!r}"
            )

            scan_r = cmd("SCAN_RESULTS")
            assert MOCK_SSID in scan_r

            net_id = int(cmd("ADD_NETWORK"))
            assert net_id >= 0

            assert cmd(f'SET_NETWORK {net_id} ssid "{MOCK_SSID}"').startswith("OK")
            assert cmd(f'SET_NETWORK {net_id} psk "testpass"').startswith("OK")
            assert cmd(f"SELECT_NETWORK {net_id}").startswith("OK")

            # Wait for CTRL-EVENT-CONNECTED
            ev = client.recvfrom(256)[0].decode()
            assert "CONNECTED" in ev, f"Expected CONNECTED event, got: {ev!r}"

            status = cmd("STATUS")
            assert f"ip_address={MOCK_IP}" in status, (
                f"Expected ip_address={MOCK_IP} in STATUS, got: {status!r}"
            )
        finally:
            client.close()
            try:
                os.unlink(MOCK_CLIENT_PATH)
            except OSError:
                pass
