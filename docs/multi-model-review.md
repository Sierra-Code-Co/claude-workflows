# Multi-model review: don't let the author grade the homework

Both review tools in this repo exist because of one principle: **code written by Claude should not be reviewed only by Claude.** A model reviewing its own output shares the blind spots that produced the bugs. Every review gate here routes to models from *other* vendors; Anthropic is deliberately absent from the reviewer cascade even though Anthropic models write most of the code.

There are two tools because there are two moments to review:

| | `/review-plan` (v1) | `review-plan-v2` |
| --- | --- | --- |
| Reviews | spec.md + plan.md (design, before code) | the git diff (code, before push) |
| When | Between `/speckit.tasks` and `/speckit.implement` | Before every push |
| Form | Bash script, parallel calls to OpenAI + Google models | Python orchestrator (`scripts/review_plan_v2/`, stdlib only) behind a thin bash entrypoint |
| Output | GREEN / YELLOW / RED, with critique | Findings, CodeRabbit-compatible: same flags, same exit codes |
| On failure | YELLOW/RED requires explicit human approval to continue | Exit 1 = actionable findings; fix before pushing |

## v1: the plan gate

`scripts/review-plan.sh` sends the spec and plan to two external models in parallel and aggregates their verdicts. It needs `OPENAI_API_KEY` + `GEMINI_API_KEY` in `.env` (see `.env.example`). The interesting design choice is social, not technical: the gate's output is a **rating with teeth** — the pipeline stops on YELLOW/RED until a human reads the critique. A review that can't stop anything is a suggestion box.

## v2: local diff review

`review-plan-v2` is a drop-in replacement for `coderabbit review --plain --base main` — same flag shape, same exit-code semantics (0 clean / 1 actionable / 2 tool error / 3 cost cap / 5 strict-config) — that runs entirely on your own API keys, so there are no vendor rate limits and nothing leaves your machine except the model calls you configured.

Architecture, in review order:

1. **Deterministic analyzers first** — gitleaks (always first: never send a diff containing a secret to an LLM), then markdownlint, actionlint, shellcheck, ruff as file types warrant. Free checks short-circuit LLM spend: a deterministic failure means you fix and re-run before any tokens burn.
2. **Four specialized LLM reviewers** — security, correctness, tests, consistency — each with a narrow charter, run against the diff via a DeepSeek broad pass.
3. **A cascade on high-risk paths** — files matched by `.review-plan-v2.yaml` also go to OpenAI and Google models for a second and third opinion.

The portfolio is *declared*, not implicit: `gates.yml` lists every gate with three mechanically-enforced invariants — each gate's `failure_proof` must reference a real file demonstrating the gate can fail; free gates order before LLM gates; and a probabilistic gate may only block merges once its acceptance rate has been measured. The registry refused a placeholder proof path during its own rollout; that refusal is documented in the file because "the registry would not let me lie to it" is the design working.

## Lessons that are now load-bearing

These are baked into the code because each one was paid for:

**A cascade leg is only real if it answers.** For three months, one cascade leg failed 136 out of 136 calls — while every run's summary still reported the leg as "called." Verdicts on high-risk paths looked triple-checked and were single-checked. v2 now prints a `[DEAD-LEG]` banner when a leg contributes nothing, and the rule is: treat a clean verdict on that leg's paths as unproven until the leg is fixed. Generalization: **any pipeline that reports participation instead of results will eventually lie to you.**

**Exit 0 must not mean "reviewed nothing."** `coderabbit`'s exit contract makes 0 cover both "clean" and "empty diff / everything path-filtered." v2 keeps the contract for compatibility but prints a `[NOTHING REVIEWED]` banner naming the cause, and offers `--require-changes` to turn that case into exit 2. Check the `reviewing N of M` line, not the exit code.

**A check that reports to nobody is indistinguishable from no check.** The v2 test suite existed for months before it ran anywhere but "whichever laptop happened to run it by hand." It's in CI now (`.github/workflows/tests.yml` — the workflow's header comment tells the story).

**Completeness questions don't go to LLMs.** "Did I update *all* the call sites?" is unanswerable by a reviewer that was never shown the whole repo — and it's exactly the kind of question a probabilistic reviewer will confidently answer anyway. Those checks are `ast-grep` structural rules in `rules/`, deterministic and milliseconds-cheap. Each rule ships with a fixture *tree* (not a single file) proving it matches what it must and ignores what it must — because the first version validated its rule against a fixture at a path outside the rule's scope globs: zero matches, exit 0, a proof that proved nothing.

**Parse `.env`, never source it.** The entrypoint reads the repo's `.env` with a strict KEY=VALUE parser and an allowlist of exportable names. Sourcing would execute `$(…)` planted in the file; the allowlist also drops `PATH`, `LD_PRELOAD`, and `PYTHONPATH` so a hostile `.env` can't hijack the interpreter.

## Setup

```bash
# system deps
brew install python@3.12 jq yq gitleaks markdownlint-cli actionlint shellcheck

# make it a command
ln -s "$(pwd)/scripts/review-plan-v2.sh" ~/.local/bin/review-plan-v2

# keys: DEEPSEEK_API_KEY required; OPENAI_API_KEY / GEMINI_API_KEY enable the cascade.
# Put them in the target repo's .env or your shell env.

# then, before any push:
review-plan-v2 --plain --base main
```

`--agent` swaps plain text for NDJSON if you're piping findings into other tooling. Fix what it surfaces locally; the goal is for any PR-side review bot to converge in one or two rounds because the catchable issues never reached the PR.
