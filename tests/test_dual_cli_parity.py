"""Dual-CLI parity check.

Both GitHub Copilot CLI and Anthropic Claude Code CLI consume the same
Agent-Skills artefacts in this repo, but each looks under its own root:
``.github/{agents,skills}/`` vs ``.claude/{agents,skills}/``. We keep
``.github/`` as the canonical source and mirror it into ``.claude/`` via
symlinks managed by ``tools/sync-claude-mirror.sh``.

This test enforces:

1. Every canonical skill under ``.github/skills/<name>/`` has a matching
   ``.claude/skills/<name>`` symlink that resolves to the same SKILL.md.
2. Every canonical agent under ``.github/agents/<name>.agent.md`` has a
   matching ``.claude/agents/<name>.md`` symlink that resolves to the
   same file.
3. There are no dangling or orphan symlinks in ``.claude/``.
4. Every SKILL.md (and the agent file) carries the YAML frontmatter
   keys required by both CLIs (``name`` and ``description``).
5. ``.mcp.json`` exists at the repo root for Claude Code, and every
   server entry declares ``type`` (Claude requires this; the older
   ``.vscode/mcp.json`` URL-only form is Copilot-CLI-only).

If any of these break, the dual-CLI workflow has silently regressed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GITHUB_SKILLS = PROJECT_ROOT / ".github" / "skills"
GITHUB_AGENTS = PROJECT_ROOT / ".github" / "agents"
CLAUDE_SKILLS = PROJECT_ROOT / ".claude" / "skills"
CLAUDE_AGENTS = PROJECT_ROOT / ".claude" / "agents"
MCP_JSON = PROJECT_ROOT / ".mcp.json"

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---", re.DOTALL)


def _frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    assert m, f"{path}: missing YAML frontmatter (--- ... ---)"
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip().strip('"').strip("'")
    return fm


def _skill_names() -> list[str]:
    return sorted(p.name for p in GITHUB_SKILLS.iterdir() if p.is_dir())


def _agent_names() -> list[str]:
    return sorted(
        p.name[: -len(".agent.md")]
        for p in GITHUB_AGENTS.iterdir()
        if p.is_file() and p.name.endswith(".agent.md")
    )


@pytest.mark.parametrize("skill", _skill_names())
def test_skill_mirrored_to_claude(skill: str) -> None:
    src = GITHUB_SKILLS / skill / "SKILL.md"
    mirror = CLAUDE_SKILLS / skill
    assert src.is_file(), f"canonical skill missing: {src}"
    assert mirror.is_symlink(), f".claude/skills/{skill} must be a symlink"
    assert mirror.resolve() == (GITHUB_SKILLS / skill).resolve(), (
        f".claude/skills/{skill} resolves to {mirror.resolve()}, expected {(GITHUB_SKILLS / skill).resolve()}"
    )
    assert (mirror / "SKILL.md").is_file(), f"SKILL.md not reachable through {mirror}"


@pytest.mark.parametrize("skill", _skill_names())
def test_skill_frontmatter(skill: str) -> None:
    fm = _frontmatter(GITHUB_SKILLS / skill / "SKILL.md")
    assert fm.get("name") == skill, f"skill '{skill}' frontmatter name mismatch: {fm.get('name')!r}"
    assert fm.get("description"), f"skill '{skill}' missing description"


@pytest.mark.parametrize("agent", _agent_names())
def test_agent_mirrored_to_claude(agent: str) -> None:
    src = GITHUB_AGENTS / f"{agent}.agent.md"
    mirror = CLAUDE_AGENTS / f"{agent}.md"
    assert src.is_file(), f"canonical agent missing: {src}"
    assert mirror.is_symlink(), f".claude/agents/{agent}.md must be a symlink"
    assert mirror.resolve() == src.resolve()


@pytest.mark.parametrize("agent", _agent_names())
def test_agent_frontmatter(agent: str) -> None:
    fm = _frontmatter(GITHUB_AGENTS / f"{agent}.agent.md")
    assert fm.get("name") == agent, f"agent '{agent}' frontmatter name mismatch: {fm.get('name')!r}"
    assert fm.get("description"), f"agent '{agent}' missing description"


def test_no_dangling_claude_symlinks() -> None:
    for d in (CLAUDE_SKILLS, CLAUDE_AGENTS):
        if not d.exists():
            continue
        for entry in d.iterdir():
            assert entry.is_symlink(), f"{entry} should be a symlink (not a regular file/dir)"
            assert entry.exists(), f"{entry} is a dangling symlink -> {entry.readlink()}"


def test_no_orphan_mirror_entries() -> None:
    """A .claude/ entry without a matching .github/ source is a stale mirror."""
    skills = set(_skill_names())
    for entry in CLAUDE_SKILLS.iterdir():
        assert entry.name in skills, f".claude/skills/{entry.name} has no canonical source"
    agents = set(_agent_names())
    for entry in CLAUDE_AGENTS.iterdir():
        stem = entry.name.removesuffix(".md")
        assert stem in agents, f".claude/agents/{entry.name} has no canonical source"


def test_mcp_json_format_for_claude() -> None:
    assert MCP_JSON.is_file(), "Claude Code requires .mcp.json at the repo root"
    data = json.loads(MCP_JSON.read_text(encoding="utf-8"))
    servers = data.get("mcpServers")
    assert isinstance(servers, dict) and servers, ".mcp.json must define mcpServers"
    for name, cfg in servers.items():
        # Claude Code requires explicit transport type for HTTP/SSE servers.
        # Stdio servers are identified by `command` instead.
        assert "type" in cfg or "command" in cfg, (
            f"{name}: must declare 'type' (http/sse) or 'command' (stdio); "
            "Claude Code rejects URL-only entries"
        )
        if "url" in cfg:
            assert cfg.get("type") in {"http", "sse"}, (
                f"{name}: URL servers must set type=http or type=sse"
            )
