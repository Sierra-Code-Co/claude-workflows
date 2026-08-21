# Feature Specification: The Gate Portfolio — deterministic enumeration, claim verification, and fail-visible review

**Feature Branch**: `003-gate-portfolio`
**Created**: 2026-08-13
**Status**: Draft
**Input**: Consolidation of the 2026-08-13 review-tooling investigation. Decide which quality gates are deterministic and which are probabilistic, what each is allowed to block, in what order they run, and how each one proves it is capable of failing. Fold in the vendored-pristine + overlay decision for spec-kit, the three filed-and-unbuilt context augmentations (#18/#19/#20), and a fail-visibility sweep of the remaining skills.

## Background

This repo is the trunk. `mtg-cube-ai` is the proving ground, and twelve repos inherit whatever ships here. On 2026-08-13 a full day of production bug-fixing in the proving ground turned into an investigation of the review tooling itself, because the tooling kept being wrong in ways that looked right.

Three findings drive this spec.

**1. Two harness bugs are fixed; the design questions they exposed are not.**
`#27` fixed a dead OpenAI cascade leg (136 calls, 0 successes, ever) and added fail-visible run health. `#29` fixed the larger defect: `max_tokens` on reasoning models is a *combined reasoning+answer* budget, so the reviewers doing the hardest analysis exhausted it and returned HTTP 200 with empty content. Correctness failed 10.2% of production calls; security failed 0.77%. The tool was starved, not incompetent. Both fixes are merged. Every quality verdict measured before them is void, including the "15 findings, 1 real" scoreboard that motivated this work.

**2. Re-measured post-fix, the tool's failure mode is specific and gateable.**
Re-running the fixed tool against the same two diffs the void scoreboard used produced 10 actionable findings. Three were real, including a live blind spot in a source guard — a non-parse-aware regex comment-stripper that deletes real code in 4 files, hiding 6 live `console` calls in a single 765-line span of the product's hottest file (measured 2026-08-13; see the table below) — that four rounds of CodeRabbit never found. Every false finding shared one shape: **a confident, specific, technically detailed claim about the semantics of an API defined outside the diff.** Two of the three would have died in seconds by executing eight lines of code. That is not a context problem that more tokens fix; it is a missing verification step.

**3. The same defect class appears in three independent checks.**
`review-plan-v2` degraded silently for months. `check-speckit-update.yml` runs every Monday and has never produced a visible drift issue while the pin sat ~11 minor versions behind. `speckit.manifest.json` hashes exactly one file against a surface of nine skills, so the skills forked locally with nothing detecting it. Three checks, three silent degradations — including in the tooling whose stated purpose is to enforce fail-visible degradation.

The theme of this spec is therefore not "make the reviewer smarter." It is: **give each question the kind of gate that can actually answer it, and make every gate prove it can fail.**

## The routing model (the core design decision)

The earlier hypothesis — "review-plan-v2 is strong on localized logic and blind on sweeps/completeness work" — **is wrong as stated, and the spec must not encode it.** The post-fix comparison disproved it: the single best finding of the run *was* a completeness finding, on the sweep diff, derived by reading the guard's own source inside the diff.

The real split is not localized-vs-sweep. It is:

| Question shape | Correct gate | Why |
|---|---|---|
| "Is this code, which I can read, wrong?" | **Probabilistic reviewer** | Judgment. All 3 real findings were this shape. |
| "Did I get *all* the sites?" | **Deterministic enumerator** | Completeness over code not in the diff. An LLM cannot enumerate a repo it cannot see. |
| "Does this API actually behave the way the finding claims?" | **Execution** | Checkable in seconds. All 3 false findings were this shape. |
| "Is there a secret / syntax error / policy violation here?" | **Deterministic analyzer** | Already shipped (gitleaks, actionlint, shellcheck, markdownlint). |

The differentiator between our reviewer and CodeRabbit was never context volume — CodeRabbit's advantage is that its analysis chains *run things* (`rg`, `ast-grep`, `node`) against the checkout before asserting. More context helps. Being able to verify a claim before emitting it helps more.

## Prerequisite: the constitution is an unfilled template

`.specify/memory/constitution.md` in this repo is still `[PROJECT_NAME]` / `[PRINCIPLE_1_NAME]`. `/speckit.plan`'s mandatory Constitution Check would validate this feature against placeholders — a gate that passes because it has nothing to compare against, which is precisely the defect class this spec exists to close. US1 fixes it before any other work proceeds.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — The trunk has principles that gates can be checked against (Priority: P1)

A developer running `/speckit.plan` in this repo, or in any of the twelve repos that inherit from it, gets a Constitution Check that compares the plan against real, non-negotiable principles drawn from actual incidents — not against template placeholders. The principles state, at minimum: that a check reporting to nobody is not a check; that a gate must demonstrate it can fail; that completeness questions get deterministic answers; and that a limit is never sized from data collected under that limit.

**Why this priority**: It is a hard blocker. Every other user story in this spec produces a plan that must pass a Constitution Check, and today that check is vacuous. It is also the highest-leverage single artifact in the repo, since it propagates to every downstream project.

**Independent Test**: Run `/speckit.plan` on this spec. Verify the Constitution Check section cites specific numbered principles and that at least one gate decision in the plan is justified or rejected by reference to one. Confirm zero `[PLACEHOLDER]` tokens remain in `constitution.md`.

**Acceptance Scenarios**:

1. **Given** the filled constitution, **When** a plan proposes a check that logs a failure without surfacing it, **Then** the Constitution Check fails and names the violated principle.
2. **Given** the filled constitution, **When** a plan proposes an LLM gate for a completeness question, **Then** the Constitution Check flags it and requires a justification entry in Complexity Tracking.
3. **Given** a downstream repo with its own constitution, **When** the trunk constitution is amended, **Then** the amendment is recorded with a version bump and a sync-impact report, so the drift that let the proving-ground constitution rot for three months is visible.

---

### User Story 2 — A finding that makes a checkable claim is checked before it is shown (Priority: P1)

A reviewer emits a finding asserting that a function returns a particular shape, that an AST predicate does not match a particular node, or that a symbol does not exist. Before that finding reaches the developer, the harness attempts to verify the claim against the actual checkout. Claims that are refuted are dropped, or demoted and labelled as unverified — never presented with the same confidence as a finding about code the reviewer could read.

**Why this priority**: This is the single highest-leverage change the post-fix measurement identified. 3 of 3 false actionable findings were checkable claims about out-of-diff API semantics, and two were refutable by executing under ten lines. One of them — that `describeThrown()` may return `undefined` for a declared field — has now recurred as a false positive in three independent runs, which means no amount of prompt tuning is going to remove it. False findings are more expensive than missed ones: they cost developer trust, and this session shows they also cost real time, because a plausible false finding gets investigated.

**Independent Test**: Replay the gold set (below) of 10 classified findings from the 2026-08-13 comparison through the verification stage. Verify all 3 known-false claims are refuted, and all 3 known-real findings survive untouched.

**Acceptance Scenarios**:

1. **Given** a finding claiming a function's return type differs from the code, **When** verification runs, **Then** the claim is checked against the type declaration and the finding is dropped if refuted.
2. **Given** a finding claiming a symbol does not exist in the repo, **When** verification runs, **Then** the claim is checked by enumeration and refuted findings are dropped.
3. **Given** a finding whose claim cannot be mechanically checked (a design judgment), **When** verification runs, **Then** the finding passes through unchanged and is not penalized for being unverifiable.
4. **Given** the verification stage itself fails or times out, **When** the run completes, **Then** findings are shown with an explicit "unverified" marker rather than silently passing through as verified.

---

### User Story 3 — Completeness questions are answered by enumeration, never by a reviewer (Priority: P1)

A developer doing a sweep — "replace every raw `console.error(err)` with `describeThrown`", "migrate all 57 catch sites" — gets a deterministic answer to "did I get all of them?" in milliseconds, expressed as a portable rule rather than a hand-rolled scanner. The rule engine understands code structure, so the answer does not depend on which formatting style a call site happens to use.

**Why this priority**: The proving ground burned five review rounds on this exact question and got it wrong four times. Every hand-rolled regex scanner written that day had a different blind spot: one anchored on `ident)` and missed multi-line calls with trailing commas (7 live sites); one pre-stripped block comments with a non-parse-aware regex and scanned a mutilated copy of its highest-risk file (6 live sites inside one 765-line span). The general lesson stated at the time — *regex over call syntax does not hold; it was used three times and was wrong three times* — is the requirement here. This is also the cheapest gate in the portfolio: it runs at zero LLM cost and answers in milliseconds what cost hours of review.

**Independent Test**: Express the proving ground's `describeThrown` policy as a structural rule. Run it against the pre-sweep commit and verify it enumerates all 57 sites including every formatting variant (trailing comma, own-line argument, non-final argument, single argument, template literal, nested call, and a call inside a block comment). Run it against the post-sweep commit and verify zero.

**Acceptance Scenarios**:

1. **Given** a structural rule and a repo with N violating sites in mixed formatting styles, **When** the rule runs, **Then** it reports exactly N, independent of formatting.
2. **Given** a violating call written inside a block comment, **When** the rule runs, **Then** it is correctly *not* reported — and given a violating call written *after* a block comment, **Then** it *is* reported.
3. **Given** a completeness rule exists for a policy, **When** a reviewer emits a finding of the form "you may have missed some call sites", **Then** the finding is replaced by the enumerator's exact answer.
4. **Given** a repo with no structural rules configured, **When** the harness runs, **Then** it reports that no completeness coverage is active rather than silently reporting clean.

---

### User Story 4 — Every gate proves it can fail, and the proof is a required artifact (Priority: P1)

Anyone adding or modifying a gate must record how the gate was demonstrated to fail: the seeded violation, the observed red result, and the restoration. A gate without that record is not accepted. The check runs against known-bad input, not only against the cases it already handles.

**Why this priority**: Earned four separate times in one session, twice inside the tooling built to prevent it. A test suite passed against unfixed code. A source guard reported clean over seven live leaks — *and every positive control written for it happened to use the one call shape it could see, so the controls passed too*. A CI drill silently never ran, because the worktree had no `node_modules` and the grep for "Tests" matched nothing, which reads identical to passing. And `reasoning_effort=none` made reviews fast, complete, and clean on everything while returning **zero findings on both planted-bug fixtures** — a change that would have looked like a pure win on every metric the harness collects. Only testing against known-bad input caught it. A guard validated solely against cases it already handles proves nothing.

**Independent Test**: Take each gate in the portfolio, seed its violation, and confirm a red result. Confirm the plan template rejects a gate proposal that lacks the field.

**Acceptance Scenarios**:

1. **Given** a new gate proposal without a failure proof, **When** the plan is reviewed, **Then** it is rejected with a named missing field.
2. **Given** a gate whose positive controls all use one input shape, **When** the failure proof is written, **Then** it must enumerate the distinct input shapes the gate claims to cover.
3. **Given** a gate that has been made permanently incapable of failing by a config change, **When** the failure-proof check re-runs in CI, **Then** it goes red.
4. **Given** a gate expressed as a rule with N constraints, **When** its failure proof is validated, **Then** the proof is rejected unless it carries N near-miss negatives, each violating exactly one constraint while satisfying the rest — the shape list is derived from the rule, not supplied by the author.
5. **Given** a schema whose invariant is conditional on a field, **When** its failure proof is validated, **Then** the proof is rejected unless it covers that field **absent** in addition to every value case.

---

### User Story 5 — Reviewers see the definitions of symbols they reason about (Priority: P2)

When a diff calls a function defined elsewhere, the reviewer receives that definition. When a diff adds test files, the reviewer is told they are tests. Standing project context is attached to every reviewer call rather than being re-derived per run.

**Why this priority**: Three issues (#18 `always_include_files`, #19 `--include-related-files`, #20 round-N memory) were filed 2026-04-30 and never built. #19 is the direct fix for the recurring `describeThrown` false positive: the interface lives in a file outside the diff window. The recurring "no tests exist for this path" false positive — raised four times across the session against diffs whose test files were *in the same diff* — is the other half. This is P2 rather than P1 because US2's verification stage catches the resulting false findings even when context does not prevent them; context reduces the volume, verification enforces the floor.

**Independent Test**: Run the gold-set replay with related-file context enabled and verification disabled. Verify the `describeThrown` and "no tests" false positives are not generated in the first place.

**Acceptance Scenarios**:

1. **Given** a diff calling a symbol defined in an untouched file, **When** review runs, **Then** that definition is included in the reviewer's context.
2. **Given** a diff that adds test files, **When** review runs, **Then** findings asserting the absence of tests for covered paths are not produced.
3. **Given** a second review round on the same branch, **When** review runs, **Then** findings already raised and addressed in round 1 are suppressed.
4. **Given** context assembly exceeding the configured budget, **When** review runs, **Then** the harness reports what it dropped rather than silently truncating.

---

### User Story 6 — Gates are tiered, ordered, and earn the right to block (Priority: P2)

Cheap deterministic checks run first; probabilistic reviewers run only if they pass. Deterministic rules with no false-positive mode may hard-block. Probabilistic findings advise. A new gate enters the portfolio advisory, and is promoted to blocking only on measured acceptance.

**Why this priority**: This is the external consensus (hybrid deterministic + probabilistic reportedly outperforms either alone; layering AI comments on top of unresolved lint noise destroys trust quickly), and it matches what the portfolio already does halfway — gitleaks runs sequentially first and can halt the run. The gap is that the tiering is implicit in code rather than a stated contract, so nothing prevents the next gate from being added at the wrong tier.

**Independent Test**: Add a deliberately noisy advisory rule. Verify it cannot block a push, that its acceptance rate is recorded, and that promoting it to blocking requires an explicit config change rather than happening by default.

**Acceptance Scenarios**:

1. **Given** a deterministic check that fails, **When** the run proceeds, **Then** probabilistic reviewers do not run and no LLM spend is incurred.
2. **Given** a probabilistic finding, **When** it is rendered, **Then** it is labelled as advisory and cannot by itself produce a blocking exit code.
3. **Given** a gate at advisory tier, **When** promotion to blocking is proposed, **Then** the proposal cites a measured acceptance rate over a stated number of runs.

---

### User Story 7 — Upstream spec-kit stays pristine and drift is legible (Priority: P2)

Vendored upstream files are never hand-edited. Local opinions live in separate overlay files. The manifest hashes every vendored file against its declared source, so an update reports exactly which files changed upstream, which are clean, and which have been locally modified and will conflict.

**Why this priority**: The pin sits at `0.5.1.dev0` (2026-04-07) against upstream `v0.16.2` (2026-08-10) — roughly eleven minors and four months behind — with a weekly checker that has never surfaced an issue and a manifest covering one file out of a nine-skill surface. Pristine vendoring is what preserves the ability to *read* upstream's diff and adopt improvements; editing in place permanently destroys it, which is the current state. Each skill already declares `metadata.author: "github-spec-kit"` and `metadata.source`, so the provenance mapping exists and the manifest simply does not use it.

**Independent Test**: Modify one vendored file locally. Run the drift check. Verify it names that exact file as locally modified and distinguishes it from files that merely changed upstream.

**Acceptance Scenarios**:

1. **Given** an upstream release with changes to 6 files of which 1 is locally modified, **When** the drift check runs, **Then** it reports 5 clean and 1 conflicting, by name.
2. **Given** the drift check finds drift, **When** it completes, **Then** the result reaches a human — and a run that produces no notification is itself reported as a failure.
3. **Given** a developer needs to change vendored behavior, **When** they attempt to edit a vendored file, **Then** the workflow directs them to either upstream the change or express it as an overlay.

---

### User Story 8 — The remaining skills are swept for the same silent-failure class (Priority: P3)

Every other skill and script in this repo is audited for checks that can degrade without anyone noticing: swallowed exceptions, warn-only paths that never escalate, notifications that depend on a channel nobody reads, and success paths that cannot distinguish "passed" from "never ran".

**Why this priority**: Three-for-three on the checks examined so far is not a coincidence, it is a pattern, and the remaining skills have never been looked at through this lens. P3 because it is discovery work whose scope is unknown until the sweep runs; findings become their own issues.

**Independent Test**: For each skill, identify the failure signal and confirm it is distinguishable from success. Record any that are not.

**Acceptance Scenarios**:

1. **Given** a skill that invokes an external service, **When** that service is unavailable, **Then** the skill's output distinguishes "unavailable" from "found nothing".
2. **Given** a skill with a warn-only code path, **When** the sweep runs, **Then** it is recorded with either a promotion plan or an explicit justification for staying advisory.

---

## The gold set (replay corpus)

US2 and US5 are measured against a fixed corpus rather than against new runs, so that a change to prompts cannot quietly move the target. The corpus is the 10 actionable findings from the 2026-08-13 post-fix comparison, each already classified by reading the code:

| Diff | Finding | Classification |
|---|---|---|
| #2099 | comparator change orphans persisted dedup keys | **REAL** (matched CodeRabbit's own Major) |
| #2099 | "no test coverage added" | FALSE — tests were in the diff |
| #2101 | guard misses optional chaining via wrong AST predicate | FALSE — refuted by the TS compiler API |
| #2101 | missing tests for optional-chain forms | FALSE — follows from the above |
| #2101 | guard pre-strips block comments non-parse-aware | **REAL AND STILL LIVE** — see measurement below |
| #2101 | `describeThrown(...).errMessage` may be undefined | FALSE — 3rd independent recurrence |
| #2101 | replacing error object strips the promised stack trace | **REAL** |
| #2101 | "no tests for this catch path" ×3 | test-blindness class, unverified |

Target: 3 real retained, 3 checkable-false refuted. The three test-blindness findings are US5's measure, not US2's.

### Measured 2026-08-13: the comment-stripper finding is still live

Re-verified against the proving ground's current `staging`, using AST node
positions as ground truth (a genuine block comment contains no code nodes). An
earlier attempt using the TypeScript *scanner* for ground truth reported ~170
bogus spans across 46 files and was wrong — flagging ordinary JSDoc — which is
itself an instance of Principle III and is recorded here so the number is not
cited from the bad run.

Across 357 `.ts` files, **4 files** contain a span where
`src.replace(/\/\*[\s\S]*?\*\//g, '')` deletes real code:

| File | Live `console` calls deleted |
|---|---|
| `web/src/routes/api/chat/+server.ts` | **6** |
| `web/src/lib/server/describe-thrown.guard.test.ts` | 19 (fixture strings, not production code) |
| `web/src/lib/components/usage-meter-format.ts` | 0 |
| `web/src/lib/server/usage-snapshot.ts` | 0 |

The `+server.ts` case is the instructive one. Line 3511 is a **line** comment:

```ts
// delegate to /api/workflow/tools/* which enforces ownership (FR-026)
```

The `/*` inside `tools/*` opens a fake block comment. The regex closes it 765
lines later at the `*/` inside a regex literal `/\s*\n+\s*/g`. **A 33,904-character
span — 765 lines of the hottest file in the product — is deleted before two of
the three guards ever see it.**

The AST-based console scan was fixed (it reads original source and cites
CR #2098 in a comment). `offenders()` at line 247, which feeds the `NAME_EXTRACT`
and `STRINGIFY_LEAK` guards, still pre-strips. So the finding was half-fixed,
and the half that remains covers the two guards protecting against the
original #2048 row-value leak. This is the concrete motivating case for FR-006, and it is
a live defect in the proving ground to be filed separately.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The trunk constitution MUST contain no template placeholders and MUST state the fail-visibility, provable-failure, deterministic-completeness, and censored-data principles as numbered, checkable principles.
- **FR-002**: A finding that asserts a mechanically checkable fact about the checkout MUST be verified before presentation; refuted findings MUST NOT be presented as findings.
- **FR-003**: Verification failure MUST be visible. A finding that could not be verified MUST be labelled, never silently promoted to verified.
- **FR-004**: Completeness questions MUST be answerable by a structural rule engine that is not regex-over-syntax.
- **FR-005**: A structural rule MUST produce identical results across formatting variants of the same construct, including multi-line calls, trailing commas, and arguments on their own line.
- **FR-006**: Comment handling in any scanner MUST be parse-aware; pre-stripping comments with a regex before parsing is prohibited.
- **FR-007**: Every gate MUST carry a recorded failure proof naming the seeded violation and the observed red result.
- **FR-008**: A gate's failure proof MUST enumerate the distinct input shapes the gate claims to cover, not only the shape used in its first positive control.
- **FR-008a**: The shape list in FR-008 MUST be derived mechanically from the gate's decision structure rather than supplied from the author's recall, because author recall reproduces the set the gate already handles. For a structural rule with N constraints, the proof MUST include N near-miss negatives, each violating exactly one constraint while satisfying the rest. For a schema invariant conditional on a field, the proof MUST include the field-absent case as well as every value case. The derivation MUST be checkable: constraint count and covered-shape count are both machine-readable, so a proof with fewer negatives than constraints fails validation without human judgment.
- **FR-009**: Reviewers MUST receive definitions for symbols the diff references but does not define.
- **FR-010**: Added test files MUST be identifiable as tests to the reviewer.
- **FR-011**: Context dropped for budget reasons MUST be reported.
- **FR-012**: Deterministic checks MUST run before probabilistic reviewers, and a deterministic failure MUST prevent LLM spend.
- **FR-013**: Only deterministic gates may hard-block. Probabilistic findings are advisory.
- **FR-014**: A gate MUST enter the portfolio at advisory tier; promotion to blocking MUST cite measured acceptance.
- **FR-015**: The vendoring manifest MUST hash every vendored file against its declared upstream source.
- **FR-016**: A drift check that produces no notification MUST be treated as a failed run, not a clean one.
- **FR-017**: Vendored files MUST NOT be hand-edited; local behavior MUST be expressed as overlay files.
- **FR-018**: Every gate MUST emit run health — what ran, what was skipped, and why — on every run, including successful ones.
- **FR-019**: No gate may size a threshold or limit from telemetry collected under that same threshold.
- **FR-020**: No gate may write to the dataset used to judge it.
- **FR-021**: Telemetry MUST record sizes, counts, and outcomes — never prompt bodies, diff content, or message content.
- **FR-022**: Diff content is **untrusted data**. A reviewer reads attacker-influenceable text, so any claim it emits is attacker-influenceable output.
- **FR-023**: A verification `check` MUST NOT execute reviewer-authored commands or snippets. Permitted inputs are limited to: a registered structural-rule id, a symbol path resolved against the checkout, or a type name — each validated against an allowlist before use. Free-form command strings are prohibited regardless of how the claim was phrased.
- **FR-024**: The `execute` check method MUST remain unimplemented until a sandboxing model is specified and reviewed. Until then it resolves to `unverifiable` with an explicit log line, so the gap stays visible rather than presumed handled.

### Security boundary (added after review of this spec)

`review-plan-v2` flagged this on the spec itself, and it is correct: the routing model
promotes execution to a first-class verification step while the reviewer producing the
claims is reading untrusted diff content. Without a stated boundary, a malicious diff
could steer a reviewer into emitting a claim whose "verification" runs attacker-controlled
code — turning the safety mechanism into an RCE vector inside the review pipeline.

The boundary: **verification inputs are derived deterministically or drawn from an
allowlist; they are never taken as free-form text from a model that read the diff.** The
three gold-set false findings are all refuted by `enumerate` and `typecheck`, neither of
which needs to run reviewer-authored code, so this constraint costs nothing measurable
against SC-002.

This is also why Microsoft Threat Intelligence's finding on the Claude Code GitHub Action
(CI secret exposure when processing untrusted GitHub content, fixed in 2.1.128) stays in
Out of Scope: the same untrusted-input boundary has to be settled before gates move into
Actions.

### Key Entities

- **Gate** — a named check with a tier (deterministic/probabilistic), a blocking policy, an ordering position, a failure proof, and a health signal.
- **Finding** — a reviewer output carrying a claim, a claim-checkability classification, and a verification verdict.
- **Structural rule** — a portable, engine-executed pattern expressing a policy over code structure; the deterministic answer to a completeness question.
- **Vendored file** — an upstream artifact with declared provenance, a content hash, and a pristine/modified status.
- **Overlay file** — a local artifact that composes over vendored behavior without editing it.

## Success Criteria *(mandatory)*

- **SC-001**: `constitution.md` contains zero placeholder tokens, and `/speckit.plan` on this spec produces a Constitution Check citing numbered principles.
- **SC-002**: On the gold set, all 3 checkable-false findings are refuted and all 3 real findings are retained — measured as 3/3 and 3/3, not as an aggregate rate.
- **SC-003**: A structural rule for the `describeThrown` policy enumerates every violating site at the pre-sweep commit (`81f54898`) and 0 at the post-sweep commit (`083084e5`), including the 7 multi-line sites the first regex missed.
- **SC-003b**: Running the portfolio's own scanners over the proving ground's `staging` yields 0 files in which a comment-handling step deletes code — measured with AST node positions as ground truth, down from the 4 files (and one 765-line span in `+server.ts`) measured on 2026-08-13.
- **SC-004**: Every gate in the portfolio has a recorded failure proof, and seeding each gate's violation produces a red result — verified by running each proof, not by inspecting the record.
- **SC-005**: With related-file context enabled, the `describeThrown` and "no tests exist" false-positive classes are not generated on the gold-set diffs.
- **SC-006**: A deterministic failure short-circuits the run with zero LLM calls made, verified from telemetry call counts.
- **SC-007**: The manifest covers 100% of the vendored spec-kit surface — 9 skills plus templates and scripts — up from 1 file.
- **SC-008**: Locally modifying one vendored file causes the drift check to name that file, distinguishing it from upstream-changed-but-clean files.
- **SC-009**: Every skill in `.claude/skills/` has a recorded answer to "how would a silent failure of this skill be detected?", with any gaps filed as issues.
- **SC-010**: A run with a dead provider leg exits non-zero and names the dead leg — the regression guard for #27, now asserted rather than assumed.

## Out of Scope

- Rewriting the reviewer prompts for quality. Prompt tuning cannot fix the three false-positive classes measured here; three independent runs produced the same false claim.
- Migrating off spec-kit. 213 specs and a load-bearing constitution in the proving ground make a framework swap expensive and lossy. Individual skills from other sources are adopted as overlay, never as a framework replacement.
- Restoring the CodeRabbit bot on this repo. It reviewed 8 PRs through #25 and has been silent since 2026-05-09 with correct config; this needs the operator's CodeRabbit dashboard, not a code change. Tracked separately, but noted here because it means the trunk — which propagates to twelve repos — currently has the weakest review coverage in the fleet.
- Moving gates into GitHub Actions. Deferred pending review of the Microsoft Threat Intelligence finding that the Claude Code GitHub Action could expose CI secrets when processing untrusted GitHub content (fixed in 2.1.128).
- The entries-vs-quantity units bug and other proving-ground application bugs.

## Assumptions

- The two prerequisite harness bugs (#27, #29) remain fixed; this spec is written against a working tool and its acceptance criteria assume post-fix behavior.
- The gold-set diffs (#2099, #2101 in the proving ground) remain reachable for replay.
- The operator's own LLM API keys remain the funding model for probabilistic gates; deterministic gates must remain zero-cost.
