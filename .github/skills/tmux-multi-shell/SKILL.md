---
name: tmux-multi-shell
description: tmux 多终端管理，为 AI Agent 提供可靠的多终端自动化能力。Use when you need to run multiple terminal tasks in parallel (build, flash, serial monitor), need persistent terminal sessions, or need to send commands and reliably capture their output and exit codes.
---

# Skill: tmux 多终端管理（AI Agent 优化版）

## 用途

为 AI Agent 提供可靠的多终端自动化操作能力。核心价值：**在多个隔离窗口中并行执行命令，可靠地等待完成、获取完整输出、判断成败。**

**何时使用：**
- 需要同时运行多个终端任务（编译 + 烧录 + 串口监控）
- 需要持久化终端会话（Agent 重启后可恢复）
- 需要发送命令并可靠地获取结果

**何时不使用：**
- 单终端任务足够的情况
- 非命令行环境

## 前置条件

- `tmux` 已安装（macOS: `brew install tmux`, Linux: `apt install tmux`）
- 终端支持 tmux

## 操作步骤

### 1. 幂等创建项目会话（P0）

> **关键：** Agent 可能重启或重试，必须用 `has-session` 避免重复创建。

```bash
# 幂等创建 — 会话已存在则跳过，不存在则新建
tmux has-session -t {{PROJECT_NAME}} 2>/dev/null || {
  tmux new-session -d -s {{PROJECT_NAME}}
  tmux rename-window -t {{PROJECT_NAME}}:0 'edit'
  tmux new-window -t {{PROJECT_NAME}} -n 'build'
  tmux new-window -t {{PROJECT_NAME}} -n 'flash'
  tmux new-window -t {{PROJECT_NAME}} -n 'monitor'
  echo "[tmux] Session '{{PROJECT_NAME}}' created with 4 windows"
}

# 验证会话就绪
tmux list-windows -t {{PROJECT_NAME}} -F '#{window_index}:#{window_name}'
```

```bash
# 幂等添加单个窗口 — 已存在则跳过
tmux list-windows -t {{PROJECT_NAME}} -F '#{window_name}' | grep -q '^build$' || \
  tmux new-window -t {{PROJECT_NAME}} -n 'build'
```

### 2. 标准窗口布局

| 窗口编号 | 名称 | 用途 |
|---------|------|------|
| 0 | edit | 代码编辑/git 操作 |
| 1 | build | 编译构建 |
| 2 | flash | 烧录固件 |
| 3 | monitor | 串口日志监控 |

### 3. 发送命令到指定窗口

```bash
# 在 build 窗口执行编译
tmux send-keys -t {{PROJECT_NAME}}:build 'idf.py build' C-m

# 在 flash 窗口执行烧录
tmux send-keys -t {{PROJECT_NAME}}:flash 'idf.py -p /dev/ttyUSB0 flash' C-m

# 在 monitor 窗口启动串口监控
tmux send-keys -t {{PROJECT_NAME}}:monitor 'idf.py -p /dev/ttyUSB0 monitor' C-m
```

### 4. 等待命令完成 + 退出码检测（P0）

> **核心模式：** AI Agent 的操作闭环 — 发命令 → 等完成 → 读退出码 → 判断成败。

**原理：** 用 sentinel 标记包裹实际命令，通过轮询 `capture-pane` 检测 sentinel 出现来判断完成。

```bash
# === 发送带 sentinel 的命令 ===
# 格式: 实际命令; 然后输出 sentinel + 退出码
SENTINEL="__DONE_$(date +%s)__"
tmux send-keys -t {{PROJECT_NAME}}:build \
  "idf.py build; echo \"${SENTINEL}_EXIT_\$?\"" C-m

# === 轮询等待完成（带超时） ===
TIMEOUT=120  # 秒
ELAPSED=0
INTERVAL=2   # 每 2 秒检查一次
sleep 1      # 等待命令开始执行
while [ $ELAPSED -lt $TIMEOUT ]; do
  OUTPUT=$(tmux capture-pane -t {{PROJECT_NAME}}:build -p -S -1000)
  if echo "$OUTPUT" | grep -q "${SENTINEL}_EXIT_[0-9]"; then
    # 提取退出码
    EXIT_CODE=$(echo "$OUTPUT" | grep -o "${SENTINEL}_EXIT_[0-9][0-9]*" | head -1 | grep -o '[0-9]*$')
    if [ "$EXIT_CODE" = "0" ]; then
      echo "[OK] Command succeeded (exit code 0)"
    else
      echo "[FAIL] Command failed (exit code $EXIT_CODE)"
    fi
    break
  fi
  sleep $INTERVAL
  ELAPSED=$((ELAPSED + INTERVAL))
done

if [ $ELAPSED -ge $TIMEOUT ]; then
  echo "[TIMEOUT] Command did not complete within ${TIMEOUT}s"
fi
```

