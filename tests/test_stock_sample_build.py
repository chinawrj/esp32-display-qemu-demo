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

import os
import pathlib
import re
import subprocess

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


def test_basic_wifi_smoke_supports_build_only_mode():
    """Day-48: the basic-wifi-smoke gate supports a `build_only` profile
    for samples whose runtime depends on inputs the harness does not
    provision (console UART, real upstream APs, etc.).  This test pins
    the harness contract independent of which specific samples are
    currently classified as build_only — sample-specific assertions
    live in dedicated tests below.

    Day-50: fast_scan was promoted out of build-only to runtime once
    the startup-scan-vs-CMD_CONNECT race was fixed and the sample's
    SSID/password were wired through the EXTRA_SDKCONFIG_DEFAULTS
    overlay channel.

    Day-51: power_save was promoted out of build-only to runtime via
    the same overlay playbook.  See
    `test_basic_wifi_smoke_promotes_power_save_to_runtime`.
    """
    script = (TOOLS_DIR / "run-basic-wifi-smoke.sh").read_text()
    # The 4-field SAMPLES entry format must still include a build_only
    # marker (used today by softap_sta and roaming_app).
    assert "|build_only" in script
    # And run_one must support the build_only mode.
    assert 'mode="${4:-run}"' in script
    assert 'mode" = "build_only"' in script
    # build_only samples are still counted as PASS (gate is green when
    # build succeeds, even though run is skipped).
    assert 'run_status="build_only"' in script


def test_basic_wifi_smoke_promotes_power_save_to_runtime():
    """Day-51: power_save promoted from build-only (Day 48) to runtime,
    mirroring the Day-50 fast_scan playbook.

    The sample's runtime blocker was the Kconfig-default SSID
    ("myssid"), which we now override via the EXTRA_SDKCONFIG_DEFAULTS
    overlay channel to point at the mock supplicant's QEMU_TEST AP.
    EXAMPLE_GET_AP_INFO_FROM_STDIN defaults to `n` (no console UART
    input needed) and Phase C
    (`esp_wifi_set_ps` + `esp_wifi_set_inactive_time` round-trip) is
    already implemented end-to-end, so promotion is purely an overlay
    + smoke-script change with **zero source diff** to the upstream
    sample.  This regression gates all three of those facts.
    """
    script = (TOOLS_DIR / "run-basic-wifi-smoke.sh").read_text()
    # 1. Smoke gate runtime entry + overlay wiring.
    assert ("power_save|${IDF_PATH}/examples/wifi/power_save|station|run|"
            "${PROJECT_DIR}/tools/sample-overlays/power_save.sdkconfig"
            ) in script, "power_save must be a runtime entry with overlay"
    # power_save must NOT also be in the build_only list.
    assert "power_save|${IDF_PATH}/examples/wifi/power_save|station|build_only" not in script

    # 2. run_one must accept the 5th overlay field and forward it.
    assert 'overlay="${5:-}"' in script
    assert 'EXTRA_SDKCONFIG_DEFAULTS="$overlay"' in script

    # 3. The overlay file must exist and provision the QEMU_TEST SSID.
    overlay = TOOLS_DIR / "sample-overlays" / "power_save.sdkconfig"
    assert overlay.exists(), "power_save sdkconfig overlay missing"
    overlay_text = overlay.read_text()
    assert 'CONFIG_EXAMPLE_WIFI_SSID="QEMU_TEST"' in overlay_text
    assert 'CONFIG_EXAMPLE_WIFI_PASSWORD=' in overlay_text


