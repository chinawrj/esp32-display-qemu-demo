# Day 13 — 重构日: esp_wifi_qemu 组件拆分

**Date**: 2026-05-04  
**Session**: Day 13  
**Milestone**: 重构日（health check 触发）  
**Commit**: TBD

---

## Goals for Today

- [x] Health check: 识别重构触发条件
- [x] 拆分 `esp_wifi_shim.c`（403行）为三个职责清晰的模块
- [x] 新增 `esp_wifi_private.h` 组件内部共享头文件
- [x] 更新 `CMakeLists.txt` — 新增 SRCS + PRIV_INCLUDE_DIRS
- [x] 编译验证：零警告，`idf.py build` 成功
- [x] 回归测试：93 passed, 1 skipped
- [x] 规划 NEXT-003 backlog 条目（LVGL + Wi-Fi 集成 Demo）

---

## Health Check Results

| 指标 | 值 | 阈值 | 状态 |
|------|----|------|------|
| `esp_wifi_shim.c` 行数 | 403 | >300 | 🔴 触发重构 |
| 连续功能开发天数 | 5（Days 8-12） | ≥4 | 🔴 触发重构 |
| TODO/FIXME 数量 | 0 | <5 | ✅ |
| 编译警告 | 0 | <3 | ✅ |

决定：**今日为重构日，不加新功能。**

---

## What Was Done

### 重构: esp_wifi_qemu 组件拆分

将 `components/esp_wifi_qemu/esp_wifi_shim.c`（403行）拆分为三个模块：

| 文件 | 行数 | 职责 |
|------|------|------|
| `esp_wifi_shim.c` | 255 | 共享状态定义、`wifi_qemu_send_cmd()`、`wifi_event_task()`、lifecycle API（init/deinit/mode/start/stop） |
| `esp_wifi_config.c` | 103 | set_config/get_config/connect/disconnect/get_mac/set_mac |
| `esp_wifi_scan.c` | 70 | 全部 scan API |
| `esp_wifi_private.h` | 23 | 组件内部共享声明（`s_sta_cfg` extern + `SHIM_MIN` macro） |

**设计决策：**
- `s_sta_cfg` 是唯一需要跨文件共享的状态变量（config.c 写入，shim.c 的 event_task 读取）
- `s_inited`、`s_mode`、`s_evt_task`、`s_sta_netif` 均保持 `static`，不对外暴露
- `PRIV_INCLUDE_DIRS "."` 让组件内部 .c 文件可以 include `esp_wifi_private.h`，但不对依赖组件暴露

### CMakeLists.txt

```cmake
idf_component_register(
    SRCS "esp_wifi_shim.c" "esp_wifi_config.c" "esp_wifi_scan.c"
    INCLUDE_DIRS "include"
    PRIV_INCLUDE_DIRS "."
    REQUIRES esp_wifi esp_event esp_netif nvs_flash freertos log
)
```

### NEXT-003 Backlog 规划

新增 `NEXT-003 — LVGL + Wi-Fi 集成 Demo` 条目：
- 将 NEXT-001（帧缓冲 → Chrome）和 NEXT-002（Wi-Fi STA）集成为单一 Demo
- 在 LVGL 界面中实时显示 Wi-Fi 连接状态
- 新增 `main/wifi_ui.c` 模块和 `test_qemu_integrated_demo.py`

---

## Test Results

```
93 passed, 1 skipped, 2 warnings
```

Baseline maintained. No regressions.

---

## 文件变动汇总

| 操作 | 文件 |
|------|------|
| 修改（拆分） | `components/esp_wifi_qemu/esp_wifi_shim.c` (403→255行) |
| 新增 | `components/esp_wifi_qemu/esp_wifi_config.c` (103行) |
| 新增 | `components/esp_wifi_qemu/esp_wifi_scan.c` (70行) |
| 新增 | `components/esp_wifi_qemu/esp_wifi_private.h` (23行) |
| 修改 | `components/esp_wifi_qemu/CMakeLists.txt` |
| 新增条目 | `BACKLOG.md` (NEXT-003) |

## Tomorrow (Day 14)

开始 **NEXT-003 — LVGL + Wi-Fi 集成 Demo**：
1. 添加 `main/Kconfig.projbuild`（DEMO_WIFI_SSID/PASSWORD 配置项）
2. 创建 `main/wifi_ui.c` — LVGL 状态标签模块
3. 修改 `main/main.c` 集成 Wi-Fi 初始化和事件处理
