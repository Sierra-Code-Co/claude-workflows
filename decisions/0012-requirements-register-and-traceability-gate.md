# 0012 — A requirements register in the build repo, and a script that makes FR traceability real

**Status:** partly superseded — the register stands, part 3 (the gate) was rolled back
**Date:** 2026-09-10
**Superseded:** 2026-09-10, same day, by decision #4 and rollback R1 in a client's private fork of the template
**Tags:** speckit, scope, requirements, traceability, gates, internal-speckit-template

> **Read this first.** Parts 1, 2 and 4 of the Decision below are in force. **Part 3 is not.**
> `scripts/assert-requirements-traceability.sh` was rolled back the day it was built, recorded as
> R1 in that client fork of the template. Two reasons, both of which this ADR contains the evidence for
> without drawing the conclusion: its output on the first real repo was the 59 findings across two
> pre-register specs that the Consequences section already calls "a 59-item bill", and nobody was
> going to action them; and 320 lines of script plus a 400-line suite is larger than the register it
> enforces. What replaced it is `complexity-budget.md` thresholds, which force a decision to be
> recorded before the code exists rather than cataloguing citations after.
>
> The "Why a script and not a principle" argument below is left as written rather than edited,
> because the reasoning was not wrong — a rule enforced only by remembering to look did fail on its
> first use. What it got wrong is the cost side, which is not visible until the gate is pointed at a
> repo with history. The generalisable lesson survives the rollback: **enforcement machinery larger
> than the thing it enforces is scaffolding, whatever it is guarding.**

## Context

One project in the fleet reached **five figures of source lines on `main` containing zero lines of the requestor's first priority.** Not late, not partially built — absent. The requestor's actual ask was a data-entry form replacing a spreadsheet workflow; what existed instead was a routing backend, including an 8,000-line datastore built for a consumer that did not exist yet.

Nothing in the repo was wrong on its own terms. The specs were internally coherent, the tests passed, the constitution existed, and the spec-quality checklists were filled in. The failure was upstream of all of it, in four places at once:

1. **The requirements lived somewhere the code could not see them.** Scope was recorded in a separate notes workspace, on the theory that "if a fact would change the code it belongs in the build repo; if it would change who to talk to it belongs in the notes." Requirements are the first case, and they had been filed as the second. No coding agent working in the build repo ever read them.
2. **Each spec's `Input:` field paraphrased whoever ran the command.** So an FR traced to a sentence typed at a prompt, not to anything a stakeholder said. There was no way to ask "who wanted this?" and get an answer.
3. **The constitution's Out of Scope section named the requestor's first priority as somebody else's problem**, and had for two weeks, while the notes-side requirements record listed it as the ask. Two scope documents disagreed and nothing read both. Each looked authoritative on its own.
4. **The quality checklist recorded the traceability box as ticked** while the condition was false, because a checklist is a self-report.

The first remedy was a **requirements register** — numbered stable IDs, a verbatim quote per requirement, a provenance reference, a status of Confirmed / Asked / Inferred / Open, a named owner on every open question — committed to the build repo, plus a constitution principle marked ELEVATED requiring every functional requirement to cite a register ID.

**The very first spec written under that principle violated it.** Two FRs cited constitution principles instead of register IDs, and the spec-quality checklist's traceability box was ticked anyway. A vendor review round found it; the author did not, and neither did the checklist. That is the fact this ADR is built around: the rule failed on its first use, with a self-report claiming otherwise.

A second, smaller problem compounded it. Spec-kit's `/speckit-specify` writes its spec-QUALITY checklist to `specs/<feature>/checklists/requirements.md`. With the register at `docs/requirements.md`, grepping a repo for `requirements.md` returns the wrong file — and a coding agent that opens a quality checklist looking for scope finds a list of ticked boxes and treats it as the requirements. That collision is recreated on every new feature, because the skill that writes it is vendored from upstream.

## Decision

**Four parts, and only the third is new machinery.**

1. **The requirements register is `docs/requirements.md`, committed to the repo that holds the code.** `internal-speckit-template` ships a starter with a status vocabulary, example rows, and a self-identifying HTML comment marking it as unreplaced.
2. **Every functional requirement in every `specs/*/spec.md` cites at least one ID the register actually defines.** An FR that cannot cite one is a deletion candidate, not a feature. Where the register and the constitution's Scope section disagree, **the register wins and the constitution is what gets corrected** — stated in `.specify/memory/constitution.md` itself, in the Scope section, as an instruction to whoever reads it next.
3. **`scripts/assert-requirements-traceability.sh` enforces rule 2 mechanically**, runs in the pre-push gate, and also *repairs* the checklist filename collision. Exit codes are tiered `0` clean / `1` actionable / `2` could not run.
4. **Never name a checklist `requirements.md`.** Spec-quality checklists are `specs/<feature>/checklists/spec-quality.md`.

The register also draws a content boundary rather than a location boundary. A verbatim requirement quote and its provenance belong in the build repo. A stakeholder read-out, anything about a named person's competence or politics, a transcript excerpt beyond the sentence stating the requirement, and anything received under a no-reshare condition stay in the notes workspace and reach the build repo — if at all — through a gitignored symlink.

