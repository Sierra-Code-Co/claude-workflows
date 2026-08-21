# 0006 — claude-workflows repo structure

**Status:** active
**Date:** 2026-04-27
**Tags:** meta, repo-design

## Context

Conversations about Claude Code improvements were happening ad-hoc in chat sessions, with no persistent record. Three concrete needs:

1. **Cross-machine sync** — global `~/.claude/CLAUDE.md`, settings, MCP installs all live per-machine; no version control
2. **Decision tracking** — why is `/feature` structured this way? Why GitHub MCP user-scope? Why org-scoped Sentry? Without ADRs, future-me re-litigates these
3. **Improvement backlog** — ideas from `/insights` reports, video tutorials, etc. need a queue, not just a chat history

Existing `claude-speckit-template` is the bootstrap target for new projects. Polluting it with WIP experiments and personal config breaks its job.

## Decision

Create a separate repo `claude-workflows` at `~/dev/projects/claude-workflows/`. Three layers, clear separation:

| Layer              | Owns                                            | Lifecycle               |
| ------------------ | ----------------------------------------------- | ----------------------- |
| `claude-workflows` | Personal config, decisions, experiments, tooling | Continuously evolving   |
| `claude-speckit-template` | Stable bootstrap for new projects        | Updates when patterns mature |
| Active projects    | Project code + project-specific overrides       | Per-project             |

Structure (see `README.md` for full layout):

- `dotfiles/claude/` — canonical `CLAUDE.md` + sanitized `settings.example.json`
- `scripts/` — `new-machine.sh`, `sync-push.sh`, `sync-pull.sh`, `propagate-skill.sh`
- `decisions/` — ADRs (this file is one of them)
- `experiments/` — WIP that hasn't graduated
- GitHub issues — backlog, labeled `idea` / `experiment` / `graduated` / `killed` / `meta`

Sync strategy: **symlinks** (not chezmoi/stow). Simple, no learning curve, edits in either location are live in both.

## Why

- **Different lifecycles** — template = stable; workflows = evolving. Mixing them creates pressure to either freeze experiments (bad) or destabilize bootstrap (worse).
- **Symlinks over copy** — copy needs a "which is canonical" answer every time you edit. Symlinks make it not a question.
- **Symlinks over chezmoi** — chezmoi handles per-machine templating, but I don't need that yet. YAGNI.
- **GitHub issues over a `backlog.md`** — better filtering, labels, can link to ADRs and PRs, free.
- **ADRs as files** — searchable in repo, survive history rewrites, can be linked from CHANGELOG and issues.

Alternatives considered:

- **Extend `claude-speckit-template`** — rejected: contaminates bootstrap with personal/experimental content.
- **Use a Notion/Obsidian vault** — rejected: outside the workflow, not version-controlled, doesn't sync with the symlink approach.
- **`chezmoi`** — overkill for current needs. Reconsider if I add many machines or templated configs.

## Consequences

- Two repos to maintain (template + workflows) instead of one. Acceptable cost.
- New-machine setup is now: clone two repos, run `new-machine.sh`, install Claude Code, run a few `claude mcp add` commands. ~5 min.
- Skill propagation across active projects becomes scripted (`propagate-skill.sh`) instead of manual.

## Verification

- New machine setup completes in under 10 min
- Decisions captured here can be cited in future conversations ("see ADR-0002")
- After 30 days: count how many ad-hoc decisions in chat got captured here vs lost
