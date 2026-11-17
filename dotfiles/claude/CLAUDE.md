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
- **A green test proves nothing until you have seen it go red.** For any test whose job is to prove a guard holds, break the guard, run the test, confirm it FAILS, restore. Ten seconds. Vacuity hides in the test DOUBLE, not the assertion: a fake that filters, slices, shallow-copies, or models a state the real system cannot be in silently removes the very condition under test, and reading the test will not reveal it. A *partial* red is information — if breaking the guard fails 1 of 4 assertions, find out why the other 3 did not care. (2026-08-25: three vacuous tests in one session, every one caught by review rather than by me.)
- **A check whose failure is indistinguishable from its success is not a check.** The single most expensive lesson in this portfolio — most of the gate defects logged in `scripts/vendor-gate-defect-log.md` and `scripts/preflight-vendor-review-defect-log.md` are that one defect wearing different clothes. So when you write a bound, write the case that runs the clock past it *and* the one that lands exactly on it. When you write an `exit 0`, write the case where the thing you ran failed. When you write an escalation, write the fixture that refuses the first signal. When a script expands an environment variable it did not set, ask what happens when it is absent, because your own shell will never tell you. When you grep for a string to prove a message is right, check the wrong message does not contain it too.
- **When a test could not catch a defect, the vacuity is almost always OUTSIDE the assertion** — in the fixture, the harness, an inherited environment, an output mode no fixture speaks, or the assertion's anchor. Reading the test will not show it. So: when a harness merges two streams, ask whether the difference between them is what you are asserting about, and ask again one layer in, because the answer changes. When every case shares a knob, ask what interval that setting makes invisible. When the tool has a second output mode, ask which fixture has ever spoken it. When a script prints something for a HUMAN to act on, ask which assertion reads it.
- **A stated limit with no answer to "what new evidence would close this?" is a defect with a note on it**, and the note makes it read as considered. Write the limit down, then write down what would retire it. If nothing would, fix it instead.

## Scope Discipline

- Make the minimum change that satisfies the request. If the ask is to remove or strip something, remove it — do not replace it with a more elaborate alternative. (ADR-0011)
- If you believe additional machinery is genuinely needed, propose it in one sentence and wait; don't write it speculatively. (ADR-0011)
- Never re-raise a decision the user has already declined. (ADR-0011)

## Prose style (personal and client-facing drafts)

For letters, emails, client documents, and similar personal/client prose (NOT engineering artifacts like PR bodies or ADRs): no em dashes, no rhetorical triads, no "it's not X, it's Y" constructions, no AI-sounding flourishes, no closing summary paragraph. Plain declarative sentences. Quote sources verbatim with a file/line reference — if you can't cite it, don't quote it. (ADR-0011) Before such a draft goes to Jason to send, run `~/.claude/skills/writing-check/scripts/prose-check.sh FILE` (banned-phrase list plus slop-guard) and fix what it flags; add new tells Jason points out to `~/.claude/skills/writing-check/banned-phrases.txt`.

## Editing files

