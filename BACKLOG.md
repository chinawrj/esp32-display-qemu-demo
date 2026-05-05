# Backlog

Tracked, implementation-ready next targets for this project. Items here are
**not yet started** — they're written so any contributor (especially on a
fresh Linux machine) can pick them up without re-deriving the design.

The headline target is at the top.

---

## ★★★ PRIMARY-TARGET — Drop-in ESP-IDF Wi-Fi sample compatibility

**Status:** Planning. Manager directive (Day 22, 2026-05-05).

### Mission statement

> **Any Wi-Fi sample under `$IDF_PATH/examples/wifi/**` (and any application
> that uses `esp_wifi_*` / `esp_now_*` / `esp_netif_*`) MUST run unmodified on
> our QEMU Wi-Fi simulator. Only `CMakeLists.txt` / `sdkconfig` changes are
> permitted to select the QEMU Wi-Fi component; NO `.c` / `.h` source code
> changes are allowed.**

This is the **north star** for every subsequent Wi-Fi work item. Every BUG
fix, GAP closure, and architectural decision must be evaluated against
"does this bring us closer to drop-in sample support?".

### Acceptance criteria

A given ESP-IDF Wi-Fi sample is considered "supported" when:

- [ ] Sample's `main/*.c` and `main/*.h` are byte-identical to upstream.
- [ ] Only `CMakeLists.txt` (project-level or main) and `sdkconfig.defaults`
      may differ, and only to: (a) add `EXTRA_COMPONENT_DIRS` pointing at our
      `components/` overlay, (b) enable `CONFIG_ESP_WIFI_QEMU=y`.
- [ ] `idf.py build` succeeds with zero warnings.
- [ ] `bash tools/run-direct-demo.sh` boots the sample in QEMU and the
      sample's expected runtime log line appears (e.g. `got ip:`,
      `wifi_init_softap finished`, `iperf TCP send N MBytes`, …).
- [ ] No real ESP32 hardware required.

### Phase-1 target samples (Day 22+)

| Priority | Sample path | What it exercises |
|----------|-------------|-------------------|
| P0 | `examples/wifi/getting_started/station/` | STA connect + GOT_IP |
| P0 | `examples/wifi/scan/` | active scan + result enumeration |
| P1 | `examples/wifi/getting_started/softAP/` | AP mode + DHCP server |
| P1 | `examples/protocols/sockets/tcp_client/` | lwIP TCP outbound |
| P1 | `examples/protocols/sockets/udp_client/` | lwIP UDP outbound |
| P2 | `examples/wifi/iperf/` | bandwidth API + ps mode |
| P2 | `examples/wifi/power_save/` | esp_wifi_set_ps + sleep |
| P2 | `examples/wifi/espnow/` | esp_now_* full API |
| P3 | `examples/wifi/fast_scan/` | fine-grained scan_config |
| P3 | `examples/wifi/wpa2_enterprise/` | enterprise auth |
| P3 | `examples/wifi/smartconfig/` | smartconfig API |
| P3 | `examples/wifi/itwt/` | individual TWT |
| P3 | `examples/network/simple_sniffer/` | promiscuous mode |

### Un-aligned parts inventory (gap list, sourced from Day 22 review)

The following gaps prevent stock samples from running today. Each gap is a
new BACKLOG item (see "Gap details" section below for fix plans).

#### A. esp_wifi_* API surface gaps (linker would silently drop through to libnet80211)

Currently overridden (16 symbols): `esp_wifi_init/deinit`, `set_mode/get_mode`,
`start/stop`, `set_config/get_config`, `connect/disconnect`,
`get_mac/set_mac`, `scan_start/scan_stop`,
`scan_get_ap_num/scan_get_ap_records`.

Currently NOT overridden but called by ESP-IDF samples — currently fall
through to libnet80211 with `--allow-multiple-definition` and behavior is
**undefined in QEMU** (most likely panic or silent no-op):

- `esp_wifi_set_ps` / `esp_wifi_get_ps` — power save (iperf, power_save)
- `esp_wifi_set_bandwidth` / `esp_wifi_get_bandwidth` — iperf
- `esp_wifi_set_channel` / `esp_wifi_get_channel` — sniffer, fast_scan
- `esp_wifi_set_country` / `esp_wifi_get_country` / `esp_wifi_get_country_code`
- `esp_wifi_set_storage` — many samples set `WIFI_STORAGE_RAM`
- `esp_wifi_set_protocol` / `esp_wifi_get_protocol`
- `esp_wifi_set_max_tx_power` / `esp_wifi_get_max_tx_power`
- `esp_wifi_restore` — many samples call this on boot
- `esp_wifi_sta_get_ap_info` — fast_scan, mqtt
- `esp_wifi_sta_get_rssi` — diagnostic UIs
- `esp_wifi_set_promiscuous` / `_get_promiscuous` / `_filter` / `_rx_cb` —
  sniffer
- `esp_wifi_set_vendor_ie` / `_set_vendor_ie_cb`
- `esp_wifi_set_inactive_time` / `_get_inactive_time`
- `esp_wifi_set_event_mask` / `_get_event_mask`
- `esp_wifi_80211_tx` — raw frame injection
- `esp_wifi_set_csi` / `_set_csi_config` / `_set_csi_rx_cb` — CSI samples

#### B. AP / SoftAP mode (entirely absent)

- `esp_wifi_ap_get_sta_list` / `_ap_get_sta_aid`
- `esp_wifi_deauth_sta`
- `WIFI_MODE_AP` / `WIFI_MODE_APSTA` are accepted by `esp_wifi_set_mode` but
  the QEMU device only models a STA endpoint. softAP samples will set the
  mode then call `esp_wifi_set_config(WIFI_IF_AP, …)` which today is rejected
  by our shim (only `WIFI_IF_STA` is wired).
