# AI Orchestration — Parallel Agents, Less Yes/No, Worktree Isolation

How to chew through a backlog with multiple agents working in parallel on the same repo, without conflicts, without you babysitting each one. Plus the global Claude Code rules that stop the narrative-question pestering.

---

## Your Preferences (captured for future reference)

So we don't re-litigate this in a future conversation:

- **Solo developer.** No team coordination needs. No PR review handoff between humans.
- **Don't code yourself.** All code is written by AI agents. You're the orchestrator.
- **Wispr Flow** for voice input — long dictated prompts are normal.
- **Already in env**: keys for Anthropic, OpenAI, Gemini, DeepSeek, xAI in `~/.zshrc`.
- **Stack**: Ghostty + Zellij. CLI-only. Cisco-themed.
- **Default orchestration: tabs, not worktrees.** Tried Claude Squad; the worktree model added more merge tax than it saved in parallelism for a solo-orchestrator workflow. Reverted to "multiple Ghostty tabs on the same working tree" as the default. See "Default orchestration" section below.
- **Claude Squad reserved for the rare genuine parallel case** — 3+ agents on truly independent features that won't merge-conflict.
- **Skipped Warp / Wave** — agent-in-terminal redundant with Claude Code/OpenCode; Ghostty perf wins.
- **Backlog use cases**: companion-ai, choose-adventure (novelflame.ai), mtg-cube-ai (mtgcommander.ai). All have a stack of GitHub issues to grind through.

## Default orchestration: tabs on the same working tree

The workflow that actually fits your use case:

```bash
cd ~/dev/projects/mtg-cube-ai

# Tab 1: primary agent
c                                  # claude code (subscription)
# or: opencode, or: codex

# Tab 2: second-opinion / reviewer agent
codex                              # cross-model review
# or: opencode, or: claude

# Tab 3: shell
lg                                 # lazygit for review/commit
gd                                 # GitHub dashboard
# + regular shell commands: git, gh, pnpm test, etc.
```

**Why this beats Claude Squad for your workflow:**

- All tabs see the same files, same branch, same running dev servers (no "my agent's worktree doesn't have the latest migration" problems).
- Coordinating agents is "tab over and ask" instead of "reconcile two worktrees."
- Merge tax is zero — they're all on the same branch, committing in the order you decide.
- Ghostty's native tab management (`Cmd+T`, `Cmd+1..9`) is simpler than the Claude Squad TUI.

**When to still reach for Claude Squad:**

- You genuinely have 3+ independent features to work on in parallel, and they won't touch the same files.
- You want agents to make trial-and-error attempts in isolation without affecting your working tree.
- You're okay with worktree overhead for that specific session.

Otherwise: tabs.

---

## Step 0 — Global CLAUDE.md (the biggest QoL win)

Already added to `~/.claude/CLAUDE.md`. Cuts narrative interruptions by ~80% per the source benchmark. Key rule: **ask only for irreversible / external-credential / external-visibility / cost actions**. Otherwise complete the task end-to-end.

If you ever need to override per-project (e.g., a client wants you to confirm every change), drop a `CLAUDE.md` in that project root with project-specific rules.

---

## Claude Squad (`cs`)

Manages multiple AI agents in parallel, each in their own tmux session and git worktree.

### Install (already done)

```bash
brew install tmux                # REQUIRED — claude-squad uses tmux internally
brew install claude-squad        # binary is `claude-squad`
alias cs='claude-squad'          # smart wrapper added to ~/.zshrc (see below)
cs version                       # 1.0.17 confirmed
```

**Dependency note**: `tmux` is required even though the user-facing UI is Claude Squad's own TUI. Each agent instance runs inside its own tmux session under the hood. If you see `failed to start new session: exec: "tmux": exec...`, that's a missing tmux install.

Config lives at `~/.claude-squad/config.json`:

```json
{
  "default_program": "/opt/homebrew/bin/codex",
  "auto_yes": false,
  "daemon_poll_interval": 1000,
  "branch_prefix": "jabelk/"
}
```

**Default agent: codex**, set 2026-04-23. Reasoning: codex uses `OPENAI_API_KEY` cleanly from env (no subscription/API billing conflict like claude has), and the cross-model review pattern works fine with codex as the builder when you want to use claude as reviewer in another instance (use `N` to spawn with a different program).

### Spawn claude on demand instead

