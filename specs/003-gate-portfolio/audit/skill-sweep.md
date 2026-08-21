# US8 — silent-failure sweep of `.claude/skills/` and `scripts/`

**2026-08-16.** The question for every site: *when this degrades, is the result
distinguishable from success?* Not "does it handle the error" — handling it
quietly is the defect.

## Method, and a false clean result on the way

An AST scan found **33 swallowed handlers** in `scripts/` (`except …:` whose body
is exactly `pass`, `continue`, or `return`). I then wrote a heuristic to sort
them into signalled vs silent, and it reported **0 silent out of 33**.

That is an implausibly clean result, and this repo's own rule is to distrust
exactly that. The heuristic was junk in two ways: `documented = "#" in above`
matched *any* comment within five lines, and the signal check scanned the whole
enclosing function for words like "skip" or "warn". Both accept nearly
everything. The sweep was redone by reading all 33 sites.

Recording it because it is the same failure the sweep is looking for — a check
that passes for a reason unrelated to what it claims — produced by the tooling
written to find it.

## Findings

### F1 (HIGH, CONFIRMED — **FIXED in this change, not filed**)

*An analyzer that exits 0 with unparseable JSON reads as clean.*

`markdownlint.py:26`, `ruff.py:84`, `shellcheck.py:33` — `except
json.JSONDecodeError: return []`. `actionlint.py:43` is the per-item variant.

Measured, not argued:

```text
exit 0 + malformed JSON -> skipped=False  findings=0  reason=''
=> INDISTINGUISHABLE FROM CLEAN
```

T005e/#38 fixed the neighbouring case — `base.run()` now reports SKIPPED when a
tool exits non-zero *and* returns nothing. This is the half that fix does not
cover: **exit 0 with garbage on stdout**. Reachable from a truncated write, a
tool whose JSON schema changed between versions, or output interleaved with a
warning. The gate then covers nothing while reporting clean, which is this
portfolio's founding defect.

**Fix.** `parse_output` now raises `AnalyzerOutputError` instead of returning
`[]`, and `base.run()` converts that to a SKIPPED result carrying the reason.
Both properties, not a trade: the wave still survives one broken analyzer, and
the gap is visible. Valid JSON of the WRONG SHAPE raises too — it parsed, so the
decoder never objected, and an upstream schema change lands exactly there.

The test that guarded the old behaviour said "A crash here takes down the whole
analyzer wave. Degrade to empty." Half right, and worth keeping as a record: not
crashing the wave is correct, degrading to `[]` is not. It now asserts the
corrected property, and a companion test pins that the wave survives.

Filed as an issue? **No — fixed here.** SC-009 asks for an issue per gap, and a
closed gap is better than a tracked one.

### F2 (MEDIUM, CONFIRMED — filed) — a reviewer's unparseable response is uncounted

`reviewers/base.py::parse_findings` ends `return []` when no candidate JSON
extraction succeeds, and `:158` drops individual malformed items with a bare
`continue`. Neither is counted anywhere.

The orchestrator's `failed_task_count` covers tasks that RAISED. A task that
returned successfully with an unparseable body is not a failure by that
measure — so "the reviewer found nothing" and "the reviewer answered with
garbage" produce identical output and an identical exit code.

Note `:117`'s `continue` is NOT a defect: it advances to the next candidate
extraction in a deliberate fallback chain.

## Classified as adequately signalled (31 sites)

Read individually; each makes its degradation observable to its caller:

| pattern | sites | why it is not silent |
|---|---|---|
| timeout → `skipped=True` + reason | `base.py:64`, `gitleaks.py:122` | the skip and its reason travel to the report |
| rule parse error → error string | `structural.py:164` | becomes a named coverage gap |
| unverifiable → `Verdict(UNVERIFIABLE)` | `verify.py:309` | rendered with a marker |
| containment failure → `False` | `paths.py:68` | fail-safe by design, documented, mutation-covered |
| HTTP error → `(code, body)` | 4 providers | the status code is inspected by the caller |
| unreadable → `None` | `related.py:71`, `rounds.py:95` | feeds `unreadable` / "not a match" |
| junk row → skip | `rounds.py:148,244`, `telemetry.py:93,103` | documented hand-edited-file tolerance |
| missing provenance → `None` | `speckit_drift.py:107` | absence of `source:` IS the answer |
| config load failure → defaults | `config.py:21` | surfaced via `config_warnings` |

## `.claude/skills/` — 12 skills

Skills are prompt documents, not executables: they have no exception handling to
audit. The relevant question is whether each one tells its caller when it could
not do its job. `review-plan/SKILL.md` is the strongest example in the repo — it
enumerates SKIPPED, empty, `UNUSABLE:` and `TRUNCATED:` leg outcomes and
requires the verdict to say a leg did not answer, including "if ALL legs are
skipped, flag it and do a manual review — never present a no-op run as a
completed review."

The nine vendored `speckit-*` skills are upstream text and out of scope for
local change (see the overlay rule in `quickstart.md`); no local silent-failure
class was found in them.

## Not filed

`auto_pause.py:134` (state write fails → the pause counter silently misses one
increment) and `diff_capture.py:57,64` (a per-file `git diff` failing is skipped)
are real but low-severity, and both fail toward MORE review rather than less.
Recorded here rather than filed, so the tracker keeps signal.
