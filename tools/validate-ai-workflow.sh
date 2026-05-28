#!/usr/bin/env bash
# Validate the repository AI workflow layer.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PASS=0
FAIL=0
SKIP=0

run_required() {
    local name="$1"
    shift
    echo "[ai-workflow] === ${name} ==="
    if "$@"; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
    fi
}

run_skill_self_test() {
    local script="$1"
    local name
    name="$(basename "$(dirname "$script")")"
    echo "[ai-workflow] === skill:${name} ==="

    # tmux cannot create sessions in some sandboxes. Treat that as an
    # environment skip here; the skill's own self-test remains strict when
    # run directly on a normal development host.
    if [ "$name" = "tmux-multi-shell" ]; then
        if ! tmux new-session -d -s __ai_workflow_tmux_probe__ >/dev/null 2>&1; then
            echo "[ai-workflow] SKIP skill:${name}: tmux session creation unavailable"
            SKIP=$((SKIP + 1))
            return 0
        fi
        tmux kill-session -t __ai_workflow_tmux_probe__ >/dev/null 2>&1 || true
    fi

    if bash "$script"; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
    fi
}

PYTEST=".venv/bin/pytest"
if [ ! -x "$PYTEST" ]; then
    PYTEST="python3 -m pytest"
fi

run_required "dual-cli parity" $PYTEST tests/test_dual_cli_parity.py -q

for script in .github/skills/*/self-test.sh; do
    [ -f "$script" ] || continue
    run_skill_self_test "$script"
done

echo ""
echo "[ai-workflow] Results: ${PASS} passed, ${FAIL} failed, ${SKIP} skipped"
[ "$FAIL" -eq 0 ]
