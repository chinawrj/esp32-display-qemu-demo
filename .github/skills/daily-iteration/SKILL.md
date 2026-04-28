---
name: daily-iteration
description: 每日迭代开发工作流，包含晨会计划、执行开发和晚间回顾三个阶段。Use when starting a new development day, planning daily tasks, reviewing progress, or managing the daily development cycle.
---

# Skill: 每日迭代工作流

## 用途

定义 AI agent 驱动的每日开发迭代流程，包括计划制定、任务执行、进度验证和日报输出。

**何时使用：**
- 需要结构化的开发节奏
- 项目周期超过 1 天
- 需要跟踪进度和里程碑

**何时不使用：**
- 一次性小任务
- 不需要迭代的简单项目

## 前置条件

- 项目需求文档已确定（`requirements.md`）
- 工作流 Agent 已配置
- 开发环境已就绪

## 操作步骤

### 1. 每日迭代模型

```
┌─────────────────────────────────────────────────┐
│                 每日迭代循环                       │
│                                                  │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐    │
│  │ Morning  │──▶│ Execute  │──▶│ Evening  │    │
│  │ Planning │   │ & Test   │   │ Review   │    │
│  └──────────┘   └──────────┘   └──────────┘    │
│       │                              │           │
│       └──────── 下一天 ◀─────────────┘           │
└─────────────────────────────────────────────────┘
```

### 2. Morning Planning（晨会计划）

每日开始时执行：

```markdown
## Day N 计划

### 昨日回顾
- 完成: [列出完成的任务]
- 未完成: [列出未完成任务及原因]
- 阻塞: [列出阻塞项]

### 今日目标
1. [目标1] - 预计耗时
2. [目标2] - 预计耗时
3. [目标3] - 预计耗时

### 风险与依赖
- [风险项]

### 验收检查点
- [ ] [检查项1]
- [ ] [检查项2]
```

### 3. Execute & Test（执行与测试）

每个任务遵循以下流程：

```
编写代码 → 编译检查 → 烧录测试 → 串口验证 → Web UI 验证
    ↑                                            │
    └────── 修复问题 ◀──────────────────────────┘
```

关键规则：
- 每个任务完成后立即运行测试
- 测试失败必须在继续下一任务前修复
- 每完成一个里程碑进行 git commit

### 4. Evening Review（晚间回顾）

每日结束时：

```markdown
## Day N 回顾

### 完成状态
| 任务 | 状态 | 备注 |
|------|------|------|
| 任务1 | ✅ 完成 | |
| 任务2 | ⚠️ 部分完成 | 原因: ... |
| 任务3 | ❌ 未开始 | 阻塞: ... |

### 代码质量
- 新增代码行数: N
- 测试通过率: N%
- 已知问题: [列出]

### 明日计划
- [优先任务]

### 技术笔记
- [记录今天学到的关键信息]
```

### 5. 里程碑检查

每 3-5 天进行一次里程碑评审：

```markdown
## 里程碑 M: {{MILESTONE_NAME}}

### 目标达成度
- [x] 子目标1
- [ ] 子目标2 (进度 70%)
- [ ] 子目标3 (未开始)

### 整体进度: N%

### 是否需要调整计划: 是/否
### 调整内容: ...
```

### 6. 重构窗口

每 5 个迭代日安排一次重构：
- 审查代码复杂度
- 消除技术债务
- 优化性能瓶颈
- 更新文档

## 工作日志格式

所有日志保存在 `docs/daily-logs/` 目录：

```
docs/daily-logs/
├── day-001.md
├── day-002.md
├── ...
└── milestone-1-review.md
```

## Self-Test（自检）

> 验证每日迭代工作流的文档生成和跟踪机制。

### 自检步骤

```bash
# Test 1: docs 目录可创建
mkdir -p /tmp/__selftest_daily__/docs/daily-logs && \
  echo "SELF_TEST_PASS: docs_dir" || echo "SELF_TEST_FAIL: docs_dir"

# Test 2: Markdown 模板渲染
cat > /tmp/__selftest_daily__/docs/daily-logs/day-001.md << 'PLAN'
## Day 1 计划
### 昨日回顾
- 完成: 项目初始化
### 今日目标
1. [x] 搭建项目框架
2. [ ] 实现 WiFi 连接
### 验收检查点
- [x] 编译通过
PLAN
grep -c '\[x\]' /tmp/__selftest_daily__/docs/daily-logs/day-001.md | \
  xargs -I{} bash -c '[ {} -ge 1 ] && echo "SELF_TEST_PASS: plan_format" || echo "SELF_TEST_FAIL: plan_format"'

# Test 3: Git 可用于提交跟踪
command -v git &>/dev/null && echo "SELF_TEST_PASS: git_available" || echo "SELF_TEST_FAIL: git_available"

rm -rf /tmp/__selftest_daily__
```

### Blind Test（盲测）

**测试 Prompt:**
```
你是一个 AI 开发助手。请阅读此 Skill，然后为一个名为 "test-project" 的项目
生成 Day 1 的完整工作计划文档，包含：
- 晨会计划（3 个具体目标）
- 执行记录模板
- 晚间回顾模板
项目目标是"搭建 ESP32 WiFi HTTP 服务器"。
输出完整的 Markdown 文档。
```

**验收标准:**
- [ ] Agent 生成了包含所有三个部分的文档
- [ ] 目标是具体的、可执行的（而非模糊的）
- [ ] 文档使用了 checkbox 格式
- [ ] Agent 参考了 Skill 中的模板格式

## 成功标准

- [ ] 每日计划和回顾文档已生成
- [ ] 任务执行有对应的测试验证
- [ ] Git 提交与任务完成同步
- [ ] 里程碑按时评审
- [ ] 重构窗口按计划执行