def test_basic_wifi_smoke_promotes_fast_scan_to_runtime():
    """Day-50: fast_scan promoted from build-only to runtime.  This
    requires three things to be in place:

    1. The firmware-shim startup-scan must be MMIO-written BEFORE the
       STA_START event is posted, so the app's STA_START handler (which
       calls esp_wifi_connect()) cannot land CMD_CONNECT on the device
       before the housekeeping CMD_SCAN.

    2. The device-side WIFI_CMD_SCAN handler must defensively drop a
       redundant scan whenever a connect flow is already in-flight, so
       no future race can re-assert scan_only=true on top of an active
       ADD_NETWORK / SELECT_NETWORK chain.

    3. The smoke gate must merge the sample's SSID/password into the
       sdkconfig channel via the EXTRA_SDKCONFIG_DEFAULTS overlay (the
       only allowed deviation from byte-identical-source).

    All three are asserted here as a single regression gate.
    """
    # 1. Firmware shim ordering.
    shim = (PROJECT_ROOT / "components" / "esp_wifi_qemu" /
            "esp_wifi_shim.c").read_text()
    assert "wifi_qemu_write(WIFI_REG_CMD, WIFI_CMD_SCAN);\n            ESP_LOGI(TAG, \"startup scan initiated\");\n            esp_event_post(WIFI_EVENT, WIFI_EVENT_STA_START," in shim, (
        "esp_wifi_start must MMIO-write CMD_SCAN before posting STA_START"
    )

    # 2. Device-side defensive guard.
    device = (PROJECT_ROOT / "tools" / "qemu-src-patches" / "hw" / "net" /
              "esp_wifi.c").read_text()
    assert "CMD_SCAN dropped" in device or (
        "s->status == WIFI_STATE_STARTED &&" in device
        and "s->conn_state != WPA_CONN_NONE &&" in device
        and "s->conn_state != WPA_CONN_IDLE" in device
    ), "device CMD_SCAN handler must drop a redundant scan when conn_state is not IDLE/NONE"

    # 3. Smoke gate runtime entry + overlay wiring.
    script = (TOOLS_DIR / "run-basic-wifi-smoke.sh").read_text()
    assert ("fast_scan|${IDF_PATH}/examples/wifi/fast_scan|station|run|"
            "${PROJECT_DIR}/tools/sample-overlays/fast_scan.sdkconfig"
            ) in script, "fast_scan must be a runtime entry with overlay"
    # run_one must accept the 5th overlay field and forward it.
    assert 'overlay="${5:-}"' in script
    assert 'EXTRA_SDKCONFIG_DEFAULTS="$overlay"' in script
    # The overlay file must exist and provision the QEMU_TEST SSID.
    overlay = TOOLS_DIR / "sample-overlays" / "fast_scan.sdkconfig"
    assert overlay.exists(), "fast_scan sdkconfig overlay missing"
    overlay_text = overlay.read_text()
    assert 'CONFIG_EXAMPLE_WIFI_SSID="QEMU_TEST"' in overlay_text
    assert 'CONFIG_EXAMPLE_WIFI_PASSWORD=' in overlay_text


def test_basic_wifi_smoke_includes_softap_sta_build_only():
    """Day-49: softap_sta is the only stock wifi example that runs APSTA
    mode (STA + SoftAP simultaneously) in a single binary.  Building it
    against the QEMU overlay with zero source diff proves Phase A + B +
    C + D-1 + D-2 all link together cleanly for the same firmware image.
    Runtime is gated on a configured upstream SSID and on lwIP NAPT,
    which the smoke gate does not provision today, so the entry is
    build_only.
    """
    script = (TOOLS_DIR / "run-basic-wifi-smoke.sh").read_text()
    assert "examples/wifi/softap_sta" in script, (
        "basic smoke gate missing softap_sta"
    )
    # 4-field entry, build_only mode, softap profile.
    assert "softap_sta|" in script
    assert "softap_sta|${IDF_PATH}/examples/wifi/softap_sta|softap|build_only" in script


def test_basic_wifi_smoke_includes_roaming_app_build_only():
    """Day-49: roaming_app exercises the IDF roaming library
    (BSS-Transition-Management hooks, RSSI thresholds) on top of the
    same Phase-A station surface as getting_started/station. Building
    it drop-in proves our QEMU overlay does not break the roaming
    subsystem's link expectations even when the firmware also pulls
    in `WIFI_ROAMING_ENABLE` glue code. Runtime would need an
    802.11k/v-capable AP cluster which neither the smoke gate nor a
    single mock_wpa_supplicant can stand up.
    """
    script = (TOOLS_DIR / "run-basic-wifi-smoke.sh").read_text()
    assert "examples/wifi/roaming/roaming_app" in script, (
        "basic smoke gate missing roaming_app"
    )
    assert "roaming_app|" in script
    assert ("roaming_app|${IDF_PATH}/examples/wifi/roaming/roaming_app|"
            "station|build_only") in script


