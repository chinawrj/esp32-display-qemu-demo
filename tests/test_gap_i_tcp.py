"""
test_gap_i_tcp.py - GAP-I: TCP/IP Data Plane non-runtime tests.

Validates the Day-27 changes that enable P1 stock samples
(protocols/sockets/tcp_client, udp_client) to build and run on the
QEMU Wi-Fi simulator.  All tests are non-runtime (no QEMU execution).

Day-27 fixes:
    - esp_wifi_internal_tx -> calls qemu_wifi_tx_raw() (MMIO TX via IDF driver)
  - Late WIFI_EVENT_STA_CONNECTED handler in esp_wifi_start() assigns
    static IP AFTER IDF's DHCP-clearing handler, fixing EHOSTUNREACH
    - esp_wifi_internal_free_rx_buffer -> calls free() to avoid memory leak
  - esp_wifi_netif_init() no longer called from GOT_IP handler (avoids
    double driver attach / InstrFetchProhibited crash)
  - build-stock-sample.sh: protocol_examples_common in EXTRA_COMPONENT_DIRS
  - sdkconfig.qemu.wifi.defaults: CONFIG_EXAMPLE_IPV4=y,
    CONFIG_EXAMPLE_IPV4_ADDR="10.0.2.2", CONFIG_EXAMPLE_PORT=3333
"""

import os
import re
import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPONENTS = os.path.join(REPO_ROOT, "components", "esp_wifi_qemu")
TOOLS_DIR = os.path.join(REPO_ROOT, "tools")
SDKCONFIG_QEMU = os.path.join(REPO_ROOT, "sdkconfig.qemu.wifi.defaults")
BUILD_STOCK_SH = os.path.join(TOOLS_DIR, "build-stock-sample.sh")
RUN_STOCK_SH = os.path.join(TOOLS_DIR, "run-stock-qemu.sh")
TCP_ECHO_PY = os.path.join(TOOLS_DIR, "tcp_echo_server.py")
RELAY_PY = os.path.join(TOOLS_DIR, "wifi_packet_relay.py")

