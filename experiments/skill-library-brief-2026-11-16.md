# Brief: a public skill library, starting with a writing check (2026-11-16)

Input for `/speckit-specify` in this repo. Written at the end of a brainstorm with Jason in another session; everything marked **Jason** is his decision, everything marked **call** is a recommendation he accepted in outline ("sounds good") and can still change. No client names belong in this file or anything it produces (ADR-0010 denylist).

## Intent

Sierra Code Co. teaches clients to use Claude, and one client mostly uses Microsoft 365 Copilot. Jason wants a library of reusable skills that he uses every day and can point people to: useful to himself first, public as a marketing and teaching piece. The first skill is a writing check built during real client work on 2026-11-16, after Jason kept finding Claude-style phrasing ("Two blanks only you can fill", "Name them once") in client drafts and speaker notes.

## Decisions already made

- **Jason:** the library lives in this repo (`internal-claude-workflows`) and is published through the existing public mirror `Sierra-Code-Co/claude-workflows` (ADR-0010: allowlist manifest, overlay, denylist gate, scrub at source). No new repo, no fork.
- **Jason:** public, doubling as a marketing piece.
- **Jason:** target Claude Code and Microsoft 365 Copilot only. Codex, Cursor and others wait until a client asks ("so that we're not maintaining more than we have to").
- **Jason:** keep slop-guard rather than drop it where it cannot be installed; mine its source to improve the phrase list and the instructions.
- **Jason:** update the related docs along the way.
- **Jason:** do it as one spec.
- **call:** personal skills move into this repo (proposed path `dotfiles/claude/skills/<name>/`) and `~/.claude/skills/<name>` becomes a symlink to it, the same way `dotfiles/claude/CLAUDE.md` is `~/.claude/CLAUDE.md`. The repo copy is the only copy.
- **call:** project skills (`speckit-*`, `review-plan`, `ship`, office skills) stay in `internal-speckit-template` as today.
- **call:** first release = the writing-check skill, a public guide on how projects are organized for Claude, the doc updates, a weekly update check, and a tested Copilot upload. `client-doc` (house-style PDF pipeline) waits until after mid-December, then its generally useful parts (the checklist; the print-set builder with contents page, section covers and "page N of M") get generalized.
- **call:** no local cron. Add a slop-guard version check to the existing weekly `check-speckit-update.yml` job (Monday 09:00 UTC); it opens an issue on a new release and never updates anything itself.

## What exists today (outside any repo)

`~/.claude/skills/client-doc/` on Jason's Mac, not version-controlled:

- `banned-phrases.txt`: 192 extended regexes, one per line, `#` comments, sections: Claude's framing devices and stage directions, plumbing showing through (file names), published-tool tells, Jason's banned words, Wikipedia "Signs of AI writing" vocabulary 2023 to 2026, puffery, chatbot correspondence.
- `prose-lint.sh FILE [names.txt]`: em dashes, "it's not X, it's Y", "not only ... but", double spaces, every phrase-list entry, banned names. Exit 0 clean, 1 hit, 2 tool error (missing or empty list, bad regex, unreadable file). Reads patterns with `IFS= read -r` so leading and trailing spaces survive; dash patterns are written as a space followed by `–( |$)` because editors strip trailing spaces.
- `prose-check.sh FILE [-t MIN] [names.txt]`: HTML reduced to visible text (comments, CSS, scripts dropped), then prose-lint, then `sg -v -t MIN` (default 80 for prose, 60 for step-by-step handouts). Exit 0 pass, 1 flagged, 2 tool error (sg missing, unreadable file).
- `SKILL.md` (the client-doc checklist) mentions a client three times: scrub before anything syncs.
- Test cases used on 2026-11-16 (scratch only, need to become real tests): red cases ("Two blanks only you can fill.", "Five things you may want to know:", "One more thing you may run into", "Name them once.", "Say it once, plainly.", "That is the lesson:", "Nobody asked it to count.", "That is the difference between a variance and a story.", "Built by build_sheets.py", spaced en dash and double hyphen); green cases ("only your files", "has to be cleared first", "helper key", "Name them in the report header", "July 31–August 6", CSS `--navy:`, HTML comment `-->`, file names only inside an HTML comment); tool-error cases (missing list, list with a bad regex, list of comments only, missing document, sg not on PATH).

