# dotfiles/

Canonical versions of files that live in `~/.claude/` and need to stay in sync across machines.

## Strategy: symlinks (not copies)

`scripts/sync-push.sh` creates symlinks from `~/.claude/<file>` → `dotfiles/claude/<file>`. That means:

- Edit the file in EITHER location and the change is live in BOTH.
- `git status` in this repo immediately shows your local changes.
- No risk of two machines drifting silently — the file is the file.

## Files in here

| File                          | Sync mode | Notes                                                                    |
| ----------------------------- | --------- | ------------------------------------------------------------------------ |
| `claude/CLAUDE.md`            | symlink   | Global instructions Claude reads in every session.                       |
| `claude/settings.example.json` | template  | Actual `settings.json` is gitignored. Fill in `~/.claude/settings.json` from this template on each machine. |
| `claude/skills/<name>/`       | symlink   | Personal skills (ADR-0013). `new-machine.sh` links each to `~/.claude/skills/<name>`. Everything here is published by the public mirror, so nothing private goes in. |

## Why settings.json is a template (not symlinked)

`~/.claude/settings.json` may grow to contain MCP server URLs that include org slugs (e.g., your Sentry MCP). That's not strictly secret, but it's also not interesting to share. More importantly:

- `~/.claude.json` (note: NOT `~/.claude/settings.json` — different file) holds MCP credentials added via `claude mcp add` (e.g., your GitHub PAT). NEVER commit it.
- Per-machine MCP server preferences may legitimately differ.

So we ship a sanitized example and let each machine maintain its own.

## What if I want to sync memory too?

Memory at `/Users/jabelk/.claude/projects/-Users-jabelk-dev-projects/memory/` is per-machine by default. If you want it to sync:

1. Symlink `~/.claude/projects/-Users-jabelk-dev-projects/memory/` → `dotfiles/claude/memory/`
2. Remove `dotfiles/claude/memory/` from `.gitignore`
3. Decide whether to commit personal facts publicly or use a private repo

Not done by default — opt in if you want it.
