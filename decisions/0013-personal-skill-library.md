# 0013 — Personal skills live in this repo and publish through the mirror; Claude Code and Copilot only

**Status:** active
**Date:** 2026-11-16
**Tags:** skills, publishing, repo-design, slop-guard, copilot
**Spec:** `specs/004-skill-library/`

## Context

Sierra Code Co. teaches clients to use AI tools, and Jason wanted a library of skills he uses every day and can point people to: useful to him first, public as a teaching and marketing piece. The first one is a writing check, built during client work on 2026-11-16 in an unversioned folder under `~/.claude/skills/`. One client works mainly in Microsoft 365 Copilot, which gained skill uploads in October and November 2026 using the same `SKILL.md` format as Claude Code (agentskills.io).

Two existing decisions bound the answer. ADR-0006 made this repo the home of the global config, linked into `~/.claude/` by symlink. ADR-0010 made `Sierra-Code-Co/claude-workflows` a generated mirror of this repo, built from an allowlist and gated by a denylist. `internal-speckit-template` stays the source of truth for *project* skills.

## Decision

1. **Personal skills live in `dotfiles/claude/skills/<name>/`** and `scripts/new-machine.sh` links each to `~/.claude/skills/<name>`, the same model as `CLAUDE.md`. The repo copy is the only copy. `dotfiles/` is already in the public manifest, so everything placed there is public on the next sync; nothing private goes in.
2. **Project skills do not move.** `speckit-*`, `review-plan`, `review-plan-v2`, `ship`, `feature` and the office skills stay in the template, which `propagate-skill.sh` reads.
3. **Publication is the existing mirror, two ways.** A Claude Code plugin list at the mirror root (`public/.claude-plugin/marketplace.json`, overlay only) and a committed Copilot upload zip per skill (`dist/copilot/`), built deterministically and checked against a fresh build by a test.
4. **The plugin list tracks commits; it carries no `version`.** Syncs are manual and deliberate. With a version field, a forgotten bump silently freezes every user on the old release, a failure that looks like success. Without it, `/plugin marketplace update` always gets the latest sync.
5. **slop-guard runs in three layers with the rules written once.** Where scripts run, the phrase list and a packed slop-guard both run. Where only instructions run, `SKILL.md` states slop-guard's structural rules and the phrase-list categories in plain words. slop-guard's word and phrase lists are merged into the phrase list, with ambiguous words on `# read-by-hand:` lines, and a test fails when an upstream release adds words nobody has classified.
6. **slop-guard is packed without editing it.** The zipapp carries every wheel file byte for byte and two overlay files (a `typing_extensions` shim and an entry point). The brief planned a one-line edit to `models.py`; constitution Principle VI forbids that, so the overlay replaced it. A test re-checks every packed file against the wheel's own `RECORD` hashes.
7. **Updates are never automatic.** The weekly `check-speckit-update.yml` gains a separate slop-guard job that opens an issue on a new PyPI release. A person runs `scripts/pull-slop-guard.py`, the tests and a PR.
8. **Claude Code and Microsoft 365 Copilot only.** Codex, Cursor and others wait until a client asks. GitHub Copilot already reads the same format, so supporting it later costs little.

## Why

- One copy, linked, is the rule that already works for `CLAUDE.md`. A second copy of a skill would drift on its first edit.
- No new repo: the mirror already has the allowlist, the denylist gate and the scrub-at-source rule, so a public skill inherits all three.
- A committed zip is convenient for Copilot users, who download one file; the byte comparison is what stops it being a second copy.

## Alternatives considered

- **A separate public skills repo** (the obra/superpowers shape): rejected, a second repo to keep in sync with no gain.
- **Personal skills in the template**: rejected, the template is what new projects copy; a personal skill there would be copied into every project.
- **`version` in the plugin entry**: rejected, see Decision 4.
- **Installing slop-guard with uv or pip**: rejected, Copilot's sandbox allows no installs and clients should not need a Python toolchain.

## Consequences

- `dotfiles/claude/skills/` is public by construction. A personal skill with private content has to live elsewhere.
- `client-doc` stays outside the repo until after mid-December 2026; its prose checks now call the writing-check skill.
- What would retire Decision 8: a client asking for Codex or Cursor, at which point the open format means a new install doc, not a new build.
