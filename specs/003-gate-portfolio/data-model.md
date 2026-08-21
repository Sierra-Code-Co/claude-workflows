# Data Model — 003 Gate Portfolio

No database. These are in-process structures and on-disk file formats. Field names are
the contract; `contracts/` holds the machine-readable schemas.

## Gate

The portfolio's unit. Today the set of checks is implicit in `orchestrator.py`'s control
flow, which is why nothing prevents the next one being added at the wrong tier. A Gate
makes tier, ordering, and blocking policy declared data.

| Field | Type | Notes |
|---|---|---|
| `id` | str | stable slug, e.g. `gitleaks`, `structural.raw-caught-to-logger`, `reviewer.correctness` |
| `tier` | enum | `deterministic` \| `probabilistic` |
| `blocking` | enum | `blocks` \| `advisory` |
| `order` | int | ascending; ties run in parallel |
| `cost` | enum | `free` \| `llm` — drives FR-012 short-circuit |
| `failure_proof` | ref | path to the recorded proof; **required** (FR-007) |
| `health` | `GateHealth` | emitted every run, success included (FR-018) |
| `enabled_since` | date | when it entered the portfolio |
| `promoted_at` | date? | null while advisory; set only with `acceptance` |
| `acceptance` | `Acceptance`? | required to set `blocking = blocks` on a probabilistic gate |

**Invariants** (enforced at registry load, not by convention):

1. `tier == probabilistic` ⇒ `blocking == advisory` unless `acceptance` is present (FR-013/014).
2. `failure_proof` MUST resolve to an existing, runnable proof. A dangling reference fails the load.
3. All `cost == free` gates MUST have lower `order` than any `cost == llm` gate (FR-012).
4. A gate MUST NOT be *reportable* without `health`. `health` is per-run output, so it is
   absent at registry-load time and attached when the gate runs; the renderer MUST refuse
   to emit a result for a gate whose `health` is unset rather than rendering it as clean.
   (Originally written as "not constructible", which was impossible — a gate cannot be
   constructed before its first run. Caught by review-plan-v2 on this PR.)

### GateHealth

| Field | Type | Notes |
|---|---|---|
| `ran` | bool | distinguishes "found nothing" from "never ran" |
| `skipped_reason` | str? | non-null iff `ran == false` |
| `calls_attempted` | int | 0 for deterministic gates |
| `calls_succeeded` | int | |
| `dead_legs` | list[str] | a provider that answered zero times; forces non-zero exit (SC-010) |
| `dropped_context` | list[str] | what was cut for budget (FR-011) |

`GateHealth` is rendered on every run. A run in which any gate has `ran == false` without
a `skipped_reason`, or a non-empty `dead_legs`, is not a clean run.

### Acceptance

| Field | Type | Notes |
|---|---|---|
| `runs` | int | sample size |
| `accepted` | int | findings the developer acted on |
| `measured_through` | date | |

Exists so "promote to blocking" cannot be argued; FR-014 requires citing it.

## Finding

Extends the existing aggregator finding with the verification fields US2 needs.

| Field | Type | Notes |
|---|---|---|
| `gate_id` | str | provenance |
| `file`, `line` | str, int | |
| `severity` | enum | existing |
| `body` | str | existing prose |
| `claim` | `Claim`? | null when the finding rests on judgment |
| `verdict` | enum | `confirmed` \| `refuted` \| `unverifiable` \| `unchecked` |

**Rendering rules**:

- `refuted` ⇒ never rendered (FR-002).
- `unverifiable` and `unchecked` ⇒ rendered with an explicit marker (FR-003). `unchecked`
  means verification itself failed or timed out — it MUST NOT silently render as
  `confirmed`, which is the Principle I failure mode applied to this stage.
- `claim == null` ⇒ `verdict = unverifiable`, rendered normally, **not penalized**
  (FR-002's third clause). Design judgments are the reviewer's job.

### Claim

The reviewer's falsifiable assertion, self-declared in structured output (research R3,
option (a)). A reviewer that must name its claim must commit to something checkable.

| Field | Type | Notes |
|---|---|---|
| `kind` | enum | `symbol_exists` \| `symbol_absent` \| `return_shape` \| `predicate_result` \| `count` |
| `subject` | str | symbol, file, or expression the claim is about |
| `expected` | str | what the reviewer asserts is true |
| `check` | `Check` | how to falsify it |

The five `kind`s are drawn from the gold set, not invented — every false finding measured
on 2026-08-13 was `return_shape` (the `describeThrown` recurrence), `predicate_result`
(the AST predicate claim), or `symbol_absent` ("no tests exist").

### Check

| Field | Type | Notes |
|---|---|---|
| `method` | enum | `enumerate` \| `typecheck` \| `execute` |
| `input` | str | rule id, symbol path, or snippet |

`execute` is the sandboxing question carried into Phase 1 (research R3, open question 2).
Until it is resolved, `execute` claims resolve to `unverifiable` rather than running
anything. **`enumerate` and `typecheck` alone refute all three checkable-false gold-set
findings**, so SC-002 does not depend on `execute` shipping.

## StructuralRule

An `ast-grep` YAML rule. The on-disk format is ast-grep's own — deliberately not wrapped,
so rules stay portable and runnable outside this harness.

| Field | Source | Notes |
|---|---|---|
| `id` | rule YAML | becomes `structural.<id>` as the Gate id |
| `language` | rule YAML | |
| `files` / `ignores` | rule YAML | policy scope. The `ssr = false` case in research R1 proves scope is part of the policy, not an afterthought |
| `severity` | rule YAML | |
| fixture | sibling `.ts`/`.py` | the failure proof (see below) |

**Fixture requirement** (FR-008): a rule's fixture MUST contain, for each construct the
rule claims to cover, both a positive and a negative shape — including at minimum a
commented-out decoy and a construct *following* a comment containing `/*`. This clause
exists because the first fixture written for `raw-caught-to-logger` passed 7/7 while
being unable to detect the rule's real defect: every control paired the caught value only
with string literals, so no non-caught identifier ever appeared inside a catch block.

## FailureProof

| Field | Type | Notes |
|---|---|---|
| `gate_id` | str | |
| `seed` | str | the violation introduced |
| `expected` | str | the red result |
| `shapes` | list[str] | distinct input shapes covered (FR-008) |
| `verified_at` | date | |

Stored beside the gate. Executable, not prose — SC-004 requires *running* each proof, not
inspecting the record. A proof that cannot be run is not a proof.

## VendoredFile / OverlayFile

| Field | Type | Notes |
|---|---|---|
| `path` | str | local path |
| `source` | str | upstream path, read from existing `metadata.source` frontmatter |
| `upstream_version` | str | the pin |
| `hash` | str | content hash at vendoring time |
| `status` | enum | `pristine` \| `modified_locally` |

`status` is derived, never stored — computed by comparing current content to `hash`. This
is the whole of US7: today the manifest stores one hash, so `modified_locally` is
undetectable for the other files and the skills forked invisibly.

`OverlayFile` carries `path` and `composes_over` (a `VendoredFile.path`) and is never
hashed against upstream — it is ours by construction.

## Relationships

```text
Gate 1──1 GateHealth          (emitted per run)
Gate 1──1 FailureProof        (required; dangling ref fails registry load)
Gate 0──1 Acceptance          (required iff probabilistic AND blocking)
Gate 1──* Finding             (provenance)
Finding 0──1 Claim ──1 Check  (null Claim ⇒ verdict = unverifiable, rendered)
Gate 0──1 StructuralRule      (for tier=deterministic, id prefix "structural.")
VendoredFile 0──* OverlayFile (composes_over)
```