def test_basic_wifi_smoke_includes_day52_wide_build_only_sweep():
    """Day-52: extend build-only stock-sample coverage to wps,
    smart_config, ftm, espnow, wps_softap_registrar, and itwt — the
    remaining ESP-IDF Wi-Fi samples that *link* clean today against the
    QEMU shim (after Day-52 added esp_wifi_sta_itwt_setup /
    esp_wifi_sta_twt_config stubs for the non-HE esp32 target).

    Build coverage is the cheapest unambiguous regression gate against
    silent shim symbol drops: every sample below pulls in a different
    Wi-Fi feature subsystem (WPS-PBC, ESPTOUCH, FTM, ESP-NOW, WPS
    Registrar, iTWT) and any future esp_wifi_qemu/* edit that loses a
    public symbol surfaces here as a link error before it reaches
    runtime.
    """
    script = (TOOLS_DIR / "run-basic-wifi-smoke.sh").read_text()
    expected = [
        "wps|${IDF_PATH}/examples/wifi/wps|station|build_only",
        "smart_config|${IDF_PATH}/examples/wifi/smart_config|station|build_only",
        "ftm|${IDF_PATH}/examples/wifi/ftm|station|build_only",
        "espnow|${IDF_PATH}/examples/wifi/espnow|station|build_only",
        ("wps_softap_registrar|${IDF_PATH}/examples/wifi/wps_softap_registrar|"
         "softap|build_only"),
        "itwt|${IDF_PATH}/examples/wifi/itwt|station|build_only",
    ]
    for entry in expected:
        assert entry in script, (
            f"Day-52 build-only sweep missing {entry!r}"
        )


def test_basic_wifi_smoke_includes_day54_protocol_samples():
    """Day-54: drop-in build-only coverage extends beyond
    `examples/wifi/**`.  Every sample below uses `example_connect()`
    (protocol_examples_common) to bring up Wi-Fi station via the QEMU
    shim and then opens UDP/TCP sockets or HTTP/SNTP clients on top
    of the lwIP stack.  Build success here is the strongest evidence
    that the lwIP-over-QEMU-Wi-Fi data plane links cleanly for every
    common socket family with zero source diff.
    """
    script = (TOOLS_DIR / "run-basic-wifi-smoke.sh").read_text()
    for entry in (
        "tcp_client|${IDF_PATH}/examples/protocols/sockets/tcp_client|station|build_only",
        "tcp_server|${IDF_PATH}/examples/protocols/sockets/tcp_server|station|build_only",
        "udp_client|${IDF_PATH}/examples/protocols/sockets/udp_client|station|build_only",
        "udp_server|${IDF_PATH}/examples/protocols/sockets/udp_server|station|build_only",
        "http_request|${IDF_PATH}/examples/protocols/http_request|station|build_only",
        "sntp|${IDF_PATH}/examples/protocols/sntp|station|build_only",
    ):
        assert entry in script, f"Day-54 protocol-sample smoke entry missing: {entry!r}"


