---
name: environment-setup
description: 开发环境检查与配置，验证工具链、驱动和依赖是否就绪。Use when starting a project for the first time, after switching machines, after upgrading toolchains, or when diagnosing build environment issues.
---

# Skill: 开发环境检查与配置

## 用途

在项目开始前验证开发环境是否就绪，检查工具链、驱动、Python 包等依赖是否已正确安装和配置。

**何时使用：**
- 项目启动的第一步（Day 0）
- 更换开发机器后
- 工具链升级后需要重新验证
- CI 环境初始化

**何时不使用：**
- 环境已验证且未发生变更
- 仅做代码审查，不执行构建

## 前置条件

- 操作系统：macOS / Linux
- 基本命令行工具可用（bash/zsh, which, python3）

## 操作步骤

### 1. 基础工具检查

```bash
#!/bin/bash
# check-env.sh - 开发环境检查脚本

echo "=== 开发环境检查 ==="
ERRORS=0

check_cmd() {
    local cmd=$1
    local name=${2:-$1}
    if command -v "$cmd" &>/dev/null; then
        echo "  ✓ $name: $(command -v "$cmd")"
    else
        echo "  ✗ $name: 未安装"
        ERRORS=$((ERRORS + 1))
    fi
}

# 基础工具
echo ""
echo "[基础工具]"
check_cmd git "Git"
check_cmd python3 "Python3"
check_cmd pip3 "pip3"
check_cmd tmux "tmux"

# ESP-IDF 工具链（如适用）
echo ""
echo "[ESP-IDF 工具链]"
if [ -f "$HOME/esp/esp-idf/export.sh" ]; then
    echo "  ✓ ESP-IDF: $HOME/esp/esp-idf"
    source "$HOME/esp/esp-idf/export.sh" 2>/dev/null
    check_cmd idf.py "idf.py"
    check_cmd xtensa-esp32-elf-gcc "xtensa 编译器"
else
    echo "  ✗ ESP-IDF: 未找到 (期望路径: ~/esp/esp-idf/)"
    ERRORS=$((ERRORS + 1))
fi

# 串口设备
echo ""
echo "[串口设备]"
PORTS=$(ls /dev/tty.usb* /dev/cu.usb* /dev/ttyUSB* /dev/ttyACM* 2>/dev/null)
if [ -n "$PORTS" ]; then
    echo "$PORTS" | while read p; do echo "  ✓ $p"; done
else
    echo "  ⚠ 未检测到 USB 串口设备（设备未连接？）"
fi

# Python 包
echo ""
echo "[Python 包]"
for pkg in patchright pyyaml pyserial; do
    if python3 -c "import ${pkg//-/_}" 2>/dev/null; then
        echo "  ✓ $pkg"
    else
        echo "  ✗ $pkg: 未安装 (pip3 install $pkg)"
        ERRORS=$((ERRORS + 1))
    fi
done

# Patchright 浏览器驱动
echo ""
echo "[浏览器驱动]"
CHROMIUM_DIR="$HOME/Library/Caches/ms-playwright"
if [ -d "$CHROMIUM_DIR" ] && ls "$CHROMIUM_DIR"/chromium-* &>/dev/null; then
    echo "  ✓ Chromium 驱动: $(ls -d "$CHROMIUM_DIR"/chromium-* | head -1)"
else
    echo "  ✗ Chromium 驱动未安装 (python -m patchright install chromium)"
    ERRORS=$((ERRORS + 1))
fi

# 汇总
echo ""
echo "================================"
if [ $ERRORS -eq 0 ]; then
    echo "✅ 环境检查通过，可以开始开发"
else
    echo "❌ 发现 $ERRORS 个问题，请先修复"
fi
exit $ERRORS
```

### 2. ESP-IDF 版本确认

```bash
# 检查 ESP-IDF 版本
idf.py --version

# 检查支持的芯片
idf.py --list-targets
```

### 3. Python 虚拟环境

```bash
# 如果使用 Patchright，确认虚拟环境
source ~/patchright-env/bin/activate
python -c "import patchright; print(f'Patchright {patchright.__version__}')"
```

### 4. 网络连通性

```bash
# 检查能否访问设备（如已知 IP）
ping -c 3 {{DEVICE_IP}} 2>/dev/null && echo "✓ 设备可达" || echo "✗ 设备不可达"

# 检查 CDP 端口
curl -s http://localhost:9222/json/version && echo "✓ CDP 可用" || echo "⚠ CDP 未启动"
```

## Self-Test（自检）

> 以下测试用于验证本 Skill 的指令在当前环境下是否有效。AI Agent 应在首次使用此 Skill 时执行自检。

### 自检步骤

```bash
# Test 1: check-env.sh 脚本可以执行
bash -c 'command -v git && command -v python3 && echo "SELF_TEST_PASS: basic_tools"'

# Test 2: Python 可以导入 yaml
python3 -c "import yaml; print('SELF_TEST_PASS: pyyaml')" 2>/dev/null || echo "SELF_TEST_FAIL: pyyaml"

# Test 3: tmux 可交互
tmux new-session -d -s __selftest__ && tmux kill-session -t __selftest__ && echo "SELF_TEST_PASS: tmux" || echo "SELF_TEST_FAIL: tmux"
```

### 预期结果

| 测试项 | 预期输出 | 失败影响 |
|--------|---------|---------|
| basic_tools | `SELF_TEST_PASS: basic_tools` | 缺少基础工具，无法继续 |
| pyyaml | `SELF_TEST_PASS: pyyaml` | builder 引擎无法运行 |
| tmux | `SELF_TEST_PASS: tmux` | 多窗口工作流不可用 |

### Blind Test（盲测）

> Blind Test 模拟 AI Agent 首次阅读此 Skill 后独立执行的场景，不提供额外上下文。

**测试 Prompt:**
```
你是一个 AI 开发助手。请阅读以下 Skill 并在当前机器上执行环境检查。
不要假设任何工具已安装，按照 Skill 中的步骤逐一验证。
将结果汇总为一个表格，标注每项的状态（✓/✗/⚠）。
```

**验收标准:**
- [ ] Agent 能正确执行 check-env.sh 中的检查逻辑
- [ ] Agent 不会跳过任何检查步骤
- [ ] Agent 能正确识别缺失的工具并给出安装建议
- [ ] Agent 输出结果为清晰的表格格式

## 成功标准

- [ ] 所有必需工具已安装并可执行
- [ ] ESP-IDF 环境加载成功
- [ ] 串口设备可检测到（如已连接）
- [ ] Python 依赖包均已安装
- [ ] 浏览器驱动可用（如需 Web 测试）
