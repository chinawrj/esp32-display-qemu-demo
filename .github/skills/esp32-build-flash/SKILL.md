---
name: esp32-build-flash
description: ESP-IDF 项目编译、配置和烧录工作流。Use when building, configuring (menuconfig), or flashing an ESP-IDF project to an ESP32 device or QEMU emulator.
---

# Skill: ESP32 编译与烧录

## 用途

管理 ESP-IDF 项目的编译、配置和烧录流程。

**何时使用：**
- 需要编译 ESP-IDF 项目
- 需要配置 menuconfig 选项
- 需要烧录固件到 ESP32 设备
- 需要清理构建产物重新编译

**何时不使用：**
- Arduino 或 PlatformIO 项目（使用对应工具链）
- 非 ESP32 平台

## 前置条件

- ESP-IDF v5.x 已安装
- 环境变量已配置：`. $HOME/esp/esp-idf/export.sh`
- 目标芯片已确认（ESP32 / ESP32-S2 / ESP32-S3 / ESP32-C3）

## 操作步骤

### 1. 环境准备

```bash
# 加载 ESP-IDF 环境（每个新终端都需要）
. $HOME/esp/esp-idf/export.sh

# 验证环境
idf.py --version
```

### 2. 项目配置

```bash
# 设置目标芯片
idf.py set-target esp32  # 或 esp32s3 等

# 打开菜单配置
idf.py menuconfig

# 常用配置项：
# - Component config → ESP32-specific → CPU frequency (240MHz)
# - Component config → Camera configuration (ESP-CAM 项目)
# - Component config → WiFi → WiFi SSID / Password
# - Serial flasher config → Flash size (4MB)
```

### 3. 编译

```bash
# 完整编译
idf.py build

# 仅编译应用（跳过 bootloader）
idf.py app

# 查看编译产物大小
idf.py size
idf.py size-components  # 按组件查看
```

### 4. 烧录

```bash
# 自动检测端口并烧录
idf.py -p /dev/ttyUSB0 flash

# 仅烧录应用分区（更快）
idf.py -p /dev/ttyUSB0 app-flash

# 烧录并立即监控
idf.py -p /dev/ttyUSB0 flash monitor
```

### 5. 构建错误处理

| 错误类型 | 常见原因 | 解决方法 |
|---------|---------|---------|
| `undefined reference` | 缺少组件依赖 | 检查 CMakeLists.txt 的 REQUIRES |
| `region 'iram0_0_seg' overflowed` | IRAM 溢出 | 优化代码或启用 PSRAM |
| `No such file or directory` | 头文件路径错误 | 检查 include 路径配置 |
| `fatal error: esp_camera.h` | 缺少 camera 组件 | 添加 esp32-camera 组件 |

### 6. 清理与重建

```bash
# 清理构建产物
idf.py fullclean

# 重新编译
idf.py build
```

### 7. 在 tmux 中的自动化流程

```bash
# 编译（在 build 窗口）
tmux send-keys -t {{PROJECT_NAME}}:build '. $HOME/esp/esp-idf/export.sh && idf.py build' C-m

# 等待编译完成后检查结果
sleep 30  # 根据项目大小调整
BUILD_OUTPUT=$(tmux capture-pane -t {{PROJECT_NAME}}:build -p | tail -20)
if echo "$BUILD_OUTPUT" | grep -q "Project build complete"; then
    echo "编译成功"
    # 烧录
    tmux send-keys -t {{PROJECT_NAME}}:flash 'idf.py -p /dev/ttyUSB0 flash' C-m
else
    echo "编译失败，检查错误"
    tmux capture-pane -t {{PROJECT_NAME}}:build -p | grep -i "error"
fi
```

## Self-Test（自检）

> 验证 ESP-IDF 工具链和编译环境是否就绪。

### 自检步骤

```bash
# Test 1: ESP-IDF 环境变量
[ -n "$IDF_PATH" ] && echo "SELF_TEST_PASS: idf_path ($IDF_PATH)" || echo "SELF_TEST_FAIL: idf_path (运行 . ~/esp/esp-idf/export.sh)"

# Test 2: idf.py 可执行
command -v idf.py &>/dev/null && echo "SELF_TEST_PASS: idf_cli" || echo "SELF_TEST_FAIL: idf_cli"

# Test 3: 编译器可用
command -v xtensa-esp32-elf-gcc &>/dev/null && echo "SELF_TEST_PASS: xtensa_gcc" || echo "SELF_TEST_WARN: xtensa_gcc (可能使用 riscv 目标)"

# Test 4: 创建并编译最小项目
TMP_DIR=$(mktemp -d)
mkdir -p "$TMP_DIR/main"
cat > "$TMP_DIR/CMakeLists.txt" << 'EOF'
cmake_minimum_required(VERSION 3.16)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(selftest)
EOF
cat > "$TMP_DIR/main/CMakeLists.txt" << 'EOF'
idf_component_register(SRCS "main.c" INCLUDE_DIRS ".")
EOF
cat > "$TMP_DIR/main/main.c" << 'EOF'
#include <stdio.h>
void app_main(void) { printf("selftest ok\n"); }
EOF
cd "$TMP_DIR" && idf.py set-target esp32 &>/dev/null && idf.py build &>/dev/null && \
  echo "SELF_TEST_PASS: minimal_build" || echo "SELF_TEST_FAIL: minimal_build"
rm -rf "$TMP_DIR"
```

### 预期结果

| 测试项 | 预期输出 | 失败影响 |
|--------|---------|----------|
| idf_path | `SELF_TEST_PASS` | 无法使用 ESP-IDF |
| idf_cli | `SELF_TEST_PASS` | 无法编译/烧录 |
| xtensa_gcc | `SELF_TEST_PASS/WARN` | ESP32 目标不可编译 |
| minimal_build | `SELF_TEST_PASS` | 编译环境有问题 |

### Blind Test（盲测）

**测试 Prompt:**
```
你是一个 AI 开发助手。请阅读此 Skill，然后：
1. 检查 ESP-IDF 环境是否加载
2. 创建一个最小的 ESP32 项目（只有 app_main 打印一行日志）
3. 执行 idf.py build 并报告结果
4. 如果编译成功，报告固件大小
5. 清理临时文件
```

**验收标准:**
- [ ] Agent 先加载 ESP-IDF 环境（source export.sh）
- [ ] Agent 创建了正确的 CMakeLists.txt 结构
- [ ] Agent 执行 build 并检查退出码
- [ ] Agent 报告 build 成功或失败原因

## 成功标准

- [ ] `idf.py build` 编译成功，无错误
- [ ] 固件大小在 flash 容量限制内
- [ ] `idf.py flash` 烧录成功
- [ ] 设备重启后串口输出正常启动日志
