# Codex CLI

OpenAI's open-source terminal coding agent (Rust). The reason to keep it on hand: trained differently from Claude, so it catches different bugs. Use it as a reviewer, not a primary.

## Status — already configured for you

- **Install**: `npm i -g @openai/codex` (run once if not installed; `codex --version` to verify)
- **Auth**: `OPENAI_API_KEY` is in your `~/.zshrc`. Codex auto-detects it.
- Alternative: sign in with ChatGPT (Plus/Pro/Business/Edu/Enterprise includes Codex) — useful if you'd rather burn ChatGPT subscription credits than API budget. Skip unless you want it.

So: `codex` from any project, you're working.

## First Run

```bash
cd ~/dev/projects/figment
codex
```

Pick an approval mode at startup (read-only / auto-in-workspace / full-auto). Read-only is safe for first runs.

In the TUI:

```text
/model         # switch between gpt-5.4, gpt-5.4-mini, gpt-5.3-codex, etc.
```

## Two Modes That Matter

### Interactive — for working

```bash
codex
```

TUI session, you talk back and forth.

### `exec` — for scripting

```bash
codex exec "list all TODOs grouped by file in markdown"
```

One-shot. Output to stdout. This is what you use in CI, git hooks, or shell scripts that want an agent in the pipeline.

## The Pattern Worth Memorizing — Codex as Reviewer

This is what makes Codex worth installing. Workflow:

```bash
# 1. Build the change with your primary agent (Claude Code or OpenCode)
cd ~/dev/projects/mtg-cube-ai
git checkout -b feature-x
# ... do work in OpenCode/Claude Code, commit ...

# 2. Review with Codex in a fresh session
codex
```

In Codex: *"Review the most recent commit on this branch. Focus on security, missed edge cases, and anything that looks plausibly correct but actually wrong."*

Different model family → different blind spots → catches things your primary missed.

## Exercises

### Exercise 1 — Read-only walk-through on `figment`

```bash
cd ~/dev/projects/figment
codex
```

Pick read-only mode. *"What does this project do? What are the three files most important to understand it?"*

**Goal**: feel the TUI. No risk of accidental edits.

### Exercise 2 — Cross-model review (the real use case)

```bash
cd ~/dev/projects/mtg-cube-ai
git checkout -b codex-review-test
# Make a real change in OpenCode (or Claude Code), commit it
```

Then:

```bash
codex
```

*"Review the most recent commit. Focus on security, missed edge cases, and anything that compiles but is logically wrong."*

Write what Codex caught vs missed. This is the validation of whether the second-opinion pattern is worth the time on your codebase.

**Goal**: form a real opinion on cross-model review.

### Exercise 3 — Scripting with `exec`

Make `~/dev/projects/learn-coding-agents/scripts/audit.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$1"
codex exec "List any TODOs, FIXMEs, or HACK comments grouped by file. Markdown output."
```

Run it:

```bash
chmod +x scripts/audit.sh
./scripts/audit.sh ~/dev/projects/family-meeting
```

**Goal**: see how `exec` turns the agent into a Unix-style tool. Pipeable, scriptable, cron-able.

### Exercise 4 — Wire Codex into your SpecKit step 4.5

Your `claude-speckit-template` already fans out to multiple models for plan review. Add Codex:

1. Find the step 4.5 implementation.
2. Add a `codex exec --json "Review this plan…" < plan.md` invocation as a fourth reviewer.
3. Aggregate its output alongside Gemini/OpenAI/Claude.

**Goal**: make Codex a permanent part of your workflow, not a one-off experiment.

## Gotchas

- **Sandbox blocks writes outside the project root by default.** If your project writes to `~/.cache/...` or similar, configure the sandbox or expect blocks.
- **Approval modes are sticky per session.** Pick the right one at the start; switching mid-session may require restart.
- **Model IDs change.** If `gpt-5.4` doesn't work, hit `/model` to see what's available in your install.
- **`exec` output is plain text by default.** Add structured-output flags (check `codex exec --help`) if you're parsing.

## Sources

- <https://openai.com/codex/>
- <https://developers.openai.com/codex/cli>
- <https://github.com/openai/codex> (latest as of writing: 0.123.0)
