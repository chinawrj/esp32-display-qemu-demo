---
name: code-refactoring
description: 周期性代码重构策略，根据代码健康指标自适应触发重构。Use when code quality metrics exceed thresholds (file too large, too many warnings, duplicate code, excessive TODOs), or when planning a refactoring day.
---

# Skill: 代码重构策略

## 用途

定义周期性代码重构的策略和流程，确保在持续开发中保持代码质量。

**何时使用：**
- 每 5 个迭代日进行一次计划重构
- 发现代码异味（code smell）时
- 功能完成后的清理阶段
- 代码复杂度超过阈值时

**何时不使用：**
- 项目初期原型阶段（先让功能跑起来）
- 紧急 bug 修复中
- 代码质量已经很好的模块

## 前置条件

- 所有当前测试通过（重构前必须有绿灯）
- Git 工作区干净（无未提交的改动）
- 已明确重构目标

## 操作步骤

### 1. 重构触发条件

每次重构前评估以下指标：

| 指标 | 阈值 | 检测方法 |
|------|------|---------|
| 函数行数 | > 50 行 | `wc -l` |
| 文件行数 | > 500 行 | `wc -l` |
| 重复代码 | > 3 处 | `grep` 搜索 |
| TODO/FIXME | > 5 个 | `grep -rn "TODO\|FIXME"` |
| 嵌套层级 | > 4 层 | 代码审查 |
| 全局变量 | > 10 个 | `grep` 搜索 |

### 2. 重构检查清单

```markdown
## 重构清单 - Day N

### 代码检查
- [ ] 查找超长函数并拆分
- [ ] 提取重复代码为公共函数
- [ ] 消除魔术数字，定义常量
- [ ] 检查命名一致性
- [ ] 清理无用的 #include / import
- [ ] 处理所有 TODO/FIXME

### 架构检查
- [ ] 模块间依赖是否合理
- [ ] 接口是否清晰（输入/输出明确）
- [ ] 错误处理是否一致
- [ ] 内存管理是否正确（嵌入式重点）

### 文档检查
- [ ] README 是否与代码同步
- [ ] 关键函数是否有注释
- [ ] 配置说明是否完整
```

### 3. 安全重构流程

```bash
# Step 1: 确保测试通过
idf.py build && python test_serial.py && echo "绿灯 ✅"

# Step 2: 创建重构分支
git checkout -b refactor/day-N-cleanup

# Step 3: 执行重构（小步提交）
# ... 代码修改 ...
git add -A && git commit -m "refactor: 提取 WiFi 初始化为独立模块"

# ... 更多修改 ...
git add -A && git commit -m "refactor: 消除 main.c 中的魔术数字"

# Step 4: 重构后验证
idf.py build && python test_serial.py && echo "重构后仍然绿灯 ✅"

# Step 5: 合并
git checkout main && git merge refactor/day-N-cleanup
```

### 4. ESP32/嵌入式特定重构

#### 内存优化
```c
// Before: 栈上分配大缓冲区
void handle_request() {
    char buf[4096];  // 可能导致栈溢出
    // ...
}

// After: 使用堆分配或静态分配
static char s_buf[4096];  // 或使用 malloc/free
void handle_request() {
    // 使用 s_buf
}
```

#### 模块化
```
// Before: 所有代码在 main.c
main.c (800 lines)

// After: 按功能拆分
main.c          (50 lines)  - 入口和初始化调度
wifi_manager.c  (150 lines) - WiFi 管理
http_server.c   (200 lines) - HTTP 服务
camera_ctrl.c   (150 lines) - 摄像头控制
sensor_reader.c (100 lines) - 传感器读取
```

#### 错误处理统一
```c
// 定义统一的错误处理宏
#define CHECK_ESP_ERR(x, tag) do { \
    esp_err_t err = (x); \
    if (err != ESP_OK) { \
        ESP_LOGE(tag, "%s failed: %s", #x, esp_err_to_name(err)); \
        return err; \
    } \
} while(0)
```

