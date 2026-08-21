# 0010 — Public mirror via allowlist sync; internal repo stays private

**Status:** active
**Date:** 2026-08-21
**Tags:** meta, repo-design, publishing

## Context

The user wants to share this repo's workflow material publicly — for credibility and for teaching spec-driven development — under the Sierra-Code-Co org. Flipping `internal-claude-workflows` itself to public was evaluated and rejected:

1. **The client roster is baked in.** `STATE.md`, `specs/002-fleet-cr-rollout/`, and git history name consulting clients (repo names, PR links). Whether the client list is disclosable is a per-engagement legal question; the safe default is no.
2. **Visibility flips publish history, issues, and PRs — not just the tree.** Scrubbing history means a rewrite that breaks the issues/PRs carried over in the org transfer.
3. **A gitleaks sweep of all 161 commits found no secrets** (2026-08-21), so credentials are *not* the blocker — names are. `.gitignore` already fences `.env`, `settings.json`, and `memory/`.

Precedent: `internal-speckit-template` is already public and serves as the bootstrap artifact people clone.

## Decision

Publish a **generated, curated mirror** at `Sierra-Code-Co/claude-workflows` (public, fresh history, MIT) rather than flipping the internal repo. Mechanics:

- `scripts/public-manifest.txt` — the explicit allowlist of paths that sync. Anything unlisted stays private. Notable exclusions: `STATE.md`, `CHANGELOG.md`, `CLAUDE.md`, `specs/002+`, `.claude/` and `.specify/` (skills already public in the template; a third copy would drift).
- `public/` — overlay files that exist only in the mirror: its README, `docs/` guides (architecture, SDD walkthrough, multi-model review, skills install, spec-kit lineage), LICENSE.
- `scripts/sync-public.sh` — rebuilds the mirror tree from scratch each run (manifest + overlay), then **fails closed** on two gates before committing: a denylist grep (`scripts/public-denylist.txt` — client names and private-person patterns; the denylist itself is hard-excluded from sync) and a gitleaks scan of the staged tree. Dry-run by default; `--apply` commits `sync: internal@<sha>`; `--push` pushes.
- **Scrub at source, not in transit.** A file that trips the denylist gets fixed in *this* repo (client names don't belong in reusable scripts/docs anyway) or dropped from the manifest — the sync never rewrites content, so the mirror is always byte-identical to allowlisted internal files.
- Cadence: re-run after merges that touch manifest paths. Manual for now; a CI trigger would need a cross-repo deploy key (deferred — new credential).

**The template stays a separate repo.** `internal-speckit-template` is the *clone-me bootstrap* (a mechanical artifact: `newproject` targets it, `propagate-skill.sh` reads from its local clone); the public mirror is the *documentation front door* that links to it. Merging them was considered and rejected: a template full of ADRs and teaching docs is a worse template, and retargeting the propagation tooling buys nothing. One front door, two artifacts with distinct jobs.

## Consequences

- Sharing is one URL: the mirror. The template README should point back to it for docs.
- Every future file in a manifest path is public by default on next sync — writing client names into `scripts/`, `decisions/`, or `references/` now has a tripwire (the denylist gate) instead of a convention.
- The mirror's history is sync commits only; it carries no pre-publication history to audit.
- New "never publish" names (clients, private individuals) must be added to `scripts/public-denylist.txt` as they appear.
