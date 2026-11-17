# Tasks: Public skill library, first release

**Input**: `specs/004-skill-library/` (spec, plan, research, data-model, contracts, quickstart)

Tests are required by the spec (FR-021). Every guard test is run once with its guard broken (Principle II); the result is noted beside the task.

## Phase 1: Setup

- [X] T001 Create `dotfiles/claude/skills/writing-check/{scripts,vendor/slop-guard}` and `dist/copilot/`
- [X] T002 Copy `~/.claude/skills/client-doc/{banned-phrases.txt,prose-lint.sh,prose-check.sh}` into the skill (lists at the skill root, scripts under `scripts/`)

## Phase 2: Foundational

- [X] T003 Write `scripts/pull-slop-guard.py` (download pinned wheel, verify sha256, deterministic pyz with overlay `typing_extensions.py` + `__main__.py`, copy LICENSE, write VENDOR.json; exit 2 on any mismatch)
- [X] T004 Run it for 0.5.0 to produce `dotfiles/claude/skills/writing-check/vendor/slop-guard/{slop-guard.pyz,LICENSE,VENDOR.json,README.md}`
- [X] T005 [P] `tests/unit/test_slop_guard_vendor.py`: pyz sha matches VENDOR.json; every RECORD member hash matches; only declared overlay members are extra; pyz runs under the test interpreter and prints 0.5.0. Break once (append a byte to a member) and watch it fail.

## Phase 3: User Story 1 — check a draft in Claude Code (P1)

- [X] T006 [US1] Harden `scripts/prose-lint.sh`: phrase list default `../banned-phrases.txt`; empty document exits 2; keep IFS-safe reads and per-check grep-exit-2 handling
- [X] T007 [US1] Update `scripts/prose-check.sh`: packed slop-guard first (`$PROSE_CHECK_PYTHON` ≥ 3.11 check), `sg` fallback, exit 2 when neither; temp file removed via trap; empty file exits 2; HTML reducer unchanged
- [X] T008 [US1] Scrub and extend `banned-phrases.txt`: neutral wording in comments; merge slop-guard word/phrase/weasel/tone/AI-disclosure literals with per-section credit; `# read-by-hand:` line for ambiguous words
- [X] T009 [US1] Write `SKILL.md` (standard frontmatter only; three layers; plain-word structural rules and phrase categories; style aid, not an authorship detector; pass marks; `client-doc` noted as a later, separate skill)
- [X] T010 [P] [US1] `tests/unit/test_writing_check.py`: 17 red, 12 green, tool errors (missing list, bad regex, comments-only list, missing doc, empty doc, no slop-guard at all, old Python), HTML comment vs `<p>`, packed fallback with `sg` hidden, calibration smoke tests (bullet-heavy email < 80 and paragraphs ≥ 80; one elaboration colon in a short note scores lower than without). Break each guard once.
- [X] T011 [P] [US1] Phrase-list coverage test in `tests/unit/test_writing_check.py`: every slop-guard literal (read from the pyz) is matched by a list entry or named on a read-by-hand line; every entry compiles

## Phase 4: User Story 4 — one copy, linked (P2)

- [X] T012 [US4] Extend `scripts/new-machine.sh` to link each `dotfiles/claude/skills/<name>` into `~/.claude/skills/` (idempotent, backs up a real dir)
- [X] T013 [P] [US4] `tests/unit/test_personal_skill_links.py` with `HOME` in a temp dir: creates, idempotent, backs up. Break once.
- [X] T014 [US4] Run `scripts/new-machine.sh` on this Mac; replace `client-doc`'s three copied files with symlinks into the repo; point `client-doc/SKILL.md` helper paths at the writing-check skill
- [X] T015 [US4] Update the prose sentence in `dotfiles/claude/CLAUDE.md` to `~/.claude/skills/writing-check/scripts/prose-check.sh` and `.../writing-check/banned-phrases.txt`
- [X] T016 [P] [US4] Update `dotfiles/README.md` file table for `claude/skills/`

## Phase 5: User Story 2 — install from the public repo (P2)

- [X] T017 [US2] Write `public/.claude-plugin/marketplace.json` per contracts/packaging.md (no `version`)
- [X] T018 [P] [US2] `tests/unit/test_marketplace.py`: valid JSON, names not reserved, no `version`, skill paths exist and sit under a manifest-listed directory, skill frontmatter meets the standard. Break once.
- [X] T019 [US2] Validate with `claude plugin validate` on a staged mirror tree if the CLI offers it; else install from a local marketplace path in a scratch dir and record the result

## Phase 6: User Story 3 — Copilot (P2)

- [X] T020 [US3] Write `scripts/build-copilot-zips.py` (`--check` mode) and build `dist/copilot/writing-check.zip`
- [X] T021 [P] [US3] `tests/unit/test_copilot_zip.py`: SKILL.md at root, depth ≤ 3, file count and size limits, frontmatter limits, committed zip equals a fresh build. Break once.
- [X] T022 [US3] Ask Jason; on yes, upload the zip on the Sierra Code Co. test tenant in the browser, run a red and a green sample, record results in `research.md` "Copilot result"; rebuild without `vendor/` if the pyz cannot run

## Phase 7: User Story 6 — weekly slop-guard check (P3)

- [X] T023 [US6] Write `scripts/check-slop-guard-version.sh` per contracts/cli.md
- [X] T024 [P] [US6] `tests/unit/test_slop_guard_version_check.py`: equal, behind, unreadable latest, missing VENDOR.json. Break once.
- [X] T025 [US6] Add slop-guard steps and a `slop-guard-update` labelled issue to `.github/workflows/check-speckit-update.yml`

## Phase 8: User Story 5 — guide and docs (P3)

- [X] T026 [US5] Re-check the guide's numbers against code.claude.com/docs (memory, best-practices, large-codebases, context-window) and record what changed
- [X] T027 [US5] Write `public/docs/organizing-projects-for-claude.md`
- [X] T028 [P] [US5] Update `public/docs/installing-skills.md` (marketplaces, Copilot upload incl. the Windows .md note, personal symlink; keep the disable-model-invocation and propagation sections)
- [X] T029 [P] [US5] Update `public/README.md` (library section, guide link) and `public/docs/architecture.md` (personal-skill layer)
- [X] T030 [P] [US5] Update `scripts/public-manifest.txt` (comments; add `dist/copilot/` and `specs/004-skill-library/`)
- [X] T031 [P] [US5] Write `decisions/0013-personal-skill-library.md` and add it to `decisions/README.md`
- [X] T032 [P] [US5] Update `README.md`, `STATE.md`, `CHANGELOG.md` in this repo

## Phase 9: Polish

- [X] T033 Run the full test suite and the writing check on the new public docs
- [ ] T034 (denylist replicated locally 2026-11-16: no hits in this branch; 2 pre-existing hits on main, see PR) Dry-run `scripts/sync-public.sh` (no `--apply`) and confirm `denylist gate: clean`
- [X] T035 `review-plan-v2 --static-only --base main`, unpiped; read the exit code and the files-reviewed line
- [ ] T036 Ask Jason, then open the PR; template README PR separately on yes

## Dependencies

Phase 2 before all stories. US1 before US4 (the linked folder must be complete), US2 and US3 (they package US1). US5 and US6 independent. T022 and T036 wait on Jason.

## Parallel examples

T005 alongside T006–T009; T010/T011 together; T013, T018, T021, T024 each beside their story's implementation; T028–T032 together.

## MVP

US1 (Phases 1–3): a tested writing check in the repo.
