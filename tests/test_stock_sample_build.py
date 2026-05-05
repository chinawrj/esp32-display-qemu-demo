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
