# Phase 0 Research — 003 Gate Portfolio

All findings below were produced by running the tools, not by reading their docs.
Constitution Principle II makes the demonstration the deliverable; a claim that an
engine "can express the policy" is worth nothing until a rule has been written,
run against known-bad input, and observed going red.

## R1: Which structural rule engine? — DECIDED: ast-grep

**Decision**: `ast-grep` 0.45.1 as the structural enumerator. Semgrep 1.172.0 installed
alongside for evaluation but not adopted in this phase.

**Rationale**: measured, not assumed. The `describeThrown` policy — "a raw caught value
must never be passed to a server-side logger" — is the hardest real completeness rule
this repo's fleet has, having defeated four hand-rolled scanners across five review
rounds. It was expressed as a **24-line ast-grep YAML rule** that replicates a
**421-line** hand-rolled TypeScript-compiler-API guard, and it gets right every case
the hand-rolled versions got wrong.

### The rule

```yaml
id: raw-caught-to-logger
language: typescript
severity: error
message: "raw caught value passed to a server logger; use describeThrown(e).errMessage"
files:
  - "**/src/lib/server/**/*.ts"
  - "**/src/routes/api/**/*.ts"
ignores:
  - "**/*.test.ts"
rule:
  kind: identifier
  pattern: $ERR
  all:
    - inside:
        kind: arguments
        stopBy: neighbor
        inside:
          kind: call_expression
          stopBy: neighbor
          has:
            field: function
            regex: '^console\.(error|warn|log)$'
    - inside:
        kind: catch_clause
        stopBy: end
        has:
          field: parameter
          pattern: $ERR
```

### Capability findings

- **Metavariable unification across relations works.** `$ERR` bound in the match target
  unifies with `$ERR` in the `catch_clause` parameter constraint. This is the capability
  the whole rule turns on, and it was not assumed — an earlier version without it
  produced 8 false positives on real code (`modelId`, `toolCallId`, `idx`, and even the
  already-remediated `describeThrown(err).errMessage`), because `inside: catch_clause`
  proves only that an identifier is lexically *within* a catch block, not that it *is*
  the catch binding.
- **Comment handling is free and correct.** The engine parses; comments are trivia. The
  three decoy shapes (line-commented call, block-commented call, and a call *following*
  a line comment containing `/*`) are all handled with no special casing.
- **Formatting invariance is free.** Multi-line calls with own-line arguments and
  trailing commas — the seven live sites the first hand-rolled regex missed because it
  anchored on `ident)` — match identically to single-line calls.

### Measured against the real repo

