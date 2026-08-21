# CLI Flag Contract — review-plan-v2

**Phase**: 1 (Design & Contracts)

Defines the exact command-line interface. Designed for **drop-in compatibility** with `coderabbit review --plain` so the global CLAUDE.md "Pre-push" section can reference either tool with minimal change (FR-012).

## Synopsis

```text
review-plan-v2 [OPTIONS]
```

## Options (mirrors `coderabbit review` where possible)

| Flag | Argument | Default | Status | Notes |
|---|---|---|---|---|
| `--plain` | (none) | on | mirrors CR | Plain-text output, no color, no interactive prompts |
| `--agent` | (none) | off | mirrors CR | Structured JSON output for agent workflows; supersedes `--plain` |
| `--base` | `<branch>` | `origin/HEAD` then `main` | mirrors CR | Base branch for diff comparison |
| `--type` | `all` \| `committed` \| `uncommitted` | `all` | mirrors CR | Diff scope |
| `-c, --config` | `<path>` | `./.coderabbit.yaml` | mirrors CR | Override config file location |
| `--no-color` | (none) | off | mirrors CR | Disable color in plain output |
| `-v, --version` | (none) | — | mirrors CR | Print version and exit |
| `-h, --help` | (none) | — | mirrors CR | Print help and exit |
| `--force-full` | (none) | off | **v2-only** | Bypass auto-pause-after-N (run all reviewers regardless of state) |
| `--auto-pause-n` | `<int>` | 3 | **v2-only** | Override auto-pause threshold |
| `--max-concurrency` | `<int>` | 4 | **v2-only** | Cap on parallel reviewer×chunk×provider calls. Prevents resource contention and provider 429s on large diffs. |
| `--dedup-window` | `<int>` | 5 | **v2-only** | Line-overlap window for the aggregator's dedup (lines). |
| `--no-static-analyzers` | (none) | off | **v2-only** | Skip gitleaks/markdownlint/etc. (LLM reviewers only) |
| `--no-cascade` | (none) | off | **v2-only** | Disable Claude cascade on high-risk paths (DeepSeek-only) |
| `--max-cost-usd` | `<float>` | unset | **v2-only** | Hard cap; abort run if estimated cost exceeds (FR-009 graceful degradation) |
| `--dry-run` | (none) | off | **v2-only** | Print what would be reviewed (file list, model selection, estimated cost) without invoking LLMs |
| `--require-changes` | (none) | off | **v2-only** | Exit 2 if 0 files were reviewed. Off by default: an empty diff is genuinely nothing to do and has nothing to push either, and `\|\| exit 1` pre-push hooks are a documented use. CI jobs that mean "prove you reviewed this" should pass it. |
| `--strict-config` | (none) | off | **v2-only** | Treat malformed `.coderabbit.yaml`/`.review-plan-v2.yaml` or missing `yq` as a hard config error (exit 5). Default off — drop-in pre-push usage tolerates degraded config with stderr warning |

## Drop-in compatibility check

The user's existing global CLAUDE.md "Pre-push" instruction is:

```bash
coderabbit review --plain --base main
```

After v2 ships, this becomes:

```bash
review-plan-v2 --plain --base main
```

**One-line edit**, identical semantics. Tested via `tests/integration/test_cli_flags.py`.

## Exit codes (FR-014)

| Code | Meaning |
|---|---|
| 0 | No actionable findings — safe to push. Includes: clean diff, only nits/info, OR auto-paused (notice on stdout). **A run that reviewed ZERO files also exits 0** (empty diff, or every file excluded by `path_filters`) — the exit code alone cannot distinguish it from a full clean review, so such runs always print a `[NOTHING REVIEWED]` banner to stderr naming the cause. Pass `--require-changes` to make it exit 2 instead (T005k). |
| 1 | At least one `actionable` finding (gate; surface to user before push) |
| 2 | Tool error (missing required dep that has no degradation path, invalid `--base`, network failure with all providers) |
| 3 | Aborted via `--max-cost-usd` cap (FR-021) |
| 5 | Config error (malformed YAML or missing `yq`) — **only emitted with `--strict-config`**. Without `--strict-config`, the same condition produces a stderr warning and exit follows findings (0/1) so drop-in pre-push usage is not blocked by config drift. CI pipelines that want to gate on config integrity should pass `--strict-config`. |

**Auto-pause exits 0** — not a distinct error code. A pre-push hook that does `|| exit 1` would otherwise block legitimate pushes when the tool intentionally skipped LLM passes due to no recent actionable findings. The auto-paused state is surfaced via a stdout notice ("Auto-paused (last 3 runs trivial)…") and via the `auto_paused: true` field in `--agent` mode summary, not via exit code.

Exit 0 vs. 1 lets pre-push hooks gate on `actionable`-only:

```bash
review-plan-v2 --plain --base main || { echo "actionable findings — fix before pushing"; exit 1; }
```

## Environment variables

| Var | Required? | Default | Notes |
|---|---|---|---|
| `DEEPSEEK_API_KEY` | yes for default config | — | Required for the broad-pass reviewers. If absent and no other provider is configured, tool exits with code 2 |
| `ANTHROPIC_API_KEY` | only if cascade is enabled | — | If absent, cascade silently disabled with note |
| `OPENAI_API_KEY` | optional | — | Only used if config replaces DeepSeek with OpenAI |
| `GEMINI_API_KEY` | optional | — | Only used if config adds Gemini as a reviewer |
| `REVIEW_PLAN_V2_LOG_DIR` | no | `~/.claude/review-plan-v2/logs` | Where per-provider stderr logs go |
| `REVIEW_PLAN_V2_STATE_FILE` | no | `~/.claude/review-plan-v2/auto-pause-state.json` | Auto-pause state file path |

Provider HTTP base URLs are also overridable for testing (`DEEPSEEK_API_BASE`, etc.) — see research.md R-3.

## Examples

```bash
# Standard pre-push (drop-in for coderabbit review --plain --base main)
review-plan-v2 --plain --base main

# Faster mode: skip cascade, no static analyzers (DeepSeek only)
review-plan-v2 --plain --base main --no-cascade --no-static-analyzers

# CI mode: structured JSON, fail on cost cap
review-plan-v2 --agent --base origin/main --max-cost-usd 0.50

# Force a full review (bypass auto-pause)
review-plan-v2 --plain --base main --force-full

# Dry run: see what would happen
review-plan-v2 --dry-run --base main
```
