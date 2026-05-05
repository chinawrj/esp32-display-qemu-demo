# Day 20 — 2026-05-05 (Linux)

## Morning Planning

### 昨日回顾
- Day 17: 更新 docs/qemu-wifi.md，澄清 API 级别 Wi-Fi 仿真架构
- Day 18: 分析 lwIP 数据面状态，14 个 Wi-Fi 测试通过
- Day 19: 将 NEXT-004 (lwIP socket proof) 写入 BACKLOG.md，规划实现路径

### 今日目标
1. **NEXT-004 Step 1**: 添加 Kconfig 探针选项 (`DEMO_LWIP_PROBE_ENABLE/HOST/PORT`)
2. **NEXT-004 Step 2**: 创建 `main/lwip_probe.c` + 头文件，实现 TCP socket 探针任务
3. **NEXT-004 Step 3**: 将探针接入 `main/main.c`，在 Wi-Fi 启动后调用
4. **NEXT-004 Step 4**: 更新 `tools/run-direct-demo.sh` 启动 `wifi_packet_relay.py`
5. **NEXT-004 Step 5**: 创建 `tests/test_qemu_lwip_probe.py` 断言 `lwip probe ok:` 日志
6. 运行非运行时 pytest 套件，确保无回归

### 风险与依赖
- 风险: `wifi_packet_relay.py` 中的 TCP 代理逻辑未经实际 QEMU 测试 (需要 QEMU binary)
- 依赖: `ESP_WIFI_PKT_SOCKET` env var 需要在 QEMU 启动前正确设置
- 风险: 探针任务连接时序 — 需要足够的重试次数让 Wi-Fi 控制面先完成

### 验收检查点
- [ ] `main/lwip_probe.c` 存在，包含 `lwip probe ok:` 日志
- [ ] `main/Kconfig.projbuild` 包含 `DEMO_LWIP_PROBE_ENABLE`
- [ ] `tools/run-direct-demo.sh` 启动 `wifi_packet_relay.py`
- [ ] `tests/test_qemu_lwip_probe.py` 通过 (非运行时 source 检查)
- [ ] 全套非运行时测试无回归

---

## 执行记录

### Task 1: Kconfig 探针选项
- 在 `main/Kconfig.projbuild` 添加 `DEMO_LWIP_PROBE_ENABLE`, `DEMO_LWIP_PROBE_HOST`, `DEMO_LWIP_PROBE_PORT`

### Task 2: lwip_probe.c 实现
- 创建 `main/include/lwip_probe.h`
- 创建 `main/lwip_probe.c`: FreeRTOS 任务，TCP 连接至 HOST:PORT，发送 PING，读取响应，日志 `lwip probe ok:`
- 更新 `main/CMakeLists.txt` 添加源文件

### Task 3: main.c 接入
- `#include "lwip_probe.h"` (条件编译)
- `demo_wifi_start()` 后调用 `lwip_probe_start()`

### Task 4: run-direct-demo.sh 更新
- 添加 `--no-relay` 标志
- 启动 `wifi_packet_relay.py`，监听 `/tmp/pkt-relay-demo` socket
- export `ESP_WIFI_PKT_SOCKET`
- 添加 `PKT_RELAY_PID` 到 cleanup

### Task 5: pytest 新测试
- `tests/test_qemu_lwip_probe.py`: `TestLwipProbeSource` (静态检查) + `TestLwipProbeRuntime` (运行时)

---

## Evening Review

### 完成情况
- ✅ `main/Kconfig.projbuild` 新增 `DEMO_LWIP_PROBE_ENABLE/HOST/PORT`
- ✅ `main/include/lwip_probe.h` 创建
- ✅ `main/lwip_probe.c` 创建：FreeRTOS 探针任务，30 次重试，日志 `lwip probe ok:`
- ✅ `main/CMakeLists.txt` 添加 `lwip_probe.c`
- ✅ `main/main.c` 接入 `lwip_probe_start()` (条件编译 `CONFIG_DEMO_LWIP_PROBE_ENABLE`)
- ✅ `tools/echo_server.py` 新建：最小 TCP echo 服务器 (PING → PONG)
- ✅ `tools/run-direct-demo.sh` 更新：启动 `wifi_packet_relay.py` + `echo_server.py`，export `ESP_WIFI_PKT_SOCKET`
- ✅ `tests/test_qemu_lwip_probe.py` 创建：12 个非运行时测试 + 1 个运行时测试

### 测试结果
- **新增测试**: 12 / 12 pass (`TestLwipProbeSource` × 11 + `TestEchoServer` × 1)
- **回归**: 75 pass, 15 skip, 无新失败
- **运行时失败**: `TestLwipProbeRuntime::test_lwip_probe_ok_in_serial`
  - 根因 1: flash binary 是 Day 20 前的旧版本，不含 `lwip_probe.c` — 需要 `idf.py build`
  - 根因 2: Wi-Fi 控制面 (`got ip:`) 有 pre-existing 问题 — 同 `TestIntegratedDemo` 的已知失败

### 明日计划
1. 调查 Wi-Fi 控制面 pre-existing 失败：为什么固件在 QEMU + mock_wpa 下无法获得 IP
2. 运行 `idf.py build` 将 `lwip_probe.c` 编入 flash binary
3. 重新运行 `TestLwipProbeRuntime` 验收

### Skill 反馈
无新反馈。

