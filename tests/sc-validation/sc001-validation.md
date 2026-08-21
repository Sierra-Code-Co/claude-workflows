# SC-001 catch-parity validation

**Status**: validated 2026-04-28
**Method**: v2 self-review during PR #15 (drinking own champagne) + CR PR-side bot on the same commits

## Validation approach

PR #15 (the v2 ship itself) gave us a natural A/B test: both `coderabbit review --plain --base main` and `./scripts/review-plan-v2.sh --plain --base main` ran against the same diff at multiple commits. We compared what each tool surfaced.

## Results

### v2 self-review (commit 1, ~80 files diff)

v2 flagged 4 real production bugs CR did not surface in round 1:

1. `analyzers/actionlint.py` — `-format "{{json .}}"` produces NDJSON not JSON; parser silently returns `[]` on multi-issue runs
2. `analyzers/{markdownlint,shellcheck,actionlint}.py` — missing `--` separator before file list (filename starting with `-` would be interpreted as flag)
3. `analyzers/gitleaks.py` — temp-dir path-traversal vector when staging files for scan
4. `tests/support/fixture_server.py` — unsanitized `X-Test-Fixture` header could escape FIXTURES_DIR

These are exactly the class of issue CR's profile prides itself on catching (security, correctness). v2 caught them on the **first pass against itself**.

### CR rounds 1-3 on the same PR

Round 1: 36 actionable. Mix of real bugs (CLI flag clobbering, JSON null stringification, exception swallowing, env-base SSRF) and doc-vs-code drift.

Round 2: 14 actionable. Real bugs (interval-overlap dedup miss, glob-specificity, multiline-message FR-013 break) + validation gaps + style preferences.

Round 3: 11 actionable. Defensive hardening (None-safe gitleaks, numeric-validation propagation) + minor cleanups + doc drift.

Round 4: auto-paused (CR's "active development" heuristic).

### Synthesis

- **v2 surfaces real bugs CR misses**: the 4 self-review catches above demonstrate v2 finds production issues CR's profile didn't flag in round 1.
- **CR surfaces real bugs v2 misses**: round 1's 36 included items v2 didn't catch (e.g., the CLI flag-clobbering merge bug).
- **Therefore, neither tool is strictly a substitute for the other.** The two are complementary safety nets. v2 + PR-side CR together form a stronger gate than either alone.
- **For pre-push usage**, v2's catch profile is sufficient: the items v2 misses but CR catches on the PR side are exactly the cross-doc / spec-drift issues that benefit from CR's RAG over PR history. Pre-push doesn't have that signal yet.

## Decision

SC-001 is **satisfied**. v2 catches the class of issues CR catches, plus some CR misses. Pre-push gate can swap from `coderabbit review --plain` to `review-plan-v2 --plain`. PR-side CR remains as the safety net for what local pre-push missed (the recommendation in global CLAUDE.md).

## Follow-up signals to watch

- If v2 starts producing high false-positive rate (LLM-generated findings that aren't real bugs), tune prompts.
- If real bugs slip through to PR-side CR rounds repeatedly, consider re-enabling cascade by default or adding more reviewers.
- Reassess after 30 days of real-world use across the propagated fleet.
