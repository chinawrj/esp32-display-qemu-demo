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