**简化版 — 封装为函数：**

```bash
# tmux_exec: 在指定窗口执行命令，等待完成，返回退出码
# 用法: tmux_exec <session:window> <command> [timeout_seconds]
tmux_exec() {
  local target="$1"
  local cmd="$2"
  local timeout="${3:-120}"
  local sentinel="__DONE_${RANDOM}__"

  # 发送命令
  tmux send-keys -t "$target" "$cmd; echo \"${sentinel}_EXIT_\$?\"" C-m

  # 轮询等待
  local elapsed=0
  sleep 1  # 等待命令开始执行
  while [ $elapsed -lt $timeout ]; do
    local output
    output=$(tmux capture-pane -t "$target" -p -S -1000)
    local match
    match=$(echo "$output" | grep -o "${sentinel}_EXIT_[0-9][0-9]*" | head -1)
    if [ -n "$match" ]; then
      echo "$output"  # 输出完整内容供调用方分析
      local code
      code=$(echo "$match" | grep -o '[0-9]*$')
      return "${code:-1}"
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done

  echo "[TIMEOUT] after ${timeout}s"
  return 124  # 与 GNU timeout 保持一致
}

# 使用示例
tmux_exec "{{PROJECT_NAME}}:build" "idf.py build" 300
if [ $? -eq 0 ]; then
  echo "Build succeeded, proceeding to flash..."
  tmux_exec "{{PROJECT_NAME}}:flash" "idf.py -p /dev/ttyUSB0 flash" 60
fi
```

### 5. 完整输出捕获（P0）

> **关键：** 默认 `capture-pane -p` 只捕获可见区域（约 50 行）。编译错误可能在几百行前，AI 必须读取完整历史。

```bash
# 捕获最近 1000 行历史（覆盖大多数编译输出）
tmux capture-pane -t {{PROJECT_NAME}}:build -p -S -1000

# 捕获全部历史（从缓冲区起始位置）
tmux capture-pane -t {{PROJECT_NAME}}:build -p -S -

# 捕获并保存到文件（适合超长输出分析）
tmux capture-pane -t {{PROJECT_NAME}}:build -p -S - > /tmp/build-output.txt
wc -l /tmp/build-output.txt  # 检查行数

# 只读最后 N 行（节省 Agent 上下文窗口）
tmux capture-pane -t {{PROJECT_NAME}}:build -p -S -1000 | tail -50
```

**设置更大的历史缓冲区（创建会话前）：**

```bash
# 将回滚缓冲区设为 10000 行（默认 2000）
tmux set-option -g history-limit 10000
```

### 6. 超时处理与命令中止（P1）

> **场景：** 命令挂死（如等待用户输入、网络超时），AI 需要主动中止并恢复。

```bash
# 方式 1: 发送 Ctrl+C 中止当前命令
tmux send-keys -t {{PROJECT_NAME}}:build C-c

# 方式 2: 发送 Ctrl+C 后等待 shell prompt 恢复
tmux send-keys -t {{PROJECT_NAME}}:build C-c
sleep 1
# 检查是否回到 shell prompt（通过发送空 echo 测试）
tmux send-keys -t {{PROJECT_NAME}}:build 'echo __SHELL_READY__' C-m
sleep 1
tmux capture-pane -t {{PROJECT_NAME}}:build -p | grep -q __SHELL_READY__ && \
  echo "Shell recovered" || echo "Shell still stuck"

# 方式 3: 强制杀死窗口并重建（最后手段）
tmux kill-window -t {{PROJECT_NAME}}:build
tmux new-window -t {{PROJECT_NAME}} -n 'build'
```

**tmux_exec 已内置超时处理**（见第 4 节），超时返回退出码 124。典型处理链：

```bash
tmux_exec "{{PROJECT_NAME}}:build" "idf.py build" 300
rc=$?
case $rc in
  0)   echo "Success" ;;
  124) echo "Timeout — sending Ctrl+C"
       tmux send-keys -t {{PROJECT_NAME}}:build C-c ;;
  *)   echo "Failed with exit code $rc" ;;
esac
```

### 7. 结构化输出解析（P1）

> **目标：** 从原始 capture-pane 文本中提取 AI 可直接使用的结构化信息，而非依赖 grep 碰运气。

