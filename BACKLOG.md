# Backlog — Day 42+ (Wi-Fi API finalization)

Focused backlog for the next iteration. Historical entries (Days 4–41,
covering framebuffer, lwIP socket proof, basic STA/SCAN/AP release, real
hardware scan via wpa_cli, scan-record field completeness) live in
[`docs/BACKLOG-archive-pre-day42.md`](docs/BACKLOG-archive-pre-day42.md).

---

## ★★★ North star (unchanged)

> **Any Wi-Fi sample under `$IDF_PATH/examples/wifi/**` must run on our
> QEMU Wi-Fi simulator without modifying its `.c` / `.h`. Only top-level
> `CMakeLists.txt` and `sdkconfig` may differ to select the QEMU
> overlay component.**

A given sample is "supported" when:
- [ ] `main/*.c` / `main/*.h` are byte-identical to upstream.
- [ ] Only project `CMakeLists.txt` / `sdkconfig.defaults` differ (overlay).
- [ ] `idf.py build` succeeds with zero warnings.
- [ ] Runtime smoke produces the sample's expected log line(s).
- [ ] No real ESP32 hardware required.

---

## State as of Day 41 (2026-05-07)

### What works

- STA mode: connect / disconnect / GOT_IP, real wpa_supplicant on host.
- Scan mode: real APs from host hardware (wpa_cli backend).
  Day 41: `wifi_ap_record_t` carries real **MAC, RSSI, SSID, channel,
  authmode, pairwise_cipher, group_cipher, WPS** (no longer hardcoded).
- SoftAP mode: build + boot OK; events fire; station list always empty.
- TCP/UDP socket data plane via `wifi_packet_relay.py`.
- Stock samples that build & runtime-pass:
  `wifi/getting_started/station`, `wifi/scan`, `wifi/getting_started/softAP`,
  `protocols/sockets/tcp_client`, `protocols/sockets/udp_client`.
- Stock samples that **build clean** with zero source diff (build-only
  coverage in the release smoke gate, Day 48):
  `wifi/fast_scan` (exercises Phase A connection AP record + Phase B
  channel/auth/cipher), `wifi/power_save` (exercises Phase C
  `esp_wifi_set_ps` round-trip).  Runtime is gated on Kconfig SSID /
  console UART input that the smoke harness does not provision.
- Day 49 — `wifi/softap_sta` joins the build-only set: it is the only
  stock sample that runs APSTA mode, so building it against the QEMU
  overlay is the strongest single proof that Phase A + B + C + D-1 +
  D-2 link together for one firmware image.  Runtime is gated on a
  configured upstream STA SSID and on lwIP NAPT.
- 90 tests green (87 baseline + 3 Day 41 source-analysis tests).

### What is still a stub (the gap this backlog closes)

`components/esp_wifi_qemu/esp_wifi_extras.c`,
`components/esp_wifi_qemu/esp_wifi_ap.c`,
`components/esp_wifi_qemu/esp_wifi_promisc.c` contain ~25 functions
that just `return ESP_OK` or hand back a hardcoded fake. They satisfy
the linker but produce wrong runtime data for stock samples that
**read** state (e.g. `iperf` checks bandwidth, `fast_scan` checks
channel, mqtt prints `sta_get_ap_info`, sniffer wants real promiscuous
RX, etc.). The remaining north-star push is to make these APIs return
**real values driven by the QEMU device** — exactly the same treatment
Day 41 applied to scan results.

---

## Day 42+ work plan — Phases A–E

Phases are in priority order. Each phase is one or more days of work.
Acceptance is a stock ESP-IDF sample that exercises that API, plus
green pytest.

---

### ★ Phase A — Connection-time AP record (P0, Day 42) ✅ DONE

**Goal:** Eliminate the hardcoded `s_fake_ap` in `esp_wifi_sta_get_ap_info`
and the `-50` constant in `esp_wifi_sta_get_rssi`. Both must return the
**actual** AP record from the connection that just succeeded, identical
to what `esp_wifi_scan_get_ap_records` now produces.

#### Files

- `tools/qemu-src-patches/hw/net/esp_wifi.c` — when STATUS reply parses
  `bssid=` / `ssid=` / `freq=` / `key_mgmt=` / `pairwise_cipher=` /
  `group_cipher=` / `signal=`, store them as `s->connected_ap` (new
  struct field, mirror of `ESPWifiScanResult`).
- `tools/qemu-src-patches/include/hw/net/esp_wifi.h` — add `connected_ap`
  field + new MMIO regs `WIFI_REG_CONN_AP_*` (one read register per
  field at offsets 0x134–0x143; total IO size 0x144 — still room before
  RNG conflict).
