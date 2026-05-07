# Day 37 — Real wpa_supplicant Passthrough Mode

**Date**: 2026-05-09  
**Commit**: 94a3d37  
**Branch**: main

## Goals

- Add real `wpa_supplicant` passthrough as a second documented launch mode
  alongside the existing mock-based flow.
- Keep it a drop-in option: no source-code changes required in the firmware.
- Document it properly so it is usable as a released feature option.

## Completed Work

### `tools/wifi_packet_relay.py` — `--gateway-ip` / `--no-local-map` flags

Added `argparse`-based `main()` with two new flags:

| Flag | Effect |
|------|--------|
| `--gateway-ip <IP>` | Overrides `GATEWAY_IP = "10.0.2.2"` globally; ARP replies are sent for the real router IP. |
| `--no-local-map` | Clears `LOCAL_HOST_MAP` so TCP/UDP traffic reaches real destinations instead of being redirected to localhost. |

In mock mode the flags are omitted and the defaults remain unchanged.

### `tools/run-real-wifi.sh` — New launcher (220 lines)

New script that:
1. Auto-detects the wireless interface from `ip -o link show | grep wl`.
2. Checks wpa_supplicant socket at `/var/run/wpa_supplicant/<iface>`.
3. Reads the real gateway IP from `ip route show default dev <iface>`.
4. Starts `wifi_packet_relay.py --gateway-ip <real_gw> --no-local-map`.
5. Exports `ESP_WIFI_CTRL_SOCKET` to the real wpa_supplicant socket path.
6. Runs QEMU (optionally under `sudo` when `WIFI_SUDO=1` or socket is root-only).
7. Emits tmux sudo-window guidance when escalation is needed.

Supported env vars: `WIFI_IFACE`, `WIFI_SUDO`, `PKT_SOCKET`, `LOG_FILE`, `VERIFY_PROFILE`.

### `tests/test_stock_sample_build.py` — 5 new non-runtime tests

| Test | Asserts |
|------|---------|
| `test_run_real_wifi_script_exists` | Script exists and is executable |
| `test_relay_accepts_gateway_ip_flag` | `--gateway-ip` argparse wired in relay |
| `test_relay_accepts_no_local_map_flag` | `--no-local-map` argparse clears `LOCAL_HOST_MAP` |
| `test_run_real_wifi_uses_real_wpa_socket` | Script references real wpa socket, exports `ESP_WIFI_CTRL_SOCKET`, passes `--no-local-map` |
| `test_run_real_wifi_supports_sudo_mode` | Script uses `WIFI_SUDO` env var and `sudo` |

All 5 pass immediately.

### `docs/qemu-wifi-stock-samples.md` — "Real Wi-Fi Passthrough Mode" section

Appended a new section covering:
- Mock vs real mode comparison table.
- Prerequisites (netdev group or `WIFI_SUDO=1`).
- Run commands for `station` sample.
- Full environment variable table.
- Known limits (SSID compiled in, host WiFi disruption, DHCP from real server).

## Test Results

```
191 passed, 6 skipped (0:02:13)
```

+5 vs Day 36 baseline (186 passed, 6 skipped).

## Architecture Notes

- The QEMU device (`esp_wifi.c`) already reads `ESP_WIFI_CTRL_SOCKET` env var,
  so no QEMU patch was needed.
- The firmware shim already writes the ctrl socket path via `WIFI_REG_CTRL_SOCK_*`
  registers; `run-real-wifi.sh` simply sets the env var instead.
- ARP: relay's `handle_arp()` responds to any `target == GATEWAY_IP` —
  with `--gateway-ip 192.168.1.1` it answers for the real router IP with the
  fake relay MAC (`52:54:00:12:34:56`), which the guest uses to route packets.
- No firmware source changes needed; real-WiFi mode is purely a launcher
  + relay configuration change.

## Health Check

- Lines in `run-real-wifi.sh`: 220 (under 250 threshold — OK)
- Compilation warnings: 0 (no firmware code changed)
- TODO/FIXME count: unchanged
- No new hacks in `main/wifi_ui.c` or any firmware `.c` file

## Tomorrow / Follow-up

- Optional: tag `v1.1.0-qemu-wifi-realwifi` to mark the passthrough release.
- Consider integration test: run `run-real-wifi.sh` in CI if a real WiFi adapter
  is present (skip otherwise).
- `ICMP (ping)` not yet bridged — document or implement if needed.
