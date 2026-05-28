#!/usr/bin/env bash
# Common helper for skill self-tests.

detect_python() {
    local module="${1:-}"
    local candidates=()

    if [ -x ".venv/bin/python" ]; then
        candidates+=(".venv/bin/python")
    fi
    candidates+=("python3" "python")

    local py
    for py in "${candidates[@]}"; do
        command -v "$py" >/dev/null 2>&1 || continue
        if [ -z "$module" ] || "$py" -c "import ${module}" >/dev/null 2>&1; then
            printf '%s\n' "$py"
            return 0
        fi
    done

    return 1
}