def test_build_stock_sample_keyword_before_close_paren():
    """Day-54 FB-026 regression gate: the wrap-script awk extractor
    must check the component-register keyword boundary BEFORE the
    close-paren boundary.  A continuation line like
    `INCLUDE_DIRS ".")` matches both regexes; if `)` wins first the
    extractor leaks the other keyword value into the current keyword
    argument list (which broke protocols/sockets/udp_client whose
    main/CMakeLists.txt has PRIV_REQUIRES ${priv_requires} then
    INCLUDE_DIRS "." on consecutive lines).  Pin the order so a
    future refactor cannot silently regress udp_client and friends.
    """
    script = (TOOLS_DIR / "build-stock-sample.sh").read_text()
    # Locate both branches of the awk extractor (in_kw continuation
    # branch and the initial-match branch).  In each, the keyword
    # regex must appear before the `\\)` regex.
    in_kw_idx = script.find("if (in_kw) {")
    assert in_kw_idx > 0, "extract_requires_kw continuation branch missing"
    end_idx = script.find("re = \"(^|[^A-Z_])\" kw", in_kw_idx)
    assert end_idx > in_kw_idx, "extract_requires_kw initial-match branch missing"
    cont_branch = script[in_kw_idx:end_idx]
    kw_pos = cont_branch.find("EMBED_TXTFILES|KCONFIG|KCONFIG_PROJBUILD")
    paren_pos = cont_branch.find("/\\)/")
    assert kw_pos > 0 and paren_pos > 0, (
        "continuation branch must check both keyword and close-paren"
    )
    assert kw_pos < paren_pos, (
        "FB-026: keyword-boundary check must come BEFORE close-paren "
        "check in the in_kw continuation branch"
    )
    init_branch = script[end_idx:script.find("' \"$2\"", end_idx)]
    kw_pos = init_branch.find("EMBED_TXTFILES|KCONFIG|KCONFIG_PROJBUILD")
    paren_pos = init_branch.find("/\\)/")
    assert kw_pos > 0 and paren_pos > 0, (
        "initial-match branch must check both keyword and close-paren"
    )
    assert kw_pos < paren_pos, (
        "FB-026: keyword-boundary check must come BEFORE close-paren "
        "check in the initial-match branch"
    )


def test_basic_wifi_smoke_includes_day55_protocol_samples():
    """Day-55 extends drop-in coverage further into
    `examples/protocols/**`.  `mqtt/tcp` exercises the esp_mqtt_client
    public API end-to-end over plain TCP; `https_request` was unblocked
    by Day-55's FB-028 fix (INCLUDE_DIRS subdir propagation) because
    its main/CMakeLists.txt lists `INCLUDE_DIRS "include"` to expose
    main/include/time_sync.h to its companion .c sources.
    """
    script = (TOOLS_DIR / "run-basic-wifi-smoke.sh").read_text()
    for entry in (
        "mqtt_tcp|${IDF_PATH}/examples/protocols/mqtt/tcp|station|build_only",
        "https_request|${IDF_PATH}/examples/protocols/https_request|station|build_only",
    ):
        assert entry in script, f"Day-55 protocol-sample smoke entry missing: {entry!r}"


def test_build_stock_sample_propagates_include_dirs_subdirs(tmp_path):
    """Day-55 FB-028 regression gate: any non-`.` entry in the
    original sample's `INCLUDE_DIRS` keyword list must be re-emitted
    in the wrap component's CMakeLists with an absolute path under
    SAMPLE_MAIN_DIR.  Without this, samples like https_request (whose
    main/CMakeLists.txt declares `INCLUDE_DIRS "include"`) cannot
    locate headers under main/include/ from main/*.c.
    """
    # Build a synthetic sample tree with a custom INCLUDE_DIRS subdir.
    sample = tmp_path / "fake_sample"
    main_dir = sample / "main"
    inc_dir = main_dir / "include"
    inc_dir.mkdir(parents=True)
    (main_dir / "fake.c").write_text("/* fake */\n")
    (inc_dir / "fake_priv.h").write_text("/* fake header */\n")
    (sample / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.16)\n"
        "include($ENV{IDF_PATH}/tools/cmake/project.cmake)\n"
        "project(fake_sample)\n"
    )
    (main_dir / "CMakeLists.txt").write_text(
        'idf_component_register(SRCS "fake.c"\n'
        '                       INCLUDE_DIRS "include")\n'
    )
    # Stub idf.py so the wrap-script generates CMakeLists without
    # actually invoking a real build.
    stub_idf = tmp_path / "idf" / "tools" / "idf.py"
    stub_idf.parent.mkdir(parents=True)
    stub_idf.write_text("#!/usr/bin/env bash\nexit 0\n")
    stub_idf.chmod(0o755)
    env = os.environ.copy()
    env["IDF_PATH"] = str(tmp_path / "idf")
    env["PATH"] = f"{stub_idf.parent}:{env.get('PATH','')}"
    env["BUILD_DIR"] = str(sample / "build_qemu")
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
    wrap_cmake = sample / "_qemu_wrap_fake_sample" / "main" / "CMakeLists.txt"
    assert wrap_cmake.is_file(), "wrap main CMakeLists.txt not generated"
    body = wrap_cmake.read_text()
    expected_inc = str(main_dir / "include")
    assert expected_inc in body, (
        f"FB-028: wrap CMakeLists missing absolute INCLUDE_DIRS subdir.\n"
        f"Expected '{expected_inc}' in:\n{body}"
    )


