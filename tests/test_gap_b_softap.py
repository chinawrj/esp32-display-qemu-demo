"""tests/test_gap_b_softap.py — Non-runtime tests for GAP-B (SoftAP support).

These tests verify:
  - esp_wifi_ap.c is present with the required stub symbols
  - esp_wifi_shim.c handles AP mode in set_mode / start / stop
  - esp_wifi_config.c handles WIFI_IF_AP in set_config / get_config / get_mac
  - CMakeLists.txt lists esp_wifi_ap.c as a source
  - SoftAP build artifact exists (if previously built)
  - SoftAP map file shows our stubs win over libnet80211

All tests are non-runtime (no QEMU, no hardware required).
"""
from __future__ import annotations

import pathlib
import re

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPONENT_DIR = PROJECT_ROOT / "components" / "esp_wifi_qemu"
IDF_PATH = pathlib.Path.home() / "esp-idf"
SOFTAP_BUILD = IDF_PATH / "examples" / "wifi" / "getting_started" / "softAP" / "build_qemu"


# ---------------------------------------------------------------------------
# GAP-B source presence: esp_wifi_ap.c
# ---------------------------------------------------------------------------

def test_esp_wifi_ap_c_exists():
    ap_c = COMPONENT_DIR / "esp_wifi_ap.c"
    assert ap_c.exists(), "esp_wifi_ap.c not found in esp_wifi_qemu component"


GAP_B_SYMBOLS = [
    "esp_wifi_ap_get_sta_list",
    "esp_wifi_deauth_sta",
    "esp_wifi_ap_get_sta_aid",
]


@pytest.mark.parametrize("symbol", GAP_B_SYMBOLS)
def test_gap_b_stub_defined(symbol):
    """Each GAP-B symbol must be defined in esp_wifi_ap.c."""
    ap_c = (COMPONENT_DIR / "esp_wifi_ap.c").read_text()
    assert re.search(rf"\b{re.escape(symbol)}\s*\(", ap_c), (
        f"GAP-B stub {symbol!r} not found in esp_wifi_ap.c"
    )


def test_cmake_lists_esp_wifi_ap_c():
    cmake = (COMPONENT_DIR / "CMakeLists.txt").read_text()
    assert "esp_wifi_ap.c" in cmake, (
        "esp_wifi_ap.c must be listed in CMakeLists.txt SRCS"
    )


# ---------------------------------------------------------------------------
# GAP-B shim: set_mode accepts AP modes
# ---------------------------------------------------------------------------

def test_shim_accepts_wifi_mode_ap():
    """esp_wifi_shim.c must not reject WIFI_MODE_AP."""
    shim = (COMPONENT_DIR / "esp_wifi_shim.c").read_text()
    # Old code returned ERR_NOT_SUPPORTED for non-STA modes; confirm it's gone.
    assert "only STA mode supported" not in shim, (
        "esp_wifi_shim.c still rejects non-STA modes — GAP-B fix not applied"
    )


def test_shim_start_handles_ap_mode():
    """esp_wifi_start() must have an AP-mode branch that emits WIFI_EVENT_AP_START."""
    shim = (COMPONENT_DIR / "esp_wifi_shim.c").read_text()
    assert "WIFI_EVENT_AP_START" in shim, (
        "esp_wifi_start() must emit WIFI_EVENT_AP_START for AP mode"
    )


def test_shim_stop_handles_ap_mode():
    """esp_wifi_stop() must have an AP-mode branch that emits WIFI_EVENT_AP_STOP."""
    shim = (COMPONENT_DIR / "esp_wifi_shim.c").read_text()
    assert "WIFI_EVENT_AP_STOP" in shim, (
        "esp_wifi_stop() must emit WIFI_EVENT_AP_STOP for AP mode"
    )


# ---------------------------------------------------------------------------
# GAP-B config: set_config / get_config / get_mac handle WIFI_IF_AP
# ---------------------------------------------------------------------------