- `components/esp_wifi_qemu/include/esp_wifi_qemu.h` — mirror new regs.
- `components/esp_wifi_qemu/esp_wifi_extras.c` — `sta_get_ap_info` reads
  regs; `sta_get_rssi` reads the dedicated rssi reg (reuse existing
  `WIFI_REG_SCAN_RSSI` indexed via a "current connection" sentinel, OR
  introduce `WIFI_REG_CONN_RSSI`).
- `tools/mock_wpa_supplicant.py` — proxy `wpa_cli status` (real backend)
  or fabricate a STATUS that includes `signal=-N` and `key_mgmt=…`.
- `tests/test_qemu_wifi_sta.py` — new source-analysis test asserting
  `s_fake_ap` is gone and the new regs are read; new runtime assertion
  on station example log "RSSI" line varying per run with REAL_SCAN=1.

#### Acceptance

- [x] In `wifi/getting_started/station` runtime, `esp_wifi_sta_get_ap_info`
      after GOT_IP returns the SSID/BSSID/RSSI from wpa_supplicant
      STATUS — not the hardcoded `QEMU_TEST` / `AA:BB:…` fake.
- [x] `esp_wifi_sta_get_rssi` matches `signal_level=` from `wpa_cli status`
      (no longer hardcoded -50).
- [x] Source-analysis tests assert `s_fake_ap` and `-50` constants are gone
      and the 4 new MMIO regs are read.

---

### Phase B — Channel / country / protocol (P0, Day 43) ✅ DONE

**Goal:** Stock samples (`fast_scan`, `iperf`, `wifi_country`) read
`esp_wifi_get_channel` / `_get_country` / `_get_protocol` to display
or branch on the current state. Today they all return zero-initialized
or default values. Make these **track what the firmware just wrote**,
plus seed initial values from wpa_supplicant where applicable.

#### Subtasks

1. Add device-side state: `s->channel_primary`, `s->channel_second`,
   `s->country[3]`, `s->protocol_bitmap[2]` (per IF), `s->bandwidth[2]`,
   `s->max_tx_power`. Expose as MMIO read/write registers.
2. Firmware setters write the reg (replace current `return ESP_OK`).
   Firmware getters read the reg.
3. Initial channel comes from connected AP's freq (Phase A reuse).
4. `set_channel` is allowed only when STA is **stopped or
   promiscuous** (matches IDF doc). Validate and return
   `ESP_ERR_INVALID_STATE` otherwise.
5. New tests assert round-trip read-after-write.

#### Acceptance

- [x] `esp_wifi_set_channel(11, …)` followed by
      `esp_wifi_get_channel(&p, &s)` returns 11.
- [x] After connect, `get_channel` returns the AP's channel by reading
      `WIFI_REG_CONN_FREQ_RSSI_AUTH` (Phase A reuse).
- [x] `esp_wifi_set_country({.cc="US",…})` round-trips through `s_country`.
- [x] `set_max_tx_power` / `_get_max_tx_power` round-trip with IDF
      0.25-dBm range validation (8..84).
- [x] `set_bandwidth` / `set_protocol` are now per-interface (STA + AP).
- [x] Stock `wifi/scan` and `wifi/getting_started/station` still build
      with the new shim, no warnings.

**Implementation note:** No new MMIO registers were added — the device-side
IO range is already at the 0x144 hard limit (RNG sits at +0x144). Phase B
is implemented as firmware-only round-trip storage in `esp_wifi_extras.c`,
which is sound because QEMU has no real PHY for these settings to affect.
The one cross-component dependency is `get_channel` reusing the Phase-A
`WIFI_REG_CONN_FREQ_RSSI_AUTH` register so a connected client's reported
channel still matches the AP.

---

### Phase C — Power save & event mask (P1, Day 44) ✅ DONE

**Goal:** `esp_wifi_set_ps` / `_get_ps`, `_set_event_mask` /
`_get_event_mask`, `_set_inactive_time`. These are state-bearing
no-ops today. Stock `power_save` and `iperf` read `get_ps` to print
the mode. Real PS semantics in QEMU are meaningless (no radio), but
**round-trip storage** must work.

#### Subtasks

1. Add `s->ps_type`, `s->event_mask`, `s->inactive_time` device state
   with MMIO accessors.
2. `esp_wifi_set_ps(WIFI_PS_NONE | _MIN_MODEM | _MAX_MODEM)` — write
   reg, return OK; `get_ps` reads back.
