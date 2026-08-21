# Quickstart — working with the gate portfolio

Audience: anyone adding or changing a quality gate here or in a downstream repo.

## Install

```bash
brew install ast-grep            # 0.45.1+ — the structural enumerator
# existing deps unchanged: gitleaks markdownlint-cli actionlint shellcheck
```

## Which gate does my question need?

This is the whole design, and getting it wrong is what cost five review rounds on
2026-08-13.

| Your question | Gate | Cost |
|---|---|---|
| "Did I get **all** the sites?" | structural rule | free |
| "Is there a secret / syntax error here?" | existing analyzer | free |
| "Is this code, which I can read, wrong?" | reviewer | LLM |
| "Does this API really behave that way?" | **verification**, not a gate you add | free |

If you are reaching for a reviewer to answer a completeness question, stop — Principle III
forbids it, and the reviewer cannot enumerate code it was never shown.

## Add a structural rule

### 1. Write the fixture first

The fixture is the failure proof. It must contain, for every construct the rule claims to
cover, both a positive and a negative shape.

**Non-negotiable minimum** (FR-008), because each of these has already broken a real
scanner in this fleet:

```ts
// multi-line, own-line argument, TRAILING COMMA   <- broke scanner v1 (7 live sites)
console.error(
  'ctx:',
  e,
);

// commented-out decoy                              <- must NOT match
// console.error('x:', e);

/* block-commented decoy */                         // <- must NOT match

// a line comment containing /* ... like /api/tools/*   <- broke scanner v2 (765-line span)
console.error('after the fake opener:', e);         // <- must MATCH

// already-remediated call                          <- must NOT match
console.warn('ctx:', describeThrown(e).errMessage);

// non-caught identifier inside a catch block       <- must NOT match
console.error('ctx:', modelId, describeThrown(e).errMessage);
```

That last one exists because the first fixture written for `raw-caught-to-logger` passed
7/7 while being unable to detect the rule's real defect. Every positive control paired the
caught value only with string literals, so no non-caught identifier ever appeared inside a
catch block. **A fixture that only contains shapes your rule already handles proves
nothing.**

#### Derive the shape list — do not recall it (FR-008a)

The list above is a floor, not the method. The method is mechanical, because the failure
mode is *author recall*: whatever shapes you can bring to mind are approximately the
shapes your gate already handles. That is how three separate guards in this fleet passed
their own controls while broken, including the schema written for this spec.

Read the shape list off the gate's decision structure instead:

- **Structural rule** — count the constraints in the rule YAML. Each `inside`, `has`,
  `follows`, `regex`, and metavariable unification is one constraint. Write one negative
  per constraint that violates *exactly that one* and satisfies all the others. For
  `raw-caught-to-logger` (2 constraints: inside-a-logger-call, is-the-catch-binding) that
  is 2 near-misses — a caught value passed to a non-logger, and a non-caught identifier
  passed to a logger. The second is SHAPE 12, and it was the one missing.
- **Schema invariant** — for every field named in an `if`, cover the field **absent** in
  addition to every value in its domain. Omission is a distinct shape from explicit null,
  and JSON Schema's `if` does not fire on an absent property unless `required` says so.
  Testing `claim: null` and stopping there is what left the FR-002 guard fully bypassable.
- **Scanner over source** — one negative per formatting axis the language permits, not per
  axis you have seen: line breaks, trailing commas, argument position, comment context.

Both counts are machine-readable, so this is checkable rather than aspirational: the proof
validator counts constraints and counts negatives, and rejects a proof with fewer
negatives than constraints. If deriving the list feels like busywork on a rule you
understand well, note that every author in this fleet's incident record understood their
rule well.

### 2. Write the rule

Start from `rules/raw-caught-to-logger.yml`. Three things that are not obvious:

- **Metavariables unify across relations.** Binding `$ERR` in the match target and again
  in a relational constraint requires them to be the same text. This is what separates
  "an identifier inside a catch block" (wrong — matches `modelId`, `idx`, `toolCallId`)
  from "the catch clause's binding" (right).