- Need: AP-side event flow `WIFI_EVENT_AP_START` / `_STACONNECTED` /
  `_STADISCONNECTED` / `_AP_STOP`.
- Mock side: `mock_wpa_supplicant.py` is STA-only; needs an AP variant or a
  unified daemon with role config.
- Relay side: AP mode needs an in-relay DHCP **server** that hands leases to
  fictional client MACs.

#### C. ESPNOW (entirely absent)

`esp_now_init/deinit`, `_send/_recv`, `_register_send_cb/_register_recv_cb`,
`_add_peer/_del_peer/_mod_peer`, `_get_peer/_fetch_peer`, `_set_pmk`,
`_set_wake_window`, `_get_version`. ESPNOW has no infrastructure — frames
are direct peer-to-peer. Either: (a) loopback echo within one QEMU instance,
or (b) cross-instance via `wifi_packet_relay.py` carrying ESPNOW frames.

#### D. WPS / SmartConfig (entirely absent)

`esp_wifi_wps_*`, `esp_smartconfig_*`. Lower priority (P3).

#### E. WPA2-Enterprise (entirely absent)

`esp_wifi_sta_wpa2_ent_*`. Mock_wpa unconditionally answers SUCCESS — but
enterprise samples set certificates via these APIs and would fail to link.

#### F. esp_netif / driver-glue gaps

- `esp_netif_attach_wifi_station` / `esp_netif_attach_wifi_ap` — currently
  flow through libnet80211. They register `esp_wifi_internal_reg_rxcb` and
  similar internals. Our shim avoids them by manually setting the driver
  config in `esp_wifi_netif_init()`. **A standard ESP-IDF sample that calls
  `esp_netif_create_default_wifi_sta()` works only by accident** (libnet80211
  registers callbacks our shim never invokes). Need to formally document
  which call paths are safe and which silently break.
- `esp_wifi_internal_set_sta_ip` — used by `esp_netif` for static IP.
- `esp_wifi_internal_reg_rxcb` / `_free_rx_buffer` — driver TX/RX callbacks.

#### G. CMake / build-system alignment (CRITICAL for "no source change")

Right now `main/CMakeLists.txt` explicitly `REQUIRES esp_wifi_qemu`. A stock
ESP-IDF sample's `CMakeLists.txt` does NOT — it just `REQUIRES esp_wifi`.
For our shim to be linked into a stock sample, one of:

1. **Recommended**: provide a top-level CMake snippet
   `tools/qemu-wifi-overlay.cmake` that the sample's project-level
   `CMakeLists.txt` includes (one-line `include()` is the only allowed
   "change"). The snippet sets `EXTRA_COMPONENT_DIRS` and forces a
   `PRIV_REQUIRES esp_wifi_qemu` injection on every component that requires
   `esp_wifi`.
2. **Alternative**: `idf.py -DEXTRA_COMPONENT_DIRS=…` from the launcher
   script `tools/run-direct-demo.sh`, plus a per-sample
   `sdkconfig.defaults.qemu` overlay enabling `CONFIG_ESP_WIFI_QEMU=y`. This
   keeps the sample's `CMakeLists.txt` byte-identical at the cost of a
   non-standard build invocation.
3. **Out-of-tree component manager**: publish `esp_wifi_qemu` as a managed
   component (`idf_component.yml` with `dependencies`), so samples include it
   via `idf_component.yml` override. Higher overhead.

#### H. sdkconfig defaults that samples expect

Stock Wi-Fi samples expect `CONFIG_ESP_WIFI_*` Kconfig knobs (e.g.
`CONFIG_ESP_WIFI_DYNAMIC_TX_BUFFER_NUM`, `CONFIG_ESP_WIFI_RX_BA_WIN`,
`CONFIG_ESP_WIFI_AMPDU_RX_ENABLED`). These pass through to the real
`esp_wifi` component harmlessly today, but if we ever fully replace
`esp_wifi`, we must continue accepting them as no-ops.

#### I. lwIP / DHCP / DNS data-plane gaps

- `wifi_packet_relay.py` does not implement DHCP server. Real ESP-IDF samples
  enable DHCP client by default — they currently work only because mock_wpa
  injects a static IP via `esp_netif_set_ip_info()` in our shim. A sample
  that calls `esp_netif_dhcpc_start()` would hang.
- No DNS proxy: samples that resolve hostnames (e.g. `pool.ntp.org`) fail.
- No IPv6: `esp_netif_create_ip6_linklocal()` and IPv6 multicast samples
  fail silently.
- No NAT outbound to real internet: relay only maps `10.0.2.100` and
  `10.0.2.2` to `127.0.0.1`. Samples that connect to public servers fail.

#### J. Event ordering / timing correctness

- Mode switch races (BUG-004 — see below).
- `WIFI_EVENT_HOME_CHANNEL_CHANGE`, `WIFI_EVENT_STA_BEACON_TIMEOUT`,
  `WIFI_EVENT_STA_BSS_RSSI_LOW`, `WIFI_EVENT_ROC_DONE` not emitted.
- `IP_EVENT_AP_STAIPASSIGNED` not emitted (softAP DHCP).

### Current support matrix (Day 28 start, 2026-05-05)

| Sample | Build | QEMU run | Release relevance |
|--------|-------|----------|-------------------|
| `examples/wifi/getting_started/station/` | Done | Done: `got ip:10.0.2.15` | Basic STA gate |
| `examples/wifi/scan/` | Done | Done: `Total APs scanned = 1`, `SSID QEMU_TEST` | Basic SCAN gate |
| `examples/wifi/getting_started/softAP/` | Done | Done: `wifi_init_softap finished` | Basic AP gate |
| `examples/protocols/sockets/tcp_client/` | Done | Done: `Echo: Message from ESP32` | Data-plane confidence |
| `examples/protocols/sockets/udp_client/` | Not started | Not started | Stretch after release gate |

