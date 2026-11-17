# CLI contract

## prose-lint.sh FILE [banned-names.txt]

- Phrase list: `$PROSE_LINT_PHRASES`, else `../banned-phrases.txt` relative to the script.
- Checks: em dash (raw and `&mdash;`), "it's not X, it's Y", "not only … but", double space, every phrase-list regex (case-insensitive), every name in the optional names file (fixed string, case-insensitive).
- Output: `== <label>` then `line:text` per hit; final line `prose-lint: clean (N phrases checked)` or `prose-lint: K check(s) hit`.
- Exit: 0 clean · 1 any hit · 2 tool error (unreadable or empty document, missing/empty/comment-only list, invalid regex).

## prose-check.sh FILE [-t MIN] [banned-names.txt]

- HTML (`.html`, `.htm`) is reduced to visible text; comments, `<style>`, `<script>` dropped. The temp file is removed on every exit.
- Runs prose-lint, then slop-guard as `-v -t MIN` (default 80; 60 for step-by-step handouts).
- slop-guard resolution: `vendor/slop-guard/slop-guard.pyz` under `$PROSE_CHECK_PYTHON` (default `python3`, must be ≥ 3.11); else `sg` on PATH; else exit 2.
- Exit: 0 both pass · 1 either flags · 2 tool error (unreadable/empty file, HTML failure, no runnable slop-guard, slop-guard exit other than 0/1, lint exit 2).

## check-slop-guard-version.sh [VENDOR.json]

- Latest from `${SLOP_GUARD_PYPI_URL:-https://pypi.org/pypi/slop-guard/json}` `.info.version`.
- Prints `current=X`, `latest=Y`, `needs_update=true|false`; exit 0. Exit 1 if either is unknown.