def test_basic_wifi_smoke_includes_day56_protocol_samples():
    """Day-56 (FB-027) lands a probe-configure helper that runs
    `idf.py reconfigure` on the unmodified sample and reads
    project_description.json to obtain main's authoritative resolved
    REQUIRES / PRIV_REQUIRES.  This unlocks samples whose
    main/CMakeLists.txt would defeat textual extraction:

      • esp_http_client — uses `${requires}` with `list(APPEND)`
      • icmp_echo, smtp_client — declare no REQUIRES; rely on
        ESP-IDF's implicit-all-components rule for main (the wrap
        widens REQUIRES to the probed build_components list)
      • https_server/{simple,wss_server}, modbus/serial/mb_master —
        previously failed for similar reasons; cleared by probe
      • system/ota/{simple,advanced_https,native}_ota_example —
        unlocked by `${project_dir}` substitution in EMBED_TXTFILES
        plus sample-root data-dir symlinking (server_certs/) into
        the wrap project root.
    """
    script = (TOOLS_DIR / "run-basic-wifi-smoke.sh").read_text()
    for entry in (
        "esp_http_client|${IDF_PATH}/examples/protocols/esp_http_client|station|build_only",
        "icmp_echo|${IDF_PATH}/examples/protocols/icmp_echo|station|build_only",
        "smtp_client|${IDF_PATH}/examples/protocols/smtp_client|station|build_only",
        "https_server_simple|${IDF_PATH}/examples/protocols/https_server/simple|station|build_only",
        "https_server_wss|${IDF_PATH}/examples/protocols/https_server/wss_server|station|build_only",
        "modbus_mb_master|${IDF_PATH}/examples/protocols/modbus/serial/mb_master|station|build_only",
        "ota_advanced_https|${IDF_PATH}/examples/system/ota/advanced_https_ota|station|build_only",
        "ota_native|${IDF_PATH}/examples/system/ota/native_ota_example|station|build_only",
        "ota_simple|${IDF_PATH}/examples/system/ota/simple_ota_example|station|build_only",
    ):
        assert entry in script, f"Day-56 protocol-sample smoke entry missing: {entry!r}"


