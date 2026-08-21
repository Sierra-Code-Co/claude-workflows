#!/usr/bin/env bash
# propagate-office-skills.sh — install Anthropic's Office skills (docx / pptx / xlsx)
# into existing project repos that already have Claude Code wired up.
#
# Usage:
#   ./propagate-office-skills.sh              # interactive — prompts per project
#   ./propagate-office-skills.sh --dry-run    # show what would happen, change nothing
#   ./propagate-office-skills.sh --yes        # auto-yes all prompts (use with care)
#   ./propagate-office-skills.sh <project>    # target a single project by name
#
# What it does, per target project:
#   1. Copies claude-speckit-template/scripts/install_office_skills.sh into
#      <project>/scripts/ (creates scripts/ if missing).
#   2. Runs the install script in the project — installs docx/pptx/xlsx into
#      <project>/.claude/skills/, verifies deps, installs npm globals.
#   3. Appends .gitignore entries for the skills (non-redistributable) and
#      generated Office artifacts (hand-off only) — idempotent, won't duplicate.
#
# Skip list: projects that are archived, dormant, or have intentional reasons
# not to receive this. Edit SKIP_LIST below to add more.

set -euo pipefail

PROJECTS_DIR="$HOME/dev/projects"
TEMPLATE_DIR="$PROJECTS_DIR/claude-speckit-template"
SOURCE_SCRIPT="$TEMPLATE_DIR/scripts/install_office_skills.sh"

SKIP_LIST=(
  "claude-speckit-template"
  "claude-workflows"
  "_archive"
  "avatar-scratch"
  "LogosBibleSoftwareMCP"
  "story-memory-business"
)

DRY_RUN=false
ASSUME_YES=false
SINGLE_PROJECT=""

# Parse args
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --yes|-y) ASSUME_YES=true; shift ;;
    -h|--help)
      sed -n '1,/^set -euo/p' "$0" | sed -n '/^# /p' | sed 's/^# //'
      exit 0
      ;;
    --*) echo "× unknown flag: $1" >&2; exit 1 ;;
    *)
      if [ -n "$SINGLE_PROJECT" ]; then
        echo "× only one project name argument allowed" >&2
        exit 1
      fi
      SINGLE_PROJECT="$1"; shift ;;
  esac
done

if [ ! -f "$SOURCE_SCRIPT" ]; then
  echo "✗ source install script not found: $SOURCE_SCRIPT" >&2
  echo "  Make sure claude-speckit-template is cloned at $TEMPLATE_DIR" >&2
  echo "  and up to date (git pull)." >&2
  exit 1
fi

# Enumerate target projects: those with a .claude/ directory.
if [ -n "$SINGLE_PROJECT" ]; then
  candidate="$PROJECTS_DIR/$SINGLE_PROJECT"
  if [ ! -d "$candidate/.claude" ]; then
    echo "✗ $SINGLE_PROJECT: no .claude/ directory (not Claude-Code-aware?)" >&2
    exit 1
  fi
  TARGETS=("$candidate")
else
  mapfile -t TARGETS < <(find "$PROJECTS_DIR" -mindepth 2 -maxdepth 2 -type d -name ".claude" \
    -not -path "*/node_modules/*" 2>/dev/null \
    | while read -r claude_dir; do
        project_dir="$(dirname "$claude_dir")"
        project_name="$(basename "$project_dir")"
        skip=false
        for s in "${SKIP_LIST[@]}"; do
          [ "$project_name" = "$s" ] && skip=true && break
        done
        [ "$skip" = "true" ] && continue
        printf '%s\n' "$project_dir"
      done | sort)
fi

if [ ${#TARGETS[@]} -eq 0 ]; then
  echo "No target projects found."
  exit 0
fi

echo "Found ${#TARGETS[@]} target project(s):"
for p in "${TARGETS[@]}"; do
  rel="$(echo "$p" | sed "s|$PROJECTS_DIR/||")"
  status=""
  if [ -d "$p/.claude/skills/docx" ] && [ -d "$p/.claude/skills/pptx" ] && [ -d "$p/.claude/skills/xlsx" ]; then
    status=" (all 3 already installed — will refresh)"
  elif [ -d "$p/.claude/skills/docx" ] || [ -d "$p/.claude/skills/pptx" ] || [ -d "$p/.claude/skills/xlsx" ]; then
    status=" (partial install — will complete)"
  else
    status=" (no Office skills yet)"
  fi
  echo "  - $rel$status"
done
echo

if [ "$DRY_RUN" = "true" ]; then
  echo "Dry run — no changes."
  exit 0
fi

ensure_gitignore_entries() {
  local project="$1"
  local gi="$project/.gitignore"
  touch "$gi"
  if grep -q "Anthropic Office skills" "$gi" 2>/dev/null; then
    return 0
  fi
  cat >> "$gi" <<'EOF'

# Anthropic Office skills — non-redistributable per their LICENSE.txt.
# Re-installed at setup time via scripts/install_office_skills.sh.
.claude/skills/docx/
.claude/skills/pptx/
.claude/skills/xlsx/

# Generated Office artifacts — hand-off only, never commit.
*.docx
*.pptx
*.xlsx
*.pdf
~$*
EOF
  echo "  ✓ appended .gitignore entries"
}

failed=()
succeeded=()
skipped=()

for project in "${TARGETS[@]}"; do
  rel="$(echo "$project" | sed "s|$PROJECTS_DIR/||")"
  echo "──────────────────────────────────────────────────────────"
  echo "Project: $rel"

  if [ "$ASSUME_YES" = "true" ]; then
    ans="y"
  else
    read -r -p "  Install Office skills in $rel? [y/N/q to quit] " ans
  fi

  case "$ans" in
    q|Q) echo "Quit."; break ;;
    y|Y) ;;
    *) echo "  skipped."; skipped+=("$rel"); continue ;;
  esac

  # 1. Copy install script into project's scripts/ (overwrites if older)
  mkdir -p "$project/scripts"
  cp "$SOURCE_SCRIPT" "$project/scripts/install_office_skills.sh"
  chmod +x "$project/scripts/install_office_skills.sh"
  echo "  ✓ copied install_office_skills.sh"

  # 2. Run it from inside the project
  if ( cd "$project" && ./scripts/install_office_skills.sh ); then
    echo "  ✓ install complete"
  else
    echo "  ✗ install failed in $rel" >&2
    failed+=("$rel")
    continue
  fi

  # 3. Ensure .gitignore protects skills + generated artifacts
  ensure_gitignore_entries "$project"

  succeeded+=("$rel")
done

echo
echo "══════════════════════════════════════════════════════════"
echo "Summary:"
echo "  ✓ succeeded: ${#succeeded[@]}"
for p in "${succeeded[@]}"; do echo "    - $p"; done
if [ ${#skipped[@]} -gt 0 ]; then
  echo "  · skipped:   ${#skipped[@]}"
  for p in "${skipped[@]}"; do echo "    - $p"; done
fi
if [ ${#failed[@]} -gt 0 ]; then
  echo "  ✗ failed:    ${#failed[@]}"
  for p in "${failed[@]}"; do echo "    - $p"; done
fi
echo
echo "Reminder: in each successful project, commit the new"
echo "scripts/install_office_skills.sh and updated .gitignore."
echo "Restart Claude Code in each project to pick up the new skills."
