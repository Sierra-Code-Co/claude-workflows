---

description: "Tasks for /review-plan v2"

---

# Tasks: /review-plan v2 — Parallel Multi-Agent Local Code Review

**Input**: Design documents from `/specs/001-review-plan-v2/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/* ✅, quickstart.md ✅

**Tests**: Included — the spec's Constitution Check requires TDD (canned fixture diffs + failing `unittest` cases first, then module impl).

**Organization**: Tasks grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelizable (different files, no dependencies)
- **[Story]**: which user story (US1, US2, etc., maps to spec.md)
- File paths are absolute repo-root–relative.

## Path Conventions

- Single project: `scripts/`, `tests/`, `.claude/skills/` at repository root.
- Orchestrator and supporting code live under `scripts/review_plan_v2/` (Python module, stdlib only). Thin bash entrypoint at `scripts/review-plan-v2.sh` exec's `python3 -m review_plan_v2`.
- See `plan.md#project-structure` for the full directory layout.
- v1 (`scripts/review-plan.sh`) is **not touched** by any task in this plan.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project skeleton + dev tooling.

- [X] T001 Create directory tree per `plan.md#project-structure`: `scripts/review-plan-v2.sh`, `scripts/review_plan_v2/{providers,reviewers,analyzers,prompts}/` with `__init__.py` in each Python package, `.claude/skills/review-plan-v2/SKILL.md`, `tests/{fixtures,support,unit,integration}/` with `__init__.py` in each test package.
- [X] T002 [P] Add the bash entrypoint `scripts/review-plan-v2.sh` (6 lines): `#!/usr/bin/env bash`, `set -euo pipefail`, `SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"`, `export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH:-}"` (the `:-}` default is required because `set -u` would otherwise abort on an unset PYTHONPATH on fresh shells), `exec python3 -m review_plan_v2 "$@"`.
- [X] T003 [P] Add `scripts/review_plan_v2/__init__.py` (`__version__ = "0.1.0"`) and `scripts/review_plan_v2/__main__.py` (argparse skeleton mirroring `contracts/cli-flags.md` — flags only, no orchestration body yet).
- [X] T004 [P] Add `tests/fixtures/responses/README.md` documenting the canned-response naming convention (`<fixture-name>/<provider>.json`) used by `tests/support/fixture_server.py`.
- [X] T005 [P] Add `scripts/review_plan_v2/check_deps.py` (CLI: `python3 -m review_plan_v2.check_deps`) that verifies `python3 >= 3.10`, `jq`, `yq`, `gitleaks`, `markdownlint`, `actionlint`, `shellcheck` are present and reports missing ones (per `quickstart.md`). NO `bats-core` / `pytest` / `pip` checks — there are none.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that ALL user stories depend on. Diff capture, config loading, finding schema, output rendering, provider clients, concurrency, locking, test harness. **No user-story phase can begin until this is complete.**

⚠️ **CRITICAL**: complete this phase before user-story work.

- [X] T006 [P] Implement `scripts/review_plan_v2/diff_capture.py` — `capture_diff(base, scope)` returns the `Diff` dataclass per `data-model.md#Diff` (file/hunk/binary/language detection). Includes base-ref detection (`origin/HEAD` → `main` → `master` → `develop` → `staging` chain per research R-9). Detached HEAD → raise with helpful message; mapped to exit 2 by `__main__.py`.
- [X] T007 [P] Implement `scripts/review_plan_v2/config.py` — `load_config(repo_root) -> RunConfig`. Default behavior is **drop-in friendly** (no exit-code surprise on missing/malformed config); strict behavior is opt-in via `--strict-config` flag. Three failure modes, each handled distinctly:
  1. **`yq` not on PATH**: emit a clear warning to stderr (`"yq not installed; project-aware path_filters/instructions disabled. Install with: brew install yq"`), AND validate `yq` is the mikefarah variant (parse `yq --version` output looking for "mikefarah" or version `>= 4.x`; the python-yq variant matches differently — flag it explicitly). Fall back to default RunConfig (no path_filters, no path_instructions, no high_risk_paths). Set `RunConfig.config_warnings[]`. Without `--strict-config`: exit code follows findings (0/1). With `--strict-config`: exit 5.
  2. **YAML file missing**: silent fallback to defaults (this is the common case; a project may not have `.coderabbit.yaml` or `.review-plan-v2.yaml`). No warning, no exit-code change.
  3. **YAML present but malformed**: emit warning to stderr with file path + line info (`yq` reports this), fall back to defaults, set `RunConfig.config_warnings[]`. Without `--strict-config`: exit follows findings. With `--strict-config`: exit 5.
