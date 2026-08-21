---
name: CR CLI workflow rollout from claude-workflows
description: 2026-04-27 coordinated rollout adding pre-push CodeRabbit CLI workflow across all jabelk repos. PRs/branches named cr-cli-rollout-* are part of this; not random/local changes.
type: project
---

# CR CLI workflow rollout

**Coordinated cross-repo rollout** from `~/dev/projects/claude-workflows/` — see PR #10 there for the canonical `.coderabbit.yaml` pattern.

If you see a recent PR/branch named like:

- `cr-cli-rollout` or `cr-cli-rollout-*`
- A PR titled "Add .coderabbit.yaml" or "Add CR CLI to Phase 6"
- A new `.coderabbit.yaml` at repo root that wasn't there before

…it's intentional. **Don't revert.** Don't treat as accidental.

## The new workflow (in global ~/.claude/CLAUDE.md)

1. Run `coderabbit review --plain --base main` (or `--base staging`) before pushing — catches most CR-class issues locally
2. Open PR — PR-side CR review is now the safety net (target 1–2 rounds, not 4–5)
3. Address what the CLI surfaces; merge when CR approves

## Why

Companion-ai PRs were averaging 4–5 PR-side CR rounds, each ~5min CR + a CI cycle. Pre-push CLI runs the same engine locally, so most catches happen before the PR exists.

Empirical data from claude-workflows:

- PR #8 (no pre-push): 5 rounds
- PR #9 (with pre-push): 1 round, APPROVED first pass

## If you're working in this repo

- Coordinate before pushing changes that conflict with `.coderabbit.yaml` or the `feature` skill's Phase 6 self-review (the rollout adds a CR CLI step there)
- The yaml is per-repo; `path_instructions` should be tuned to the project's tech stack (see companion-ai/mtg-cube-ai for substantive examples)
- Don't lower the profile to `chill` — keep ASSERTIVE; the catches are real (`'UserCancelled'` PascalCase, library version drift, race conditions, contract drift)

## Source of truth

- ~/.claude/CLAUDE.md "Pre-push: run CodeRabbit CLI locally" section
- ~/dev/projects/claude-workflows/CHANGELOG.md (search for "CodeRabbit CLI")
- ~/dev/projects/claude-workflows/.coderabbit.yaml (canonical pattern)
