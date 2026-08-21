# 0001 — Three CLAUDE.md additions

**Status:** active
**Date:** 2026-04-26
**Tags:** global-config, prompts, friction-mitigation

## Context

`/insights` report (Apr 2026) flagged three recurring failure patterns that were costing real time:

- 6 sessions died entirely from `output_token_limit_exceeded` errors
- Multiple "premature success claims" frictions where Claude declared work done before catching regressions
- One incident where Claude `--delete-branch`'d the long-lived staging branch despite existing per-project guidance (the rule existed but wasn't global)

None of the existing global `~/.claude/CLAUDE.md` sections addressed these directly.

## Decision

Append three sections to global `~/.claude/CLAUDE.md`:

1. **Branch & Deployment Safety** — never `--delete-branch`, verify protections, never destructively rewrite without confirmation
2. **Output Token Management** — prefer `head`/`tail`/`grep` over full file reads, ask subagents for short reports, summarize-then-expand
3. **Verification Before Claiming Success** — don't claim shipped until CI green + deploy succeeded + symptom resolved; trust user's direct observation over inferred state; verify cleanup after refactors

Skip a 4th proposed section ("Spec-Kit Workflow Defaults") since the existing "Multi-phase workflows" section already covers it.

## Why

- Global > per-project. Branch-safety incident in companion-ai showed that per-project rules don't transfer; global ones do.
- Phrased as **rules with reasons**, not just rules — e.g., "trust user observation over inferred state" includes the why so Claude can judge edge cases.
- Output-token rules are the only fix for sessions that die mid-flight; once over the limit, no recovery is possible.

Alternatives considered:

- **Hooks for branch safety** — would only catch git-CLI calls, not all the ways branches get deleted (gh, MCP, etc.). Rule is more general.
- **A "review before push" script** — possible but heavyweight; covered separately by Phase 6 self-review (ADR-0002).

## Consequences

- Every Claude Code session loads these rules. Slight context overhead, accepted.
- The "trust user observation" rule may produce friction if users are wrong, but the cost of arguing with a correct user observation is much higher.

## Verification

Watch the next `/insights` run for:

- `output_token_limit_exceeded` count → goal: 0
- "premature success claims" friction tag → goal: down from current
- Branch-deletion incidents → goal: 0