- **Scope is part of the policy.** `files:` / `ignores:` are not an afterthought. The
  `raw-caught-to-logger` rule flagged a real `console.error(..., e)` that turned out to be
  correct, because its file starts with `export const ssr = false` and never runs
  server-side.
- **Scope also silently voids your fixture.** `files:` filters explicit paths, not just
  directory walks. A fixture at a path matching no glob produces **zero findings and
  exit 0** — indistinguishable from a passing rule. That is not hypothetical: it is what
  the first version of this rule's own proof did, for a month, while
  `rules/README.md` documented the inert command as the way to check your work
  (measured 2026-08-14). Fixtures are therefore directory trees at scoped paths, with at
  least one deliberately out-of-scope file holding a genuine violation.

### 3. Prove it can fail

Two artifacts, because they prove different things. The fixture test proves the rule
matches the right **shapes**; the failure proof proves the **gate** moves an exit code.
Every silent-degradation incident in this fleet had a check whose logic was fine and
whose exit code never moved.

```bash
python -m pytest tests/unit/test_structural_rules.py -q   # shapes + scope: SET EQUALITY
bash tests/proofs/<id>.sh                                 # seeded violation => red, restore => green
```

Assert **set equality** between the lines you marked `// sg-expect` and the lines the
rule reports — not "every positive was found". A rule that matches every identifier
satisfies the latter perfectly. And do not point `ast-grep scan` at a fixture path by
hand to check your work; see the third bullet above.

Record the proof script as the gate's `failure_proof`. SC-004 verifies by **running**
it, not by reading it, so a proof that is prose rather than a command is not a proof.

### 4. Register it

```yaml
- id: structural.raw-caught-to-logger
  tier: deterministic
  blocking: blocks          # deterministic gates may block
  order: 20                 # must be below every cost:llm gate
  cost: free
  rule: rules/raw-caught-to-logger.yml
  failure_proof: tests/proofs/raw_caught_to_logger.sh
```

The registry validates against `contracts/gate-registry.schema.json` at load. A dangling
`failure_proof`, a probabilistic gate set to `blocks` without `acceptance`, or an
LLM-cost gate ordered before a free one all fail the load rather than degrading quietly.

## Add a probabilistic gate (reviewer)

It enters **advisory**. Always. Promotion to `blocks` needs an `acceptance` block citing
runs and accepted-finding count — you cannot argue it through, and the schema will reject
the registry without it.

## Make a reviewer finding verifiable

Reviewers self-declare a falsifiable claim. If your finding asserts something checkable,
say what and how:

```json
{
  "body": "describeThrown() may return undefined for errMessage",
  "claim": {
    "kind": "return_shape",
    "subject": "web/src/lib/server/describe-thrown.ts:describeThrown",
    "expected": "errMessage?: string | undefined",
    "check": { "method": "typecheck", "input": "DescribeThrownResult" }
  }
}
```

That claim is refuted in milliseconds, and the finding never reaches you. It has been
raised — wrongly — in three independent runs, which is why prompt tuning is not the fix.

Findings resting on judgment carry `claim: null`, render normally, and are **not**
penalized for being unverifiable. Design opinions are the reviewer's actual job.

## Adding a policy to a downstream repo

Shared base rules live in `rules/` here and propagate via `propagate-skill.sh`. Repo-specific
scope belongs in the repo's own overlay — same split as spec-kit vendoring: never edit the
propagated rule in place, or you lose the ability to take the next update.

## Promoting a gate from advisory to blocking (T044)

FR-014 permits a probabilistic gate to block **only with measured acceptance**.
Not "it seems good now" — a number, in the registry, that someone can check.

### Why the bar is here

The failure this prevents is documented in this repo's own history: markdownlint
entered with a 2541-finding baseline, and a gate that fails a build on 2541
pre-existing findings is a gate people route around within a week. Once routed
around, its *real* findings are lost too. Advisory tiering exists so a noisy
gate can earn trust without spending it first.

