# Feature Specification: Public skill library, first release (writing check + project-organization guide)

**Feature Branch**: `004-skill-library`

**Created**: 2026-11-16

**Status**: Draft

**Input**: `experiments/skill-library-brief-2026-11-16.md` plus the fuller session prompt of 2026-11-16 (the prompt wins where they differ). Public Sierra Code Co. skill library, first release: a writing-check skill published through the existing public mirror as a Claude Code plugin and a Microsoft 365 Copilot upload, personal skills moved into this repo behind a symlink, slop-guard added to the weekly update check, a public guide on how projects are organized for Claude, and related doc updates.

## Background

Sierra Code Co. teaches clients to use AI tools. Jason works mostly in Claude Code; one consulting client mostly uses Microsoft 365 Copilot. During client work on 2026-11-16 Jason kept finding Claude-style phrasing in drafts and presenter notes ("Two blanks only you can fill", "Name them once.", "That is the lesson:"). A writing check was built on his Mac that day, outside version control. This feature makes it a versioned, tested, public skill that he runs daily and can point clients to, and adds a public guide on how he layers CLAUDE.md files across projects.

### Decisions carried in (not re-opened here)

- The library lives in this repo and goes public through the existing generated mirror (ADR-0010). No new repo, no fork.
- Claude Code and Microsoft 365 Copilot only.
- slop-guard is kept, in three layers with the rules written once (scripts where scripts run, plain-word rules where only instructions run, its word and phrase lists merged into ours).
- Personal skills live in this repo and `~/.claude/skills/<name>` is a symlink to them; project skills stay in `internal-speckit-template`.
- `client-doc` (the house-style PDF pipeline) waits until after mid-December.
- No local cron: the existing weekly GitHub workflow gains a slop-guard check that only opens an issue.

### Concrete problem found while specifying

Constitution Principle VI (Pristine Upstream) forbids hand-editing vendored files. The brief planned a one-line edit to slop-guard's `models.py` (`typing_extensions` to `typing`). This spec replaces that edit with an **overlay**: the packed file carries slop-guard's files byte-for-byte as published, plus a small separate shim module that supplies the one missing name. The upstream archive's hash is recorded, so drift reporting can tell "changed upstream" from "modified locally" (nothing is modified locally). The same applies to slop-guard's version lookup, which needs the package metadata; the metadata is carried unmodified rather than the lookup being patched.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Check a draft before it ships, in Claude Code (Priority: P1)

Jason (or Claude acting for him) finishes a client email, document or handout and runs the writing check on it. The check reports every phrase-list hit and slop-guard's structural findings with a score, and exits with a status that a script or a person can trust: clean, flagged, or the check itself could not run.

**Why this priority**: This is the daily use. Everything else is distribution of this.

**Independent Test**: On a fresh shell with nothing installed beyond the operating system's Python and the repo, run the check on a known-bad file and a known-good file and see exit 1 and exit 0.

**Acceptance Scenarios**:

1. **Given** a text containing "Five things you may want to know:", **When** the lint runs, **Then** it names the matching phrase and line and exits 1.
2. **Given** "Switch Web search off if it should use only your files.", **When** the lint runs, **Then** it exits 0 and states how many phrases were checked.
3. **Given** the phrase list is missing, contains an invalid pattern, or contains only comments, **When** the lint runs, **Then** it exits 2 and says why.
4. **Given** an HTML file whose only file name sits inside an HTML comment, **When** the full check runs, **Then** it passes; **Given** the same name in a paragraph, **Then** it is flagged.
5. **Given** a machine with no `sg` on PATH, **When** the full check runs, **Then** it uses the packed slop-guard and still scores the text.
6. **Given** the packed slop-guard is missing and no `sg` is on PATH, **When** the full check runs, **Then** it exits 2.

---

### User Story 2 - Install the writing check from the public repo (Priority: P2)

A reader of the public mirror (a client, a workshop participant, a stranger) adds the Sierra Code Co. plugin list in Claude Code and installs the writing check with two commands, and it works without installing anything else.

**Why this priority**: This is the public, marketing half of the decision, and the cheapest way for a client to get the check.

