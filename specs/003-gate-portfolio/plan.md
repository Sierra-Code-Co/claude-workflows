# Implementation Plan: The Gate Portfolio

**Branch**: `003-gate-portfolio` | **Date**: 2026-08-13 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/003-gate-portfolio/spec.md`

## Summary

Turn the ad-hoc collection of quality checks into a declared portfolio with four
properties it currently lacks: each question routed to a gate that can actually answer
it, each gate proven capable of failing, deterministic enumeration for completeness
questions, and claim verification before a probabilistic finding is shown.

Phase 0 already de-risked the largest unknown by measurement: the hardest real
completeness policy in the fleet compiles to a 24-line `ast-grep` rule that enumerates
30 sites pre-sweep and 0 post-sweep, correctly handles every formatting and comment
shape that defeated four hand-rolled scanners, and goes red on a seeded violation.

## Technical Context

**Language/Version**: Python 3.12 (harness, `scripts/review_plan_v2/`); YAML (rule
definitions, CI); Markdown (skills, constitution, manifest docs).
**Primary Dependencies**: `ast-grep` 0.45.1 (NEW — single Rust binary, `brew install
ast-grep`); existing `gitleaks`, `markdownlint-cli`, `actionlint`, `shellcheck`; existing
provider clients (DeepSeek broad pass, OpenAI + Google cascade).
**Storage**: N/A — rules and manifests are files in the repo; telemetry is the existing
`~/.claude/review-plan-v2/logs/calls.jsonl` (sizes and counts only, never content).
**Testing**: `pytest` under `tests/`, with the session-autouse telemetry-isolation
fixture in `tests/conftest.py` (Principle IV).
**Target Platform**: macOS + Linux developer machines; the twelve repos that consume
`propagate-skill.sh`.
**Project Type**: CLI tooling / developer infrastructure.
**Performance Goals**: structural rules complete in the existing analyzer wave with no
measurable wall-clock increase (Phase 0: full-repo scan of 357 files was sub-second).
**Constraints**: deterministic gates MUST remain zero LLM cost; a deterministic failure
MUST short-circuit before any provider call.
**Scale/Scope**: 8 user stories; 1 trunk repo propagating to 12.

**Rejected as unnecessary**: Semgrep (deferred, see research R1 — revisit on the first
policy needing taint tracking); a dataflow engine; moving gates into GitHub Actions
(deferred pending the Claude Code GitHub Action secret-exposure finding).

## Constitution Check

*Checked against `.specify/memory/constitution.md` v1.1.0 (ratified 2026-08-13 as US1 of
this feature — see Complexity Tracking entry 1; amended 2026-08-14 to add Principle II's
shape-derivation clause, which this plan satisfies via FR-008a and tasks T034a/T034b).*

| Principle | Status | Notes |
|---|---|---|
| I. Fail-Visible Degradation ⚑ | **PASS** | FR-018 requires run health on every gate. US8 sweeps the remaining skills for the same class. The manifest drift check gets FR-016: a run producing no notification is a failed run. |
| II. Provable Failure ⚑ | **PASS** | FR-007/FR-008. The ast-grep rule already carries its proof (research R1). The plan template gains a required Failure Proof field. |
| III. Deterministic Answers ⚑(not elevated) | **PASS** | US3 is this principle. FR-004/005/006. Phase 0 demonstrated the engine handles the exact comment case the regex could not. |
| IV. Uncensored Measurement ⚑ | **PASS** | Gold set is fixed and pre-classified, so prompt changes cannot move the target (SC-002). Void baselines explicitly excluded in the spec. Telemetry isolation already fixed in `tests/conftest.py`. FR-021 bars content. |
| V. Verify Before Asserting | **PASS** | US2 is this principle, attached at the aggregator (research R3). |
| VI. Pristine Upstream | **PASS** | US7. FR-015/017. |
| VII. Fix Upstream, Propagate Down ⚑ | **PASS** | Everything lands here first. Note the tension flagged below. |

**One tension, declared rather than hidden**: the motivating defects live in the proving
ground (`mtg-cube-ai`), and Principle VII says fix upstream first. The comment-stripper
defect (research R2) is a *proving-ground* bug in a *proving-ground* guard — it is not
shared tooling, so it is filed and fixed there. What comes upstream is the general rule
that produced the finding. That split is the correct reading of VII, not an exception to
it.

**Post-design re-check**: no new violation introduced. The one added runtime dependency
(`ast-grep`) is justified in research R1 against the two alternatives.

## Project Structure

### Documentation

```text
specs/003-gate-portfolio/
├── spec.md              # done
├── research.md          # done — Phase 0, all findings measured
├── plan.md              # this file
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/           # Phase 1 — gate registry schema, finding envelope
├── rules/
│   ├── raw-caught-to-logger.yml   # done — validated, 30→0, RED-proven
│   └── fixture.ts                 # done — 13 shapes incl. 3 comment decoys
└── tasks.md             # /speckit.tasks
```

### Source

```text
scripts/review_plan_v2/
├── gates/               # NEW — the declared portfolio
│   ├── registry.py      #   tier, blocking policy, order, failure-proof ref
│   └── structural.py    #   ast-grep analyzer, joins the existing analyzer wave
├── verification/        # NEW — US2
│   ├── classify.py      #   is this claim machine-checkable?
│   └── verify.py        #   check it; label unverifiable
├── analyzers/           # existing — gitleaks, markdownlint, actionlint, shellcheck
├── aggregator.py        # MODIFIED — verification stage after dedup, before tiering
├── orchestrator.py      # MODIFIED — portfolio-driven ordering, health line
└── context/             # NEW — US5 (#18/#19/#20)