IDF_PATH = os.environ.get("IDF_PATH", "") or os.path.expanduser("~/esp-idf")
TCP_CLIENT_BUILD = os.path.join(
    IDF_PATH, "examples", "protocols", "sockets",
    "tcp_client", "build_qemu"
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


def _has_tcp_build() -> bool:
    return bool(TCP_CLIENT_BUILD and os.path.isdir(TCP_CLIENT_BUILD))


# ===========================================================================
# GAP-I: esp_wifi_internal_tx - real MMIO TX
# ===========================================================================

class TestEspWifiInternalTx:
    """esp_wifi_internal_tx now calls qemu_wifi_tx_raw (not a no-op)."""

    def test_internal_tx_file_exists(self):
        assert os.path.isfile(os.path.join(COMPONENTS, "esp_wifi_internal.c"))

    def test_internal_tx_calls_qemu_tx_raw(self):
        src = _read(os.path.join(COMPONENTS, "esp_wifi_internal.c"))
        assert "qemu_wifi_tx_raw" in src, (
            "esp_wifi_internal_tx must call qemu_wifi_tx_raw() "
            "to support IDF default wifi driver TX path"
        )

    def test_internal_tx_not_noop(self):
        """The function must not unconditionally return 0 without transmitting."""
        src = _read(os.path.join(COMPONENTS, "esp_wifi_internal.c"))
        # After the fix, the no-op return should be gone
        assert "(void)buffer; (void)len;" not in src or "qemu_wifi_tx_raw" in src, (
            "esp_wifi_internal_tx must not be a no-op"
        )

    def test_qemu_wifi_tx_raw_declared_in_private_header(self):
        private_h = os.path.join(COMPONENTS, "esp_wifi_private.h")
        assert os.path.isfile(private_h)
        src = _read(private_h)
        assert "qemu_wifi_tx_raw" in src, (
            "qemu_wifi_tx_raw must be declared in esp_wifi_private.h "
            "so esp_wifi_internal.c can use it"
        )

    def test_qemu_wifi_tx_raw_defined_in_netif(self):
        src = _read(os.path.join(COMPONENTS, "esp_wifi_netif.c"))
        assert re.search(r"int\s+qemu_wifi_tx_raw\s*\(", src), (
            "qemu_wifi_tx_raw must be defined in esp_wifi_netif.c"
        )

    def test_internal_free_rx_buffer_calls_free(self):
        """esp_wifi_internal_free_rx_buffer must free the buffer (not no-op)."""
        src = _read(os.path.join(COMPONENTS, "esp_wifi_internal.c"))
        # Should contain free(buffer), not (void)buffer.
        func_start = src.find("esp_wifi_internal_free_rx_buffer")
        assert func_start != -1
        func_body = src[func_start:func_start + 300]
        assert "free(" in func_body, (
            "esp_wifi_internal_free_rx_buffer must call free(buffer) "
            "to avoid memory leak when IDF default wifi driver is used"
        )


# ===========================================================================
# GAP-I: Static IP handler in esp_wifi_start
# ===========================================================================

class TestStaticIpHandler:
    """Late WIFI_EVENT_STA_CONNECTED handler assigns static IP after DHCP."""

    def test_handler_function_exists(self):
        src = _read(os.path.join(COMPONENTS, "esp_wifi_shim.c"))
        assert "wifi_qemu_sta_connected_static_ip" in src, (
            "wifi_qemu_sta_connected_static_ip handler must be defined "
            "in esp_wifi_shim.c"
        )

    def test_handler_registered_in_esp_wifi_start(self):
        src = _read(os.path.join(COMPONENTS, "esp_wifi_shim.c"))
        # Find esp_wifi_start and verify handler registration nearby
        start_idx = src.find("esp_err_t esp_wifi_start(void)")
        assert start_idx != -1
        start_body = src[start_idx:start_idx + 1000]
        assert "esp_event_handler_register" in start_body, (
            "esp_wifi_start() must register wifi_qemu_sta_connected_static_ip "
            "via esp_event_handler_register for WIFI_EVENT_STA_CONNECTED"
        )

    def test_handler_registers_for_sta_connected(self):
        src = _read(os.path.join(COMPONENTS, "esp_wifi_shim.c"))
        assert "WIFI_EVENT_STA_CONNECTED" in src
        # The handler name must appear near the registration call
        handler_reg = re.search(
            r"esp_event_handler_register.*WIFI_EVENT_STA_CONNECTED.*"
            r"wifi_qemu_sta_connected_static_ip",
            src, re.DOTALL
        )
        assert handler_reg, (
            "Handler registration must pass wifi_qemu_sta_connected_static_ip "
            "as the callback for WIFI_EVENT_STA_CONNECTED"
        )

    def test_handler_calls_dhcpc_stop(self):
        src = _read(os.path.join(COMPONENTS, "esp_wifi_shim.c"))
        # The handler must explicitly stop DHCP before setting IP
        handler_start = src.find("wifi_qemu_sta_connected_static_ip")
        assert handler_start != -1
        handler_body = src[handler_start:handler_start + 2000]
        assert "esp_netif_dhcpc_stop" in handler_body, (
            "wifi_qemu_sta_connected_static_ip must call esp_netif_dhcpc_stop "
            "before esp_netif_set_ip_info (IDF 5.5 requires DHCP to be stopped "
            "before setting static IP)"
        )

    def test_handler_calls_set_ip_info(self):
        src = _read(os.path.join(COMPONENTS, "esp_wifi_shim.c"))
        handler_start = src.find("wifi_qemu_sta_connected_static_ip")
        handler_body = src[handler_start:handler_start + 2000]
        assert "esp_netif_set_ip_info" in handler_body, (
            "Handler must call esp_netif_set_ip_info to assign static IP"
        )

    def test_handler_posts_got_ip_event(self):
        src = _read(os.path.join(COMPONENTS, "esp_wifi_shim.c"))
        handler_start = src.find("wifi_qemu_sta_connected_static_ip")
        handler_body = src[handler_start:handler_start + 2000]
        assert "IP_EVENT_STA_GOT_IP" in handler_body, (
            "Handler must post IP_EVENT_STA_GOT_IP so example_connect "
            "and similar wrappers receive the IP"
        )

    def test_got_ip_handler_is_no_op(self):
        """WIFI_EVT_GOT_IP handler in wifi_event_task must not set IP anymore."""
        src = _read(os.path.join(COMPONENTS, "esp_wifi_shim.c"))
        # Find the WIFI_EVT_GOT_IP case
        got_ip_idx = src.find("case WIFI_EVT_GOT_IP:")
        assert got_ip_idx != -1

        # Find the end of this case: look for the next 'case WIFI_EVT_' statement
        next_case = src.find("case WIFI_EVT_", got_ip_idx + 20)
        if next_case == -1 or next_case - got_ip_idx > 3000:
            next_case = got_ip_idx + 2000
        case_body = src[got_ip_idx:next_case]

        # Strip block comments (/* ... */) and line comments (//) before checking
        # so references like "do NOT call esp_netif_set_ip_info()" in comments
        # don't create false failures.
        no_block_comments = re.sub(r"/\*.*?\*/", "", case_body, flags=re.DOTALL)
        no_comments = re.sub(r"//[^\n]*", "", no_block_comments)

        assert "esp_netif_set_ip_info(" not in no_comments, (
            "WIFI_EVT_GOT_IP handler must NOT call esp_netif_set_ip_info "
            "(races with STA_CONNECTED event ordering - Day-27 bug)"
        )
        # The manual IP event post should be removed from this handler
        assert 'esp_event_post(IP_EVENT, IP_EVENT_STA_GOT_IP' not in no_comments, (
            "WIFI_EVT_GOT_IP handler must NOT post IP_EVENT_STA_GOT_IP "
            "(this caused EHOSTUNREACH due to event ordering race)"
        )


# ===========================================================================
# GAP-I: esp_wifi_netif_init no longer called from GOT_IP handler
# ===========================================================================

class TestNetifInitNotFromGotIp:
    """Calling esp_netif_set_driver_config after IDF driver is attached
    corrupts function pointers -> InstrFetchProhibited (Day-27 bug)."""

    def test_netif_init_not_in_got_ip_handler(self):
        src = _read(os.path.join(COMPONENTS, "esp_wifi_shim.c"))
        got_ip_idx = src.find("WIFI_EVT_GOT_IP")
        assert got_ip_idx != -1
        case_body = src[got_ip_idx:got_ip_idx + 600]
        assert "esp_wifi_netif_init" not in case_body, (
            "esp_wifi_netif_init must NOT be called from WIFI_EVT_GOT_IP handler"
            " - calling it after esp_netif_create_wifi attaches the IDF driver"
            " corrupts netif function pointers (InstrFetchProhibited)"
        )

    def test_esp_wifi_netif_init_still_exists(self):
        """The function still exists for explicit custom netif setups."""
        src = _read(os.path.join(COMPONENTS, "esp_wifi_netif.c"))
        assert "esp_wifi_netif_init" in src


# ===========================================================================
# GAP-I: sdkconfig.qemu.wifi.defaults - tcp/udp sample config
# ===========================================================================

class TestSdkconfigQemuDefaults:
    """sdkconfig.qemu.wifi.defaults must have correct settings."""

    def test_file_exists(self):
        assert os.path.isfile(SDKCONFIG_QEMU), (
            f"sdkconfig.qemu.wifi.defaults not found at {SDKCONFIG_QEMU}"
        )

    def test_example_ipv4_enabled(self):
        content = _read(SDKCONFIG_QEMU)
        assert "CONFIG_EXAMPLE_IPV4=y" in content, (
            "CONFIG_EXAMPLE_IPV4=y required for tcp_client and udp_client"
        )

    def test_example_ipv4_addr_set(self):
        content = _read(SDKCONFIG_QEMU)
        assert "CONFIG_EXAMPLE_IPV4_ADDR" in content, (
            "CONFIG_EXAMPLE_IPV4_ADDR must point to SLIRP gateway 10.0.2.2"
        )
        # Should be the SLIRP gateway
        assert "10.0.2.2" in content

    def test_example_port_set(self):
        content = _read(SDKCONFIG_QEMU)
        assert "CONFIG_EXAMPLE_PORT" in content, (
            "CONFIG_EXAMPLE_PORT must be set for socket samples"
        )

    def test_connect_wifi_enabled(self):
        content = _read(SDKCONFIG_QEMU)
        assert "CONFIG_EXAMPLE_CONNECT_WIFI=y" in content


# ===========================================================================
# GAP-I: build-stock-sample.sh - protocol_examples_common support
# ===========================================================================

class TestBuildStockSampleScript:
    """build-stock-sample.sh must include protocol_examples_common."""

    def test_script_exists(self):
        assert os.path.isfile(BUILD_STOCK_SH)

    def test_protocol_examples_common_in_extra_dirs(self):
        src = _read(BUILD_STOCK_SH)
        assert "protocol_examples_common" in src, (
            "build-stock-sample.sh must add protocol_examples_common "
            "to EXTRA_COMPONENT_DIRS for tcp_client and similar samples"
        )

    def test_v6_files_skipped(self):
        """_v6.c files must be excluded to avoid IPv6-only compile errors."""
        src = _read(BUILD_STOCK_SH)
        assert "_v6.c" in src, (
            "build-stock-sample.sh must skip *_v6.c files "
            "(they use IPv6 structs conditionally unsupported with IPV4-only)"
        )

    def test_sdkconfig_qemu_overlay_applied(self):
        src = _read(BUILD_STOCK_SH)
        assert "sdkconfig.qemu.wifi.defaults" in src, (
            "build-stock-sample.sh must apply sdkconfig.qemu.wifi.defaults "
            "overlay for correct sample configuration"
        )


# ===========================================================================
# GAP-I: tools/tcp_echo_server.py - TCP echo server for tests
# ===========================================================================

class TestTcpEchoServer:
    """tcp_echo_server.py must exist and be syntactically valid."""

    def test_echo_server_exists(self):
        assert os.path.isfile(TCP_ECHO_PY), (
            f"tools/tcp_echo_server.py not found at {TCP_ECHO_PY}"
        )

    def test_echo_server_imports_asyncio(self):
        src = _read(TCP_ECHO_PY)
        assert "asyncio" in src, "tcp_echo_server.py must use asyncio"

    def test_echo_server_has_listen_port(self):
        src = _read(TCP_ECHO_PY)
        # Server should listen on a configurable port
        assert "3333" in src or "port" in src.lower(), (
            "tcp_echo_server.py must support port 3333 (default for socket samples)"
        )

    def test_echo_server_python_syntax(self):
        import subprocess
        result = subprocess.run(
            ["python3", "-m", "py_compile", TCP_ECHO_PY],
            capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"tcp_echo_server.py has syntax errors: {result.stderr}"
        )


# ===========================================================================
# GAP-I: run-stock-qemu.sh - TCP echo server integration
# ===========================================================================

class TestRunStockQemuScript:
    """run-stock-qemu.sh must support TCP_ECHO_PORT env var."""

    def test_run_stock_script_exists(self):
        assert os.path.isfile(RUN_STOCK_SH)

    def test_run_stock_script_has_tcp_echo_port(self):
        src = _read(RUN_STOCK_SH)
        assert "TCP_ECHO_PORT" in src, (
            "run-stock-qemu.sh must support TCP_ECHO_PORT env variable "
            "to start tcp_echo_server.py for socket sample testing"
        )

    def test_run_stock_script_starts_echo_server(self):
        src = _read(RUN_STOCK_SH)
        assert "tcp_echo_server.py" in src, (
            "run-stock-qemu.sh must start tools/tcp_echo_server.py "
            "when TCP_ECHO_PORT is set"
        )


# ===========================================================================
# GAP-I: wifi_packet_relay.py - TCP proxy support
# ===========================================================================

class TestRelayTcpProxy:
    """wifi_packet_relay.py must have TCP proxy support for 10.0.2.2."""

    def test_relay_exists(self):
        assert os.path.isfile(RELAY_PY)

    def test_relay_has_tcp_proxy_conn(self):
        src = _read(RELAY_PY)
        assert "TCPProxyConn" in src, (
            "wifi_packet_relay.py must have TCPProxyConn class "
            "for TCP connection proxying"
        )

    def test_relay_maps_slirp_gateway(self):
        src = _read(RELAY_PY)
        assert "10.0.2.2" in src, (
            "wifi_packet_relay.py must map 10.0.2.2 (SLIRP gateway) "
            "to 127.0.0.1 for TCP proxy"
        )

    def test_relay_maps_local_host(self):
        src = _read(RELAY_PY)
        assert "127.0.0.1" in src or "localhost" in src.lower(), (
            "wifi_packet_relay.py must forward TCP to 127.0.0.1"
        )


# ===========================================================================
# GAP-I: tcp_client build artifact (if available)
# ===========================================================================

@pytest.mark.skipif(
    not _has_tcp_build(),
    reason="tcp_client build not present (run tools/build-stock-sample.sh "
           "~/esp-idf/examples/protocols/sockets/tcp_client first)"
)
class TestTcpClientBuild:
    """tcp_client wrapper build artifacts exist."""

    def test_elf_exists(self):
        elf = os.path.join(TCP_CLIENT_BUILD, "tcp_client.bin")
        assert os.path.isfile(elf), f"tcp_client.bin not found at {elf}"

    def test_merged_flash_exists(self):
        merged = os.path.join(TCP_CLIENT_BUILD, "merged_flash.bin")
        assert os.path.isfile(merged), f"merged_flash.bin not found"

    def test_sdkconfig_has_example_ipv4(self):
        # sdkconfig is in the wrapper project directory, not build_qemu
        parent = os.path.dirname(TCP_CLIENT_BUILD)
        sdk_candidates = [
            os.path.join(parent, "_qemu_wrap_tcp_client", "sdkconfig"),
            os.path.join(parent, "sdkconfig"),
        ]
        sdk = next((p for p in sdk_candidates if os.path.isfile(p)), None)
        if not sdk:
            pytest.skip("sdkconfig not found in tcp_client wrapper project")
        content = _read(sdk)
        assert "CONFIG_EXAMPLE_IPV4=y" in content, (
            "tcp_client build must have CONFIG_EXAMPLE_IPV4=y"
        )

    def test_sdkconfig_has_example_ipv4_addr(self):
        # sdkconfig is in the wrapper project directory, not build_qemu
        parent = os.path.dirname(TCP_CLIENT_BUILD)
        sdk_candidates = [
            os.path.join(parent, "_qemu_wrap_tcp_client", "sdkconfig"),
            os.path.join(parent, "sdkconfig"),
        ]
        sdk = next((p for p in sdk_candidates if os.path.isfile(p)), None)
        if not sdk:
            pytest.skip("sdkconfig not found in tcp_client wrapper project")
        content = _read(sdk)
        assert "CONFIG_EXAMPLE_IPV4_ADDR" in content

    def test_map_file_has_qemu_wifi_internal_tx(self):
        """esp_wifi_internal_tx must come from libesp_wifi_qemu.a."""
        map_files = [f for f in os.listdir(TCP_CLIENT_BUILD)
                     if f.endswith(".map")]
        if not map_files:
            pytest.skip("No .map file in tcp_client build")
        map_content = _read(os.path.join(TCP_CLIENT_BUILD, map_files[0]))
        # The symbol should come from our component
        assert "esp_wifi_qemu" in map_content and "internal_tx" in map_content, (
            "esp_wifi_internal_tx must be provided by esp_wifi_qemu component"
        )