**Independent Test**: In a scratch directory, add the marketplace from a local copy of the staged mirror tree, install the plugin, and invoke the skill.

**Acceptance Scenarios**:

1. **Given** the mirror is published, **When** a user runs `/plugin marketplace add Sierra-Code-Co/claude-workflows` then `/plugin install writing-check@sierra-code-co`, **Then** the writing-check skill is listed and invocable.
2. **Given** a later sync of the mirror, **When** the user runs `/plugin marketplace update`, **Then** they receive the new commit without anyone having bumped a version number.

---

### User Story 3 - Use the writing check in Microsoft 365 Copilot (Priority: P2)

A Copilot user at a client downloads one zip from the public repo and uploads it under Agents, Upload skill. Copilot then checks drafts the same way: it runs the scripts if its sandbox allows, and follows the plain-word rules in the skill's instructions if not.

**Why this priority**: One client works mainly in Copilot; this is how Jason teaches there.

**Independent Test**: Build the zip, confirm `SKILL.md` is at the zip root and the frontmatter meets the open standard's limits; then (with Jason's yes) upload it on the Sierra Code Co. test account in the browser and run it on a red and a green sample.

**Acceptance Scenarios**:

1. **Given** the build step has run, **When** the zip is opened, **Then** `SKILL.md` is at its root (no enclosing folder), and name and description meet the standard's limits.
2. **Given** the zip is uploaded on the test tenant, **When** a red sample is pasted with a request to check it, **Then** the result is recorded: whether the packed slop-guard ran, whether the lint script ran, and what the skill did when only instructions applied.
3. **Given** the packed slop-guard cannot run in Copilot's sandbox, **When** the zip is rebuilt, **Then** it leaves the packed file out and the instructions carry the checks.

---

### User Story 4 - One copy of each personal skill, on every machine (Priority: P2)

Jason edits the writing check in one place. On his Mac, `~/.claude/skills/writing-check` is a symlink into this repo, created by the same bootstrap script that links the global CLAUDE.md. The global instructions point at that path.

**Why this priority**: The anti-goal "a second copy that can drift" is otherwise violated on the first edit.

**Independent Test**: Run the bootstrap script twice and confirm the symlink exists, points into the repo, and the second run changes nothing; run the path named in the global instructions and see it work.

**Acceptance Scenarios**:

1. **Given** a machine with no `~/.claude/skills/writing-check`, **When** the bootstrap runs, **Then** it creates a symlink to the repo copy.
2. **Given** a real directory already at that path, **When** the bootstrap runs, **Then** it backs it up and links, and says so.
3. **Given** the global instructions, **When** read, **Then** the prose-check path they name exists and runs.

---

### User Story 5 - Learn how projects are organized for Claude (Priority: P3)

A reader of the public mirror finds a guide that explains how Jason layers CLAUDE.md files, rules, current-state files and memory across a project so that what loads every session stays small, with each claim checked against Claude Code's documentation.

**Why this priority**: Second public item, valuable but independent of the skill.

**Independent Test**: Read the guide from the mirror README link; every numeric claim cites the doc page it came from and the date checked; the denylist finds nothing.

**Acceptance Scenarios**:

1. **Given** the mirror README, **When** a reader follows the library section, **Then** they reach the guide and the install instructions.
2. **Given** the guide, **When** checked against the denylist, **Then** it contains no client name or client file name.

---

### User Story 6 - Hear about a new slop-guard release without anything changing on its own (Priority: P3)

Every Monday the existing update workflow also compares the packed slop-guard version with the latest on PyPI and opens one issue when they differ. Bumping is a deliberate step: run the pull-in script for the new version, run the tests, open a PR.

**Why this priority**: Keeps the packed copy from rotting without auto-updating.

**Independent Test**: Run the comparison logic with the recorded version equal to, behind, and unreadable relative to a stubbed latest version.

**Acceptance Scenarios**:

1. **Given** the recorded version equals PyPI's latest, **Then** no issue is opened.
2. **Given** PyPI has a newer version, **Then** one issue is opened (none if one is already open).
3. **Given** either version cannot be determined, **Then** the job fails visibly rather than reporting "up to date".

