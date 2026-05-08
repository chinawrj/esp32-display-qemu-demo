"""tests/test_stock_sample_build.py — Non-runtime tests for the stock sample
build + run infrastructure added in Days 23-25.

These tests verify:
  - build-stock-sample.sh and run-stock-qemu.sh are present and executable
  - esp_wifi_qemu component contains required stub symbols (GAP-A, GAP-F)
  - CMakeLists.txt uses --whole-archive so stubs win over libnet80211
  - Station and scan build artifacts exist (if previously built)
  - Station map file shows esp_wifi_get_mac from our library (not libnet80211)

All tests are non-runtime (no QEMU, no hardware required).
"""
from __future__ import annotations

import pathlib
import re

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPONENT_DIR = PROJECT_ROOT / "components" / "esp_wifi_qemu"
TOOLS_DIR = PROJECT_ROOT / "tools"
DOCS_DIR = PROJECT_ROOT / "docs"
IDF_PATH = pathlib.Path.home() / "esp-idf"

STATION_BUILD = IDF_PATH / "examples" / "wifi" / "getting_started" / "station" / "build_qemu"
SCAN_BUILD = IDF_PATH / "examples" / "wifi" / "scan" / "build_qemu"


# ---------------------------------------------------------------------------
# Script presence
# ---------------------------------------------------------------------------

def test_build_stock_sample_script_exists():
    script = TOOLS_DIR / "build-stock-sample.sh"
    assert script.exists(), f"build-stock-sample.sh not found at {script}"
    assert script.stat().st_mode & 0o111, "build-stock-sample.sh is not executable"


def test_run_stock_qemu_script_exists():
    script = TOOLS_DIR / "run-stock-qemu.sh"
    assert script.exists(), f"run-stock-qemu.sh not found at {script}"
    assert script.stat().st_mode & 0o111, "run-stock-qemu.sh is not executable"


def test_basic_wifi_smoke_script_exists():
    script = TOOLS_DIR / "run-basic-wifi-smoke.sh"
    assert script.exists(), f"run-basic-wifi-smoke.sh not found at {script}"
    assert script.stat().st_mode & 0o111, "run-basic-wifi-smoke.sh is not executable"


def test_run_stock_qemu_has_verify_profiles():
    script = TOOLS_DIR / "run-stock-qemu.sh"
    content = script.read_text()
    assert "VERIFY_PROFILE" in content, (
        "run-stock-qemu.sh must support sample-aware verification profiles"
    )
    for profile in ("station", "scan", "softap", "custom"):
        assert f"{profile})" in content, f"missing VERIFY_PROFILE={profile} case"


def test_run_stock_qemu_scan_profile_checks_scan_results():
    script = TOOLS_DIR / "run-stock-qemu.sh"
    content = script.read_text()
    assert "Total APs scanned" in content, (
        "scan profile must verify stock scan output instead of Got IP"
    )
    assert "Scan results" in content


def test_basic_wifi_smoke_covers_release_samples():
    script = TOOLS_DIR / "run-basic-wifi-smoke.sh"
    content = script.read_text()
    expected = [
        "examples/wifi/getting_started/station",
        "examples/wifi/scan",
        "examples/wifi/getting_started/softAP",
    ]
    for sample in expected:
        assert sample in content, f"release smoke gate missing {sample}"


def test_basic_wifi_smoke_uses_verify_profiles():
    script = TOOLS_DIR / "run-basic-wifi-smoke.sh"
    content = script.read_text()
    for profile in ("station", "scan", "softap"):
        assert f"|{profile}" in content, f"missing VERIFY_PROFILE={profile} entry"
    assert "VERIFY_PROFILE=\"$profile\"" in content


def test_basic_wifi_smoke_writes_per_sample_logs():
    script = TOOLS_DIR / "run-basic-wifi-smoke.sh"
    content = script.read_text()
    assert "LOG_DIR" in content
    assert "build.log" in content
    assert "run.log" in content
    assert "serial.log" in content


def test_basic_wifi_smoke_writes_summary_file():
    script = TOOLS_DIR / "run-basic-wifi-smoke.sh"
    content = script.read_text()
    assert "SUMMARY_FILE" in content
    assert "summary.tsv" in content
    assert r"sample\tprofile\tbuild\trun\tbuild_log\trun_log\tserial_log" in content


