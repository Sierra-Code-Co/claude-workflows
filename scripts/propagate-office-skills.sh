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

# Overridable so the skip/target logic can be exercised against a scratch tree. It was
# hardcoded until 2026-08-29, which meant the only way to test a change to target
# discovery was to run it against the real projects directory — so the SKIP_LIST fix
# below could not be shown to work before being committed. A propagation script whose
# blast radius is every repo on the machine should not be unverifiable.
PROJECTS_DIR="${PROJECTS_DIR:-$HOME/dev/projects}"

# The template repo is `internal-speckit-template` since the 2026-08-24 rename, and
# this script hardcoded the pre-rename `claude-speckit-template` until 2026-08-29 — so
# on a machine carrying the current name it exited 1 on "source install script not
# found" for a template sitting right there. The template's own README still documents
# cloning into the OLD directory name (README.md:36), so neither name can be assumed;
# resolve across both, current name first. Same reasoning and same failure as
# propagate-skill.sh, which is where the longer write-up lives. `TEMPLATE_DIR` from the
# environment overrides and is not second-guessed with a fallback.
TEMPLATE_CANDIDATES=(internal-speckit-template claude-speckit-template)
if [ -n "${TEMPLATE_DIR:-}" ]; then
  if [ ! -d "$TEMPLATE_DIR" ]; then
    echo "✗ TEMPLATE_DIR is set to a directory that does not exist: $TEMPLATE_DIR" >&2
    echo "  Unset it to fall back to directory search, or fix the path." >&2
    exit 1
  fi
else
  TEMPLATE_DIR=""
  for candidate in "${TEMPLATE_CANDIDATES[@]}"; do
    if [ -d "$PROJECTS_DIR/$candidate" ]; then
      TEMPLATE_DIR="$PROJECTS_DIR/$candidate"
      break
    fi
  done
  if [ -z "$TEMPLATE_DIR" ]; then
    echo "✗ template repo not found. Tried, in order:" >&2
    for candidate in "${TEMPLATE_CANDIDATES[@]}"; do
      echo "    $PROJECTS_DIR/$candidate" >&2
    done
    echo "  Clone it, or set TEMPLATE_DIR if the repo moved again." >&2
    exit 1
  fi
fi
SOURCE_SCRIPT="$TEMPLATE_DIR/scripts/install_office_skills.sh"

# BOTH names of both source-of-truth repos. The skip list matches on exact basename, so
# the pre-rename spellings alone meant `internal-speckit-template` and
# `internal-claude-workflows` were enumerated as propagation TARGETS on this machine —
# the template and the global-config repo offered up to receive skills pushed from
# here. That is the quiet counterpart to the loud not-found above: same rename, one
# failure that stops the script and one that silently widens its blast radius.
SKIP_LIST=(
  "internal-speckit-template"
  "claude-speckit-template"
  "internal-claude-workflows"
  "claude-workflows"
  "claude-workflows-public"
  "_archive"
  "avatar-scratch"
  "LogosBibleSoftwareMCP"
  "story-memory-business"
)

# Plus the resolved template's own basename, which the fixed names above cannot cover.
# `TEMPLATE_DIR=$PROJECTS_DIR/my-template` selects a source template whose basename is
# in no list, so target discovery enumerates it and installs the Office skills into the
# repo they are being copied FROM. Same defect propagate-skill.sh had, and the fix there
# derives its exclusions from `basename "$TEMPLATE_DIR"` for exactly this reason. It was
# fixed there by hand and stayed broken here, which is what two scripts sharing a
# resolution rule and not sharing a helper costs. CodeRabbit caught it.
#
# Added only when the override actually lives under PROJECTS_DIR. From anywhere else it
# can never be enumerated as a target, and skipping on a bare basename match would then
# silently drop a real project that happens to share the name — trading a loud
# duplicate-install for a quiet miss.
TEMPLATE_BASENAME="$(basename "$TEMPLATE_DIR")"
case "$TEMPLATE_DIR" in
  "$PROJECTS_DIR"/*)
    already_skipped=0
    for s in "${SKIP_LIST[@]}"; do
      if [ "$s" = "$TEMPLATE_BASENAME" ]; then
        already_skipped=1
        break
      fi
    done
    if [ "$already_skipped" -eq 0 ]; then
      SKIP_LIST+=("$TEMPLATE_BASENAME")
    fi
    ;;
esac

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
  echo "  The template repo resolved to $TEMPLATE_DIR but has no install script there." >&2
  echo "  Make sure it is cloned and up to date (git pull)." >&2
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
  # Read loop, not `mapfile -t`: `mapfile` is a bash-4 builtin and this machine has
  # only bash 3.2.57, which both `/bin/bash` and `/usr/bin/env bash` resolve to. With
  # `mapfile` here the script died on this line with `command not found` and exit 127
  # after printing its header, so it read as working until it enumerated nothing.
  # Note that shellcheck assumes bash 4+ and passes `mapfile` clean, so a green lint
  # was not evidence this ran. Found by sweeping for the same construct after
  # propagate-skill.sh hit it on 2026-08-29. (This comment cannot begin with the word
  # "shellcheck" either — that spelling is parsed as a lint DIRECTIVE and fails the
  # file with SC1072/SC1073. Cost one red lint on 2026-08-29.)
  TARGETS=()
  while IFS= read -r project_dir_found; do
    TARGETS+=("$project_dir_found")
  done < <(find "$PROJECTS_DIR" -mindepth 2 -maxdepth 2 -type d -name ".claude" \
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
  rel="${p#"$PROJECTS_DIR"/}"
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
  rel="${project#"$PROJECTS_DIR"/}"
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
