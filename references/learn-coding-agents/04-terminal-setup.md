# Terminal Setup — Ghostty + Zellij + Modern CLI

Your terminal stack, what each piece does, and the cheat sheet for the new tools. Everything is already installed and configured — this is the reference card.

## What's Installed

| Tool | Role | Where its config lives |
|------|------|------------------------|
| **Ghostty** | Terminal emulator (replaces iTerm2) | `~/.config/ghostty/config` |
| **Zellij** | Terminal multiplexer (panes, sessions, persistence) | `~/.config/zellij/config.kdl` |
| **Starship** | Prompt with git/lang info | `~/.config/starship.toml` |
| **Atuin** | Searchable shell history | `~/.config/atuin/config.toml` |
| **fzf** | Fuzzy finder for files / history / etc. | shell init |
| **direnv** | Auto-load `.env` per project | shell init |
| **eza** | Better `ls` with git status | aliased over `ls`, `ll`, `lt` |
| **bat** | Better `cat` with syntax highlighting | aliased over `cat`, `less` |
| **ripgrep** (`rg`) | Fast `grep` with sane defaults | `~/.config/ripgrep/config` |
| **lazygit** | Visual TUI for git | `~/.config/lazygit/config.yml` |
| **glow** | Render markdown in terminal | n/a |
| **gh-dash** | TUI for GitHub issues + PRs | `~/.config/gh-dash/config.yml` |

All themed `cisco-dark` (dark navy bg + bright cyan accents).

## Quick Aliases

Defined in `~/.zshrc`:

| Alias | Runs | When you'd use it |
|-------|------|-------------------|
| `cat` | `bat --paging=never` | Reading any file with syntax highlight |
| `less` | `bat` | Same, with paging |
| `ls` | `eza --group-directories-first` | Day-to-day listing |
| `ll` | `eza -la --git --group-directories-first` | See git status per file |
| `lt` | `eza --tree --git-ignore --level=3` | Quick tree view (3 levels deep) |
| `gd` | `gh dash` | Open GitHub issues/PRs dashboard |
| `lg` | `lazygit` | Open git TUI |
| `md` | `glow` | Render a markdown file |
| `c` | `claude` | Launch Claude Code |

## Navigation

Built around the fact that `cd` was your #1 command (411 uses).

| Command | Does |
|---------|------|
| `cd <name>` | Smart cd via zoxide. After a few uses, `cd fig` jumps to `~/dev/projects/figment`. |
| `cd <name>` (first time) | Falls back to CDPATH lookup — `cd figment` works from any directory because `~/dev/projects` is in CDPATH. |
| `dev` | fzf-pick a project from `~/dev/projects` interactively. Type, fuzzy-filter, enter. |
| `recent` | Jump into the most recently modified project under `~/dev/projects`. |
| `cd -` | Jump back to previous directory (built-in zsh). |

**Behavior on new shell**: opening a fresh terminal at `$HOME` auto-cds to `~/dev/projects` so `dev` and `cd <name>` work immediately. Subshells and scripts unaffected.

**zoxide tips**:

- `cd <name>` — jump to most-frecent match
- `cdi` — interactive picker over zoxide's history
- `zoxide query -l` — see what zoxide knows about
- `zoxide add <path>` — manually add a directory

---

## Ghostty

Terminal app. Launched from Spotlight or Dock like any macOS app.

**Hotkey**: press `Ctrl+\`` (backtick — the key to the left of`1`) anywhere in macOS to bring Ghostty (with your existing windows + tabs) to the front. Press again to hide. First trigger pops a System Settings prompt for Accessibility — approve it once.

**Reload config**: `Cmd+Shift+,` (comma) or quit + relaunch.

**Useful built-ins**:

- New tab: `Cmd+T`
- New window: `Cmd+N`
- Split right: `Cmd+D`
- Split down: `Cmd+Shift+D`
- Switch split: `Cmd+Opt+arrow`
- Close split/tab: `Cmd+W`

**Themes**: `cisco-dark` is default. To browse alternatives, run `ghostty +list-themes` from inside Ghostty.

---

## Zellij — multiplexer

Run inside Ghostty when you want **persistent sessions, splits, and the discoverable status bar**. Alternative to native Ghostty splits when you want everything to survive a quit/relaunch or remote work.

