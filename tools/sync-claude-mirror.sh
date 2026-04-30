#!/usr/bin/env bash
# tools/sync-claude-mirror.sh — keep .claude/{agents,skills} in sync with .github/.
#
# Both GitHub Copilot CLI and Anthropic Claude Code CLI expect the same
# Agent-Skills file layout, just under different roots:
#
#   Copilot CLI : .github/{agents,skills}/...
#   Claude Code : .claude/{agents,skills}/...
#
# We keep .github/ as the single canonical source and mirror it into .claude/
# via relative symlinks. This script is idempotent: re-run it any time you
# add a new skill or rename the agent file.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT="$(pwd)"

mkdir -p .claude/skills .claude/agents

# Skills: every directory under .github/skills/ becomes a sibling symlink
# under .claude/skills/.
for src in .github/skills/*/; do
    name="$(basename "$src")"
    link=".claude/skills/$name"
    target="../../.github/skills/$name"
    if [ ! -L "$link" ]; then
        ln -s "$target" "$link"
        echo "linked $link -> $target"
    fi
done

# Agent: rename .agent.md → .md so Claude Code's filename-derived agent name
# stays clean (dev-workflow, not dev-workflow.agent).
for src in .github/agents/*.agent.md; do
    [ -e "$src" ] || continue
    base="$(basename "$src" .agent.md)"
    link=".claude/agents/${base}.md"
    target="../../.github/agents/${base}.agent.md"
    if [ ! -L "$link" ]; then
        ln -s "$target" "$link"
        echo "linked $link -> $target"
    fi
done

# Prune dangling symlinks (e.g. after a skill rename).
for link in .claude/skills/* .claude/agents/*; do
    [ -L "$link" ] || continue
    if [ ! -e "$link" ]; then
        echo "pruning dangling symlink: $link"
        rm -f "$link"
    fi
done

echo "[sync-claude-mirror] OK"