Global instructions (`dotfiles/claude/CLAUDE.md`, Prose style) already tell Claude to run `prose-check.sh` before a draft goes to Jason (uncommitted on 2026-11-16, alongside an unrelated uncommitted Cloudflare section that is not part of this work).

## Findings behind the decisions (sources)

- One format works in both targets: a folder with `SKILL.md` per the open standard (agentskills.io/specification). Required frontmatter: `name` (1 to 64 chars, lowercase letters, digits, hyphens, matches the folder) and `description` (1 to 1024 chars); optional `license`, `compatibility`, `metadata`, `allowed-tools`; optional `scripts/`, `references/`, `assets/`. Keep `SKILL.md` under 500 lines (Claude) and under 20,000 characters (Microsoft).
- Claude Code installs from a repo with `.claude-plugin/marketplace.json` (`name`, `owner`, `plugins[]` with `name` and `source`; one repo may list several plugins; anthropics/skills uses `source: "./"`, `strict: false` and a `skills` array per plugin). Users: `/plugin marketplace add Sierra-Code-Co/claude-workflows`. Third-party marketplaces do not auto-update by default; if `version` is set it must be bumped every release. Names starting `claude-` or `anthropic-` are reserved. (code.claude.com/docs/en/plugin-marketplaces, /plugins/manifest-reference, /plugins/host-marketplace)
- Microsoft 365 Copilot Chat: Agents, More agents, Add, Upload skill; a bare `SKILL.md` or a zip with `SKILL.md` at the zip root (no enclosing folder). Scripts (.py, .sh and others) run in a sandbox with no network and no package installs. Rolled out October to mid-November 2026. Seen working on two tenants (2026-11-15 and 11-16): create in chat, Save skill, About card "Free to use", Upload skill dialog. (learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/build-copilot-chat-skills; support.microsoft.com create-edit-skills-copilot.) Unconfirmed: upload size limits for Chat, whether the desktop app runs skill scripts.
- GitHub Copilot reads the same format (`.github/skills`, `.claude/skills`, `~/.copilot/skills`) and Copilot CLI reads `.claude-plugin/marketplace.json`, so nothing extra is needed if a client uses it later.
- slop-guard (github.com/eric-tramel/slop-guard, MIT, PyPI `slop-guard`, author Eric Tramel): 0.5.0 installed 2026-11-16 with `uv tool install slop-guard==0.5.0`. Releases: 0.1.0 2026-02-22, 0.2.0 02-23, 0.3.0 02-26, 0.3.1 03-04, 0.4.0 03-27, 0.4.1 04-01, 0.5.0 07-09. Rule engine and CLI are standard-library Python (re, math, json, dataclasses, importlib.resources); only `apps/mcp.py` needs `mcp`, and `models.py` imports `TypedDict` from `typing_extensions` (one-line change to `typing`). Default rule settings load from `rules/assets/default.jsonl` through `importlib.resources`. 24 rules: word-level slop words, slop phrases, weasel phrases, tone markers, AI disclosure, placeholders, contrast pairs, setup-resolution, pithy fragments, intra-sentence keyword bold, closing aphorism, bullet density and runs, bold bullet lists, colon density, phrase reuse, sentence-length uniformity, extreme sentences.
- First run on real deliverables (2026-11-16): a client email scored 55 for a seven-bullet list and reached 100 as paragraphs; one colon in a 65-word note scored 16 (penalties scale with length); field-label colons and repeated file names lower step-by-step handouts to 70 to 96 without being tells.

## Goals

