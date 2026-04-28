---
name: project-scaffolding
description: 为目标项目生成初始目录结构、CMakeLists.txt、HTML 模板和基础源码框架。Use when initializing a new ESP-IDF project from scratch, creating the standard directory layout, or setting up a compilable Hello World starting point.
---

# Skill: 项目脚手架生成

## 用途

为目标项目生成初始目录结构、构建配置文件（CMakeLists.txt）、HTML 模板和基础源码框架。这是项目开发的第一步实际编码工作。

**何时使用：**
- 项目从零开始，需要初始化目录和文件
- 需要标准的 ESP-IDF 项目结构
- 需要一个可编译的 "Hello World" 起点

**何时不使用：**
- 项目已有代码结构
- 基于已有模板/示例项目开发

## 前置条件

- 开发环境已通过 `environment-setup` skill 验证
- ESP-IDF 环境已加载
- 已确定目标芯片型号

## 操作步骤

### 1. ESP-IDF 项目标准结构

```
{{PROJECT_NAME}}/
├── CMakeLists.txt              # 顶层构建文件
├── sdkconfig.defaults          # 默认配置
├── partitions.csv              # 分区表（大项目需要）
├── main/
│   ├── CMakeLists.txt          # main 组件构建文件
│   ├── main.c                  # 入口文件
│   ├── wifi_manager.c          # WiFi 管理
│   ├── wifi_manager.h
│   ├── http_server.c           # HTTP 服务器
│   ├── http_server.h
│   └── Kconfig.projbuild       # menuconfig 自定义项
├── components/                  # 自定义组件
│   └── virtual_sensor/
│       ├── CMakeLists.txt
│       ├── virtual_sensor.c
│       └── include/
│           └── virtual_sensor.h
├── frontend/                    # Web 前端资源
│   ├── index.html
│   ├── style.css
│   └── app.js
├── tools/                       # 开发辅助工具
│   ├── start-browser.py
│   └── check-env.sh
├── tests/                       # 测试脚本
│   ├── test_serial.py
│   └── test_web_ui.py
└── docs/
    └── daily-logs/             # 每日工作日志
```

### 2. 顶层 CMakeLists.txt

```cmake
cmake_minimum_required(VERSION 3.16)

# 包含 ESP-IDF 构建系统
include($ENV{IDF_PATH}/tools/cmake/project.cmake)

project({{PROJECT_NAME}})
```

### 3. main/CMakeLists.txt

```cmake
idf_component_register(
    SRCS "main.c" "wifi_manager.c" "http_server.c"
    INCLUDE_DIRS "."
    REQUIRES esp_wifi esp_http_server nvs_flash esp_netif
    PRIV_REQUIRES virtual_sensor
)

# 嵌入前端文件到固件
spiffs_create_partition_image(storage ../frontend FLASH_IN_PROJECT)
```

### 4. 最小可运行的 main.c

```c
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "wifi_manager.h"
#include "http_server.h"

static const char *TAG = "app_main";

void app_main(void)
{
    ESP_LOGI(TAG, "Starting {{PROJECT_NAME}}...");

    // 初始化 NVS
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    // 初始化 WiFi
    wifi_init_sta();

    // 启动 HTTP 服务器
    start_webserver();

    ESP_LOGI(TAG, "{{PROJECT_NAME}} started successfully");
}
```

### 5. 基础 HTML 模板

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{PROJECT_NAME}}</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #1a1a2e; color: #eee; }
        .container { max-width: 800px; margin: 0 auto; }
        .card { background: #16213e; border-radius: 8px; padding: 16px; margin: 12px 0; }
        .sensor-value { font-size: 2em; font-weight: bold; color: #0f3460; }
        #stream { width: 100%; border-radius: 8px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>{{PROJECT_NAME}}</h1>
        <div class="card">
            <h2>Camera Stream</h2>
            <img id="stream" src="/stream" alt="Camera Stream">
        </div>
        <div class="card">
            <h2>Sensors</h2>
            <p>Temperature: <span id="temperature" class="sensor-value">--</span> °C</p>
            <p>Humidity: <span id="humidity" class="sensor-value">--</span> %</p>
        </div>
    </div>
    <script>
        async function updateSensors() {
            try {
                const resp = await fetch('/api/sensors');
                const data = await resp.json();
                document.getElementById('temperature').textContent = data.temperature.toFixed(1);
                document.getElementById('humidity').textContent = data.humidity.toFixed(1);
            } catch(e) { console.error('Sensor update failed:', e); }
        }
        setInterval(updateSensors, 5000);
        updateSensors();
    </script>
</body>
</html>
```

### 6. 生成脚手架命令

```bash
# 创建项目目录
mkdir -p {{PROJECT_NAME}}/{main,components/virtual_sensor/include,frontend,tools,tests,docs/daily-logs}

# 设置目标芯片
cd {{PROJECT_NAME}}
idf.py set-target esp32

# 首次编译验证
idf.py build
```

## Self-Test（自检）

> 验证脚手架生成的项目结构能正确编译。

### 自检步骤

```bash
# Test 1: 目录结构完整性
DIRS="main components frontend tools tests docs/daily-logs"
ALL_OK=true
for d in $DIRS; do
    [ -d "{{PROJECT_NAME}}/$d" ] || { echo "SELF_TEST_FAIL: missing dir $d"; ALL_OK=false; }
done
$ALL_OK && echo "SELF_TEST_PASS: directory_structure"

# Test 2: CMakeLists.txt 语法检查
grep -q "project({{PROJECT_NAME}})" {{PROJECT_NAME}}/CMakeLists.txt && \
    echo "SELF_TEST_PASS: cmake_syntax" || echo "SELF_TEST_FAIL: cmake_syntax"

# Test 3: 编译通过（需要 ESP-IDF 环境）
cd {{PROJECT_NAME}} && idf.py build 2>&1 | tail -5
[ ${PIPESTATUS[0]} -eq 0 ] && echo "SELF_TEST_PASS: build" || echo "SELF_TEST_FAIL: build"
```

### Blind Test（盲测）

**测试 Prompt:**
```
你是一个 AI 开发助手。请阅读此 Skill，然后为一个名为 "test-project" 的
ESP32 项目生成完整的脚手架。项目需要 WiFi 连接和一个简单的 HTTP 服务器。
生成所有必需文件后，执行 idf.py build 验证可编译。
```

**验收标准:**
- [ ] Agent 生成了所有必需的目录和文件
- [ ] CMakeLists.txt 结构正确
- [ ] main.c 包含基本的初始化流程
- [ ] HTML 模板包含必要的 UI 元素
- [ ] 首次编译成功（或错误仅因缺少硬件组件）

## 成功标准

- [ ] 项目目录结构完整
- [ ] `idf.py build` 编译通过（或仅有可预期的组件缺失警告）
- [ ] HTML 页面在浏览器中可渲染
- [ ] 所有源文件的 include/import 路径正确
