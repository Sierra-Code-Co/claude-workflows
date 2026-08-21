# Feature Specification: /review-plan v2 — Parallel Multi-Agent Local Code Review

**Feature Branch**: `001-review-plan-v2`
**Created**: 2026-04-27
**Status**: Draft
**Input**: User description: "review-plan v2: parallel multi-agent local code review tool that replaces coderabbit review CLI as the pre-push gate. Uses the user's own LLM API keys (no vendor rate limits) with a multi-model adversarial cascade. Reads path_instructions from .coderabbit.yaml so review behavior is project-aware. Runs static analyzers (gitleaks, markdownlint, actionlint, shellcheck) in parallel on changed files at zero LLM cost. Specialized parallel review agents: security, correctness, tests, cross-doc consistency. Aggregator dedups overlapping findings, applies path_instructions filtering, tiers by severity, outputs CR-style structured findings. Auto-pause-after-N consecutive trivial reviews. Drop-in interface mirrors coderabbit review --plain --base main syntax. Goal: 1-2 PR-side rounds, not 4-5; no rate limits; no vendor lock-in."

## Background

The user currently runs `coderabbit review --plain --base main` before pushing feature branches. CodeRabbit's CLI is rate-limited on the Pro plan (hit twice in a single working session). The PR-side CR bot remains useful as a safety net, but the pre-push CLI is the single highest-leverage step in the new workflow (collapses 4-5 PR-side review rounds to 1-2). Losing it to rate limits is unacceptable.

The existing `/review-plan` skill calls `scripts/review-plan.sh` for a multi-model peer review of a *plan + spec* before implementation. v2 generalizes this idea to **diff review**: review actual changed code (not just plans) using the same multi-model approach, but tuned for the pre-push code-review use case.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Pre-push code review with no rate limits (Priority: P1)

A developer finishes a feature branch and wants to catch issues before opening a PR. They run a single command from the repo root. Within ~2 minutes they get CR-style structured findings on the diff against their base branch — same kind of catches CodeRabbit would surface (SDK string contracts, race conditions, missing error handling, contract drift between docs and code). The tool uses the developer's own LLM API keys, so there are no vendor rate limits, no daily caps, and no surprise paywalls — just the developer's API spend.

**Why this priority**: This is the core value proposition. Without rate-limit-free pre-push review, the new workflow degrades to the old "5 PR-side rounds" pattern observed in audit data. Every other capability builds on this.

**Independent Test**: Run `./scripts/review-plan-v2.sh --base main` on a branch with known issues (e.g., a deliberately introduced race condition or wrong-cased SDK string). Verify the tool surfaces those issues in under 2 minutes and produces no rate-limit errors. Compare findings against running `coderabbit review --plain --base main` on the same diff.

**Acceptance Scenarios**:

1. **Given** a feature branch with 500 changed lines and a base of `main`, **When** developer runs `./scripts/review-plan-v2.sh --base main`, **Then** findings are output in under 2 minutes with no rate-limit errors.
2. **Given** the developer has only a `DEEPSEEK_API_KEY` and no other provider keys, **When** they run the tool, **Then** the review runs successfully against the available provider with a clear note about which others were skipped.
3. **Given** the developer runs the tool 10 times in 10 minutes, **When** each run completes, **Then** none of the runs fail due to vendor-imposed rate limits.

---

### User Story 2 — Specialized parallel reviewers find a wider class of issues (Priority: P1)

Instead of one general-purpose reviewer, the tool runs multiple specialized reviewers in parallel — each with a focused system prompt. A security reviewer looks for auth, injection, OWASP, and secrets-handling issues; a correctness reviewer looks for logic bugs, race conditions, contract drift, and SDK string contracts; a tests reviewer evaluates coverage, mock-vs-real-interface match, and assertion quality; a cross-doc consistency reviewer compares CHANGELOG / spec / code / PR description / CLAUDE.md for drift. Results are aggregated, deduped, and tiered. The developer sees a wider class of issues than a single-prompt reviewer would catch, in roughly the same wall-clock time as a single-prompt reviewer would take.

