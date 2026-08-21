# Kilo Code (CLI)

Open-source agentic coding tool. We're focusing on the **CLI** since that's how you work — the VS Code extension exists if you ever want it, but we'll skip it.

The distinctive feature worth knowing: explicit **agents** (code / ask / plan / debug) with different tool permissions baked in. Plus the Kilo Gateway for access to 500+ models under one key (or BYOK with the env keys you already have).

## Status — install once

```bash
npm install -g @kilocode/cli
kilo --version
```

**Auth/keys**: Kilo CLI picks up the same provider keys already in your `~/.zshrc` (Anthropic, OpenAI, Gemini, DeepSeek, xAI). On first run it'll ask which provider to use as default — pick whichever; you can swap mid-session.

## First Run

```bash
cd ~/dev/projects/figment
kilo
```

Once you're in, type your task. That's it. The agent runs in your shell, prints to stdout, edits files in place.

## The Five Built-in Agents

These are Kilo's distinguishing feature — they're not just "modes," they're separate agents with different tool access.

| Agent | Tool access | When to use |
|-------|-------------|-------------|
| **code** (default) | Full | Writing, refactoring, building |
| **ask** | Read-only | Exploring an unfamiliar codebase. Can't edit even if you ask. |
| **plan** | Read-only + writes only to `.kilo/plans/` | Designing a change. Plans land on disk as markdown. |
| **debug** | Full | Troubleshooting. Same tools as code, different prompt. |
| **orchestrator** | (deprecated) | Don't use. |

Plus **custom agents** — define your own in config with specific tool access.

### Switching agents in the CLI

```text
/agents                          # show / switch agents
```

The mode-switching habit is what differentiates Kilo. Use **ask** when you don't trust yourself with a hot agent. Use **plan** when you want a written plan on disk before mutating.

## When to Reach for Kilo Over OpenCode / Claude Code

Kilo is third-pick for you given OpenCode + Claude Code already cover daily work. Reasons to pull it out:

- **You want a plan persisted as a markdown file in `.kilo/plans/`** — useful when a plan is going to be reviewed by a human or another tool.
- **You want explicit tool-permission scoping per agent** — strictly safer than Claude Code's "deny by default" because the constraint is at the agent level, not just per-prompt.
- **You want to access a Kilo Gateway model you don't have a direct key for** without setting up another provider.

If none of those apply, stay in OpenCode + Claude Code.

## Exercises

### Exercise 1 — Three agents, one task on `figment`

```bash
cd ~/dev/projects/figment
git checkout -b learning-kilo-1
kilo
```

In the CLI:

1. `/agents` → switch to **ask**. "How is state managed in this project?"
2. `/agents` → switch to **plan**. "Design a plan to add structured logging to the three most critical functions." A plan file lands at `.kilo/plans/<name>.md`.
3. `/agents` → switch to **code**. "Execute the plan in `.kilo/plans/`."
4. Review the diff with `lg` (lazygit) in another zellij pane. Commit or discard.

**Goal**: feel the three-agent workflow. The plan-on-disk is the unique differentiator.

### Exercise 2 — Custom agent for spec review

Drop a Kilo config in your project (`.kilo/config.json` or wherever the docs say) defining a custom agent:

- Name: `spec-reviewer`
- Tool access: read-only + write to `specs/*/review.md`
- Instructions: *"Review spec.md, plan.md, and tasks.md in the given specs/ directory. Write findings to review.md. Focus on missed edge cases, unclear acceptance criteria, plan-task mismatches."*

Run it on an existing speckit folder in `~/dev/projects/sierra-code-co/specs/`.

**Goal**: encode a recurring role as a first-class agent — a workflow Claude Code's subagents don't quite do as cleanly.

## Gotchas

- **Pre-release recommended.** The install docs explicitly point to "Install Pre-Release Version" — expect rough edges and changing CLI flags.
- **`orchestrator` is deprecated.** Don't build on it.
- **Mode lock is a feature.** If you forget you're in `ask` and try to ship code, Kilo refuses. Don't fight it; switch agents.

## Sources

- <https://kilo.ai/docs/>
- <https://kilo.ai/docs/getting-started/installing>
- <https://kilo.ai/docs/basic-usage/using-modes>
- <https://github.com/Kilo-Org/kilocode>
