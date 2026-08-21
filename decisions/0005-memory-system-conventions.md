# 0005 — Memory system conventions

**Status:** active
**Date:** 2026-04-26
**Tags:** memory, global-config, conventions

## Context

Claude Code's auto-memory system stores per-user, per-project memories at `~/.claude/projects/<project-key>/memory/`. The structure is:

- `MEMORY.md` — index file, always loaded into context (truncates after line 200)
- `<topic>.md` files — typed memories (`user`, `feedback`, `project`, `reference`) referenced from `MEMORY.md`

Global instructions in `~/.claude/CLAUDE.md` define when and how to write memories. Without conventions, memory grows unstructured and stale.

## Decision

Follow these conventions for memory writes:

1. **Type discipline** — every memory is one of: `user`, `feedback`, `project`, `reference`. No "misc."
2. **Why, not what** — for `feedback` and `project` entries, include `**Why:**` and `**How to apply:**` lines. Knowing the reason lets future-me judge edge cases instead of blindly following.
3. **Index entries are one-liners** — `MEMORY.md` is an index, not a memory. Each line ≤150 chars: `- [Title](file.md) — one-line hook`.
4. **Save validated successes too** — not just corrections. If a non-obvious approach worked and the user said "yes that's right," capture it as `feedback`. Otherwise the memory drifts toward overcaution.
5. **Convert relative dates to absolute** — "Thursday" → "2026-03-05" so the memory remains interpretable after time passes.
6. **Verify before recommending** — a memory that names a function/file is a claim about state at write-time. Grep before suggesting an action based on it.

These are codified in `~/.claude/CLAUDE.md` (the auto-memory section).

## Why

- Type discipline prevents memory becoming a junk drawer.
- Why-lines turn rules into judgment calls.
- One-line index avoids the "MEMORY.md balloons past 200 lines and gets truncated" failure mode.
- Capturing successes (not just corrections) keeps memory balanced.

## Consequences

- Slight overhead per memory write (more structured, longer to compose).
- Memory becomes useful as a *narrative of decisions*, not just a list of preferences.

## Verification

- `MEMORY.md` line count stays under 200 across all project directories
- Memory entries that get acted on are easy to interpret 30+ days later
- When a memory turns out wrong, it's easy to find and update (clear naming + types)