| Corpus | Result |
|---|---|
| Pre-sweep (`68db762a`, before #2100/#2101) | **30 sites across 10 files**, incl. 17 in `+server.ts` |
| Post-sweep (current `staging`) | **0** |
| Seeded violation (multi-line, own-line arg, trailing comma) | **exit 1**, correctly located |
| After restore | **exit 0**, working tree clean |

This satisfies SC-003's shape and constitutes the rule's recorded failure proof
(Principle II).

### The false positive it did produce, and why it is not one

Before the `files:` scope was added, the rule flagged
`web/src/routes/chat/[id]/+page.ts:78`. Investigated rather than assumed: line 1 of that
file is `export const ssr = false`, so the universal load never runs server-side, the
`console.error` reaches the browser console, and `e` is a fetch/JSON error rather than a
PostgREST object. **The existing guard's `isServerSide()` exclusion is correct.** The
rule needed the same scope, expressed as a `files:` glob — a config concern, not a
limit on expressiveness.

### Alternatives considered

- **Semgrep** — installed and available. Richer dataflow (taint tracking), a large
  community rule registry, and a portable rule format. Deferred rather than rejected:
  ast-grep cleared the hardest known policy in this fleet without needing dataflow, and
  it is a single Rust binary versus a Python toolchain, which matters for `new-machine.sh`
  and for twelve repos. **Revisit trigger**: the first policy that genuinely requires
  taint tracking (e.g. "a value derived from a caught error reaches a client response").
- **Keep hand-rolled TypeScript-compiler-API guards.** Rejected as the default. They
  work — the current 421-line guard is correct today — but the cost is 421 lines per
  policy, TS-only, non-portable across the fleet, and four documented wrong versions
  before the correct one. Retained as the escape hatch for policies no rule engine can
  express.
- **Regex over source.** Prohibited by Principle III. Used three times in the
  motivating incident and wrong three times.

## R2: Is the comment-stripper finding still live? — YES, and it is worse than reported

Re-measured against current `staging` using **AST node positions as ground truth** (a
genuine block comment contains no code nodes). Across 357 `.ts` files, 4 files contain a
span where `src.replace(/\/\*[\s\S]*?\*\//g, '')` deletes real code.

The `+server.ts` case: line 3511 is a **line** comment reading
`// delegate to /api/workflow/tools/* which enforces ownership (FR-026)`. The `/*` inside
`tools/*` opens a fake block comment, closed 765 lines later by the `*/` inside a regex
literal `/\s*\n+\s*/g`. **A 33,904-character span — 765 lines of the hottest file in the
product, containing 6 live `console` calls — is deleted before two of the three guards
parse it.**

Half-fixed: the AST-based console scan reads original source and cites CR #2098 in a
comment. `offenders()` at line 247, feeding `NAME_EXTRACT` and `STRINGIFY_LEAK`, still
pre-strips. Those are the two guards protecting against the original #2048 row-value
leak. **This is a live defect in the proving ground and needs its own issue.**

**A methodology note that is itself a finding**: a first attempt used the TypeScript
*scanner* for ground truth and reported ~170 bogus spans across 46 files — flagging
ordinary JSDoc. That number is wrong and is recorded here only so it cannot be cited.
Hand-rolling ground truth for a correctness measurement reproduced the exact failure the
measurement was investigating.

## R3: Where does verification (US2) attach? — the aggregator

`scripts/review_plan_v2/aggregator.py` already dedups, filters by `path_instructions`,
and tiers by severity. Verification is a stage in that pipeline, after dedup (so a claim
is verified once, not once per reviewer that raised it) and before tiering.

Open question for Phase 1: the checkability classifier. Options are (a) ask the reviewer
to self-declare a machine-checkable claim in its structured output, or (b) classify
post-hoc from finding text. (a) is cheaper and more reliable but changes the reviewer
contract; (b) is retrofittable. **Leaning (a)**, because the gold set shows the false
findings are already highly structured ("X returns shape Y", "predicate P does not match
node N") and a reviewer that must name its claim is a reviewer that must commit to
something falsifiable.

## R4: Ordering — already half-built

`orchestrator.py` already runs gitleaks sequentially first (able to halt the run), then
markdownlint/actionlint/shellcheck in parallel, then reviewers. The gap is that this
ordering is implicit in code rather than a declared contract, so nothing stops the next
gate being added at the wrong tier. Phase 1 makes the portfolio a declared table with
tier, blocking policy, order, and failure-proof reference per gate.

Structural rules slot into the existing analyzer wave — zero LLM cost, parallel-safe,
and they short-circuit reviewers on failure per Principle-driven FR-012.

## R5: Manifest coverage — the provenance mapping already exists

Each vendored speckit skill declares `metadata.author: "github-spec-kit"` and
`metadata.source: "templates/commands/<name>.md"` in frontmatter. The manifest hashes one
file (`constitution-template.md`). Extending it to hash every file with a declared
`source` is mechanical and needs no new metadata.

Still to read before designing the drift report: Cole Medin's `rules-check-drift` skill
(`github.com/coleam00/skills`), which solves the same problem shape.

## R6: Constitution — RATIFIED

Was the unfilled template; ratified at v1.0.0 with seven principles, each tied to a named
incident. Zero placeholder tokens remain (verified by scan). Unblocks the Constitution
Check for this and every future plan in the trunk. Satisfies the first half of SC-001.

## Open questions carried into Phase 1

1. Checkability classification — reviewer self-declares (preferred) vs post-hoc.
2. What executes a verification claim safely? Running arbitrary reviewer-suggested code
   is a sandboxing question, not just a design one.
3. Whether the structural-rule set lives in the trunk and propagates, or per-repo with a
   shared base. Leaning shared base + per-repo overlay, mirroring the spec-kit decision.

## T051 — prior art: Cole Medin's `rules-check-drift`

Read 2026-08-16 (`coleam00/skills`, `.claude/skills/rules-check-drift/SKILL.md`)
before designing the drift report, as T051 requires.

**What it is.** A skill that checks whether `CLAUDE.md`/`AGENTS.md` is still
*true* after a change set: stale rules, drifted architecture-map paths, new
invariants worth adding. Output is three sections — *Fix (now false)* as a
Where/What's-wrong/Minimal-fix table, *Add (new invariant only)*, and
**"Checked, still true — no edit"**.

**ADOPTED:**

1. **The "checked, still true" section.** This is the important one and it is
   the same principle this spec is built on: reporting what was VERIFIED, not
   only what failed. Without it, "no drift" and "nothing was examined" print
   identically. Our report lists the pristine files by count and names the
   unverifiable ones.
2. **An explicit no-drift sentence** rather than empty output. Silence is the
   failure mode; a positive statement is not.
3. **Naming the location and the minimal action per row.** A drift report that
   says "3 files differ" sends the reader to diff everything.
4. **Advisory by default** — report, never auto-apply. Ours exits non-zero so CI
   can gate, but it never edits a vendored file.

**REJECTED, with reasons:**

1. **Its semantic judgement.** "Is this rule still true?" is a question only a
   model can answer, and routing it to one is correct there. Ours is "do the
   bytes match the manifest", which is DETERMINISTIC — constitution Principle
   III forbids sending it to a reviewer, and sha256 answers it in milliseconds
   with no false positives. Same word, different question.
2. **"Lean by default — when in doubt, suggest nothing."** Right for prose
   advice, wrong here. A vendored file we cannot classify is exactly what must
   be reported (FR-004); staying quiet about it is the defect this portfolio
   exists to close.
3. **Its scope** (`CLAUDE.md`/`AGENTS.md` only). Ours is the vendored spec-kit
   surface: `.specify/templates/`, `.specify/scripts/`, `.claude/skills/`.