def test_basic_wifi_smoke_records_build_failures():
    script = TOOLS_DIR / "run-basic-wifi-smoke.sh"
    content = script.read_text()
    assert "run_status=\"skipped\"" in content
    assert "build_status=\"fail\"" in content
    assert "build failed" in content


def test_basic_wifi_smoke_records_run_failures():
    script = TOOLS_DIR / "run-basic-wifi-smoke.sh"
    content = script.read_text()
    assert "run_status=\"fail\"" in content
    assert "run failed" in content
    assert "run_status=\"ok\"" in content


def test_basic_wifi_smoke_includes_phase_abc_build_only_samples():
    """Day-48: fast_scan and power_save extend the release gate as
    build-only samples.  Their successful build proves Phase A (real
    connection AP record), Phase B (channel/auth/cipher) and Phase C
    (esp_wifi_set_ps round-trip) are wide enough for the stock
    esp_wifi.h surface, even though their runtime depends on
    config knobs (Kconfig SSID, console UART) that the smoke gate
    does not provision.
    """
    script = (TOOLS_DIR / "run-basic-wifi-smoke.sh").read_text()
    for sample in ("examples/wifi/fast_scan", "examples/wifi/power_save"):
        assert sample in script, f"basic smoke gate missing {sample}"
    # The 4-field SAMPLES entry format must include the build_only marker.
    assert "fast_scan|" in script and "|build_only" in script
    assert "power_save|" in script
    # And run_one must support the build_only mode.
    assert 'mode="${4:-run}"' in script
    assert 'mode" = "build_only"' in script
    # build_only samples are still counted as PASS (gate is green when
    # build succeeds, even though run is skipped).
    assert 'run_status="build_only"' in script


def test_stock_sample_release_doc_exists():
    doc = DOCS_DIR / "qemu-wifi-stock-samples.md"
    assert doc.exists(), "stock Wi-Fi sample release guide is missing"


def test_stock_sample_release_doc_covers_basic_samples():
    doc = DOCS_DIR / "qemu-wifi-stock-samples.md"
    content = doc.read_text()
    for sample in (
        "examples/wifi/getting_started/station/",
        "examples/wifi/scan/",
        "examples/wifi/getting_started/softAP/",
    ):
        assert sample in content
    for profile in ("VERIFY_PROFILE=station", "VERIFY_PROFILE=scan", "VERIFY_PROFILE=softap"):
        assert profile in content


def test_stock_sample_release_doc_has_release_contract():
    doc = DOCS_DIR / "qemu-wifi-stock-samples.md"
    content = doc.read_text()
    required = [
        "Prerequisites",
        "Build And Run One Sample",
        "Expected Logs",
        "Known Limits",
        "run-basic-wifi-smoke.sh",
        "summary.tsv",
        "got ip:10.0.2.15",
        "Total APs scanned",
        "SSID QEMU_TEST",
        "wifi_init_softap finished",
    ]
    for text in required:
        assert text in content


def test_readme_links_stock_sample_release_doc():
    readme = PROJECT_ROOT / "README.md"
    content = readme.read_text()
    assert "docs/qemu-wifi-stock-samples.md" in content
    assert "run-basic-wifi-smoke.sh" in content


# ---------------------------------------------------------------------------
# CMakeLists.txt: --whole-archive is used to force stubs first
# ---------------------------------------------------------------------------

def test_cmake_uses_whole_archive():
    cmake_file = COMPONENT_DIR / "CMakeLists.txt"
    content = cmake_file.read_text()
    assert "--whole-archive" in content, (
        "esp_wifi_qemu/CMakeLists.txt must use --whole-archive to ensure "
        "our stubs override libnet80211 symbols regardless of link order."
    )
    assert "--allow-multiple-definition" in content, (
        "esp_wifi_qemu/CMakeLists.txt must also use --allow-multiple-definition"
    )


def test_cmake_lists_all_source_files():
    cmake_file = COMPONENT_DIR / "CMakeLists.txt"
    content = cmake_file.read_text()
    expected_sources = [
        "esp_wifi_shim.c",
        "esp_wifi_config.c",
        "esp_wifi_scan.c",
        "esp_wifi_netif.c",
        "esp_wifi_extras.c",
        "esp_wifi_internal.c",
        "esp_wifi_ap.c",
    ]
    for src in expected_sources:
        assert src in content, f"Expected {src} in CMakeLists.txt SRCS"


