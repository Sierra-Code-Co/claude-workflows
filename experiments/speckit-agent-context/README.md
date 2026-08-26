# speckit-agent-context

**Status:** killed

Not started as a deliberate experiment: salvaged from a stale install, never registered in the
fleet-owned file, never run. No further work is planned. The tree is retained rather than deleted because it is the
artifact the reasoning below is about, and because the objection in "The real objection" is
worth keeping on record for the next time this need surfaces.

## What this is

Spec-kit's `agent-context` extension plus the skill it registers. It maintains a
`<!-- SPECKIT START -->` / `<!-- SPECKIT END -->` managed block inside a project's
`CLAUDE.md`, pointing at the most recent `specs/<feature>/plan.md`, so an agent opening
the repo cold lands on the active plan without being told where to look.

Contents:

| Path | What |
|---|---|
| `skill/SKILL.md` | A skill file derived from the command, **not registered anywhere**. `extension.yml` `provides:` lists only the `speckit.agent-context.update` command, and `registry-snapshot.json` has `registered_skills: []`. Its frontmatter claims `author: github-spec-kit` and `source: agent-context:commands/speckit.agent-context.update.md`, so it was generated from the command rather than authored. |
| `extension/` | The extension itself: `extension.yml`, `agent-context-config.yml`, the command, and bash + powershell `update-agent-context` scripts |
| `registry-snapshot.json` | The `.specify/extensions/.registry` entry as it existed, recording `installed_at: 2026-08-04` |

## Why it's here and not in the template

It arrived in `internal-speckit-template` as output from a spec-kit **0.10.1** `specify init`
run, and then got orphaned:

- **Not in the pinned payload.** The template now pins spec-kit **1.0.1**, whose
  `speckit.manifest.json` lists 12 files and contains no `agent-context` entry. So this is
  not something a fresh bootstrap produces.
- **Not fleet-authored.** Frontmatter says `author: github-spec-kit`. Nobody here wrote it,
  so there is no local intent to preserve.
- **Never wired in.** Two files can register an extension and only one of them counts.
  `specify init` wrote this one into the auto-generated registry it manages,
  `.specify/extensions/.registry`, with `enabled: true` and one registered command (that is
  the `registry-snapshot.json` copied here). But `.specify/extensions.yml`, the fleet-owned
  registration file that `specify init` does not overwrite, registers only `review-plan-gate`.
  That is the file that would have made this fleet-managed, and it never named this extension.
- **Never propagated.** `.specify/extensions/` is neither tracked nor gitignored in the
  template, so `gh repo create --template` (tracked files only) never copied it to a new
  project. Confirmed against a freshly bootstrapped repo, which does not have it.

So it sat untracked in the template for weeks, doing nothing, showing up as `git status`
noise on every pull.

## Known defect, found on review and fixed here

The managed-block rewrite destroyed user content whenever the marker pair was incomplete.
With only a start marker present, both scripts replaced from that marker through end of file;
with only an end marker, they deleted everything preceding it. A partial merge or a single
hand edit reaches either state, and the next run then ate the section the operator was
editing. On the highest-blast-radius file in the repo.

Both scripts now write only for a complete, correctly ordered pair, and otherwise name the
malformed state on stderr, exit non-zero, and leave the file untouched
(`scripts/bash/update-agent-context.sh:179`, `scripts/powershell/update-agent-context.ps1:219`).

Verified against all four marker states by running the embedded Python block directly:
complete pair replaces the block and preserves surrounding content; start-only and end-only
both refuse with exit 1 and leave the file byte-identical; no markers appends. The bash
wrapper's `set -euo pipefail` and the powershell wrapper's `$ErrorActionPreference = 'Stop'`
both abort before the "updated" line, so a refusal cannot be mistaken for a success.

This fix does **not** revive the experiment. The code is still spec-kit 0.10.1-era output
against a 1.0.1 pin and still needs a parity pass before anyone runs it. It was worth fixing
in place rather than committing a known data-loss bug, however dormant.

## The real objection, if it were ever revived

It **rewrites `CLAUDE.md` automatically.** That runs against the fleet convention that hooks
remind but never auto-fire — the same reasoning behind `optional: true` on the
`review-plan-gate` hook and `disable-model-invocation: true` on every skill. An automatic
edit to the one file every agent reads first is the highest-blast-radius auto-write in the
repo, and it would land without review.

If the underlying need turns out to be real (agents not finding the active plan), the
cheaper version is a static line in the template `CLAUDE.md` telling the agent to read the
newest directory under `specs/`. No script, no managed block, no auto-write.

## Next step

None. Revisit only if agents demonstrably fail to locate the active spec, and prefer the
static-line alternative above if they do. Reviving this tree would need a spec-kit 0.10.1 ->
1.0.1 parity pass first.
