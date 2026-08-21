# 0009 — Per-repo `.coderabbit.yaml` propagation; two-failure-mode diagnostic model

**Status:** active
**Date:** 2026-05-01
**Tags:** coderabbit, propagation, fleet, architecture, review-plan-v2

## Context

`sierra-code-co` PR #41 (merged 2026-05-01 as `19c0a91`) ran 4 CodeRabbit (CR) review rounds where target is 1–2. Investigation found the round count was driven by:

- Two recurring **doc/spec false positives** (`author:` byline flagged as PII, intentional file-path references in `spec.md` flagged as over-specification)
- Three legitimate **cross-file content drift** findings (FAQ hand-coded vs JSON-LD source-of-truth, stale price ranges across spec/research/quickstart, project-structure tree marking EDITED files as UNCHANGED)

The original lesson note framed this as "review-plan-v2 too loose." That framing was wrong. The **real** root cause was that `sierra-code-co` had no `.coderabbit.yaml` at all (CR ran with default ASSERTIVE strictness) and no `review-plan-v2/SKILL.md` (no in-repo Claude session awareness of the local pre-push tool). Audit extended that finding fleet-wide: 14/19 active projects lack `.coderabbit.yaml`, 3/19 lack `review-plan-v2/SKILL.md`. The existing propagation infra (`scripts/propagate-coderabbit-yaml.sh`, added 2026-04-27) was built but the rollout was never finished — its `NON_PROJECTS` skip list also incorrectly treated `sierra-code-co` and `family-meeting` as inactive.

Two architecture questions had to be answered before designing the fix:

1. **Does CodeRabbit support a centralized config that would obviate per-repo `.coderabbit.yaml` files?**
2. **Is `.review-plan-v2.yaml` a needed companion to fix the spec hygiene rules locally?**

## Decision

**Per-repo `.coderabbit.yaml` propagation is the only viable architecture for CR config; `.review-plan-v2.yaml` is NOT introduced.**

Concretely:

- **CR config** stays per-repo. The augmented `scripts/templates/coderabbit-baseline.yaml` is the source of truth for projects that don't need bespoke tuning; the propagation script (`propagate-coderabbit-yaml.sh`) drops it into each candidate repo, with each repo's actual default branch detected and injected at apply time.
- **No `.review-plan-v2.yaml`** is created — review-plan-v2 is a code-diff reviewer, not a doc-hygiene config tool. The spec-rules whitelisting belongs in `.coderabbit.yaml`'s `path_instructions`, not in a new schema.
- **SKILL.md propagation flows through `claude-speckit-template`**, not direct copy from `claude-workflows`. The `propagate-skill.sh` script gains an `--install-missing` flag so the same script that updates existing skills can also fill gaps.

**Two-failure-mode diagnostic model** (recorded here so future regressions are diagnosed correctly):

