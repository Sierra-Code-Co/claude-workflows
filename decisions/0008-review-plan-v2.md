# 0008 — /review-plan v2: Python orchestrator + drop-in CR replacement

**Status:** active
**Date:** 2026-04-27
**Tags:** review-plan, python, llm, gitleaks, fcntl

## Context

The existing `/review-plan` skill (v1, bash) reviews specs/plans pre-implementation via OpenAI + Gemini. After hitting CodeRabbit Pro CLI rate limits during routine pre-push usage, we needed a local CR-equivalent that:

1. Reviews **diffs pre-push** (not specs).
2. Has no vendor rate limits (uses BYO API keys).
3. Drops in for `coderabbit review --plain --base main` with a one-line edit in CLAUDE.md.
4. Coexists with v1 — different point in the workflow, different concern.

Designed via the speckit chain (specify → plan → tasks → /review-plan → implement) over 4 review rounds. Round 2 surfaced a RED rating on the bash architecture; round 3 onward used Python stdlib instead.

## Decision

Ship `/review-plan-v2` as a **Python module** under `scripts/review_plan_v2/` with a 5-line bash entrypoint at `scripts/review-plan-v2.sh`. Stdlib only — no `pip install`, no `requirements.txt`. Tests use `unittest`. State locking uses `fcntl.flock`. Concurrency uses `concurrent.futures.ThreadPoolExecutor`. HTTP via `urllib`. YAML via subprocess to `yq` (mikefarah). Default reviewers: 4 specialized (security, correctness, tests, consistency) over DeepSeek R1 + Anthropic Claude Sonnet cascade on `.review-plan-v2.yaml`-flagged high-risk paths. Static analyzers: gitleaks runs sequentially **first** (halts run on actionable secrets, never transmits them to LLMs); markdownlint, actionlint, shellcheck run in parallel.

Specifically:

1. **Python over bash.** Bounded-parallelism pools, file locking, mock HTTP fixtures, and assertion-based tests are stdlib-native in Python. Reproducing them in bash (`concurrency.sh`, `mkdir`-as-mutex, `_lib.sh`, ad-hoc fixture server) violates YAGNI. Python with stdlib only adds zero install steps over bash.
2. **v1 stays bash + untouched.** No shared library across the language boundary. v2 has its own ~80-line provider modules. Bridging Python ↔ bash for shared "reviewer" code would be more complex than maintaining two thin per-provider modules.
3. **Separate `.review-plan-v2.yaml` config.** Don't extend CR's `.coderabbit.yaml` schema — read it as-is per FR-004; v2-specific config (high_risk_paths, max_concurrency, auto_pause_n, dedup_line_window) lives in its own file.
4. **`fcntl.flock` over `mkdir`-as-mutex.** Kernel auto-releases the lock on `kill -9`; no stale-lock cleanup needed. Single context manager spans the full read-modify-write.
5. **Stdlib `unittest` only.** No `pytest`, no `bats-core`. Stdlib ships with Python 3.10+ — not a "test runner framework" in the charter sense.
6. **Sequential gitleaks-first.** Security: never send a secret to external LLMs. On actionable secret detection, halt with exit 1 after running other local analyzers. Line-overlap filter scopes to the diff so pre-existing baselined secrets don't block.
7. **MVP providers = DeepSeek R1 + Claude Sonnet cascade.** OpenAI/Gemini deferred (FR-003 SHOULD, not MUST) — they remain in v1 for spec/plan review.
8. **Drop-in CLI flag set.** Mirrors `coderabbit review --plain` exactly; v2-only flags (`--force-full`, `--strict-config`, `--max-concurrency`, etc.) added without breaking compat.
9. **Auto-pause exits 0 with notice, not exit 4.** A pre-push hook that does `|| exit 1` would otherwise block legitimate pushes when the tool intentionally skipped LLM passes due to no recent actionable findings.
10. **Config-error exit 5 only with `--strict-config`.** Default behavior is drop-in friendly (warning + exit follows findings); CI can opt into strict mode.

## Why

- Round-2 Gemini review flagged bash as the wrong tool for parallel HTTP calls + state locking + mocked tests. Round 3+ in Python: both reviewers improved to YELLOW with smaller, tractable issues.
- DeepSeek R1 is ~$0.55/$2.19 per M tokens (vs. Claude Sonnet $3/$15) and quality is high enough for broad-pass. Sonnet cascade on critical paths gives multi-model second opinion without 4× cost on every diff.
- The CR PR-side bot remains the safety net for what the local pass missed — local + remote complement each other.

## Consequences

**Enables:**

- Pre-push gate without burning a CR Pro rate-limit slot.
- One-line swap in `dotfiles/claude/CLAUDE.md` "Pre-push" section once SC-001 catch parity is validated.
- Specialized reviewers can be tuned/extended per repo via prompts/ markdown files.
- Cascade activates only on configured high-risk paths — opt-in cost increase.

**Commits us to:**

- Maintaining a Python module alongside the bash v1. They share no code.
- DeepSeek + Anthropic API contracts. If either changes shape, providers/{deepseek,anthropic}.py need updates.
- yq (mikefarah's go binary) as a runtime dep for project-aware path filtering. Without it, the tool degrades to no-config mode.

**Prevents:**

- Adding `pip install` / `requirements.txt` (charter compliance).
- Extending `.coderabbit.yaml` schema (compatibility with CR's own bot).

## Verification

- 48 tests pass: `PYTHONPATH=scripts python3 -m unittest discover -s tests`
- `shellcheck --severity=warning scripts/review-plan-v2.sh` clean
- End-to-end smoke against this repo: `./scripts/review-plan-v2.sh --plain --base main` exits 0 on a no-diff state
- SC-001 catch parity validation against real CR runs: deferred until tool sees real-world use across companion-ai + this repo (T066)
- Issue #13 (DeepSeek discrepancy in v1 docs) closes when this lands

## Related

- spec: `specs/001-review-plan-v2/spec.md`
- plan: `specs/001-review-plan-v2/plan.md`
- 4 round /review-plan history: in chat transcript at `~/.claude/projects/-Users-jabelk-dev-projects-claude-workflows/`
