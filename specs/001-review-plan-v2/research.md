# Phase 0 Research — /review-plan v2

**Date**: 2026-04-27
**Branch**: `001-review-plan-v2`

Resolves the nine unknowns (R-1 through R-9) identified in `plan.md` Phase 0.

---

## R-1: DeepSeek R1 API contract

**Decision**: Use DeepSeek's Chat Completions endpoint with model `deepseek-reasoner`. Strip reasoning output, keep only the final answer.

**Rationale**:

- DeepSeek's API is OpenAI-compatible (Chat Completions style). Endpoint: `https://api.deepseek.com/v1/chat/completions`. Auth: `Authorization: Bearer $DEEPSEEK_API_KEY`.
- `deepseek-reasoner` is the R1-equivalent reasoning model. Output structure: `choices[0].message.content` (final answer) and `choices[0].message.reasoning_content` (chain-of-thought; can be many KB; we don't want it in findings).
- Parse response with the same Python pattern as the existing `scripts/review-plan.sh` — read stdin JSON, extract `choices[0].message.content`, fall back to `__EMPTY__` on parse failure.
- Apply the same subshell-with-error-guard pattern from the v1 fix: `if ! ( curl … | python3 -c … > "$OUT" 2>>"$LOG" ); then echo "__EMPTY__" > "$OUT"; fi`.

**Alternatives considered**:

- DeepSeek-V3 (non-reasoning model): cheaper but lower quality on the kind of subtle catches we need (race conditions, contract drift). Reasoning model worth the extra latency for code review.
- DeepSeek's beta endpoints: too unstable for daily-use tooling.

---

## R-2: Anthropic Claude cascade integration

**Decision**: Anthropic Messages API with `claude-sonnet-4-6`. Cascade-only — Claude is invoked for the security and correctness reviewers when the diff touches a high-risk path, NOT for every reviewer or every diff.

**Rationale**:

- Messages API endpoint: `https://api.anthropic.com/v1/messages`. Headers: `x-api-key: $ANTHROPIC_API_KEY`, `anthropic-version: 2023-06-01`.
- Request shape: `{model, max_tokens, system, messages: [{role: "user", content: "..."}]}`. Parse `response.content[0].text`.
- `max_tokens: 8192` to match v1's pattern.
- High-risk paths configured via `.review-plan-v2.yaml` `high_risk_paths[]` keyed by glob (e.g., `src/**/auth/**`, `src/**/db/schema.*`, `infra/**`). v2 does NOT extend `.coderabbit.yaml`'s schema — high-risk config lives in the v2-specific file per FR-016 / ADR-0008. Cascade triggers on per-file basis, not per-diff.
- Findings flagged by both DeepSeek + Claude get `confidence: "high-confidence"`. DeepSeek-only gets `confidence: "single-source"`.

**Alternatives considered**:

- Cascade on every diff: 10x cost increase, no proportional quality gain on most diffs.
- Cascade only on RED-rated diffs: requires a meta-classifier first; adds complexity.
- Use Claude Opus instead of Sonnet for cascade: ~3x cost; for code review, Sonnet's quality is sufficient and the 5x speedup matters for keeping wall-clock under 2 min.

---

## R-3: Tests via Python stdlib `unittest` only

**Decision**: All tests are Python stdlib `unittest`, run via `python3 -m unittest discover -s tests/unit` and `python3 -m unittest discover -s tests/integration`. No `bats-core`, no `pytest`. Two layers of test doubles for provider HTTP:

1. **Unit tests** patch `urllib.request.urlopen` via `unittest.mock.patch` — fast, in-process, exercises request-shape assertions (URL, headers, body JSON).
2. **Integration tests** spin up `tests/support/fixture_server.py` (a stdlib `http.server.ThreadingHTTPServer` subclass) on a free localhost port; provider clients pick up `DEEPSEEK_API_BASE` / `ANTHROPIC_API_BASE` from env to point at `http://127.0.0.1:<port>`. The server returns canned JSON keyed by fixture name + provider, looked up from `tests/fixtures/responses/<fixture-name>/<provider>.json`.

**Rationale**:

- `unittest` ships with Python 3.10+ — no `pip install`, no `requirements.txt`, no test-runner binary. Charter compliance: the charter forbids "test runner" frameworks (e.g., `pytest`, `bats-core`) that need install steps and config files; stdlib `unittest` is just an import.
- `unittest.mock.patch` covers the fast-path: aggregator dedup, finding parsing, config merging, base-ref detection — no HTTP round-trip needed, tests run in milliseconds.
- The `http.server`-based fixture server is preferred for end-to-end integration tests because it exercises the full HTTP path (URL building, header serialization, JSON parsing) — the same code path that hits real providers in production. `ThreadingHTTPServer` handles parallel requests cleanly (matches our `ThreadPoolExecutor`-based concurrency).
- **Fixture server lifecycle**: `tests/support/fixture_server.py` exposes `start()` (binds to port 0, returns server + thread), `stop()` (calls `server.shutdown()`). Test cases use a `setUp`/`tearDown` pair or `addClassCleanup` to ensure the server is torn down even on test failure. No PID files, no traps — Python's `unittest` handles cleanup automatically.
- For each fixture diff, the corresponding provider response is committed alongside under `tests/fixtures/responses/<fixture-name>/<provider>.json`. The server reads these on each request.

**Alternatives considered**:

- `bats-core`: rejected per charter ("don't add a test runner") and rejected on architectural grounds — bash + bats-core for testing concurrent HTTP code recreates from scratch what Python's stdlib provides for free.
- `pytest`: rejected per charter; stdlib `unittest` is sufficient.
- Plain shell scripts (`tests/integration/*.sh`) with `set -e`: rejected because they would still need a Python fixture server (no portable bash HTTP server), and would be a parallel test harness alongside the Python `unittest` aggregator tests — two test-runners is worse than one.
- `nc`/`socat` listener: doesn't handle parallel requests cleanly; doesn't handle `Content-Length` parsing for POST bodies.
- `vcr.py`-style cassettes (record real, replay): overkill; the fixture-response approach gives deterministic catches tied to specific test cases.

---

## R-4: `.coderabbit.yaml` parsing

**Decision**: Require `yq` (mikefarah's go binary) as a runtime dep, invoked from Python via `subprocess.run(["yq", "-o=json", ".", path], capture_output=True)` to convert the entire YAML document to JSON. `config.py` then extracts both `path_filters[]` and `path_instructions[]` from the parsed dict (CR's schema allows `path_instructions` either at the top level or nested under `reviews.path_instructions`, so we check both). Document in `quickstart.md`. No `pyyaml` dep — keeps the project at zero `pip install` dependencies.

**Rationale**:

- The `path_instructions` parsing involves nested YAML structures + globs. `yq` returns canonical JSON which `json.loads` handles natively in stdlib.
- `yq` is small (~5MB), easily installed via brew/apt, and used elsewhere in the claude-workflows ecosystem (`scripts/review-plan.sh` v1 already shells out to `yq` for spec parsing).
- Adding `pyyaml` would mean shipping a `requirements.txt` and a `pip install` step — both forbidden by the claude-workflows charter ("Don't add a build system, package.json, or test runner"). `subprocess` to a system binary is the same shape as our existing static-analyzer invocations.
- Document in `quickstart.md` install line: `brew install gitleaks markdownlint-cli actionlint shellcheck jq yq` (plus Python 3.10+, which ships on macOS 13+ and all supported Linux distros).

**Alternatives considered**:

- `pyyaml`: rejected — adds a `pip install` step that the charter forbids.
- Python stdlib YAML parse: stdlib has no YAML parser. (`json` and `tomllib` only.)
- Hand-roll a minimal YAML parser in stdlib: unmaintainable; YAML's edge cases bite quickly.
- Skip `path_instructions` support in v2 and add later: spec User Story 3 is P1 — not deferrable.

---

## R-5: Auto-pause state tracking

**Decision**: JSON state file at `~/.claude/review-plan-v2/auto-pause-state.json` keyed by `<git-common-dir>:<branch>` (worktree-safe — `git rev-parse --git-common-dir` returns the same path for every worktree of one underlying repo). Read-modify-write protected by **`fcntl.flock`** on the state file itself (Python stdlib, native to macOS + Linux). PID + timestamp also recorded inside the JSON as a defense-in-depth check.

**Rationale**:

- `fcntl.flock` is in the Python stdlib (`import fcntl`) and works identically on macOS + Linux. We are no longer in bash, so the macOS portability concern that pushed earlier drafts toward `mkdir`-as-mutex is moot.
- **Kernel auto-releases the lock on process exit** — including `kill -9`, `OSError`, `KeyboardInterrupt`. This is the killer feature: `mkdir`-as-mutex requires a `trap` to clean up on error, which is fragile (e.g., `kill -9` bypasses the trap, leaving a stale lock that blocks all future runs until manual cleanup).
- Implementation: open the state file, `fcntl.flock(fd, fcntl.LOCK_EX)` to acquire (blocks if another process holds it), `json.load` → mutate → `json.dump`, close the file. Lock auto-releases on close.
- Per-repo + per-branch state is necessary because multiple repos may use the tool simultaneously.
- State schema: `{ "$repo:$branch": { last_run_commits: [<sha>...], consecutive_trivial: <int>, last_updated: <iso8601>, holder_pid: <int>, holder_started_at: <iso8601> } }`. The `holder_pid` + `holder_started_at` fields let a future run detect "lock held by PID X for > 60s — that PID is gone, log a warning" if `fcntl.flock` ever misbehaves.
- Skip-LLM kicks in when `consecutive_trivial >= N` (default 3, override via `--auto-pause-n`). Auto-paused runs **exit 0 with informational notice on stdout**, NOT a distinct error code (would break pre-push hooks per FR-014).
- `--force-full` flag bypasses the check entirely.

**Alternatives considered**:

- `mkdir`-as-mutex: rejected — no kernel auto-release on `kill -9`, fragile under concurrent load (race on the EEXIST check on some filesystems), and we're not constrained to bash anymore.
- `filelock` package (`pip install filelock`): adds a `pip install` step the charter forbids. `fcntl.flock` is stdlib.
- SQLite: overkill for this state shape.
- In-repo `.review-plan-v2-state` file (gitignored): fragile (gets nuked on `git clean -fdx`); clutters the working tree.
- No state at all (always run all reviewers): violates User Story 7.

---

## R-6: Diff chunking

**Decision**: Chunk by file. Group changes per file; if a single file's diff exceeds a configured threshold (default 1500 lines, defined as `CHUNK_LINE_THRESHOLD` in `diff_capture.py`), further sub-chunk by hunk. Token estimation uses `chars / 4` heuristic per provider context limit.

**Rationale**:

- Per-file is the natural review boundary — context for a finding is usually within-file.
- 1500-line threshold per file keeps each chunk well under DeepSeek R1's 64k context (≈12k tokens at 4 chars/token, leaving headroom for system prompt + reviewer output).
- Multiple chunks for the same file are reviewed independently and findings are merged in the aggregator (deduplication is straightforward since findings have file+line keys).
- Cross-file findings are handled by the consistency-reviewer, which gets a different (smaller) per-file summary input rather than the raw diff.

**Alternatives considered**:

- Token-counting via `tiktoken`-equivalent: more accurate but adds a Python dep and is overkill for a heuristic that mostly works.
- No chunking, always send full diff: breaks on large refactors; defers FR-020 indefinitely.
- Per-hunk chunking: too granular; loses cross-hunk context within a file (e.g., a function's signature change being reviewed without the corresponding body change).

---

## R-7: Issue #13 reconciliation — which models does v2 actually use?

**Decision**: v2 MVP = **DeepSeek R1 (broad-pass) + Claude Sonnet (cascade-on-high-risk)**. OpenAI gpt-5.3-codex and Gemini 2.5 Pro **are NOT in MVP**. Adding them later if user demand justifies; for now they remain in v1 (spec/plan review) only.

**Rationale**:

- Spec User Story 1 (P1) requires "no rate limits" — DeepSeek + Anthropic Pro plans give effectively unlimited usage at this volume.
- DeepSeek R1 is significantly cheaper ($0.55 / $2.19 per M tokens vs. $3 / $15 for Claude Sonnet) and quality is high enough for broad-pass.
- Claude Sonnet cascade gives high-quality second opinion on critical paths without 4x cost on every diff.
- v1 `scripts/review-plan.sh` (in 12+ active projects post-rollout today) runs OpenAI + Gemini for spec/plan review — different tool, different point in workflow, stays as-is and stays bash. **Out of MVP** = no `providers/openai.py` / `providers/gemini.py` modules in v2; they don't exist in this codebase to reduce surface area.
- This resolves Issue #13: the audit memory's claim that "DeepSeek R1 is part of /review-plan" was a hallucination from CR's learning store. v2 is the first place DeepSeek R1 is actually wired in. Issue #13 closes once v2 ships.

**Alternatives considered**:

- DeepSeek-only (no cascade): faster, cheaper, but loses the multi-model adversarial check (User Story 6 P3).
- All four providers in MVP: rejected as scope creep — Gemini reviewer Gemini 2.5 Pro flagged this exact concern in its review of this spec/plan ("scope creep — distracts from MVP, adds code that will likely go unused, violates YAGNI"). Defer until validated need.
- Refactor v1 + v2 into a shared "reviewers" abstraction: rejected — v1 is bash and stays bash (no churn); v2 is Python with its own ~80-line provider clients. The call shapes are small and stable; bridging a Python/bash boundary for shared "reviewer" code would be more complex than maintaining two small per-provider modules. v1 reviews specs; v2 reviews diffs — different orchestration semantics either way.

---

## R-8: Cross-file context for the consistency reviewer

**Decision (MVP)**: Generate a file-level `ChangeManifest` upfront (after diff capture, before reviewer dispatch) listing added/removed/renamed files. Pass it to the consistency reviewer's prompt as context, alongside the per-file diff chunk being reviewed. Symbol-level extraction is **deferred to v2.1**.

**Rationale**:

- The consistency reviewer's job is detecting drift across files (CHANGELOG vs spec vs code, file renames affecting imports, removed paths still referenced, etc.). File-level signal is sufficient for the MVP.
- ChangeManifest is built from `git diff --name-status -M` (no per-file parsing). Implementation lives in `change_manifest.py`.
- The manifest is small (typically <500 tokens) and prepended to every consistency-reviewer call.
- Other reviewers (security, correctness, tests) get only their per-file chunk — they don't need cross-file context.

**Symbol-level extraction (deferred to v2.1)**: regex-based per-language symbol extraction was originally proposed but flagged as scope creep / fragility risk during the speckit review (Gemini round-3/4). MVP ships with file-level only; symbol-level lands in v2.1 if MVP usage demonstrates the consistency reviewer's catch rate is insufficient.

**ChangeManifest shape (MVP)**:

```json
{
  "files_added": ["src/lib/new-feature.ts"],
  "files_removed": ["src/lib/old-feature.ts"],
  "files_renamed": [{"from": "src/lib/foo.ts", "to": "src/lib/bar.ts"}]
}
```

**Alternatives considered**:

- Full diff to every reviewer: token-cost prohibitive for 1000+ line diffs; no improvement on specialization.
- AST-based symbol extraction: requires per-language tooling; out of scope for v2 MVP and v2.1.
- Regex-based symbol extraction: deferred per scope-creep concern above.

---

## R-9: Default base branch detection

**Decision**: Try `origin/HEAD` first (resolved via `git symbolic-ref refs/remotes/origin/HEAD`). If absent or invalid, fall back through ordered list: `main`, `master`, `develop`, `staging`. If none of those exist as local refs, error out with a helpful message asking the user to specify `--base` explicitly.

**Rationale**:

- `origin/HEAD` is the right answer when set, but not all repos have it (e.g., some org defaults skip it; users sometimes clone with `--single-branch`).
- Fallback chain handles common conventions in priority order.
- Wrong base = empty diff (best case) or massive diff with thousands of unrelated changes (worst case, expensive token spend). Erroring out beats guessing.
- Detection logic lives in `scripts/review_plan_v2/diff_capture.py`; tested via `tests/integration/test_detached_head.py` against fixtures `09-detached-head/` and `10-no-upstream/`.

**Alternatives considered**:

- Always require `--base`: noisier UX; FR-001 specifies a default.
- Hardcode `main` only: breaks for repos using `master` or `staging`.
- Detect via `git rev-parse @{u}`: that's "upstream of current branch," not "default base" — different concept.

---

## Summary of resolved unknowns

| # | Unknown | Resolution |
|---|---|---|
| 1 | DeepSeek R1 API contract | Chat Completions, `deepseek-reasoner`, strip `reasoning_content`; `urllib.request.urlopen` from Python stdlib |
| 2 | Anthropic cascade integration | Messages API + `claude-sonnet-4-6`, cascade triggers on high-risk paths only; same `urllib`-based client |
| 3 | Tests + provider mocking | Python stdlib `unittest` + `unittest.mock.patch` (units) + `http.server` fixture in `tests/support/fixture_server.py` (integration). NO bats-core, NO pytest — per charter |
| 4 | `.coderabbit.yaml` parsing | `yq` (go binary) via `subprocess.run`; NO `pyyaml` (zero `pip install` deps). v2-specific config in separate `.review-plan-v2.yaml` (NO extensions to CR's schema) |
| 5 | Auto-pause state tracking | `~/.claude/review-plan-v2/auto-pause-state.json` + `fcntl.flock` (Python stdlib; kernel auto-release on `kill -9`). PID + timestamp recorded for defense-in-depth |
| 6 | Diff chunking | Per-file with 1500-line sub-chunk threshold; rough `chars/4` token estimate gates against DeepSeek 64k context |
| 7 | Default model selection | DeepSeek R1 broad + Claude Sonnet cascade ONLY in MVP; OpenAI/Gemini deferred (FR-003 SHOULD, not MUST) |
| 8 | Cross-file context | File-level ChangeManifest (added/removed/renamed) passed to consistency reviewer. Built in `change_manifest.py`. Symbol-level extraction **deferred to v2.1** |
| 9 | Default base branch detection | `origin/HEAD` → `main` → `master` → `develop` → `staging` → error with helpful message. Detection lives in `diff_capture.py` |

All Technical Context items in `plan.md` are now non-NEEDS-CLARIFICATION.