- [X] T007a [P] Update `contracts/cli-flags.md#exit-codes` to document exit 5 as `--strict-config` only. Add the `--strict-config` flag to the flags table.
- [X] T007b Clarify in `data-model.md#PathInstruction` the **two-layer semantics**: (1) prompt guidance — `instructions` text is prepended to reviewer system prompts for files matching `path_glob` (LLM best-effort obedience); (2) aggregator severity demotion — soft-category findings (style/prose/docs/nit) on those files get demoted from `actionable`/`nit` → `info` if `instructions` contains suppression keywords. Hard categories (security/correctness/bug) never demoted. `path_filters` remain the only mechanism for guaranteed exclusion. T029 test (path_instructions integration test) asserts the prose-nit demotion path, NOT deterministic deletion.
- [X] T008 [P] Implement `scripts/review_plan_v2/output_format.py` — `render_findings_plain(findings) -> str` per `contracts/output-format.md`; `render_findings_agent(findings, summary) -> str` for NDJSON. Severity prefixes, footer summary, exit-code helper.
- [X] T009 [P] Implement `scripts/review_plan_v2/aggregator.py` — pure function `aggregate(findings_lists, path_instructions, dedup_window=5) -> List[Finding]`. Dedups overlapping findings (same file + ±dedup_window lines + same category), promotes confidence on multi-source overlap (`high-confidence` if ≥2 sources, else `single-source`), tiers by severity, and applies the **two-layer path_instructions handling** per `data-model.md#PathInstruction`: instructions are prepended to reviewer prompts before the call (handled by reviewer dispatch in T036, not here), AND the aggregator demotes severity from `actionable`/`nit` → `info` for soft-category findings (`style`/`prose`/`docs`/`nit`) on files matching a `path_instructions` glob whose `instructions` text contains recognized suppression keywords (`skip`/`ignore`/`do not flag`/`not actionable`). Hard categories (`security`/`correctness`/`bug`) are never demoted by `path_instructions`. Stdin→stdout entrypoint via `python3 -m review_plan_v2.aggregator` for ad-hoc use.
- [X] T010 [P] Implement `scripts/review_plan_v2/providers/deepseek.py` — `call(system_prompt, user_prompt, max_tokens=8192, timeout=30.0) -> CallResult` via `urllib.request.urlopen(req, timeout=timeout)` against `DEEPSEEK_API_BASE` (default `https://api.deepseek.com`). Reads `DEEPSEEK_API_KEY` from env. Strips `reasoning_content`. **Per-call timeout 30s** + **bounded retry with exponential backoff**: on `error_kind in ("rate_limit", "transient")`, retry up to 2 times with sleeps `1s, 4s` (capped); on `auth`/`parse`/`unknown`, never retry. Total max time per `call()` ≈ 30s + 4s + 30s + 1s + 30s = ~95s (well under SC-002's 2-min wall-clock budget when capped to 4 concurrent). **Differentiated error handling**: 401/403 → `error_kind="auth", retryable=False`, log clear actionable stderr message (`"DeepSeek auth failed (401). Check DEEPSEEK_API_KEY."`); 429 → `error_kind="rate_limit", retryable=True`; 5xx / `socket.timeout` → `error_kind="transient", retryable=True`; other → `error_kind="unknown", retryable=False`. JSON parse → `error_kind="parse"`. Orchestrator surfaces `auth`/`unknown` in stderr summary so user sees _why_ a reviewer produced no findings rather than assuming "code is clean." Logs metrics-only (provider/model/tokens/latency/status_code/error_kind/retry_count; **never** prompt or diff content) to `$REVIEW_PLAN_V2_LOG_DIR/deepseek.metrics.jsonl`.
- [X] T011 [P] Implement `scripts/review_plan_v2/providers/anthropic.py` — same shape as deepseek.py (including the differentiated error handling above) but for Messages API, `claude-sonnet-4-6`, `x-api-key` + `anthropic-version: 2023-06-01` headers, `ANTHROPIC_API_BASE` default `https://api.anthropic.com`.
- [X] T012 [P] Implement `scripts/review_plan_v2/concurrency.py` — `run_with_cap(callables, max_workers=4) -> List[Result]` using `concurrent.futures.ThreadPoolExecutor`. Each `Result` carries `{value, exception, duration_ms}`. Used to bound total reviewer × chunk × provider calls per `--max-concurrency`.
- [X] T013 [P] Implement `scripts/review_plan_v2/auto_pause.py` per research R-5. **Avoids the read-modify-write race**: instead of separate `read_state` + `update_state` (lock-release-rerun-lock), expose a single context manager `with state_session(state_path, repo_key, branch) as session:` that holds `fcntl.flock(LOCK_EX)` for the entire critical section. The orchestrator pattern is:

  ```python
  with state_session(...) as session:
      should_pause = session.consecutive_trivial >= cfg.auto_pause_n
      if should_pause and not cfg.force_full:
          return  # exit 0 with notice; counter unchanged
      # ... run reviewers ...
      session.record(was_trivial=(actionable_count == 0))
  ```

  The lock is released only after `record()` writes the new state. This eliminates the round-4 race where two concurrent runs both read counter=2 and both write counter=3. `repo_key` comes from `git rev-parse --git-common-dir` (worktree-safe), NOT from the working-tree absolute path. State schema includes `holder_pid` + `holder_started_at` for defense-in-depth. Note: holding the lock for the full review duration is acceptable because the lock is per-(repo, branch); concurrent runs on different branches do not block each other, and concurrent runs on the same branch should serialize anyway (otherwise the auto-pause counter is meaningless).
- [X] T014 [P] Implement `scripts/review_plan_v2/change_manifest.py` — `build(diff) -> ChangeManifest` per `data-model.md#ChangeManifest`. **MVP scope = file-level only**: uses `git diff --name-status -M $base...HEAD` for added/removed/renamed file lists. **Regex-based symbol extraction is deferred to a follow-up** (Gemini round-3/4 scope-creep concern: regex parsing across multiple languages is fragile and adds maintenance cost for marginal MVP value). The consistency reviewer's prompt receives the file-list-only manifest; that's enough for catching cross-doc drift (e.g., CHANGELOG mentions feature X but no file added). Symbol-level cross-references can ship in v2.1 if MVP usage justifies it.
- [X] T015 [P] Implement `scripts/review_plan_v2/reviewers/base.py` — `Reviewer` ABC with `name`, `prompt_path`, `model`, `run(diff_chunk, manifest=None) -> List[Finding]`. Concrete subclasses (security/correctness/tests/consistency) load their prompt from `prompts/<name>.md`, call the appropriate provider, parse the JSON response into Findings.
- [X] T016 [P] Implement `scripts/review_plan_v2/analyzers/base.py` — `StaticAnalyzer` ABC with `name`, `cmd_template`, `applicable_globs`, `parse_output(stdout, stderr) -> List[Finding]`. Concrete subclasses for `gitleaks`, `markdownlint`, `actionlint`, `shellcheck`. Receives **explicit changed-file lists** (NOT whole-repo scans); uses `subprocess.run(args=[…], shell=False)` so paths can never be shell-interpolated. Emits **explicit warning** if the binary is not on `PATH` (NOT silent skip — silent creates false confidence, especially for gitleaks).
- [X] T017 Implement `scripts/review_plan_v2/orchestrator.py` — `run(args)` ties everything together: argv parse → diff capture → config load → ChangeManifest → **gitleaks runs sequentially first** (halt on actionable findings, **then run remaining local deterministic analyzers** so the user gets full local findings before the halt-with-exit-1 — gitleaks blocks LLM transmission, not other locals) → remaining analyzer dispatch (parallel via ThreadPoolExecutor) → auto-pause check (inside `state_session` context manager from T013) → reviewer dispatch (parallel via `concurrency.run_with_cap`) → aggregator → output render → exit code per contracts/cli-flags.md. **Run-level deadline**: orchestrator enforces a wall-clock budget (default 180s, SC-002 + buffer); if exceeded, cancels in-flight futures, surfaces partial findings, exits 1 if any actionable were collected before timeout, else 0 with a "deadline-exceeded" notice. Cost-cap check (FR-021) happens before reviewer dispatch — token estimate × per-provider pricing; abort with exit 3 if over `--max-cost-usd`.
- [X] T018 Wire `scripts/review_plan_v2/__main__.py` to call `orchestrator.run` with parsed args; map exceptions to exit codes per `contracts/cli-flags.md#exit-codes` (0 clean / auto-paused, 1 actionable, 2 tool error, 3 cost cap).
- [X] T019 [P] Implement `tests/support/fixture_server.py` per research R-3 — `ThreadingHTTPServer` subclass binding to port 0 (free port), `start()` returns `(server, thread, base_url)`, `stop(server, thread)` calls `server.shutdown()`. Routes `POST /v1/chat/completions` (DeepSeek) and `POST /v1/messages` (Anthropic) to canned JSON files at `tests/fixtures/responses/<fixture-name>/<provider>.json`. Fixture name is selected via a request header `X-Test-Fixture` set by the test runner.
- [X] T020 [P] Implement `tests/support/runner.py` — helper to invoke `python3 -m review_plan_v2` as a subprocess with the appropriate `DEEPSEEK_API_BASE` / `ANTHROPIC_API_BASE` env pointing at the running fixture server. Returns `(stdout, stderr, exit_code)`. Provides `assert_exit_code`, `assert_stdout_contains` convenience asserts. **`tests/fixtures/*.diff` files are not consumed directly by `__main__.py`** — instead, `runner.py` exposes `make_repo_from_diff(diff_path) -> tempdir`, which initializes a temp git repo, applies the diff via `git apply`, commits, and returns the path. Tests then `cd` there and invoke the tool against `--base HEAD~1`. This keeps `diff_capture.py`'s "real git" code path exercised end-to-end without needing a `--diff-file` test backdoor in production code.
- [X] T021 Add `.claude/skills/review-plan-v2/SKILL.md` — thin Claude Code skill wrapper that invokes `scripts/review-plan-v2.sh` with appropriate flags. References `contracts/cli-flags.md` for the flag set. Coexists with the existing `/review-plan` skill (different concern).

**Checkpoint**: foundation ready — user-story phases can now begin in parallel.

---

## Phase 3: User Story 1 — Pre-push without rate limits + parallel specialized reviewers + project-aware (Priority: P1) 🎯 MVP

**Goal**: A developer runs one command before pushing, gets CR-style findings within ~2 min using their own LLM keys, with specialized reviewers (security, correctness, tests, consistency) running in parallel and respecting `.coderabbit.yaml` `path_instructions`.

**Independent Test**: Run `review-plan-v2 --plain --base main` on a fixture branch with a known issue (e.g., `'user-cancelled'` PascalCase bug). Verify it's flagged as actionable + categorized correctly + completes < 2 min + zero rate-limit errors over 10 consecutive runs.

### Tests for User Story 1 (TDD — write FIRST, ensure they FAIL before implementation)

- [X] T022 [P] [US1] Create `tests/fixtures/01-clean.diff` (no findings expected) + `tests/fixtures/responses/01-clean/{deepseek,anthropic}.json` (canned empty-Finding-array responses).
- [X] T023 [P] [US1] Create `tests/fixtures/02-pascalcase-bug.diff` (the `err.code === 'user-cancelled'` antipattern) + canned responses where security + correctness reviewers flag it.
- [X] T024 [P] [US1] Create `tests/fixtures/03-sql-injection.diff` + canned responses (security flags it; others don't — exercises specialization).
- [X] T025 [P] [US1] Create `tests/fixtures/08-cross-doc-drift.diff` (CHANGELOG claims feature X but feature/SKILL.md doesn't have it) + canned responses (consistency flags it).
- [X] T026 [P] [US1] `tests/integration/test_happy_path.py` — runs the tool against fixture 01 and asserts: exit 0, "Clean (no findings)" in output, wall-clock < 120s.
- [X] T027 [P] [US1] `tests/integration/test_specialization.py` — runs against fixtures 02, 03, 08 and asserts each is caught by the expected reviewer (and ONLY that reviewer; no spurious cross-firing).
- [X] T028 [P] [US1] `tests/integration/test_parallelism.py` — asserts wall-clock for 4 reviewers ≈ slowest single reviewer time (not sum); fixture server returns canned responses with explicit per-reviewer delay headers.
- [X] T029 [P] [US1] `tests/integration/test_path_instructions.py` — fixture with a real bug, a soft-category prose nit, and a hard-category security finding on a `**/*.md` file with `path_instruction: "skip prose nits"`. Asserts: (a) reviewer system prompt receives the `path_instruction` text (verifies prompt-guidance layer); (b) the prose nit appears in output but at `[INFO]` severity (demoted by aggregator); (c) the security finding is unchanged (hard categories never demoted); (d) exit code 0 (info-tier doesn't gate).
- [X] T030 [P] [US1] `tests/unit/test_aggregator.py` — `unittest` cases for the dedup logic: same finding from 2 reviewers → 1 finding tagged `high-confidence`; non-overlapping findings stay separate; severity tier promotion (multi-source actionable beats single-source nit); configurable dedup window honored.

### Implementation for User Story 1

- [X] T031 [P] [US1] Write `scripts/review_plan_v2/prompts/security.md` — system prompt for security agent (auth, OWASP, injection, secrets handling); output schema reference per `contracts/finding-schema.md#llm-reviewer-output`.
- [X] T032 [P] [US1] Write `scripts/review_plan_v2/prompts/correctness.md` — system prompt for correctness agent (logic bugs, race conditions, contract drift, SDK string contracts).
- [X] T033 [P] [US1] Write `scripts/review_plan_v2/prompts/tests.md` — system prompt for tests agent (coverage, mock-vs-real interface match, vacuous tests, assertion quality).
- [X] T034 [P] [US1] Write `scripts/review_plan_v2/prompts/consistency.md` — system prompt for cross-doc consistency agent (CHANGELOG vs spec vs code vs PR description vs CLAUDE.md). Includes `{{change_manifest}}` placeholder filled by `change_manifest.py`.
- [X] T035 [P] [US1] Implement reviewer subclasses `scripts/review_plan_v2/reviewers/{security,correctness,tests,consistency}.py` extending `base.Reviewer`. Each loads its prompt, calls the appropriate provider, parses JSON to Findings.
- [X] T036 [US1] Wire reviewer dispatch in `orchestrator.py` — for each enabled reviewer, build a callable that takes a diff chunk; submit all to `concurrency.run_with_cap` with `max_workers=config.max_concurrency` (default 4).
- [X] T037 [US1] Implement diff chunking per research R-6 in `diff_capture.py` — files > 1500 lines split by hunk; multiple chunks per file are reviewed independently and findings merged in aggregator.
- [X] T038 [US1] Verify all T026–T030 tests pass against the implementation (rerun after T031–T037).

**Checkpoint**: User Story 1 fully functional. The tool can be used as a drop-in replacement for the pre-push step in CLAUDE.md "Pre-push" section. **This is the MVP — stop and validate before continuing.**

---

## Phase 4: User Story 4 — Drop-in CLI compatibility (Priority: P2)

**Goal**: Tool's `--plain` output is grep-compatible with `coderabbit review --plain` output. Same flag interface (`--base`, `--type`). Minimal-edit swap in CLAUDE.md.

**Independent Test**: Replace `coderabbit review --plain --base main` with `review-plan-v2 --plain --base main` in a script that pipes to `grep '^\[ACTIONABLE\]'`. Same script, same output shape. No script changes needed.

- [ ] T039 [P] [US4] `tests/integration/test_cli_flags.py` — for each flag in `contracts/cli-flags.md` (--plain, --base, --type, --agent, --no-color, --version, --help), assert it's accepted and behaves per spec.
- [ ] T040 [P] [US4] `tests/integration/test_output_format_golden.py` — assert plain-mode lines match the regex `^\[(ACTIONABLE|NIT|INFO)\] [^:]+:[0-9]+(-[0-9]+)? \[\w+\]` for fixtures 02, 03, 08; cross-check against captured `tests/fixtures/golden/cr-plain-output-sample.txt`.
- [ ] T041 [P] [US4] `tests/integration/test_exit_codes.py` — assert exit 0 on clean diff, exit 0 on auto-paused (with stdout notice), 1 on actionable findings, 2 on tool error, 3 on cost cap (FR-021), 5 on config error with fallback to defaults (per `contracts/cli-flags.md#exit-codes`). **No exit code 4** — auto-pause is informational, exits 0.
- [ ] T042 [US4] Complete flag parsing in `scripts/review_plan_v2/__main__.py` — argparse with `add_argument` for each flag; unknown flags exit 2 with helpful argparse error; mirrors CR's flag names verbatim where they exist.
- [ ] T043 [US4] Implement exit-code mapping in `orchestrator.py` per the table in `contracts/cli-flags.md`.

**Checkpoint**: Drop-in CLI verified. Global CLAUDE.md "Pre-push" section can swap tool names with one-line edit.

---

## Phase 5: User Story 5 — Static analyzer ensemble + sequential gitleaks (Priority: P2)

**Goal**: gitleaks runs **first, sequentially**, halting the run if it finds actionable secrets (so the diff is never sent to external LLM APIs). Other static analyzers (markdownlint/actionlint/shellcheck) run in parallel as deterministic pre-checks; their findings flow into the aggregator alongside LLM findings; complete in < 10s even on large diffs.

**Independent Test**: Add a fake AWS access key to a file, run review. Verify gitleaks catches it as actionable+secrets within 10s, **the diff is NOT sent to any LLM provider** (no entries in fixture server access log), and the run halts with exit 1.

- [ ] T044 [P] [US5] Create `tests/fixtures/04-secret-leak.diff` (fake AWS access key string) — no canned LLM responses needed because gitleaks should catch it before any LLM call.
- [ ] T045 [P] [US5] `tests/integration/test_static_analyzers.py` — fixture 04 produces gitleaks finding within 10s; **assertion: fixture server received zero requests** (proves diff was not transmitted to external APIs); missing-analyzer case (e.g., `actionlint` not installed) gracefully skipped with **explicit warning** (NOT silent skip).
- [X] T046 [US5] Implement sequential-first gitleaks dispatch in `orchestrator.py` — invoke `analyzers/gitleaks.py` before any LLM call against **only the changed files** (copy them into `tempfile.mkdtemp()`, point `--source` at it, copy `.gitleaks.toml` if present so the user's allowlist and custom rules apply). On any remaining findings (post-allowlist, post-line-filter from T046a): render output, exit 1, but **first run remaining LOCAL deterministic analyzers** (markdownlint, actionlint, shellcheck) so the user gets the full set of local findings in one run rather than discovering them only on the next pass. The "halt" applies only to LLM transmission, not to local analyzers. After all locals complete, render combined output and exit 1 if any actionable secret/analyzer finding exists.
- [X] T046a [P] [US5] Implement `analyzers/gitleaks.py` line-overlap filter — separate function `filter_to_diff_lines(findings, diff) -> List[Finding]`. For each gitleaks finding, look up the file in the `Diff` object, check whether `finding.line` falls inside any added/modified line range from the diff hunks; drop findings outside those ranges (pre-existing secrets in unchanged code). This makes "actionable secret" mean exactly: (a) appears in a line that this diff added or modified, (b) not allowlisted by `.gitleaks.toml`. Unit-tested in isolation with synthetic Diff + findings inputs (`tests/unit/test_gitleaks_overlap.py`).
- [ ] T047 [US5] Implement analyzer subclasses `scripts/review_plan_v2/analyzers/{gitleaks,markdownlint,actionlint,shellcheck}.py` per `data-model.md#StaticAnalyzerRun` — each receives explicit changed-file list (intersected with `applicable_globs`); shell=False subprocess invocation; output→Finding parser. Missing-binary path emits warning to stderr and to the `analyzers_skipped` summary metadata.

**Checkpoint**: User Stories 1, 4, 5 all working. The tool is now feature-equivalent to the basic CR CLI usage.

---

## Phase 6: User Story 6 — Adversarial multi-model cascade (Priority: P3)

**Goal**: For changes touching paths flagged in `.review-plan-v2.yaml#high_risk_paths`, the security and correctness reviewers run on Claude Sonnet in addition to DeepSeek. Findings flagged by both get `high-confidence`; single-source findings get `single-source` so the user can weigh them.

**Independent Test**: Configure `src/**/auth/**` in `.review-plan-v2.yaml#high_risk_paths`. Run on a diff that touches that path. Verify `--agent` output shows `providers_called` includes both `deepseek` and `anthropic`, and at least one finding has `confidence: high-confidence`.

- [ ] T048 [P] [US6] Create `tests/fixtures/05-cascade-trigger.diff` — touches both `src/lib/auth/session.ts` (configured high-risk) and `src/utils/format.ts` (not high-risk) + canned responses where DeepSeek and Claude both flag a session-handling issue.
- [ ] T049 [P] [US6] `tests/integration/test_cascade.py` — fixture 05 produces at least one `high-confidence` finding; confirms `providers_called` in agent output includes both `deepseek` and `anthropic`; non-high-risk paths NOT cascaded.
- [ ] T050 [US6] Wire cascade dispatch in `orchestrator.py` — for each diff file matching a `.review-plan-v2.yaml#high_risk_paths` glob (matched via `fnmatch`), and for each cascade-eligible reviewer (security, correctness): submit an additional `anthropic` callable to `concurrency.run_with_cap` alongside the `deepseek` one. Aggregator promotes confidence on overlap. **No `is_high_risk` extension to `.coderabbit.yaml`** — high-risk paths live in `.review-plan-v2.yaml` only (per FR-016).

**Checkpoint**: Cascade working. Higher-risk diffs get higher-quality second opinion automatically.

---

## Phase 7: User Story 7 — Auto-pause-after-N (Priority: P3)

**Goal**: After N consecutive runs on the same branch with 0 actionable findings, subsequent runs skip the LLM phase (still run static analyzers); reset on actionable findings or `--force-full`.

**Independent Test**: Run review 3 times on commits that change only whitespace. Verify the 4th run **exits with code 0** AND emits "Auto-paused" notice on stdout (not exit 4 — that would block pre-push hooks per FR-014). `--force-full` overrides.

- [ ] T051 [P] [US7] `tests/integration/test_auto_pause_e2e.py` — uses fixture 01 (clean) repeated; asserts state file accumulates `consecutive_trivial_runs`; after N=3, **exits with code 0** AND emits "Auto-paused" notice on stdout; `--force-full` resets behavior to a normal run.
- [ ] T052 [P] [US7] `tests/unit/test_auto_pause.py` — `unittest` cases for `auto_pause.read_state` / `update_state` under `fcntl.flock`; concurrent-writer test launches two threads writing to the same state file and asserts no torn writes; `--force-full` bypass; state-file corruption → reset to defaults with warning.
- [ ] T053 [US7] Wire auto-pause check in `orchestrator.py` — after diff capture, before reviewer dispatch: if `consecutive_trivial_runs >= auto_pause_n` AND `--force-full` not set, skip LLM phase, still run analyzers, emit "Auto-paused (last N runs trivial) — pass --force-full to override" notice on stdout, exit 0. Update state at end of run.

**Checkpoint**: All P1–P3 user stories implemented and tested.

---

## Phase 8: Polish & Cross-Cutting

**Purpose**: Edge-case fixtures, security hardening tests, telemetry, propagation, and the foundational template PR.

- [ ] T054 [P] Write `tests/fixtures/06-binary-file.diff` + `tests/integration/test_binary_file.py` asserting binaries are flagged "binary, not reviewed" and excluded from LLM passes (FR-018).
- [ ] T055 [P] Write `tests/fixtures/07-empty-diff.diff` + `tests/integration/test_empty_diff.py` asserting clean exit with informational message and 0 LLM token spend (FR-019).
- [ ] T056 [P] Write `tests/fixtures/11-malformed-yaml.diff` + `tests/integration/test_malformed_yaml.py` — invalid `.coderabbit.yaml` produces parse error with line info, falls back to defaults. Default mode: stderr warning + exit follows findings (0 if clean). With `--strict-config`: exit 5. Test also covers `yq` not on PATH (both modes) and python-yq variant detection (warns "wrong yq variant; install mikefarah's yq").
- [ ] T057 [P] Write `tests/integration/test_detached_head.py` — sets up detached HEAD via `git checkout <sha>`, runs review, asserts clear error message + exit 2 (NOT silent failure or massive unrelated diff).
- [ ] T058 [P] Write `tests/integration/test_no_upstream.py` — clones with `--single-branch` (no `origin/HEAD` set); tool falls back through main → master → develop → staging chain; if none match, errors with helpful message asking for `--base` explicitly (per research R-9).
- [ ] T059 [P] Capture `tests/fixtures/golden/cr-plain-output-sample.txt` from a real `coderabbit review --plain` run; `test_output_format_golden.py` (T040) asserts our `--plain` output matches the same line-format regex (FR-013 verification).
- [ ] T060 [P] Write `tests/fixtures/12-malicious-filename.diff` (file named `; rm -rf ~.txt`) + `tests/integration/test_shell_injection.py` — verifies analyzer subprocess invocations use `shell=False` and an args list, so injected commands cannot be exec'd.
- [ ] T061 [P] Write `tests/integration/test_concurrency_cap.py` — diff with 20 chunks × 4 reviewers; assert no more than `--max-concurrency` parallel calls at any time (verifiable via overlapping-timestamp count in `metrics.jsonl` log).
- [ ] T062 [P] Write `tests/integration/test_degraded_providers.py` — simulate missing `DEEPSEEK_API_KEY` (with no other configured provider) → exit 2; missing `ANTHROPIC_API_KEY` with cascade enabled → cascade silently disabled with notice on stdout (FR-009 + edge cases).
- [X] T063 [P] Add cost-log telemetry in `scripts/review_plan_v2/telemetry.py` — single-writer module exposing `log_call(record: dict)`. Implementation uses a module-level `threading.Lock`; each call serializes `json.dumps(record)` to a single line and appends to `~/.claude/review-plan-v2/cost-log.jsonl` while holding the lock (no torn lines under thread-pool concurrency). Providers (`deepseek.py`, `anthropic.py`) import and call `log_call` instead of writing files directly. **Strict log schema: provider/model/reviewer/input_tokens/output_tokens/latency_ms/status only — no prompt content, no diff content, no error message bodies that might contain prompt fragments** (FR-015).
- [ ] T064 [P] Update CLAUDE.md "Pre-push" section in `dotfiles/claude/CLAUDE.md` — replace `coderabbit review --plain --base main` with `review-plan-v2 --plain --base main` once tool is shipped and validated against SC-001 (80% catch parity).
- [ ] T065 [P] Add example `.review-plan-v2.yaml.example` at repo root documenting the v2-specific config (high_risk_paths, max_concurrency, auto_pause_n, dedup_line_window). **No `.coderabbit.yaml` extensions** — CR's schema is read as-is.
- [ ] T066 [P] Validate against SC-001: run on 10 representative pre-push diffs from companion-ai + claude-workflows, compare findings list against `coderabbit review --plain` output. Document catch-rate parity in `tests/sc001-validation.md`.
- [ ] T067 [P] Validate SC-003 (cost): instrument 20 runs, assert avg cost < $0.20 USD on default config.
- [ ] T068 [P] Validate SC-004 (rate limits): 100 consecutive runs with no rate-limit errors.
- [ ] T069 [P] Update `STATE.md` — note `review-plan-v2` as installed tool under "CLIs installed (review tooling)".
- [ ] T070 [P] Add memory entry `feedback_review_plan_v2_workflow.md` — confirms which models v2 uses (DeepSeek + Claude Sonnet cascade), reconciles Issue #13.
- [ ] T071 [P] Close Issue #13 with reference to v2's resolution.
- [ ] T072 Add ADR `decisions/0008-review-plan-v2.md` — documents:
  1. Model selection (DeepSeek R1 default + Claude Sonnet cascade-on-high-risk; OpenAI/Gemini deferred from MVP per research R-7 and FR-003 SHOULD-not-MUST).
  2. Separate-from-v1 namespace decision (no shared bash library; v1 stays bash + untouched, v2 is Python).
  3. **Python orchestrator over bash** (the round-2 RED → pivot decision; YAGNI rationale around stdlib `concurrent.futures` / `fcntl.flock` / `http.server` / `unittest`).
  4. Separate `.review-plan-v2.yaml` for v2-specific config (NO extensions to `.coderabbit.yaml`).
  5. `fcntl.flock` over `mkdir`-as-mutex (kernel auto-release on `kill -9`).
  6. Stdlib `unittest` over `pytest`/`bats-core` (charter compliance: stdlib ships, no install step).
  7. Sequential gitleaks-first (security: never transmit secrets to external LLMs).
- [ ] T073 Run `scripts/propagate-skill.sh review-plan-v2` from claude-speckit-template to deploy to active projects (after speckit-template's foundational PR merges first).
- [ ] T074 Update `decisions/README.md` index with ADR-0008.
- [ ] T075 Run `coderabbit review --plain --base main` on the v2 PR pre-push (drinking own champagne — once v2 is mergeable, this run becomes the validation that the new tool catches the same things CR catches on its own implementation).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: no deps; can start immediately.
- **Phase 2 (Foundational)**: depends on Phase 1; **BLOCKS** all user-story phases.
- **Phase 3 (US1)** = MVP: depends on Phase 2.
- **Phase 4–7 (US4, US5, US6, US7)**: each depends on Phase 2; can run in parallel with each other AFTER Phase 3 (US1) is verified working as MVP.
- **Phase 8 (Polish)**: depends on whichever user-story phases you've decided to ship.

### User Story Independence

- US1 (P1) is the standalone MVP: pre-push works without rate limits, with specialized reviewers and `.coderabbit.yaml` integration. Stop after Phase 3 if you want a minimal shipping increment.
- US4 (P2 drop-in CLI) and US5 (P2 static analyzers + sequential gitleaks) are independent and can be added after US1.
- US6 (P3 cascade) requires US1 (cascade is a refinement of how reviewers run, not a separate workflow).
- US7 (P3 auto-pause) is orthogonal — could be implemented anytime after Phase 2.

### Within Each User Story

- Tests written first (`unittest` cases + canned fixture diffs), verify they FAIL before implementation.
- Module files (`scripts/review_plan_v2/*.py`) before orchestrator wiring.
- Orchestrator wiring last in each phase.

### Parallel Opportunities

- All [P] tasks within Phase 1 can run in parallel.
- All [P] tasks within Phase 2 can run in parallel (foundational `*.py` modules touch different files).
- All US1 test+fixture tasks (T022–T030) can run in parallel.
- All US1 prompt-writing tasks (T031–T034) can run in parallel.
- Polish tasks (T054–T071) all parallelizable.

---

## Parallel Example: User Story 1

```bash
# Test fixtures + canned responses (all in parallel):
T022 — fixture 01-clean
T023 — fixture 02-pascalcase-bug
T024 — fixture 03-sql-injection
T025 — fixture 08-cross-doc-drift

# Integration + unit tests (all in parallel):
T026 — test_happy_path.py
T027 — test_specialization.py
T028 — test_parallelism.py
T029 — test_path_instructions.py
T030 — test_aggregator.py

# Reviewer prompts (all in parallel):
T031 — security.md
T032 — correctness.md
T033 — tests.md
T034 — consistency.md
```

After fixtures + tests are all in place (and FAILING per TDD), do T035 + T036 + T037 + T038 to wire the orchestrator and pass the tests.

---

## Implementation Strategy

### MVP First (Phase 3 / User Story 1)

1. Phase 1 (Setup) — ~30 min.
2. Phase 2 (Foundational) — ~3-4 hr (Python modules + test harness).
3. Phase 3 (US1: pre-push, parallel reviewers, path_instructions) — ~3-4 hr.
4. **STOP and VALIDATE**: pre-push CR-style review works end-to-end on a real repo.
5. Replace pre-push CLI in personal usage; collect data on SC-001 catch parity.

This is the minimum to meaningfully use the tool. Total: ~7-8 hr of focused work.

### Incremental Delivery

After MVP, layer in:

- US4 (drop-in CLI compat) — small, ~1 hr.
- US5 (static analyzers + sequential gitleaks) — ~2 hr.
- US6 (cascade) — ~1-2 hr.
- US7 (auto-pause) — ~1 hr.
- Polish (T054–T075) — ~3-4 hr.

Total to full-spec: ~16-18 hr.

### Parallel Solo Strategy

Even working alone, leverage the parallel-safe boundaries:

- After Phase 2, work US1 + US5 in parallel (they touch different module files: `reviewers/` vs `analyzers/`).
- US6 + US7 are orthogonal once US1 ships.

---

## Notes

- The existing `scripts/review-plan.sh` (v1) is **not modified** by this work. v1 (spec/plan review, bash) and v2 (diff review, Python) coexist.
- Per FR-013, `--plain` output must be grep-compatible with `coderabbit review --plain`. Tests T040 and T059 enforce this.
- Issue #13 (DeepSeek docs vs script discrepancy) is fully resolved in v2: research R-7 settles which models are used. T071 closes the issue.
- The `.coderabbit.yaml` parsing requires `yq` (mikefarah's go binary) per research R-4; quickstart.md install line includes it. **No `is_high_risk` extension** to CR's schema — high-risk paths live in `.review-plan-v2.yaml` (FR-016).
- Auto-pause state file path is overridable via `REVIEW_PLAN_V2_STATE_FILE` env var per `contracts/cli-flags.md#environment-variables` — useful for testing.
- Auto-pause exits 0 (informational notice on stdout), NOT a distinct exit code. Exit code 4 does not exist.
- Sequential gitleaks-first means **the diff is never sent to external LLM APIs if a secret is detected**. This is the security fix from Gemini's round-2 review.
- Concurrency cap is enforced via `concurrent.futures.ThreadPoolExecutor(max_workers=N)` (default 4); test T061 verifies the cap is honored.
- After implementation, the global CLAUDE.md "Pre-push" section gets a one-line edit (T064) to swap the tool name. This is the same edit the speckit-template foundational PR will need to make in its own copy of CLAUDE.md.