**Why this priority**: Specialization is the second-biggest lever. Audit data showed CodeRabbit catches things Claude self-review misses precisely because CR's prompts are domain-specialized (e.g., the `'UserCancelled'` PascalCase catch). Single-prompt review tools blur these specializations.

**Independent Test**: Run the tool on a diff that contains issues only one specialization would catch (e.g., a SQL injection that a security reviewer would flag but a correctness reviewer would not). Verify all the specialized reviewers actually run, and the aggregator correctly attributes the finding to the right specialization.

**Acceptance Scenarios**:

1. **Given** a diff with exactly one security issue, **When** developer runs the tool, **Then** the security reviewer flags it and other reviewers do not duplicate the same finding.
2. **Given** a diff where two reviewers independently flag the same line, **When** the aggregator processes findings, **Then** the output shows one finding per line with both reviewer attributions.
3. **Given** the user has 4 reviewers configured, **When** the tool runs, **Then** wall-clock time is roughly equal to the slowest single reviewer (parallelism), not their sum (sequential).

---

### User Story 3 — Project-aware review via existing CodeRabbit config (Priority: P1)

A repo already has a `.coderabbit.yaml` with `path_instructions` (e.g., "skip prose nits on `**/*.md`"; "flag DB schema changes in `src/db/schema.ts`"). The tool reads that file at startup and applies the matching instructions to its reviewers. The developer doesn't maintain two configs — the same `.coderabbit.yaml` drives both pre-push (this tool) and PR-side (CodeRabbit's bot). Findings on `**/*.md` files are filtered the way the yaml requests; findings on tagged paths get domain-specific scrutiny.

**Why this priority**: Without this, every repo would need two config files maintained in lockstep — drift would be inevitable. Reusing `.coderabbit.yaml` makes the tool a true drop-in for the CR CLI.

**Independent Test**: Set up a `.coderabbit.yaml` with a `**/*.md` path_instruction that says "skip prose style nits." Make a diff that contains a markdown prose-style issue. Run the tool and verify the prose nit is suppressed (filtered) while real issues still surface.

**Acceptance Scenarios**:

1. **Given** a `.coderabbit.yaml` with a `**/*.md` path_instruction "skip prose nits", **When** review runs on a diff containing a prose nit and a broken markdown link, **Then** only the broken link is reported.
2. **Given** a repo without a `.coderabbit.yaml`, **When** review runs, **Then** the tool falls back to a sensible default profile and reports the absence as informational (not as an error).
3. **Given** a `.coderabbit.yaml` with a `path_filters` block excluding `node_modules/**`, **When** review runs on a diff that touches `node_modules/`, **Then** files under `node_modules/` are not reviewed.

---

### User Story 4 — Drop-in CLI that mirrors CodeRabbit's interface (Priority: P2)

The developer (and any Claude Code session reading the global CLAUDE.md "Pre-push" section) should be able to swap `coderabbit review --plain --base main` for the new tool with minimal change. Same flags where reasonable: `--plain` for plain-text output, `--base <branch>` for base comparison, `--type all|committed|uncommitted` for diff scope. Output format mirrors CR's plain-text findings closely enough that downstream tooling, scripts, and conditioning on output don't break.

**Why this priority**: The whole rollout (claude-speckit-template + Tier 1/2/3) currently references `coderabbit review` in the Phase 6 self-review and global CLAUDE.md. A drop-in replacement is a 1-line edit in those places; a non-drop-in is a fan-out edit across the propagation chain.

**Independent Test**: Replace `coderabbit review --plain --base main` with the new tool's equivalent invocation in the global CLAUDE.md "Pre-push" section. Run a Phase 6 self-review on a real feature. Verify nothing breaks downstream.

**Acceptance Scenarios**:

1. **Given** the existing global CLAUDE.md "Pre-push" instructions, **When** the only change is replacing `coderabbit review` with the new tool's name, **Then** the workflow still works end-to-end.
2. **Given** a script that pipes the tool's output to `grep` or processes it line-by-line, **When** the script ran successfully against `coderabbit review --plain` output, **Then** it should also run successfully against this tool's `--plain` output.

