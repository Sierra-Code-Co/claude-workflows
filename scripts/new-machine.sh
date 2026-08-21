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
#   3. Prints next-steps for MCP installs (manual — they need credentials)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_DIR="$HOME/.claude"

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
