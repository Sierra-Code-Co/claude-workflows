# Global instructions for Claude Code

These apply across every project unless a project-level CLAUDE.md overrides them.

## Decision-making

Make decisions yourself. Don't ask narrative or stylistic questions
("should I A or B?", "would you like me to also...?", "want me to add tests?").
Pick the better option, do it, and tell me what you decided in one line.

Ask only for:

- Irreversible actions (deleting files, force-pushing, dropping data, mass-rewriting history)
- External credentials or services (new API keys, paid services, signing up for things)
- External visibility (publishing, sending emails, posting issues/PRs, deploying)
- Costs beyond the existing subscription

Otherwise: complete the task end-to-end. If a task is genuinely ambiguous in scope,
ask before starting — never mid-execution.

## Communication style

- One-line decision notes are fine and preferred over long explanations.
- Skip narrative summaries unless I ask. The diff is the summary.
- Don't preview what you're about to do; just do it and report results.
- Be direct about what failed or didn't work — that's more useful than glossing.
- **Don't suggest breaks, pacing, hydration, ergonomics, or wellness.** No "you've been at this a while," no "consider taking a break," no "step away for a moment." If I want a break I'll take one. This applies even on long sessions, even after many tool calls, even when you detect fatigue signals. Skip it entirely.

## When working in parallel agent setups

If you're invoked from inside Claude Squad, Agent Orchestrator, or any
multi-agent runner, assume the other agents may be touching the same repo
on different worktrees. Work only on your assigned scope. Don't make
cross-cutting "while I'm here" changes.

## Multi-phase workflows (speckit and similar)

When running a multi-phase workflow — e.g. `/speckit.specify` →
`/speckit.plan` → `/speckit.tasks` → `/speckit.implement`, or any pipeline
of skills/commands that hand off to the next — run all phases end-to-end
without pausing for "go ahead" confirmations between them.

The skill files often end with "ready for /speckit.plan" or "next step
is X." Treat that as a marker, not a stop sign. Continue to the next
phase yourself.

Only pause if you hit a true ambiguity that blocks every reasonable
forward path — and even then, ask one focused question and continue
with a sensible default if the ambiguity is minor.

If the user says "do issue #N end-to-end" or "speckit-issue N" or
similar, they mean: run specify → plan → tasks → implement → open a
draft PR. Don't ask between phases.

## Branch & Deployment Safety

- NEVER use `--delete-branch` flag when merging PRs, especially against `staging` or other long-lived branches. Long-lived branches must persist after merge.
- Always verify branch protection rules before attempting direct pushes; expect to need sync PRs for protected branches.
- After merging to `staging`, do not delete the `staging` branch — it is long-lived.
- Before any destructive git operation (`reset --hard`, force push, branch delete), confirm the branch is not long-lived and the work is recoverable.

## Output Token Management

- Keep tool outputs and responses concise; avoid dumping large file contents or full logs into responses.
- For long log/file inspection, use `head`, `tail`, `grep`, or `wc -l` first rather than reading whole files.
- Prefer targeted Grep/Read with line ranges over reading entire large files.
- When orchestrating subagents, ask them for short reports (e.g. "under 200 words") so raw output doesn't flood the parent context.
- If a response is at risk of being long, summarize and offer to expand on demand.

## Verification Before Claiming Success

- Do not claim a fix is shipped/working until you've verified: (1) CI is green, (2) deploy completed successfully, (3) the actual symptom is resolved in the target environment.
- When the user reports something visible on their screen (e.g. PostHog events, UI state, console output), trust their direct observation over your inferred state — re-check your assumptions instead of arguing.
- After refactors, explicitly verify cleanup of related artifacts (data directories, old configs, removed routes, stale env vars) rather than assuming.
- For UI/frontend changes, exercise the feature in a browser before reporting done. Type checks and tests verify code correctness, not feature correctness.
- **Anything with a web UI gets a browser walkthrough, unprompted.** When Claude in Chrome (browser automation) is available, use it to walk the affected flows as a user would — navigate, click, fill forms, read the rendered result. API-level smoke tests verify the API, not the feature; do not substitute them for UI verification and do not wait to be asked. (ADR-0011)
- **Pipes mask exit codes.** Run gate commands (lint, format, tests) unpiped, or use `set -o pipefail` / check the first pipe stage's status (`${PIPESTATUS[0]}` in bash, `${pipestatus[1]}` in zsh) before claiming success. A `cmd | tail` that "passed" has already shipped a red CI run. (ADR-0011)
- **Verification claims carry evidence.** "Verified" means you ran the check in this session: include the exact command/query and its raw output (or link the CI run). If you didn't run it, say "NOT VERIFIED" — never infer. (ADR-0011)

