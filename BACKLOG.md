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

### ★ Phase A — Connection-time AP record (P0, Day 42)

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

- [ ] In `wifi/getting_started/station` runtime, `esp_wifi_sta_get_ap_info`
      after GOT_IP returns the SSID/BSSID/RSSI from wpa_supplicant
      STATUS — not the hardcoded `QEMU_TEST` / `AA:BB:…` fake.
- [ ] `esp_wifi_sta_get_rssi` matches `signal=` from `wpa_cli status`
      within ±2 dBm.
- [ ] 93 tests green (90 baseline + 3 new).

---

### ★ Phase B — Channel / country / protocol (P0, Day 43)

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

- [ ] `esp_wifi_set_channel(11, …)` followed by
      `esp_wifi_get_channel(&p, &s)` returns 11.
- [ ] After connect, `get_channel` matches the AP's channel (Phase A
      validation).
- [ ] `esp_wifi_set_country({.cc="US",…})` round-trips.
- [ ] Stock `fast_scan` example builds and runs unmodified.

---

### Phase C — Power save & event mask (P1, Day 44)

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

- [ ] `power_save` example builds + runs; serial shows
      `wifi_set_ps mode=2` followed by a matching `get_ps`.
- [ ] No regressions on existing samples.

---

### Phase D — SoftAP station list & DHCP (P1, Day 45–46)

**Goal:** SoftAP is currently boot-only. `esp_wifi_ap_get_sta_list`
returns empty. Stock `softAP` example expects to log
`station <MAC> join, AID=<n>` on `WIFI_EVENT_AP_STACONNECTED`. This
needs a fake station injector (or two QEMU instances cross-connected
via `wifi_packet_relay.py`).

#### Subtasks

1. **v1 — single-instance fake station**: `wifi_packet_relay.py`
   accepts a CLI option `--ap-fake-clients=2` that, after the AP starts,
   sends two `STACONNECTED` events with deterministic fake MACs +
   AIDs through the QEMU control socket. `esp_wifi_ap_get_sta_list`
   then iterates this device-side table.
2. **v1 DHCP server**: relay implements a tiny DHCP server (UDP/67)
   handing 192.168.4.2 / 192.168.4.3 leases to those fake MACs.
   Fires `IP_EVENT_AP_STAIPASSIGNED`.
3. New MMIO: `WIFI_REG_AP_STA_COUNT`, `WIFI_REG_AP_STA_IDX`,
   `WIFI_REG_AP_STA_MAC0/1`, `WIFI_REG_AP_STA_AID`, `WIFI_REG_AP_STA_RSSI`.
4. `esp_wifi_deauth_sta(aid)` writes a deauth command; relay drops
   that fake client.
5. Pytest: assert `softAP` log contains `station … join` and the
   subsequent `IPASSIGNED` line.

#### Acceptance

- [ ] Stock `softAP` runtime: `Found %d stations` reports 2.
- [ ] `wifi_ap_get_sta_list` returns 2 entries with non-zero MACs.
- [ ] `IP_EVENT_AP_STAIPASSIGNED` fires twice.

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

#### Acceptance

- [ ] Stock `simple_sniffer` runtime captures ≥10 frames per second
      while a TCP test runs alongside.
- [ ] No crashes when promiscuous is enabled mid-connection.

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

### CC-1 — Stub audit test (Day 42 quick-win)

Add `tests/test_no_hardcoded_ap_info.py` (source-analysis): grep the
component for `s_fake_ap`, `-50` constant, `0xAA, 0xBB, 0xCC`,
`"QEMU_TEST"` outside test fixtures and `mock_wpa_supplicant.py`. Fail
the test until Phase A lands. Acts as a regression gate so future
edits can't accidentally re-introduce hardcoded fakes.

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
| `esp_wifi_promisc.c` | `esp_wifi_80211_tx` | NOT_SUPPORTED | E (low) |
| `esp_wifi_promisc.c` | `esp_wifi_set_vendor_ie*` | no-op | accepted (no real beacon) |