3. `event_mask` is purely informational in QEMU — store + return.
4. (Optional) emit an `info_report` if firmware enables an event we
   don't actually fire (e.g. `WIFI_EVENT_STA_BEACON_TIMEOUT`) so we
   know which events stock samples expect.

#### Acceptance

- [x] `esp_wifi_set_ps(WIFI_PS_MAX_MODEM)` then `esp_wifi_get_ps(&t)`
      returns `WIFI_PS_MAX_MODEM`. Invalid enum values rejected.
- [x] `esp_wifi_set_event_mask(0xDEAD)` round-trips through `s_event_mask`.
- [x] `esp_wifi_set_inactive_time(STA, 30)` round-trips per interface;
      sub-10s values rejected per IDF spec.
- [x] No regressions on existing samples (stock scan + station rebuild
      cleanly).

#### Day-45 follow-up (committed separately)

- Round-trip storage added for `esp_wifi_set/get_promiscuous`,
  `set/get_promiscuous_filter`, `set/get_promiscuous_ctrl_filter` in
  `esp_wifi_promisc.c`. `set_promiscuous(true)` no longer returns
  `ESP_ERR_NOT_SUPPORTED` (state stored; raw RX delivery still Phase E).

---

### Phase D — SoftAP station list & DHCP (P1, Day 45–46)

**Goal:** SoftAP is currently boot-only. `esp_wifi_ap_get_sta_list`
returns empty. Stock `softAP` example expects to log
`station <MAC> join, AID=<n>` on `WIFI_EVENT_AP_STACONNECTED`. This
needs a fake station injector (or two QEMU instances cross-connected
via `wifi_packet_relay.py`).

#### Day-45 progress (firmware-only slice — committed)

- [x] `esp_wifi_ap.c` keeps a real `s_ap_table[ESP_WIFI_MAX_CONN_NUM]`
      with MAC / AID / RSSI / phy_mode entries.
- [x] `esp_wifi_start()` injects `CONFIG_ESP_WIFI_QEMU_AP_FAKE_CLIENTS`
      synthetic stations on AP/APSTA mode start, posting a
      `WIFI_EVENT_AP_STACONNECTED` event for each (deterministic
      locally-administered MACs `02:51:45:00:00:NN`, AID = NN+1).
- [x] `esp_wifi_ap_get_sta_list()` walks the table; `esp_wifi_deauth_sta`
      removes entries (or all when `aid==0`) and posts
      `WIFI_EVENT_AP_STADISCONNECTED`; `esp_wifi_ap_get_sta_aid` does
      a real MAC lookup.
- [x] Stock `examples/wifi/getting_started/softAP/` runtime:
      `station 02:51:45:00:00:00 join, AID=1` and `AID=2` log lines
      now fire — first time ever.
- [x] Kconfig adds `ESP_WIFI_QEMU_AP_FAKE_CLIENTS` (range 0..4,
      default 2). 0 keeps the legacy empty-AP behaviour.

#### Day-46 remaining work

#### Subtasks

1. **v1 DHCP server**: extend `wifi_packet_relay.py` with a tiny DHCP
   server (UDP/67) that hands `192.168.4.2 / .3` leases to the fake
   MACs and fires `IP_EVENT_AP_STAIPASSIGNED`.
2. (Optional) cross-instance: add `--ap-fake-clients=N` CLI to the
   relay so it can drive the join events from the host side instead
   of firmware-injected.
3. Pytest: assert `softAP` log contains `station … join` and the
   subsequent `IPASSIGNED` line.

#### Acceptance

- [x] Stock `softAP` runtime: `wifi_ap_get_sta_list` reports 2 entries
      with non-zero MACs.
- [x] `WIFI_EVENT_AP_STACONNECTED` fires twice with deterministic AIDs.
- [x] `IP_EVENT_AP_STAIPASSIGNED` fires twice (Day-46): deterministic
      192.168.4.2 / 192.168.4.3 leases stored in `s_ap_table[].assigned_ip`.

---

### Phase E — Promiscuous RX (P2, Day 47)

**Goal:** Stock `network/simple_sniffer` and `wifi/fast_scan` use
promiscuous mode to capture frames. Today
`esp_wifi_set_promiscuous(true)` returns OK but no callback fires.

#### Approach

QEMU device gets a new packet path: when promiscuous is on, the
existing RX path (already wired to `wifi_packet_relay.py`) **also**
delivers frames to the promisc callback after wrapping them in a
fabricated 802.11 header (subtype DATA, BSSID = our virtual AP MAC).
Real 802.11 management/control frames are out of scope.

