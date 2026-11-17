# Implementation Plan: Public skill library, first release

**Branch**: `004-skill-library` | **Date**: 2026-11-16 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/004-skill-library/spec.md`

## Summary

Move the writing check from an unversioned folder on Jason's Mac into `dotfiles/claude/skills/writing-check/`, link it back with the bootstrap script, carry slop-guard 0.5.0 inside it as a pristine zipapp plus one overlay shim, fold slop-guard's word and phrase lists into the phrase list with a coverage test that forces review on every bump, and publish it two ways: a Claude Code plugin list in the mirror overlay and a deterministic Copilot upload zip. Add the slop-guard version to the weekly update workflow, a public guide on organizing projects for Claude, an ADR, and doc updates.

## Technical Context

**Language/Version**: Bash (scripts, as today), Python 3.11+ standard library (slop-guard floor; the HTML reducer, builders and pull-in script). CI runs 3.12.

**Primary Dependencies**: slop-guard 0.5.0 (MIT, vendored as a zipapp; no runtime install). grep -E with `\b` (BSD and GNU both support it).

**Storage**: Files only. `VENDOR.json` beside the packed file records version and hashes.

**Testing**: pytest under the existing `uv`/`.venv` setup, `tests/unit/`. Scripts are exercised as subprocesses.

**Target Platform**: macOS (Jason), Linux (CI, Copilot sandbox), Claude Code plugin cache, Microsoft 365 Copilot Chat in the browser.

**Project Type**: Skill package plus build and maintenance scripts.

**Performance Goals**: A full check on a 2,000-word document completes in under 5 seconds.

**Constraints**: Nothing to install for users. Copilot zip within Agent Builder limits (depth 3, 350 files, 25 MB per file). `SKILL.md` under 500 lines and 20,000 characters. No client names anywhere public.

**Scale/Scope**: One skill, about 260 phrase-list entries, one guide, one ADR, five doc updates.

## Constitution Check

| Principle | How this plan complies |
| --- | --- |
| I. Fail-Visible Degradation | Every tool error exits 2 with a reason: empty input, zero rules loaded, missing slop-guard, Python too old, unexpected `sg` exit. The weekly check fails when either version is unknown. Success lines state counts ("N phrases checked", the score). |
| II. Provable Failure | Each guard's test is run once with the guard broken (recorded in tasks). The phrase-list coverage test fails on a list missing an upstream word. |
| III. Deterministic answers | "Did we merge every slop-guard word?" is answered by a test that imports the lists from the packed file, not by reading. "Is the zip current?" is a byte comparison against a fresh build. |
| IV. Uncensored measurement | No telemetry is added. |
| V. Verify before asserting | Copilot behaviour is recorded from an actual upload, not from Microsoft's docs; guide numbers are re-checked against the docs before publishing. |
| VI. Pristine Upstream | slop-guard files are carried byte-for-byte; a test checks every member against the wheel's own `RECORD` hashes. The one compatibility need is a separate overlay module, declared in `VENDOR.json`. **This replaces the brief's planned edit to `models.py`.** |
| VII. Fix upstream, propagate down | Personal skills now have one canonical copy (this repo); `client-doc`'s old copies become symlinks to it. The template README change goes to the template repo in its own PR. |

Gate result: PASS. No violations to justify.

## Project Structure

### Documentation (this feature)

```text
specs/004-skill-library/
├── plan.md          # this file
├── research.md      # decisions and the Copilot test record
├── data-model.md    # files and their invariants
├── quickstart.md    # validation walk-through
├── contracts/
│   ├── cli.md       # prose-lint / prose-check / sg arguments and exit codes
│   └── packaging.md # marketplace.json, Copilot zip, VENDOR.json
└── tasks.md
```

### Source Code (repository root)

```text
dotfiles/claude/skills/writing-check/        # THE copy; ~/.claude/skills/writing-check links here
├── SKILL.md
├── banned-phrases.txt
├── scripts/
│   ├── prose-lint.sh
│   └── prose-check.sh
└── vendor/slop-guard/
    ├── slop-guard.pyz        # wheel members unmodified + typing_extensions.py overlay + __main__.py
    ├── LICENSE               # upstream MIT licence, unmodified
    ├── VENDOR.json           # version, wheel sha256, pyz sha256, overlay list
    └── README.md             # provenance and how to bump

scripts/
├── pull-slop-guard.py        # pinned version + sha256 -> rebuild vendor/slop-guard/
├── build-copilot-zips.py     # dotfiles/claude/skills/* -> dist/copilot/<name>.zip
├── check-slop-guard-version.sh  # used by the weekly workflow; testable with stubs
└── new-machine.sh            # + links every dotfiles/claude/skills/<name>

dist/copilot/writing-check.zip   # committed, checked against a fresh build

public/
├── .claude-plugin/marketplace.json   # mirror-only plugin list
├── README.md                          # + library section
└── docs/
    ├── installing-skills.md           # + marketplaces, Copilot, symlink
    ├── architecture.md                # + personal-skill layer
    └── organizing-projects-for-claude.md   # new guide

decisions/0013-personal-skill-library.md
.github/workflows/check-speckit-update.yml   # + slop-guard steps
tests/unit/test_writing_check.py, test_slop_guard_vendor.py, test_copilot_zip.py,
          test_marketplace.py, test_personal_skill_links.py, test_slop_guard_version_check.py
```

**Structure Decision**: The skill sits under `dotfiles/claude/skills/` because `dotfiles/` is already the "identical on every machine, symlinked into `~/.claude/`" layer and is already in the public manifest. The packed file lives in `vendor/` rather than `scripts/` so the standard's `scripts/` folder holds only our own code. Copilot zip depth is root, `scripts/` or `vendor/slop-guard/`: at most 3.

## Complexity Tracking

None. Two small Python builders and one shell check; no new runtime dependency (slop-guard is vendored, not installed).
