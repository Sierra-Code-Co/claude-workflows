# Workflows

Walkthroughs for how the tools fit your actual day, not abstract examples. Each one is scenario → exact steps → expected outcome.

These reference the cheat sheet at `04-terminal-setup.md` for individual command details. This file is about *combinations*.

---

## Workflow 1 — Daily start: see what changed

**When**: morning, or after a few hours away. You want to know what's open, what's waiting on you, what landed overnight.

**Steps**:

```bash
cd ~/dev/projects/sierra-code-co       # or any active project
gd                                      # opens gh-dash
```

In gh-dash:

1. The default view is **My PRs**. Skim.
2. `tab` to **Needs My Review**. If anything's there, `enter` to preview, `o` to open in browser if it needs deep review.
3. Press `2` to switch to **Issues**. Look at "Assigned to Me" first.
4. `enter` on an issue to read the body. The preview pane handles most things; for long issues, quit gh-dash and run:

```bash
gh issue view 42 | glow
```

**Outcome**: you know your day's input without ever opening a browser.

**Why this is better than the old way**: in iTerm2 you'd open Cursor or a browser to read each issue. With `gh dash` and `glow`, you stay in the terminal and read 5 issues in the time it took to context-switch once.

---

## Workflow 2 — Start a new feature with spec-driven dev + parallel agents

**When**: a new client asks for a feature. You want to use SpecKit and have multiple agents working/reviewing in parallel.

**Steps**:

```bash
cd ~/dev/projects/some-client-project
git checkout -b 003-feature-name
zellij --layout agents
```

You're now in a 3-pane layout:

- **primary** (left, 60% width)
- **reviewer** (top right)
- **shell** (bottom right)

In **primary**:

```bash
opencode
# Then: /speckit.specify "what the feature does, who uses it, what success looks like"
# Then: /speckit.clarify  (let it ask you 3-5 clarifying questions)
# Then: /speckit.plan
# Then: /speckit.tasks
```

In **shell** (use `Alt+→` to focus):

```bash
ll specs/                              # see the new spec dir take shape
glow specs/003-feature-name/spec.md    # read the spec as it's generated
```

In **reviewer** (use `Alt+→` again):

```bash
codex                                  # idle until you have something to review
```

When the plan is ready:

- Switch to **reviewer** pane
- In codex: *"Review the spec, plan, and tasks at `specs/003-feature-name/`. Flag missing edge cases, ambiguous acceptance criteria, plan-task mismatches."*

When ready to implement, in **primary**: `/speckit.implement`.

When you need to step away: `Ctrl+O` then `D` to detach. Session keeps running. Reattach later with `zellij a`.

**Outcome**: spec, plan, tasks reviewed by two different model families before a line of code is written. Your existing SpecKit step 4.5 review is happening live in another pane.

---

## Workflow 3 — Read a long spec or agent output without leaving the terminal

**When**: an agent just output a 600-line markdown plan, or you want to read a spec file. Previously you'd open it in Cursor.

**Steps**:

```bash
glow specs/003-feature-name/plan.md             # render once
glow -p specs/003-feature-name/plan.md          # render with paging (j/k to scroll)
glow specs/003-feature-name/                    # browse all .md in the dir
```

For something the agent just printed to your terminal but you want to re-render cleanly:

```bash
opencode-output | glow                          # if you piped output to a file
pbpaste | glow                                  # if you copied output, render the clipboard
```

**Outcome**: zero context-switch to read agent markdown. The `pbpaste | glow` pattern is the one that probably saves you the most time — agents output something useful, you copy it, and read it formatted in 2 keystrokes.

---

## Workflow 4 — Review your AI's work with a different AI

**When**: Claude Code (or OpenCode) just finished a feature. Before you commit, you want a second opinion from a different model family.

**Steps**:

In the **shell** pane (lazygit shows you the diff visually):

```bash
lg
```

In lazygit:

1. `4` for the commits panel — but you haven't committed yet. So:
2. `1` for the status panel — see the unstaged changes.
3. Arrow to a file, `enter` to see the diff. Read it. Quit with `q`.

Now switch to **reviewer** pane and start codex:

```bash
codex
```

In codex:
> *"Review the uncommitted changes on this branch. `git diff` to see them. Focus on: security issues (any new XSS, SQL injection, auth bypass surface), missed edge cases (empty inputs, very long inputs, concurrent access), and anything that compiles but is logically wrong."*

If codex flags something real:

- Switch back to **primary** pane (`Alt+←`)
- Tell opencode/claude code: *"Codex found X. Fix it."*

When clean, in **shell**: `lg`, then `space` to stage, `c` to commit, `P` to push.