### Six-day formal release plan: basic STA/SCAN/AP

Manager request (Day 28): prepare a formal release after 6 days. The release
target is not long-tail Wi-Fi completeness; it is a stable, documented,
repeatable **basic STA/SCAN/AP** simulator release with matching tests.

| Day | Focus | GAPs / tests | Exit criteria |
|-----|-------|--------------|---------------|
| Day 28 | SCAN hardening | GAP-J scan event ordering; runner verifier tests | Stock `wifi/scan` prints `Total APs scanned` and `SSID QEMU_TEST`; non-runtime tests cover scan-only QEMU flow |
| Day 29 | AP hardening | GAP-B SoftAP event/API tests | Stock `softAP` builds/runs; AP start/config/station-list stubs covered; no station regression |
| Day 30 | STA regression suite | GAP-F/G station path tests | Done: `tools/run-basic-wifi-smoke.sh` rebuilds and runs station/scan/softAP wrappers; runtime gate passed 3/3 |
| Day 31 | Release automation | automated-testing runtime smoke profiles | Done: `tools/run-basic-wifi-smoke.sh` writes `summary.tsv`; station/scan/softAP runtime gate passed 3/3 |
| Day 32 | Documentation freeze | `docs/qemu-wifi-stock-samples.md` | Release docs include prerequisites, build/run commands, expected logs, known limits |
| Day 33 | Release candidate | final build/test matrix | Clean worktree; non-runtime tests pass; runtime smoke green for station/scan/softAP; tag-ready release notes drafted |

Non-goals for this six-day release: ESPNOW, WPS/SmartConfig,
WPA2-Enterprise, promiscuous/sniffer, IPv6, DNS proxy, and external internet
NAT. Keep those in the backlog after the release gate.

### Why this matters

A demo that requires forking every sample is "yet another fork";
a simulator that runs them unchanged is *infrastructure*. The latter is
what the manager has explicitly asked for.

---

## NEXT-004 — lwIP socket proof over QEMU virtual Wi-Fi

**Status:** Planned for Day 19, Linux.

### Problem

NEXT-002 and NEXT-003 prove the Wi-Fi control plane: firmware can call the
public `esp_wifi_*` API, connect through the QEMU virtual Wi-Fi device, and
receive `IP_EVENT_STA_GOT_IP`. Day 14 added raw Ethernet DMA plumbing between
ESP-IDF lwIP and a host packet relay, but the accepted demo/test path still
does not prove application-level socket traffic.

In practical terms, the answer to "does lwIP over this Wi-Fi network work?" is
currently: the plumbing exists, but it is not accepted until firmware opens a
real TCP/UDP socket and receives a host response through `ESP_WIFI_PKT_SOCKET`.

### Goal

Add an end-to-end runtime proof that an ESP-IDF application can use lwIP over
the QEMU virtual Wi-Fi network without real hardware.

Target flow:

```
firmware lwIP socket
  -> esp_wifi_qemu esp_netif transmit callback
  -> QEMU esp_wifi DMA TX registers
  -> tools/wifi_packet_relay.py
  -> host echo/HTTP server on 127.0.0.1
  -> relay response
  -> QEMU DMA RX registers
  -> esp_netif_receive()
  -> firmware log: lwip echo ok
```

### Concrete subtasks (in order)

1. Add a minimal firmware socket probe guarded by Kconfig, default enabled only
  for the QEMU demo:
  - after `IP_EVENT_STA_GOT_IP`, create a TCP socket;
  - connect to `10.0.2.100:<CONFIG_DEMO_LWIP_PROBE_PORT>`;
  - send a short request/payload;
  - log `lwip probe ok:` when the expected response arrives.

2. Update `tools/run-direct-demo.sh`:
  - start `tools/wifi_packet_relay.py`;
  - export `ESP_WIFI_PKT_SOCKET` before QEMU boots;
  - optionally start a tiny host echo/HTTP server for manual demo mode;
  - clean up relay/server processes on exit.

3. Add pytest runtime coverage:
  - start mock wpa_supplicant;
  - start packet relay;
  - start host echo/HTTP server;
  - boot QEMU;
  - assert serial log contains both `got ip:` and `lwip probe ok:`.

4. Keep fast source checks so environments without QEMU still validate the
  planned wiring and skip runtime tests cleanly.

### Acceptance criteria

- [ ] `idf.py build` succeeds with zero warnings.
- [ ] `bash tools/run-direct-demo.sh` starts mock Wi-Fi ctrl socket and packet
    relay, and firmware logs `lwip probe ok:`.
- [ ] `pytest -q tests/test_qemu_integrated_demo.py` includes a runtime lwIP
    probe test that passes when QEMU prerequisites are present and skips
    cleanly otherwise.
- [ ] Existing non-runtime tests keep passing.
- [ ] The implementation remains API-level Wi-Fi simulation; no ESP32 Wi-Fi
    hardware register modeling is introduced.

### Known limitations (v1 scope)

- TCP proof is enough for acceptance; UDP/ICMP can remain relay-supported but
  separately unaccepted.
- This is still a virtual STA-only path, not SoftAP or Wi-Fi Direct.
- The packet relay is SLIRP-like test infrastructure, not a full network stack.

---

## ★ NEXT-001 — QEMU-native framebuffer → Chrome export (no firmware changes)

**Status:** ✅ **DONE** (Days 4–7, Linux).  
Shipped commits: d922378 (Day 5 WS server), c09fea8 (Day 6 VRAM-direct), f798616 (web viewer), 180eae5 (tests), b9f9199 (Day 6 log).

