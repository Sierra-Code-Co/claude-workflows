# Data Model — /review-plan v2

**Phase**: 1 (Design & Contracts)
**Date**: 2026-04-27

Entities the tool operates on internally. Not a database schema — `review-plan-v2` has no persistent storage beyond the auto-pause state file. These are the conceptual data structures passed between orchestrator → reviewers → aggregator → output.

---

## Diff

The set of changes the tool reviews. Captured once at startup via `git diff $base...HEAD` (or `--type` variants).

| Field | Type | Notes |
|---|---|---|
| `base_ref` | string | git ref (e.g., `main`, `staging`) |
| `head_sha` | string | current HEAD commit SHA |
| `files` | `FileDiff[]` | one per changed file |

### FileDiff

| Field | Type | Notes |
|---|---|---|
| `path` | string | repo-relative path |
| `is_binary` | bool | excluded from LLM review (FR-018) |
| `is_filtered` | bool | matched a `path_filters` exclusion in `.coderabbit.yaml` |
| `hunks` | `Hunk[]` | parsed unified diff hunks |
| `language` | string \| null | inferred from file extension; informs which static analyzers apply |

### Hunk

| Field | Type | Notes |
|---|---|---|
| `start_line` | int | first line in head version |
| `length` | int | number of lines |
| `lines` | string | raw diff text including +/- prefixes |

---

## ChangeManifest

