#!/usr/bin/env bash
# propagate-skill.sh — copy a skill from claude-speckit-template to all active projects.
#
# Usage:
#   ./propagate-skill.sh <skill-name>                  # update existing installs only
#   ./propagate-skill.sh --install-missing <skill-name> # also install in projects missing the skill
#
# Example:
#   ./propagate-skill.sh feature
#   ./propagate-skill.sh --install-missing review-plan-v2
#
# What it does:
#   1. Reads the canonical skill from claude-speckit-template/.claude/skills/<name>/
#   2. Finds all projects in ~/dev/projects/ that have a .claude/skills/<name>/ already
#   3. With --install-missing: also finds projects that have a .claude/ directory
#      (Claude-Code-aware) but no <name>/SKILL.md inside .claude/skills/. The
#      .claude/skills/ subdirectory is created on install if it doesn't exist.
#   4. Shows diff for each existing target, prompts before overwriting
#   5. For missing-install targets, prompts before fresh install (creates parent dir)
#
# IMPORTANT: This is the "easy" propagation that overwrites cleanly. For drift-aware
# updates (e.g., projects that have customized the skill — companion-ai's CLAUDE.md
# reference — you must edit those manually. The script will warn if it detects drift.
#
# Idempotency: re-running with the same args on a project that's now in sync is a no-op
# (reports "already in sync"). re-running with --install-missing on a project that now
# has the file produces the same in-sync report.

set -euo pipefail

INSTALL_MISSING=false

# Parse flags. Skill name is the first positional arg after flags.
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --install-missing) INSTALL_MISSING=true; shift ;;
    -h|--help)
      sed -n '1,/^set -euo/p' "$0" | sed -n '/^# /p' | sed 's/^# //'
      exit 0
      ;;
    --*) echo "× unknown flag: $1" >&2; exit 1 ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
set -- "${ARGS[@]}"

SKILL_NAME="${1:-}"
if [ -z "$SKILL_NAME" ]; then
  echo "Usage: $0 [--install-missing] <skill-name>"
  echo "Example: $0 feature"
  echo "Example: $0 --install-missing review-plan-v2"
  exit 1
fi

PROJECTS_DIR="$HOME/dev/projects"
TEMPLATE_DIR="$PROJECTS_DIR/claude-speckit-template"
SOURCE="$TEMPLATE_DIR/.claude/skills/$SKILL_NAME/SKILL.md"

if [ ! -f "$SOURCE" ]; then
  echo "× Source skill not found: $SOURCE"
  exit 1
fi

echo "Source of truth: $SOURCE"
[ "$INSTALL_MISSING" = "true" ] && echo "Mode: --install-missing (will also install in projects missing the skill)"
echo

# Find all projects with this skill ALREADY installed
mapfile -t TARGETS < <(find "$PROJECTS_DIR" -path "*/skills/$SKILL_NAME/SKILL.md" \
  -not -path "*/claude-speckit-template/*" \
  -not -path "*/claude-workflows/*" \
  -not -path "*/worktrees/*" \
  -not -path "*/node_modules/*" \
  2>/dev/null | sort)

# With --install-missing, also enumerate Claude-Code-aware projects that
# don't yet have the skill. "Claude-Code-aware" = has a .claude/ directory.
# We look at the standard .claude/skills/<skill>/SKILL.md path — projects
# may not have a .claude/skills/ subdir yet (it gets created on install).
# Note: this intentionally does NOT cover companion-ai's .agents/skills/
# parallel install path; that one is project-specific and only relevant for
# update mode (which the find above already handles via -path matching).
#
# -mindepth 2 ensures we match $PROJECTS_DIR/<project>/.claude (depth 2)
# but NOT $PROJECTS_DIR/.claude (depth 1, which is the user's projects-level
# config dir, not a project).
INSTALL_MISSING_SKIP=(
  "LogosBibleSoftwareMCP"
  "_archive"
  "avatar-scratch"
  "story-memory-business"
)
if [ "$INSTALL_MISSING" = "true" ]; then
  mapfile -t MISSING < <(find "$PROJECTS_DIR" -mindepth 2 -maxdepth 2 -type d -name ".claude" \
    -not -path "*/claude-speckit-template/*" \
    -not -path "*/claude-workflows/*" \
    -not -path "*/worktrees/*" \
    -not -path "*/node_modules/*" \
    2>/dev/null | while read -r claude_dir; do
      # Skip projects on the install-missing skip list (dormant, archived, special-case)
      project_name="$(basename "$(dirname "$claude_dir")")"
      skip=false
      for s in "${INSTALL_MISSING_SKIP[@]}"; do
        [ "$project_name" = "$s" ] && skip=true && break
      done
      [ "$skip" = "true" ] && continue
      target="$claude_dir/skills/$SKILL_NAME/SKILL.md"
      [ -f "$target" ] && continue
      printf '%s\n' "$target"
    done | sort)
  if [ ${#MISSING[@]} -gt 0 ]; then
    TARGETS+=("${MISSING[@]}")
  fi
fi

if [ ${#TARGETS[@]} -eq 0 ]; then
  if [ "$INSTALL_MISSING" = "true" ]; then
    echo "No projects found with skill '$SKILL_NAME' and no missing-install candidates."
  else
    echo "No projects found with skill '$SKILL_NAME'. (Try --install-missing to enumerate projects without it.)"
  fi
  exit 0
fi

echo "Found ${#TARGETS[@]} target(s) for skill '$SKILL_NAME':"
for t in "${TARGETS[@]}"; do
  marker="(update)"
  [ -f "$t" ] || marker="(install — missing)"
  echo "  - $(echo "$t" | sed "s|$PROJECTS_DIR/||")  $marker"
done
echo

# Per-project diff + copy (or fresh install)
for target in "${TARGETS[@]}"; do
  rel="$(echo "$target" | sed "s|$PROJECTS_DIR/||")"
  echo "──────────────────────────────────────────────────────────"
  echo "Target: $rel"

  if [ ! -f "$target" ]; then
    # Fresh install (only reached when --install-missing is set)
    echo "  (skill not yet installed — will install fresh from canonical source)"
    parent_dir="$(dirname "$target")"
    read -r -p "  Install skill into $rel? [y/N/q to quit] " ans
    case "$ans" in
      y|Y) mkdir -p "$parent_dir"; cp "$SOURCE" "$target"; echo "  ✓ installed" ;;
      q|Q) echo "Quit."; exit 0 ;;
      *) echo "  skipped" ;;
    esac
    continue
  fi

  if cmp -s "$SOURCE" "$target"; then
    echo "  ✓ already in sync"
    continue
  fi

  echo "  Diff (- target, + source):"
  diff -u "$target" "$SOURCE" | head -40 || true
  echo

  read -r -p "  Overwrite this file? [y/N/q to quit] " ans
  case "$ans" in
    y|Y) cp "$SOURCE" "$target"; echo "  ✓ updated" ;;
    q|Q) echo "Quit."; exit 0 ;;
    *) echo "  skipped" ;;
  esac
done

echo
echo "Done. Remember to commit changes in each project repo."
