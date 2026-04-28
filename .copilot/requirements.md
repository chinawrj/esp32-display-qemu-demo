# esp32-display-qemu-demo - 项目需求文档

## 项目概述

**项目名称**: esp32-display-qemu-demo
**描述**: 使用 ESP32 官方 QEMU 模拟器运行 LVGL UI 示例，无需真实硬件即可开发和验证显示界面
**目标硬件**: esp32-qemu

## 功能需求

- 在 QEMU 模拟器中编译并运行 LVGL sample 应用
- ESP-IDF + LVGL 组件集成（通过 idf-component-manager）
- QEMU 启动配置（qemu-system-xtensa，framebuffer 模拟）
- 通过 tmux 管理编译窗口和 QEMU 运行窗口
- LVGL 渲染验证（日志输出 + framebuffer 截图）

## 验收标准

- [ ] idf.py build 编译成功，零警告
- [ ] QEMU 成功启动并输出 LVGL 初始化日志
- [ ] LVGL demo 页面在 QEMU 中正常渲染（至少 1 秒稳定输出）
- [ ] 不需要真实 ESP32 硬件即可完整运行验证流程
- [ ] tmux 会话正常管理编译与 QEMU 窗口

## 里程碑

### Milestone 1: M1 - 环境准备

验证 ESP-IDF 环境、QEMU（qemu-system-xtensa）安装就绪。
创建最简 ESP-IDF Hello World 项目并在 QEMU 中成功运行。

### Milestone 2: M2 - LVGL 集成

通过 idf-component-manager 添加 lvgl/lvgl 组件。
配置 sdkconfig 启用 LVGL 和虚拟显示驱动（lv_port_disp）。
编译通过，LVGL 初始化日志正常输出。

### Milestone 3: M3 - LVGL Demo 运行

运行 LVGL 官方 demo（lv_demo_widgets 或 lv_demo_benchmark）。
在 QEMU 中验证渲染输出（日志 + framebuffer）。
完善 tmux 启动脚本，一键启动开发环境。

### Milestone 4: M4 - 测试与文档

编写自动化测试：启动 QEMU、等待 LVGL 初始化日志、判断 pass/fail。
代码重构，补充 README，记录 QEMU 启动参数和注意事项。

## 技术栈

- 硬件平台: esp32-qemu
- 开发工具: tmux, ESP-IDF, CDP 浏览器工具
- 测试工具: 串口自动化测试, Web UI 自动化测试

## AI Agent Skills

以下 skills 将用于项目开发：

- `tmux-multi-shell`: tmux 多终端管理（编译/烧录/串口监控）
- `esp32-build-flash`: ESP-IDF 编译与烧录工作流
- `environment-setup`: 开发环境检查与配置（工具链、驱动、依赖）
- `project-scaffolding`: 项目脚手架生成（目录结构、CMake、HTML 模板）
- `daily-iteration`: 每日迭代计划与执行
- `automated-testing`: 自动化测试（串口验证 + Web UI 验证）
- `code-refactoring`: 周期性代码重构策略

## 非功能需求

- 设备应在 WiFi 断开后自动重连
- Web 页面应在 3 秒内加载完成
- 视频流延迟不超过 2 秒
- 传感器数据刷新间隔不超过 5 秒
- 系统连续运行 24 小时无崩溃

## 约束条件

- Flash 空间限制: 4MB（根据硬件型号调整）
- RAM 限制: 520KB SRAM + 4MB PSRAM（如有）
- WiFi 仅支持 2.4GHz
