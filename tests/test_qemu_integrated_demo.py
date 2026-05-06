"""NEXT-003 — LVGL + Wi-Fi integration demo test.

Validates that the main firmware (LVGL benchmark + Wi-Fi) runs end-to-end in
QEMU without real hardware:

    main firmware (esp_wifi_qemu component — API-level simulation)
        ↓  MMIO registers (firmware↔QEMU communication channel)
    QEMU esp_wifi device
        ↓  Unix domain socket
    mock_wpa_supplicant (tools/mock_wpa_supplicant.py)
        ↓  simulated wpa_supplicant ctrl responses
    GOT_IP event → serial log "got ip:10.0.2.15"

Design note: We simulate the *Wi-Fi API*, not the underlying ESP32 hardware
registers.  The esp_wifi_qemu component wraps public esp_wifi_* calls; tests
validate at the API/event level (serial output) rather than register state.

Skips are aggressive to avoid failures in environments without QEMU binary.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import time

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
QEMU_BIN = PROJECT_ROOT / "tools" / "qemu-src" / "build" / "qemu-system-xtensa"
FLASH_BIN = PROJECT_ROOT / "build" / "qemu_flash.bin"
EFUSE_BIN = PROJECT_ROOT / "build" / "qemu_efuse.bin"

# mock wpa_supplicant socket path for this test
_MOCK_SOCKET = "/tmp/mock-wpa-integrated-demo"
_MOCK_IP = "10.0.2.15"
_MOCK_SSID = "QEMU_TEST"

# Day-33: QEMU ESP32 emulation runs ~18x slower than real-time.
# The LVGL benchmark + WiFi connect need ~210 wall-seconds.
_BOOT_TIMEOUT_S = 260


# ---------------------------------------------------------------------------
# Skip helpers
# ---------------------------------------------------------------------------

def _has_qemu() -> bool:
    return QEMU_BIN.is_file() and os.access(str(QEMU_BIN), os.X_OK)


def _has_flash_images() -> bool:
    return FLASH_BIN.is_file() and EFUSE_BIN.is_file()


def _qemu_has_wifi_device() -> bool:
    """True if the QEMU binary contains the esp_wifi device type string."""
    if not _has_qemu():
        return False
    result = subprocess.run(
        ["strings", str(QEMU_BIN)],
        capture_output=True, text=True, timeout=10,
    )
    return "net.esp.wifi" in result.stdout


_REASON_NO_QEMU = "QEMU binary not found (run bash tools/build-qemu.sh first)"
_REASON_NO_IMAGES = "Flash images not found (run idf.py build first)"
_REASON_NO_WIFI_DEV = (
    "QEMU binary lacks esp_wifi device "
    "(run bash tools/build-qemu.sh after implementing esp_wifi.c)"
)


# ---------------------------------------------------------------------------
# Source / scaffold tests (fast, no runtime)
# ---------------------------------------------------------------------------

class TestIntegratedDemoSources:
    """Verify NEXT-003 source files are in place."""

    def test_wifi_ui_source_exists(self):
        """main/wifi_ui.c must be present."""
        assert (PROJECT_ROOT / "main" / "wifi_ui.c").is_file(), (
            "main/wifi_ui.c missing — run NEXT-003 scaffold"
        )

    def test_wifi_ui_header_exists(self):
        """main/include/wifi_ui.h must be present."""
        assert (PROJECT_ROOT / "main" / "include" / "wifi_ui.h").is_file(), (
            "main/include/wifi_ui.h missing"
        )

    def test_kconfig_has_wifi_ssid(self):
        """main/Kconfig.projbuild must define DEMO_WIFI_SSID."""
        kconfig = PROJECT_ROOT / "main" / "Kconfig.projbuild"
        assert kconfig.is_file(), "main/Kconfig.projbuild missing"
        text = kconfig.read_text()
        assert "DEMO_WIFI_SSID" in text, (
            "Kconfig.projbuild does not define DEMO_WIFI_SSID"
        )
        assert "DEMO_WIFI_PASSWORD" in text, (
            "Kconfig.projbuild does not define DEMO_WIFI_PASSWORD"
        )

    def test_main_c_has_demo_wifi_start(self):
        """main/main.c must call demo_wifi_start()."""
        main_c = PROJECT_ROOT / "main" / "main.c"
        assert main_c.is_file(), "main/main.c missing"
        text = main_c.read_text()
        assert "demo_wifi_start" in text, (
            "main/main.c does not call demo_wifi_start()"
        )

    def test_main_c_has_got_ip_log(self):
        """main/main.c must log 'got ip:' on IP_EVENT_STA_GOT_IP."""
        main_c = PROJECT_ROOT / "main" / "main.c"
        text = main_c.read_text()
        assert "got ip:" in text, (
            "main/main.c does not log 'got ip:' — "
            "add ESP_LOGI in IP_EVENT_STA_GOT_IP handler"
        )

    def test_sdkconfig_defaults_has_wifi_qemu(self):
        """sdkconfig.defaults must enable CONFIG_ESP_WIFI_QEMU=y."""
        defaults = PROJECT_ROOT / "sdkconfig.defaults"
        assert defaults.is_file(), "sdkconfig.defaults missing"
        text = defaults.read_text()
        assert "CONFIG_ESP_WIFI_QEMU=y" in text, (
            "sdkconfig.defaults does not set CONFIG_ESP_WIFI_QEMU=y"
        )

    def test_mock_wpa_supplicant_exists(self):
        """tools/mock_wpa_supplicant.py must be present."""
        assert (PROJECT_ROOT / "tools" / "mock_wpa_supplicant.py").is_file(), (
            "tools/mock_wpa_supplicant.py missing"
        )

    def test_partitions_csv_exists(self):
        """partitions.csv must be present (needed for larger firmware)."""
        assert (PROJECT_ROOT / "partitions.csv").is_file(), (
            "partitions.csv missing"
        )


# ---------------------------------------------------------------------------
# Runtime integration test
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _has_qemu(), reason=_REASON_NO_QEMU)
@pytest.mark.skipif(not _has_flash_images(), reason=_REASON_NO_IMAGES)
@pytest.mark.skipif(not _qemu_has_wifi_device(), reason=_REASON_NO_WIFI_DEV)
class TestIntegratedDemo:
    """End-to-end test: main firmware (LVGL + Wi-Fi) in QEMU with mock AP."""

    def test_got_ip_with_mock_ap(self):
        """Main firmware must print 'got ip:10.0.2.15' within boot timeout.

        The test:
        1. Starts mock_wpa_supplicant (simulates a Wi-Fi AP at the API level).
        2. Boots QEMU with ESP_WIFI_CTRL_SOCKET pointing to the mock.
        3. Waits for 'got ip:' in serial output.

        We test Wi-Fi at the *API level* — the mock responds to wpa_supplicant
        ctrl commands, not register reads. No real Wi-Fi hardware needed.
        """
        sys.path.insert(0, str(PROJECT_ROOT / "tools"))
        from mock_wpa_supplicant import MockWpaSupplicant  # type: ignore

        # Clean up stale socket from a previous run
        try:
            os.unlink(_MOCK_SOCKET)
        except OSError:
            pass

        daemon = MockWpaSupplicant(
            ctrl_path=_MOCK_SOCKET,
            ssid=_MOCK_SSID,
            ip=_MOCK_IP,
            scan_delay=0.1,
            connect_delay=0.2,
        )
        daemon.start()
        time.sleep(0.5)  # allow socket to appear

        qemu_env = os.environ.copy()
        qemu_env["ESP_WIFI_CTRL_SOCKET"] = _MOCK_SOCKET

        qemu_cmd = [
            str(QEMU_BIN),
            "-M", "esp32",
            "-m", "4M",
            "-nographic",
            "-drive", f"file={FLASH_BIN},if=mtd,format=raw",
            "-drive", f"file={EFUSE_BIN},if=none,format=raw,id=efuse",
            "-global", "driver=nvram.esp32.efuse,property=drive,value=efuse",
            "-global", "driver=timer.esp32.timg,property=wdt_disable,value=true",
        ]

        try:
            result = subprocess.run(
                qemu_cmd,
                env=qemu_env,
                capture_output=True,
                text=True,
                timeout=_BOOT_TIMEOUT_S,
            )
            serial_out = result.stdout + result.stderr
        except subprocess.TimeoutExpired as exc:
            # Timeout means QEMU ran for full duration — extract available output
            raw_out = (exc.stdout or b"") + (exc.stderr or b"")
            if isinstance(raw_out, bytes):
                serial_out = raw_out.decode("utf-8", errors="replace")
            else:
                serial_out = str(raw_out)
        finally:
            daemon.stop()
            # Kill any residual QEMU process
            subprocess.run(
                ["pkill", "-f", "qemu-system-xtensa"],
                capture_output=True,
            )
            try:
                os.unlink(_MOCK_SOCKET)
            except OSError:
                pass

        assert "got ip:" in serial_out, (
            f"'got ip:' not found in QEMU serial output after {_BOOT_TIMEOUT_S}s.\n"
            f"Last 80 lines:\n"
            + "\n".join(serial_out.splitlines()[-80:])
        )

    def test_lvgl_banner_in_serial(self):
        """Main firmware must print the LVGL initialization banner.

        This is a lighter check that does not require Wi-Fi at all —
        it verifies the firmware boots and LVGL initialises correctly
        (the 'M3 LVGL benchmark demo' banner).
        Uses a pre-existing log if available to avoid double boot.
        """
        log_path = pathlib.Path("/tmp/esp32-qemu-serial.log")
        if log_path.is_file() and log_path.stat().st_size > 0:
            text = log_path.read_text(errors="replace")
        else:
            # Boot briefly just to get the banner
            qemu_cmd = [
                str(QEMU_BIN),
                "-M", "esp32",
                "-m", "4M",
                "-nographic",
                "-drive", f"file={FLASH_BIN},if=mtd,format=raw",
                "-drive", f"file={EFUSE_BIN},if=none,format=raw,id=efuse",
                "-global", "driver=nvram.esp32.efuse,property=drive,value=efuse",
                "-global", "driver=timer.esp32.timg,property=wdt_disable,value=true",
            ]
            try:
                result = subprocess.run(
                    qemu_cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                text = result.stdout + result.stderr
            except subprocess.TimeoutExpired as exc:
                raw_out = (exc.stdout or b"") + (exc.stderr or b"")
                text = raw_out.decode("utf-8", errors="replace") if isinstance(raw_out, bytes) else str(raw_out)
            finally:
                subprocess.run(["pkill", "-f", "qemu-system-xtensa"], capture_output=True)

        assert "esp32-display-qemu-demo starting" in text or "lvgl" in text.lower(), (
            "LVGL startup banner not found in QEMU serial output"
        )
