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
WIFI_STA_BUILD = PROJECT_ROOT / "examples" / "wifi_sta" / "build"
ESP_WIFI_C = (
    PROJECT_ROOT / "tools" / "qemu-src" / "hw" / "net" / "esp_wifi.c"
)
ESP_WIFI_H = (
    PROJECT_ROOT / "tools" / "qemu-src" / "include" / "hw" / "net" / "esp_wifi.h"
)
ESP_WIFI_PATCH_C = (
    PROJECT_ROOT / "tools" / "qemu-src-patches" / "hw" / "net" / "esp_wifi.c"
)
ESP_WIFI_PATCH_H = (
    PROJECT_ROOT / "tools" / "qemu-src-patches" / "include" / "hw" / "net" / "esp_wifi.h"
)

_WIFI_CTRL_SOCKET = os.environ.get(
    "WIFI_CTRL_SOCKET",
    "/var/run/wpa_supplicant/wlo1",
)
_BOOT_TIMEOUT_S = 30    # time to get ip after QEMU boot


def _has_wifi_sta_firmware() -> bool:
    return (WIFI_STA_BUILD / "wifi_sta_example.bin").is_file()


_REASON_NO_WIFI_STA = (
    "wifi_sta example not built. "
    "Run: cd examples/wifi_sta && idf.py build"
)


def _idf_python() -> str:
    """Return the IDF virtualenv Python that has esptool installed."""
    import glob as _glob
    # Prefer explicit IDF_PYTHON env var
    idf_py = os.environ.get("IDF_PYTHON")
    if idf_py and os.path.isfile(idf_py):
        return idf_py
    # Look in ~/.espressif/python_env/
    pattern = str(pathlib.Path.home() / ".espressif" / "python_env" / "idf*_env" / "bin" / "python3")
    matches = sorted(_glob.glob(pattern))
    if matches:
        return matches[-1]  # pick newest
    # Fall back to system python (might work if esptool is installed)
    import sys
    return sys.executable