### Starting and stopping

```bash
zellij                          # new session
zellij --layout agents          # new session with the 3-pane agents layout
zellij ls                       # list running sessions
zellij a                        # attach to most recent
zellij a <name>                 # attach to a named session
zellij -s mysession             # new named session
exit                            # detach (closes the active pane)
```

### Modes

Zellij has modes. The status bar at the bottom **always shows the keys for the current mode** — you don't need to memorize anything. Press `Ctrl+G` to lock/unlock keys (useful when running another TUI inside zellij that has conflicting binds).

The modes you'll use most:

| Mode | How to enter | What it does |
|------|--------------|--------------|
| Normal | default | typing into the pane |
| Pane | `Ctrl+P` | splits, navigation, close, fullscreen |
| Tab | `Ctrl+T` | new tab, switch tabs, rename |
| Resize | `Ctrl+N` | resize the focused pane |
| Scroll | `Ctrl+S` | scroll back through pane history (also: search) |
| Session | `Ctrl+O` | detach, switch sessions |
| Move | `Ctrl+H` | rearrange panes |
| Locked | `Ctrl+G` | pass all keys through to the running app |

### Most-used moves

| Action | Sequence |
|--------|----------|
| New pane (right of focus) | `Ctrl+P` then `R` |
| New pane (below focus) | `Ctrl+P` then `D` |
| Close pane | `Ctrl+P` then `X` |
| Fullscreen toggle | `Ctrl+P` then `F` |
| New tab | `Ctrl+T` then `N` |
| Rename tab | `Ctrl+T` then `R` |
| Detach (session keeps running) | `Ctrl+O` then `D` |
| Move focus | `Alt+arrow` |
| Resize | `Ctrl+N` then arrows |
| Scroll back | `Ctrl+S`, then arrows / `PgUp` / `/search` |

### The agents layout

```bash
zellij --layout agents
```

Drops you into 3 panes:

- **primary** (60% width): your main agent (e.g. `opencode` or `claude`)
- **reviewer** (top right): second agent (e.g. `codex`)
- **shell** (bottom right): for `git`, `npm test`, ad-hoc commands

You start each tool manually after the panes appear — that way you can choose what to run.

---

## Atuin — history

Replaces `Ctrl+R` with a fuzzy, ranked, full-text searchable history. Every command, including exit code, runtime, and which directory you ran it in.

### Search (most-used)

Press `Ctrl+R`. Type. Use arrows to navigate, Enter to run, Tab to edit before running.

| Inside the search UI | Action |
|---------------------|--------|
| `Tab` | Place command on prompt without executing |
| `Enter` | Execute selected |
| `Esc` | Cancel |
| `Ctrl+C` | Cancel |
| `Alt+1..9` | Pick result by number |

### Filters (type these inside the search box)

- `mtg` → matches commands containing `mtg`
- `git push` (leading space) → exact phrase
- `directory:~/dev/projects/figment` → only commands run in that dir

### Other useful commands

```bash
atuin search "git push"     # search from CLI without UI
atuin stats                 # see your most-used commands
atuin history list          # list recent
atuin import zsh            # already done; re-run if you nuke history
```

(Sync across machines is optional — requires `atuin register`. Local-only works without it.)

---

## fzf — fuzzy finder

Already wired into your shell:

| Keybind | Does |
|---------|------|
| `Ctrl+T` | Insert a fuzzy-selected file path at the cursor |
| `Alt+C` | `cd` into a fuzzy-selected directory |
| `Ctrl+R` | (handled by atuin instead) |

Pipe anything into it for ad-hoc fuzzy filtering:

```bash
git branch | fzf            # pick a branch
ls | fzf                    # pick a file
gh pr list | fzf            # pick a PR
```

---

## direnv — auto-load `.env`

When you `cd` into a project with a `.envrc` file, direnv auto-exports those vars and unsets them when you leave.

### One-time per project

```bash
cd ~/dev/projects/some-project
echo 'dotenv' > .envrc           # tell direnv to load .env
direnv allow                     # one-time approval (security)
```

After that, any time you `cd` into that project, the `.env` is loaded. `cd` out and it's unloaded.

### Why this matters for you