To spawn a claude instance from inside cs, press `N` (capital) instead of `n` and type `/Users/jabelk/bin/claude` when prompted. That uses the subscription wrapper (which strips `ANTHROPIC_API_KEY` so Claude Code falls back to your Max subscription auth instead of billing the API). Without the wrapper, every claude instance would bill the API account because `ANTHROPIC_API_KEY` is in your env for OpenCode/other tools.

### Codex auto-approval (configured 2026-04-23)

Codex defaults to `untrusted` approval (asks for most non-trivial commands), which makes it noisy for batch work. Configured `~/.codex/config.toml` to bypass that:

```toml
approval_policy = "never"        # don't ask; return failures to the model
sandbox_mode = "workspace-write" # can read/write in workspace, blocked outside
```

This combination is the same as the `--full-auto` CLI flag, but persistent. Failures (e.g., trying to write outside the workspace, network calls) come back to the model so it can adapt or escalate, rather than blocking on a prompt.

**Note**: changes only apply to *new* Codex instances. To activate on an already-running instance, kill it (`D` in the cs TUI) and spawn a new one.

### SpecKit + Codex

**Codex supports SpecKit officially.** SpecKit installs differently for each agent:

- **Claude Code** uses slash commands at `.claude/commands/speckit.*.md` (invoked as `/speckit.specify` etc.)
- **Codex** uses **AI Skills** at `.agents/skills/speckit-*/` plus an `AGENTS.md` at the project root (invoked by skill name, e.g., *"use the speckit-specify skill"*)

Both can coexist in the same project. The SpecKit CLI (`specify`) is what installs them.

#### Add Codex SpecKit to a project that already has Claude SpecKit

```bash
cd <project>
specify integration install codex
```

This is non-destructive — it adds the Codex skills + AGENTS.md without touching the existing Claude commands. Confirmed working on mtg-cube-ai 2026-04-23. Replicate per project as needed.

**Important — commit it.** The install creates `.agents/skills/`, modifies `AGENTS.md`, and adds `.specify/integrations/`. These are *untracked* until you commit. Claude Squad creates worktrees from your branch HEAD, so any worktree spawned before the commit *won't have the skills* and Codex inside that worktree will fail with "skill not available." Either:

- Commit the integration files to your branch (`git add .agents/ .specify/integrations/ AGENTS.md && git commit`), then spawn fresh Claude Squad instances. Future worktrees auto-inherit.
- Or run `specify integration install codex` directly inside the existing worktree (one-off fix per worktree, less clean).

After installing in a worktree, the running Codex instance still won't see the new skills — it discovers tools at session start. Kill the instance (`D` in cs TUI) and respawn (`n`) to pick up the changes.

#### Workflow split (with both agents now SpecKit-aware)

| Phase | Tool of choice | Why |
|-------|---------------|-----|
| `/speckit.specify`, `/speckit.clarify`, `/speckit.plan`, `/speckit.tasks` | **Either** Claude Code (slash commands) or Codex (skills) | Pick whichever you're already in |
| Implementing tasks in parallel | **Codex via Claude Squad** | Cheap, fast, runs autonomously with auto-approval |
| Cross-model review of agent work | **Other agent** (separate instance) | Different blind spots |

Typical run for mtg-cube-ai-style backlog:

1. Either in Claude Code (`c`) or in a single Codex instance: run the spec phases for the feature. Output lands at `specs/NNN-feature/{spec,plan,tasks}.md`.
2. `cs` from the project root.
3. For each task in `tasks.md`, press `n` to spawn a Codex agent: *"Read `specs/NNN-feature/spec.md` and `plan.md`. Use the speckit-implement skill for task T00X only. Open a draft PR when done."*
4. Walk away. Agents run in parallel on separate worktrees.
5. Review draft PRs with `lg` or `gd`.

Codex reads both `CLAUDE.md` and `AGENTS.md` from the project. The `AGENTS.md` that `specify integration install codex` creates already includes the SpecKit workflow guide, so no extra prompting needed.

#### List of SpecKit-supported agents (for reference)

`specify integration list` shows the full set. As of v0.7.4 it includes: claude, codex, copilot, cursor-agent, gemini, opencode, qwen, kilocode, kimi, kiro-cli, qodercli, tabnine, amp, auggie, junie, forge, goose, iflow, pi, roo, shai, trae, vibe (Mistral), and more.

### Mental model

