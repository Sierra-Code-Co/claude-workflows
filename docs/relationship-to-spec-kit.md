# Relationship to GitHub's Spec Kit

The spec-driven machinery here descends from [github/spec-kit](https://github.com/github/spec-kit): the `.specify/` framework (scripts, templates, memory) and the `speckit-*` skills came from it, and its specify → plan → tasks → implement arc is the backbone of [our SDD workflow](spec-driven-development.md). This page is the honest ledger of what we kept, what we changed, and why the fork is deliberately detached.

## What we kept

- The phase model and its artifacts: `spec.md`, `plan.md`, `tasks.md`, plus `research.md` / `data-model.md` / `contracts/` / `quickstart.md` from the plan phase
- The numbered-feature convention (`specs/NNN-name/`) and the FR-nnn / SC-nnn requirement IDs
- The constitution concept — project principles that the phase templates then enforce
- The `.specify/` split between framework machinery and per-feature output

## What we changed, and why

| Divergence | Why |
| --- | --- |
| **`/review-plan` gate inserted between tasks and implement** | Spec Kit's chain goes straight from tasks to implementation. We added a mandatory external-model review of spec + plan (GREEN/YELLOW/RED, human approval required on YELLOW/RED) because the cheapest place to catch a design error is before the first line of code — and because of the [anti-self-grading principle](multi-model-review.md): the vendor writing the code shouldn't be the only one reviewing the design. |
| **`disable-model-invocation: true` on every skill** | Stock skills can be auto-invoked by the model when a description matches. Workflow-shaped skills firing by surprise mid-conversation was a real failure mode; all of ours are explicit slash commands only. |
| **`/feature` orchestrator on top** | One command that runs the whole arc (orient → research → specify → plan → review → implement → ship) including issue triage and PR creation, instead of a human typing seven commands in order. |
| **Run-through-without-pausing convention** | The stock skills end each phase with "ready for the next command" prompts. Our global instructions treat those as markers, not stop signs — the chain runs end-to-end, stopping only at the review gate and for genuinely irreversible actions. |

## Detached by design

Neither this repo nor the template tracks upstream as a fork, on purpose:

- **The skills are load-bearing.** Fleet consistency (see [architecture.md](architecture.md)) depends on the template being the single source of truth. An upstream that can change the skills' behavior underneath twenty projects would break the propagation model's core promise.
- **The divergences are the value.** The review gate, invocation policy, and orchestrator are the opinionated parts. Merging upstream wholesale would mean re-applying them on every sync.
- **But upstream isn't ignored.** A scheduled CI job in the private repo checks weekly for new spec-kit releases, and useful upstream changes get evaluated and ported deliberately — cherry-picked into the template with the local conventions applied, then propagated fleet-wide. Pull, don't merge.

If you're building your own setup: start from spec-kit directly — it's the maintained, general-purpose skeleton. Copy the *pattern* of our divergences (an external review gate, explicit-invocation-only workflow skills, one orchestrator command) rather than the files; they're each a few hours to re-create on current upstream, and you'll understand what you own.