def test_build_stock_sample_resolves_project_dir_in_embed_txtfiles(tmp_path):
    """Day-56: EMBED_FILES / EMBED_TXTFILES tokens of the form
    `${project_dir}/foo.pem` (used by system/ota/* samples) must be
    rewritten to absolute paths under SAMPLE_DIR (not SAMPLE_MAIN_DIR)
    when the wrap CMakeLists is generated.  Without this, the wrap
    main register call would emit
    `${SAMPLE_MAIN_DIR}/${project_dir}/foo.pem`, which CMake then
    expands to a non-existent path inside the wrap dir itself.
    """
    sample = tmp_path / "ota_like"
    main_dir = sample / "main"
    main_dir.mkdir(parents=True)
    (sample / "server_certs").mkdir()
    (sample / "server_certs" / "ca_cert.pem").write_text("dummy cert\n")
    (main_dir / "fake.c").write_text("/* fake */\n")
    (sample / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.16)\n"
        "include($ENV{IDF_PATH}/tools/cmake/project.cmake)\n"
        "project(ota_like)\n"
    )
    (main_dir / "CMakeLists.txt").write_text(
        "idf_build_get_property(project_dir PROJECT_DIR)\n"
        'idf_component_register(SRCS "fake.c"\n'
        '                       INCLUDE_DIRS "."\n'
        '                       PRIV_REQUIRES esp_netif\n'
        '                       EMBED_TXTFILES ${project_dir}/server_certs/ca_cert.pem)\n'
    )
    stub_idf = tmp_path / "idf" / "tools" / "idf.py"
    stub_idf.parent.mkdir(parents=True)
    stub_idf.write_text("#!/usr/bin/env bash\nexit 0\n")
    stub_idf.chmod(0o755)
    env = os.environ.copy()
    env["IDF_PATH"] = str(tmp_path / "idf")
    env["PATH"] = f"{stub_idf.parent}:{env.get('PATH','')}"
    env["BUILD_DIR"] = str(sample / "build_qemu")
    result = subprocess.run(
        ["bash", str(PROJECT_ROOT / "tools" / "build-stock-sample.sh"), str(sample)],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"build-stock-sample.sh failed:\nSTDOUT={result.stdout}\nSTDERR={result.stderr}"
    )
    wrap_cmake = sample / "_qemu_wrap_ota_like" / "main" / "CMakeLists.txt"
    assert wrap_cmake.is_file(), "wrap main CMakeLists.txt not generated"
    body = wrap_cmake.read_text()
    expected_abs = str(sample / "server_certs" / "ca_cert.pem")
    assert expected_abs in body, (
        f"Day-56: EMBED_TXTFILES ${{project_dir}} not rewritten to absolute SAMPLE_DIR path.\n"
        f"Expected '{expected_abs}' in:\n{body}"
    )
    # And the unresolved literal must NOT appear.
    assert "${project_dir}" not in body, (
        f"Day-56: literal ${{project_dir}} still present in wrap CMakeLists:\n{body}"
    )


def test_build_stock_sample_symlinks_sample_root_data_dirs(tmp_path):
    """Day-56: sdkconfig keys can resolve paths relative to PROJECT_DIR
    (e.g. CONFIG_MBEDTLS_CUSTOM_CERTIFICATE_BUNDLE_PATH).  Because the
    wrap is the project root from CMake's perspective, sample-root data
    dirs (server_certs/, etc.) must be symlinked into the wrap dir.
    """
    sample = tmp_path / "data_dir_sample"
    main_dir = sample / "main"
    main_dir.mkdir(parents=True)
    (sample / "server_certs").mkdir()
    (sample / "server_certs" / "ca_cert.pem").write_text("dummy\n")
    (main_dir / "fake.c").write_text("/* fake */\n")
    (sample / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.16)\n"
        "include($ENV{IDF_PATH}/tools/cmake/project.cmake)\n"
        "project(data_dir_sample)\n"
    )
    (main_dir / "CMakeLists.txt").write_text(
        'idf_component_register(SRCS "fake.c" INCLUDE_DIRS ".")\n'
    )
    stub_idf = tmp_path / "idf" / "tools" / "idf.py"
    stub_idf.parent.mkdir(parents=True)
    stub_idf.write_text("#!/usr/bin/env bash\nexit 0\n")
    stub_idf.chmod(0o755)
    env = os.environ.copy()
    env["IDF_PATH"] = str(tmp_path / "idf")
    env["PATH"] = f"{stub_idf.parent}:{env.get('PATH','')}"
    env["BUILD_DIR"] = str(sample / "build_qemu")
    result = subprocess.run(
        ["bash", str(PROJECT_ROOT / "tools" / "build-stock-sample.sh"), str(sample)],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"build-stock-sample.sh failed:\nSTDOUT={result.stdout}\nSTDERR={result.stderr}"
    )
    wrap_link = sample / "_qemu_wrap_data_dir_sample" / "server_certs"
    assert wrap_link.is_symlink() or wrap_link.is_dir(), (
        f"Day-56: sample-root data dir not symlinked into wrap dir at {wrap_link}"
    )
    # And the linked file must resolve.
    assert (wrap_link / "ca_cert.pem").is_file(), (
        f"Day-56: ca_cert.pem unreachable through {wrap_link}"
    )


