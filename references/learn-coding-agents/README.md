# learn-coding-agents

A practical lab for getting hands-on with open-source coding agents beyond Claude Code.

## Tools Covered

| Tool | What it is | Guide |
|------|------------|-------|
| **OpenCode** | Open-source CLI coding agent by SST. 75+ providers, BYOK or OpenCode Zen gateway. | [01-opencode.md](./01-opencode.md) |
| **Codex CLI** | OpenAI's terminal coding agent, built in Rust. Ships with ChatGPT Plus. | [02-codex-cli.md](./02-codex-cli.md) |
| **Kilo Code** | Open-source agent with VS Code / JetBrains / CLI surfaces and built-in modes (code / ask / plan / debug). | [03-kilo-code.md](./03-kilo-code.md) |
| **Terminal stack** | Ghostty + Zellij + 10 modern CLI tools (atuin, fzf, lazygit, gh-dash, glow, etc.) — Cisco-themed. | [04-terminal-setup.md](./04-terminal-setup.md) |
| **Workflows** | End-to-end walkthroughs combining tools for your actual flow (issue triage, spec-driven dev, cross-model review, etc.). | [05-workflows.md](./05-workflows.md) |
| **Cheat sheet** | One-page condensed reference of every command, alias, and keybind. | [cheatsheet.md](./cheatsheet.md) |
| **AI orchestration** | Parallel agents on worktrees (Claude Squad), the global CLAUDE.md rules that stop narrative-question pestering, and notes for graduating to Agent Orchestrator later. | [06-ai-orchestration.md](./06-ai-orchestration.md) |

Plus:

- [comparison.md](./comparison.md) — when to reach for which
- [exercises.md](./exercises.md) — specific practice tasks using your existing projects

## Why these and not just Claude Code

Short version: vendor independence, model flexibility, local-first options, and cost control. The practical reason is that fluency with one agent makes you dependent on one vendor, while fluency across agents lets you pick the right tool per task and route around any one company's decisions (pricing changes, context quirks, deprecations).

## Recommended Order

1. **Start with OpenCode** (01). It's the closest mental model to Claude Code, so the transition is cheapest. Get it installed and do the two smallest exercises.
2. **Add Codex CLI** (02). Run it alongside OpenCode/Claude Code on the same task and compare. Codex works well as the "second opinion" agent for catching gaps.
3. **Try Kilo Code** (03) if you want an editor-integrated option. Its "modes" concept (code/ask/plan/debug) is different enough to be worth experiencing even if you stay primarily in a CLI workflow.

## Status — Setup Already Done

Your provider keys (Anthropic, OpenAI, Gemini, DeepSeek, xAI) are exported in `~/.zshrc` and wired into OpenCode at `~/.config/opencode/opencode.json`. Codex CLI auto-picks up `OPENAI_API_KEY` from the same env. Kilo Code in VS Code picks up keys when you BYOK on first launch.

What's left for you to do:

- [ ] Verify OpenCode runs (`opencode --version`)
- [ ] Verify Codex runs (`codex --version`)
- [ ] Install Kilo VS Code extension if/when you want editor integration
- [ ] Do one warmup exercise per tool (in `exercises.md`)

If you ever need to add a new provider, just add the export to `~/.zshrc` and a stanza to `~/.config/opencode/opencode.json`. The pattern is in the existing config.

## Practice Targets

Your currently-active projects, ordered by recency of git activity. These are the suggested targets for the exercises — pick whichever feels safest for a given experiment.

| Project | Last commit | Good for |
|---------|-------------|----------|
| `~/dev/projects/choose-adventure` (novelflame.ai) | 2026-04-23 | App-level refactors, SEO/marketing exercises |
| `~/dev/projects/companion-ai` | 2026-04-23 | Agent design, MCP experiments |
| `~/dev/projects/family-app` (runourhouse.com) | 2026-04-22 | Production-facing — be careful, use branches |
| `~/dev/projects/family-meeting` | 2026-04-22 | Scripting, smaller surface area |
| `~/dev/projects/mtg-cube-ai` (mtgcommander.ai) | 2026-04-22 | Data-heavy logic, test writing |
| `~/dev/projects/figment` | 2026-04-21 | Small, low-stakes — ideal warmup target |

Default to `figment` or `family-meeting` for first experiments. Leave `family-app` alone until you trust the tool.

## How to Use This Repo

- Read one tool guide start-to-finish before touching the tool.
- Do exercises in a **branch**, never on main. You are practicing the tool, not refactoring production.
- After each exercise, write three lines at the bottom of `notes.md` (create it when you want): what worked, what didn't, which tool you'd use for that task next time.
- When a tool's actual behavior diverges from what this guide says (these tools ship fast), update the guide. That's the point of owning the notes.

## Sources

All guides cite the official docs they were built from. If anything feels stale, re-verify against the source linked at the bottom of each guide.
