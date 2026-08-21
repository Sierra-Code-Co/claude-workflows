# OpenCode

Open-source AI coding agent from the SST team. Same mental model as Claude Code, with vendor independence.

## Status — already configured for you

- **Installed**: assumed; verify with `opencode --version`
- **Keys**: Anthropic, OpenAI, Gemini, DeepSeek, xAI all live in `~/.zshrc` (auto-loaded into every shell)
- **Config**: `~/.config/opencode/opencode.json` references those env vars
- **Default model**: `anthropic/claude-sonnet-4-6` (override with `/models` mid-session)

So: `cd` into any project, run `opencode`, you're working. No `/connect` flow needed.

## First Run

```bash
cd ~/dev/projects/figment
opencode
```

In the TUI:

```text
/init       # generates AGENTS.md (commit it; it's the OpenCode equivalent of CLAUDE.md)
/models     # see all available models across all providers
```

Then just type your task. That's it.

## Core Interactions

| Action | How |
|--------|-----|
| Toggle Plan ⇄ Build mode | `Tab` |
| Attach a file with fuzzy search | `@` |
| Switch model mid-session | `/models` |
| Undo last change | `/undo` |
| Redo | `/redo` |
| Share the session (link out) | `/share` |

**Plan mode** is read-only — agent proposes changes but doesn't touch files. **Build mode** is execution. Toggle freely; this is the most important UX habit to build.

## The Workflow That Pays Off

1. Open OpenCode in the project.
2. Hit `Tab` to enter Plan mode.
3. Describe the change. Read the proposed plan.
4. If it's wrong, push back in chat without leaving Plan mode.
5. When the plan is right, hit `Tab` to switch to Build, say "do it."
6. Review the diff. Commit or `/undo`.

This loop is faster than just-build-it because the corrections happen in chat (cheap) instead of in code (expensive to undo cleanly).

## Switching Models for Different Tasks

You have five providers wired in. Swap mid-session with `/models`:

- **Heavy lifting / architecture**: `anthropic/claude-opus-4-7` or `anthropic/claude-sonnet-4-6`
- **Cheap iteration**: `anthropic/claude-haiku-4-5` or `deepseek/deepseek-chat`
- **Long context / synthesis**: try `google/gemini-2.5-pro` (Gemini is good at large repo summarization)
- **Second opinion / review**: `openai/gpt-5.4` or `xai/grok-4`

Don't agonize. Default to Sonnet for code, swap when something feels off.

## Exercises

Pick one. Always work on a branch (`git checkout -b learning-opencode-<name>`).

### Exercise 1 — Plan / Build loop on `figment`

```bash
cd ~/dev/projects/figment
git checkout -b learning-opencode-1
opencode
```

In Plan mode: "Look at this project and find one function that's longer than 40 lines. Propose a refactor that doesn't change behavior."

When the plan is reasonable, `Tab` to Build, say "do it." Review the diff. Run tests if any. Commit or discard.

**Goal**: live with the Plan/Build toggle. That's the distinguishing UX habit of OpenCode.

### Exercise 2 — Model swap mid-task on `mtg-cube-ai`

```bash
cd ~/dev/projects/mtg-cube-ai
opencode
```

1. Default model (Sonnet): "Find one thing in this codebase that looks plausibly correct but might actually be wrong."
2. `/models`, switch to `openai/gpt-5.4` or `xai/grok-4`. Same prompt.
3. `/models`, switch to `deepseek/deepseek-chat`. Same prompt.

Note differences. Often DeepSeek catches things at 1/10th the cost of GPT.

**Goal**: build intuition for which model to reach for when.

### Exercise 3 — Custom slash command on `choose-adventure`

Add `opencode.json` to the project root:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "command": {
    "story-review": {
      "template": "Review the story generation prompts in this codebase. For each, flag any that could fail when the user's input is very short, very long, or in a non-English language.",
      "description": "Audit story prompts for edge cases",
      "agent": "build"
    }
  }
}
```

Then in OpenCode: `/story-review`.

**Goal**: turn a repeated prompt into a one-key command. Project-level config overrides global, so this only fires in this project.

### Exercise 4 — Side-by-side with Claude Code on the same task

Pick a real task. Run it in OpenCode in one terminal, Claude Code in another, on the same branch (or two branches off the same point). Note which one needed less correction. Write the result somewhere you'll see again.

**Goal**: form your own opinion. The internet's opinion isn't yours.

## Gotchas

- **Default permissions are loose.** I set `permission: ask` for edit and bash in your global config. If a project should be unrestricted, override locally.
- **Model IDs drift.** If `claude-sonnet-4-6` ever errors, run `/models` and update `~/.config/opencode/opencode.json`.
- **AGENTS.md isn't CLAUDE.md.** Same purpose, different file. Don't symlink — keep them separate so you can tune them per agent.
- **Project `.env` keys aren't auto-imported.** OpenCode reads from your shell env (`~/.zshrc`), not from project-local `.env` files. If a specific project needs its own key (like `mtg-cube-ai`), add a project `opencode.json` overriding the provider key.

## Reference — config schema

Already configured for you, but if you want to customize:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "anthropic/claude-sonnet-4-6",
  "small_model": "anthropic/claude-haiku-4-5",
  "permission": { "edit": "ask", "bash": "ask" },
  "provider": {
    "anthropic": { "options": { "apiKey": "{env:ANTHROPIC_API_KEY}" } }
  },
  "mcp": {
    "jira": { "type": "remote", "url": "https://jira.example.com/mcp", "enabled": true }
  },
  "agent": {
    "code-reviewer": {
      "description": "Reviews code for best practices and potential issues",
      "model": "anthropic/claude-sonnet-4-6",
      "prompt": "You are a code reviewer. Focus on security, performance, and maintainability.",
      "tools": { "write": false, "edit": false }
    }
  }
}
```

Config precedence (later wins): global → project `opencode.json` → `.opencode/` directories → `OPENCODE_CONFIG_CONTENT` env var.

## Sources

- <https://opencode.ai/docs/>
- <https://opencode.ai/docs/config/>
- <https://opencode.ai/docs/zen/>
- <https://github.com/sst/opencode>
