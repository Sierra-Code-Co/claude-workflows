# Architecture Decision Records (ADRs)

Short, append-only records of decisions made about how I use Claude Code. Each ADR captures **what** was decided and **why** — so future-me (or a different machine) doesn't second-guess past calls.

## Format

Each file is named `NNNN-<short-title>.md` and follows this template:

```markdown
# NNNN — <Title>

**Status:** active | superseded by NNNN | killed
**Date:** YYYY-MM-DD
**Tags:** <comma-separated>

## Context

What's the situation that needs a decision?

## Decision

What's the call?

## Why

What's the reasoning? What were the alternatives?

## Consequences

What does this enable, prevent, or commit us to?

## Verification

How will I know this is working (or not)?
```

## Index

| #    | Title                                                           | Status |
| ---- | --------------------------------------------------------------- | ------ |
| 0001 | [Three CLAUDE.md additions](0001-claude-md-additions.md)        | active |
| 0002 | [Phase 6 CodeRabbit-style self-review](0002-phase-6-self-review.md) | active |
| 0003 | [GitHub MCP via org-scoped user-scope install](0003-github-mcp-org-scoped.md) | active |
| 0004 | [Sentry MCP per-project, org-scoped](0004-sentry-mcp-strategy.md) | active |
| 0005 | [Memory system conventions](0005-memory-system-conventions.md)  | active |
| 0006 | [claude-workflows repo structure](0006-workflows-repo-structure.md) | active |
| 0007 | [User-scope permissions baseline](0007-user-scope-permissions-baseline.md) | active |
| 0008 | [/review-plan v2: Python orchestrator + drop-in CR replacement](0008-review-plan-v2.md) | active |
| 0009 | [Per-repo `.coderabbit.yaml` propagation; two-failure-mode diagnostic model](0009-cr-yaml-propagation-architecture.md) | active |
| 0010 | [Public mirror via allowlist sync; internal repo stays private](0010-public-mirror.md) | active |

## How to use ADRs

- **Adding one:** new decision = new file, increment number, append to index above.
- **Reversing one:** don't delete the old file. Mark `Status: superseded by NNNN` and write a new ADR. The trail of reasoning matters.
- **When in doubt:** if you find yourself re-deciding the same thing, it's an ADR-worthy decision.
