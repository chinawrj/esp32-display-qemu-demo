# Copilot CLI Issue Draft

> Ready-to-paste draft for https://github.com/github/copilot-cli/issues/new
> Repo: github/copilot-cli — version observed: 1.0.39 (Linux x64, npm)

---

## Title

Misleading auth error hides custom agent / skill / MCP discovery failures in `-p` mode

## Body

### TL;DR

When the CLI is launched without valid credentials, `-p` mode (and `--agent <name>`) exits with `Error: No authentication information found.` **before** scanning local `.github/agents/`, `.github/skills/`, or MCP config. The user has no way to tell whether their agent/skill file is wrong or whether the CLI just never looked at it. A small reorder of startup steps — or a tiny offline `list` subcommand — would have saved hours of false-trail debugging.

I really like Copilot CLI; this is a paper-cut report, not a complaint. 🙂

### Version

```
GitHub Copilot CLI 1.0.39
Linux x64, installed via `npm install -g @github/copilot`
```

### What I expected

When I have a valid `.github/agents/dev-workflow.agent.md` and run:

```bash
copilot --agent dev-workflow -p "hi"
```

…I expect *either* the agent to be found (and then the auth error to surface as the next step), *or* a clear "you're not logged in" hint that doesn't make me doubt my agent file.

### What actually happens

Both of these print the **identical** error, with no way to distinguish them:

```bash
$ copilot --agent dev-workflow         -p "hi"
$ copilot --agent does-not-exist-xyz   -p "hi"
```
```
Error: No authentication information found.

Copilot can be authenticated with GitHub using an OAuth Token or a
Fine-Grained Personal Access Token.

To authenticate, you can use any of the following methods:
  • Start 'copilot' and run the '/login' command
  • Set the COPILOT_GITHUB_TOKEN, GH_TOKEN, or GITHUB_TOKEN environment variable
  • Run 'gh auth login' to authenticate with the GitHub CLI
```

The same gate hides skills and MCP servers too — they are simply never enumerated, so any "my skill isn't being picked up" investigation runs into the same dead end.

### Minimal reproduction

```bash
# Make sure no token is available
gh auth logout 2>/dev/null
unset GH_TOKEN GITHUB_TOKEN COPILOT_GITHUB_TOKEN

# A perfectly valid agent
mkdir -p .github/agents
cat > .github/agents/demo.agent.md <<'EOF'
---
description: Demo agent
---
You are a demo agent.
EOF

# A perfectly valid skill
mkdir -p .github/skills/demo-skill
cat > .github/skills/demo-skill/SKILL.md <<'EOF'
---
description: A demo skill
---
You are a demo skill.
EOF

copilot --agent demo            -p "hi"   # auth error
copilot --agent does-not-exist  -p "hi"   # same auth error — indistinguishable
copilot                          -p "/demo-skill"  # same auth error
```

After `gh auth login`, all three work and both `demo` and `demo-skill` show up. So the files were always correct — only the ordering of startup checks made them invisible.

### Why I think this is a bug, not a design choice

- `--help`, `--version`, and `--print-debug-info` all run fine without credentials. Listing local agent / skill / MCP definitions is the same kind of operation: pure local file I/O, no Copilot API needed.
- In the bundled `app.js`, agent discovery (`vTn` / `bTn`) and skill discovery (the `SKILL.md` walker) are both `readdir` + frontmatter parse — neither touches the network. The auth check just happens to fire earlier on the `-p` path.
- The error message points the user at the *wrong layer*. The first thing I checked was YAML frontmatter, then file path, then encoding, then the `.github/agents/` discovery rules. None of that mattered; the only fix was a stale `gh` token.
- A previous release (≤ 0.0.x) shipped `--list-env` for exactly this kind of offline introspection; it was removed in 1.0.30. The need clearly exists, and the replacement path is missing.

### Suggested fix (pick whichever is easier)

1. **Reorder startup**: argv parsing → local discovery (agents / skills / MCP, with warnings collected) → auth check. Auth only needs to gate the actual model call, not the introspection that precedes it.
2. **Or expose offline subcommands** (no token required):
   ```
   copilot agents list
   copilot skills list
   copilot mcp list
   ```
   These would print discovered items with their source paths and any frontmatter warnings, and would be invaluable in CI / debugging.
3. As a smaller stopgap: when `--agent <name>` is passed and auth fails, still attempt local discovery and add one extra line to the error, e.g.
   `Note: agent "<name>" was not found in any discovered location either.`
   That single line would have unblocked me immediately.

### Workaround (for anyone hitting this via search)

```bash
gh auth login          # or: copilot, then /login
copilot --agent <name> -p "hi"
```

Thanks for the great tool — happy to provide more diagnostics if useful.