The counter-case matters just as much. **At a baseline of zero the reasoning
does not apply**, and all six deterministic gates entered blocking on day one:
a report-only check over a clean baseline is where checkers go to die, and
there is no backlog to grant amnesty to.

### The procedure

1. **Run advisory for long enough to have data.** Findings still print and are
   still real; they just do not set a failing exit code, and an `[ADVISORY]`
   notice says so on every run that has them.

2. **Read the acceptance counts.** Recorded per run, counts only (FR-021):

   ```python
   from review_plan_v2.telemetry import acceptance_for
   acceptance_for("reviewer.correctness")   # {"runs": n, "raised": n, "addressed": n}
   ```

   `addressed` is fed from round-memory suppression, which fires only when the
   flagged code **changed** between rounds. That is the closest observable
   proxy for "the developer agreed": a finding that keeps coming back untouched
   is one they declined to act on. Whether a finding was any good is a fact
   about what happened next, so it cannot be measured inside a single run.

3. **Decide on the rate, and be honest about the sample.** `n=5` is not a
   measurement — the constitution says so about model tiering and the same
   arithmetic applies here. A gate whose findings are acted on a third of the
   time is a gate that fails builds two thirds of the time for nothing.

4. **Record it in `gates.yml`.** Both fields, or the schema refuses the file:

   ```yaml
   - id: reviewer.correctness
     tier: probabilistic
     blocking: blocks
     promoted_at: "2026-09-01"
     acceptance:
       runs: 40
       accepted: 31
       measured_through: "2026-08-28"
   ```

   `promoted_at` must be a **date, not null** — `required` checks presence, not
   non-nullness, and a `promoted_at: null` gate would otherwise satisfy the
   schema and block anyway. `accepted` may not exceed `runs`; an impossible
   ratio that validates is worse than one that crashes, because it promotes.

5. **Expect the short-circuit.** A blocking gate declared `deterministic` stops
   the run before any provider is called (FR-012). Promoting a **deterministic**
   gate therefore changes what later gates even get to see.

### Demoting

Same edit in reverse, and it is not a defeat — a gate that has started producing
noise should go back to advisory rather than be deleted or bypassed. Clear
`promoted_at` and `acceptance` when you do, so the next promotion has to cite
fresh numbers rather than inheriting stale ones.

## Vendored spec-kit files: never edit in place (T057)

`./setup.sh` re-runs `specify init`, which **overwrites** everything under
`.specify/templates/`, `.specify/scripts/`, and the `speckit-*` skills in
`.claude/skills/`. An edit made directly to one of those files survives until
the next update and then vanishes, with no error.

### Check before you update

```bash
python3 scripts/speckit_drift.py          # exit 1 if anything drifted
```

It classifies every vendored file as `pristine`, `modified`, `missing` or
`untracked`, and names each one. `untracked` counts as NOT clean: a file the
manifest never recorded cannot be classified, and a drift checker that reports
success for files it never examined is worse than none.

### The overlay pattern

Do not edit the vendored file. Put your change beside it and let the vendored
copy stay pristine, so the next update applies cleanly and your change survives:

- **Skills** — add a new skill (`review-plan-v2`, not a patched `review-plan`).
  Locally authored skills carry **no `source:` frontmatter**, which is exactly
  how the drift checker tells yours from upstream's.
- **Templates and scripts** — keep the override in a repo-owned path and
  reference it, rather than patching the vendored file.

### If you must edit in place

Record it, or the next manifest rebuild will bake the edit in as "pristine" and
the file most at risk becomes the quietest:

```json
"local_edits": [".specify/templates/plan-template.md"]
```

The checker then reports it on every run, and a rebuild carries the entry
forward — `local_edits` is a human judgement that hashing cannot recover once
the edit is baselined.

### After a spec-kit update

```bash
python3 scripts/speckit_drift.py --rebuild "$(jq -r '.speckit_version // .version' .specify/init-options.json)"
```

Run this **immediately after** `specify init`, never at an arbitrary moment —
rebuilding records whatever is on disk as the new baseline, so rebuilding on top
of an unrecorded local edit is how that edit stops being visible.
