# Research: Public skill library, first release

Sources are the 2026-11-16 session prompt (section 4) unless noted. Items marked **verified here** were run in this session.

## R1. Packing slop-guard without editing it

- **Decision**: Build a zipapp from the PyPI wheel. Every wheel member goes in unchanged, including `slop_guard-0.5.0.dist-info/` (so `importlib.metadata.version("slop-guard")` works and the licence and `RECORD` travel with it). Two files are added at the zip root: `typing_extensions.py` (`from typing import TypedDict`) and `__main__.py` (calls `slop_guard.apps.cli:main`). Fixed timestamps make the build byte-reproducible.
- **Rationale**: Constitution Principle VI forbids editing vendored files. `models.py` is the only module importing `typing_extensions`; a shim module satisfies it without touching upstream. `apps/mcp.py` stays in the archive but is never imported (the CLI entry point does not import it).
- **Verified here**: wheel sha256 `f92ff3876dc49131c68c88fb0f37209dd0fb818429e7437fa07f72807e189e7d` matches PyPI's JSON; the prototype (330 KB) ran under `python3 -I` with no packages, scored a setup-resolution sample 0/100, exited 1, and printed `--version` 0.5.0.
- **Alternatives**: editing `models.py` (violates VI); a shiv/pex bundle (needs a build tool); a vendored source tree (47 files, more for Copilot to carry, no benefit).

## R2. Phrase-list merge policy

- **Decision**: Merge slop-guard's slop words, slop phrases, weasel, tone and AI-disclosure literals into `banned-phrases.txt`, de-duplicated, credited per section. Words that are ordinary in plain business prose (e.g. "comprehensive", "ecosystem", "significantly", "in addition", "on the other hand") go on a machine-readable `# read-by-hand:` line instead of becoming hard failures, matching the list's existing "read for them by hand" convention.
- **Rationale**: slop-guard scores these with small, length-scaled penalties; our lint fails on a single hit, so importing every word would flag ordinary sentences. A test asserts each upstream literal is either matched by an entry or named on a read-by-hand line, so a bump that adds words fails until someone classifies them.
- **Alternatives**: import everything (false positives, e.g. the known "a note that…" hit); import nothing (loses the merge the brief asked for).

## R3. Plugin list: version versus commit tracking

- **Decision**: No `version` field; users track commits. Marketplace name `sierra-code-co`, plugin `writing-check`, `source: "./"`, `strict: false`, `skills: ["./dotfiles/claude/skills/writing-check"]`, mirroring anthropics/skills.
- **Rationale**: Mirror syncs are manual and deliberate. With a `version` set, a forgotten bump silently freezes every user, a failure that looks like success. Commit tracking has no such step.
- **Alternatives**: a separate marketplace repo (obra/superpowers style), rejected as a second repo to maintain.

## R4. Where the plugin list lives

- **Decision**: `public/.claude-plugin/marketplace.json` (mirror-only overlay). A test validates it and checks that every skill path it names exists in this repo and is inside a manifest-listed directory.
- **Rationale**: The internal repo is not a marketplace for anyone; Jason uses the symlink.

## R5. Copilot zip

- **Decision**: `scripts/build-copilot-zips.py` writes `dist/copilot/<skill>.zip` with `SKILL.md` at the root, sorted members, fixed timestamps and mode bits. The committed zip is compared to a fresh in-memory build by a test. If the upload test shows the packed file cannot run, the builder takes an `--exclude vendor/` setting recorded in the skill's metadata.
- **Rationale**: Users download one file from GitHub; the byte comparison keeps it from becoming a drifting second copy.

## R6. Weekly check

- **Decision**: `scripts/check-slop-guard-version.sh` reads `VENDOR.json` and PyPI's `.info.version` (URL overridable for tests), prints `needs_update=true|false`, exits 1 when either side is unknown. The workflow calls it, then reuses the existing issue-dedupe pattern with label `slop-guard-update`.

## R7. Personal-skill links

- **Decision**: `new-machine.sh` links every directory under `dotfiles/claude/skills/` to `~/.claude/skills/<name>`, backing up a real directory to `<name>.bak` (as it does for CLAUDE.md). `client-doc`'s old `prose-lint.sh`, `prose-check.sh` and `banned-phrases.txt` become symlinks into the repo copy so its own instructions keep working with one source.

## R8. Python floor

macOS `/usr/bin/python3` is 3.9; slop-guard needs 3.11. `prose-check.sh` checks the interpreter version before running the packed file and exits 2 with the reason. `PROSE_CHECK_PYTHON` overrides the interpreter.

## R9. Copilot upload test record

Filled in by task T040 after Jason's yes. See "Copilot result" below.

### Copilot result

Tested 2026-11-16 on the Sierra Code Co. test tenant (admin account, M365 Copilot Premium), Copilot Chat in Chrome, with `dist/copilot/writing-check.zip` as committed at that point (109,632 bytes).

- **Upload**: Agents, More agents, Add drop-down, Upload skill, pick the zip, Upload. "Uploading skill" for about 18 seconds, then a "Skill added" toast ("Mention writing-check to use it in a prompt"). It was listed under Installed and switched on. First attempt, no errors.
- **Red sample, scripts asked for**: Copilot saved the draft to `/mnt/data/draft.txt` and ran `scripts/prose-check.sh`. `prose-lint.sh` ran: "6 check(s) hit (232 phrases checked)". The packed slop-guard ran as `python3.12 -I slop-guard.pyz`: "2/100 [saturated] (29 words)", with the setup_resolution finding. Exit 1, FLAGGED. The sandbox has bash, grep and Python 3.12, so **both script layers run in Copilot and the zip keeps `vendor/`**.
- **Green sample**: "prose-lint: clean (232 phrases checked)", "100/100 [clean] (21 words)", "prose-check: pass", exit 0.
- **Instructions only** (asked not to run code): Copilot applied the SKILL.md categories by reading and reported six problems as line, rule and rewrite: framing device, payoff line, reveal pair, chatbot correspondence, closing aphorism, short-sentence rhythm. Weakness: its suggested rewrite put back an "X, not Y" contrast. The reading layer finds problems, but rewrites still need the scripts or a person to check them.
- Each answer took under 30 seconds, much faster than the several minutes seen with a skill attached on 2026-11-16.
- The skill is left installed and switched on in the test tenant.

Still unconfirmed: whether the desktop app runs skill scripts, and the size limits for personal uploads.