```bash
# === ESP-IDF 编译输出解析 ===
OUTPUT=$(tmux capture-pane -t {{PROJECT_NAME}}:build -p -S -1000)

# 提取错误计数
ERROR_COUNT=$(echo "$OUTPUT" | grep -c "^.*error:")
WARNING_COUNT=$(echo "$OUTPUT" | grep -c "^.*warning:")

# 提取编译进度（ESP-IDF 格式: [nn/mm]）
PROGRESS=$(echo "$OUTPUT" | grep -oE '\[[0-9]+/[0-9]+\]' | tail -1)

# 提取固件大小（如果编译成功）
FIRMWARE_SIZE=$(echo "$OUTPUT" | grep -oE 'Binary size: [0-9.]+ [KM]B' | tail -1)

# 汇总报告
echo "=== Build Summary ==="
echo "Errors:   $ERROR_COUNT"
echo "Warnings: $WARNING_COUNT"
echo "Progress: $PROGRESS"
echo "Firmware: $FIRMWARE_SIZE"
```

```bash
# === 通用命令输出解析模式 ===
# 提取第一条错误的完整上下文（前后 3 行）
tmux capture-pane -t {{PROJECT_NAME}}:build -p -S -1000 | \
  grep -n "error:" | head -1 | cut -d: -f1 | \
  xargs -I{} sed -n "$(({}>=3?{}-3:1)),$(({} + 3))p" <(
    tmux capture-pane -t {{PROJECT_NAME}}:build -p -S -1000
  )
```

### 8. 并行命令协调（P1）

> **场景：** 同时在多个窗口启动任务，等待全部完成后再继续。

```bash
# === 并行执行，收集所有结果 ===

# 在每个窗口启动命令（带各自的 sentinel）
S1="__DONE_build_${RANDOM}__"
S2="__DONE_test_${RANDOM}__"

tmux send-keys -t {{PROJECT_NAME}}:build "make build; echo \"${S1}_EXIT_\$?\"" C-m
tmux send-keys -t {{PROJECT_NAME}}:edit  "make test; echo \"${S2}_EXIT_\$?\"" C-m

# 等待所有命令完成
TIMEOUT=300
ELAPSED=0
BUILD_DONE=0
TEST_DONE=0

while [ $ELAPSED -lt $TIMEOUT ] && { [ $BUILD_DONE -eq 0 ] || [ $TEST_DONE -eq 0 ]; }; do
  if [ $BUILD_DONE -eq 0 ]; then
    tmux capture-pane -t {{PROJECT_NAME}}:build -p -S -1000 | grep -q "${S1}_EXIT_" && BUILD_DONE=1
  fi
  if [ $TEST_DONE -eq 0 ]; then
    tmux capture-pane -t {{PROJECT_NAME}}:edit -p -S -1000 | grep -q "${S2}_EXIT_" && TEST_DONE=1
  fi
  sleep 2
  ELAPSED=$((ELAPSED + 2))
done

# 汇报结果
echo "Build: $([ $BUILD_DONE -eq 1 ] && echo 'completed' || echo 'TIMEOUT')"
echo "Test:  $([ $TEST_DONE -eq 1 ] && echo 'completed' || echo 'TIMEOUT')"
```

### 9. 会话管理

```bash
# 列出所有会话
tmux list-sessions

# 检查会话是否存在（脚本中使用）
tmux has-session -t {{PROJECT_NAME}} 2>/dev/null && echo "exists" || echo "not found"

# 附加到会话（人类调试时使用）
tmux attach-session -t {{PROJECT_NAME}}

# 安全关闭 — 发送 Ctrl+C 到所有窗口后再销毁
for win in $(tmux list-windows -t {{PROJECT_NAME}} -F '#{window_name}'); do
  tmux send-keys -t "{{PROJECT_NAME}}:${win}" C-c 2>/dev/null
done
sleep 1
tmux kill-session -t {{PROJECT_NAME}}
```

## Self-Test（自检）

> 验证 tmux 可用，且 P0/P1 全部能力正常。

### 自检步骤