Use the Edit tool for interactive file modification. Ad-hoc `perl -pi` / `sed -i` stream edits on source files are forbidden — they have mangled import aliases and clobbered test files. Scripted stream edits are acceptable only inside committed, tested scripts that verify their end state and fail loudly (e.g. the template's drift re-apply). Before overwriting an existing path with Write, Read it first — creating a genuinely new file needs no prior read. (ADR-0011)

## Prefer MCP servers over CLI equivalents

When an MCP server is configured for a system, use its tools instead of the CLI. The MCPs are installed precisely to replace ad-hoc CLI calls — falling back to the CLI defeats the purpose.

- **GitHub MCP** (`mcp__github__*`) — issues, PRs, reviews, releases, branches, commits, file contents. Don't shell out to `gh` for any of these. (See ADR-0003.)
- **Sentry, Supabase, Railway, Axiom, mem0, etc.** — same rule when configured per-project.

Read tools auto-approve via the user-scope baseline (`mcp__*__get_*`, `mcp__*__list_*`, `mcp__*__search_*`); destructive/visible-action tools still prompt by design. CLI fallback only when the MCP doesn't expose what you need (e.g. `gh repo clone`, niche flags). Tool schemas may be deferred — load them via ToolSearch as needed.

## Pre-push: run the deterministic gate

Before pushing a feature branch, with the change **committed**:

```bash
BASE=main   # or `staging` on repos with a staging branch
review-plan-v2 --static-only --base "$BASE"
```

`--static-only` runs the deterministic analyzers and nothing else — gitleaks (sequential, first), markdownlint, actionlint, shellcheck, ruff, and the structural enumerator. **Nothing leaves the machine, no provider is called, no API key is billed.** Run it unpiped and read `$?` directly; a `cmd | tail` that "passed" has already shipped a red CI run.

**Do not run the tool without `--static-only`.** Its AI reviewer legs are retired (they were introduced by ADR-0008): they were billed to your own API keys for a subset of what the PR-side review finds anyway, and a full run held per-file reviewer output for every changed file in a long-lived foreground process with no concurrency guard, which kernel-panicked this machine twice on 2026-08-28. `--static-only --no-static-analyzers` is exit 2, not a clean run, because together they check nothing.

Exit codes are tiered: `0` clean, `1` actionable, `2` tool error. **Exit 0 also covers "reviewed ZERO files"** — an empty diff, or everything excluded — and those runs print a `[NOTHING REVIEWED]` banner, so read the `reviewing N of M` line rather than trusting the status, or pass `--require-changes` to make it exit 2. A clean static run prints a `STATIC ONLY` banner, because a clean static run and a clean full review otherwise print the same "No findings" body.

`.review-plan-v2.yaml` supplies `high_risk_paths`, the numeric tuning keys, `always_include_files`, and `import_aliases`, and **no path filter of any kind** — a `path_filters:` block written there is silently ignored, and an empty filter means review everything. One repo carried such a block for weeks believing it was filtered. **Confirm a filter from what a run actually reviewed, never from a config file containing the word.**

`gitleaks dir .` scans the working tree locally, including untracked and gitignored files, if you need that answer before committing. If a long local command needs a memory ceiling, `memguard -c 8 -- <cmd>` samples the process tree's RSS and kills the tree past the cap.

System deps: `brew install python@3.12 jq yq gitleaks markdownlint-cli actionlint shellcheck`. The `review-plan-v2` binary is a symlink at `~/.local/bin/review-plan-v2` → this repo's `scripts/review-plan-v2.sh`.

**CodeRabbit is not part of the pre-push gate.** The PR-side review is the review — it runs server-side between GitHub and the vendor, sees the full PR diff and prior rounds, and is a superset of anything the local CLI could produce. `scripts/preflight-vendor-review.sh` and `scripts/bounded-vendor-review.sh` and their suites stay in this repo with their defect logs, but nothing in the default workflow calls them. If you have a specific reason to run a local vendor leg, read `scripts/vendor-gate-defect-log.md` and `scripts/preflight-vendor-review-defect-log.md` first, and note the Cisco layer bars it outright in repos holding real person data or received material.

## Waiting for PR review + CI

After a clean pre-push run, open the PR. Don't merge prematurely, and don't poll synchronously — use `ScheduleWakeup` to self-pace.

1. Open the PR via `mcp__github__create_pull_request` (prompts; that's intentional for visible-action tools).
2. Self-paced poll loop via `ScheduleWakeup`. Use `mcp__github__pull_request_read` with methods `get` (mergeStateStatus), `get_status` (CI checks), `get_reviews` (submitted reviews), `get_comments` (CodeRabbit summary).
3. **Pacing:** start at 240–270s (cache stays warm), back off to 1200s if pending past 10 min.
4. **"Passing"** = all CI checks SUCCESS *and* no actionable review concerns. Style nits on docs are not blocking; logical/correctness concerns are. A green checkmark on a job that did not execute is not a pass — confirm the job ran.
5. **Actionable concerns** → STOP, summarize to the user with file paths and what's flagged. Do NOT auto-fix without confirmation.
6. **Clean** → merge with `mcp__github__merge_pull_request` (`merge_method: "squash"` unless the repo prefers otherwise). Never delete the branch — preserve feature branches and never `--delete-branch` long-lived branches like `main`/`staging`.
7. After merge: `git checkout main && git pull` (or whichever base branch), report the merge SHA.

**Batch the review round.** When addressing review findings, first enumerate EVERY unresolved comment in a table (comment / real bug yes-no / planned fix), then fix all the real ones in ONE commit — never fix-and-push per finding. Before pushing the batch, re-verify the behaviors fixed in earlier rounds of the same PR so a hardening pass doesn't regress them (this exact failure has happened: a round-3 fix reintroduced a parsing bug that cost a follow-up PR). (ADR-0011)

**Round-count signal:** on round 3+, something is off — surface the open findings to the user and let them decide, rather than grinding through more rounds. On 2026-09-01 a 229-line script took twenty-plus rounds and this sentence did not fire once, so treat it as a real threshold rather than a nudge: **a bound that depends on the bounded party spotting it is not a bound.**