All acceptance criteria met:
- ✅ `bash tools/build-qemu.sh` produces a `qemu-system-xtensa` with the built-in WS device.
- ✅ `bash tools/run-direct-demo.sh` boots QEMU + opens `web/qemu-direct.html`; LVGL animates at ~30 fps with no `ESP_RGB_VRAM_FILE`.
- ✅ `pytest -q tests/cdp/test_qemu_direct_canvas.py` passes with `ESP_RGB_VRAM_FILE` unset.
- ✅ Full test suite: 62 passed, 0 failed (50 non-CDP + 12 CDP).
- ✅ No firmware-side changes required; `main/qemu_vram.c` calls remain optional.

### Problem

Today, getting an LVGL/ESP-IDF app's frames into a Chrome page requires
**firmware-level cooperation**:

1. The firmware mmap's a magic MMIO region (`QEMU_RGB_VRAM_ADDR = 0x20000000`)
   inside the `esp_rgb` device's VRAM and writes RGB565 pixels into it
   every flush (see `main/qemu_vram.c` → `qemu_vram_mirror`).
2. QEMU is launched with `ESP_RGB_VRAM_FILE=/tmp/esp32-rgb-vram.bin` so that
   VRAM is `memory_region_init_ram_from_file(... RAM_SHARED ...)` instead of
   anonymous RAM (see `tools/qemu-src/hw/display/esp_rgb.c`, the
   `ESP_RGB_VRAM_FILE_PATCH` block around line 303).
3. A host-side Python `fb_server` (see `tools/fb_server/shmem_producer.py`)
   mmaps the same file and streams a slice of it to Chrome over a WebSocket.

That works (and is what `tools/run-demo.sh` does today), but it means **every
ESP-IDF app that wants Chrome viewing has to be modified** to do the
firmware-side mirror dance. We want any unmodified `esp_lcd_qemu_rgb`-based
app to "just appear" in Chrome.

### Desired architecture

Move the streaming responsibility **into the QEMU device itself**:

```
        before                                 after
        ──────                                 ─────
   ESP-IDF app ─┐                          ESP-IDF app ─┐
                │ (special MMIO writes)                 │ (normal LCD draw)
                ▼                                       ▼
   QEMU esp_rgb ─┐ (RAM-backed file)        QEMU esp_rgb ─┐ (DisplaySurface)
                ▼                                       │
            host file ───┐                              │  WebSocket / HTTP
                         ▼                              ▼
                   Python fb_server ───── WS ──── Chrome canvas
                                                    (direct)
```

The `esp_rgb` device already maintains a fully-rendered `DisplaySurface`
(updated via `update_rgb_surface()` and `dpy_gfx_replace_surface()` in
`tools/qemu-src/hw/display/esp_rgb.c`). That surface contains exactly the
pixels QEMU's GTK/SDL window would draw. We just need to push those pixels
out over a network socket Chrome can read.

### Concrete subtasks (in order)

1. **Spec the wire protocol.** Simplest viable design:
   - QEMU listens on `127.0.0.1:9334` (configurable via `-device esp_rgb,websocket-port=…` or the `ESP_RGB_WS_PORT` env var, mirroring the existing `ESP_RGB_VRAM_FILE` pattern).
   - On client connect, send a one-shot JSON header: `{ "w": W, "h": H, "format": "rgb565" | "x8r8g8b8" }`.
   - Then send raw frame bodies as binary WebSocket messages: `[u32 le seq][u32 le size][bytes pixels]`. One message = one frame. No diffs in v1.
   - Throttle to ~30 fps (reuse the existing `update_display_area()` / dirty-rect cadence inside `esp_rgb.c`).

2. **Implement the WebSocket server inside the device.**
   - Don't pull in libwebsockets unless trivial; QEMU already links
     libnice/glib + an HTTP-ish server for VNC. The cheapest route is
     probably `ws://` with a hand-rolled handshake (RFC 6455 frame format
     in <300 LoC C; reference: `qemu/ui/vnc-ws.c`).
   - Hook into the existing `update_display_area()` path so every time
     QEMU pushes a damaged region to its surface, we also push a frame to
     all connected clients. Use a `QIOChannel` non-blocking write so a
     stalled Chrome doesn't freeze the device.
   - Keep `ESP_RGB_VRAM_FILE` working for back-compat (don't remove the
     existing patch).

3. **Frontend page.** Add `web/qemu-direct.html` (sibling to the existing
   `web/index.html`): a single `<canvas>` + a tiny JS that opens
   `ws://localhost:9334/`, reads the header, then `decodeRGB565()`s each
   message into ImageData. ~80 LoC. Reuse `web/main.js`'s existing
   `decodeRGB565` helper.

4. **Acceptance test.** Add `tests/cdp/test_qemu_direct_canvas.py`:
   - Start QEMU with `ESP_RGB_WS_PORT=9334` against the existing built
     firmware (no firmware change required).
   - Open `web/qemu-direct.html` in Playwright.
   - Poll the canvas for `unique >= 8 && sum > 0` (same threshold as
     `tests/cdp/test_live_qemu_canvas.py`).
   - Assert that **`ESP_RGB_VRAM_FILE` is unset** for this test, so we
     prove the new path is independent of the old one.

5. **Package.** Add a `tools/run-direct-demo.sh` (or just an `--engine
   qemu-direct` flag to `tools/run-demo.sh`) that boots QEMU + opens the
   new page. Update README's Quickstart to offer both paths.

6. **Optional v2.** Multi-client broadcast, simple JPEG encoding for
   bandwidth, an HTTP `GET /` that serves the static page so Chrome
   doesn't need a separate `python -m http.server`.

### Files this work will touch

| Area | Path |
| --- | --- |
| Device source | `tools/qemu-src/hw/display/esp_rgb.c` |
| Device header | `tools/qemu-src/include/hw/display/esp_rgb.h` |
| WebSocket reference | `tools/qemu-src/ui/vnc-ws.c` |
| QEMU build (rebuild after edits) | `bash tools/build-qemu.sh` |
| Frontend | `web/qemu-direct.html`, reuses `web/main.js` `decodeRGB565` |
| Test | `tests/cdp/test_qemu_direct_canvas.py` |
| Launcher | `tools/run-direct-demo.sh` (new) or extend `tools/run-demo.sh` |
| Docs | `docs/qemu-native-fb.md` (Day 26+ section), README Quickstart |