You have ~19 `.env` files across projects. Without direnv you have to remember which keys belong to which project. With direnv it just works — and your global `~/.zshrc` keys stay as fallback.

### Useful

```bash
direnv status            # what's loaded
direnv reload            # re-source .envrc
direnv allow             # approve current dir's .envrc
direnv deny              # revoke
```

---

## eza — better `ls`

Already aliased. Some quick power moves:

```bash
eza -la --git                       # detailed, with git status column
eza --tree --level=2                # tree view, 2 levels
eza --tree --git-ignore             # tree, hide gitignored
eza --sort=modified                 # sort by mtime
eza --long --git-repos              # show submodule status
```

---

## bat — better `cat`

Aliased over `cat` and `less`. Bypasses the alias with `\cat` if you need raw output (e.g., piping to a script).

```bash
bat README.md                       # syntax-highlighted
bat -p README.md                    # plain (no decorations)
bat --diff                          # show diff in piped input
```

Use `\cat file.json | jq .` if a script needs raw text.

---

## ripgrep (`rg`) — fast grep

Replaces `grep -r`. Honors `.gitignore` by default. Smart-case (case-insensitive unless you type uppercase).

```bash
rg 'TODO'                           # find TODO in current tree
rg 'TODO' -t md                     # only in markdown files
rg -l 'API_KEY'                     # just list filenames
rg -A 3 -B 1 'pattern'              # 3 lines after, 1 before
rg --json 'pattern'                 # JSON output for scripting
```

Your config at `~/.config/ripgrep/config` already excludes `.git`, `node_modules`, `.venv`, `dist`, `build`, `.next`, `.turbo`.

---

## lazygit — visual git

```bash
lg                                  # alias for lazygit
```

Inside, the basics:

| Key | Action |
|-----|--------|
| `1`-`5` | Switch panels (status, files, branches, commits, stash) |
| `space` | Stage/unstage file or hunk |
| `c` | Commit (writes a commit message in $EDITOR) |
| `P` | Push |
| `p` | Pull |
| `b` | Branch menu |
| `?` | Help (in any panel) |
| `q` | Quit |

For PR review: `5` for commits panel, navigate with arrows, `space` to view diff.

---

## glow — markdown in terminal

```bash
glow README.md                      # render a file
glow .                              # browse all .md files in cwd
gh issue view 42 | glow             # render a GitHub issue
gh pr view 12 | glow                # render a PR description
glow -p                             # paged mode
```

This is the one that solves your "Claude outputs markdown, I have to open Cursor to read it" problem. Pipe AI output through glow and it renders inline.

```bash
echo "# Heading\n\n- item 1\n- item 2" | glow
```

---

## gh-dash — GitHub TUI

```bash
gd                                  # alias for `gh dash`
```

Sections (configured in `~/.config/gh-dash/config.yml`):

- **My PRs** — open PRs you authored
- **Needs My Review** — PRs assigned to you
- **Recent** — other open PRs

| Key | Action |
|-----|--------|
| `tab` / `shift+tab` | Switch sections |
| `j` / `k` | Down / up |
| `enter` | Open in preview pane |
| `o` | Open in browser |
| `c` | Comment |
| `m` | Merge (if able) |
| `2` | Switch to issues view |
| `1` | Switch back to PRs view |
| `?` | Help |
| `q` | Quit |

Edit `~/.config/gh-dash/config.yml` to add more sections (per-repo, by label, etc.).

---

## Suggested Workflow

For agent-orchestration sessions:

```bash
cd ~/dev/projects/some-project
zellij --layout agents
```

In **primary**: `opencode`
In **reviewer**: `codex` (when you have a commit to review)
In **shell**: `lg` for git ops, `gd` for issue context, regular shell otherwise

Detach with `Ctrl+O` then `D`. The session keeps running. Reattach later with `zellij a`.

---

## Reset / Recovery

If anything's broken:

```bash
# Restore zshrc
ls ~/.zshrc.backup-*                 # find the backup from setup day
cp ~/.zshrc.backup-YYYYMMDD-HHMMSS ~/.zshrc

# Remove a tool
brew uninstall <tool>

# Reset a config
rm ~/.config/<tool>/config           # then re-run the tool to regen defaults
```
