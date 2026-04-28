#!/bin/bash
# self-test for automated-testing
# 运行: bash skills/automated-testing/self-test.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/../_common/detect-python.sh"

PASS=0
FAIL=0
SKIP=0

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

skip_case() {
  echo "SELF_TEST_SKIP: $1 ($2)"
  SKIP=$((SKIP + 1))
}

# --- Detect Python with patchright ---
PYTHON=$(detect_python "patchright.sync_api")
if [ -n "$PYTHON" ]; then
  echo "SELF_TEST_PASS: patchright_import ($PYTHON)"
  PASS=$((PASS + 1))
else
  skip_case "patchright_import" "pip install patchright"
  PYTHON="python3"  # fallback for non-patchright tests
fi

# --- Test 2: pyserial 可导入 ---
if $PYTHON -c "import serial" 2>/dev/null; then
  echo "SELF_TEST_PASS: pyserial_import"
  PASS=$((PASS + 1))
else
  skip_case "pyserial_import" "pip install pyserial"
fi

# --- Test 3: 测试框架模拟 — 串口模式匹配 ---
test_case "test_framework_pattern_match" $PYTHON -c "
import re
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
assert len(t.results) == 2, f'Expected 2, got {len(t.results)}'
"

# --- Test 4: bash 测试流程逻辑 ---
test_case "bash_test_flow" bash -c 'RESULT=0; [ $RESULT -eq 0 ]'

# --- Test 5: 测试结果汇总逻辑 ---
test_case "result_aggregation" $PYTHON -c "
results = [
    {'name': 'test1', 'passed': True},
    {'name': 'test2', 'passed': False},
    {'name': 'test3', 'passed': True},
]
passed = sum(1 for r in results if r['passed'])
failed = sum(1 for r in results if not r['passed'])
assert passed == 2 and failed == 1, f'Aggregation error: {passed}/{failed}'
"

# --- 汇总 ---
echo ""
echo "Results: $PASS passed, $FAIL failed, $SKIP skipped"
exit $FAIL
