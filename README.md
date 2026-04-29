# esp32-display-qemu-demo

Run an LVGL benchmark on the official **ESP32 QEMU emulator** — no real hardware
required — and capture a real, reproducible screenshot from the device
framebuffer over UART.

![LVGL benchmark on ESP32 QEMU, captured from the device framebuffer](docs/screenshot.png)

> Above: actual LVGL `lv_demo_benchmark` frame rendered inside QEMU at 240×135
> (RGB565), captured via UART base64 dump and decoded back to PNG on the host.
> The dimming overlay in the corner is the LVGL `LV_USE_PERF_MONITOR` widget.

---

## Why

Embedded UI work normally needs the physical display attached. This project
shows a fully self-contained loop:

1. **Build** an ESP-IDF firmware that boots LVGL with a 240×135 RGB565 display.
2. **Run** it in QEMU's `xtensa` machine — fully headless.
3. **Capture** a single LVGL framebuffer over UART as base64.
4. **Decode** the base64 stream back to a PNG on the host.
5. **Verify** with a 10-check assertion harness so a green run is provable in CI.

Everything is driven by two scripts:

```bash
bash tools/run-qemu.sh 45 verify        # boots QEMU, runs ~7s, verifies, dumps log
python3 tools/decode-fb.py /tmp/esp32-qemu-serial.log docs/screenshot.png --scale 4
```

---

## Prerequisites

### macOS (tested)

```bash
brew install pixman libgcrypt sdl2 tmux
```

### ESP-IDF + QEMU

This project targets **ESP-IDF v5.5+** with the prebuilt Espressif QEMU.

```bash
# 1. Install ESP-IDF (skip if you already have it)
#    https://docs.espressif.com/projects/esp-idf/en/latest/esp32/get-started/

# 2. Install the prebuilt qemu-xtensa via idf_tools
python3 $IDF_PATH/tools/idf_tools.py install qemu-xtensa
. $IDF_PATH/export.sh                   # makes idf.py + qemu-system-xtensa visible
```

### Project Python environment

```bash
cd esp32-display-qemu-demo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt          # currently just Pillow for the decoder
```

---

## Quickstart

```bash
. $IDF_PATH/export.sh
source .venv/bin/activate

idf.py set-target esp32                  # one time
idf.py build                             # ~60 s clean / ~5 s incremental

bash tools/run-qemu.sh 45 verify         # boots, captures FB, verifies (10/10)
python3 tools/decode-fb.py /tmp/esp32-qemu-serial.log /tmp/shot.png --scale 4
open /tmp/shot.png                       # macOS
```

Expected verify output:

```
[run-qemu] === Verification ===
  ✅ app_main reached
  ✅ lvgl initialized log
  ✅ lvgl display created
  ✅ lvgl flush callback fired
  ✅ demo started
  ✅ demo rendered ≥30 flushes (≥1s)
  ✅ framebuffer capture begin marker
  ✅ framebuffer capture end marker
  ✅ demo completion banner
  ✅ framebuffer payload size  (1440 base64 lines, expected 1440)
[run-qemu] Result: 10 passed, 0 failed
```

A one-shot wrapper is also available:

```bash
bash tools/start-demo.sh                 # full: build + boot + verify
bash tools/start-demo.sh quick           # skip build
```

---

## How the screenshot pipeline works

```
  ┌──────────────┐    flush_cb #80    ┌──────────────────────┐
  │   LVGL       │ ─────────────────▶ │ dump_framebuffer_     │
  │   benchmark  │  (RGB565, 64.8 KB) │ base64()              │
  └──────────────┘                    └─────────┬────────────┘
                                                │ <<<FB_BEGIN size=64800 …>>>
                                                │ FB=<base64 line × 1440>
                                                │ <<<FB_END>>>
                                                ▼
  ┌──────────────────────┐    UART    ┌──────────────────────┐
  │ tools/run-qemu.sh    │ ─────────▶ │ /tmp/esp32-qemu-      │
  │ (10-check verify)    │            │ serial.log            │
  └──────────────────────┘            └─────────┬────────────┘
                                                │
                                                ▼
                              ┌────────────────────────────────┐
                              │ tools/decode-fb.py             │
                              │   - parse FB_BEGIN/END markers │
                              │   - base64-decode payload      │
                              │   - RGB565 LE → RGB888         │
                              │     (bit-replication)          │
                              │   - PIL Image.save("PNG")      │
                              └────────────────┬───────────────┘
                                               ▼
                                       docs/screenshot.png
```

Key numbers:

| Item | Value |
|---|---|
| Display | 240 × 135 RGB565 (64 800 bytes) |
| Capture frame | flush #80 (mid-benchmark) |
| Base64 lines | 1 440 (60 chars each, prefixed `FB=`) |
| Verify duration | ~7 s of QEMU + ~6 s UART drain → use `45 s` timeout |
| Binary | 776 KB / 1 024 KB partition (76 %) |

---

## Testing

```bash
source .venv/bin/activate
pytest                                   # 17 tests, ~1 s warm / ~50 s cold
```

