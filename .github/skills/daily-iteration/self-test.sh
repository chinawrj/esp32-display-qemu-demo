#!/bin/bash
# self-test for daily-iteration
# 运行: bash skills/daily-iteration/self-test.sh

PASS=0
FAIL=0

test_case() {
  local name=$1; shift
  if "$@" 2>/dev/null; then
    echo "SELF_TEST_PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "SELF_TEST_FAIL: $name"
    FAIL=$((FAIL + 1))
  fi
}

# --- Test 1: 目录结构创建 ---
test_case "docs_dir_creation" bash -c '
  TMP=$(mktemp -d)
  mkdir -p "$TMP/docs/daily-logs" && [ -d "$TMP/docs/daily-logs" ]
  RC=$?; rm -rf "$TMP"; exit $RC
'

# --- Test 2: Markdown 模板渲染 ---
test_case "markdown_template" bash -c '
  TMP=$(mktemp -d)
  mkdir -p "$TMP/docs/daily-logs"
  cat > "$TMP/docs/daily-logs/day-001.md" << EOF
## Day 1 计划
**日期:** 2025-01-01
**目标:** 基础框架搭建

### 任务列表
- [ ] 初始化项目
- [ ] 配置编译环境
- [x] 创建目录结构

### 验证结果
| 项目 | 状态 |
|------|------|
| 编译 | ⏳ |
EOF
  # 验证 markdown 结构
  grep -q "## Day 1" "$TMP/docs/daily-logs/day-001.md" && \
  grep -q "\- \[ \]" "$TMP/docs/daily-logs/day-001.md" && \
  grep -q "\- \[x\]" "$TMP/docs/daily-logs/day-001.md"
  RC=$?; rm -rf "$TMP"; exit $RC
'

# --- Test 3: checklist 完成度统计 ---
test_case "checklist_stats" bash -c '
  TMP=$(mktemp)
  cat > "$TMP" << EOF
- [x] task 1
- [ ] task 2
- [x] task 3
- [ ] task 4
- [x] task 5
EOF
  TOTAL=$(grep -c "\- \[" "$TMP")
  DONE=$(grep -c "\- \[x\]" "$TMP")
  rm "$TMP"
  [ "$TOTAL" -eq 5 ] && [ "$DONE" -eq 3 ]
'

# --- Test 4: 日期格式生成 ---
test_case "date_format" bash -c '
  DATE=$(date +%Y-%m-%d)
  echo "$DATE" | grep -qE "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
'

# --- Test 5: 日志文件命名模式 ---
test_case "log_naming_pattern" bash -c '
  for i in 1 10 100; do
    NAME=$(printf "day-%03d.md" $i)
    echo "$NAME" | grep -qE "^day-[0-9]{3}\.md$" || exit 1
  done
'

# --- 汇总 ---
echo ""
echo "Results: $PASS passed, $FAIL failed"
exit $FAIL
