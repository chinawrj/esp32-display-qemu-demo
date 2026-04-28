#!/bin/bash
# self-test for esp32-build-flash
# 运行: bash skills/esp32-build-flash/self-test.sh

PASS=0
FAIL=0
SKIP=0

test_pass() { echo "SELF_TEST_PASS: $1"; PASS=$((PASS + 1)); }
test_fail() { echo "SELF_TEST_FAIL: $1"; FAIL=$((FAIL + 1)); }
skip_case() { echo "SELF_TEST_SKIP: $1 ($2)"; SKIP=$((SKIP + 1)); }

# --- Test 1: ESP-IDF 环境变量 ---
if [ -n "$IDF_PATH" ]; then
  test_pass "idf_path"
else
  skip_case "idf_path" "需要 source esp-idf/export.sh"
fi

# --- Test 2: idf.py 可执行 ---
if command -v idf.py &>/dev/null; then
  test_pass "idf_cli"
else
  skip_case "idf_cli" "ESP-IDF 未安装或未加载"
fi

# --- Test 3: 编译器可用 ---
if command -v xtensa-esp32-elf-gcc &>/dev/null; then
  test_pass "xtensa_gcc"
elif command -v riscv32-esp-elf-gcc &>/dev/null; then
  test_pass "riscv_gcc"
else
  skip_case "cross_compiler" "需要 ESP-IDF 工具链"
fi

# --- Test 4: cmake 可用 ---
if command -v cmake &>/dev/null; then
  test_pass "cmake"
else
  test_fail "cmake"
fi

# --- Test 5: ninja 可用 ---
if command -v ninja &>/dev/null; then
  test_pass "ninja"
else
  skip_case "ninja" "brew install ninja"
fi

# --- 汇总 ---
echo ""
echo "Results: $PASS passed, $FAIL failed, $SKIP skipped"
exit $FAIL