| Mode | Name | Trigger | Lever |
|------|------|---------|-------|
| **Mode 1** | Doc/spec false positives | CR flags intentional patterns (bylines, file-path refs, prose style) as issues | Tune `.coderabbit.yaml` `path_instructions` (this ADR's mechanism) |
| **Mode 2** | Cross-file real bugs | CR catches drift across files (FAQ ↔ JSON-LD, stale numbers across spec/plan/research) that local diff-only reviewers cannot see | Accept as design — CR is the safety net; no local-tool fix |

**When a future PR runs ≥3 rounds, the diagnostic question is "which mode is this?" — not "is review-plan-v2 too loose?"**

## Why

**Why per-repo `.coderabbit.yaml` (not centralized):**

CR offers two centralization mechanisms:

- **Global Overrides** — org-admin only. Confirmed via CR docs (`coderabbit.ai/blog/introducing-global-overrides`): "Only organization admins can view or edit Global Overrides." This account is solo (no GitHub organization with CR Pro/Teams plan), so Global Overrides are unavailable.
- **Shared Configuration** — host the yaml at a public URL. CR docs explicitly mark this as "not recommended" because it exposes config publicly; only intended for self-hosted air-gapped deployments.

Per-repo propagation is the only working path. The existing `propagate-coderabbit-yaml.sh` is the right architecture; this rollout completes the unfinished work.

**Why no `.review-plan-v2.yaml`:**

review-plan-v2 is a **code-diff reviewer** (security, correctness, tests, consistency). It has no concept of "doc/spec hygiene rules." The two false-positive classes that triggered this work (`author:` bylines, `specs/**` file-path refs) are not patterns review-plan-v2 should be detecting — they are reviewer-instruction-level conventions that belong in CR's `path_instructions`. Inventing a new yaml schema for "spec hygiene" inside review-plan-v2 would conflate two distinct review concerns and create a maintenance surface that no other project in the fleet uses (none of the 19 active projects has `.review-plan-v2.yaml`).

The cross-file content drift catches (Mode 2 above) are a known and documented limitation in `review-plan-v2/SKILL.md` ("cross-file mitigations won't be visible") — fixing that limitation would require fundamental architecture changes (multi-file context per reviewer call), which is out of scope. CR remains the safety net for cross-file drift by design.

**Why SKILL.md flows through `claude-speckit-template`:**

`CLAUDE.md` is explicit: *"`claude-speckit-template` remains the source of truth for skill propagation. Don't propagate skills *out* of this repo."* Direct copy from `claude-workflows` violates this principle and creates governance debt — future template-based propagations would not know about manually-placed copies, leading to drift or unintended overwrites.

The fix is simple: enhance `propagate-skill.sh` with `--install-missing` (currently it only updates existing installs), and run from the template. The existing precedent of "direct copy" from the 2026-04-28 fleet rollout is documented in `STATE.md` but should not be repeated.

## Consequences

**Enables:**

- Reproducible fleet-wide CR config rollout: any future active project added under `~/dev/projects/` picks up the baseline on next propagation run.
- Pilot-first sequencing on rollout: catch baseline defects in one repo before fanning out to 14.
- Per-repo default-branch injection: works for `main`, `staging`, `master` without per-project manual fixes.
- Generalizable `propagate-skill.sh --install-missing`: useful for any future skill that needs to land fleet-wide.
- Future round-count regressions diagnosed correctly via the two-failure-mode model — no re-litigation of "is review-plan-v2 too loose?"

**Prevents / commits us to:**

- Continued per-repo PR work for fleet-level config changes (~14 PRs per major baseline change). The cost is acceptable for a 19-project fleet at this scale.
- 5 tailored-yaml projects (`companion-ai`, `mtg-cube-ai`, `family-app`, `church-bible-study`, `claude-workflows`) remain manually maintained — `STATE.md` carries an advisory table with recommended whitelist additions per project, deferred to manual review.
- If CR Global Overrides become available for solo accounts in the future (e.g., via a free-tier change), this ADR should be revisited — centralized config would meaningfully simplify maintenance.

## Verification

- **Immediate:** sierra-code-co smoke test (per quickstart.md § Smoke test) — open a doc-only PR with `author:` byline + file-path reference; observe CR round count ≤2.
- **Short-term (14 days):** all 19 active projects have `.coderabbit.yaml` (5 tailored + 14 baseline). Run the SC-002 for-loop from quickstart.md.
- **Medium-term:** SC-005 — across the next 5 doc-heavy PRs in rolled-out projects, median CR round count is ≤2 and max is ≤3.
- **Diagnostic test:** read this ADR cold (after a memory wipe). Within 5 minutes, can determine whether a hypothetical regression is Mode 1 or Mode 2 and which lever to pull.

## Related

- Issue: `claude-workflows#23` — fleet-wide CR config + review-plan-v2 SKILL.md gap rollout.
- Spec: `specs/002-fleet-cr-rollout/spec.md`.
- Trigger PR: `sierra-code-co#41` (4-round CR cycle, merged 2026-05-01 as `19c0a91`).
- Earlier rollout context: `STATE.md` § "Rollout tooling for `.coderabbit.yaml`" (added 2026-04-27).
- Related ADR: `0008-review-plan-v2.md` (review-plan-v2 architecture; this ADR is downstream).