Think of it as **tmux for AI agents**, with each agent on its own git worktree:

- **Instance** = one running agent (Claude, Codex, OpenCode, Aider, Amp, etc.)
- Each instance gets its own tmux session AND its own git worktree on a new branch
- You switch between instances in a TUI; each one is independent
- When an instance is "done," you review the diff and choose to merge or discard

The worktree isolation means three Claude agents working on three issues can't stomp on each other. Each lands its work on a separate branch. You merge in your order.

### First run

```bash
cd ~/dev/projects/companion-ai          # any project with a backlog
cs                                       # opens the TUI
```

**Important**: `cs` requires being inside a git repo. The smart `cs()` wrapper in `~/.zshrc` auto-fzf-picks a project from `~/dev/projects` if you run it from anywhere else (e.g., `~/dev/projects` itself). To bypass the wrapper, use `claude-squad` directly.

In the TUI:

- `n` to spawn a new instance (default program: `claude`)
- `N` (capital) to spawn with a different program (e.g., `opencode` or `codex`)
- `tab` / arrow keys to switch between instances
- `enter` to focus an instance (your keystrokes go to it)
- `esc` to leave the focused instance and return to the TUI
- `?` for help (always available)
- `q` to quit (sessions persist; reattach later)

### Useful flags

```bash
cs                                                    # default
cs -p 'opencode'                                      # different default program
cs -p 'aider --model ollama_chat/gemma3:1b'           # local model agent
cs -y                                                 # autoyes — auto-accept prompts in all instances (experimental)
```

### Your first real session — chewing through companion-ai backlog

Concrete walkthrough for one of your actual use cases.

```bash
cd ~/dev/projects/companion-ai
gd                                       # gh-dash; pick 3 issues you want done in parallel
# Note the issue numbers, e.g. #42, #43, #44

cs
```

In Claude Squad:

1. `n` → spawn instance 1, default to claude. In its prompt:
   *"Read GitHub issue #42 in this repo. Implement the fix. Open a draft PR when done. Don't ask narrative questions."*
2. `esc` to come back to the TUI.
3. `n` → spawn instance 2. Same idea for #43.
4. `N` → spawn instance 3 with `opencode` instead, for variety. Same idea for #44.
5. Walk away. They're working on three separate worktree branches in parallel.
6. Come back, `tab` through to see status. The done ones have draft PRs.
7. Use `lg` (lazygit) or `gd` (gh-dash) to review and merge in your order.

The branches will be named `jabelk/<auto-generated>`. Tweak `branch_prefix` in `~/.claude-squad/config.json` if you want a different convention per project.

### Workflow tips for backlog grinding

- **One issue per instance.** Don't ask one agent to do 3 issues; you lose the parallelism and the worktree isolation gets messier.
- **Spawn in batches of 3-5.** More than that and you can't track them. Less and you're not getting the parallelism payoff.
- **Use different agents for variety.** Claude for one, OpenCode for the next, Codex for review. They have different blind spots.
- **Auto-yes is tempting but risky.** `cs -y` skips prompts in *every* instance. With your CLAUDE.md decision rules in place, you don't need it for narrative questions. Save `-y` for genuinely no-stakes batch work where you're going to review every PR anyway.

### What can go wrong

- **Instance dies or hangs.** Reset it from the TUI; the worktree is preserved so you can re-spawn against the same branch.
- **Branch conflicts on merge.** That's the part Claude Squad doesn't solve — you handle merges yourself in `lg` or via `gh pr merge`. (See "When to graduate to Agent Orchestrator" below.)
- **Two agents working on the same file.** Should never happen with worktrees, unless you started two on the same issue or your prompts overlap in scope.

### Reset everything

```bash
cs reset             # nuke all stored instances (worktrees stay)
```

### Gotcha — config changes need a full cs restart

claude-squad reads `~/.claude-squad/config.json` once at startup and caches it in memory. Killing instances inside the TUI (with `D`) does **not** reload the config. If you change `default_program`, branch_prefix, or other settings, you have to fully exit and restart:

```bash
# inside TUI: press q
pkill -f claude-squad           # kill any lingering process
tmux kill-server                # nuke stale agent sessions
cs                              # fresh start, config now in effect
```

This bit us when setting up the subscription wrapper — config pointed to `~/bin/claude` correctly, but the running `cs` was still spawning instances with the old absolute path.

---

