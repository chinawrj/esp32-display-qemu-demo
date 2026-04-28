#!/bin/bash
# self-test for code-refactoring
# 运行: bash skills/code-refactoring/self-test.sh

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

# --- Test 1: git 分支工作流 ---
test_case "git_branch_workflow" bash -c '
  TMP_REPO=$(mktemp -d)
  cd "$TMP_REPO" && git init -q && \
    git config user.email "test@test.com" && git config user.name "test" && \
    echo "init" > file.txt && git add . && git commit -q -m "init" && \
    git checkout -q -b refactor/test && \
    echo "refactored" > file.txt && git add . && git commit -q -m "refactor: test" && \
    git checkout -q main && git merge -q refactor/test
  RC=$?
  rm -rf "$TMP_REPO"
  exit $RC
'

# --- Test 2: 代码分析工具可用 ---
test_case "code_analysis_tools" bash -c '
  command -v grep &>/dev/null && command -v wc &>/dev/null && command -v sort &>/dev/null
'

# --- Test 3: TODO/FIXME 检测 ---
test_case "todo_detection" bash -c '
  TMP_FILE=$(mktemp)
  cat > "$TMP_FILE" << EOF
// TODO: fix this
// FIXME: memory leak
void ok_function() {}
// TODO: another one
EOF
  COUNT=$(grep -c "TODO\|FIXME" "$TMP_FILE")
  rm "$TMP_FILE"
  [ "$COUNT" -eq 3 ]
'

# --- Test 4: 长函数检测 ---
test_case "long_function_detect" bash -c '
  TMP_SRC=$(mktemp)
  for i in $(seq 1 60); do echo "line $i;" >> "$TMP_SRC"; done
  LINES=$(wc -l < "$TMP_SRC")
  rm "$TMP_SRC"
  [ "$LINES" -gt 50 ]
'

# --- Test 5: 重构分支命名规范 ---
test_case "branch_naming" bash -c '
  echo "refactor/extract-wifi-module" | grep -qE "^refactor/"
'

# --- 汇总 ---
echo ""
echo "Results: $PASS passed, $FAIL failed"
exit $FAIL