Cross-file context structure built once after diff capture. Passed alongside per-file diff chunks when calling the consistency reviewer (NOT to security/correctness/tests reviewers — they don't need cross-file context). Per research.md R-8.

| Field | Type | Notes |
|---|---|---|
| `files_added` | string[] | new files in diff |
| `files_removed` | string[] | deleted files |
| `files_renamed` | `{from: string, to: string}[]` | from `git diff --name-status -M` |
| `symbols_changed` | `SymbolChange[]` | **deferred to v2.1** — MVP ships with file-level only |

### SymbolChange (deferred)

Symbol-level cross-references (function/class/exported-name extraction via regex) are deferred from MVP per the round-3/4 review scope-creep concern: regex parsing across multiple languages is fragile and adds maintenance cost for marginal MVP value. The consistency reviewer ships with file-list-only context — sufficient for catching common cross-doc drift like "CHANGELOG mentions feature X but no file added" or "module renamed but README still references old path."

Example consistency-reviewer prompt input (MVP):

```text
[Cross-file change manifest]
- files_added: ["src/lib/new-feature.ts"]
- files_removed: []
- files_renamed: [{"from": "src/lib/foo.ts", "to": "src/lib/bar.ts"}]

[Per-file diff chunk being reviewed]
+++ b/src/api/login.ts
... (the actual diff for this file) ...
```

The reviewer is prompted to use the manifest to detect inconsistencies (e.g., "this file imports from 'src/lib/foo' but foo was renamed to bar"). Symbol-level catches like "checkToken still called but removed from auth.ts" land in v2.1 if MVP usage justifies the regex maintenance burden.

---

## Reviewer

A specialized review perspective. Multiple reviewers run in parallel.

| Field | Type | Notes |
|---|---|---|
| `name` | string | `security`, `correctness`, `tests`, `consistency` (default set) |
| `system_prompt_path` | string | e.g., `scripts/review_plan_v2/prompts/security.md` (canonical: `<reviewer-name>.md`, no `-reviewer` suffix; underscore-separated module path) |
| `model` | string | provider+model identifier (e.g., `deepseek/deepseek-reasoner`) |
| `cascade_model` | string \| null | optional second-opinion model invoked on high-risk paths only |
| `applies_to_paths` | string[] | glob patterns that scope this reviewer; empty = all paths |

**Default config** ships with 4 reviewers, each on `deepseek-reasoner` with `claude-sonnet-4-6` cascade for `security` and `correctness` only.

---

## StaticAnalyzerRun

A deterministic pre-LLM check.

| Field | Type | Notes |
|---|---|---|
| `name` | string | `gitleaks`, `markdownlint`, `actionlint`, `shellcheck` |
| `command` | string[] | argv-style. `gitleaks` runs against **only the changed files** (staged in a temp dir or via `--source <tmpdir>`), NOT the whole repo, to keep wall-clock under 10s and avoid surfacing pre-existing baselined secrets. Honors `.gitleaks.toml` (allowlist + rules) if present. A finding is "actionable" only if it lives in lines added/modified by the current diff AND is not allowlisted. |
| `applicable_globs` | string[] | which file patterns trigger this analyzer (e.g., `markdownlint` → `**/*.md`) |
| `output_parser` | callable | `parse_output(stdout, stderr) -> List[Finding]` method on the `StaticAnalyzer` subclass in `scripts/review_plan_v2/analyzers/<name>.py` |
| `is_installed` | bool | computed at startup; if false, analyzer is gracefully skipped (FR-005) |

---

## Finding

The canonical output unit. Produced by reviewers (LLMs) and analyzers (deterministic tools); flow into the aggregator; rendered to plain text or JSON for the user.

| Field | Type | Notes |
|---|---|---|
| `file` | string | repo-relative path |
| `line` | int | exact line (1-based; 0 if whole-file finding) |
| `line_end` | int \| null | optional end-line for ranged findings; null when single-line |
| `severity` | enum | `actionable` \| `nit` \| `info` (FR-007) |
| `category` | enum | `bug` \| `security` \| `correctness` \| `tests` \| `consistency` \| `style` \| `prose` \| `docs` \| `secrets` \| `nit` (mirrors `types.py` + aggregator `SOFT_CATEGORIES`) |
| `message` | string | the finding text (single-line preferred for grep-ability) |
| `suggested_fix` | string \| null | optional unified diff snippet, like CR's "Suggested fix" |
| `sources` | `Source[]` | who flagged this (one or more reviewers/analyzers — multi-source = high-confidence) |
| `confidence` | enum | `high-confidence` (multi-source) \| `single-source` (one reviewer/analyzer) |

### Source

| Field | Type | Notes |
|---|---|---|
| `kind` | enum | `reviewer` \| `analyzer` |
| `name` | string | reviewer name or analyzer name |
| `model` | string \| null | for `kind=reviewer`, the model that produced this |

---

## RunConfig

Resolved at startup from CLI flags + `.coderabbit.yaml` + `.review-plan-v2.yaml` + env vars + tool defaults.

| Field | Type | Notes |
|---|---|---|
| `base_ref` | string | from `--base` or detected via `origin/HEAD` → `main` → `master` → `develop` → `staging` chain (research.md R-9) |
| `diff_type` | enum | `all` \| `committed` \| `uncommitted` |
| `output_mode` | enum | `plain` \| `agent` (JSON) |
| `reviewers` | `Reviewer[]` | default 4: security/correctness/tests/consistency, all on DeepSeek R1, security+correctness with Claude Sonnet cascade |
| `analyzers` | `StaticAnalyzerRun[]` | default 4: gitleaks (always), markdownlint (md files), actionlint (workflow yml), shellcheck (sh files); skipped if not installed |
| `path_instructions` | `PathInstruction[]` | from `.coderabbit.yaml` (CR schema, no extensions) |
| `path_filters` | string[] | from `.coderabbit.yaml` |
| `high_risk_paths` | `HighRiskPath[]` | from `.review-plan-v2.yaml` (v2-specific) |
| `max_concurrency` | int | from `.review-plan-v2.yaml` or `--max-concurrency`; default 4. Caps total parallel reviewer×chunk×provider calls. |
| `auto_pause_n` | int | from `.review-plan-v2.yaml` or `--auto-pause-n`; default 3 |
| `force_full` | bool | from `--force-full` |
| `cost_log_path` | string | default `~/.claude/review-plan-v2/cost-log.jsonl` |

### PathInstruction (from `.coderabbit.yaml`)

| Field | Type | Notes |
|---|---|---|
| `path_glob` | string | from yaml `path_instructions[].path` |
| `instructions` | string | prompt-prefix text prepended to reviewer system prompts when files matching this glob are in the diff |

**Semantics — two-layer enforcement**:

1. **Pre-reviewer (prompt guidance)**: the `instructions` text is prepended to the reviewer's system prompt for files matching `path_glob`. LLM obedience is best-effort — for the common patterns ("skip prose nits", "ignore X"), the LLM usually obeys; for novel ones it may not.
2. **Post-reviewer (best-effort severity demotion in the aggregator)**: if the `instructions` text contains a recognized suppression keyword (`skip`, `ignore`, `do not flag`, `not actionable`) AND the finding's `category` matches a recognized soft category (`style`, `prose`, `docs`, `nit`), the aggregator demotes severity from `actionable`/`nit` to `info`. The finding is still surfaced (so the user sees what the LLM caught despite instructions), but it does not gate the push (info-tier never sets exit 1). This honors user intent without silently deleting LLM findings — addresses the principle-of-least-surprise concern while avoiding the contradiction of "deterministic filter on freeform text."

Hard-suppression categories (`actionable` security/correctness findings) are NEVER demoted by `path_instructions`. Use `path_filters` (next entity) if a file should not be reviewed at all.

`path_filters` (CR's `path_filters` array, also from `.coderabbit.yaml`): exclusion globs applied at diff-capture time. Files matching `path_filters` are never sent to any reviewer or analyzer. Stored on `RunConfig.path_filters`. This is the only mechanism for guaranteed exclusion.

PathInstruction is read **as-is from `.coderabbit.yaml`**; v2 does not extend the CR schema. v2-specific config (which paths are "high-risk" for cascade) lives in a separate file:

### HighRiskPath (from `.review-plan-v2.yaml`)

| Field | Type | Notes |
|---|---|---|
| `path_glob` | string | which files trigger cascade |
| `reason` | string | optional human-readable rationale (informational; logged for cost/audit) |

Schema of `.review-plan-v2.yaml`:

```yaml
high_risk_paths:
  - path: 'src/**/auth/**'
    reason: 'authentication code; correctness is critical'
  - path: 'src/**/db/schema.*'
    reason: 'schema changes can break production'

max_concurrency: 4   # cap on parallel reviewer×chunk×provider calls
auto_pause_n: 3      # default 3
```

---

## Run

A single end-to-end invocation. One `Run` per CLI invocation.

| Field | Type | Notes |
|---|---|---|
| `run_id` | string | UUID; used in cost-log + auto-pause state |
| `started_at` | iso8601 | |
| `config` | `RunConfig` | resolved at start |
| `diff` | `Diff` | captured at start |
| `analyzer_results` | `Finding[]` | from static analyzers (deterministic, fast) |
| `reviewer_results` | `Finding[]` | from LLM reviewers (parallel) |
| `findings` | `Finding[]` | aggregated, deduped, severity-tiered |
| `exit_code` | int | 0 if no actionables, non-zero otherwise (FR-014) |
| `wall_clock_ms` | int | for SC-002 verification |
| `cost_usd` | float | sum of provider tokens × prices; logged to cost-log |
| `provider_calls` | `ProviderCall[]` | one per LLM invocation; includes input/output tokens, latency, success |

### ProviderCall

| Field | Type | Notes |
|---|---|---|
| `provider` | string | `deepseek` \| `anthropic` \| `openai` \| `gemini` |
| `model` | string | exact model identifier |
| `reviewer` | string | which reviewer this call was for |
| `input_tokens` | int | |
| `output_tokens` | int | |
| `latency_ms` | int | |
| `status` | enum | `success` \| `transport_error` \| `parse_error` \| `empty_response` \| `quota_exceeded` |
| `cost_usd` | float | |

---

## State (auto-pause)

Persisted across runs in `~/.claude/review-plan-v2/auto-pause-state.json`.

```json
{
  "<git-common-dir>:<branch>": {
    "last_run_commits": ["sha1", "sha2", ...],
    "consecutive_trivial_runs": 0,
    "last_updated": "2026-04-27T22:00:00Z",
    "holder_pid": 12345,
    "holder_started_at": "2026-04-27T22:00:00Z"
  }
}
```

The state key uses `git rev-parse --git-common-dir` (NOT the working-tree absolute path). `--git-common-dir` returns the same path for every worktree of a single underlying repository, so the auto-pause counter is shared correctly across `git worktree`-based parallel work — a user iterating on the same branch in two worktrees gets one counter, not two.

`consecutive_trivial_runs` increments after each run that produced 0 `actionable` findings. Reset to 0 on any run with `actionable` findings or when `--force-full` is passed. When `>= auto_pause_n` (default 3), subsequent runs skip the LLM-reviewer phase but still run static analyzers.

---

## Acceptance criteria mapping (for /speckit.tasks)

Each User Story P1–P3 maps to data-model entities used:

| Spec User Story | Entities exercised | Verifying fixture / test |
|---|---|---|
| P1: Pre-push without rate limits | `Diff`, `Reviewer`, `Run.exit_code`, `RunConfig` | `tests/fixtures/02-pascalcase-bug.diff` |
| P1: Specialized parallel reviewers | `Reviewer[]` (4 distinct), `Finding.sources[]`, aggregator dedup | `tests/fixtures/03-sql-injection.diff`, `tests/fixtures/08-cross-doc-drift.diff` |
| P1: Project-aware via `.coderabbit.yaml` | `PathInstruction[]`, `RunConfig.path_filters[]` | `tests/integration/test_path_instructions.py` |
| P2: Drop-in CLI | `RunConfig.output_mode`, exit codes, flag parsing | `tests/integration/test_cli_flags.py` |
| P2: Static analyzer ensemble | `StaticAnalyzerRun[]`, `analyzer_results` flowing into `findings` | `tests/fixtures/04-secret-leak.diff` |
| P3: Adversarial cascade | `Reviewer.cascade_model`, `HighRiskPath` (from `.review-plan-v2.yaml`), `Finding.confidence` | `tests/fixtures/03-sql-injection.diff` (matched by a high-risk path glob) |
| P3: Auto-pause-after-N | `State.consecutive_trivial_runs`, `--force-full` | `tests/integration/test_auto_pause_e2e.py` |
