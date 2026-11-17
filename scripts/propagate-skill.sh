#!/usr/bin/env bash
# propagate-skill.sh — copy a skill from internal-speckit-template to all active projects.
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
#   1. Reads the canonical skill from internal-speckit-template/.claude/skills/<name>/
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

# Overridable so target discovery can be exercised against a scratch tree rather than
# against every repo on the machine. See the same note in propagate-office-skills.sh.
PROJECTS_DIR="${PROJECTS_DIR:-$HOME/dev/projects}"

# The template repo was renamed `claude-speckit-template` → `internal-speckit-template`
# on 2026-08-24. This script kept the old name and so resolved a directory that does
# not exist: every invocation died on the source-not-found check below, which reads as
# "you asked for a skill that isn't in the template" rather than "the template is
# gone". The name also appeared in the two -not -path exclusions further down, where
# the failure would have been the opposite of loud — `*/claude-speckit-template/*`
# does not match `internal-speckit-template`, so the source of truth would have been
# enumerated as a propagation TARGET and offered up for overwrite by its own content.
#
# Hardcoding the NEW name fixed this machine and broke the documented setup: the
# template's own README still says `git clone ... ~/dev/projects/claude-speckit-template`
# (README.md:36), so a machine built from those instructions has the repo under the old
# directory name and every run here would exit 1 on a template that is present. So the
# directory is RESOLVED rather than assumed, and the exclusion pattern is DERIVED from
# whatever it resolves to. That derivation is the load-bearing half: a legacy fallback
# with a hardcoded `*/internal-speckit-template/*` exclusion would find the template at
# the old path, fail to exclude it, and offer the source of truth up for overwrite —
# reintroducing the quiet half of the original bug in the act of fixing the loud half.
# Current name first. Order is the whole safety property when both exist.
TEMPLATE_CANDIDATES=(internal-speckit-template claude-speckit-template)

if [ -n "${TEMPLATE_DIR:-}" ]; then
  # An explicit override wins, and it is NOT second-guessed with a fallback: someone
  # who names a path wants that path, and silently reviewing a different template is
  # worse than exiting.
  TEMPLATE_ORIGIN="TEMPLATE_DIR from the environment"
  if [ ! -d "$TEMPLATE_DIR" ]; then
    echo "× TEMPLATE_DIR is set to a directory that does not exist: $TEMPLATE_DIR"
    echo "  Unset it to fall back to directory search, or fix the path."
    exit 1
  fi
else
  TEMPLATE_DIR=""
  for candidate in "${TEMPLATE_CANDIDATES[@]}"; do
    if [ -d "$PROJECTS_DIR/$candidate" ]; then
      TEMPLATE_DIR="$PROJECTS_DIR/$candidate"
      TEMPLATE_ORIGIN="found at $candidate"
      break
    fi
  done
  if [ -z "$TEMPLATE_DIR" ]; then
    echo "× Template repo not found. Tried, in order:"
    for candidate in "${TEMPLATE_CANDIDATES[@]}"; do
      echo "    $PROJECTS_DIR/$candidate"
    done
    echo "  This is the source of truth for skill propagation — without it there is"
    echo "  nothing to propagate. Clone it, or set TEMPLATE_DIR if the repo moved again."
    exit 1
  fi
  # Both present means one is stale, and picking the newer one silently is how a run
  # propagates from an abandoned checkout. Say so rather than resolving it quietly.
  if [ -d "$PROJECTS_DIR/claude-speckit-template" ] \
    && [ -d "$PROJECTS_DIR/internal-speckit-template" ]; then
    echo "! Both template directory names exist:"
    echo "    $PROJECTS_DIR/internal-speckit-template  (using this one)"
    echo "    $PROJECTS_DIR/claude-speckit-template    (pre-2026-08-24 name)"
    echo "  One of them is stale. Confirm which holds the skills you mean to propagate."
    echo
  fi
fi

# EVERY candidate template name is excluded, not just the resolved one.
#
# Deriving a single pattern from the resolved directory looked sufficient and was not.
# Measured on 2026-08-29 with both directory names present: the pattern came out as
# `*/internal-speckit-template/*`, the LEGACY checkout was therefore not excluded, and
# the run enumerated `claude-speckit-template/.claude/skills/ship/SKILL.md` as a
# propagation target and offered it up for overwrite by the current template's own
# content. That is verbatim the quiet half of the rename bug, reintroduced by the
# fallback that was added to fix the loud half — a comment three lines up claimed the
# derivation prevented it. The `TEMPLATE_DIR=` override had the mirror-image version:
# pointed at the legacy path, it enumerated the CURRENT template as a target.
#
# A template checkout under any name this script knows about is a source of truth, and
# a source of truth is never a target. So the exclusion set is the candidate list plus
# whatever was resolved, which also covers an override pointing somewhere else entirely.
TEMPLATE_EXCLUDES=("*/$(basename "$TEMPLATE_DIR")/*")
for candidate in "${TEMPLATE_CANDIDATES[@]}"; do
  [ "$candidate" = "$(basename "$TEMPLATE_DIR")" ] && continue
  TEMPLATE_EXCLUDES+=("*/$candidate/*")
