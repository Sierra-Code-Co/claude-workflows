# Quickstart — review-plan-v2

**Phase**: 1 (Design & Contracts)

How to install, configure, and use the tool. Mirrors the User Stories from the spec — each P1/P2/P3 story has a corresponding "verify it works" command here.

---

## Install

```bash
# Required system tools (macOS via brew; equivalent on Linux)
brew install python@3.12 jq yq gitleaks markdownlint-cli actionlint shellcheck

# Required: DeepSeek API key (broad-pass reviewer)
echo 'export DEEPSEEK_API_KEY=sk-...' >> ~/.zshrc

# Recommended: Anthropic API key for Claude Sonnet cascade on high-risk paths
echo 'export ANTHROPIC_API_KEY=sk-ant-...' >> ~/.zshrc

source ~/.zshrc
```

### Three ways to provide API keys (pick whichever fits your workflow)

The `review-plan-v2` bash entrypoint picks up keys from any of these sources, in order:

1. **Per-project `.env` at the git repo root** (recommended for project-specific keys). The entrypoint runs `git rev-parse --show-toplevel` and, if found, **parses** `<root>/.env` with a strict KEY=VALUE allowlist parser — it does **not** `source` the file, so `$(...)` / backticks in the file cannot execute. Only allowlisted key names are exported into the python orchestrator's env: `DEEPSEEK_API_KEY*`, `ANTHROPIC_API_KEY*`, `OPENAI_API_KEY*`, `GEMINI_API_KEY*`, `REVIEW_PLAN_V2_*`. Anything else (incl. `PATH`, `LD_PRELOAD`, `PYTHONPATH`) is silently dropped to prevent hijack. Most projects in the fleet already have this `.env` pattern.
2. **Shell env** — the `~/.zshrc` exports above. Works from anywhere.
3. **Wrapper-strip fallback**. If you run Claude Code through a wrapper that strips `ANTHROPIC_API_KEY` (e.g., the subscription-auth wrapper at `~/bin/claude` that runs `env -u ANTHROPIC_API_KEY claude ...` so CC bills the subscription instead of the API), v2 won't see the key when invoked from inside CC. Workaround: also export `ANTHROPIC_API_KEY_FALLBACK="$ANTHROPIC_API_KEY"` in your `~/.zshrc`. The wrapper only strips the primary name; v2's entrypoint detects the fallback and reconstitutes the primary at run-time. Same pattern works for `DEEPSEEK_API_KEY_FALLBACK`.

**Python 3.10+ required** (stdlib only — no `pip install`, no `requirements.txt`). Ships on macOS 13+ and all supported Linux distros. The `brew install python@3.12` line above is belt-and-suspenders for older macOS.

**No bats-core, no pytest** — tests use Python stdlib `unittest` (`python3 -m unittest discover`). Locking uses Python stdlib `fcntl.flock` (kernel auto-releases on process exit).

OpenAI gpt-5.3-codex and Gemini 2.5 Pro are used by v1 (`/review-plan` for spec/plan review), NOT by v2 in MVP. Don't bother setting those keys for v2.

The orchestrator (`scripts/review-plan-v2.sh` thin bash entrypoint + `scripts/review_plan_v2/` Python module) ships with claude-workflows and propagates to active projects via `propagate-skill.sh review-plan-v2`.

## Configure (optional)

v2 reads two YAML files:

1. **`.coderabbit.yaml`** at repo root — same file CR's PR-side bot uses. v2 reads `path_filters` and `path_instructions` as-is. **No extensions** to CR's schema.
2. **`.review-plan-v2.yaml`** at repo root (optional) — v2-specific config:

```yaml
# .review-plan-v2.yaml
high_risk_paths:
  - path: 'src/**/auth/**'
    reason: 'authentication code; correctness is critical'
  - path: 'src/**/db/schema.*'
    reason: 'schema changes can break production'

max_concurrency: 4   # caps parallel reviewer×chunk×provider calls
auto_pause_n: 3      # default 3 — auto-pause after N consecutive trivial runs
dedup_line_window: 5 # default ±5 — aggregator merges findings within this line range
```

Without `.review-plan-v2.yaml`, defaults apply (no high-risk paths → no cascade unless `--cascade` flag forces it; max-concurrency 4; auto-pause-N 3).

---

## First run — verify P1 (User Story 1: pre-push without rate limits)

From any repo with a feature branch:

```bash
review-plan-v2 --plain --base main
```

Expected: review completes in < 2 minutes for diffs up to 1000 lines, no rate-limit errors. Findings (if any) printed in the format defined in `contracts/output-format.md`.

**Verify the no-rate-limit claim:** run 10 times in succession. None should fail with provider rate-limit errors (FR-008).

---

## Verify P1 (User Story 2: specialized parallel reviewers)

```bash
# Use a known fixture diff that has issues only one specialization would catch
review-plan-v2 --plain --base main --agent | jq 'select(.type == "finding") | {category, sources}'
```

Expected: a SQL injection in the diff is flagged by the `security` reviewer and not by `correctness`/`tests`/`consistency`. A doc-vs-code mismatch is flagged by `consistency` and not by `security`.

---

## Verify P1 (User Story 3: project-aware via .coderabbit.yaml)

The repo has a `.coderabbit.yaml` with `path_instructions` for `**/*.md` saying "skip prose nits."

```bash
# Diff that contains both: a prose nit and a broken markdown link
review-plan-v2 --plain --base main 2>&1 | grep '\.md:'
```

Expected: only the broken link is reported. Prose nits are filtered.

---

