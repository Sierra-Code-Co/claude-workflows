# 0004 — Sentry MCP per-project, org-scoped

**Status:** active
**Date:** 2026-04-26
**Tags:** mcp, sentry, observability

## Context

`/insights` report flagged 8 sessions on bug-triage and Sentry integration. Existing setup had a single global Sentry MCP entry pinned to one project (`sierra-code-co/family-app-api`). Two highest-commit-volume projects (`companion-ai` 479 commits/mo, `mtg-cube-ai` 413 commits/mo) had no Sentry MCP configured at all.

Sentry's hosted MCP supports both project-scoped (`/mcp/<org>/<project>`) and org-scoped (`/mcp/<org>`) URLs.

## Decision

Add Sentry MCP per-project (in each project's `.mcp.json`), using **org-scoped URLs** so a single entry covers all projects under that org.

For mtg-cube-ai (`sierra-code-co` org, two Sentry projects: `javascript-sveltekit` and `python-fastapi`):

```json
{
  "mcpServers": {
    "sentry": {
      "type": "http",
      "url": "https://mcp.sentry.dev/mcp/sierra-code-co"
    }
  }
}
```

## Why

- **Per-project over global**: keeps each repo self-documenting about its dependencies (you see `.mcp.json` and know what's wired up).
- **Org-scoped over project-scoped**: covers multi-project apps (web + api) with one entry. Cross-project queries possible.
- **Org slug discovered from Sentry URL** (e.g., `sierra-code-co.sentry.io/issues/?project=...`), NOT from the CI workflow's `SENTRY_ORG: jabelk` variable which turned out to be misleading/stale.

Alternatives considered:

- **Single global org-scoped entry** in `~/.claude/settings.json` covering all sierra-code-co projects: cleaner if all projects are in one org, but loses per-repo discoverability. Worth revisiting if active projects consolidate.
- **Project-scoped URLs**: more locked-down but doesn't help when investigating cross-project issues.

## Consequences

- Each project's `.mcp.json` needs the entry. Bulk apply via a future `propagate-mcp.sh` script if this pattern grows.
- First use in each project triggers OAuth dance. One-time per machine per project.
- Org slug must match the actual Sentry org slug — verify from the Sentry web URL, not from CI env vars.

## Status of rollout (as of 2026-04-26)

| Project       | Sentry MCP       | Notes                                              |
| ------------- | ---------------- | -------------------------------------------------- |
| family-app-api | ✓ (global, project-scoped) | Existing entry, predates this ADR        |
| mtg-cube-ai   | ✓ (per-project, org-scoped) | Covers `javascript-sveltekit` + `python-fastapi` |
| companion-ai  | parked            | No matching Sentry project found in available orgs — confirm setup |

## Verification

- `claude mcp list` in each project shows `sentry: ✓ Connected`
- Can query "show me top errors in javascript-sveltekit this week" without manual dashboard navigation
