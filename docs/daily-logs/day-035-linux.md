# Day 35 — 2026-06-02 (Linux)

## 目标

提交 Day 34 末尾遗留的 4 个 in-progress 修复，补充对应的非运行时测试，清理 BACKLOG。

---

## 完成事项

### 1. Event-task 时序竞争修复 (`esp_wifi_shim.c`)

**问题**：`wifi_event_task` 在 `esp_wifi_init()` 中以 `tskIDLE_PRIORITY+2` 启动，
高于 `app_main`（优先级 1）。任务启动后立即抢占 `wifi_qemu_send_cmd()` 的轮询循环，
消费了 `WIFI_EVT_INIT_DONE` / `WIFI_EVT_START_DONE`，导致 `send_cmd()` 超时。

**修复**：将 `xTaskCreate(wifi_event_task, ...)` 移到 `esp_wifi_start()` 中，
在 `WIFI_CMD_START` ACK 返回 `ESP_OK` **之后** 再创建任务。  
AP-only 模式下，在 `if (ap_enabled)` 分支同样创建任务。

**验证**：`test_event_task_started_in_esp_wifi_start_not_init` 通过。

---

### 2. `wpa_ctrl_open` fd 泄漏修复 (`tools/qemu-src-patches/hw/net/esp_wifi.c`)

**问题**：重复调用 `WIFI_CMD_INIT`（`esp_wifi_deinit()` + `esp_wifi_init()`）时，
`wpa_ctrl_open()` 直接打开新 fd 而不关闭旧的，导致 fd 累积和孤立 GLib watch。
每次广播事件时，所有孤立 watch 都会触发一次，导致 spurious 行为。

**修复**：在 `wpa_ctrl_open()` 开头，当 `ctrl_fd >= 0` 时先调用 `wpa_ctrl_close(s)` 关闭旧连接。
同时在 `wpa_ctrl_open` 之前添加 `wpa_ctrl_close` 的前向声明。

**验证**：`test_qemu_wpa_ctrl_open_is_idempotent` 与 `test_qemu_wpa_ctrl_close_forward_declared` 通过。

---

### 3. lwip_probe 串口输出修复 (`tests/test_qemu_lwip_probe.py`)

**问题**：`-display none -serial stdio` + `stdin=DEVNULL` 组合导致 guest 串口输出中断。

**修复**：改为使用 `-nographic`，确保 guest 串口始终输出到 stdout。

---

### 4. BACKLOG 清理

- `PRIMARY-TARGET` 状态改为 ✅ DONE（基础 STA/SCAN/AP 已发布，Days 28–33）
- `NEXT-004` 状态改为 ✅ DONE（tcp_client Day 27；udp_client + lwip_probe Day 33–34）
- 更新 support matrix：`udp_client` 标记为 Done（Day 33）
- 删除 `Day 21 Architecture Review — Wi-Fi Emulation Bug Backlog` 章节（已被后续工作覆盖）

---

### 5. 新增非运行时测试 (`tests/test_qemu_wifi_sta.py` — `TestSourceFiles`)

| 测试名 | 验证点 |
|--------|--------|
| `test_event_task_started_in_esp_wifi_start_not_init` | `xTaskCreate(wifi_event_task)` 不在 `esp_wifi_init()` 中，在 `esp_wifi_start()` 中 |
| `test_qemu_wpa_ctrl_open_is_idempotent` | `wpa_ctrl_open()` 函数体含 `ctrl_fd >= 0` 检查和 `wpa_ctrl_close(s)` 调用 |
| `test_qemu_wpa_ctrl_close_forward_declared` | `wpa_ctrl_close` 的前向声明出现在 `wpa_ctrl_open` 定义之前 |

---

## 验收检查点

- [x] Event task race fix 已提交
- [x] wpa_ctrl_open 幂等修复已提交
- [x] nographic 串口修复已提交
- [x] 3 个新非运行时测试全部通过
- [x] BACKLOG 正确更新（PRIMARY-TARGET ✅ DONE；NEXT-004 ✅ DONE；Day 21 Review 删除）
- [x] 全非运行时测试套件通过（≥168 passed）
- [x] `git status --short` commit 后 clean

## 测试结果

- 非运行时测试（排除 QEMU 运行时）：**168 passed, 6 skipped**
- 新增 3 个 `TestSourceFiles` 测试全部绿色

## Commit

`fix(wifi): event-task race, wpa_ctrl fd leak, nographic serial`