```bash
#!/bin/bash
# self-test for tmux-multi-shell
# 运行: bash skills/tmux-multi-shell/self-test.sh

SESSION="__tmux_skill_test__"
PASS=0
FAIL=0

test_case() {
  local name=$1; shift
  if "$@"; then
    echo "SELF_TEST_PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "SELF_TEST_FAIL: $name"
    FAIL=$((FAIL + 1))
  fi
}

cleanup() { tmux kill-session -t $SESSION 2>/dev/null; }
trap cleanup EXIT

# --- Test 1: tmux 已安装 ---
test_case "tmux_installed" command -v tmux

# --- Test 2: 幂等会话创建（P0）---
test_case "idempotent_session" bash -c '
  SESSION="__tmux_skill_test__"
  tmux kill-session -t $SESSION 2>/dev/null
  # 首次创建
  tmux has-session -t $SESSION 2>/dev/null || tmux new-session -d -s $SESSION
  # 重复调用不报错
  tmux has-session -t $SESSION 2>/dev/null || tmux new-session -d -s $SESSION
  # 验证只有一个
  COUNT=$(tmux list-sessions -F "#{session_name}" | grep -c "^${SESSION}$")
  [ "$COUNT" = "1" ]
'

# --- Test 3: 多窗口创建与发送命令 ---
test_case "multi_window" bash -c '
  SESSION="__tmux_skill_test__"
  tmux new-window -t $SESSION -n win_test 2>/dev/null
  tmux send-keys -t $SESSION:win_test "echo hello_tmux_test" C-m
  sleep 1
  tmux capture-pane -t $SESSION:win_test -p | grep -q hello_tmux_test
'

# --- Test 4: 命令完成等待 + 退出码检测（P0）---
test_case "wait_and_exit_code" bash -c '
  SESSION="__tmux_skill_test__"
  SENTINEL="__DONE_TEST_$$__"
  tmux send-keys -t $SESSION:win_test "true; echo \"${SENTINEL}_EXIT_\$?\"" C-m
  sleep 1
  ELAPSED=0
  while [ $ELAPSED -lt 10 ]; do
    OUTPUT=$(tmux capture-pane -t $SESSION:win_test -p -S -100)
    MATCH=$(echo "$OUTPUT" | grep -o "${SENTINEL}_EXIT_[0-9][0-9]*" | head -1)
    if [ -n "$MATCH" ]; then
      CODE=$(echo "$MATCH" | grep -o "[0-9]*$")
      [ "$CODE" = "0" ] && exit 0 || exit 1
    fi
    sleep 1
    ELAPSED=$((ELAPSED + 1))
  done
  exit 1  # timeout
'

# --- Test 5: 失败命令退出码检测（P0）---
test_case "detect_failure_exit_code" bash -c '
  SESSION="__tmux_skill_test__"
  SENTINEL="__DONE_FAIL_$$__"
  tmux send-keys -t $SESSION:win_test "false; echo \"${SENTINEL}_EXIT_\$?\"" C-m
  sleep 1
  ELAPSED=0
  while [ $ELAPSED -lt 10 ]; do
    OUTPUT=$(tmux capture-pane -t $SESSION:win_test -p -S -100)
    MATCH=$(echo "$OUTPUT" | grep -o "${SENTINEL}_EXIT_[0-9][0-9]*" | head -1)
    if [ -n "$MATCH" ]; then
      CODE=$(echo "$MATCH" | grep -o "[0-9]*$")
      [ "$CODE" = "1" ] && exit 0 || exit 1  # 期望退出码=1
    fi
    sleep 1
    ELAPSED=$((ELAPSED + 1))
  done
  exit 1
'

# --- Test 6: 完整输出捕获（P0）---
test_case "full_output_capture" bash -c '
  SESSION="__tmux_skill_test__"
  # 生成 200 行输出（超过可见区域）
  tmux send-keys -t $SESSION:win_test "for i in \$(seq 1 200); do echo \"LINE_\$i\"; done" C-m
  sleep 2
  # 用 -S -1000 捕获，验证能看到第 1 行
  OUTPUT=$(tmux capture-pane -t $SESSION:win_test -p -S -1000)
  echo "$OUTPUT" | grep -q "LINE_1" && echo "$OUTPUT" | grep -q "LINE_200"
'

# --- Test 7: 超时中止（P1）---
test_case "timeout_abort" bash -c '
  SESSION="__tmux_skill_test__"
  # 发送一个会阻塞的命令
  tmux send-keys -t $SESSION:win_test "sleep 60" C-m
  sleep 1
  # Ctrl+C 中止
  tmux send-keys -t $SESSION:win_test C-c
  sleep 1
  # 验证 shell 恢复 — 能执行新命令
  tmux send-keys -t $SESSION:win_test "echo __RECOVERED__" C-m
  sleep 1
  tmux capture-pane -t $SESSION:win_test -p | grep -q __RECOVERED__
'

# --- Test 8: 并行命令协调（P1）---
test_case "parallel_coordination" bash -c '
  SESSION="__tmux_skill_test__"
  tmux new-window -t $SESSION -n win_para 2>/dev/null
  S1="__PARA1_$$__"
  S2="__PARA2_$$__"
  tmux send-keys -t $SESSION:win_test "sleep 1; echo \"${S1}_EXIT_\$?\"" C-m
  tmux send-keys -t $SESSION:win_para "sleep 1; echo \"${S2}_EXIT_\$?\"" C-m
  ELAPSED=0; DONE1=0; DONE2=0
  while [ $ELAPSED -lt 15 ] && { [ $DONE1 -eq 0 ] || [ $DONE2 -eq 0 ]; }; do
    [ $DONE1 -eq 0 ] && tmux capture-pane -t $SESSION:win_test -p -S -100 | grep -q "${S1}_EXIT_" && DONE1=1
    [ $DONE2 -eq 0 ] && tmux capture-pane -t $SESSION:win_para -p -S -100 | grep -q "${S2}_EXIT_" && DONE2=1
    sleep 1
    ELAPSED=$((ELAPSED + 1))
  done
  [ $DONE1 -eq 1 ] && [ $DONE2 -eq 1 ]
'

# --- 汇总 ---
echo ""
echo "Results: $PASS passed, $FAIL failed"
exit $FAIL
```

