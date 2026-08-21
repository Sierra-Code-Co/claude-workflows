# 0007 — User-scope permissions baseline

**Status:** active
**Date:** 2026-04-27
**Tags:** permissions, settings, propagation

## Context

Each peer project's `.claude/settings.local.json` carried the same allow/deny block: `Bash`, the standard tools (Read/Edit/Write/Glob/Grep/WebSearch/WebFetch), and the destructive-op denies (`rm -rf`, `git push --force`, `git reset --hard`, `git branch -D`, etc.). Adding a new project meant copy-pasting it. Drift accumulated when one project was tweaked but the rest weren't.

When the user asked "can we update for all future projects so I don't need to do this for every project," the cleaner answer turned out to not be templating but cascading.

## Decision

Put the baseline allow/deny in `~/.claude/settings.json` (user-scope). Permission arrays union across scopes (user → project → local), so the baseline applies to every project automatically. Per-project `.claude/settings.local.json` is reserved for project-specific additions only: MCP tool names not covered by the user-scope MCP read patterns, `.specify/*` scripts, etc.

Mirror the same block in `dotfiles/claude/settings.example.json` so a freshly-bootstrapped machine inherits the default.

**Baseline allow** (14 entries):

- Tools: `Bash`, `Read`, `Edit`, `Write`, `Glob`, `Grep`, `WebSearch`, `WebFetch`, `Monitor`
- MCP read patterns: `mcp__*__get_*`, `mcp__*__list_*`, `mcp__*__search_*`
- Explicit GitHub reads not matching the prefixes: `mcp__github__issue_read`, `mcp__github__pull_request_read`

**Baseline deny** (9 entries — destructive ops):

- File: `Bash(rm -rf:*)`, `Bash(rm -r:*)`, `Bash(rmdir:*)`
- Git: `Bash(git push --force:*)`, `Bash(git push -f:*)`, `Bash(git reset --hard:*)`, `Bash(git checkout -- :*)`, `Bash(git clean -f:*)`, `Bash(git branch -D:*)`

## Why

- **DRY** — one place, every project picks it up.
- **No drift** — can't update one project and forget the others.
- **Retroactive** — fixes the existing fleet without per-repo edits, unlike a template-only change.
- **MCP wildcards confirmed canonical** — `mcp__*__get_*` style prefix patterns are documented at <https://code.claude.com/docs/en/permissions.md#mcp>; same matcher as Bash specifiers.
- **Destructive MCP tools still prompt** — `create_*`, `delete_*`, `merge_pull_request`, `apply_migration`, `deploy`, `add_*_comment`, `request_copilot_review`, etc. don't match read prefixes, so they keep their human-in-the-loop behavior.

Alternatives considered:

- **Continue per-project** — verbose, drift-prone. Status quo failure mode.
- **Update `claude-speckit-template` only** — applies to new projects only; doesn't fix existing fleet. Half a solution.
- **`mcp__github__*`** (allow all of one server) — auto-allows `delete_file`, `create_or_update_file`, `merge_pull_request`, `add_issue_comment`. Too broad.
- **`mcp__github(write:*)` or category rules** — don't exist; only three forms (`mcp__server`, `mcp__server__*`, `mcp__server__toolname`) plus prefix wildcards are valid.

## Consequences

- **New projects:** no allow/deny block needed in `settings.local.json` unless adding project-specific tools.
- **Existing projects:** their `settings.local.json` files now contain redundant duplicates of the baseline. Permission arrays union across scopes, so it's not breaking anything — but they can be thinned to just project-specific extras whenever touched. No bulk cleanup is required or planned.
- **Grey-zone GitHub tools** (`add_issue_comment`, `add_comment_to_pending_review`, `pull_request_review_write`, `request_copilot_review`, `update_pull_request`, `update_pull_request_branch`, `merge_pull_request`) still prompt — explicit choice to keep human-in-the-loop for visible or external actions.
- **`Bash` is broad** — denies cover the common destructive vectors but not everything. Consistent with peer projects' existing pattern; tightening is a separate decision if it ever bites.

## Verification

- New session in any project: `Bash`/`Read`/`Edit` etc. don't prompt.
- New session: `mcp__github__get_me` doesn't prompt.
- New session: `mcp__github__add_issue_comment` still prompts.
- Per-project allowlists for project-specific MCPs (e.g. `mcp__supabase__execute_sql`) continue to work.
- New machine bootstrap from `dotfiles/claude/settings.example.json` produces the same behavior on first launch.
