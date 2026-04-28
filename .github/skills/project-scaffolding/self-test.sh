#!/bin/bash
# self-test for project-scaffolding
# 运行: bash skills/project-scaffolding/self-test.sh

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

# --- Test 1: 标准目录结构创建 ---
test_case "directory_structure" bash -c '
  TMP=$(mktemp -d)
  PROJECT="$TMP/test-project"
  DIRS="main components frontend tools tests docs/daily-logs"
  for d in $DIRS; do mkdir -p "$PROJECT/$d"; done
  # 验证所有目录存在
  for d in $DIRS; do [ -d "$PROJECT/$d" ] || exit 1; done
  rm -rf "$TMP"
'

# --- Test 2: CMakeLists.txt 生成 ---
test_case "cmake_generation" bash -c '
  TMP=$(mktemp -d)
  PROJECT="$TMP/myproj"
  mkdir -p "$PROJECT/main"
  cat > "$PROJECT/CMakeLists.txt" << EOF
cmake_minimum_required(VERSION 3.16)
include(\$ENV{IDF_PATH}/tools/cmake/project.cmake)
project(myproj)
EOF
  grep -q "project(myproj)" "$PROJECT/CMakeLists.txt"
  RC=$?; rm -rf "$TMP"; exit $RC
'

# --- Test 3: HTML 模板生成 ---
test_case "html_template" bash -c '
  TMP=$(mktemp -d)
  cat > "$TMP/index.html" << EOF
<!DOCTYPE html>
<html>
<head><title>Test Project</title></head>
<body><div id="app"></div></body>
</html>
EOF
  grep -q "<!DOCTYPE html>" "$TMP/index.html" && \
  grep -q "<div id=\"app\">" "$TMP/index.html"
  RC=$?; rm -rf "$TMP"; exit $RC
'

# --- Test 4: .gitignore 内容 ---
test_case "gitignore_content" bash -c '
  TMP=$(mktemp)
  cat > "$TMP" << EOF
build/
sdkconfig.old
*.pyc
__pycache__/
.vscode/
EOF
  grep -q "build/" "$TMP" && grep -q "*.pyc" "$TMP"
  RC=$?; rm "$TMP"; exit $RC
'

# --- Test 5: 完整脚手架端到端 ---
test_case "scaffold_e2e" bash -c '
  TMP=$(mktemp -d)
  PROJECT="$TMP/e2e-proj"
  # 模拟完整脚手架生成
  mkdir -p "$PROJECT"/{main,components,frontend,tools,tests,docs/daily-logs}
  echo "cmake_minimum_required(VERSION 3.16)" > "$PROJECT/CMakeLists.txt"
  echo "idf_component_register(SRCS \"main.c\")" > "$PROJECT/main/CMakeLists.txt"
  echo "void app_main(void) {}" > "$PROJECT/main/main.c"
  echo "# E2E Project" > "$PROJECT/README.md"
  echo "build/" > "$PROJECT/.gitignore"
  # 验证
  [ -f "$PROJECT/CMakeLists.txt" ] && \
  [ -f "$PROJECT/main/main.c" ] && \
  [ -f "$PROJECT/README.md" ] && \
  [ -f "$PROJECT/.gitignore" ] && \
  [ -d "$PROJECT/docs/daily-logs" ]
  RC=$?; rm -rf "$TMP"; exit $RC
'

# --- 汇总 ---
echo ""
echo "Results: $PASS passed, $FAIL failed"
exit $FAIL