**Outcome**: cross-model review catches things one model misses. The lazygit + dual-pane setup makes the loop fast enough that you'll actually do it instead of skipping it.

---

## Workflow 5 — Switch projects without re-setting env vars

**When**: you `cd` into a client project that needs its own API key (different billing, rate limit, or org). The global `~/.zshrc` keys are wrong for this project.

**One-time setup per project**:

```bash
cd ~/dev/projects/my-client-project
echo 'dotenv' > .envrc
direnv allow
```

After that, every time you `cd` into that project:

- direnv auto-loads `.env`, overriding the global keys with the project-specific ones
- `cd` out, the project keys unset and your globals are back

To verify:

```bash
echo $ANTHROPIC_API_KEY | head -c 20         # see which key is active
direnv status                                 # see what's loaded
```

**Outcome**: stop the "wait, why is this hitting the wrong account" debugging session. Add `dotenv` + `direnv allow` once per project, then it's invisible.

---

## Workflow 6 — Find "that command from a week ago"

**When**: you remember running some `gh` or `railway` or `docker` command that did exactly the thing you need now, but you can't remember the flags.

**Steps**:

Press `Ctrl+R`. Type partial words from the command. Atuin shows ranked matches across all your shell history (now indexed since the import).

Filters that work inside the search box:

- `directory:~/dev/projects/figment` — only show commands you ran in that dir
- `exit:0` — only successful commands
- `git push origin` — leading space = exact phrase

Useful one-liners:

```bash
atuin stats                    # your most-used commands (good for spotting alias candidates)
atuin search "railway run"     # CLI search without opening UI
```

**Outcome**: every command you've ever run is one Ctrl+R away. The 2am "what was that magic incantation" stops being a problem.

---

## Workflow 7 — Triage a PR someone tagged you on

**When**: GitHub email says "X requested your review on PR #42 in repo Y."

**Steps**:

```bash
gd                                          # gh dash
# tab to "Needs My Review", arrow to PR #42, enter for preview
# Read the description in the preview pane
# Press 'o' if you need to see the full diff in browser, OR:
# Quit gh-dash, then:

cd ~/dev/projects/path-to-that-repo
git fetch
git checkout pr-branch                      # or `gh pr checkout 42`
lg                                          # lazygit
```

In lazygit:

1. `4` → commits panel
2. Arrow to the PR's commits, `enter` to read each commit's diff
3. `space` on a hunk to comment? — actually lazygit doesn't post review comments. For inline comments use:

```bash
gh pr review 42 --comment -b "your comment"
```

Or for a more thorough review with a second-opinion check:

```bash
codex
# "Review the diff on this branch vs main. Focus on security, edge cases, and unclear naming."
```

When done:

```bash
gh pr review 42 --approve                   # or --request-changes
```

**Outcome**: a structured PR review without leaving the terminal. The `codex` step is what catches things you'd miss at 4pm on a Friday.

---

## Workflow 8 — Convert speckit tasks to GitHub issues, then triage

**When**: you've finished `/speckit.tasks` and want to track the work as GitHub issues so you (and any collaborator) can see status from the web.

**Steps**:

In the project's primary agent pane:

```text
/speckit.taskstoissues
```

This creates issues in the repo. Then:

```bash
gd                          # gh dash
# Press 2 for issues view
# Filter to your repo if needed (or add a section in ~/.config/gh-dash/config.yml)
```

Pick the first issue, `enter`, read it. To see the linked spec:

```bash
glow specs/<feature-dir>/tasks.md
```

To start the task in a fresh agent:

```bash
opencode
# "Read specs/<feature>/tasks.md, find task T001, implement only that task. Open a draft PR when done."
```

**Outcome**: speckit-driven plan, GitHub-tracked execution, no spreadsheet gymnastics in between.

---

## What This All Costs You in Habit Change

The hardest part isn't installing the tools. It's:

1. **Stop reaching for Cursor / browser to read markdown.** `glow` is your reflex now. `pbpaste | glow` for the clipboard case.
2. **Stop using bare `cat`.** It's aliased to `bat` — you'll get color and line numbers automatically. If a script breaks, that's `\cat` for the alias bypass.
3. **Use `Ctrl+R` (atuin) instead of arrow-up scrolling.** Way faster after about 50 commands of history.
4. **Default to `zellij --layout agents` when starting agent work.** If you reach for Ghostty tabs out of habit, you're not getting the parallelism benefit.

Give it a week. If anything feels worse than the iTerm2 / no-multiplexer setup, edit the config or remove the alias — these are your tools, not a religion.