## Why

**Why a script and not a principle.** Because the principle was tried, in the strongest form available (ELEVATED, in the constitution, the same week), and the first spec authored under it broke it while its own checklist said otherwise. A rule whose only enforcement is someone remembering to look has a measured failure rate, and this one's first measurement was 100%. The generalisable form: **a check whose failure is indistinguishable from its success is not a check** — a ticked box and a satisfied condition look identical on the page.

**Why the collision check repairs instead of failing.** `/speckit-specify` is vendored and re-created by `specify init --force` on every `setup.sh` run, so the offending filename comes back on every new feature and after every template update. A gate whose remedy is a manual rename every time is a gate that gets skipped. It repairs, names every file it touches on stdout, and fails loudly on anything it cannot repair — including refusing, without clobbering, when both filenames exist, because a repair that destroys the file it could not reconcile is worse than the collision.

**Why the traceability check does NOT repair.** There is no safe automatic fix. An FR citing nothing is either mis-cited — a human must pick the right ID — or has no register row at all, in which case a human must go ask someone. Inventing a citation converts a real gap into a passing build, which is the exact failure this ADR exists to end. The asymmetry between the two checks is deliberate and is the point.

**Why not patch the vendored skills instead.** Seven references to `checklists/requirements.md` live across five vendored skill and template files. Editing them is destroyed on the next `setup.sh`, and the template's own overlay rule forbids editing vendored text in place. So the rule lives in the two files that survive re-vendoring — `CLAUDE.md` and `.specify/memory/constitution.md` — and the script cleans up after the vendored behaviour rather than trying to prevent it.

**Why exit codes are tiered.** A caller gating on a single non-zero cannot distinguish "this spec violates traceability" from "the script never read a file". Both are non-zero; only one is a scope problem. This is the same lesson ADR-0008's exit-code section records about a vendor CLI that returns 1 for an unknown flag, for "not a git repository", and for "found issues" alike.

**Alternatives rejected:**

- **Keep requirements in the notes workspace and cross-reference.** This is what produced the failure. The cross-reference is the step that does not happen, and a scope record the code cannot see is a scope record the code will contradict.
- **Make the constitution's Scope section authoritative.** It was, nominally, and it was wrong for two weeks. A prose section maintained by hand alongside a structured register drifts, and the version with IDs and quotes is the one that can be checked against a person.
- **Rely on the spec-quality checklist.** It is a self-report, and it reported the opposite of the truth on the first attempt.

## Consequences

**What this enables.** Scope becomes greppable and answerable: every FR resolves to an ID, a quote, and a person. "Who asked for this?" has an answer that is not "whoever ran `/speckit-specify`." An open question has a named owner, so it can be chased instead of silently defaulted. And a spec that builds something nobody asked for now fails a gate before it reaches `main`.

**What it costs.** Writing a spec now requires a register row first, which means going and asking when the requirement is not actually known. That is the intended cost — the alternative is inferring it and finding out later.

**What it does not do, stated rather than implied:**

- **It checks that an FR cites a defined ID, not that it cites the RIGHT one.** An FR citing `R1.1` when it implements `R4.2` passes. Semantic correctness is still a human read; this gate removes only the class where an FR traces to nothing at all.
- **A register full of the shipped starter's example rows passes while tracing nothing.** The starter carries a self-identifying comment and the script warns when it is still present, because inferring that from silence is the failure class above.
- **The gate is blind to requirements the register does not have.** It cannot tell you the requestor's first priority is missing — only that every FR present traces to something. Rule 2's register-versus-constitution diff is the half that catches an absence, and that half is still a human step.

**Retrofit debt is real and is being taken on knowingly.** Pointed at the originating project, the gate reports 88 FRs across three specs and 59 findings: 44 in the first spec, 15 in the second, **0 in the third.** The first two predate the register. The third was written under the traceability rule and is fully traceable — which is the evidence that the mechanism works, and simultaneously a 59-item bill for the specs written before it existed. Those specs need either retro-citation or an explicit "pre-register, accepted" marker; until that is decided, the gate cannot be promoted to blocking in that repo.

**Setup-time behaviour is deliberately non-fatal.** `setup.sh` runs the script and does not abort on exit 1, because on a fresh bootstrap "no specs and a starter register" is the correct state and would otherwise fail every new project's setup. The rename is the useful half at setup time; the traceability report is information. Pre-push is where non-zero must block.

**Suite discipline carried over from this portfolio's gate defect logs.** Every fixture is a real `git init` repository, because a mocked tree cannot exhibit a rename that half-succeeds. The clean case asserts exit 0 **and** a non-zero count of FRs examined, since "passed" and "checked nothing" are exactly the pair this script exists to separate. Three parser defects were found only by running against a real repository and none by the fixtures — a heading-only register group read as undefined, prose mentions of an FR counted as definitions, and a wrapped paragraph whose line break landed before an FR ID — and all three now have regression cases. The middle one inflated 76 requirements to 113; the last produced a false finding against a spec where every FR was correctly cited, which is the worse direction to be wrong in, because a gate that cries wolf on a clean spec is a gate that gets bypassed.
