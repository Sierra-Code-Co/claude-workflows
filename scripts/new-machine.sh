#!/usr/bin/env bash
# new-machine.sh — one-shot bootstrap on a fresh computer.
#
# Run this AFTER cloning the repo to ~/dev/projects/claude-workflows
# and AFTER installing Claude Code itself.
#
# What it does:
#   1. Symlinks dotfiles/claude/CLAUDE.md → ~/.claude/CLAUDE.md
#   2. Copies dotfiles/claude/settings.example.json → ~/.claude/settings.json
#      (only if you don't already have one)
#   3. Symlinks each personal skill dotfiles/claude/skills/<name> →
#      ~/.claude/skills/<name> (ADR-0013). The repo copy is the only copy.
#   4. Prints next-steps for MCP installs (manual — they need credentials)

set -euo pipefail
unset CDPATH   # an exported CDPATH makes `cd` print, which corrupts $(cd ...)

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_DIR="$HOME/.claude"
PROBLEMS=0

mkdir -p "$CLAUDE_DIR"

# --- CLAUDE.md → symlink ---
if [ -L "$CLAUDE_DIR/CLAUDE.md" ]; then
  echo "✓ ~/.claude/CLAUDE.md already symlinked"
elif [ -e "$CLAUDE_DIR/CLAUDE.md" ]; then
  echo "! ~/.claude/CLAUDE.md exists and is not a symlink."
  echo "  Backing up to ~/.claude/CLAUDE.md.bak then symlinking."
  mv "$CLAUDE_DIR/CLAUDE.md" "$CLAUDE_DIR/CLAUDE.md.bak"
  ln -s "$REPO_DIR/dotfiles/claude/CLAUDE.md" "$CLAUDE_DIR/CLAUDE.md"
  echo "✓ symlinked. Old version saved as ~/.claude/CLAUDE.md.bak — diff and delete when satisfied."
else
  ln -s "$REPO_DIR/dotfiles/claude/CLAUDE.md" "$CLAUDE_DIR/CLAUDE.md"
  echo "✓ symlinked ~/.claude/CLAUDE.md → repo"
fi

# --- personal skills → symlinks (same model as CLAUDE.md) ---
mkdir -p "$CLAUDE_DIR/skills"
linked=0
for src in "$REPO_DIR"/dotfiles/claude/skills/*/; do
  [ -f "$src/SKILL.md" ] || continue
  src="${src%/}"; name="$(basename "$src")"; dst="$CLAUDE_DIR/skills/$name"
  if [ -L "$dst" ]; then
    if [ "$(readlink "$dst")" = "$src" ]; then
      echo "✓ ~/.claude/skills/$name already symlinked"
    else
      echo "! ~/.claude/skills/$name is a symlink to $(readlink "$dst"), not this repo. Leaving it; fix by hand." >&2
      PROBLEMS=1
    fi
  elif [ -e "$dst" ]; then
    # Backups go OUTSIDE ~/.claude/skills/: a folder left there keeps its
    # SKILL.md and loads as a second, stale copy of the skill.
    backup="$CLAUDE_DIR/skill-backups/$name.bak"
    if [ -e "$backup" ]; then
      echo "! ~/.claude/skills/$name is a real folder and $backup already exists. Leaving both; merge by hand." >&2
      PROBLEMS=1
      continue
    fi
    mkdir -p "$CLAUDE_DIR/skill-backups"
    mv "$dst" "$backup"
    ln -s "$src" "$dst"
    echo "✓ symlinked ~/.claude/skills/$name → repo. Old folder saved as $backup — diff and delete when satisfied."
  else
    ln -s "$src" "$dst"
    echo "✓ symlinked ~/.claude/skills/$name → repo"
  fi
  linked=$((linked + 1))
done
[ "$linked" -gt 0 ] || { echo "! no personal skills found under dotfiles/claude/skills/" >&2; PROBLEMS=1; }

# --- settings.json → copy from template (don't symlink; per-machine differences expected) ---
if [ -e "$CLAUDE_DIR/settings.json" ]; then
  echo "✓ ~/.claude/settings.json already exists — leaving alone"
else
  cp "$REPO_DIR/dotfiles/claude/settings.example.json" "$CLAUDE_DIR/settings.json"
  echo "✓ created ~/.claude/settings.json from template"
  echo "  → Edit it to fill in your Sentry org slug and other MCP URLs"
fi

# --- Next steps reminder ---
cat <<'NEXT_STEPS'

────────────────────────────────────────────────────────────────────
Next steps (manual — each needs your credentials):

1. GitHub MCP (user scope, covers all projects):
   → Generate PAT at https://github.com/settings/tokens (scopes: repo, read:org, workflow)
   → Run:
     claude mcp add --transport http github https://api.githubcopilot.com/mcp/ \
       -s user --header "Authorization: Bearer <YOUR_PAT>"

2. Sentry MCP (if not already in settings.json):
   → Edit ~/.claude/settings.json and replace <your-sentry-org-slug>
   → On first use, Claude Code will prompt OAuth

3. Verify everything loaded:
   claude mcp list

4. Restart Claude Code (/exit then re-launch) so MCPs register

See decisions/0003-github-mcp-org-scoped.md and 0004-sentry-mcp-strategy.md
for the why behind these choices.
────────────────────────────────────────────────────────────────────
NEXT_STEPS

if [ "$PROBLEMS" -ne 0 ]; then
  echo "! finished with problems above; see the lines starting with !" >&2
  exit 1
fi
