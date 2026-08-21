# Spec-driven development with Claude Code

Spec-driven development (SDD) inverts the usual agent workflow: instead of prompting an agent to write code and reviewing what comes out, you drive it through **specify → plan → tasks → implement**, with review gates between phases. The agent's context at implementation time is a spec it helped sharpen and a plan that survived external review — not a one-line prompt.

The mechanics here come from [GitHub's Spec Kit](https://github.com/github/spec-kit) (see [relationship-to-spec-kit.md](relationship-to-spec-kit.md) for what we changed). This doc is the how-we-actually-run-it.

## The chain

```text
/speckit.specify  →  /speckit.clarify  →  /speckit.plan  →  /speckit.tasks  →  /review-plan  →  /speckit.implement
     spec.md          sharpened spec       plan.md +          tasks.md          GREEN/YELLOW/RED      working code
                                           research/contracts                   external review
```

| Phase | What it produces | What it's for |
| --- | --- | --- |
| `/speckit.specify` | `specs/NNN-name/spec.md` | Requirements in user language: user stories, functional requirements (FR-nnn), success criteria (SC-nnn). No implementation detail. |
| `/speckit.clarify` | Edits to spec.md | Up to five targeted questions about genuinely underspecified areas, answers encoded back into the spec. Cheap insurance against building the wrong thing. |
| `/speckit.plan` | `plan.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md` | The technical design: stack choices, structure, data model, interface contracts. |
| `/speckit.tasks` | `tasks.md` | Dependency-ordered task list with IDs (T001…), each small enough to verify independently. |
| `/review-plan` | GREEN / YELLOW / RED verdicts | **The gate.** Spec + plan go to external (non-Claude) models for independent critique before any code is written. YELLOW/RED requires explicit human approval to proceed. |
| `/speckit.implement` | Code | Executes tasks.md in order, checking off tasks as they verify. |

Supporting commands: `/speckit.analyze` (cross-artifact consistency check after task generation), `/speckit.checklist` (custom requirement checklists), `/speckit.constitution` (project principles that all templates then enforce), `/speckit.taskstoissues` (turn tasks.md into dependency-ordered GitHub issues).

On top of the chain sits a `/feature` orchestrator skill that runs the whole arc — orient, research, specify, plan, review, implement, ship — so "do issue #42 end-to-end" is one command, not eight.

## Why the review gate is the point

The chain without `/review-plan` is just structured prompting. The gate is what changes the economics: **the cheapest place to catch a design error is between the plan and the first line of code.** The review is done by models from a different vendor than the one implementing (see [multi-model-review.md](multi-model-review.md) for the anti-self-grading argument), and a YELLOW or RED verdict stops the pipeline until a human reads the critique and explicitly overrides or fixes.

In practice this catches: missing failure-mode handling in plans, success criteria that aren't measurable as written, contracts that don't cover concurrent access, and scope the spec implies but the tasks silently drop.

## A complete worked example, in this repo

`specs/001-review-plan-v2/` is a real feature spec that went through this exact chain — and the code it produced ships in this same repository at `scripts/review_plan_v2/`, with its tests in `tests/`. That makes it a rare artifact: you can read the spec, the plan, and the task list, then diff them against what actually got built.

Suggested reading order:

1. `specs/001-review-plan-v2/spec.md` — note how FRs stay implementation-free
2. `specs/001-review-plan-v2/plan.md` — the stack decision (Python stdlib only, thin bash entrypoint) and why
3. `specs/001-review-plan-v2/tasks.md` — how a plan decomposes into verifiable steps
4. `scripts/review_plan_v2/` — the result: orchestrator, reviewers, analyzers, providers
5. `tests/` — what "done" was defined to mean

## Running it end-to-end

Habits that make the chain work as a pipeline rather than a ceremony:

- **Don't pause between phases for permission.** The skill files end with "ready for /speckit.plan" — treat that as a marker, not a stop sign. The only mandatory stop is the review gate on YELLOW/RED, plus anything irreversible or externally visible.
- **One feature, one numbered spec dir.** `specs/001-…`, `specs/002-…` — the number is the feature's identity across branches, PRs, and conversation.
- **The spec outlives the implementation.** When reality diverges (a task turns out blocked, a success criterion gets measured), the spec/tasks files get updated with what was actually true — they're the record, not a sales document.
- **Convert tasks to issues for multi-session work.** `/speckit.taskstoissues` gives you resumability: any future session can pick up the next open issue with full context.

## What SDD costs, honestly

The chain adds real overhead: a small feature that would be a 20-minute prompt-and-review becomes an hour with artifacts. It pays for itself when any of these are true: the feature spans sessions or machines, more than one agent/person will touch it, the design has failure modes worth reviewing before code exists, or you'll need to explain six months later why it works this way. For one-shot scripts, skip the ceremony — that's what the ADR culture is for instead: decide once, record it, move on.