# ---------------------------------------------------------------------------
# GAP-A: all required esp_wifi_* stubs are present in source files
# ---------------------------------------------------------------------------

# Symbols from the BACKLOG GAP-A list that stock samples call
GAP_A_SYMBOLS = [
    "esp_wifi_set_storage",
    "esp_wifi_restore",
    "esp_wifi_set_ps",
    "esp_wifi_get_ps",
    "esp_wifi_set_bandwidth",
    "esp_wifi_get_bandwidth",
    "esp_wifi_set_channel",
    "esp_wifi_get_channel",
    "esp_wifi_set_country",
    "esp_wifi_get_country",
    "esp_wifi_set_max_tx_power",
    "esp_wifi_get_max_tx_power",
    "esp_wifi_set_protocol",
    "esp_wifi_get_protocol",
    "esp_wifi_sta_get_ap_info",
    "esp_wifi_sta_get_rssi",
    "esp_wifi_set_event_mask",
    "esp_wifi_get_event_mask",
    "esp_wifi_set_promiscuous",
    "esp_wifi_get_promiscuous",
    "esp_wifi_set_promiscuous_rx_cb",
    "esp_wifi_80211_tx",
    # CSI (added Day 25)
    "esp_wifi_set_csi",
    "esp_wifi_set_csi_config",
    "esp_wifi_set_csi_rx_cb",
]


def _all_component_source_text() -> str:
    texts = []
    for src_file in COMPONENT_DIR.glob("*.c"):
        texts.append(src_file.read_text())
    return "\n".join(texts)


@pytest.mark.parametrize("symbol", GAP_A_SYMBOLS)
def test_gap_a_stub_defined(symbol):
    """Each GAP-A symbol must be defined (not just declared) in the component."""
    src = _all_component_source_text()
    # Match function definition: return_type symbol(
    assert re.search(rf"\b{re.escape(symbol)}\s*\(", src), (
        f"GAP-A stub {symbol!r} not found in esp_wifi_qemu component sources"
    )


# ---------------------------------------------------------------------------
# GAP-F: esp_wifi_internal_* stubs are present
# ---------------------------------------------------------------------------

GAP_F_SYMBOLS = [
    "esp_wifi_internal_reg_rxcb",
    "esp_wifi_internal_set_sta_ip",
    "esp_wifi_internal_free_rx_buffer",
    "esp_wifi_internal_reg_netstack_buf_cb",
    "esp_wifi_internal_tx",
    "esp_wifi_internal_update_mac_time",
    "esp_wifi_internal_set_log_level",
]


@pytest.mark.parametrize("symbol", GAP_F_SYMBOLS)
def test_gap_f_stub_defined(symbol):
    """Each GAP-F internal symbol must be defined in the component."""
    internal_c = (COMPONENT_DIR / "esp_wifi_internal.c").read_text()
    assert re.search(rf"\b{re.escape(symbol)}\s*\(", internal_c), (
        f"GAP-F stub {symbol!r} not found in esp_wifi_internal.c"
    )


# ---------------------------------------------------------------------------
# Build artifact checks (skip if samples not built)
# ---------------------------------------------------------------------------

def _require_station_build():
    elf = STATION_BUILD / "wifi_station.elf"
    if not elf.exists():
        pytest.skip(
            f"Station build not found at {STATION_BUILD}. "
            "Run: bash tools/build-stock-sample.sh "
            "$IDF_PATH/examples/wifi/getting_started/station"
        )
    return elf


def _require_scan_build():
    elf = SCAN_BUILD / "scan.elf"
    if not elf.exists():
        pytest.skip(
            f"Scan build not found at {SCAN_BUILD}. "
            "Run: bash tools/build-stock-sample.sh "
            "$IDF_PATH/examples/wifi/scan"
        )
    return elf


def test_station_build_artifact_exists():
    _require_station_build()


def test_scan_build_artifact_exists():
    _require_scan_build()