def test_basic_wifi_smoke_includes_day53_eap_build_only_entries():
    """Day-53: wifi_eap_fast and wifi_enterprise are the last two stock
    ESP-IDF Wi-Fi samples.  Both require EMBED_TXTFILES to bake TLS
    material (ca.pem / client.crt / client.key / pac_file.pac) into the
    firmware image; until Day 53 the wrapper-project generator in
    tools/build-stock-sample.sh stripped those clauses (and did not
    propagate the file paths), so neither sample could be wrapped at
    parse time.  Promotion to build-only smoke entries here brings
    drop-in build coverage of `examples/wifi/**` to 15/15.
    """
    script = (TOOLS_DIR / "run-basic-wifi-smoke.sh").read_text()
    for entry in (
        "wifi_eap_fast|${IDF_PATH}/examples/wifi/wifi_eap_fast|station|build_only",
        "wifi_enterprise|${IDF_PATH}/examples/wifi/wifi_enterprise|station|build_only",
    ):
        assert entry in script, f"Day-53 EAP build-only entry missing: {entry!r}"


def test_build_stock_sample_propagates_embed_txtfiles():
    """Day-53 (FB-024 closure): the wrapper-project generator must
    extract `EMBED_FILES` and `EMBED_TXTFILES` from the sample's
    main/CMakeLists.txt and re-emit them in the synthetic wrap
    component, otherwise samples that bake binary blobs (TLS certs,
    EAP-FAST PAC, custom firmware blobs) fail at CMake parse time.
    Pin the awk-extractor + emit-paths combination so a future
    refactor does not silently regress the EAP samples.
    """
    script = (TOOLS_DIR / "build-stock-sample.sh").read_text()
    # The awk pass treats EMBED_FILES / EMBED_TXTFILES as keyword
    # boundaries (so REQUIRES extraction stops at them) — the Day-53
    # extension also calls extract_requires_kw with those keywords.
    assert 'extract_requires_kw EMBED_FILES' in script, (
        "build-stock-sample.sh must extract EMBED_FILES from sample "
        "main/CMakeLists.txt (Day-53 FB-024 closure)"
    )
    assert 'extract_requires_kw EMBED_TXTFILES' in script, (
        "build-stock-sample.sh must extract EMBED_TXTFILES from sample "
        "main/CMakeLists.txt (Day-53 FB-024 closure)"
    )
    # The generated wrapper CMakeLists must re-emit both clauses.
    assert 'echo "    EMBED_FILES"' in script, (
        "wrapper CMakeLists must re-emit EMBED_FILES clause"
    )
    assert 'echo "    EMBED_TXTFILES"' in script, (
        "wrapper CMakeLists must re-emit EMBED_TXTFILES clause"
    )


def test_esp_wifi_qemu_provides_he_itwt_stubs():
    """Day-52: `examples/wifi/itwt` references esp_wifi_sta_itwt_setup
    and esp_wifi_sta_twt_config — both declared in esp_wifi_he.h and
    only implemented on HE-capable targets (C5/C6/...).  ESP32 (the
    QEMU target) is non-HE, so the QEMU shim must define them as
    link-clean stubs returning ESP_ERR_NOT_SUPPORTED to preserve the
    zero-source-diff drop-in contract.
    """
    src = (PROJECT_ROOT / "components/esp_wifi_qemu/esp_wifi_extras.c").read_text()
    assert "esp_wifi_sta_itwt_setup" in src, (
        "HE/iTWT stub esp_wifi_sta_itwt_setup is missing from the shim"
    )
    assert "esp_wifi_sta_twt_config" in src, (
        "HE/TWT stub esp_wifi_sta_twt_config is missing from the shim"
    )
    assert "ESP_ERR_NOT_SUPPORTED" in src, (
        "Day-52 HE stubs must report ESP_ERR_NOT_SUPPORTED on the "
        "non-HE esp32 target rather than silently returning ESP_OK"
    )


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