### Edge Cases

- An empty document: the lint exits 2 ("nothing to check"), never "clean".
- A document with a trailing line that has no newline: still checked.
- Spaced en dash and spaced double hyphen at line end (editors strip trailing spaces): still caught; an en dash in a date range ("July 31–August 6"), a CSS custom property (`--navy:`) and an HTML comment close (`-->`) are not.
- File names with real extensions in a sentence ("Save it as .docx, .xlsx or .pdf"): not flagged; script and notes file names (.py, .md, .json, .sh, .yml, .yaml, .ipynb) in visible text: flagged.
- slop-guard returning an unexpected exit code or crashing: tool error (exit 2), not "flagged".
- A slop-guard score below the pass mark: flagged (exit 1), with the findings shown.
- The packed file present but run with a Python older than slop-guard needs: tool error with the reason.
- The HTML reducer failing on malformed input: tool error.
- The temporary text file made from HTML: removed on every exit path.

## Requirements *(mandatory)*

### Functional Requirements

**The skill**

- **FR-001**: The writing check MUST be one skill folder in this repo with frontmatter limited to the open standard's fields (name of 1 to 64 lowercase letters, digits and single hyphens matching the folder; description of 1 to 1024 characters; optional license, compatibility, metadata). Its name MUST NOT start with `claude-` or `anthropic-`.
- **FR-002**: The skill MUST contain the phrase list, the lint script, the full-check script and a packed slop-guard 0.5.0 that runs with plain `python3` and nothing installed.
- **FR-003**: `SKILL.md` MUST say what each of the three layers does, MUST state slop-guard's structural rules and the phrase-list categories in plain words so a model with no script access can check itself, and MUST say the check is a style aid for writing plainly, not a detector of AI authorship. It MUST stay under 500 lines and 20,000 characters.
- **FR-004**: The full check MUST prefer the packed slop-guard and fall back to `sg` on PATH, and MUST exit 2 when neither runs.
- **FR-005**: Exit codes MUST be 0 clean, 1 flagged, 2 tool error, for both scripts. Tool errors include: missing, empty, comment-only or invalid phrase list; missing, unreadable or empty document; slop-guard missing or failing; HTML reduction failing. A run that loaded zero rules MUST NOT report clean.
- **FR-006**: The phrase list MUST gain slop-guard's word, phrase, weasel and tone lists, de-duplicated against existing entries, with a credit comment per section. Its comments MUST contain no client names, client file names or client wording.
- **FR-007**: The packed slop-guard MUST carry upstream's files unmodified, its MIT licence and copyright line, the recorded hash of the upstream archive, and any compatibility shim as a separate, declared overlay file.
- **FR-008**: A pull-in script MUST rebuild the packed file from a pinned PyPI version, verify the archive hash, apply the declared overlay, and record the version where the weekly check reads it. It MUST fail loudly on a hash mismatch or a missing pin.

**Copilot**

- **FR-009**: A build step MUST produce one upload zip per library skill with `SKILL.md` at the zip root, deterministic contents, depth at most 3, under 350 files and under 25 MB per file.
- **FR-010**: The committed zip MUST match a fresh build byte for byte, enforced by a test, so it cannot drift from the source.
- **FR-011**: The Copilot result (whether the packed slop-guard and the lint script ran, and the instructions-only behaviour) MUST be recorded in the repo. If the packed file cannot run there, the zip MUST omit it.
- **FR-012**: The upload test MUST happen only after Jason says yes at that moment.

**Claude plugin list**

- **FR-013**: The public mirror MUST carry a plugin list so `/plugin marketplace add Sierra-Code-Co/claude-workflows` then `/plugin install writing-check@sierra-code-co` installs the skill. Version-versus-commit tracking MUST be decided and the reason written down.

**Personal-skill symlink**

- **FR-014**: The bootstrap script MUST link each personal skill in the repo into `~/.claude/skills/`, idempotently, backing up any real directory it replaces.
- **FR-015**: The prose sentence in the global instructions MUST name the new path in the same change that moves the skill. The old `client-doc` copies of the moved files MUST stop being independent copies.