The suite reuses `/tmp/esp32-qemu-serial.log` if it's < 30 minutes old; otherwise
it boots QEMU once via `tools/run-qemu.sh`. Each of the 10 verify checks plus
two end-to-end decoder tests appears as an individual pytest case so CI failures
pinpoint the regression. `tests/fb_server/` adds 5 more tests covering the
Chrome framebuffer bridge (protocol, server e2e, static HTTP).

Set `ESP32_QEMU_LOG=/path/to/log` to test against a captured log without
booting QEMU at all.

---

## Chrome framebuffer viewer (preview)

`tools/fb_server/` ships an early Phase-1 prototype of the long-term Chrome
super-simulator: a Python WebSocket bridge plus a vanilla-JS Canvas client that
together render a 240×135 RGB565 framebuffer in real time.

```bash
source .venv/bin/activate
python -m tools.fb_server.server         # ws://127.0.0.1:7788, http://127.0.0.1:8080
open http://127.0.0.1:8080               # macOS — opens Chrome viewer
```

Right now the server uses a synthetic producer (animated rectangle) so the
frontend can be developed standalone. A future workday will replace it with a
real-time push from the LVGL `flush_cb` (`cdp-phase2`).

---

## Project structure

```
esp32-display-qemu-demo/
├── main/
│   └── main.c                  # LVGL init + benchmark + FB capture (150 lines)
├── sdkconfig.defaults          # LVGL config (incl. LV_USE_SYSMON + PERF_MONITOR)
├── tools/
│   ├── run-qemu.sh             # boot QEMU + 10-check verify
│   ├── start-demo.sh           # one-click: build + boot + verify
│   ├── decode-fb.py            # FB log → PNG (RGB565 → RGB888)
│   ├── build-qemu.sh           # (future) build qemu from chinawrj/qemu fork
│   └── fb_server/              # Phase-1 Chrome FB bridge (WS + static HTTP)
├── web/                        # Canvas viewer for the FB bridge
│   ├── index.html
│   ├── main.js
│   └── style.css
├── tests/
│   ├── conftest.py             # session fixture: reuse log or boot QEMU once
│   ├── test_qemu_boot.py       # 10 verify checks as parametrized pytest cases
│   ├── test_decoder.py         # decode-fb.py end-to-end (Pillow assertions)
│   └── fb_server/              # protocol + server e2e tests
├── docs/
│   ├── screenshot.png          # committed baseline (this README's hero image)
│   └── m4-day6-serial.log      # trimmed serial log proving 10/10 verify
├── requirements.txt            # Python deps (Pillow)
└── .copilot/docs/skill-feedback.md   # iterative skill improvements log
```

---

## Troubleshooting

**`region 'dram0_0_seg' overflowed by N bytes`**
A 64 KB framebuffer in `.bss` exceeds ESP32's DRAM segment. The framebuffer is
allocated at runtime via `heap_caps_malloc(MALLOC_CAP_8BIT)` to avoid this. If
you add more globals, watch the link error closely.

**Screenshot is solid orange (single colour)**
LVGL hasn't drawn benchmark content yet at the capture frame. Bump
`CAPTURE_FLUSH_INDEX` in `main/main.c` (currently `80`).

**"LV_USE_PERF_MONITOR is not enabled" banner appears**
`LV_USE_PERF_MONITOR` is gated on `LV_USE_SYSMON` in LVGL's `lv_conf_internal.h`.
Both must be set in `sdkconfig.defaults`. Already configured here — only relevant
if you fork the config.

**`qemu-system-xtensa: command not found`**
Run `python3 $IDF_PATH/tools/idf_tools.py install qemu-xtensa` and re-source
`$IDF_PATH/export.sh`. The binary lands under
`~/.espressif/tools/qemu-xtensa/<version>/qemu/bin/`.

**`bash tools/run-qemu.sh` reports 9 / 10 passed**
Most often an old `/tmp/esp32-qemu-serial.log` was reused. The script overwrites
it on each run; if it's locked by another process, kill stale `qemu-system-xtensa`
processes (`ps aux | grep qemu-system-xtensa`) and re-run.

---

## Roadmap

| Milestone | Status | Highlights |
|---|---|---|
| M1: Hello World on QEMU | ✅ Done | ESP-IDF boots in QEMU, tmux session set up |
| M2: LVGL integration | ✅ Done | `lvgl__lvgl` component, RGB565 display, flush_cb |
| M3: Benchmark demo | ✅ Done | `lv_demo_benchmark` + `start-demo.sh` wrapper |
| M4: Framebuffer capture & verify | ✅ Done | UART base64 dump, host decoder, baseline PNG |
| M5: Local-built QEMU | ⏳ Pending | `tools/build-qemu.sh` scaffolded for `chinawrj/qemu` fork |
| M6: Chrome super-simulator | ⏳ Pending | WebSocket FB bridge → Canvas → CDP/Playwright tests |

The Chrome super-simulator (M6) will replace the UART screenshot path with a
real-time WebSocket framebuffer push, displayed in a Chrome page that doubles as
the debug surface for QEMU peripherals (Display, Wi-Fi, BLE, UART, FreeRTOS
state) and is automatable via Chrome DevTools Protocol.

---

## License

See `LICENSE` for details.