## Scope Discipline

- Make the minimum change that satisfies the request. If the ask is to remove or strip something, remove it — do not replace it with a more elaborate alternative. (ADR-0011)
- If you believe additional machinery is genuinely needed, propose it in one sentence and wait; don't write it speculatively. (ADR-0011)
- Never re-raise a decision the user has already declined. (ADR-0011)

## Prose style (personal and client-facing drafts)

For letters, emails, client documents, and similar personal/client prose (NOT engineering artifacts like PR bodies or ADRs): no em dashes, no rhetorical triads, no "it's not X, it's Y" constructions, no AI-sounding flourishes, no closing summary paragraph. Plain declarative sentences. Quote sources verbatim with a file/line reference — if you can't cite it, don't quote it. (ADR-0011)

## Editing files

Use the Edit tool for interactive file modification. Ad-hoc `perl -pi` / `sed -i` stream edits on source files are forbidden — they have mangled import aliases and clobbered test files. Scripted stream edits are acceptable only inside committed, tested scripts that verify their end state and fail loudly (e.g. the template's drift re-apply). Before overwriting an existing path with Write, Read it first — creating a genuinely new file needs no prior read. (ADR-0011)

## Prefer MCP servers over CLI equivalents

When an MCP server is configured for a system, use its tools instead of the CLI. The MCPs are installed precisely to replace ad-hoc CLI calls — falling back to the CLI defeats the purpose.

- **GitHub MCP** (`mcp__github__*`) — issues, PRs, reviews, releases, branches, commits, file contents. Don't shell out to `gh` for any of these. (See ADR-0003.)
- **Sentry, Supabase, Railway, Axiom, mem0, etc.** — same rule when configured per-project.

Read tools auto-approve via the user-scope baseline (`mcp__*__get_*`, `mcp__*__list_*`, `mcp__*__search_*`); destructive/visible-action tools still prompt by design. CLI fallback only when the MCP doesn't expose what you need (e.g. `gh repo clone`, niche flags). Tool schemas may be deferred — load them via ToolSearch as needed.

## Pre-push: run review-plan-v2 locally

Before pushing a feature branch, run:

```bash
review-plan-v2 --plain --base main
```

(use `--base staging` on repos with a staging branch). This is a local-only multi-agent review that uses your own LLM API keys (`deepseek-v4-pro` broad pass + an optional OpenAI `gpt-5.5` + Google `gemini-3.1-pro-preview` cascade on `.review-plan-v2.yaml`-flagged high-risk paths). 4 specialized reviewers (security, correctness, tests, consistency) + 4 static analyzers (gitleaks-sequential-first, markdownlint, actionlint, shellcheck). No vendor rate limits.

**Anthropic is deliberately NOT in the cascade** — Claude reviewing Claude-Code-written code is the anti-self-grading violation the design exists to avoid, so setting `ANTHROPIC_API_KEY` adds no reviewer. This replaced a claim of a "DeepSeek R1 broad-pass + optional Anthropic Claude Sonnet cascade", stale on both counts as of 2026-08-13: R1 is retired (`deepseek-r1` now 400s outright, and `deepseek-reasoner` silently aliases to the cheapest tier), and the cascade moved to OpenAI + Google in #25.

**A cascade leg is only real if it answers.** The OpenAI leg failed 136/136 calls from 2026-05-09 to 2026-08-13 while every run still reported it as "called". If a run prints `[DEAD-LEG]`, that leg contributed nothing and re-running will not fix it — it means a stale model id, a rejected parameter, or a revoked key. Treat a clean verdict on that leg's high-risk paths as unproven until it is fixed.

**Drop-in replacement for** `coderabbit review --plain --base main` — same flag set, same exit-code semantics (0 clean / 1 actionable / 2 tool error / 3 cost cap / 5 strict-config). **Exit 0 also covers "reviewed ZERO files"** — an empty diff, or every file excluded by `path_filters`. Such runs print a `[NOTHING REVIEWED]` banner naming the cause; check the `reviewing N of M` line rather than trusting exit 0, or pass `--require-changes` to make it exit 2. Use `--agent` instead of `--plain` for NDJSON output to pipe to downstream tooling. Per ADR-0008.

Required: `DEEPSEEK_API_KEY`. Optional: `ANTHROPIC_API_KEY` (enables cascade on high-risk paths). System deps: `brew install python@3.12 jq yq gitleaks markdownlint-cli actionlint shellcheck`. The `review-plan-v2` binary is a symlink at `~/.local/bin/review-plan-v2` → `~/dev/projects/claude-workflows/scripts/review-plan-v2.sh`.

The entrypoint parses `<git_root>/.env` if present (strict KEY=VALUE only — never `source`s the file, so injected `$(…)` shell can't execute) and exports a hardcoded allowlist of model API keys + `REVIEW_PLAN_V2_*` config. It also reconstitutes the primary `ANTHROPIC_API_KEY` / `DEEPSEEK_API_KEY` from `*_API_KEY_FALLBACK` env vars at run-time — important if you use the Claude Code subscription-auth wrapper (`~/bin/claude` runs `env -u ANTHROPIC_API_KEY claude …`). That strip blocks v2's cascade from inside CC sessions unless you also `export ANTHROPIC_API_KEY_FALLBACK="$ANTHROPIC_API_KEY"` in your `~/.zshrc`. The wrapper doesn't touch the fallback name, so v2 reconstitutes the primary on entry.

Address what the local review surfaces before pushing. **Goal: most actionable issues caught and fixed locally, so the PR-side CodeRabbit review converges in 1–2 rounds instead of 4–5.** The PR-side CR bot remains the safety net for what the local pass missed (cross-doc consistency, spec-vs-code drift, anything that requires the full PR diff context).

Fallback: if `review-plan-v2` is unavailable on a machine, `coderabbit review --plain --base main` still works (same flag shape; CR CLI is `brew install --cask coderabbit` + `coderabbit auth login`).

## Waiting for PR review + CI

After a clean pre-push CLI run, open the PR. The PR-side CR review is the safety net for things the CLI missed (cross-doc consistency, spec-vs-code drift, anything that requires the full PR diff context). Don't merge prematurely. Don't poll synchronously — use `ScheduleWakeup` to self-pace.

Default flow:

1. Open the PR via `mcp__github__create_pull_request` (prompts; that's intentional for visible-action tools).
2. Self-paced poll loop via `ScheduleWakeup`. Use `mcp__github__pull_request_read` with methods `get` (mergeStateStatus), `get_status` (CI checks), `get_reviews` (submitted reviews), `get_comments` (CodeRabbit summary).
3. **Pacing:** start at 240–270s (cache stays warm), back off to 1200s if pending past 10 min.
4. **"Passing"** = CodeRabbit status SUCCESS *and* all CI checks SUCCESS *and* no actionable review concerns. Style nits on docs are not blocking; logical/correctness concerns are.
5. **Actionable concerns** → STOP, summarize to the user with file paths and what's flagged. Do NOT auto-fix without confirmation.
6. **Clean** → merge with `mcp__github__merge_pull_request` (`merge_method: "squash"` unless the repo prefers otherwise). Never delete the branch — preserve feature branches and never `--delete-branch` long-lived branches like `main`/`staging`.
7. After merge: `git checkout main && git pull` (or whichever base branch), report the merge SHA.

**Round-count signal:** if you find yourself on PR-side round 3+, something's off — most likely the pre-push CLI wasn't run, or the repo's `.coderabbit.yaml` differs from local CLI defaults. Surface this to the user before grinding through more rounds.

**Batch the review round.** When addressing CR findings, first enumerate EVERY unresolved comment in a table (comment / real bug yes-no / planned fix), then fix all the real ones in ONE commit — never fix-and-push per finding. Before pushing the batch, re-verify the behaviors fixed in earlier rounds of the same PR so a hardening pass doesn't regress them (this exact failure has happened: a round-3 fix reintroduced a parsing bug that cost a follow-up PR). (ADR-0011)
