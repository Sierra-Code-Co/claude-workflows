# 0003 — GitHub MCP via remote URL, user-scope install, org-scoped

**Status:** active
**Date:** 2026-04-26
**Tags:** mcp, github, friction-mitigation

## Context

`/insights` flagged Bash as the dominant tool (21,999 calls vs Read 7,348). Much of that was `gh` CLI for PR/issue/CI polling. Each call is a context round-trip; high-volume workflows (PR-merge monitoring, CI checks) burn tokens quickly.

The `/insights` recommendation was: install GitHub MCP. Two viable paths:

- **Local stdio**: `claude mcp add github -s user -e GITHUB_PERSONAL_ACCESS_TOKEN=<PAT> -- npx -y @modelcontextprotocol/server-github`
- **Remote HTTP**: `claude mcp add --transport http github https://api.githubcopilot.com/mcp/ -s user --header "Authorization: Bearer <PAT>"`

## Decision

Use **remote HTTP, user-scope, PAT-authenticated**.

```bash
claude mcp add --transport http github https://api.githubcopilot.com/mcp/ \
  -s user --header "Authorization: Bearer <PAT>"
```

PAT scopes: `repo`, `read:org`, `workflow`.

## Why

- **Remote over local stdio**: GitHub's official Go-based server is hosted by GitHub, always-current, has more tools. The npm `@modelcontextprotocol/server-github` was archived April 2025 in favor of this.
- **User scope over local**: I have ~20 active projects. User scope means one install covers all of them. Single source of truth, single rotation point.
- **PAT over Copilot OAuth**: I don't have a Copilot subscription. PAT works without it.

Alternatives considered:

- **Per-project install**: 20× the maintenance, no benefit.
- **Org-scoped vs user-scoped (the URL kind)**: GitHub's MCP is account-scoped, not org-scoped — N/A.

## Consequences

- PAT lives in `~/.claude.json` plaintext. Treat that file like an `.env` — never commit it. Rotate the PAT periodically.
- `gh` CLI still works for things MCP doesn't cover (e.g., complex `gh api` queries).
- New machines need to repeat the install (`new-machine.sh` reminds you).

## Verification

- `claude mcp list` shows `github: ✓ Connected`
- Next `/insights` run: Bash call count down vs prior period
- Subjectively: fewer manual `gh pr view --comments` round-trips