---

### User Story 5 — Static analyzers run in parallel for free (Priority: P2)

Before (or alongside) the LLM passes, the tool runs deterministic static analyzers on the relevant changed files: `gitleaks` for secrets, `markdownlint` for `**/*.md`, `actionlint` for `.github/workflows/**/*.yml`, `shellcheck` for `**/*.sh`. These cost zero LLM tokens, complete in seconds, and catch a class of issues (leaked secrets, syntax errors, lint violations) that LLMs sometimes miss or hallucinate. Their findings flow into the aggregator alongside LLM findings.

**Why this priority**: Cheap, fast, deterministic. Catches secrets-leak class issues that are critical and that LLMs cannot reliably detect. CR bundles the same set; matching that bundle is part of being a true drop-in.

**Independent Test**: Add a fake AWS credential string to a file in the diff. Run the tool. Verify gitleaks catches it before any LLM finding lands.

**Acceptance Scenarios**:

1. **Given** a diff with a leaked AWS access key, **When** review runs, **Then** gitleaks flags it as a critical/security finding within ~10 seconds (before LLM passes complete).
2. **Given** a static analyzer is not installed on the user's machine, **When** review runs, **Then** the tool emits a warning and skips that analyzer rather than failing.
3. **Given** a diff containing only `.md` and `.sh` files, **When** review runs, **Then** `actionlint` is not invoked (no relevant files) and `markdownlint` + `shellcheck` are.

---

### User Story 6 — Adversarial multi-model cascade for high-risk paths (Priority: P3)

By default, reviewers run on a cheap broad-pass model (e.g., DeepSeek R1). For changes touching high-risk paths flagged in `.coderabbit.yaml` (e.g., `src/lib/server/db/schema.ts`, `infra/**`, `*/auth/**`), the tool spawns a second-opinion review on a higher-quality model (e.g., Claude Sonnet) for the security and correctness reviewers. Findings that BOTH models flag are tagged "high-confidence." Findings only one model raises are tagged "single-source" so the developer can weigh them appropriately.

**Why this priority**: Reduces hallucination risk on the catches that matter most. Lower-priority because the cheap model's signal is usually sufficient; the cascade is a quality lever for repos where wrong calls have outsized cost.

**Independent Test**: On a diff touching a configured high-risk path, run review and verify the security/correctness reviewers each produced findings from two distinct model identifiers, and that "high-confidence" / "single-source" tags appear correctly.

**Acceptance Scenarios**:

1. **Given** a diff touching `src/db/schema.ts` (configured as high-risk), **When** review runs, **Then** security and correctness reviewers each run on both the broad-pass and quality models.
2. **Given** both models flag the same finding, **When** the aggregator outputs it, **Then** it's tagged "high-confidence."
3. **Given** only the broad-pass model flags a finding, **When** the aggregator outputs it, **Then** it's tagged "single-source" with a hint that the user can re-run with the quality model if uncertain.

---

### User Story 7 — Auto-pause-after-N to suppress noise on iterative pushes (Priority: P3)

