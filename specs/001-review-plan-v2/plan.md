# Implementation Plan: /review-plan v2 — Parallel Multi-Agent Local Code Review

**Branch**: `001-review-plan-v2` | **Date**: 2026-04-27 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-review-plan-v2/spec.md`

## Summary

Build a Claude Code skill (`/review-plan-v2`) backed by a **Python orchestrator** (`scripts/review_plan_v2/__main__.py`) that runs a parallel multi-agent code review on a `git diff <base>...HEAD`. The user-facing entrypoint `scripts/review-plan-v2.sh` is a thin bash wrapper that exec's the Python module. Reviewers run as concurrent HTTP calls to the user's own LLM APIs (DeepSeek R1 default, Claude Sonnet cascade for high-risk paths) using stdlib `concurrent.futures`. Static analyzers (`gitleaks`, `markdownlint`, `actionlint`, `shellcheck`) are invoked via stdlib `subprocess` — **gitleaks runs sequentially first**, halting the run if it finds actionable secrets, before any LLM call sees the diff (security: prevents accidental secret transmission to external APIs). An aggregator dedups overlapping findings, applies path_instructions from `.coderabbit.yaml`, tiers by severity, and outputs CR-style structured findings.

**Why Python over bash for the orchestrator** (per Gemini's round-2 review): bounded-parallelism worker pools, file locking, mock HTTP fixtures, and assertion-based testing are all native to Python's stdlib (`concurrent.futures`, `fcntl.flock`, `http.server`, `unittest`). Implementing them in bash requires re-creating these patterns from scratch — `concurrency.sh`, `mkdir`-as-mutex, `_lib.sh` assertions, an ad-hoc fixture server. That violates YAGNI. Python with stdlib only doesn't add a "build system" or "test runner" (charter compliant) — it's just a script with structure. Static analyzers stay as subprocess calls (they're CLI tools); v1's `scripts/review-plan.sh` stays bash and untouched (no risky refactor).

Drop-in interface preserved: `coderabbit review --plain --base main` becomes `review-plan-v2 --plain --base main` — same flags, same output format, no vendor rate limits.

## Technical Context

**Language/Version**: Python 3.10+ (stdlib only) for the orchestrator, aggregator, providers, tests. Bash only for `scripts/review-plan-v2.sh` (thin entrypoint that `exec`s `python3 -m review_plan_v2`).

**Primary Dependencies**:

- **LLM APIs (BYO keys), MVP set**: DeepSeek (`https://api.deepseek.com/v1/chat/completions`, model `deepseek-reasoner`); Anthropic (Messages API, model `claude-sonnet-4-6`). OpenAI and Gemini deferred per research.md R-7.
- **No shared LLM library between v1 and v2**: v1 (`scripts/review-plan.sh`, bash) is left untouched. v2 has its own Python provider clients (`review_plan_v2/providers/{deepseek,anthropic}.py`). Acceptable duplication — the call shapes are small and stable; pre-emptive sharing across a Python/bash boundary would be more complex than two ~80-line provider modules.
- **Static analyzers** (`brew install`): `gitleaks`, `markdownlint-cli`, `actionlint`, `shellcheck`. Invoked via `subprocess.run`. Optional — gracefully skipped **with explicit warning** if not installed (FR-005). **gitleaks runs sequentially before LLMs**; if it finds actionable secrets, the run halts immediately and never sends the diff to external APIs (security fix from Gemini review).
- **Python stdlib only** — no `requests`, no `pyyaml`, no `pytest`. HTTP calls via `urllib.request`. YAML parsing via `subprocess` to `yq` (already in our deps for command-line YAML use; avoids adding `pyyaml`). Concurrency via `concurrent.futures.ThreadPoolExecutor`. Locking via `fcntl.flock`. Tests via `unittest`.
- **`jq`** for shell-side JSON output construction (still useful in the bash entrypoint).
- **`yq`** (mikefarah's go binary) for `.coderabbit.yaml` and `.review-plan-v2.yaml` parsing — invoked via `subprocess`.
- **`git`** (assumed present) for diff capture.

**Storage**: None persistent for diff/finding data. Temp files in `tempfile.mkdtemp()` per run, cleaned via context manager. Optional `~/.claude/review-plan-v2/auto-pause-state.json` for auto-pause-after-N tracking (FR-017). State-file locking uses **`fcntl.flock`** — kernel auto-releases on process exit (including `kill -9`), no stale-lock issue. PID + timestamp also recorded in state file as a defense-in-depth check (warn if a lock has been held for > 60s without progress).

**Testing**: Python stdlib `unittest` for everything (`tests/test_*.py`), invoked via `python3 -m unittest discover tests/`. **No test runner framework** (`bats-core`/`pytest`) per claude-workflows charter — `unittest` is stdlib, ships with Python, isn't a "test runner" in the project-sense. Provider mocking via `unittest.mock.patch` against `urllib.request.urlopen`, OR via env-var-driven base URL pointing at `http.server` fixture (preferred for integration tests since it exercises the full HTTP path). `shellcheck --severity=warning` as a pre-commit gatekeeper for the thin bash entrypoint.

**Target Platform**: macOS + Linux developer workstations. No Windows support (matches existing `scripts/review-plan.sh`).

**Project Type**: Single-project (CLI tool + Claude Code skill). No frontend/backend split.

**Performance Goals**: < 2 min wall-clock for 1000-line diffs (SC-002); static analyzers complete in < 10s (SC-006); cost < $0.20/run on default config (SC-003).

**Constraints**: Must respect `.coderabbit.yaml` `path_filters` and `path_instructions` (FR-004). Must gracefully degrade on missing providers/analyzers with explicit warnings (FR-009). Must never log diff content (FR-015). Must exit non-zero when actionable findings exist (FR-014, for pre-push hook gating); auto-pause exits 0 with informational notice. Static analyzers MUST receive explicit changed-file lists (not whole-repo scans); shell-out commands MUST quote file paths to prevent injection. Concurrency capped via `--max-concurrency <n>` (default 4) to prevent reviewer × chunk × provider explosion on large diffs.

**Scale/Scope**: Diffs up to ~10k lines (chunked per FR-020); 10–100 review runs/day/developer; up to 4 LLM reviewers + 4 static analyzers in parallel.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

claude-workflows' `.specify/memory/constitution.md` is the unfilled template — no project-specific principles ratified. Falling back to the generic Testing Philosophy and Quality Gates from the template:

| Constitution Item | Plan Compliance | Notes |
|---|---|---|
| TDD required | ✅ Test fixtures (canned diffs with known findings) before reviewer prompts; `unittest` test files written before module impl | Phase 2 task ordering enforces this |
| Tests cover all acceptance criteria from spec | ✅ Each User Story P1–P3 maps to a `tests/integration/test_*.py` case backed by a fixture diff | See data-model.md mapping |
| Tests independent and deterministic | ⚠️ LLM calls are non-deterministic by nature — `tests/support/fixture_server.py` (stdlib `http.server`) returns canned responses keyed by fixture name; `unittest.mock.patch` covers fast-path units | Live-provider integration test runs locally only, not CI |
| Pre-Commit gate (lint clean, no secrets) | ✅ `shellcheck --severity=warning` clean for the thin bash entrypoint; `gitleaks` clean repo-wide; `python3 -m py_compile` succeeds for all modules | Self-applied during dev |
| Pre-Merge gate (all CI green, self-reviewed) | ✅ Standard claude-workflows workflow | Pre-push CR CLI; PR-side CR safety net |
| Release gate (acceptance criteria verified) | ✅ Spec checklist + manual smoke test on real PRs | Validation per SC-001 |

**No constitution violations.** Python stdlib `unittest` is not a "test runner framework" in the charter sense (it ships with Python; no `pytest`/`bats-core`/`pip install` step). Tests being non-deterministic on the LLM-call layer is unavoidable; the `http.server` fixture preserves determinism for CI.

## Project Structure

### Documentation (this feature)

```text
specs/001-review-plan-v2/
├── plan.md              # This file (/speckit.plan output)
├── spec.md              # Already exists (/speckit.specify output)
├── research.md          # Phase 0 output (this command)
├── data-model.md        # Phase 1 output (this command)
├── quickstart.md        # Phase 1 output (this command)
├── contracts/           # Phase 1 output (this command)
│   ├── cli-flags.md         # CLI flag contract — mirrors `coderabbit review --plain`
│   ├── output-format.md     # Plain-text output format contract — parse-compatible with CR
│   └── finding-schema.md    # Internal Finding object schema
├── checklists/
│   └── requirements.md  # Already exists
└── tasks.md             # Phase 2 output (separate /speckit.tasks command)
```

### Source Code (repository root)

```text
scripts/
├── review-plan-v2.sh                       # 5-line bash entrypoint: exec python3 -m review_plan_v2 "$@"
└── review_plan_v2/                         # Python module (stdlib only, no setup.py)
    ├── __init__.py                         # version, public API
    ├── __main__.py                         # CLI entrypoint: argparse + main()
    ├── orchestrator.py                     # main run loop: diff → analyzers (sequential) → reviewers (parallel) → aggregator → output
    ├── diff_capture.py                     # git diff capture, chunking, base-ref detection (origin/HEAD → main → master → develop → staging chain)
    ├── change_manifest.py                  # cross-file context for consistency reviewer (added/removed/renamed files + per-file changed-symbol regex extraction)
    ├── config.py                           # parse .coderabbit.yaml (read-only) + .review-plan-v2.yaml; CLI flag merging
    ├── auto_pause.py                       # state file I/O with fcntl.flock; PID/timestamp defense-in-depth
    ├── concurrency.py                      # ThreadPoolExecutor-backed bounded-parallelism with --max-concurrency cap
    ├── output_format.py                    # plain-text + agent NDJSON renderers; golden-file comparison helper
    ├── aggregator.py                       # dedup (configurable line window), severity tiering, path_instructions filter
    ├── providers/
    │   ├── __init__.py
    │   ├── deepseek.py                     # urllib-based DeepSeek client; subshell error-guard equivalent: try/except around urlopen
    │   └── anthropic.py                    # urllib-based Anthropic Messages API client
    ├── reviewers/
    │   ├── __init__.py
    │   ├── base.py                         # Reviewer ABC: name, prompt_path, model, run(diff_chunk, manifest=None) -> List[Finding]
    │   ├── security.py                     # Security reviewer (DeepSeek + optional Anthropic cascade)
    │   ├── correctness.py
    │   ├── tests.py
    │   └── consistency.py                  # Receives ChangeManifest as cross-file context
    ├── analyzers/
    │   ├── __init__.py
    │   ├── base.py                         # StaticAnalyzer ABC; runs subprocess, parses output → List[Finding]
    │   ├── gitleaks.py                     # MUST run sequentially before any LLM call
    │   ├── markdownlint.py
    │   ├── actionlint.py
    │   └── shellcheck.py
    └── prompts/
        ├── security.md                     # System prompts (markdown for easy editing)
        ├── correctness.md
        ├── tests.md
        └── consistency.md                  # Includes ChangeManifest placeholder

.claude/skills/review-plan-v2/
└── SKILL.md                                # Thin Claude Code skill wrapper that invokes scripts/review-plan-v2.sh
                                            # (existing /review-plan skill stays — handles spec/plan review, separate workflow)

tests/
├── __init__.py
├── fixtures/                       # Canned diffs with known findings
│   ├── 01-clean.diff
│   ├── 02-pascalcase-bug.diff      # SDK string contract catch
│   ├── 03-sql-injection.diff       # security agent specialization
│   ├── 04-secret-leak.diff         # gitleaks catches secret pre-LLM
│   ├── 05-large-diff.diff          # FR-020 chunking
│   ├── 06-binary-file.diff         # binary excluded
│   ├── 07-empty-diff.diff          # clean exit
│   ├── 08-cross-doc-drift.diff     # consistency agent (cross-file rename)
│   ├── 09-detached-head/           # detached HEAD edge case
│   ├── 10-no-upstream/             # no `origin/HEAD` configured
│   ├── 11-malformed-yaml.diff      # invalid .coderabbit.yaml falls back to defaults
│   ├── 12-malicious-filename.diff  # shell-injection guard test (file named `; rm -rf ~.txt`)
│   ├── golden/                     # real `coderabbit review --plain` output samples for FR-013 parse-compat verification
│   │   └── *.txt
│   └── responses/                  # Canned provider responses keyed by fixture name + provider
├── support/
│   ├── __init__.py
│   ├── fixture_server.py           # http.server-based mock for DEEPSEEK_API_BASE/ANTHROPIC_API_BASE
│   └── runner.py                   # helpers to invoke `python3 -m review_plan_v2` as a subprocess and capture stdout/stderr/exit
├── unit/                           # `python3 -m unittest discover -s tests/unit`
│   ├── __init__.py
│   ├── test_aggregator.py          # dedup window, severity tiering, path_instructions filtering
│   ├── test_diff_capture.py        # base-ref chain, binary exclusion, chunking thresholds
│   ├── test_change_manifest.py     # added/removed/renamed file detection, symbol regex extraction
│   ├── test_config.py              # .coderabbit.yaml + .review-plan-v2.yaml + CLI merge precedence
│   ├── test_auto_pause.py          # state-file read/write under fcntl.flock, --force-full bypass
│   ├── test_concurrency.py         # max-concurrency cap honored under load
│   ├── test_output_format.py       # plain text + agent NDJSON renderers; golden-file parse-compat
│   ├── test_providers_deepseek.py  # mocked urlopen — request shape, error handling
│   └── test_providers_anthropic.py # mocked urlopen — request shape, error handling
└── integration/                    # `python3 -m unittest discover -s tests/integration`
    ├── __init__.py
    ├── test_happy_path.py
    ├── test_path_instructions.py
    ├── test_degraded_provider.py
    ├── test_auto_pause_e2e.py
    ├── test_cli_flags.py
    ├── test_output_format_golden.py     # asserts plain-mode parse-compat against tests/fixtures/golden/
    ├── test_exit_codes.py
    ├── test_static_analyzers.py         # gitleaks-sequential-first; halts run on actionable secrets
    ├── test_cascade.py
    ├── test_detached_head.py
    ├── test_malformed_yaml.py
    ├── test_shell_injection.py          # file named `; rm -rf ~.txt` does not get exec'd
    └── test_concurrency_cap.py
```

**Structure Decision**: Reuse the existing `scripts/review-plan.sh` skill-shape (one entrypoint script + supporting code) but namespace v2 separately as `scripts/review_plan_v2/` to avoid colliding with v1 (which reviews specs/plans pre-implementation, not diffs pre-push). Both skills coexist with separate prompts and output formats. Per the spec's Out of Scope item: "Replacing the existing /review-plan skill that reviews specs: NOT replaced. They share infrastructure; they MUST NOT collide on output."

v1 (`scripts/review-plan.sh`) stays bash and untouched — refactoring it carries risk and zero user-visible payoff. v2 is greenfield Python (stdlib only) for the orchestrator, providers, reviewers, analyzers, aggregator, and tests. The thin `scripts/review-plan-v2.sh` bash entrypoint exists solely so the global CLAUDE.md "Pre-push" instruction can read `review-plan-v2 --plain --base main` (drop-in for the current `coderabbit review --plain --base main`).

The Claude Code skill at `.claude/skills/review-plan-v2/` is a thin wrapper — its job is to invoke the bash entrypoint with the right CLI args, not re-implement orchestration in markdown.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No violations from the generic constitution gates. Two **complexity choices worth flagging**:

| Choice | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Separate `review-plan-v2/` namespace alongside existing `review-plan` | Spec's Out of Scope: "MUST NOT collide on output" with existing `/review-plan` | Refactoring v1 to also handle diffs would conflate two distinct workflows (spec review pre-implementation vs. diff review pre-push), confuse users, and require breaking changes to v1's `/review-plan` skill that 11+ projects already depend on |
| Python orchestrator (vs. all-bash like v1) | Bounded-parallelism pools, file locking, mock HTTP fixtures, and assertion-based tests are stdlib-native in Python (`concurrent.futures`, `fcntl.flock`, `http.server`, `unittest`); reproducing them in bash means writing `concurrency.sh`, `mkdir`-as-mutex, an ad-hoc `_lib.sh` assertion harness, and a separate fixture server. That violates YAGNI and was the architectural concern flagged RED in Gemini's round-2 review | Pure bash matched v1's shape but at the cost of ~3× more lines, fragile concurrency primitives (race conditions on `mkdir`-as-mutex under load), no kernel-released locks (stale lock if `kill -9`), and integration tests that would need a separate Python fixture server anyway. Python with stdlib only adds zero install steps over bash (Python 3.10+ ships on macOS 13+ and all supported Linux distros) and zero new dependencies (no `pip install`). It is not a "build system" or "test runner framework" in the claude-workflows charter sense |

## Phase 0: Outline & Research

Generated `research.md` resolves these unknowns (R-1 through R-9):

1. **DeepSeek R1 API contract** — endpoint, auth header, exact model name (`deepseek-reasoner` for R1), response shape (Chat Completions style with `choices[0].message.content`), reasoning-output handling (R1 separates reasoning from final answer; we want only the final answer in findings).
2. **Anthropic Claude API for cascade** — Messages API with `claude-sonnet-4-6`; system prompt + user message structure; `max_tokens` budget per cascade reviewer (8192 to match v1 pattern).
3. **Test approach** — Python stdlib `unittest` only; mock provider HTTP via env-var-driven base URL pointing at a `tests/support/fixture_server.py` (`http.server`-based) for integration tests, `unittest.mock.patch` for fast-path units. No `pytest`/`bats-core`.
4. **`.coderabbit.yaml` parsing** — `yq` (mikefarah's go binary) invoked via `subprocess`. Required hard dep (Homebrew `brew install yq`); avoiding `pyyaml` keeps the project at zero `pip install` dependencies.
5. **Auto-pause state locking** — `fcntl.flock` on the state file. Kernel auto-releases the lock on process exit (including `kill -9`), eliminating stale-lock concerns. PID + timestamp also recorded as a defense-in-depth check.
6. **Diff chunking** — line-count threshold (default 1500 lines/chunk) + per-hunk grouping; rough token estimate gate to keep each chunk comfortably under DeepSeek R1's 64k context.
7. **Issue #13 reconciliation** — v2 default is DeepSeek R1 broad + Claude Sonnet cascade. OpenAI and Gemini deferred from MVP per spec FR-003 (SHOULD, not MUST). v1 (`scripts/review-plan.sh`) keeps OpenAI + Gemini for spec/plan review; v2 uses different providers for diff review and they don't need to share a bash library.
8. **Sequential gitleaks-first** — gitleaks runs in the orchestrator before any LLM HTTP call; on actionable secret detection, the run halts with exit 1 and the diff is never sent to external APIs (security fix from Gemini round-2 review).
9. **Concurrency cap** — `concurrent.futures.ThreadPoolExecutor(max_workers=N)` where N defaults to 4 (configurable via `--max-concurrency`). Prevents the reviewer × chunk × provider explosion on large diffs that would otherwise trip provider 429s.

## Phase 1: Design & Contracts

**Prerequisites**: research.md complete.

1. **Extract entities** → `data-model.md`:
   - `Diff` — set of changed files + hunks vs base; binary-aware
   - `Reviewer` — name, system prompt path, model assignment, role (security/correctness/tests/consistency)
   - `StaticAnalyzerRun` — name, command, applicable file globs, output-to-finding parser
   - `Finding` — `{file, line_or_range, severity, category, message, source[s], confidence}`
   - `RunConfig` — model selection, parallelism, auto-pause-N, log paths (loaded from `.coderabbit.yaml` + tool-specific env vars)
   - `Run` — single invocation: diff + analyzers + reviewers + aggregator + output (with run-id for cost tracking)

2. **Interface contracts** → `contracts/`:
   - **`cli-flags.md`** — exact flag set: `--plain`, `--base <branch>`, `--type all|committed|uncommitted`, `--agent` (structured output for piping to Claude), `--force-full` (bypass auto-pause), `--config <path>` (override `.coderabbit.yaml` location). Mirrors `coderabbit review` for drop-in (FR-012).
   - **`output-format.md`** — plain-text output: `file:line:severity:category:message`, parse-compatible with `coderabbit review --plain` consumers (FR-013). Severity prefixes `[ACTIONABLE]`, `[NIT]`, `[INFO]`. Exit code 0 if only NIT/INFO; non-zero if any ACTIONABLE (FR-014).
   - **`finding-schema.md`** — internal Finding object as JSON; aggregator reads per-reviewer JSON streams, merges, outputs canonical findings list. Used by aggregator + agent-mode output.

3. **Quickstart** → `quickstart.md`:
   - Install: `brew install gitleaks markdownlint-cli actionlint shellcheck jq yq`; env vars to set (`DEEPSEEK_API_KEY` required, `ANTHROPIC_API_KEY` optional for cascade).
   - First run: equivalent of `coderabbit review --plain --base main` for this tool.
   - Common configs: stricter mode (require Claude cascade on all paths), faster mode (DeepSeek-only, no static analyzers), CI mode (`--agent` for structured output).
   - Validation: each User Story P1 → P3 has a corresponding "verify it works" command.

4. **Agent context update**: run `.specify/scripts/bash/update-agent-context.sh claude` after Phase 1.

## Open Questions Deferred to /speckit.tasks

- Concrete task breakdown by Phase + dependencies
- Estimated effort per task
- Test-first ordering (which fixture diff is needed before which reviewer prompt)
- Rollout sequencing: claude-workflows internal use first, then propagate to other repos via `propagate-skill.sh review-plan-v2`