1. **Writing-check skill** in this repo, to the agentskills.io fields, working in Claude Code with nothing to install: phrase list, `prose-lint.sh`, `prose-check.sh`, and slop-guard 0.5.0 carried inside the skill (MIT licence and a note of the one change) as a single runnable file run with plain `python3`.
2. **Three layers, rules written once:** where scripts run, the phrase list and slop-guard run; where only instructions run, `SKILL.md` states slop-guard's structural rules and the phrase-list categories in plain words so the model checks itself.
3. **Phrase list improved from slop-guard's source:** merge its word and phrase rules, de-duplicated, credited per section.
4. **Copilot:** a build step produces an upload zip per skill with `SKILL.md` at the zip root; tested by uploading on the Sierra Code Co. Copilot account Jason uses for tests, in the browser. Record whether the packed slop-guard runs in Copilot's sandbox; if it does not, the zip leaves it out and relies on the instructions.
5. **Claude plugin list** in the public mirror (through the `public/` overlay or the manifest) so `/plugin marketplace add Sierra-Code-Co/claude-workflows` installs the writing check.
6. **Personal-skill symlink** for this Mac (and the cross-machine sync in `scripts/`, if it handles dotfiles): `~/.claude/skills/<name>` points into this repo.
7. **Weekly update check:** slop-guard added to `check-speckit-update.yml`; opens an issue on a new PyPI release.
8. **Public guide: how projects are organized for Claude.** The layering: a short root `CLAUDE.md` (under 200 lines) that loads the rest; nested `CLAUDE.md` per track or project that loads on first touch; rules files that load by path; a current-state file kept under 150 lines with dated history elsewhere; client material in a gitignored `reference/`; records updated in lockstep after each client interaction; what compaction re-injects (root only) and the 200-line cap on the memory index. Sources to pull from: ADR-0006, this repo's `CLAUDE.md`, `company/docs/business/client-engagement-repo-layout.md` in the company repo (private; paraphrase, no client names), and the verified 2026-10-20 context-scaling notes.
9. **Docs updated:** `public/docs/installing-skills.md` (its "Installation is file-copying, there is no registry step" is out of date), the mirror README, `scripts/public-manifest.txt` comments, the template README (point to the library), and `dotfiles/claude/CLAUDE.md` paths if the skill moves.
10. **Tests** in `tests/` for every case listed above (red, green, tool error), including a test that fails when the phrase list is missing and one that proves the HTML-comment exclusion.

## Non-goals

- Codex, Cursor or other tools.
- `client-doc` in the first release.
- A skill that scaffolds new projects (`client-template` covers it privately).
- Detecting whether text was written by AI. The skill is a style check that helps a person write plainly; it makes no claim about authorship.

## Anti-goals (fails even if it works)

- Any client name, client file name or client wording in the public mirror, the phrase list's comments, examples or tests.
- Anything from Jason's day-job employer's material or internal knowledge (his conflict-of-interest conditions, recorded in the private company repo, rule it out). Public sources and Jason's own work only.
- A second copy of a skill that can drift from the one Jason runs.
- Auto-updating slop-guard or the phrase list without a person reviewing the change.
- A check whose failure looks like success (missing list, bad regex, missing `sg`, empty input must all exit 2).
- Breaking the existing `prose-check.sh` path in the global instructions without updating it in the same change.

## Constraints

- External visibility needs Jason's yes at the moment it happens: running `sync-public.sh` to publish, creating or changing anything in the public repos, and uploading to Copilot.
- Copy only MIT-licensed code (slop-guard), keep its LICENSE and copyright line, and note the modification. Paraphrase the Wikipedia page and other sources; a word list with attribution is fine, copied prose is not.
- Pin slop-guard to an exact version; bumps go through a PR with the tests.
- This repo's own gates apply: `review-plan-v2 --static-only --base main` before push, CodeRabbit on the PR, ADR for the decision (personal skills live here and publish through the mirror).

## Left to the builder

The exact folder layout inside the skill, the single-file packing method (a Python zipapp is the obvious candidate), the plugin and skill names (writing check; avoid reserved prefixes), how the overlay or manifest exposes the plugin list, the test framework (this repo already has `tests/` and `uv`), and the guide's structure.