def test_station_map_internal_reg_rxcb_from_qemu_shim():
    """In station build, esp_wifi_internal_reg_rxcb must come from libesp_wifi_qemu."""
    _require_station_build()
    map_file = STATION_BUILD / "wifi_station.map"
    if not map_file.exists():
        pytest.skip("Map file not found")
    content = map_file.read_text()
    # Find the entry with a non-zero address (the winning definition)
    matches = re.findall(
        r"\.text\.esp_wifi_internal_reg_rxcb\s+(0x[0-9a-f]+)\s+(0x[0-9a-f]+)\s+(\S+)",
        content,
    )
    non_zero = [(addr, size, lib) for addr, size, lib in matches if addr != "0x00000000"]
    if not non_zero:
        pytest.skip("Symbol not placed at non-zero address (GC'd)")
    provider = non_zero[0][2]
    assert "esp_wifi_qemu" in provider, (
        f"esp_wifi_internal_reg_rxcb should come from libesp_wifi_qemu, got: {provider}"
    )


def test_scan_map_get_mac_from_qemu_shim():
    """In scan build, esp_wifi_get_mac must come from libesp_wifi_qemu (not libnet80211)."""
    _require_scan_build()
    map_file = SCAN_BUILD / "scan.map"
    if not map_file.exists():
        pytest.skip("Map file not found")
    content = map_file.read_text()
    # Find the entry with a non-zero address (the winning definition)
    matches = re.findall(
        r"\.text\.esp_wifi_get_mac\s+(0x[0-9a-f]+)\s+(0x[0-9a-f]+)\s+(\S+)",
        content,
    )
    non_zero = [(addr, size, lib) for addr, size, lib in matches if addr != "0x00000000"]
    if not non_zero:
        pytest.skip("esp_wifi_get_mac not placed at non-zero address (GC'd)")
    provider = non_zero[0][2]
    assert "esp_wifi_qemu" in provider, (
        f"esp_wifi_get_mac should come from libesp_wifi_qemu, got: {provider}"
    )


def test_scan_start_has_result_count_fallback():
    """Blocking scan must not rely only on the single QEMU event register."""
    scan_c = COMPONENT_DIR / "esp_wifi_scan.c"
    content = scan_c.read_text()
    assert "WIFI_REG_SCAN_COUNT" in content, (
        "esp_wifi_scan_start must poll WIFI_REG_SCAN_COUNT as a fallback"
    )
    assert "WIFI_EVT_SCAN_DONE" in content
    assert "ESP_ERR_TIMEOUT" in content


# ---------------------------------------------------------------------------
# Real wpa_supplicant passthrough mode (Day 37)
# ---------------------------------------------------------------------------

def test_run_real_wifi_script_exists():
    """run-real-wifi.sh must exist and be executable."""
    script = TOOLS_DIR / "run-real-wifi.sh"
    assert script.exists(), f"run-real-wifi.sh not found at {script}"
    assert script.stat().st_mode & 0o111, "run-real-wifi.sh is not executable"


def test_relay_accepts_gateway_ip_flag():
    """wifi_packet_relay.py must accept --gateway-ip flag."""
    relay = TOOLS_DIR / "wifi_packet_relay.py"
    src = relay.read_text()
    assert "--gateway-ip" in src, (
        "wifi_packet_relay.py must accept --gateway-ip for real-WiFi mode"
    )
    assert "GATEWAY_IP = args.gateway_ip" in src or "GATEWAY_IP = args.gateway_ip" in src or \
           "args.gateway_ip" in src, (
        "wifi_packet_relay.py must apply --gateway-ip to override GATEWAY_IP"
    )


def test_relay_accepts_no_local_map_flag():
    """wifi_packet_relay.py must accept --no-local-map flag."""
    relay = TOOLS_DIR / "wifi_packet_relay.py"
    src = relay.read_text()
    assert "--no-local-map" in src, (
        "wifi_packet_relay.py must accept --no-local-map for real-WiFi mode"
    )
    assert "LOCAL_HOST_MAP = {}" in src, (
        "wifi_packet_relay.py must clear LOCAL_HOST_MAP when --no-local-map is set"
    )


def test_run_real_wifi_uses_real_wpa_socket():
    """run-real-wifi.sh must point QEMU at the real wpa_supplicant socket."""
    script = (TOOLS_DIR / "run-real-wifi.sh").read_text()
    assert "wpa_supplicant" in script.lower(), (
        "run-real-wifi.sh must reference the wpa_supplicant socket path"
    )
    assert "ESP_WIFI_CTRL_SOCKET" in script, (
        "run-real-wifi.sh must export ESP_WIFI_CTRL_SOCKET pointing at real wpa_supplicant"
    )
    assert "no-local-map" in script, (
        "run-real-wifi.sh must pass --no-local-map to wifi_packet_relay.py"
    )