def _make_flash_image(build_dir: pathlib.Path, out: pathlib.Path) -> None:
    """Merge bootloader + partition table + app into a single flash image."""
    idf_path = pathlib.Path(os.environ.get("IDF_PATH", str(pathlib.Path.home() / "esp-idf")))
    esptool_py = idf_path / "components" / "esptool_py" / "esptool" / "esptool.py"

    # Determine app binary name (not bootloader or partition-table)
    app_bins = [
        b for b in build_dir.glob("*.bin")
        if b.name not in ("bootloader.bin", "partition-table.bin")
    ]
    if not app_bins:
        raise FileNotFoundError(f"No app binary found in {build_dir}")
    app_bin = app_bins[0]

    cmd = [
        _idf_python(), str(esptool_py),
        "--chip", "esp32",
        "merge_bin",
        "--fill-flash-size", "2MB",
        "--flash_mode", "dio",
        "--flash_freq", "40m",
        "--flash_size", "2MB",
        "-o", str(out),
        "0x1000", str(build_dir / "bootloader" / "bootloader.bin"),
        "0x8000", str(build_dir / "partition_table" / "partition-table.bin"),
        "0x10000", str(app_bin),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(
            f"merge_bin failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout.decode()}\n"
            f"stderr: {result.stderr.decode()}"
        )


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
        header_path = ESP_WIFI_PATCH_H
        assert header_path.is_file(), f"Missing QEMU device header: {header_path}"

    def test_scan_command_has_scan_only_state(self):
        """WIFI_CMD_SCAN must not fall through into the CONNECT state machine."""
        src = ESP_WIFI_PATCH_C.read_text()
        header = ESP_WIFI_PATCH_H.read_text()
        assert "scan_only" in header, (
            "ESPWifiState must track scan_only so WIFI_CMD_SCAN can be "
            "distinguished from the scan phase of WIFI_CMD_CONNECT."
        )
        assert "case WIFI_CMD_SCAN:" in src
        scan_case = src[src.index("case WIFI_CMD_SCAN:"):src.index("case WIFI_CMD_GET_MAC:")]
        assert "s->scan_only = true" in scan_case, (
            "WIFI_CMD_SCAN must set scan_only before sending SCAN to mock_wpa."
        )

    def test_scan_results_post_scan_done_for_scan_only(self):
        """Parsed scan results must post WIFI_EVT_SCAN_DONE for scan-only calls."""
        src = ESP_WIFI_PATCH_C.read_text()
        case_start = src.index("case WPA_CONN_SCAN_RESULTS_SENT:")
        case_end = src.index("case WPA_CONN_ADD_NET_SENT:")
        scan_results_case = src[case_start:case_end]
        assert "if (s->scan_only)" in scan_results_case, (
            "SCAN_RESULTS handler must branch when the command was WIFI_CMD_SCAN."
        )
        assert "esp_wifi_post_event(s, WIFI_EVT_SCAN_DONE)" in scan_results_case, (
            "WIFI_CMD_SCAN must complete by posting WIFI_EVT_SCAN_DONE."
        )
        assert "wpa_ctrl_send(s, \"ADD_NETWORK\")" in scan_results_case, (
            "Connect flow must still continue into ADD_NETWORK after scan results."
        )

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

    def test_event_task_started_in_esp_wifi_start_not_init(self):
        """wifi_event_task must be created inside esp_wifi_start(), not esp_wifi_init().

        Day-35 fix: starting the FreeRTOS task from esp_wifi_init() at
        tskIDLE_PRIORITY+2 races with wifi_qemu_send_cmd() for
        WIFI_EVT_INIT_DONE / WIFI_EVT_START_DONE because the task preempts
        the send_cmd polling loop, causing those commands to time out.
        """
        shim = PROJECT_ROOT / "components" / "esp_wifi_qemu" / "esp_wifi_shim.c"
        src = shim.read_text()

        # Locate esp_wifi_init and esp_wifi_start function bodies
        init_start  = src.index("esp_err_t esp_wifi_init(")
        init_end    = src.index("esp_err_t esp_wifi_deinit(")
        start_start = src.index("esp_err_t esp_wifi_start(")
        start_end   = src.index("esp_err_t esp_wifi_stop(")

        init_body  = src[init_start:init_end]
        start_body = src[start_start:start_end]

        assert "xTaskCreate(wifi_event_task" not in init_body, (
            "wifi_event_task must NOT be created inside esp_wifi_init() — "
            "doing so races with wifi_qemu_send_cmd() for INIT_DONE/START_DONE."
        )
        assert "xTaskCreate(wifi_event_task" in start_body, (
            "wifi_event_task must be created inside esp_wifi_start() after "
            "WIFI_CMD_START has been acknowledged."
        )

    def test_qemu_wpa_ctrl_open_is_idempotent(self):
        """wpa_ctrl_open() must close a stale fd before opening a new one.

        Day-35 fix: without this guard, repeated WIFI_CMD_INIT calls leak
        file descriptors and accumulate orphaned GLib IO watches that fire
        spuriously on every future broadcast event.
        """
        src = ESP_WIFI_PATCH_C.read_text()
        open_start = src.index("static void wpa_ctrl_open(ESPWifiState *s)")
        # Find the first closing brace after the open — locate end of function
        open_body_start = src.index("{", open_start)
        depth = 0
        idx = open_body_start
        for idx, ch in enumerate(src[open_body_start:], start=open_body_start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
        open_body = src[open_body_start:idx + 1]

        assert "ctrl_fd >= 0" in open_body, (
            "wpa_ctrl_open() must check ctrl_fd >= 0 and close a stale "
            "connection before opening a new one."
        )
        assert "wpa_ctrl_close(s)" in open_body, (
            "wpa_ctrl_open() must call wpa_ctrl_close() when ctrl_fd >= 0."
        )

    def test_qemu_wpa_ctrl_close_forward_declared(self):
        """wpa_ctrl_close must be forward-declared before wpa_ctrl_open calls it."""
        src = ESP_WIFI_PATCH_C.read_text()
        fwd_decl = "static void wpa_ctrl_close(ESPWifiState *s);"
        open_def = "static void wpa_ctrl_open(ESPWifiState *s)"
        assert fwd_decl in src, (
            "wpa_ctrl_close must have a forward declaration before wpa_ctrl_open."
        )
        assert src.index(fwd_decl) < src.index(open_def), (
            "Forward declaration of wpa_ctrl_close must appear before wpa_ctrl_open."
        )

    def test_esp_wifi_start_issues_startup_scan(self):
        """esp_wifi_start() must write WIFI_CMD_SCAN after posting STA_START.

        During startup the shim issues an async scan so the AP list is already
        populated when the application's WIFI_EVENT_STA_START handler runs or
        before the first esp_wifi_connect() call.
        """
        shim_c = PROJECT_ROOT / "components" / "esp_wifi_qemu" / "esp_wifi_shim.c"
        src = shim_c.read_text()

        # Locate the esp_wifi_start function body
        start_idx = src.find("esp_err_t esp_wifi_start(void)")
        assert start_idx >= 0, "esp_wifi_start not found in esp_wifi_shim.c"
        # The scan write must come after the STA_START post
        sta_start_post = src.find("WIFI_EVENT_STA_START", start_idx)
        scan_write = src.find("WIFI_CMD_SCAN", start_idx)
        assert sta_start_post >= 0, (
            "esp_wifi_start must post WIFI_EVENT_STA_START"
        )
        assert scan_write >= 0, (
            "esp_wifi_start must write WIFI_CMD_SCAN (startup scan)"
        )
        assert scan_write > sta_start_post, (
            "WIFI_CMD_SCAN write in esp_wifi_start must appear after "
            "WIFI_EVENT_STA_START post, not before"
        )

    def test_scan_get_ap_records_uses_real_authmode(self):
        """Day-41: esp_wifi_scan_get_ap_records must read real authmode/cipher
        and channel from MMIO, not hardcode them."""
        scan_c = PROJECT_ROOT / "components" / "esp_wifi_qemu" / "esp_wifi_scan.c"
        src = scan_c.read_text()
        # Old hardcoded values must be gone
        assert "ap_records[i].authmode = WIFI_AUTH_WPA2_PSK;" not in src, (
            "authmode must not be hardcoded to WIFI_AUTH_WPA2_PSK"
        )
        assert "ap_records[i].primary  = 1;" not in src, (
            "primary channel must not be hardcoded to 1"
        )
        # Must read all four new MMIO regs
        for reg in ("WIFI_REG_SCAN_FREQ", "WIFI_REG_SCAN_AUTHMODE",
                    "WIFI_REG_SCAN_PAIRWISE_CIPHER", "WIFI_REG_SCAN_GROUP_CIPHER"):
            assert reg in src, f"esp_wifi_scan.c must read {reg}"
        # Must populate all new fields on wifi_ap_record_t
        for field in ("authmode", "pairwise_cipher", "group_cipher", "primary"):
            assert f"ap_records[i].{field}" in src, (
                f"esp_wifi_scan.c must set ap_records[i].{field}"
            )

    def test_scan_freq_to_channel_conversion(self):
        """Day-41: firmware must convert MHz frequency to channel number."""
        scan_c = PROJECT_ROOT / "components" / "esp_wifi_qemu" / "esp_wifi_scan.c"
        src = scan_c.read_text()
        # 2.4 GHz: ch = (freq - 2407) / 5
        assert "(freq - 2407)" in src, (
            "scan code must convert 2.4 GHz freq to channel via (freq-2407)/5"
        )
        # 5 GHz: ch = (freq - 5000) / 5
        assert "(freq - 5000)" in src, (
            "scan code must convert 5 GHz freq to channel via (freq-5000)/5"
        )

    def test_qemu_device_parses_wpa_flags(self):
        """Day-41: QEMU device must parse wpa_cli flags string into authmode/cipher."""
        wifi_c = PROJECT_ROOT / "tools" / "qemu-src-patches" / "hw" / "net" / "esp_wifi.c"
        src = wifi_c.read_text()
        assert "parse_wpa_flags" in src, (
            "QEMU device must define parse_wpa_flags() helper"
        )
        # Must distinguish WPA1/WPA2/WPA3
        for token in ("WPA3", "WPA2", "EAP", "WEP", "WPS", "CCMP", "TKIP"):
            assert token in src, f"parse_wpa_flags must recognize '{token}' token"
        # ESPWifiScanResult must store the new fields
        h = PROJECT_ROOT / "tools" / "qemu-src-patches" / "include" / "hw" / "net" / "esp_wifi.h"
        h_src = h.read_text()
        for field in ("freq", "authmode", "pairwise_cipher", "group_cipher", "flag_bits"):
            assert field in h_src, (
                f"ESPWifiScanResult struct must have {field} field"
            )

    def test_sta_get_ap_info_no_hardcoded_fake(self):
        """Day-42 Phase-A: esp_wifi_sta_get_ap_info must not return s_fake_ap."""
        extras = PROJECT_ROOT / "components" / "esp_wifi_qemu" / "esp_wifi_extras.c"
        src = extras.read_text()
        assert "s_fake_ap" not in src, (
            "esp_wifi_sta_get_ap_info must not return a hardcoded s_fake_ap struct"
        )
        assert "QEMU_TEST" not in src, (
            "esp_wifi_extras.c must not embed the QEMU_TEST SSID literal"
        )
        # Must read connected-AP regs from MMIO
        for reg in ("WIFI_REG_CONN_BSSID0", "WIFI_REG_CONN_BSSID1",
                    "WIFI_REG_CONN_FREQ_RSSI_AUTH", "WIFI_REG_CONN_CIPHERS"):
            assert reg in src, (
                f"esp_wifi_extras.c sta_get_ap_info must read {reg}"
            )

    def test_sta_get_rssi_no_hardcoded_minus_50(self):
        """Day-42 Phase-A: esp_wifi_sta_get_rssi must derive from MMIO, not hardcode -50."""
        extras = PROJECT_ROOT / "components" / "esp_wifi_qemu" / "esp_wifi_extras.c"
        src = extras.read_text()
        # The function body around sta_get_rssi must not assign *rssi = -50.
        idx = src.find("esp_wifi_sta_get_rssi")
        assert idx != -1
        body = src[idx:idx + 600]
        assert "*rssi = -50" not in body, (
            "esp_wifi_sta_get_rssi must not hardcode -50 dBm"
        )
        assert "WIFI_REG_CONN_FREQ_RSSI_AUTH" in body, (
            "esp_wifi_sta_get_rssi must read WIFI_REG_CONN_FREQ_RSSI_AUTH"
        )

    def test_qemu_device_parses_wpa_status_fields(self):
        """Day-42 Phase-A: wpa_parse_status must populate connected_ap fields."""
        wifi_c = PROJECT_ROOT / "tools" / "qemu-src-patches" / "hw" / "net" / "esp_wifi.c"
        src = wifi_c.read_text()
        # Must parse the new STATUS tokens.
        for tok in ('"bssid="', '"\\nssid="', '"\\nfreq="',
                    '"signal_level="', '"\\nkey_mgmt="',
                    '"\\npairwise_cipher="', '"\\ngroup_cipher="'):
            assert tok in src, f"wpa_parse_status must look for {tok}"
        # connected_ap must be referenced in the parser.
        assert "connected_ap" in src, (
            "wpa_parse_status must populate s->connected_ap"
        )
        # MMIO read cases for the new regs must exist.
        for reg in ("WIFI_REG_CONN_BSSID0", "WIFI_REG_CONN_BSSID1",
                    "WIFI_REG_CONN_FREQ_RSSI_AUTH", "WIFI_REG_CONN_CIPHERS"):
            assert f"case {reg}" in src, (
                f"esp_wifi.c read handler must serve {reg}"
            )

    def test_connected_ap_cleared_on_disconnect(self):
        """Day-42 Phase-A: disconnect must zero the connected_ap record."""
        wifi_c = PROJECT_ROOT / "tools" / "qemu-src-patches" / "hw" / "net" / "esp_wifi.c"
        src = wifi_c.read_text()
        # Find the CTRL-EVENT-DISCONNECTED block and ensure it memsets.
        idx = src.find("CTRL-EVENT-DISCONNECTED")
        assert idx != -1
        block = src[idx:idx + 400]
        assert "memset(&s->connected_ap" in block, (
            "Disconnect handler must zero s->connected_ap"
        )

    # ----- Day-43 Phase-B: round-trip storage ---------------------------------

    def test_phase_b_channel_round_trip_storage(self):
        """Phase-B: channel setter must store, getter must return stored value."""
        extras = PROJECT_ROOT / "components" / "esp_wifi_qemu" / "esp_wifi_extras.c"
        src = extras.read_text()
        assert "s_channel_primary" in src, "channel storage missing"
        assert "s_channel_second" in src, "second-channel storage missing"
        # set_channel must validate input range.
        set_idx = src.find("esp_wifi_set_channel(uint8_t primary")
        assert set_idx != -1
        set_body = src[set_idx:set_idx + 600]
        assert "primary < 1" in set_body and "primary > 14" in set_body, (
            "set_channel must validate 1..14"
        )
        assert "s_channel_primary = primary" in set_body, (
            "set_channel must store the primary channel"
        )
        # get_channel must NOT return a hardcoded *primary = 1.
        get_idx = src.find("esp_wifi_get_channel(uint8_t *primary")
        assert get_idx != -1
        get_body = src[get_idx:get_idx + 800]
        assert "*primary = 1;" not in get_body, (
            "get_channel must not hardcode *primary = 1"
        )
        # When connected, get_channel must derive from the AP's freq reg.
        assert "WIFI_REG_CONN_FREQ_RSSI_AUTH" in get_body, (
            "get_channel must consult the connected-AP freq register"
        )

    def test_phase_b_country_round_trip_storage(self):
        """Phase-B: country setter must store the struct verbatim."""
        extras = PROJECT_ROOT / "components" / "esp_wifi_qemu" / "esp_wifi_extras.c"
        src = extras.read_text()
        assert "s_country" in src, "country storage missing"
        set_idx = src.find("esp_wifi_set_country(const wifi_country_t")
        assert set_idx != -1
        body = src[set_idx:set_idx + 600]
        assert "s_country = *country" in body, (
            "set_country must copy the caller-supplied struct"
        )
        # get_country_code must read s_country.cc (no hardcoded 'C','N').
        gcc_idx = src.find("esp_wifi_get_country_code(char *country)")
        assert gcc_idx != -1
        gcc_body = src[gcc_idx:gcc_idx + 400]
        assert "s_country.cc" in gcc_body, (
            "get_country_code must read from s_country.cc"
        )

    def test_phase_b_protocol_per_interface_storage(self):
        """Phase-B: protocol bitmap is stored per interface (STA / AP)."""
        extras = PROJECT_ROOT / "components" / "esp_wifi_qemu" / "esp_wifi_extras.c"
        src = extras.read_text()
        assert "s_protocol[" in src, "per-interface protocol storage missing"
        set_idx = src.find("esp_wifi_set_protocol(wifi_interface_t ifx")
        assert set_idx != -1
        body = src[set_idx:set_idx + 400]
        assert "s_protocol[ifx] = protocol_bitmap" in body, (
            "set_protocol must store per-interface"
        )

    def test_phase_b_max_tx_power_round_trip(self):
        """Phase-B: max_tx_power setter must store and validate range 8..84."""
        extras = PROJECT_ROOT / "components" / "esp_wifi_qemu" / "esp_wifi_extras.c"
        src = extras.read_text()
        set_idx = src.find("esp_wifi_set_max_tx_power(int8_t power)")
        assert set_idx != -1
        body = src[set_idx:set_idx + 400]
        assert "power < 8" in body and "power > 84" in body, (
            "set_max_tx_power must validate IDF range 8..84"
        )
        assert "s_max_tx_power_qdbm = power" in body, (
            "set_max_tx_power must store the value"
        )
        # get_max_tx_power must not return a hardcoded 20.
        get_idx = src.find("esp_wifi_get_max_tx_power(int8_t *power)")
        assert get_idx != -1
        get_body = src[get_idx:get_idx + 300]
        assert "*power = 20;" not in get_body, (
            "get_max_tx_power must not hardcode *power = 20"
        )
        assert "*power = s_max_tx_power_qdbm" in get_body

    def test_phase_b_bandwidth_per_interface_storage(self):
        """Phase-B: bandwidth is stored per interface."""
        extras = PROJECT_ROOT / "components" / "esp_wifi_qemu" / "esp_wifi_extras.c"
        src = extras.read_text()
        assert "s_bandwidth[" in src, "per-interface bandwidth storage missing"
        set_idx = src.find("esp_wifi_set_bandwidth(wifi_interface_t ifx")
        assert set_idx != -1
        body = src[set_idx:set_idx + 400]
        assert "s_bandwidth[ifx] = bw" in body, (
            "set_bandwidth must store per-interface"
        )
        get_idx = src.find("esp_wifi_get_bandwidth(wifi_interface_t ifx")
        assert get_idx != -1
        get_body = src[get_idx:get_idx + 400]
        assert "*bw = WIFI_BW_HT20;" not in get_body, (
            "get_bandwidth must not hardcode HT20"
        )

    # ----- Day-44 Phase-C: power save / event mask / inactive time -----------

    def test_phase_c_ps_round_trip_storage(self):
        """Phase-C: power-save type setter stores; getter returns stored value."""
        extras = PROJECT_ROOT / "components" / "esp_wifi_qemu" / "esp_wifi_extras.c"
        src = extras.read_text()
        assert "s_ps_type" in src, "power-save storage missing"
        set_idx = src.find("esp_wifi_set_ps(wifi_ps_type_t type)")
        assert set_idx != -1
        body = src[set_idx:set_idx + 500]
        # Must validate the enum range.
        assert "WIFI_PS_MIN_MODEM" in body and "WIFI_PS_MAX_MODEM" in body, (
            "set_ps must validate against the IDF wifi_ps_type_t enum"
        )
        assert "s_ps_type = type" in body, (
            "set_ps must store the supplied type"
        )
        get_idx = src.find("esp_wifi_get_ps(wifi_ps_type_t *type)")
        assert get_idx != -1
        get_body = src[get_idx:get_idx + 300]
        assert "*type = WIFI_PS_NONE;" not in get_body, (
            "get_ps must not hardcode WIFI_PS_NONE"
        )
        assert "*type = s_ps_type" in get_body

    def test_phase_c_event_mask_round_trip_storage(self):
        """Phase-C: event_mask setter stores; getter returns stored value."""
        extras = PROJECT_ROOT / "components" / "esp_wifi_qemu" / "esp_wifi_extras.c"
        src = extras.read_text()
        assert "s_event_mask" in src, "event_mask storage missing"
        set_idx = src.find("esp_wifi_set_event_mask(uint32_t mask)")
        assert set_idx != -1
        body = src[set_idx:set_idx + 300]
        assert "s_event_mask = mask" in body, (
            "set_event_mask must store the mask"
        )
        get_idx = src.find("esp_wifi_get_event_mask(uint32_t *mask)")
        assert get_idx != -1
        get_body = src[get_idx:get_idx + 300]
        assert "*mask = WIFI_EVENT_MASK_NONE;" not in get_body, (
            "get_event_mask must not hardcode WIFI_EVENT_MASK_NONE"
        )
        assert "*mask = s_event_mask" in get_body

    def test_phase_c_inactive_time_per_interface_storage(self):
        """Phase-C: inactive_time stored per interface; per-interface
        minimum validation (Day-51 fix: STA min is 3s per IDF docs,
        SoftAP min is 10s)."""
        extras = PROJECT_ROOT / "components" / "esp_wifi_qemu" / "esp_wifi_extras.c"
        src = extras.read_text()
        assert "s_inactive_time[" in src, "per-iface inactive_time storage missing"
        set_idx = src.find("esp_wifi_set_inactive_time(wifi_interface_t ifx")
        assert set_idx != -1
        body = src[set_idx:set_idx + 800]
        # Day-51: per-interface minimum (STA=3, AP=10), not a single
        # blanket "< 10" check that would falsely reject the stock
        # power_save sample's BEACON_TIMEOUT default of 6s.
        assert "WIFI_IF_AP" in body and "10" in body and "3" in body, (
            "set_inactive_time must enforce per-interface min "
            "(STA>=3, AP>=10) per esp_wifi.h docs"
        )
        assert "sec < min_sec" in body, (
            "set_inactive_time must compare against the per-iface min"
        )
        assert "s_inactive_time[ifx]" in body, (
            "set_inactive_time must store per-interface"
        )
        get_idx = src.find("esp_wifi_get_inactive_time(wifi_interface_t ifx")
        assert get_idx != -1
        get_body = src[get_idx:get_idx + 300]
        assert "*sec = 300;" not in get_body, (
            "get_inactive_time must not hardcode 300"
        )
        assert "*sec = s_inactive_time[ifx]" in get_body

    def test_phase_c_promisc_state_round_trip(self):
        """Phase-C: promiscuous enable/filter state round-trips through storage."""
        promisc = PROJECT_ROOT / "components" / "esp_wifi_qemu" / "esp_wifi_promisc.c"
        src = promisc.read_text()
        assert "s_promisc_enabled" in src, (
            "promisc enable storage missing"
        )
        assert "s_promisc_filter" in src, (
            "promisc filter storage missing"
        )
        assert "s_promisc_ctrl_filter" in src, (
            "promisc ctrl filter storage missing"
        )
        # set_promiscuous must no longer return ESP_ERR_NOT_SUPPORTED.
        sp_idx = src.find("esp_wifi_set_promiscuous(bool en)")
        assert sp_idx != -1
        body = src[sp_idx:sp_idx + 400]
        assert "ESP_ERR_NOT_SUPPORTED" not in body, (
            "set_promiscuous must accept the call (state stored)"
        )
        assert "s_promisc_enabled = en" in body
        # get_promiscuous must read back stored state, not hardcode false.
        gp_idx = src.find("esp_wifi_get_promiscuous(bool *en)")
        assert gp_idx != -1
        get_body = src[gp_idx:gp_idx + 300]
        assert "*en = false;" not in get_body, (
            "get_promiscuous must not hardcode false"
        )
        assert "*en = s_promisc_enabled" in get_body
        # set_promiscuous_filter must validate non-NULL and store.
        sf_idx = src.find("esp_wifi_set_promiscuous_filter")
        assert sf_idx != -1
        sf_body = src[sf_idx:sf_idx + 400]
        assert "s_promisc_filter = *filter" in sf_body

    def test_phase_d_ap_sta_table_real_entries(self):
        """Phase-D: SoftAP keeps a real station table; deauth & AID lookup work."""
        ap = PROJECT_ROOT / "components" / "esp_wifi_qemu" / "esp_wifi_ap.c"
        src = ap.read_text()
        # No more "always returns empty list" comment / hard-zero behaviour.
        assert "s_ap_table" in src, "AP station table missing"
        assert "qemu_wifi_ap_inject_fake_station" in src, (
            "fake-station injector missing"
        )
        # ap_get_sta_list must iterate s_ap_table, not blanket-zero.
        gl_idx = src.find("esp_wifi_ap_get_sta_list(wifi_sta_list_t")
        assert gl_idx != -1
        gl_body = src[gl_idx:gl_idx + 800]
        assert "info->num = n;" in gl_body, (
            "ap_get_sta_list must report real station count"
        )
        assert "s_ap_table[i].mac" in gl_body
        # deauth_sta must remove from table and post STADISCONNECTED.
        de_idx = src.find("esp_wifi_deauth_sta(uint16_t")
        assert de_idx != -1
        de_body = src[de_idx:de_idx + 1500]
        assert "WIFI_EVENT_AP_STADISCONNECTED" in de_body
        assert "in_use = false" in de_body
        # ap_get_sta_aid must do real MAC lookup, not always return NOT_FOUND.
        ai_idx = src.find("esp_wifi_ap_get_sta_aid(const uint8_t")
        assert ai_idx != -1
        ai_body = src[ai_idx:ai_idx + 600]
        assert "qemu_ap_find_by_mac" in ai_body, (
            "ap_get_sta_aid must search the table"
        )

    def test_phase_d_ap_start_injects_fake_clients(self):
        """Phase-D: esp_wifi_start AP path must call the injector."""
        shim = PROJECT_ROOT / "components" / "esp_wifi_qemu" / "esp_wifi_shim.c"
        src = shim.read_text()
        assert "qemu_wifi_ap_clear_stations" in src
        assert "qemu_wifi_ap_inject_fake_station" in src
        assert "CONFIG_ESP_WIFI_QEMU_AP_FAKE_CLIENTS" in src

    def test_phase_d_kconfig_fake_clients_option(self):
        """Phase-D: Kconfig exposes ESP_WIFI_QEMU_AP_FAKE_CLIENTS option."""
        kc = PROJECT_ROOT / "components" / "esp_wifi_qemu" / "Kconfig.projbuild"
        src = kc.read_text()
        assert "ESP_WIFI_QEMU_AP_FAKE_CLIENTS" in src
        assert "range 0 4" in src

    def test_phase_d2_ap_staipassigned_event(self):
        """Phase-D2: fake-station inject must also post IP_EVENT_AP_STAIPASSIGNED."""
        ap = PROJECT_ROOT / "components" / "esp_wifi_qemu" / "esp_wifi_ap.c"
        src = ap.read_text()
        assert "IP_EVENT_AP_STAIPASSIGNED" in src, (
            "fake-station injector must fire IP_EVENT_AP_STAIPASSIGNED"
        )
        assert "ip_event_ap_staipassigned_t" in src
        # Deterministic 192.168.4.(2+index) lease.
        assert "(2 + index)" in src
        # Table entry must record the assigned lease.
        assert "assigned_ip" in src
        # AP netif lookup by ifkey.
        assert "WIFI_AP_DEF" in src

    def test_phase_e_promisc_cb_storage_and_helper(self):
        """Phase-E: promiscuous RX callback is stored and a deliver helper exists."""
        promisc = PROJECT_ROOT / "components" / "esp_wifi_qemu" / "esp_wifi_promisc.c"
        src = promisc.read_text()
        assert "s_promisc_rx_cb" in src, "promisc RX callback storage missing"
        # set_promiscuous_rx_cb must store the callback (not just log).
        sc_idx = src.find("esp_wifi_set_promiscuous_rx_cb(wifi_promiscuous_cb_t cb)")
        assert sc_idx != -1
        sc_body = src[sc_idx:sc_idx + 200]
        assert "s_promisc_rx_cb = cb" in sc_body
        # qemu_promisc_deliver_eth is the public wrap helper.
        assert "qemu_promisc_deliver_eth" in src
        # 802.11 DATA frame fabrication: type=Data (FC byte = 0x08).
        assert "0x08" in src
        # LLC/SNAP shim AA AA 03 ...
        assert "0xAA" in src and "0x03" in src
        # Guards: enabled + cb + DATA mask.
        assert "WIFI_PROMIS_FILTER_MASK_DATA" in src
        # Virtual AP MAC for fabricated BSSID.
        assert "s_qemu_virtual_bssid" in src

    def test_phase_e_promisc_tap_in_netif(self):
        """Phase-E: netif RX/TX paths call qemu_promisc_deliver_eth."""
        netif = PROJECT_ROOT / "components" / "esp_wifi_qemu" / "esp_wifi_netif.c"
        src = netif.read_text()
        # Must call deliver helper from both directions.
        assert src.count("qemu_promisc_deliver_eth(") >= 3, (
            "promiscuous tap missing on at least one of: qemu_wifi_transmit, "
            "qemu_wifi_tx_raw, esp_wifi_netif_rx_frame"
        )
        # RX path tap.
        rx_idx = src.find("esp_wifi_netif_rx_frame(void)")
        assert rx_idx != -1
        rx_body = src[rx_idx:rx_idx + 1500]
        assert "qemu_promisc_deliver_eth(buf, rx_len, false)" in rx_body
        # TX raw path tap.
        tx_idx = src.find("qemu_wifi_tx_raw(const void *buffer, uint16_t len)")
        assert tx_idx != -1
        tx_body = src[tx_idx:tx_idx + 600]
        assert "qemu_promisc_deliver_eth(buffer, len, true)" in tx_body

    def test_phase_e_80211_tx_implemented(self):
        """Phase-E (Day 48): esp_wifi_80211_tx is no longer NOT_SUPPORTED.

        It must (1) loop the raw 802.11 frame back to the local promiscuous
        callback when filter masks accept it, with per-type mask handling
        (MGMT / CTRL / DATA / MISC), and (2) decode DATA frames carrying a
        valid LLC/SNAP shim into Ethernet and inject them onto the wire via
        a no-promisc TX helper to avoid double-tapping.
        """
        promisc = PROJECT_ROOT / "components" / "esp_wifi_qemu" / "esp_wifi_promisc.c"
        src = promisc.read_text()
        # Find the function body.
        start = src.find("esp_err_t esp_wifi_80211_tx(")
        assert start != -1, "esp_wifi_80211_tx symbol missing"
        # Take a generous slice covering the whole function.
        body = src[start:start + 6000]

        # Must NOT short-circuit to ESP_ERR_NOT_SUPPORTED any more.
        assert "ESP_ERR_NOT_SUPPORTED" not in body, (
            "esp_wifi_80211_tx still returns ESP_ERR_NOT_SUPPORTED"
        )

        # Argument validation must reject bad ifx / NULL buffer / bad length.
        assert "WIFI_IF_MAX" in body
        assert "len < 24" in body or "len < 24 ||" in body

        # Per-type filter mask switch.
        for token in (
            "WIFI_PROMIS_FILTER_MASK_MGMT",
            "WIFI_PROMIS_FILTER_MASK_CTRL",
            "WIFI_PROMIS_FILTER_MASK_DATA",
            "WIFI_PKT_MGMT",
            "WIFI_PKT_CTRL",
            "WIFI_PKT_DATA",
        ):
            assert token in body, f"80211_tx missing per-type handling for {token}"

        # Loopback to the registered cb (the *raw* frame, not a fabricated wrap).
        assert "s_promisc_rx_cb(pkt," in body, (
            "80211_tx must deliver the raw frame to the registered cb"
        )

        # DATA-frame Ethernet projection must use the no-promisc TX helper to
        # avoid double-tapping the sniffer.
        assert "qemu_wifi_tx_raw_no_promisc(" in body, (
            "DATA-frame projection must use qemu_wifi_tx_raw_no_promisc"
        )
        # And the LLC/SNAP shim is recognized before projecting.
        assert "0xAA" in body and "0x03" in body

        # Address-field decode honors ToDS / FromDS bits.
        assert "WIFI_FC1_TODS" in body or "to_ds" in body
        assert "WIFI_FC1_FROMDS" in body or "from_ds" in body

    def test_phase_e_no_promisc_tx_helper(self):
        """Phase-E (Day 48): qemu_wifi_tx_raw_no_promisc exists in the netif
        layer, performs the MMIO TX, and does NOT call qemu_promisc_deliver_eth.
        """
        netif = PROJECT_ROOT / "components" / "esp_wifi_qemu" / "esp_wifi_netif.c"
        src = netif.read_text()
        start = src.find("int qemu_wifi_tx_raw_no_promisc(")
        assert start != -1, "qemu_wifi_tx_raw_no_promisc missing"
        # Find the next function definition to bound the body.
        end = src.find("\n}\n", start)
        assert end != -1
        body = src[start:end]
        assert "WIFI_REG_TX_ADDR" in body and "WIFI_REG_TX_LEN" in body, (
            "no-promisc TX helper must drive the QEMU DMA registers"
        )
        assert "qemu_promisc_deliver_eth" not in body, (
            "no-promisc TX helper must not tap the promiscuous cb"
        )
        # And the prototype is exposed in the private header.
        priv = (PROJECT_ROOT / "components" / "esp_wifi_qemu" / "esp_wifi_private.h").read_text()
        assert "qemu_wifi_tx_raw_no_promisc" in priv

    def test_build_stock_sample_handles_custom_partitions_and_priv_requires(self, tmp_path):
        """Phase-E tooling: build-stock-sample.sh must
           (a) symlink any partitions*.csv from sample root into the wrapper
               project root so CONFIG_PARTITION_TABLE_CUSTOM_FILENAME (relative
               path in sample's sdkconfig.defaults) resolves correctly,
           (b) merge the sample's PRIV_REQUIRES into the wrapper's REQUIRES so
               samples that need extra components (console, fatfs, esp_eth,
               app_trace, unity, ...) link without source modification,
           (c) symlink the sample's idf_component.yml so managed-component
               manifests are honored,
           (d) honor the EXTRA_SDKCONFIG_DEFAULTS env var.
        """
        # Build a synthetic sample tree.
        sample = tmp_path / "fake_sample"
        (sample / "main").mkdir(parents=True)
        (sample / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.16)\n"
            "include($ENV{IDF_PATH}/tools/cmake/project.cmake)\n"
            "project(fake_sample)\n"
        )
        (sample / "sdkconfig.defaults").write_text(
            'CONFIG_PARTITION_TABLE_CUSTOM=y\n'
            'CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions_example.csv"\n'
        )
        (sample / "partitions_example.csv").write_text(
            "# Name, Type, SubType, Offset, Size, Flags\n"
            "nvs, data, nvs, 0x9000, 0x6000,\n"
        )
        (sample / "main" / "fake_main.c").write_text("void app_main(void){}\n")
        (sample / "main" / "CMakeLists.txt").write_text(
            'idf_component_register(SRCS "fake_main.c"\n'
            '    INCLUDE_DIRS "."\n'
            '    PRIV_REQUIRES console fatfs esp_eth app_trace nvs_flash)\n'
        )
        (sample / "main" / "idf_component.yml").write_text(
            "dependencies:\n  idf: '>=5.0'\n"
        )

        # Stub IDF_PATH + idf.py so the script does not actually build.  We
        # only care about wrapper-generation side effects.
        fake_idf = tmp_path / "idf"
        (fake_idf / "tools" / "cmake").mkdir(parents=True)
        (fake_idf / "tools" / "cmake" / "project.cmake").write_text("# stub\n")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "idf.py").write_text("#!/usr/bin/env bash\nexit 0\n")
        (bin_dir / "idf.py").chmod(0o755)

        wrap_dir = sample / "_qemu_wrap_fake_sample"
        env = os.environ.copy()
        env["IDF_PATH"] = str(fake_idf)
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["BUILD_DIR"] = str(sample / "build_qemu")
        # Caller-supplied overlay (path doesn't need to exist for the script
        # to assemble it; idf.py is stubbed and never validates).
        extra_overlay = tmp_path / "extra.sdkconfig"
        extra_overlay.write_text("CONFIG_SNIFFER_PCAP_DESTINATION_MEMORY=y\n")
        env["EXTRA_SDKCONFIG_DEFAULTS"] = str(extra_overlay)

        result = subprocess.run(
            ["bash", str(PROJECT_ROOT / "tools" / "build-stock-sample.sh"), str(sample)],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"build-stock-sample.sh failed:\nSTDOUT={result.stdout}\nSTDERR={result.stderr}"
        )

        # (a) partitions_example.csv must be symlinked into wrapper root.
        wrap_csv = wrap_dir / "partitions_example.csv"
        assert wrap_csv.is_symlink(), (
            f"partitions_example.csv not symlinked into {wrap_dir}"
        )
        assert wrap_csv.resolve() == (sample / "partitions_example.csv").resolve()

        # (b) Wrapper main/CMakeLists.txt must merge PRIV_REQUIRES into REQUIRES
        #     and always include esp_wifi_qemu.
        wrap_main_cmake = (wrap_dir / "main" / "CMakeLists.txt").read_text()
        assert "esp_wifi_qemu" in wrap_main_cmake
        for needed in ("console", "fatfs", "esp_eth", "app_trace", "nvs_flash"):
            assert needed in wrap_main_cmake, (
                f"merged REQUIRES missing '{needed}':\n{wrap_main_cmake}"
            )
        # esp_wifi_qemu must appear exactly once (de-duped).
        assert wrap_main_cmake.count("esp_wifi_qemu") == 1
        # Sources are referenced by absolute path (so the wrapper main dir
        # does not need a .c file copy).
        assert str(sample / "main" / "fake_main.c") in wrap_main_cmake

        # (c) idf_component.yml is symlinked into wrapper main.
        wrap_yml = wrap_dir / "main" / "idf_component.yml"
        assert wrap_yml.is_symlink()
        assert wrap_yml.resolve() == (sample / "main" / "idf_component.yml").resolve()

        # (d) EXTRA_SDKCONFIG_DEFAULTS must end up in the SDKCONFIG_DEFAULTS
        #     CMake invocation.  We grep the script's stdout banner.
        # The script's last `idf.py ... build` invocation is captured because
        # idf.py is a stub.  The SDKCONFIG_DEFAULTS string is assembled in
        # shell; verify it indirectly by re-running the script with bash -x
        # and checking the final command line.
        result_x = subprocess.run(
            ["bash", "-x", str(PROJECT_ROOT / "tools" / "build-stock-sample.sh"), str(sample)],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        combined = result_x.stdout + result_x.stderr
        assert str(extra_overlay) in combined, (
            "EXTRA_SDKCONFIG_DEFAULTS overlay not appended to SDKCONFIG_DEFAULTS"
        )


# ---------------------------------------------------------------------------
# QEMU device integration tests (require runtime environment)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _has_qemu(), reason=_REASON_NO_QEMU)
@pytest.mark.skipif(not _has_flash_images(), reason=_REASON_NO_IMAGES)
class TestQemuWifiDevice:
    """Tests that require a running QEMU with the esp_wifi device."""

    @pytest.mark.skipif(not _qemu_has_wifi_device(), reason=_REASON_NO_WIFI_DEV)
    def test_qemu_enumerates_wifi_device(self):
        """QEMU binary string table must contain 'net.esp.wifi' type name."""
        result = subprocess.run(
            ["strings", str(QEMU_BIN)],
            capture_output=True, text=True, timeout=10,
        )
        assert "net.esp.wifi" in result.stdout, (
            "esp_wifi device type 'net.esp.wifi' not found in QEMU binary. "
            f"Run bash tools/build-qemu.sh. Binary: {QEMU_BIN}"
        )

    @pytest.mark.skipif(not _qemu_has_wifi_device(), reason=_REASON_NO_WIFI_DEV)
    @pytest.mark.skipif(not _has_wifi_sta_firmware(), reason=_REASON_NO_WIFI_STA)
    def test_qemu_wifi_sta_got_ip_mock(self):
        """wifi_sta firmware boots in QEMU, mock wpa_supplicant provides IP,
        serial log must contain 'got ip:10.0.2.15'.

        Uses the project's mock wpa_supplicant daemon — no real Wi-Fi needed.
        """
        import sys
        import tempfile
        sys.path.insert(0, str(PROJECT_ROOT / "tools"))
        from mock_wpa_supplicant import MockWpaSupplicant  # type: ignore

        mock_socket = "/tmp/mock-wpa-qemu-e2e"
        mock_ssid   = "QEMU_TEST"
        mock_ip     = "10.0.2.15"

        # Clean up stale socket
        try:
            os.unlink(mock_socket)
        except OSError:
            pass

        # Build merged flash image in a temp dir
        with tempfile.TemporaryDirectory() as tmpdir:
            flash_img = pathlib.Path(tmpdir) / "wifi_sta_flash.bin"
            _make_flash_image(WIFI_STA_BUILD, flash_img)

            # Start mock wpa_supplicant
            daemon = MockWpaSupplicant(
                ctrl_path=mock_socket,
                ssid=mock_ssid,
                ip=mock_ip,
                scan_delay=0.1,
                connect_delay=0.2,
            )
            daemon.start()
            time.sleep(0.5)  # let socket appear

            # The ESP32 machine creates the net.esp.wifi device internally.
            # The ctrl socket path is communicated via the ESP_WIFI_CTRL_SOCKET
            # environment variable read by the QEMU device at realize-time.
            qemu_env = os.environ.copy()
            qemu_env["ESP_WIFI_CTRL_SOCKET"] = mock_socket

            try:
                qemu_cmd = [
                    str(QEMU_BIN),
                    "-M", "esp32",
                    "-m", "4M",
                    "-nographic",
                    "-drive", f"file={flash_img},if=mtd,format=raw",
                    "-global", "driver=timer.esp32.timg,property=wdt_disable,value=true",
                ]
                result = subprocess.run(
                    qemu_cmd,
                    env=qemu_env,
                    capture_output=True,
                    text=True,
                    timeout=90,
                )
                serial_out = result.stdout + result.stderr
            except subprocess.TimeoutExpired as exc:
                # TimeoutExpired.stdout is always bytes regardless of text=True
                raw_out = (exc.stdout or b"") + (exc.stderr or b"")
                serial_out = raw_out.decode("utf-8", errors="replace") if isinstance(raw_out, bytes) else raw_out
            finally:
                daemon.stop()
                try:
                    os.unlink(mock_socket)
                except OSError:
                    pass

        # Write log for debugging
        log_path = pathlib.Path("/tmp/esp32-wifi-sta-e2e.log")
        log_path.write_text(serial_out if isinstance(serial_out, str) else serial_out.decode("utf-8", errors="replace"))

        assert re.search(r"got ip:[0-9]", serial_out), (
            f"'got ip:' not found in QEMU serial output. "
            f"Log saved to {log_path}.\n"
            f"Last 20 lines:\n" + "\n".join(serial_out.splitlines()[-20:])
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