If the developer pushes the same branch repeatedly with only nit-tier changes, the tool detects that the previous N (default 3) consecutive runs produced only nits and informational findings — and on the next run, suppresses LLM passes entirely (still runs static analyzers, since they're free). The developer sees a one-line "no new substantive changes since last review; skipping LLM passes" notice. The feature is opt-out via `--force-full`.

**Why this priority**: Quality-of-life feature for iterative work. Catches the same anti-pattern that PR-Agent's `auto_pause_after_reviewed_commits` addresses — repeating expensive review when nothing changed. Lower priority because users can manually skip.

**Independent Test**: Run review 3 times on commits that change only whitespace. Verify the 4th run skips LLM passes by default and that `--force-full` overrides this.

**Acceptance Scenarios**:

1. **Given** the previous 3 review runs on this branch produced 0 actionable findings, **When** developer runs review again with no flag, **Then** LLM passes are skipped and a notice is printed.
2. **Given** the previous 3 runs produced actionable findings, **When** developer runs review, **Then** all reviewers run normally.
3. **Given** auto-pause has triggered, **When** developer adds `--force-full`, **Then** all reviewers run regardless.

---

### Edge Cases

- **Empty diff**: Tool exits cleanly with "no changes to review" message; doesn't burn LLM tokens.
- **Massive diff (>10k lines)**: Tool chunks the diff by file group and reviews chunks in parallel; warns if individual files exceed model context windows.
- **Binary files in diff**: Excluded from LLM review (LLMs can't meaningfully review binary blobs); flagged as "binary, not reviewed" in output.
- **Generated files (lock files, dist/)**: Respected per `.coderabbit.yaml` `path_filters`; default exclusions match common patterns.
- **API key missing for one provider**: Tool runs on available providers and notes the absent ones; doesn't fail the whole run.
- **Network failure to one provider mid-run**: Partial results returned; failed-provider findings noted as missing rather than silently dropped.
- **Repo without `.coderabbit.yaml`**: Falls back to a sensible default profile; emits one informational note about the absence.
- **Static analyzer not installed**: Tool prints "{tool} not found, skipping" and continues; doesn't fail the run.
- **Branch and base are the same / no commits to review**: Same as empty diff — clean exit with informational message.
- **Detached HEAD or no upstream**: Tool prints a clear error explaining the state and what flags to pass to disambiguate.
- **`.coderabbit.yaml` is invalid YAML**: Tool emits a parse error pointing to the offending line and falls back to defaults; doesn't silently apply broken config.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The tool MUST accept a `--base <branch>` flag and review changes on the current branch relative to that base. Default base is the repo's `origin/HEAD` if it can be detected, otherwise `main`.
- **FR-002**: The tool MUST run multiple specialized reviewers (security, correctness, tests, cross-doc consistency) in parallel rather than as a single monolithic review.
- **FR-003**: The tool MUST support DeepSeek-compatible API and an Anthropic API as its default LLM providers, selected via configuration. SHOULD support additional OpenAI-compatible and Gemini APIs as future extensions; these are not in MVP and are explicitly deferred per research.md R-7.
- **FR-004**: The tool MUST read `.coderabbit.yaml` at the repo root if present and apply its `path_filters` and `path_instructions` to the review.
- **FR-005**: The tool MUST run deterministic static analyzers (`gitleaks` always; `markdownlint`, `actionlint`, `shellcheck` per applicable changed files) in parallel and incorporate their findings.
- **FR-006**: The tool MUST aggregate findings from all reviewers and analyzers, dedup overlapping ones (same file/line/category from multiple sources collapse to one finding with multiple source attributions), and tier each finding by severity.
- **FR-007**: The tool MUST output structured findings with at minimum these fields: `file`, `line` (or `line_range`), `severity` (one of: `actionable`, `nit`, `info`), `category` (one of: `bug`, `security`, `style`, `docs`, `consistency`, `secrets`), `message`, and `source` (which reviewer/analyzer produced it).
- **FR-008**: The tool MUST work without any vendor-imposed rate limits beyond what the user's own LLM API quotas impose.
- **FR-009**: The tool MUST gracefully degrade when a provider is unavailable (missing API key, network failure, quota exhaustion). Affected reviewers are skipped with a clear note; remaining reviewers complete normally.
- **FR-010**: The tool MUST distinguish "actionable" findings from "nit" findings in its output, so callers can filter (e.g., gate merges on actionables only).
- **FR-011**: The tool MUST be invokable as both a Claude Code skill (`/review-plan` or equivalent) AND a standalone shell command (`./scripts/review-plan-v2.sh` or similar binary).
- **FR-012**: The tool MUST mirror CodeRabbit CLI's flag interface where possible: `--plain` for plain-text output, `--base <branch>`, `--type all|committed|uncommitted`. Other flags MAY be added as needed but the existing ones MUST work the same way.
- **FR-013**: The tool's `--plain` output MUST be parse-compatible with downstream tooling that consumes `coderabbit review --plain` output (line format, severity prefixes, file:line conventions).
- **FR-014**: The tool MUST exit with a non-zero status code when actionable findings are produced and zero when only nits/info are produced (so it can gate pre-push hooks). **Auto-pause** (no LLM run because previous N runs were trivial) MUST exit 0 with an informational notice on stdout — auto-paused state is not a "block push" condition.
- **FR-015**: The tool MUST log all LLM API calls (provider, model, token counts, latency) to a local log file for cost tracking and debugging — but NOT log diff contents (to respect any sensitive data in the diff).
- **FR-016**: The tool SHOULD support an adversarial multi-model cascade for high-risk paths. High-risk-path configuration lives in a **separate v2-owned config file** (`.review-plan-v2.yaml` at repo root), NOT as an extension to `.coderabbit.yaml`. The second-opinion model runs only on findings/files matching configured patterns; findings flagged by both models receive a "high-confidence" tag. Rationale: `.coderabbit.yaml` is CR's schema; we cannot extend it without breaking compatibility (FR-004 requires honoring it as-is).
- **FR-017**: The tool SHOULD support auto-pause-after-N: if the previous N consecutive runs on the same branch produced 0 actionable findings, skip LLM passes on subsequent runs (still run static analyzers) until either N is configurable or the user passes `--force-full`. Default N=3.
- **FR-018**: The tool MUST handle diffs with binary files by excluding them from LLM review and reporting them as "binary, not reviewed."
- **FR-019**: The tool MUST handle the empty-diff case (no changes vs base) by exiting cleanly with an informational message and consuming no LLM tokens.
- **FR-020**: The tool MUST chunk large diffs (>N lines per file, where N is provider-context-aware) into reviewable segments and run reviewers per chunk, then aggregate.
- **FR-021**: The tool SHOULD support a cost cap (`--max-cost-usd <float>`) that aborts the run before invoking LLM providers if the estimated cost (based on token-count heuristic × provider per-token pricing) exceeds the cap. Aborted runs exit with a distinct code (3) and surface the estimate vs. cap to stderr. Used in CI mode where runaway cost on large diffs is a real risk.

### Key Entities

- **Diff**: The set of files and hunks changed on the current branch relative to the configured base. May include binary files, generated files (excluded per `path_filters`), and content of any size.
- **Reviewer**: A specialized review perspective with a focused system prompt and an LLM model assignment. Examples: `security`, `correctness`, `tests`, `consistency`. Configurable to add or remove perspectives.
- **Static Analyzer Run**: An invocation of a deterministic tool (`gitleaks`, `markdownlint`, `actionlint`, `shellcheck`) against a subset of changed files, producing structured findings.
- **Finding**: An issue identified by one or more reviewers/analyzers. Attributes: `file`, `line` or `line_range`, `severity`, `category`, `message`, `source(s)`, `confidence` (high/single-source).
- **Configuration**: Project-level settings drawn from `.coderabbit.yaml` (`path_filters`, `path_instructions`, profile, high-risk path patterns) plus tool-level settings (model selection per reviewer, parallelism, auto-pause-N, log paths).
- **Run**: A single invocation: diff capture + analyzers + reviewers + aggregator + output. Represents one logical "review event," with a unique ID for log/cost tracking.

### Assumptions

- The user has at least one valid LLM provider API key in their environment or `.env` file. The tool degrades gracefully if some are missing but cannot operate with zero providers.
- The user has `git` available and is in a git working tree. The tool does not need to handle non-git directories.
- The user has at least one supported static analyzer installed (gitleaks recommended for secrets detection); missing analyzers are gracefully skipped **with an explicit warning** in output (silent skip would create false confidence — particularly dangerous for `gitleaks`).
- The user's `.coderabbit.yaml` (if present) is the same one used by the PR-side CodeRabbit bot. The tool reads it as-is; it does not extend the schema. v2-specific config (high-risk path patterns, max-concurrency, etc.) lives in a separate `.review-plan-v2.yaml` file.
- For Claude Code integration, the tool is invoked from the working directory of the repo being reviewed. CWD-detection is acceptable.
- Diff size for typical use is <10k lines; diffs larger than that are uncommon and acceptable as a degraded experience (chunking + warnings).
- The tool runs on the user's local machine; no remote execution is in scope for v2.
- LLM cost is the user's responsibility; the tool surfaces token counts but does not enforce caps.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 80%+ catch parity vs CodeRabbit CLI on the same diff: across N=10 representative pre-push diffs from companion-ai and claude-workflows, the tool catches at least 80% of the issues CR's `--plain` output flagged as actionable.
- **SC-002**: Total review wall-clock time under 2 minutes for diffs up to 1000 lines on the user's typical hardware (recent MacBook Pro, broadband internet), measured as average over N=10 runs.
- **SC-003**: Total cost per review under $0.20 USD on default config (DeepSeek R1 broad-pass + cascade-on-high-risk) for diffs up to 1000 lines, averaged over a sample of 20 runs.
- **SC-004**: Zero rate-limit errors over 100 consecutive runs (vs CodeRabbit CLI's observed rate-limit hits in 1 working session).
- **SC-005**: After adoption, PR-side CR review converges in 1-2 rounds (matching the pre-push CR CLI baseline established by claude-workflows PRs #9, #10), validated across 10 follow-on PRs.
- **SC-006**: Static analyzer findings (deterministic tools) appear in the output within 10 seconds of tool invocation, before LLM passes complete.
- **SC-007**: When invoked via the global CLAUDE.md "Pre-push" instruction, the tool produces equivalent workflow outcomes to the prior `coderabbit review --plain --base main` invocation, with no edits required to downstream Phase 6 self-review checklists.
- **SC-008**: The tool completes successfully (no errors, partial results when applicable) on edge cases: empty diff, binary-only diff, missing API key for one provider, missing static analyzer binary, repo without `.coderabbit.yaml`, network failure mid-run.
- **SC-009**: Output is parseable by the existing tooling that consumes `coderabbit review --plain` output: zero downstream-script breakage when swapping the underlying tool.
- **SC-010**: After enabling auto-pause-after-N on a branch with no substantive changes, subsequent runs complete in under 10 seconds (static analyzers only; LLM passes skipped).

## Out of Scope (v2)

- **Remote execution / cloud-hosted variant**: v2 is local-only.
- **PR-side bot equivalent**: v2 doesn't post comments to GitHub PRs. CodeRabbit's PR bot remains the safety net.
- **Repo-specific learnings (RAG over past PRs)**: CR's "Based on learnings: X" pattern is hard to replicate cleanly. Out of scope.
- **Auto-fix / autofix-on-detection**: v2 reports findings; it does not modify files.
- **Custom UI / dashboard**: CLI output only.
- **Replacing the existing `/review-plan` skill that reviews specs**: That tool is for spec/plan review pre-implementation. This tool is for diff review pre-push. They serve different points in the workflow and stay separate. v1 (`scripts/review-plan.sh`) is bash and stays untouched; v2 is a Python module under `scripts/review_plan_v2/`. **No shared library across the language boundary** — the two tools have small, stable per-provider call shapes; bridging Python ↔ bash for a few HTTP-call helpers would be more complex than maintaining two thin provider modules. They MUST NOT collide on output (separate skill names, separate config files).
- **OpenAI gpt-5.3-codex and Gemini 2.5 Pro reviewers**: Available as v2 implementation hooks but **NOT in MVP**. Default config = DeepSeek R1 broad-pass + Claude Sonnet cascade only (per research.md R-7). Adding OpenAI/Gemini support is a follow-up if user demand justifies it.
- **Multi-language UI**: English-only output.
- **Commit-message review**: v2 reviews diffs, not commit messages.
- **Test runner framework**: Per claude-workflows charter, no `bats-core` / `pytest` / similar. Tests use Python stdlib `unittest` only (`python3 -m unittest discover`). Stdlib ships with Python 3.10+ — no `pip install`, no `requirements.txt`, no project-level test runner. HTTP fixtures use stdlib `http.server`.
