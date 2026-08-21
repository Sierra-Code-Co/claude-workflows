#!/usr/bin/env bash
# sync-pull.sh — capture local ~/.claude/* state INTO the repo.
#
# Use this when you've edited ~/.claude/CLAUDE.md (or another tracked file)
# directly via Claude Code's `/memory` command or your editor, and want to
# commit the change.
#
# If files are already symlinked (the normal case after new-machine.sh),
# they're already in sync — this script just shows you the diff.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_DIR="$HOME/.claude"

# CLAUDE.md
if [ -L "$CLAUDE_DIR/CLAUDE.md" ]; then
  echo "✓ ~/.claude/CLAUDE.md is symlinked — edits are already live in repo"
elif [ -e "$CLAUDE_DIR/CLAUDE.md" ]; then
  echo "! ~/.claude/CLAUDE.md is a real file (not symlinked). Copying into repo."
  if ! cmp -s "$CLAUDE_DIR/CLAUDE.md" "$REPO_DIR/dotfiles/claude/CLAUDE.md"; then
    diff -u "$REPO_DIR/dotfiles/claude/CLAUDE.md" "$CLAUDE_DIR/CLAUDE.md" || true
    echo
    read -r -p "Apply this change to the repo? [y/N] " ans
    if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
      cp "$CLAUDE_DIR/CLAUDE.md" "$REPO_DIR/dotfiles/claude/CLAUDE.md"
      echo "✓ updated. Now commit:"
      echo "  cd $REPO_DIR && git add dotfiles/claude/CLAUDE.md && git commit"
    else
      echo "skipped."
    fi
  else
    echo "✓ no diff"
  fi
else
  echo "× ~/.claude/CLAUDE.md not found. Run scripts/new-machine.sh first."
fi

# settings.json — never auto-pulled (may contain machine-specific values)
echo
echo "ℹ settings.json is intentionally NOT auto-synced (per-machine config)."
echo "  If you've added an MCP server you want in the example template, edit"
echo "  dotfiles/claude/settings.example.json by hand and commit."