**Weekly check**

- **FR-016**: The weekly workflow MUST compare the recorded slop-guard version with PyPI's latest, open one labelled issue on a difference, never modify the repo, and fail visibly if either version is unknown.

**Docs**

- **FR-017**: A new public guide MUST explain how projects are organized for Claude (the facts listed in the prompt's goal 8), paraphrased, with no client names, and with each number re-checked against the cited documentation before publishing.
- **FR-018**: `public/docs/installing-skills.md` MUST cover plugin marketplaces, the Copilot upload and the personal-skill symlink, and keep the `disable-model-invocation` and propagation sections.
- **FR-019**: The mirror README, `public/docs/architecture.md` (if layers change), `scripts/public-manifest.txt` comments and the template README (separate repo, separate PR, with Jason's yes) MUST be updated.
- **FR-020**: An ADR MUST record that personal skills live here and publish through the mirror, the three-layer slop-guard approach, and the Claude-plus-Copilot scope.

**Tests and publication safety**

- **FR-021**: Tests MUST cover every red, green, tool-error and HTML case listed in the prompt, the slop-guard calibration examples as smoke tests, and the zip's root and frontmatter limits. Each guard's test MUST be seen failing once with the guard broken.
- **FR-022**: Test fixtures MUST use neutral file names (for example `weekly-report-2026-07-30.docx`, `build_sheets.py`), never the engagement's.
- **FR-023**: Before any sync, the staged mirror MUST pass the denylist the way `sync-public.sh` runs it. Running the sync, changing either public repo, opening PRs and the Copilot upload each need Jason's yes at the time.

### Key Entities

- **Library skill**: a folder with `SKILL.md`, scripts and assets, living under the repo's personal-skills directory; the only copy.
- **Phrase list**: one extended regex per line, comments and credits inline; read by the lint script and summarized in `SKILL.md`.
- **Packed slop-guard**: one runnable file built from a pinned upstream archive plus a declared overlay; its version and archive hash are recorded beside it.
- **Copilot zip**: a deterministic build artifact per skill, committed and checked against a fresh build.
- **Plugin list**: the marketplace file in the mirror that names the plugin and points at the skill folder.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All 17 red cases, 12 green cases, 5 tool-error cases and 2 HTML cases from the prompt pass as automated tests, and each guard has been seen failing with the guard broken.
- **SC-002**: On a machine with only the operating system's Python, the full check scores a document with no installs.
- **SC-003**: A Claude Code user gets the skill installed with two commands from the public repo.
- **SC-004**: The Copilot zip uploads on the first attempt and its behaviour is recorded (scripts ran or did not; instructions-only result).
- **SC-005**: The staged public mirror trips zero denylist patterns.
- **SC-006**: Editing the skill in the repo changes what runs at `~/.claude/skills/writing-check` with no copy step.
- **SC-007**: Within a week of a new slop-guard release, exactly one open update issue exists (a new one, or the one already open for an earlier release), and the repository is unchanged.

## Assumptions

- Skill name `writing-check`; plugin name `writing-check`; marketplace name `sierra-code-co`. `client-doc` is a different, later skill.
- Personal skills live at `dotfiles/claude/skills/<name>/`, which is already inside the public manifest's `dotfiles/` entry; nothing personal and private may be placed there.
- The plugin list tracks commits (no `version` field): mirror syncs are manual and deliberate, and a forgotten version bump would silently stop every user's updates, a failure that looks like success.
- Python 3.11 or newer is available wherever the packed slop-guard runs (slop-guard's own floor).
- Copilot personal-upload limits are unconfirmed; the Agent Builder limits are used as the design ceiling.
- The `scan` personal skill is out of scope for this release; it can move under the same mechanism later.
- This spec folder is added to the public manifest, like specs 001 and 003, after it passes the denylist.

## Non-goals

- Codex, Cursor or any tool beyond Claude Code and Microsoft 365 Copilot.
- `client-doc` in this release.
- A project-scaffolding skill.
- Detecting whether text was written by AI.
