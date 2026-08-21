# 0002 — Phase 6 CodeRabbit-style self-review checklist

**Status:** active
**Date:** 2026-04-26
**Tags:** skills, feature-pipeline, code-review, friction-mitigation

## Context

`/insights` report flagged 4-6 round CodeRabbit cycles as a major time sink. Each round costs 10-20 min of human attention to review CR comments, dispatch fixes, push, wait. Common findings across PRs (#864, #880, #903, #729, #730, #731):

- try/except scope missing early-return paths
- Signed URLs and tokens leaked in debug logs
- Vacuous test assertions (asserting on empty bodies, request shape only)
- Missing edge cases (empty collections, timezone boundaries, idempotency)
- Duplicated magic constants
- Shell pipeline safety (no `set -euo pipefail`)

The existing `/feature` skill's Phase 6 had a single one-liner: "Self-review the diff for: shell pipeline safety, API keys in URLs, secrets/PII, doc consistency." Too vague to actually catch the patterns above.

## Decision

Replace the Phase 6 single-liner with a structured CR-style checklist covering the seven recurring CR-finding categories. Source of truth: `claude-speckit-template/.claude/skills/feature/SKILL.md`. Propagated to all 21 active projects via manual edits (eventually `propagate-skill.sh`).

Two exceptions:

- **companion-ai** (both `.claude/skills/feature/SKILL.md` and `.agents/skills/feature/SKILL.md`): references the existing 13-item Pre-Push Self-Review Checklist in CLAUDE.md/AGENTS.md instead of duplicating. That checklist is more thorough (PR #729, #730, #731 lessons) and project-specific.

## Why

- Specific patterns > general advice. "Check for vacuous tests" is something Claude can act on; "self-review" is not.
- Inserting at Phase 6 (post-implementation, pre-PR) catches issues at the cheapest correction point.
- Reference (not duplicate) the more thorough companion-ai checklist — single source of truth principle.

Alternatives considered:

- **Pre-commit hook** — would slow every commit and CC users with high commit volume (companion-ai 479/mo, mtg-cube-ai 413/mo). Cost outweighs benefit.
- **Separate `/cr-review` skill** — adds friction (must remember to invoke). Inline in `/feature` is automatic.

## Consequences

- Every `/feature` run hits the checklist before opening a PR.
- Skill files now diverge by ~50 lines vs the old version. Worth it.
- Future skill updates need `propagate-skill.sh` to fan out cleanly.

## Verification

- Watch CR round count per PR over next month → goal: down from 4-6 to 1-2
- Watch for the specific finding categories in CR comments → if patterns persist, the checklist needs sharper wording
