# Day 22 — 2026-05-05 (Linux)

## Morning Planning

### 昨日回顾 (Day 21)
- ✅ Wi-Fi 仿真 4 层架构审查
- ✅ BUG-001/007 修复（IP 地址空间统一到 10.0.2.x）
- ✅ BUG-002 修复（RX buffer 早期注册）
- ✅ BUG-003 修复（esp_netif_receive 内存泄漏）
- ✅ BACKLOG.md 添加 BUG-004…007、GAP-001/003、ARCH-001/002
- ✅ 53 个非运行时测试零回归

### 今日目标 — 经理直接指令

> **总体方向变更**：让任何 ESP-IDF Wi-Fi 示例代码无需修改 .c/.h 即可在
> QEMU Wi-Fi 模拟器上运行。仅允许 CMakeLists.txt + sdkconfig 修改。

具体任务：
1. 全面盘点 stock ESP-IDF Wi-Fi 示例所需的 API / 构建系统 / 运行时差距
2. 写入 `BACKLOG.md` 顶部，作为新的 PRIMARY-TARGET 章节
3. 在 dev-workflow Agent 文件中以"北极星目标"的形式高亮此方向

### 验收检查点
- [x] BACKLOG.md 顶部新增 PRIMARY-TARGET 章节（gap A-J 全列出）
- [x] dev-workflow agent 文件首屏即指向 PRIMARY-TARGET
- [x] 每日规划检查项更新为对齐北极星目标

---

## 执行记录

### 1. 当前 API 表面盘点

`components/esp_wifi_qemu/` 当前覆盖 16 个 `esp_wifi_*` 符号：

- `esp_wifi_init` / `_deinit`
- `_set_mode` / `_get_mode`
- `_start` / `_stop`
- `_set_config` / `_get_config`
- `_connect` / `_disconnect`
- `_get_mac` / `_set_mac`
- `_scan_start` / `_scan_stop`
- `_scan_get_ap_num` / `_scan_get_ap_records`

依赖 `--allow-multiple-definition` linker flag 与 libnet80211 共存。所有
未覆盖的符号会"凑巧"链接到 libnet80211，在 QEMU 中行为未定义（很可能 panic
或静默 no-op）。

### 2. Stock 示例所需符号（从 ESP-IDF examples/wifi 调研）

详细差距清单见 `BACKLOG.md` § PRIMARY-TARGET。九大类差距：

| 类别 | 描述 |
|------|------|
| A | `esp_wifi_*` API 表面（约 25 个未覆盖符号） |
| B | AP / SoftAP 模式完全缺失 |
| C | ESPNOW 完全缺失 |
| D | WPS / SmartConfig 完全缺失（P3 优先级） |
| E | WPA2-Enterprise 完全缺失 |
| F | `esp_netif_attach_wifi_station` 仅凑巧工作 |
| G | 构建系统未对接 stock 示例（CMakeLists.txt 不能改源码） |
| H | sdkconfig 默认值 |
| I | lwIP 数据面（DHCP / DNS / IPv6 / 外网 NAT） |
| J | 事件顺序与时序正确性 |

### 3. BACKLOG.md 顶部章节

新增 ★★★ PRIMARY-TARGET 章节，包含：
- Mission statement（经理原话）
- Acceptance criteria（zero-diff 源码 + 仅 CMakeLists/sdkconfig 改动）
- Phase-1 目标示例表格（13 个示例，P0-P3 优先级）
- 9 大类差距详细分析
- 4 周高层路线图（Day 22-27+）

### 4. dev-workflow Agent 文件更新

- 在文件头部（项目信息之前）插入"北极星目标"章节
- 列出 Phase-1 P0-P2 示例
- 列出 6 大关键差距（A、B、C、F、G、I）
- 每日规划必须回答的 3 个问题
- 验收标准章节增加"项目级（北极星）"分组

### 5. 测试

本次仅文档变更，无代码改动。运行非运行时测试套件确认零回归：

```
53 passed, 5 skipped (预期 infra skips)
```

---

## Evening Review

### 完成情况

| 目标 | 状态 |
|------|------|
| 全栈差距盘点 | ✅ |
| BACKLOG.md PRIMARY-TARGET 章节 | ✅ |
| dev-workflow Agent 北极星目标 | ✅ |
| 每日检查项更新 | ✅ |

### 明日计划 (Day 23)

按 BACKLOG.md 路线图：

1. **BUG-004**: `wifi_qemu_send_cmd` / `wifi_event_task` 竞态修复
2. **BUG-005**: `pkt_relay_open()` 提前到 `CMD_START`
3. **重新编译 QEMU** 并验证 Day 21 修复（IP 地址统一）效果
4. 如果有时间：开始 GAP-G — 设计 `tools/qemu-wifi-overlay.cmake`

### 健康指标

- 编译警告: N/A（仅文档变更）
- 单文件最大行数: BACKLOG.md 已扩展到约 480 行（文档文件，可接受）
- TODO/FIXME: < 5
- 连续功能/规划天数: 22 天
- **重构日触发条件**：未触发

### 关键决策记录

> 经理指令将项目方向从"自有 LVGL+Wi-Fi demo"扩展到
> "**通用 ESP-IDF Wi-Fi 示例 QEMU 仿真平台**"。
> 这从根本上改变了所有未来 work item 的优先级评估方式。