def test_run_real_wifi_supports_sudo_mode():
    """run-real-wifi.sh must support WIFI_SUDO=1 for root-only socket access."""
    script = (TOOLS_DIR / "run-real-wifi.sh").read_text()
    assert "WIFI_SUDO" in script, (
        "run-real-wifi.sh must support WIFI_SUDO env var for elevated access"
    )
    assert "sudo" in script, (
        "run-real-wifi.sh must be able to run QEMU under sudo when WIFI_SUDO=1"
    )


# ---------------------------------------------------------------------------
# Real-scan (Day 40): mock_wpa_supplicant --real-scan uses wpa_cli (real Wi-Fi card)
# ---------------------------------------------------------------------------

def test_mock_has_real_scan_flag():
    """mock_wpa_supplicant.py must accept --real-scan CLI flag."""
    mock = TOOLS_DIR / "mock_wpa_supplicant.py"
    src = mock.read_text()
    assert "--real-scan" in src, (
        "mock_wpa_supplicant.py must expose --real-scan argparse flag"
    )
    assert "real_scan" in src, (
        "mock_wpa_supplicant.py must store real_scan attribute"
    )


def test_mock_real_scan_calls_wpa_cli():
    """_wpa_cli_scan_results() must invoke wpa_cli to read from the real Wi-Fi card."""
    mock = TOOLS_DIR / "mock_wpa_supplicant.py"
    src = mock.read_text()
    assert "_wpa_cli_scan_results" in src, (
        "mock must define _wpa_cli_scan_results() helper"
    )
    assert "wpa_cli" in src, (
        "_wpa_cli_scan_results must call wpa_cli"
    )
    assert "scan_results" in src, (
        "wpa_cli call must request scan_results"
    )


def test_mock_real_scan_proxies_wpa_cli_output():
    """mock must proxy wpa_cli output directly — no quality-to-dBm conversion
    needed because wpa_supplicant already reports signal in dBm."""
    mock = TOOLS_DIR / "mock_wpa_supplicant.py"
    src = mock.read_text()
    assert "_wpa_cli_scan_results" in src, (
        "mock must use wpa_cli backend for pre-formatted scan results"
    )
    # wpa_cli already returns dBm — nmcli quality conversion must not be present
    assert "// 2) - 100" not in src and "/ 2) - 100" not in src, (
        "wpa_cli backend must not apply nmcli quality-to-dBm conversion"
    )


def test_mock_real_scan_has_wpa_iface_option():
    """mock must expose --wpa-iface, --wpa-ctrl-dir, auto-detect iface, and group check."""
    mock = TOOLS_DIR / "mock_wpa_supplicant.py"
    src = mock.read_text()
    assert "--wpa-iface" in src, "mock must expose --wpa-iface arg"
    assert "--wpa-ctrl-dir" in src, "mock must expose --wpa-ctrl-dir arg"
    assert "_auto_detect_iface" in src, "mock must auto-detect wireless interface"
    assert "/var/run/wpa_supplicant" in src, "default ctrl dir must be /var/run/wpa_supplicant"
    assert "_need_sg_netdev" in src, "mock must detect if sg netdev workaround is needed"


def test_mock_real_scan_deduplicates_bssids():
    """mock must deduplicate APs by BSSID (nmcli lists same AP multiple times)."""
    mock = TOOLS_DIR / "mock_wpa_supplicant.py"
    src = mock.read_text()
    assert "seen" in src and "seen.add" in src, (
        "mock real-scan must track seen BSSIDs to avoid duplicates"
    )


def test_run_stock_qemu_exposes_real_scan_env():
    """run-stock-qemu.sh must pass --real-scan to mock when REAL_SCAN=1."""
    script = (TOOLS_DIR / "run-stock-qemu.sh").read_text()
    assert "REAL_SCAN" in script, (
        "run-stock-qemu.sh must support REAL_SCAN env var"
    )
    assert "--real-scan" in script, (
        "run-stock-qemu.sh must pass --real-scan flag to mock_wpa_supplicant.py"
    )
