# Packaging contract

## public/.claude-plugin/marketplace.json

```json
{
  "name": "sierra-code-co",
  "owner": { "name": "Sierra Code Co." },
  "plugins": [
    {
      "name": "writing-check",
      "source": "./",
      "strict": false,
      "description": "...",
      "skills": ["./dotfiles/claude/skills/writing-check"]
    }
  ]
}
```

Install: `/plugin marketplace add Sierra-Code-Co/claude-workflows` then `/plugin install writing-check@sierra-code-co`. Update: `/plugin marketplace update sierra-code-co` in Claude Code, or `claude plugin update writing-check@sierra-code-co` from a shell.

## `dist/copilot/<skill>.zip`

Members are the skill folder's files, relative to the folder, sorted, timestamp 1980-01-01, mode 0755 for `.sh`, `.py` and `.pyz` files, 0644 for everything else. `SKILL.md` at the root. Built by `scripts/build-copilot-zips.py [--check]`; `--check` exits 1 if a committed zip differs from a fresh build.

## vendor/slop-guard/

`scripts/pull-slop-guard.py --version V --sha256 H` downloads the wheel, verifies H, builds `slop-guard.pyz` (R1), copies the wheel's LICENSE unmodified, writes VENDOR.json. Mismatch or missing arguments: exit 2, nothing written.