def test_config_handles_wifi_if_ap_set():
    """esp_wifi_set_config must accept WIFI_IF_AP."""
    config_c = (COMPONENT_DIR / "esp_wifi_config.c").read_text()
    assert "WIFI_IF_AP" in config_c, (
        "esp_wifi_config.c must handle WIFI_IF_AP in set_config/get_config"
    )


def test_config_ap_state_variable_exists():
    """esp_wifi_config.c must have an s_ap_cfg state variable."""
    config_c = (COMPONENT_DIR / "esp_wifi_config.c").read_text()
    assert "s_ap_cfg" in config_c, (
        "esp_wifi_config.c must define s_ap_cfg for AP configuration storage"
    )


def test_get_mac_handles_wifi_if_ap():
    """esp_wifi_get_mac must handle WIFI_IF_AP (return derived AP MAC)."""
    config_c = (COMPONENT_DIR / "esp_wifi_config.c").read_text()
    # Check that get_mac has AP handling
    assert re.search(r"ifx\s*==\s*WIFI_IF_AP", config_c), (
        "esp_wifi_get_mac must handle WIFI_IF_AP"
    )


# ---------------------------------------------------------------------------
# Build artifact checks (skip if sample not built)
# ---------------------------------------------------------------------------

def _require_softap_build():
    # The wrapper builds into softAP/build_qemu; ELF name matches project name
    elfs = list(SOFTAP_BUILD.glob("*.elf")) if SOFTAP_BUILD.exists() else []
    if not elfs:
        pytest.skip(
            f"SoftAP build not found at {SOFTAP_BUILD}. "
            "Run: bash tools/build-stock-sample.sh "
            "$IDF_PATH/examples/wifi/getting_started/softAP"
        )
    return elfs[0]


def test_softap_build_artifact_exists():
    """SoftAP ELF must exist after build."""
    _require_softap_build()


def test_softap_build_has_map_file():
    """SoftAP map file must exist alongside the ELF."""
    elf = _require_softap_build()
    map_file = elf.with_suffix(".map")
    assert map_file.exists(), f"Map file not found: {map_file}"


def test_softap_map_set_mode_from_qemu_shim():
    """In softAP build, esp_wifi_set_mode must come from libesp_wifi_qemu."""
    elf = _require_softap_build()
    map_file = elf.with_suffix(".map")
    if not map_file.exists():
        pytest.skip("Map file not found")
    content = map_file.read_text()
    matches = re.findall(
        r"\.text\.esp_wifi_set_mode\s+(0x[0-9a-f]+)\s+(0x[0-9a-f]+)\s+(\S+)",
        content,
    )
    non_zero = [(addr, size, lib) for addr, size, lib in matches if addr != "0x00000000"]
    if not non_zero:
        pytest.skip("esp_wifi_set_mode not placed at non-zero address (GC'd)")
    provider = non_zero[0][2]
    assert "esp_wifi_qemu" in provider, (
        f"esp_wifi_set_mode should come from libesp_wifi_qemu, got: {provider}"
    )


def test_softap_map_ap_get_sta_list_from_qemu_shim():
    """In softAP build, esp_wifi_ap_get_sta_list must come from libesp_wifi_qemu."""
    elf = _require_softap_build()
    map_file = elf.with_suffix(".map")
    if not map_file.exists():
        pytest.skip("Map file not found")
    content = map_file.read_text()
    matches = re.findall(
        r"\.text\.esp_wifi_ap_get_sta_list\s+(0x[0-9a-f]+)\s+(0x[0-9a-f]+)\s+(\S+)",
        content,
    )
    non_zero = [(addr, size, lib) for addr, size, lib in matches if addr != "0x00000000"]
    if not non_zero:
        pytest.skip("esp_wifi_ap_get_sta_list not placed at non-zero address (GC'd)")
    provider = non_zero[0][2]
    assert "esp_wifi_qemu" in provider, (
        f"esp_wifi_ap_get_sta_list should come from libesp_wifi_qemu, got: {provider}"
    )