### 5. 重构报告

每次重构后生成报告：

```markdown
## 重构报告 - Day N

### 变更摘要
- 拆分文件: main.c → 5 个模块文件
- 消除重复: 3 处重复代码提取为公共函数
- 清理: 移除 8 个 TODO，2 个未使用变量

### 代码指标变化
| 指标 | 重构前 | 重构后 |
|------|--------|--------|
| 最大函数行数 | 120 | 45 |
| 文件数 | 2 | 6 |
| TODO 数量 | 12 | 4 |

### 测试结果
- 编译: ✅ 通过
- 串口测试: ✅ 5/5 通过
- Web UI 测试: ✅ 4/4 通过
```

## Self-Test（自检）

> 验证重构工作流的工具和流程。

### 自检步骤

```bash
# Test 1: Git 可用且支持分支操作
TMP_REPO=$(mktemp -d)
cd "$TMP_REPO" && git init -q && \
  echo "init" > file.txt && git add . && git commit -q -m "init" && \
  git checkout -q -b refactor/test && \
  echo "refactored" > file.txt && git add . && git commit -q -m "refactor: test" && \
  git checkout -q main && git merge -q refactor/test && \
  echo "SELF_TEST_PASS: git_branch_workflow" || echo "SELF_TEST_FAIL: git_branch_workflow"
rm -rf "$TMP_REPO"

# Test 2: 代码检查工具可用
command -v grep &>/dev/null && command -v wc &>/dev/null && \
  echo "SELF_TEST_PASS: code_analysis_tools" || echo "SELF_TEST_FAIL: code_analysis_tools"

# Test 3: TODO/FIXME 检测逻辑
TMP_FILE=$(mktemp)
cat > "$TMP_FILE" << 'EOF'
// TODO: fix this
// FIXME: memory leak
void ok_function() {}
// TODO: another one
EOF
COUNT=$(grep -c 'TODO\|FIXME' "$TMP_FILE")
[ "$COUNT" -eq 3 ] && echo "SELF_TEST_PASS: todo_detection ($COUNT found)" || echo "SELF_TEST_FAIL: todo_detection (expected 3, got $COUNT)"
rm "$TMP_FILE"

# Test 4: 函数行数检测
TMP_SRC=$(mktemp --suffix=.c 2>/dev/null || mktemp)
for i in $(seq 1 60); do echo "line $i;" >> "$TMP_SRC"; done
LINES=$(wc -l < "$TMP_SRC")
[ "$LINES" -gt 50 ] && echo "SELF_TEST_PASS: long_function_detect ($LINES lines)" || echo "SELF_TEST_FAIL: long_function_detect"
rm "$TMP_SRC"
```

### Blind Test（盲测）

**测试 Prompt:**
```
你是一个 AI 开发助手。请阅读此 Skill，然后对以下代码进行重构分析：

void handle_everything() {
    // 60 行 WiFi 初始化代码
    // 40 行 HTTP 服务器代码
    // 30 行传感器读取代码
    // 5 个 TODO 和 2 个 FIXME
    // 3 处重复的错误处理代码
}

1. 识别所有重构触发条件（参考 Skill 中的阈值表）
2. 提出具体的重构方案（拆分为哪几个模块）
3. 生成重构报告模板
```

**验收标准:**
- [ ] Agent 识别了函数超长（130行 > 50行阈值）
- [ ] Agent 识别了 TODO/FIXME 超标（7 > 5）
- [ ] Agent 识别了重复代码
- [ ] Agent 提出了拆分为 wifi_manager, http_server, sensor_reader 的方案
- [ ] Agent 生成了符合 Skill 格式的重构报告

## 成功标准

- [ ] 重构前后所有测试保持通过
- [ ] 代码指标有明显改善
- [ ] Git 历史清晰，每次重构小步提交
- [ ] 重构报告已生成