### 预期结果

| 测试项 | 优先级 | 预期输出 | 验证能力 |
|--------|--------|---------|----------|
| tmux_installed | - | `SELF_TEST_PASS` | tmux 可用 |
| idempotent_session | P0 | `SELF_TEST_PASS` | 重复创建不冲突 |
| multi_window | - | `SELF_TEST_PASS` | 多窗口 + send-keys |
| wait_and_exit_code | P0 | `SELF_TEST_PASS` | sentinel 等待 + 退出码=0 |
| detect_failure_exit_code | P0 | `SELF_TEST_PASS` | 检测命令失败（退出码=1） |
| full_output_capture | P0 | `SELF_TEST_PASS` | -S -1000 读完整历史 |
| timeout_abort | P1 | `SELF_TEST_PASS` | Ctrl+C 中止 + shell 恢复 |
| parallel_coordination | P1 | `SELF_TEST_PASS` | 多窗口并行等待 |

### Blind Test（盲测）

**场景描述:**
AI Agent 需要在 tmux 中编译一个项目，等待完成，检查是否成功，失败时提取错误信息。

**测试 Prompt:**
```
你是一个 AI 开发助手。请阅读此 Skill，然后：
1. 幂等创建名为 "testproj" 的 tmux 会话（如已存在不要重复创建）
2. 确保有 build 窗口
3. 在 build 窗口执行 "echo compile-start && sleep 2 && echo compile-done"
4. 使用 sentinel 模式等待命令完成，获取退出码
5. 用完整输出捕获（-S -1000）验证 "compile-start" 和 "compile-done" 都在输出中
6. 再执行一个会失败的命令 "exit 42"（注意别杀了 shell，用 bash -c），
   验证能检测到非零退出码
7. 最后清理会话
```

**验收标准:**
- [ ] Agent 使用 `has-session` 幂等创建（不是直接 `new-session`）
- [ ] Agent 使用 sentinel + 轮询模式等待命令完成（不是 `sleep` 猜时间）
- [ ] Agent 正确提取退出码并判断成功/失败
- [ ] Agent 使用 `-S -1000` 或 `-S -` 捕获完整输出
- [ ] Agent 检测到失败命令的非零退出码
- [ ] Agent 在完成后清理了测试会话

**常见失败模式:**
- 使用 `sleep 5` 代替 sentinel 等待 → 不可靠，需要强调 sentinel 模式
- 直接 `new-session` 不检查 `has-session` → 重复创建报错
- `capture-pane -p` 不加 `-S` 参数 → 输出不完整
- 用 `exit 42` 直接在窗口执行导致 shell 退出 → 需要 `bash -c "exit 42"`

## 成功标准

- [ ] tmux 会话幂等创建，包含所有必要窗口
- [ ] 每个窗口可独立发送和执行命令
- [ ] 可通过 sentinel 模式等待命令完成并获取退出码
- [ ] 可通过 `capture-pane -S -1000` 获取完整输出历史
- [ ] 命令超时时可通过 Ctrl+C 中止并恢复 shell
- [ ] 多窗口并行命令可协调等待全部完成
- [ ] 会话在 Agent 重启后仍可复用
