# Backlog

Tracked, implementation-ready next targets for this project. Items here are
**not yet started** — they're written so any contributor (especially on a
fresh Linux machine) can pick them up without re-deriving the design.

The headline target is at the top.

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
