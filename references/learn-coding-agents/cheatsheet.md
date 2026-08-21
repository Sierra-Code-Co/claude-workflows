# Cheat Sheet — One Page

The condensed version of everything. For full detail see `04-terminal-setup.md` and `05-workflows.md`.

---

## Navigation

| Command | Does |
|---------|------|
| `cd <name>` | zoxide smart cd → most-frecent match |
| `cd <name>` (first time) | falls back to CDPATH (`~/dev/projects` in PATH) |
| `dev` | fzf project picker |
| `recent` | most recently modified project |
| `cdi` | interactive zoxide picker |
| `cd -` | previous directory |
| `Alt+C` | fzf-pick a directory and `cd` |

New shell at `$HOME` → auto-cds to `~/dev/projects`.

## Aliases

| Alias | Runs |
|-------|------|
| `c` | `claude` |
| `cs` | `claude-squad` (smart — auto-fzf-picks project if not in git repo) |
| `cheat` | render the full cheat sheet via glow |
| `cheat-find <topic>` | grep docs for topic, fzf-pick a match, render |
| `cat` | `bat --paging=never` |
| `less` | `bat` |
| `ls` / `ll` / `lt` | `eza` (plain / detailed+git / tree) |
| `gd` | `gh dash` |
| `lg` | `lazygit` |
| `md` | `glow` |

Bypass an alias with backslash: `\cat file` for plain cat.

## History (atuin)

| Key | Does |
|-----|------|
| `Ctrl+R` | search history |
| `Tab` (in search) | put on prompt without running |
| `Enter` | run |
| `Alt+1..9` | pick result by number |

Filters inside search: `directory:~/dev/projects/figment`, `exit:0`, `git push` (leading space = exact phrase).

## Files (fzf, ripgrep, bat, eza)

| Command / key | Does |
|---|---|
| `Ctrl+T` | fzf-pick a file, insert path at cursor |
| `rg 'pattern'` | fast grep (honors .gitignore) |
| `rg 'pattern' -t md` | only markdown files |
| `rg -l 'pattern'` | just filenames |
| `bat file` | view with syntax highlight |
| `eza --tree --level=2` | tree view |

## Zellij (multiplexer)

```bash
zellij                       # new session
zellij --layout agents       # 3-pane agent layout
zellij ls                    # list sessions
zellij a                     # attach to most recent
```

| Mode (Ctrl+letter) | What |
|---|---|
| `Ctrl+P` | Pane mode (splits, close, fullscreen) |
| `Ctrl+T` | Tab mode |
| `Ctrl+N` | resize Notes |
| `Ctrl+S` | Scroll mode |
| `Ctrl+O` | sessiOn (detach with `D`) |
| `Ctrl+G` | locked (passthrough all keys) |

Pane mode → `R` new right, `D` new down, `X` close, `F` fullscreen.
Move focus: `Alt+arrow`. Status bar shows current keys.

## Git (lazygit)

```bash
lg                           # opens lazygit
```

| Key | Action |
|---|---|
| `1`–`5` | switch panels (status, files, branches, commits, stash) |
| `space` | stage/unstage |
| `c` | commit |
| `P` | push |
| `p` | pull |
| `b` | branches menu |
| `?` | help |
| `q` | quit |

## GitHub (gh-dash)

```bash
gd                           # gh dashboard
```

| Key | Action |
|---|---|
| `tab` / `shift+tab` | switch sections |
| `j` / `k` | down / up |
| `enter` | preview |
| `o` | open in browser |
| `c` | comment |
| `m` | merge |
| `1` / `2` | PRs view / Issues view |
| `?` | help |
| `q` | quit |

## Markdown (glow)

```bash
glow file.md                 # render
glow -p file.md              # paged
glow .                       # browse all .md in dir
gh issue view 42 | glow      # render an issue
gh pr view 12 | glow         # render a PR
pbpaste | glow               # render clipboard contents (the killer pattern)
```

## Env vars (direnv)

```bash
echo 'dotenv' > .envrc       # one-time per project
direnv allow                 # one-time per .envrc
direnv status                # what's loaded right now
direnv reload                # re-source after editing .env
```

After setup: cd into project → keys load. cd out → keys unset.

## Ghostty (terminal)

| Key | Does |
|---|---|
| `Ctrl+\`` | global hotkey — show/hide Ghostty (preserves existing windows + tabs) |
| `Cmd+T` | new tab |
| `Cmd+N` | new window |
| `Cmd+D` | split right |
| `Cmd+Shift+D` | split down |
| `Cmd+Shift+,` | reload config |

(zellij splits beat Ghostty splits when you want persistence and discoverable keys.)

## Daily Workflow Defaults

```bash
# morning: see what's open
gd

# start a feature
cd <project>
zellij --layout agents
# primary pane: c    (= claude)  or  opencode
# reviewer pane: codex
# shell pane: lg, gd, regular shell

# read agent markdown without leaving terminal
pbpaste | glow

# detach (session keeps running)
Ctrl+O then D

# reattach later
zellij a
```

## Parallel Agents (Claude Squad)

```bash
cs                              # open TUI (auto-fzf-picks a project if not in a git repo)
cs -y                           # with autoyes (experimental)
cs -p opencode                  # default to opencode for new instances
claude-squad reset              # nuke all stored instances (use the full name to bypass the wrapper)
```

In TUI: `n` new instance, `N` new with different program, `tab` switch, `enter` focus, `esc` unfocus, `?` help, `q` quit (sessions persist).

**Note**: `cs` requires being inside a git repo. Our wrapper auto-prompts you to pick one if you're not.

## When You Forget Something

- `cheat` → render this whole sheet (paged)
- `cheat-find <topic>` → grep all learn-coding-agents docs for a topic, fzf-pick, render
- `alias` → list all aliases
- `zoxide query -l` → see zoxide's database
- `atuin stats` → your top commands
