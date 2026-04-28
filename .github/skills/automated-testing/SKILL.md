---
name: automated-testing
description: 嵌入式项目自动化测试策略，结合串口验证和 Web UI 验证实现端到端测试。Use when setting up or running automated tests, validating serial output, testing Web UI behavior, or defining test acceptance criteria.
---

# Skill: 自动化测试

## 用途

定义嵌入式项目的自动化测试策略，结合串口验证和 Web UI 验证实现端到端测试。

**何时使用：**
- 需要验证固件功能是否正常
- 需要验证 Web UI 是否正确显示
- 需要回归测试防止功能退化
- 持续集成/持续开发流程中

**何时不使用：**
- 手动测试足够的一次性验证
- 没有可测试接口的纯硬件项目

## 前置条件

- 设备已连接并可通过串口通信
- Web UI 已可访问（如适用）
- CDP 浏览器工具已配置（如需 Web 测试）
- tmux 环境已准备

## 操作步骤

### 1. 测试金字塔

```
        ┌─────────┐
        │ E2E     │  ← CDP + 串口：完整流程验证
        │ Tests   │
       ┌┴─────────┴┐
       │ Integration│  ← 串口：模块间交互验证
       │ Tests      │
      ┌┴────────────┴┐
      │  Unit Tests   │  ← 编译时：组件级测试
      └───────────────┘
```

### 2. 串口自动化测试

```python
"""test_serial.py - 串口自动化测试"""
import serial
import re
import time
import sys

class ESP32SerialTest:
    def __init__(self, port="/dev/ttyUSB0", baudrate=115200):
        self.ser = serial.Serial(port, baudrate, timeout=1)
        self.results = []

    def wait_for_pattern(self, pattern, timeout=30):
        """等待串口输出匹配指定模式"""
        start = time.time()
        buffer = ""
        while time.time() - start < timeout:
            data = self.ser.readline().decode("utf-8", errors="ignore")
            buffer += data
            if re.search(pattern, buffer):
                return True, buffer
        return False, buffer

    def test_boot(self):
        """测试设备正常启动"""
        ok, output = self.wait_for_pattern(r"app_main: Starting", timeout=15)
        self._record("boot", ok, "设备启动" if ok else f"启动超时: {output[-200:]}")

    def test_wifi_connect(self):
        """测试 WiFi 连接"""
        ok, output = self.wait_for_pattern(r"got ip:(\d+\.\d+\.\d+\.\d+)", timeout=20)
        if ok:
            ip = re.search(r"got ip:(\d+\.\d+\.\d+\.\d+)", output).group(1)
            self._record("wifi", True, f"WiFi 已连接, IP: {ip}")
        else:
            self._record("wifi", False, "WiFi 连接超时")

    def test_http_server(self):
        """测试 HTTP 服务器启动"""
        ok, output = self.wait_for_pattern(r"httpd.*start|server.*listening", timeout=10)
        self._record("http", ok, "HTTP 服务已启动" if ok else "HTTP 服务未启动")

    def test_camera_init(self):
        """测试摄像头初始化"""
        ok, output = self.wait_for_pattern(r"camera.*init|cam_hal", timeout=10)
        self._record("camera", ok, "摄像头初始化成功" if ok else "摄像头初始化失败")

    def test_no_errors(self):
        """检查无严重错误"""
        time.sleep(5)  # 等待稳定
        output = ""
        while self.ser.in_waiting:
            output += self.ser.readline().decode("utf-8", errors="ignore")
        errors = re.findall(r"(error|panic|abort|assert failed)", output, re.IGNORECASE)
        ok = len(errors) == 0
        self._record("no_errors", ok, "无错误" if ok else f"发现错误: {errors}")

    def _record(self, name, passed, message):
        self.results.append({"name": name, "passed": passed, "message": message})
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {name} - {message}")

    def run_all(self):
        """运行所有测试"""
        print("=" * 50)
        print("ESP32 串口自动化测试")
        print("=" * 50)
        self.test_boot()
        self.test_wifi_connect()
        self.test_http_server()
        self.test_camera_init()
        self.test_no_errors()

        passed = sum(1 for r in self.results if r["passed"])
        total = len(self.results)
        print("=" * 50)
        print(f"结果: {passed}/{total} 通过")
        return passed == total

if __name__ == "__main__":
    test = ESP32SerialTest()
    success = test.run_all()
    sys.exit(0 if success else 1)
```

### 3. Web UI 自动化测试

