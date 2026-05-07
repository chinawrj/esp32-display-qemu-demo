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