### Acceptance criteria

- [ ] `bash tools/build-qemu.sh` produces a `qemu-system-xtensa` with the
      new device feature.
- [ ] Launching that QEMU against the **unmodified** ESP-IDF firmware
      (`main/main.c` not touched) and visiting `web/qemu-direct.html`
      shows the LVGL benchmark animating in Chrome at ~30 fps.
- [ ] `pytest -q tests/cdp/test_qemu_direct_canvas.py` passes with
      `ESP_RGB_VRAM_FILE` **unset**.
- [ ] The existing `pytest -q` suite (50 passed, 2 skipped) still passes
      — no regressions in the file-mmap path.
- [ ] No new firmware-side knobs; `main/qemu_vram.c`'s direct-VRAM
      gradient and `mirror_to_qemu_vram` calls remain functional but
      become **optional** (the new app developer simply doesn't do them).

### Why not on macOS?

The existing locally-built QEMU on macOS 12 is already pinned to a
patched 9.2.2 (`tools/build-qemu.sh`). Adding a network listener on
that build is doable but the test path is heavier (Apple Clang,
no `setsockopt(SO_REUSEPORT)` quirks, etc.). On Linux the upstream
QEMU build path is uncomplicated, and `qemu/ui/vnc-ws.c` compiles
out-of-the-box. **Develop on Linux first**; macOS support is a
follow-up if anyone wants it.

### Pointers / prior art inside this repo

- `tools/qemu-src/hw/display/esp_rgb.c` — device today; `update_rgb_surface()`,
  `update_display_area()`, the `ESP_RGB_VRAM_FILE_PATCH` block.
- `tools/qemu-src/include/hw/display/esp_rgb.h` — `ESPRgbState` fields,
  `ESP_RGB_MAX_*` constants.
- `tools/fb_server/shmem_producer.py` — host-side equivalent of what the
  new in-QEMU server should produce. Read its frame layout for inspiration.
- `web/main.js` (`decodeRGB565`) — frontend already knows how to decode
  RGB565 to a canvas.
- `tests/cdp/test_live_qemu_canvas.py` — pattern for the new
  acceptance test (Playwright + canvas polling).
- `docs/qemu-native-fb.md` — the design notebook from Days 18-23, has
  the full backstory of why we ended up where we are.

---

## NEXT-002 — QEMU Wi-Fi STA 支持（wpa_supplicant ctrl socket 桥接）

**Status:** ✅ **DONE** (Days 8–12, Linux).  
**Completed:** 2026-05-04. 80 passed, 0 failed.  
**Key commits:** b821968 (Day 8 scaffold), fd4f794 (Day 9 QEMU device), 5fb748e (Day 10 wpa_supplicant), f14e3aa (Day 11 event dispatch), 4dd93ec (Day 12 e2e test).

### Problem

ESP-IDF 官方的 Wi-Fi 示例（`examples/wifi/getting_started/station`、
`examples/wifi/scan` 等）在当前 QEMU 中**无法运行**：QEMU 的
`esp32` machine 没有任何 Wi-Fi 设备，`esp_wifi_init()` 会直接
panic 或返回 `ESP_ERR_NOT_SUPPORTED`。要让开发者在 QEMU 里验证
Wi-Fi 逻辑，必须在两个层面同时实现：

1. **QEMU 层**：新增一个虚拟 Wi-Fi 设备，该设备通过
   **wpa_supplicant ctrl socket**（`/var/run/wpa_supplicant/wlanX` 或
   用户指定路径）连接到宿主机上已运行的 wpa_supplicant，代为完成
   真实的 802.11 关联；
2. **ESP-IDF 层**：实现一套与该虚拟设备通信的"伪 Wi-Fi 驱动"，向
   应用层暴露与 ESP32-C3/C6 **完全相同**的公开 API 和事件系统，
   使任何按官方文档编写的 Wi-Fi 示例无需修改即可在 QEMU 中运行。

### 目标用户体验

```c
// 这段代码在真实 ESP32-C3/C6 上能跑，在 QEMU 里也应该能跑，不改一行：
esp_netif_create_default_wifi_sta();
wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
esp_wifi_init(&cfg);
esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &event_handler, NULL);
esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &event_handler, NULL);
esp_wifi_set_mode(WIFI_MODE_STA);
esp_wifi_set_config(WIFI_IF_STA, &wifi_config);
esp_wifi_start();
// → 期望：收到 WIFI_EVENT_STA_START → WIFI_EVENT_STA_CONNECTED
//         → IP_EVENT_STA_GOT_IP，s_ip_addr 已填入宿主机分配的 IP
```

API 兼容性覆盖范围（STA 阶段最低要求）：

| API / 事件 | 说明 |
|---|---|
| `esp_wifi_init / deinit` | 初始化与资源释放 |
| `esp_wifi_set_mode(WIFI_MODE_STA)` | 切换 STA 模式 |
| `esp_wifi_set_config(WIFI_IF_STA, …)` | 写入 SSID / password |
| `esp_wifi_start / stop` | 启动/停止 Wi-Fi 子系统 |
| `esp_wifi_connect / disconnect` | 触发关联 / 断联 |
| `esp_wifi_scan_start / get_ap_records` | 扫描 AP 列表 |
| `esp_wifi_get_mac` | 读取 MAC（取宿主机 wlan MAC） |
| `WIFI_EVENT_STA_START/STOP` | 状态事件 |
| `WIFI_EVENT_STA_CONNECTED/DISCONNECTED` | 关联事件 |
| `IP_EVENT_STA_GOT_IP` | DHCP 获得 IP 事件 |

### 技术路线

> 以下描述两个必须实现的层次及其职责边界。**固件与 QEMU 设备之间的具体通信机制**（寄存器布局、中断方案、消息格式等）由实施者在详细设计阶段确定，不在本 item 中预先锁定。

#### 1. QEMU 虚拟 Wi-Fi 设备（`esp_wifi` device）

```
  ESP-IDF firmware
       │  （固件-设备通信接口，具体机制由实施者确定）
       ▼
  QEMU esp_wifi device
       │  Unix domain socket
       ▼
  宿主机 wpa_supplicant
  （通过 ctrl_iface 发 ATTACH / SCAN / ADD_NETWORK /
    SELECT_NETWORK / STATUS / DISCONNECT 等命令）
       │
       ▼
  宿主机真实 Wi-Fi NIC  ←→  AP
```

- 挂到 esp32 machine，注册为可寻址的虚拟设备。
- 设备内部维护状态机：`IDLE → SCANNING → ASSOCIATING →
  CONNECTED → DISCONNECTED`，状态变化时通知固件侧驱动，
  驱动再分发对应 ESP-IDF 事件。
- wpa_supplicant ctrl socket 通信必须是异步非阻塞的，不能阻塞 vCPU 线程。
- 设备参数通过命令行选项或环境变量传入 wpa_supplicant ctrl socket 路径。
- DHCP：关联成功后，从 wpa_supplicant `STATUS` 或宿主机网络接口获取
  已分配 IP，传递给驱动构造 `ip_event_got_ip_t` 事件上报。
  （v1 不需要在 QEMU 内部运行完整 DHCP 协议栈。）

#### 2. ESP-IDF 虚拟 Wi-Fi 驱动（component）

- 以 ESP-IDF component 形式实现，通过 `sdkconfig` 选项
  `CONFIG_ESP_WIFI_QEMU=y` 替换官方驱动，真实硬件编译时不引入任何代码。
- 必须实现全部公开 `esp_wifi_*` API（STA 模式所需子集），
  使应用层代码无需区分运行环境。
- 事件上报：向 `esp_event_loop` post `WIFI_EVENT_*` / `IP_EVENT_*`，
  事件类型和参数结构体与官方驱动完全一致。
- 创建 `esp_netif` 实例并绑定虚拟驱动，使 `esp_netif_get_ip_info()`
  等接口返回正确结果。

### Concrete subtasks（in order）

1. **设计固件-设备通信协议**（spec 文档）
   - 确定固件与 QEMU 虚拟设备之间的通信机制（形式不限）；
   - 定义命令/响应/异步事件的报文格式，覆盖 SCAN、
     CONNECT、DISCONNECT、GET_MAC 及对应的响应/异步事件；
   - 确定 IP 信息（地址/掩码/网关）的传递方式。

2. **实现 QEMU `esp_wifi` device**
   - 注册到 esp32 machine；
   - wpa_supplicant ctrl socket 异步 I/O；
   - 状态机 + 固件通知机制；
   - 构建系统条目（meson.build 或等效）。

3. **实现 ESP-IDF component `esp_wifi_qemu`**
   - 完整的 `esp_wifi_*` API 实现（仅 STA 模式所需子集）；
   - 事件上报：`WIFI_EVENT_*` / `IP_EVENT_*`，与官方驱动一致；
   - `esp_netif` 绑定，`IP_EVENT_STA_GOT_IP` 事件中携带正确 IP；
   - `sdkconfig` 选项 `CONFIG_ESP_WIFI_QEMU`，由 `sdkconfig.defaults`
     在 QEMU target 下自动启用。

4. **验证：跑通官方 station 示例**
   - 将 `examples/wifi/getting_started/station` 的 `app_main.c`
     复制进本仓库的 `examples/wifi_sta/`（不修改业务代码）；
   - 在 QEMU 中启动，观察串口输出：
     ```
     I (xxx) wifi_sta: connected to ap SSID:MyAP password:MyPass
     I (xxx) wifi_sta: got ip:192.168.x.x
     ```

5. **自动化测试**
   - `tests/test_qemu_wifi_sta.py`：启动 QEMU（带 `esp_wifi` 设备），
     捕获串口输出，断言 `got ip:` 行出现（timeout 30 s）；
   - 需要宿主机有可用 Wi-Fi 接口 + wpa_supplicant，否则 skip。

6. **文档**
   - `docs/qemu-wifi.md`：架构图、wpa_supplicant 配置步骤、
     `sdkconfig` 开关说明、已知限制（AP 模式、WPA3 等留待后续）。

### Files this work will touch / create

| Area | Path |
|---|---|
| QEMU 设备实现 | `tools/qemu-src/hw/net/esp_wifi.c` (new) |
| QEMU 设备头文件 | `tools/qemu-src/include/hw/net/esp_wifi.h` (new) |
| QEMU machine 注册 | `tools/qemu-src/hw/xtensa/esp32.c` |
| QEMU meson 构建 | `tools/qemu-src/hw/net/meson.build` |
| ESP-IDF component | `components/esp_wifi_qemu/` (new) |
| sdkconfig 默认值 | `sdkconfig.defaults` (add `CONFIG_ESP_WIFI_QEMU=y`) |
| 示例代码 | `examples/wifi_sta/main/app_main.c` (copy from ESP-IDF) |
| 自动化测试 | `tests/test_qemu_wifi_sta.py` (new) |
| 文档 | `docs/qemu-wifi.md` (new) |
| QEMU 编译脚本 | `tools/build-qemu.sh` (add net/esp_wifi.c) |

### Acceptance criteria

- [ ] `bash tools/build-qemu.sh` 产出包含 `esp_wifi` 设备的
      `qemu-system-xtensa`，无编译错误。
- [ ] 官方 `examples/wifi/getting_started/station` 的 `app_main.c`
      **不修改一行**，通过 `sdkconfig` 切换驱动后在 QEMU 中能
      成功启动并打印 `got ip:`。
- [ ] `pytest -q tests/test_qemu_wifi_sta.py` 在有 wpa_supplicant
      可用的 Linux CI 环境中通过。
- [ ] 现有 `pytest -q` 套件（50 passed, 2 skipped）无回归。
- [ ] 真实 ESP32-C3/C6 编译时，`CONFIG_ESP_WIFI_QEMU` 未启用，
      不引入任何额外代码或依赖。

### Known limitations（v1 scope）

- **仅 STA 模式**；AP / SoftAP、Wi-Fi Direct 留待后续 item。
- **WPA2-Personal 只**；WPA3、EAP 企业级认证暂不支持。
- **不在 QEMU 内部运行 TCP/IP 栈**；IP 由宿主机 DHCP 分配后直接
  透传，`lwIP` 数据面可选——v1 仅验证事件与 IP 获取，不强制要求
  应用层 TCP/UDP 数据通路可用。
- macOS 暂不支持（wpa_supplicant ctrl socket 路径差异大）。

### Prior art / references

- [esp-hosted-ng](https://github.com/espressif/esp-hosted-ng) —
  包含一套 ESP-IDF 侧 `esp_wifi` API shim 实现，可作为可选参考
  （用户原话：「也许 esp-hosted 的某个项目的接口是个可能的参考源头」）
- QEMU `hw/net/virtio-net.c`，`hw/net/e1000.c` — QEMU 网卡设备实现范式
- `tools/qemu-src/hw/display/esp_rgb.c` — 本项目已有的自定义设备，
  设备注册与通知机制可参考
- wpa_supplicant ctrl_iface 文档：`wpa_supplicant/ctrl_iface.c` +
  `wpa_supplicant/wpa_cli.c`（ATTACH / SCAN / ADD_NETWORK / STATUS
  命令格式）

---

## Other backlog items (lower priority)

(none yet — add new entries above this line)

---

## NEXT-003 — LVGL + Wi-Fi 集成 Demo（QEMU 无硬件全流程验证）

**Status:** ✅ **DONE** (Days 15–16, Linux).  
**Completed:** 2026-05-05.  73 passed (65 non-QEMU-runtime + 8 new source checks), 0 failed.  
**Key commits:** a80240c (Day 15 LVGL+Wi-Fi firmware), Day 16 log + test + run-direct-demo.sh.

### Design note: API-level simulation
The `esp_wifi_qemu` component simulates the *public `esp_wifi_*` API*, not the
ESP32 hardware register map. The MMIO registers in `esp_wifi_qemu.h` are a custom
firmware↔QEMU communication channel constrained to offsets `< 0x144` to avoid the
RNG device. Tests validate at the API/event level (`got ip:` in serial log).

### Problem

NEXT-001（QEMU 帧缓冲 → Chrome）和 NEXT-002（QEMU Wi-Fi STA）
已分别验证了显示和网络两条路径，但两者目前是**独立的**示例：
- `main/main.c` 跑 LVGL benchmark，无任何网络逻辑
- `examples/wifi_sta/` 跑 Wi-Fi 连接，无任何显示逻辑

真实的 ESP32 IoT 产品通常需要同时运行 LVGL 界面 **和** Wi-Fi 通信。
本 item 将两者合并为一个可在 QEMU 中端到端验证的集成 Demo。

### 目标用户体验

1. 执行 `bash tools/run-direct-demo.sh` 启动 QEMU；
2. 打开 `web/qemu-direct.html`，看到 LVGL 界面显示**连接进度**：
   - 「Wi-Fi Connecting…」→ 「Connected: 192.168.x.x」
3. 串口日志同时打印：`I (xxx) demo: got ip:192.168.x.x`
4. 整个流程无需真实 ESP32 硬件。

### Concrete subtasks（in order）

1. **创建 `main/wifi_ui.c` + `main/wifi_ui.h`**
   - 在 LVGL 上绘制一个简单状态标签（`lv_label`）
   - 提供 `wifi_ui_set_status(const char *msg)` API
   - 主 app 在 Wi-Fi 事件回调中调用该 API 更新界面

2. **修改 `main/main.c`**（最小改动）
   - 在 `app_main` 中初始化 Wi-Fi + 注册事件处理函数
   - `WIFI_EVENT_STA_CONNECTED` 时调用 `wifi_ui_set_status("Connected: ...")`
   - `IP_EVENT_STA_GOT_IP` 时打印 `got ip:`（和 wifi_sta 示例一致）
   - SSID/密码通过 `sdkconfig` menuconfig 配置（`CONFIG_DEMO_WIFI_SSID` /
     `CONFIG_DEMO_WIFI_PASSWORD`）；QEMU 默认值写入 `sdkconfig.defaults`

3. **添加 Kconfig 选项**（`main/Kconfig.projbuild`）
   - `DEMO_WIFI_SSID` string，default `"QEMU_TEST"`
   - `DEMO_WIFI_PASSWORD` string，default `"qemu1234"`

4. **更新 `tools/run-direct-demo.sh`**
   - 启动 mock-wpa-supplicant（`tools/mock_wpa_supplicant.py`）
   - 启动 QEMU（带 `WIFI_CTRL_SOCKET` 指向 mock 的 socket 路径）
   - 启动 HTTP server serving `web/`

5. **自动化测试 `tests/test_qemu_integrated_demo.py`**
   - 启动 mock-wpa-supplicant + QEMU
   - 断言串口出现 `got ip:` (timeout 30s)
   - 通过 WebSocket 连接 `ws://localhost:9334/` 断言帧缓冲有内容
     （canvas unique ≥ 8，类似 `test_qemu_direct_canvas.py`）

### Files this work will touch / create

| Area | Path |
|---|---|
| 新模块 | `main/wifi_ui.c`, `main/wifi_ui.h` (new) |
| 修改入口 | `main/main.c` (add Wi-Fi init + event handler) |
| Kconfig | `main/Kconfig.projbuild` (new) |
| sdkconfig 默认 | `sdkconfig.defaults` (add DEMO_WIFI_* defaults) |
| 启动脚本 | `tools/run-direct-demo.sh` (add mock-wpa + QEMU wifi flag) |
| 测试 | `tests/test_qemu_integrated_demo.py` (new) |

### Acceptance criteria

- [ ] `idf.py build` 零警告，固件包含 LVGL + Wi-Fi 逻辑。
- [ ] `bash tools/run-direct-demo.sh` 在 QEMU 中启动，打开
      `web/qemu-direct.html` 可以看到 LVGL 界面从「Connecting…」
      变为「Connected: 192.168.x.x」。
- [ ] 串口输出 `got ip:` 行出现（和 NEXT-002 的 wifi_sta 验证一致）。
- [ ] `pytest -q tests/test_qemu_integrated_demo.py` 通过。
- [ ] 现有测试套件（93 passed, 1 skipped）无回归。
- [ ] 不需要真实 ESP32 硬件、路由器、或 wpa_supplicant 守护进程。

### Known limitations（v1 scope）

- LVGL UI 极简（单标签），仅作集成验证，不追求美观。
- SSID/密码以明文写入 `sdkconfig.defaults`（QEMU 测试专用值），
  生产代码应使用 NVS 或 Provisioning。
- 不实现真实 TCP/UDP 数据通路（继承 NEXT-002 的限制）。

---

## Day 21 Architecture Review — Wi-Fi Emulation Bug Backlog

Full analysis: see `docs/daily-logs/day-021-linux.md`.

### BUG-004 — wifi_qemu_send_cmd() accepts any event (race condition)

**Status:** Open. Scheduled for Day 22.

`wifi_qemu_send_cmd()` polls `WIFI_REG_EVENT` and ACKs the first non-NONE
event regardless of type. Two failure modes:

1. A stale event from a previous command satisfies the next command's wait.
2. `wifi_event_task` (10 ms polling) can race with `wifi_qemu_send_cmd` to
   consume synchronous response events (INIT_DONE, START_DONE, STOP_DONE).

**Fix plan**: For synchronous commands, `wifi_event_task` must not consume
events. Add a `volatile bool s_cmd_in_flight` flag. When `wifi_qemu_send_cmd`
is active, `wifi_event_task` skips the ACK loop. Alternatively, add a
command-to-event mapping table so each command only accepts its designated
response event.

---

### BUG-005 — pkt_relay_open() called at CMD_CONNECT, not CMD_INIT

**Status:** Open. Scheduled for Day 22.

The packet relay socket is opened during `WIFI_CMD_CONNECT` handling. If
`ESP_WIFI_PKT_SOCKET` does not exist at that moment, data-plane is silently
disabled with no retry. ARP / DHCP frames in the window between CONNECT and
GOT_IP may be lost.

**Fix plan**: Attempt `pkt_relay_open()` at `WIFI_CMD_START` time, with a
warning if the socket is unavailable. Keep the `CMD_CONNECT` call as a fallback.

---

### BUG-006 — pkt_relay_send() treats EAGAIN as fatal

**Status:** Open. Low priority.

`pkt_relay_send()` closes the relay connection on any `send()` error including
EAGAIN. Since the socket is non-blocking, a momentary backlog could silently
kill data-plane connectivity.

**Fix plan**: Check for `EAGAIN`/`EWOULDBLOCK` and implement a small TX retry
loop before declaring failure.

---

### GAP-001 — No DHCP in wifi_packet_relay.py

**Status:** Open. Medium priority.

The relay does not implement DHCP. IP assignment comes exclusively from the
wpa_supplicant STATUS ctrl message. A firmware that enables `DHCPC` would
never receive a lease.

**Fix plan**: Add a minimal DHCP server to `wifi_packet_relay.py` that always
offers `10.0.2.15/24, gw=10.0.2.2, dns=8.8.8.8`. This also eliminates the
ctrl-plane / data-plane IP split (ARCH-002).

---

### GAP-003 — Missing esp_wifi_restore() and bandwidth API stubs

**Status:** Open. Low priority.

`esp_wifi_restore()`, `esp_wifi_get_bandwidth()`, `esp_wifi_set_bandwidth()`,
`esp_wifi_get_channel()`, `esp_wifi_set_channel()`, `esp_wifi_get_country()`,
`esp_wifi_set_country()`, `esp_wifi_get_ps()`, `esp_wifi_set_ps()` are not
implemented. Calls from application code would fall through to the real
hardware driver and likely panic in QEMU.

**Fix plan**: Add no-op / stub implementations returning `ESP_OK` or
`ESP_ERR_NOT_SUPPORTED` in a new `esp_wifi_extras.c`.

---

### ARCH-001 — Single-value event register, no event queue

**Status:** Open. Long-term technical debt.

`WIFI_REG_EVENT` holds exactly one pending event. New events overwrite
unacknowledged ones. The proper fix is a two-register design:
- `WIFI_REG_CMD_RESULT` (0x010): synchronous command response code
- `WIFI_REG_ASYNC_EVT` (0x014): asynchronous event queue head

This is a breaking MMIO protocol change requiring firmware and QEMU side
updates simultaneously.

---

### ARCH-002 — ctrl-plane and data-plane IP address spaces are independent

**Status:** Partially mitigated (Day 21: aligned both to 10.0.2.x). Long-term
debt remains until GAP-001 (DHCP) is implemented so the relay is the
single source of IP truth.
