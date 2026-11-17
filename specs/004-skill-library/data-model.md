# Data model: files and their invariants

| Entity | Location | Invariants (each has a test) |
| --- | --- | --- |
| Skill | `dotfiles/claude/skills/<name>/` | `SKILL.md` frontmatter keys within {name, description, license, compatibility, metadata, allowed-tools}; name matches folder, 1–64 chars, `^[a-z0-9]+(-[a-z0-9]+)*$`, not `claude-`/`anthropic-`; description 1–1024 chars; under 500 lines and 20,000 chars. |
| Phrase list | `<skill>/banned-phrases.txt` | Every non-comment line compiles as an extended regex; at least one rule; every slop-guard literal matched or on a `# read-by-hand:` line; no denylisted names. |
| Packed slop-guard | `<skill>/vendor/slop-guard/slop-guard.pyz` | sha256 equals `VENDOR.json.pyz_sha256`; every member listed in the wheel's `RECORD` hashes to its recorded value; the only non-`RECORD` members are those named in `VENDOR.json.overlay`. |
| VENDOR.json | beside the pyz | `{package, version, wheel_url, wheel_sha256, pyz_sha256, overlay: [..], python_requires}` |
| Copilot zip | `dist/copilot/<name>.zip` | `SKILL.md` at root; depth ≤ 3; < 350 files; each < 25 MB; equals a fresh build. |
| Plugin list | `public/.claude-plugin/marketplace.json` | Valid JSON; `name` not reserved; each plugin's skills paths exist and sit under a manifest-listed directory; no `version` key (R3). |
| Personal link | `~/.claude/skills/<name>` | Symlink to the repo folder; idempotent; real dir backed up. |
