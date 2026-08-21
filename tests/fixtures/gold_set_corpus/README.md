# Gold-set replay corpus

Extracted from the two proving-ground diffs the 2026-08-13 comparison ran against
(jabelk/mtg-cube-ai #2099 and #2101). Trimmed to the declarations each gold-set
claim actually turns on, so the replay is **hermetic**: it needs no external
checkout, no network, and no LLM, and therefore runs identically on a laptop, in
CI, and in the container.

That last property is the point. `tests/integration/test_static_analyzers.py`
skips both of its tests in CI because gitleaks is not installed there — including
the one asserting a secret-bearing diff is never transmitted to an LLM (T005i).
A gold-set replay gated on "is mtg-cube-ai checked out at the right SHA?" would
be the same defect with a different dependency, so the corpus is vendored
instead.

What is faithful here, and what is not:

- **Faithful**: the declared shapes the claims are checked against. The real
  `describeThrown` returns `ThrownDescription { errName, errMessage, errCode }` —
  that, and not `{ name, message }`, is what refutes the finding, and it is
  reproduced exactly.
- **Trimmed**: function bodies, imports, and unrelated exports. The verifier reads
  declarations, so bodies are noise.
- **Not claimed**: that these files behave like the originals. Nothing here is
  executed. Do not cite this corpus as evidence about the proving ground's
  runtime behaviour — cite the originals.

| Corpus file | Upstream | Gold-set claims it settles |
|---|---|---|
| `web/src/lib/server/describe-thrown.ts` | same path, #2101 | G6 `return_shape` — refuted |
| `web/src/lib/server/deck-dedup.ts` | `decks.ts` comparator, #2099 | G1 (real, retained) |
| `web/src/lib/server/deck-dedup.test.ts` | added in #2099 | G2 `symbol_absent` — refuted |
| `web/src/lib/server/console-guard.ts` | `describe-thrown.guard.ts`, #2101 | G3 (deferred to `execute`), G5 (real, retained) |
| `web/src/lib/server/console-guard.test.ts` | added in #2101 | G4 `symbol_absent` — refuted |

Regenerating: these are hand-trimmed, not generated. If a claim's shape changes
upstream, update the corpus file and the fixture entry together — the replay
asserts per-finding verdicts, so a drifted corpus fails loudly rather than
quietly re-classifying a finding.