## Verify P2 (User Story 4: drop-in CLI)

```bash
# Replace the existing pre-push instruction in ~/.claude/CLAUDE.md from
#   coderabbit review --plain --base main
# to
#   review-plan-v2 --plain --base main
# and verify the workflow still works end-to-end
```

A script that pipes the tool's output to a downstream consumer should work identically:

```bash
review-plan-v2 --plain --base main | grep '^\[ACTIONABLE\]' | wc -l
```

Same line shape as `coderabbit review --plain` — same grep/awk pipelines work unchanged.

---

## Verify P2 (User Story 5: static analyzer ensemble)

```bash
# Add a fake AWS access key string to a file, then:
review-plan-v2 --plain --base main 2>&1 | grep '\[secrets\]'
```

Expected: gitleaks catches it as `[ACTIONABLE] ... [secrets]` within seconds — before the LLM passes complete (SC-006).

```bash
# Verify analyzers run in parallel: time the run
time review-plan-v2 --plain --base main --no-cascade
```

Expected: total wall-clock < (sum of analyzer times) + (slowest LLM reviewer time), confirming parallelism.

---

## Verify P3 (User Story 6: adversarial multi-model cascade)

In `.review-plan-v2.yaml`, configure a high-risk path (NOT in `.coderabbit.yaml` — v2 doesn't extend CR's schema):

```yaml
# .review-plan-v2.yaml
high_risk_paths:
  - path: 'src/**/auth/**'
    reason: 'High-risk auth code. Apply cascade.'
```

Run on a diff touching `src/lib/auth/session.ts`:

```bash
review-plan-v2 --agent --base main | jq 'select(.type == "finding") | .confidence'
```

Expected: at least some findings tagged `high-confidence` (when both DeepSeek and Claude agree). Other findings tagged `single-source`.

To verify cascade actually invoked Claude:

```bash
review-plan-v2 --agent --base main | jq 'select(.type == "summary") | .providers_called[] | select(.provider == "anthropic")'
```

Expected: a non-zero `calls` count, confirming cascade ran.

---

## Verify P3 (User Story 7: auto-pause-after-N)

```bash
# Run review on a clean branch 3 times in a row (e.g., make trivial whitespace commits)
for i in 1 2 3; do
  git commit --allow-empty -m "trivial $i" && review-plan-v2 --plain --base main
done

# 4th run should auto-pause:
git commit --allow-empty -m "trivial 4"
review-plan-v2 --plain --base main
echo "Exit: $?"
# Expected output ends with: "=== Auto-paused (last 3 runs trivial) — pass --force-full to override"
# Expected exit code: 0  (NOT 4 — auto-pause is informational, not a "block push" condition)

# Override:
review-plan-v2 --plain --base main --force-full
# Runs all reviewers normally
```

**Why exit 0?** A pre-push hook that does `review-plan-v2 || exit 1` would otherwise block pushes when the tool intentionally skipped LLM passes due to no recent actionable findings. Auto-pause is a "nothing changed substantively, save your tokens" signal, not a "block this push" signal.

---

## Common configurations

### Strictest (cascade everything)

```yaml
# .review-plan-v2.yaml  (NOT .coderabbit.yaml — v2 doesn't extend CR's schema)
high_risk_paths:
  - path: '**/*'
    reason: 'High-risk repo. Apply cascade everywhere.'
```

Cost: ~5x default. Use for repos where wrong calls have outsized cost (auth/payments).

### Faster (DeepSeek-only, no cascade, no static analyzers)

```bash
review-plan-v2 --plain --base main --no-cascade --no-static-analyzers
```

Cost: ~$0.05 per 1000-line diff. Wall: < 60s. Use for high-volume iterative pushes where speed > thoroughness.

### CI mode (structured output for downstream tooling)

```bash
review-plan-v2 --agent --base origin/main --max-cost-usd 0.50
```

Output is NDJSON; the `--max-cost-usd` cap aborts the run if estimated cost would exceed the limit.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Exit 2 immediately on launch | No LLM API keys set | Set `DEEPSEEK_API_KEY` (or another supported provider) |
| All findings show `single-source` | Cascade disabled (no `ANTHROPIC_API_KEY` or `--no-cascade`) | Set the key, remove the flag |
| `gitleaks: command not found` warning | Static analyzer not installed | `brew install gitleaks` (other analyzers similar) — tool gracefully skips missing analyzers |
| Tool runs but takes > 5 minutes | Diff too large; chunking is happening | Try `--no-cascade` or scope the diff smaller |
| Findings duplicated across reviewers | Aggregator dedup miss | File a bug; expected behavior is dedup with `high-confidence` tag |

---

## Comparison vs. CodeRabbit CLI

| Aspect | `coderabbit review --plain` | `review-plan-v2 --plain` |
|---|---|---|
| Rate limits | Pro plan limit | None (bound by your API quota) |
| Cost | $30/mo subscription | ~$0.05–0.20 per run |
| Models | CR's curated stack | Your choice (DeepSeek default; Claude/OpenAI/Gemini optional) |
| Static analyzers | gitleaks, markdownlint, actionlint, shellcheck | Same (configurable) |
| Path instructions | `.coderabbit.yaml` | `.coderabbit.yaml` (same file, drop-in) |
| Repo-specific learnings ("Based on learnings: X") | Yes (RAG) | No (out of scope for v2) |
| Output format | `--plain` text + `--agent` structured | Same |
| GitHub PR posting | Yes (the bot) | No (this tool is local-only) |

**The PR-side CR bot remains useful** as the safety net for what this tool's local pre-push pass missed. Use both.
