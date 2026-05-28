#!/usr/bin/env bash
# tools/sync-claude-mirror.sh — keep AI compatibility entrypoints in sync.
#
# .github/ is the single source of truth for AI workflow files. Some tools
# still require compatibility entrypoints outside .github:
#
#   Copilot CLI : .github/{agents,skills}/...
#   Claude Code : .claude/{agents,skills}/...
#   Root agents : AGENTS.md
#   MCP clients  : .mcp.json and .vscode/mcp.json
#
# This script mirrors those entrypoints as relative symlinks. It is
# idempotent: re-run it any time you add a new skill, rename the agent file,
# or adjust MCP config.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT="$(pwd)"

mkdir -p .claude/skills .claude/agents

ensure_symlink() {
    local link="$1"
    local target="$2"
    if [ -L "$link" ]; then
        if [ "$(readlink "$link")" = "$target" ]; then
            return 0
        fi
        rm -f "$link"
    elif [ -e "$link" ]; then
        echo "replacing non-symlink compatibility file: $link"
        rm -f "$link"
    fi
    ln -s "$target" "$link"
    echo "linked $link -> $target"
}

# Skills: every directory under .github/skills/ becomes a sibling symlink
# under .claude/skills/.
for src in .github/skills/*/; do
    name="$(basename "$src")"
    [ "$name" = "_common" ] && continue
    link=".claude/skills/$name"
    target="../../.github/skills/$name"
    ensure_symlink "$link" "$target"
done

# Agent: rename .agent.md → .md so Claude Code's filename-derived agent name
# stays clean (dev-workflow, not dev-workflow.agent).
for src in .github/agents/*.agent.md; do
    [ -e "$src" ] || continue
    base="$(basename "$src" .agent.md)"
    link=".claude/agents/${base}.md"
    target="../../.github/agents/${base}.agent.md"
    ensure_symlink "$link" "$target"
done

ensure_symlink "AGENTS.md" ".github/AGENTS.md"
ensure_symlink ".mcp.json" ".github/mcp.json"
mkdir -p .vscode
ensure_symlink ".vscode/mcp.json" "../.github/mcp.json"

# Prune dangling symlinks (e.g. after a skill rename).
for link in .claude/skills/* .claude/agents/*; do
    [ -L "$link" ] || continue
    if [ ! -e "$link" ]; then
        echo "pruning dangling symlink: $link"
        rm -f "$link"
    fi
done

echo "[sync-claude-mirror] OK"