rules/                   # NEW — shared base rule set, propagated to the fleet
.specify/integrations/   # MODIFIED — US7 manifest over the full vendored surface
tests/                   # per-gate failure proofs live beside their gate
```

## Phasing

Sequenced so each phase ships something independently useful and the riskiest
assumptions were already retired in Phase 0.

| Phase | Stories | Why here |
|---|---|---|
| **0 — done** | US1 | Constitution ratified; every later plan has something to check against. Rule engine chosen by measurement, not assertion. |
| **1** | US3 | Highest confidence (already demonstrated end-to-end), zero LLM cost, immediate value to the fleet. Establishes the gate registry that later phases plug into. |
| **2** | US2 | The highest-leverage quality change. Depends on the registry from Phase 1 for its tier and failure proof. |
| **3** | US4, US6 | Formalise the portfolio contract: failure proofs required, tiers declared. Cheap once the registry exists. |
| **4** | US5 | The three filed-and-unbuilt context issues. Deliberately after US2, because verification enforces the floor whether or not context prevents the finding. |
| **5** | US7, US8 | Manifest coverage and the skill sweep. Independent of the review pipeline. |

## Complexity Tracking

| # | Deviation | Why needed | Simpler alternative rejected because |
|---|---|---|---|
| 1 | Constitution ratified inside a feature branch rather than via a standalone `/speckit.constitution` run | `/speckit.plan`'s Constitution Check is mandatory and was validating against placeholders — the feature could not proceed without it | Running `/speckit.constitution` separately would produce the same file with an extra round trip; the principles are all drawn from evidence gathered in this feature's own investigation |
| 2 | New runtime dependency (`ast-grep`) | Principle III prohibits regex over call syntax, and the hand-rolled compiler-API alternative costs 421 lines per policy and was wrong four times | Rejected keeping hand-rolled guards as default (cost, non-portability); rejected Semgrep for now (Python toolchain across 12 repos, and ast-grep cleared the hardest policy without dataflow) |
| 3 | Gold set is a frozen 10-finding corpus rather than live runs | Principle IV — a target measured on fresh runs moves whenever prompts change | Live measurement was how the void 15:1 scoreboard happened |

## Progress

- [x] Phase 0: Research complete (`research.md`) — engine chosen and validated by measurement
- [x] US1: Constitution ratified v1.0.0, zero placeholders
- [x] Constitution Check: PASS (initial and post-design)
- [ ] Phase 1: `data-model.md`, `contracts/`, `quickstart.md`
- [ ] `/speckit.tasks`