done
# Pre-expanded into find arguments. Always at least one element, so `"${...[@]}"` is
# safe under `set -u` on bash 3.2, where expanding an EMPTY array is an error.
TEMPLATE_EXCLUDE_ARGS=()
for pattern in "${TEMPLATE_EXCLUDES[@]}"; do
  TEMPLATE_EXCLUDE_ARGS+=(-not -path "$pattern")
done
# The workflows-repo exclusion is `*claude-workflows/*` rather than
# `*/claude-workflows/*` so it plainly covers this repo (canonical for the global
# CLAUDE.md, and not a propagation target) along with any other prefixed
# `*-claude-workflows` config layer sitting in ~/dev/projects — those belong to
# separate scopes and must not receive skills pushed from here. The old pattern
# excluded them too, but only because `*` matches across `/` and swallowed the
# prefix: a substring accident standing in for a deliberate boundary.
WORKFLOWS_EXCLUDE="*claude-workflows/*"
SOURCE="$TEMPLATE_DIR/.claude/skills/$SKILL_NAME/SKILL.md"

if [ ! -f "$SOURCE" ]; then
  echo "× Source skill not found: $SOURCE"
  echo "  The template exists but has no '$SKILL_NAME' skill. Add it there first —"
  echo "  skills propagate OUT of the template, never into it."
  exit 1
fi

# Name how the template was resolved, not just the path. A run that fell back to the
# pre-rename directory should be visible in the output rather than inferred from it.
echo "Source of truth: $SOURCE"
echo "Template repo:   $TEMPLATE_DIR ($TEMPLATE_ORIGIN)"
[ "$INSTALL_MISSING" = "true" ] && echo "Mode: --install-missing (will also install in projects missing the skill)"
echo

# Find all projects with this skill ALREADY installed.
#
# Read loop rather than `mapfile -t`, because `mapfile` is a bash-4 builtin and this
# machine has only bash 3.2.57 — `/bin/bash` AND `/usr/bin/env bash` both resolve to
# it, so the shebang does not rescue this. Measured on 2026-08-29: with `mapfile`
# here the script died at this line with `mapfile: command not found` and exit
# **127**, having already printed "Source of truth:" — so it looked like it was
# working right up to the point where it enumerated nothing. That failure was
# invisible for as long as it was, because the pre-rename `TEMPLATE_DIR` above exited
# 1 before ever reaching this line; fixing the loud bug is what exposed the quiet
# one. shellcheck does not catch it either — it assumes bash 4+ and passes `mapfile`
# clean (exit 0 on this file while the script was unrunnable), so "shellcheck is
# green" is not evidence a script runs on the shell that will run it.
TARGETS=()
while IFS= read -r found; do
  TARGETS+=("$found")
done < <(find "$PROJECTS_DIR" -path "*/skills/$SKILL_NAME/SKILL.md" \
  "${TEMPLATE_EXCLUDE_ARGS[@]}" \
  -not -path "$WORKFLOWS_EXCLUDE" \
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
  # Same bash-3.2 constraint as the loop above.
  MISSING=()
  while IFS= read -r candidate; do
    MISSING+=("$candidate")
  done < <(find "$PROJECTS_DIR" -mindepth 2 -maxdepth 2 -type d -name ".claude" \
    "${TEMPLATE_EXCLUDE_ARGS[@]}" \
    -not -path "$WORKFLOWS_EXCLUDE" \
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
  # The count guard is load-bearing under `set -u` on bash 3.2: `"${MISSING[@]}"` on
  # an EMPTY array is an `unbound variable` error there, not an empty expansion.
  # Verified on 3.2.57 — `${#MISSING[@]}` is safe and returns 0, `"${MISSING[@]}"` is
  # not. Same reason the `-eq 0` early exit below has to come before the `for` loop.
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
  echo "  - ${t#"$PROJECTS_DIR"/}  $marker"
done
echo

# Per-project diff + copy (or fresh install)
for target in "${TARGETS[@]}"; do
  rel="${target#"$PROJECTS_DIR"/}"
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