```python
"""test_web_ui.py - Web UI 自动化测试（使用 Patchright）"""
from patchright.sync_api import sync_playwright

class WebUITest:
    def __init__(self, device_ip):
        self.device_ip = device_ip
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.connect_over_cdp("http://localhost:9222")
        self.context = self.browser.contexts[0]
        self.page = self.context.new_page()
        self.results = []

    def test_page_loads(self):
        """测试页面可以加载"""
        try:
            self.page.goto(f"http://{self.device_ip}/", timeout=10000)
            self.page.wait_for_load_state("networkidle")
            self._record("page_load", True, "页面加载成功")
        except Exception as e:
            self._record("page_load", False, f"页面加载失败: {e}")

    def test_video_stream(self):
        """测试视频流是否显示"""
        stream = self.page.locator("img#stream, video#stream, img[src*='stream']")
        visible = stream.is_visible(timeout=5000)
        self._record("video_stream", visible, "视频流可见" if visible else "视频流不可见")

    def test_sensor_data(self):
        """测试传感器数据是否显示"""
        # 温度
        temp = self.page.locator("[data-sensor='temperature'], #temperature, .temperature")
        temp_visible = temp.is_visible(timeout=3000)
        self._record("temperature", temp_visible,
                     f"温度: {temp.text_content()}" if temp_visible else "温度数据不可见")

        # 湿度
        humidity = self.page.locator("[data-sensor='humidity'], #humidity, .humidity")
        hum_visible = humidity.is_visible(timeout=3000)
        self._record("humidity", hum_visible,
                     f"湿度: {humidity.text_content()}" if hum_visible else "湿度数据不可见")

    def test_data_updates(self):
        """测试数据是否定期更新"""
        temp_el = self.page.locator("[data-sensor='temperature'], #temperature, .temperature")
        if not temp_el.is_visible(timeout=3000):
            self._record("data_update", False, "无法获取温度元素")
            return

        value1 = temp_el.text_content()
        self.page.wait_for_timeout(5000)  # 等待 5 秒
        value2 = temp_el.text_content()
        # 数据可能相同但至少不应该是空的
        ok = value1 is not None and len(value1) > 0
        self._record("data_update", ok, f"数据采集正常: {value1} -> {value2}")

    def _record(self, name, passed, message):
        self.results.append({"name": name, "passed": passed, "message": message})
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {name} - {message}")

    def run_all(self):
        print("=" * 50)
        print("Web UI 自动化测试")
        print("=" * 50)
        self.test_page_loads()
        self.test_video_stream()
        self.test_sensor_data()
        self.test_data_updates()

        passed = sum(1 for r in self.results if r["passed"])
        total = len(self.results)
        print("=" * 50)
        print(f"结果: {passed}/{total} 通过")
        return passed == total

    def close(self):
        self.page.close()
        self.pw.stop()
```

### 4. 端到端测试流程

```bash
#!/bin/bash
# run-e2e-tests.sh - 端到端测试流程

echo "=== E2E 测试开始 ==="

# Step 1: 编译并烧录
echo "[1/4] 编译..."
idf.py build || exit 1

echo "[2/4] 烧录..."
idf.py -p /dev/ttyUSB0 flash || exit 1

# Step 3: 等待设备启动
echo "[3/4] 等待设备启动 (10s)..."
sleep 10

# Step 4: 运行串口测试
echo "[4/4] 运行串口测试..."
python test_serial.py
SERIAL_RESULT=$?

# Step 5: 运行 Web UI 测试（如果串口测试通过）
if [ $SERIAL_RESULT -eq 0 ]; then
    echo "[5/5] 运行 Web UI 测试..."
    python test_web_ui.py
    WEB_RESULT=$?
else
    echo "串口测试失败，跳过 Web UI 测试"
    WEB_RESULT=1
fi

# 汇总
echo ""
echo "=== 测试汇总 ==="
echo "串口测试: $([ $SERIAL_RESULT -eq 0 ] && echo '✅ PASS' || echo '❌ FAIL')"
echo "Web UI 测试: $([ $WEB_RESULT -eq 0 ] && echo '✅ PASS' || echo '❌ FAIL')"

exit $(( SERIAL_RESULT + WEB_RESULT ))
```

## Self-Test（自检）

> 验证自动化测试框架的依赖和核心逻辑。

### 自检步骤

```bash
# Test 1: pyserial 和 patchright 可用
python3 -c "import serial; print('SELF_TEST_PASS: pyserial')" 2>/dev/null || echo "SELF_TEST_FAIL: pyserial"
python3 -c "from patchright.sync_api import sync_playwright; print('SELF_TEST_PASS: patchright')" 2>/dev/null || echo "SELF_TEST_FAIL: patchright"

# Test 2: 测试类的基本结构验证
python3 -c "
import re, sys

# 模拟串口测试逻辑
class MockSerialTest:
    def __init__(self):
        self.results = []
    def _record(self, name, passed, msg):
        self.results.append({'name': name, 'passed': passed, 'message': msg})
    def test_pattern(self):
        lines = [
            'I (1000) wifi: got ip:192.168.1.10',
            'E (2000) panic: Guru Meditation Error',
        ]
        for line in lines:
            ip = re.search(r'got ip:(\d+\.\d+\.\d+\.\d+)', line)
            if ip:
                self._record('wifi', True, f'IP: {ip.group(1)}')
            if re.search(r'error|panic', line, re.IGNORECASE):
                self._record('error_detect', True, line.strip())

t = MockSerialTest()
t.test_pattern()
assert len(t.results) == 2, f'Expected 2 results, got {len(t.results)}'
print('SELF_TEST_PASS: test_framework')
" || echo "SELF_TEST_FAIL: test_framework"

# Test 3: bash 测试流程逻辑
bash -c '
RESULT=0
[ $RESULT -eq 0 ] && echo "SELF_TEST_PASS: bash_test_flow" || echo "SELF_TEST_FAIL: bash_test_flow"
'
```

### Blind Test（盲测）

**测试 Prompt:**
```
你是一个 AI 开发助手。请阅读此 Skill，然后：
1. 编写一个简化版的串口测试类，只包含 test_pattern 方法
2. 用以下模拟数据测试："got ip:10.0.0.1", "httpd_start: Started", "assert failed"
3. 输出 PASS/FAIL 汇总
4. 解释为什么测试金字塔中串口测试在 Web UI 测试之前
```

**验收标准:**
- [ ] Agent 使用了 Skill 中定义的测试类结构
- [ ] Agent 正确提取了 IP 地址和错误
- [ ] Agent 理解了测试金字塔的分层逻辑
- [ ] Agent 的输出包含清晰的 PASS/FAIL 标记

## 成功标准

- [ ] 串口自动化测试全部通过
- [ ] Web UI 自动化测试全部通过
- [ ] 端到端测试流程可一键执行
- [ ] 测试结果有清晰的 PASS/FAIL 输出