#### Day-47 progress (firmware-only slice — committed)

- [x] `esp_wifi_promisc.c` stores `s_promisc_rx_cb` from
      `esp_wifi_set_promiscuous_rx_cb()`.
- [x] New helper `qemu_promisc_deliver_eth(eth, len, from_tx)` wraps
      an Ethernet frame in a fabricated 802.11 DATA header (24 B) +
      LLC/SNAP shim (8 B). FromDS / ToDS bit + ADDR1/2/3 ordering
      flips with `from_tx`. Virtual BSSID `02:51:45:00:00:FF`.
      Guarded by `s_promisc_enabled && s_promisc_rx_cb &&
      (filter & WIFI_PROMIS_FILTER_MASK_DATA)`.
- [x] `esp_wifi_netif.c` taps both directions:
      `qemu_wifi_transmit()`, `qemu_wifi_tx_raw()`, and
      `esp_wifi_netif_rx_frame()` all call the deliver helper before
      the MMIO / lwIP step.
- [x] Frame structure passes 4 source-analysis tests (cb storage,
      deliver helper, both netif taps).

#### Day-48 — `esp_wifi_80211_tx` implemented

- [x] `esp_wifi_promisc.c::esp_wifi_80211_tx` no longer returns
      `ESP_ERR_NOT_SUPPORTED`.  Implements: (1) per-type filter-mask
      loopback to `s_promisc_rx_cb` (MGMT / CTRL / DATA / MISC), with
      `WIFI_PKT_*` type tag derived from the FC byte; (2) DATA-frame
      LLC/SNAP de-encapsulation back to Ethernet and injection onto the
      virtual wire via a new `qemu_wifi_tx_raw_no_promisc()` helper,
      which avoids double-tapping the sniffer (the raw frame is the
      authoritative representation, the fabricated Ethernet wrap would
      duplicate it).
- [x] Address-field decode honors ToDS / FromDS combinations
      (STA→AP, AP→STA); IBSS / WDS get the loopback only.
- [x] `en_sys_seq` honored: when true, SEQ field is forced to 0 in the
      delivered pkt (we have no real sequence counter).
- [x] Two new source-analysis tests in `test_qemu_wifi_sta.py`:
      `test_phase_e_80211_tx_implemented` (asserts no `ESP_ERR_NOT_SUPPORTED`,
      per-type mask switch, raw-frame loopback, no-promisc TX use),
      `test_phase_e_no_promisc_tx_helper` (validates the new MMIO-only
      helper does not re-tap the sniffer).

#### Remaining

- [x] **Day 48 — tooling unblocked**: `tools/build-stock-sample.sh`
      now (a) symlinks any `partitions*.csv` from the sample root into the
      wrapper project root so `CONFIG_PARTITION_TABLE_CUSTOM_FILENAME`
      relative-path lookups resolve, (b) parses the sample's
      `main/CMakeLists.txt` and merges its `REQUIRES` + `PRIV_REQUIRES`
      with our base set (de-duped), so samples needing extra components
      (`console`, `fatfs`, `esp_eth`, `app_trace`, `unity`, ...) link
      with zero source diff, (c) symlinks the sample's main
      `idf_component.yml` so managed-component manifests are honored,
      (d) accepts an `EXTRA_SDKCONFIG_DEFAULTS` env var for runtime
      overrides allowed by the zero-diff policy.  Verified by a
      synthetic-sample pytest (`test_build_stock_sample_handles_custom_
      partitions_and_priv_requires`).
- [ ] Live runtime smoke with stock `network/simple_sniffer` —
      tooling now generates a clean wrapper, but this host blocks
      `https://components-file.espressif.com/`, so the sample's managed
      `espressif/pcap` dependency cannot be fetched.  Re-run on a
      machine with component-registry access to close.
- [ ] Capture management/control frame fabrication when stock
      samples need beacons (Phase F sub-item).

#### Acceptance

- [x] No crashes when promiscuous is enabled mid-connection
      (TX/RX taps are guarded; no path forced).
- [x] Frame layout validated against IDF `wifi_promiscuous_pkt_t`
      (4 source-analysis tests).
