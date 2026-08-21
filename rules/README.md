# Shared structural rules

`ast-grep` rules that answer completeness questions deterministically — "did I get
all the sites?" — in milliseconds, at zero cost, over code that is not in the diff.

A probabilistic reviewer cannot answer that question. It cannot enumerate a repo it
was never shown. Routing completeness to a reviewer is forbidden by constitution
Principle III, and the incident that earned the rule cost five review rounds and was
wrong four times.

## Layout

| Path | What |
|---|---|
| `<id>.yml` | the rule, in ast-grep's own format — deliberately not wrapped, so it stays runnable outside this harness |
| `fixtures/<id>/` | a **directory tree**, not a file: positive shapes the rule must match, near-miss negatives it must not, at paths that exercise `files:` and `ignores:` |

### Why the fixture is a tree

`files:` and `ignores:` are constraints like any other, and neither can be exercised
from a single file. Not hypothetical: the first version of `raw-caught-to-logger` was
validated against a fixture at `specs/003-gate-portfolio/rules/fixture.ts`, a path
matching **neither** scope glob — so `ast-grep scan --rule <rule> <fixture>` found
**zero shapes and exited 0**. The rule was correct; its proof was inert, and the exit
code said everything was fine. Measured 2026-08-14, and the reason this layout changed.

So a fixture tree contains at least one file that is deliberately **out of scope** and
holds a genuine violation. `tests/unit/test_structural_rules.py` proves that exclusion
is load-bearing by scanning the same bytes at an in-scope path and requiring a match
there — otherwise "no findings in the excluded file" is satisfied by a scan that finds
nothing anywhere.

A line marked with a trailing `// sg-expect` MUST be reported; every other line MUST
NOT be. The test asserts **set equality** between the two, so an over-matching rule
fails exactly as loudly as a blind one.

## Writing one

Read [`specs/003-gate-portfolio/quickstart.md`](../specs/003-gate-portfolio/quickstart.md)
first, in particular **"Derive the shape list — do not recall it"**. The short version:

- A rule with N constraints needs **N near-miss negatives**, each violating exactly one
  constraint and satisfying the rest. Derive that count from the rule file; do not
  produce it from memory. Every guard in this fleet's incident record passed the
  controls its author thought to write, while broken.
- Metavariables **unify across relations**. `$ERR` bound in the match target and again
  in a relational constraint must be the same text. This is what separates "an
  identifier inside a catch block" (wrong — also matches `modelId`, `idx`,
  `toolCallId`) from "the catch clause's binding" (right).
- `files:` / `ignores:` are **part of the policy**, not an afterthought. The first
  real-world hit for `raw-caught-to-logger` was correct code, in a file whose line 1
  is `export const ssr = false`.

## Running one

Run the fixture through pytest, not by hand — the tree has to be copied out from under
the rule's own `**/rules/fixtures/**` exclusion first, and the assertion is set
equality, which `ast-grep` alone cannot make:

```bash
python -m pytest tests/unit/test_structural_rules.py -q   # shapes + scope
bash tests/proofs/raw_caught_to_logger.sh                 # seeded violation goes red
```

Against a real checkout:

```bash
ast-grep scan --rule rules/<id>.yml <target-dir>; echo $?    # clean tree => 0
```

Do **not** point `ast-grep scan` at a fixture path directly to check your work. That is
the command that returned 0 findings and exit 0 for a month.

## Downstream

These propagate to the fleet via `scripts/propagate-skill.sh`. Repo-specific scope
belongs in the consuming repo's own overlay — never edit a propagated rule in place,
or you lose the ability to take the next update (Principle VI).