## Agent Orchestrator (Composio) — the next step up

You said you liked the idea of merge conflicts being handled automatically. Claude Squad doesn't do that — it parallelizes the *building*, but you handle merging. Agent Orchestrator does both.

**Skip this section until** you've used Claude Squad for a couple weeks and feel like merge resolution is the next bottleneck. Documenting now so you don't have to re-research.

### What it is

A more autonomous orchestrator. Plans tasks, spawns agents in parallel worktrees, and **autonomously handles CI fixes, merge conflicts, and code reviews**. Less hands-on than Claude Squad.

GitHub: <https://github.com/ComposioHQ/agent-orchestrator>

### When to switch

Switch from Claude Squad to Agent Orchestrator when:

- You routinely have 3+ agents finishing in parallel, and merge conflict resolution is the slow step
- You want an agent to fix CI failures on its own PRs rather than you babysitting them
- You're comfortable letting an autonomous system make merge decisions on your repos (no team to push back)

Stick with Claude Squad if:

- You like the per-instance review-before-merge cadence
- You don't trust autonomous merge resolution on important code
- You want one less moving part

### Your preferences captured for the eventual switch

When/if you set this up:

- Solo dev — no need for human-in-the-loop checkpoints beyond your own
- Wants autonomous merge conflict resolution (the whole reason for switching)
- Same provider keys in env work (Anthropic, OpenAI, Gemini, DeepSeek, xAI)
- Use the same `branch_prefix: jabelk/` convention as Claude Squad
- Default model: Sonnet 4.6 for builders, GPT-5.4 or DeepSeek for reviewers (cross-model review pattern)

### Install (when you're ready, not now)

Composio's install is more involved than `brew install`. From the repo:

```bash
# pip install (typical for Composio tools)
pip install composio-agent-orchestrator
# or via uv
uv tool install composio-agent-orchestrator

# Then composio configuration
composio configure
```

Verify install path / current command name from <https://github.com/ComposioHQ/agent-orchestrator/blob/main/README.md> before running — Composio's tooling moves fast and the exact command may change.

### Minimum config to capture your preferences

Drop in `~/.config/agent-orchestrator/config.yaml` (path may vary; verify with the upstream repo):

```yaml
# Solo dev defaults — captured from learn-coding-agents/06
branch_prefix: "jabelk/"
default_builder_model: "anthropic/claude-sonnet-4-6"
default_reviewer_model: "openai/gpt-5.4"
auto_resolve_conflicts: true
auto_fix_ci: true
human_checkpoint: false                 # solo dev — no need
worktree_root: "~/dev/worktrees"        # keep worktrees out of project dirs
```

---

## Claude Code's Built-in Agent Teams (experimental)

A third option, native to Claude Code.

```bash
# In ~/.claude/settings.json
{
  "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": true
}
```

Sub-agents Claude spawns can each get their own worktree. Less mature than Claude Squad. Only worth trying if Claude Squad and Agent Orchestrator both feel like overkill and you'd rather stay 100% inside Claude Code.

Reference: <https://code.claude.com/docs/en/agent-teams>

---

## Cheat Sheet

| Command | Does |
|---------|------|
| `cs` | Open Claude Squad TUI |
| `cs -y` | Same, with autoyes (experimental, careful) |
| `cs -p opencode` | Default to OpenCode for new instances |
| `cs reset` | Nuke all stored instances |
| `cs version` | Print version |
| `cs debug` | Show config paths |

In the TUI:

| Key | Action |
|-----|--------|
| `n` | New instance (default program) |
| `N` | New instance with different program |
| `tab` / arrows | Switch instances |
| `enter` | Focus an instance (input goes to it) |
| `esc` | Leave focused instance, back to TUI |
| `?` | Help |
| `q` | Quit (sessions persist) |

---

## Sources

- [Claude Squad on GitHub](https://github.com/smtg-ai/claude-squad)
- [Agent Orchestrator (Composio)](https://github.com/ComposioHQ/agent-orchestrator)
- [Claude Code agent teams docs](https://code.claude.com/docs/en/agent-teams)
- [5 CLAUDE.md Rules That Made My AI Stop Asking](https://dev.to/yurukusa/5-claudemd-rules-that-made-my-ai-stop-asking-and-start-doing-43e1)
- [Stop Claude from asking for confirmation mid-task](https://builtbyzac.com/post-confirmation-prompts.html)