- [ ] Stock `simple_sniffer` runtime captures ≥10 frames/sec
      (deferred until tooling supports the sample's partition layout).

---

### Phase F — Long-tail (P3, no fixed day)

Items below are scheduled only if a stock sample explicitly requires
them and the user asks. Each is its own future workday.

| ID | Area | Stock samples impacted |
|----|------|------------------------|
| F-1 | ESPNOW (`esp_now_*`) | `wifi/espnow/` |
| F-2 | WPS / SmartConfig | `wifi/wps/`, `wifi/smartconfig/` |
| F-3 | WPA2-Enterprise | `wifi/wpa2_enterprise/` |
| F-4 | iTWT (`esp_wifi_sta_itwt_*`) | `wifi/itwt/` |
| F-5 | CSI | CSI samples (none in `examples/wifi/`) |
| F-6 | DNS proxy in relay | many — `pool.ntp.org`, etc. |
| F-7 | IPv6 link-local + multicast | `protocols/sntp/` |
| F-8 | NAT to real internet | OTA samples, mqtt over public broker |

---

## Cross-cutting non-API work

### CC-1 — Stub audit test (Day 42 quick-win) ✅ DONE (Day 48)

`tests/test_no_hardcoded_ap_info.py` greps the `esp_wifi_qemu`
component for the four Phase-A regression tokens (`s_fake_ap`,
`"QEMU_TEST"`, the `-50` RSSI constant, and the
`{0xAA,0xBB,0xCC,0xDD,0xEE,0xFF}` BSSID byte sequence) plus a
non-vacuity check that asserts the four Phase-A connection MMIO regs
are still actually read by `esp_wifi_extras.c`. Comments and string
literals are filtered separately so legitimate documentation can
still mention the historical behaviour.  An `ALLOWLIST` dict gives
future code an escape hatch with mandatory justification.  Verified
both directions: 6 tests pass on the current tree, all four token
checks fire on synthetic relapse input.

### CC-2 — Skill follow-up

`docs/skill-feedback.md` should grow an entry per phase summarizing
which `automated-testing` patterns worked / didn't (e.g. how to write
a runtime test that varies between machines because real Wi-Fi APs
differ).

---

## Out of scope (explicitly)

- Real 802.11 PHY / MAC modeling. We simulate the **public ESP-IDF
  API**, not the radio.
- `esp_wifi_ftm_*` (fine-time measurement) — no client demand.
- Mesh (`esp_mesh_*`) — separate component, separate backlog if ever.
- macOS support — Linux-only until a user asks.
- Large refactors. Per `code-refactoring` skill, refactor only when a
  health threshold trips.

---

## Reference: API surface still returning fake data (Day 41 audit)

Source: `git grep -nE "return ESP_OK|s_fake_ap|stub" components/esp_wifi_qemu/`

| File | Function | Current behavior | Phase |
|------|----------|------------------|-------|
| `esp_wifi_extras.c` | `esp_wifi_sta_get_ap_info` | hardcoded `s_fake_ap` | A |
| `esp_wifi_extras.c` | `esp_wifi_sta_get_rssi` | constant `-50` | A |
| `esp_wifi_extras.c` | `esp_wifi_set_channel` / `_get_channel` | no storage | B |
| `esp_wifi_extras.c` | `esp_wifi_set_country` / `_get_country` | no storage | B |
| `esp_wifi_extras.c` | `esp_wifi_set_protocol` / `_get_protocol` | no storage | B |
| `esp_wifi_extras.c` | `esp_wifi_set_bandwidth` / `_get_bandwidth` | no storage | B |
| `esp_wifi_extras.c` | `esp_wifi_set_max_tx_power` / `_get_max_tx_power` | no storage | B |
| `esp_wifi_extras.c` | `esp_wifi_set_ps` / `_get_ps` | no storage | C |
| `esp_wifi_extras.c` | `esp_wifi_set_event_mask` / `_get_event_mask` | no storage | C |
| `esp_wifi_extras.c` | `esp_wifi_set_inactive_time` | no storage | C |
| `esp_wifi_extras.c` | `esp_wifi_set_storage` | no-op | accepted (NVS not modeled) |
| `esp_wifi_extras.c` | `esp_wifi_restore` | no-op | accepted |
| `esp_wifi_ap.c` | `esp_wifi_ap_get_sta_list` | empty | D |
| `esp_wifi_ap.c` | `esp_wifi_ap_get_sta_aid` | NOT_FOUND | D |
| `esp_wifi_ap.c` | `esp_wifi_deauth_sta` | no-op | D |
| `esp_wifi_promisc.c` | `esp_wifi_set_promiscuous` (+ filter/cb/etc.) | no callback | E |
| `esp_wifi_promisc.c` | `esp_wifi_80211_tx` | implemented (loopback + DATA→Eth) | E ✅ |
| `esp_wifi_promisc.c` | `esp_wifi_set_vendor_ie*` | no-op | accepted (no real beacon) |
