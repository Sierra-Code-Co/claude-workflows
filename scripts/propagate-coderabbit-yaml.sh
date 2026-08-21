#!/usr/bin/env bash
# propagate-coderabbit-yaml.sh — drop a baseline .coderabbit.yaml into
# active projects that don't have one, plus a rollout-context memory
# file so any active Claude session in those repos has context.
#
# Usage:
#   ./propagate-coderabbit-yaml.sh              # interactive: prompt per repo
#   ./propagate-coderabbit-yaml.sh --apply      # apply to all candidates
#   ./propagate-coderabbit-yaml.sh --dry-run    # list candidates only
#
# What this DOES:
#   - For each candidate repo: copy scripts/templates/coderabbit-baseline.yaml
#     to <repo>/.coderabbit.yaml
#   - For each candidate repo: copy scripts/templates/cr-rollout-memory.md
#     to ~/.claude/projects/<sanitized-cwd>/memory/project_cr_rollout.md
#     (and update that dir's MEMORY.md index)
#
# What this does NOT do:
#   - Create branches, commit, push, or open PRs. That's per-repo work
#     since each project has its own conventions. After running this,
#     cd into each repo, branch, run `coderabbit review --plain --base main`,
#     commit, push, open PR.
#
# Repos already with tailored yamls are skipped (companion-ai, mtg-cube-ai,
# family-app, church-bible-study, claude-workflows itself).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECTS_DIR="$HOME/dev/projects"
TEMPLATE_YAML="$REPO_DIR/scripts/templates/coderabbit-baseline.yaml"
TEMPLATE_MEMORY="$REPO_DIR/scripts/templates/cr-rollout-memory.md"
MODE="${1:-interactive}"

if [ ! -d "$PROJECTS_DIR" ]; then
  echo "× PROJECTS_DIR not found: $PROJECTS_DIR" >&2
  echo "  Expected ~/dev/projects/ to exist with active project subdirs." >&2
  exit 1
fi
if [ ! -f "$TEMPLATE_YAML" ]; then
  echo "× Template not found: $TEMPLATE_YAML" >&2
  exit 1
fi
if [ ! -f "$TEMPLATE_MEMORY" ]; then
  echo "× Template not found: $TEMPLATE_MEMORY" >&2
  exit 1
fi

# Repos already with tailored .coderabbit.yaml — don't overwrite
SKIP=(
  "companion-ai"
  "mtg-cube-ai"
  "family-app"
  "church-bible-study"
  "claude-workflows"
  "claude-speckit-template"
)

# Non-project directories under ~/dev/projects/ to ignore.
#
# History:
#   2026-04-27: original list excluded sierra-code-co and family-meeting
#   2026-05-01: sierra-code-co + family-meeting promoted to active candidates
#               (per feature 002-fleet-cr-rollout)
#   2026-05-01: figment, personal-assistant, personal-finance added — dormant,
#               not in the active-19 enumeration. If they become active again,
#               remove from this list and the next run will pick them up.
NON_PROJECTS=(
  "_archive"
  "avatar-scratch"
  "story-memory-business"
  "LogosBibleSoftwareMCP"
  "figment"
  "personal-assistant"
  "personal-finance"
)

is_in_array() {
  local needle="$1"; shift
  local hay
  for hay in "$@"; do
    [ "$hay" = "$needle" ] && return 0
  done
  return 1
}

declare -a CANDIDATES=()
for dir in "$PROJECTS_DIR"/*/; do
  name="$(basename "$dir")"
  if is_in_array "$name" "${SKIP[@]}"; then continue; fi
  if is_in_array "$name" "${NON_PROJECTS[@]}"; then continue; fi
  # Use git itself to detect repos — handles both .git directories and
  # the .git-as-file form used by git worktrees.
  if ! git -C "$dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then continue; fi
  if [ -f "$dir/.coderabbit.yaml" ]; then continue; fi
  CANDIDATES+=("$name")
done

if [ ${#CANDIDATES[@]} -eq 0 ]; then
  echo "No candidates found — all active repos already have .coderabbit.yaml or are skipped."
  exit 0
fi

echo "Found ${#CANDIDATES[@]} candidate repos for .coderabbit.yaml + rollout memory:"
for c in "${CANDIDATES[@]}"; do
  echo "  - $c"
done
echo

if [ "$MODE" = "--dry-run" ]; then
  echo "Dry run — no files written."
  exit 0
fi

apply_to_repo() {
  local name="$1"
  local dir="$PROJECTS_DIR/$name"

  # Detect repo's default branch from origin/HEAD (NOT current branch —
  # the user might be checked out on a feature branch when running this).
  # Fallback chain: origin/HEAD -> init.defaultBranch -> abort loudly.
  # Per feature 002-fleet-cr-rollout FR-008a — the per-repo .coderabbit.yaml
  # MUST carry the destination's actual default branch under base_branches.
  local default_branch
  default_branch="$(git -C "$dir" symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@' || true)"
  if [ -z "$default_branch" ]; then
    default_branch="$(git -C "$dir" config init.defaultBranch 2>/dev/null || true)"
  fi
  if [ -z "$default_branch" ]; then
    echo "  × failed to detect default branch for $name (no origin/HEAD, no init.defaultBranch)" >&2
    echo "    aborting apply for this repo; other candidates will continue" >&2
    return 1
  fi

  # Copy yaml
  cp "$TEMPLATE_YAML" "$dir/.coderabbit.yaml"
  echo "  ✓ wrote $dir/.coderabbit.yaml"

  # Inject detected default branch into base_branches placeholder (FR-008a).
  # The template ships with exactly one '      - main' line under base_branches
  # as the placeholder; substitute it with the detected value. When the detected
  # value is 'main' the substitution is a no-op (idempotent).
  #
  # Defensively reject branch names that would break the sed substitution. Git
  # technically allows a wide range of characters in refnames; in practice
  # default branches are alphanumerics + '-_/.'. Anything else is suspicious
  # enough to abort rather than silently corrupt the yaml.
  if ! [[ "$default_branch" =~ ^[A-Za-z0-9._/-]+$ ]]; then
    echo "  × default branch '$default_branch' for $name contains characters outside [A-Za-z0-9._/-]; aborting apply" >&2
    rm -f "$dir/.coderabbit.yaml"
    return 1
  fi
  # Portable substitution (avoid `sed -i ''` which is BSD-only and breaks on
  # GNU sed; `sed -i` without arg is GNU-only and breaks on BSD). Write to a
  # temp file then atomically mv back.
  local yaml_tmp
  yaml_tmp="$(mktemp)"
  if ! sed "s|^      - main\$|      - ${default_branch}|" "$dir/.coderabbit.yaml" > "$yaml_tmp"; then
    rm -f "$yaml_tmp" "$dir/.coderabbit.yaml"
    echo "  × sed substitution failed for $name; aborted" >&2
    return 1
  fi
  mv "$yaml_tmp" "$dir/.coderabbit.yaml"
  echo "  ✓ injected base_branches: ${default_branch}"

  # Compute memory dir using Claude Code's path-sanitization convention
  # (strip trailing slash from $dir, then replace each '/' with '-')
  local sanitized="${dir%/}"
  sanitized="${sanitized//\//-}"
  local memory_dir="$HOME/.claude/projects/${sanitized}/memory"
  mkdir -p "$memory_dir"

  # Drop memory file
  cp "$TEMPLATE_MEMORY" "$memory_dir/project_cr_rollout.md"
  echo "  ✓ wrote $memory_dir/project_cr_rollout.md"

  # Update MEMORY.md index (append if entry doesn't exist)
  local memory_index="$memory_dir/MEMORY.md"
  local index_line='- [CR CLI workflow rollout from claude-workflows](project_cr_rollout.md) — coordinated rollout 2026-04-27; PRs/branches named cr-cli-rollout-* are not random'
  if [ -f "$memory_index" ]; then
    if ! grep -q "project_cr_rollout.md" "$memory_index"; then
      # Ensure file ends with newline before appending (defensive against
      # files saved without a trailing newline)
      if [ -s "$memory_index" ] && [ "$(tail -c 1 "$memory_index" | wc -l)" -eq 0 ]; then
        printf '\n' >> "$memory_index"
      fi
      printf '%s\n' "$index_line" >> "$memory_index"
      echo "  ✓ updated $memory_index"
    else
      echo "  · $memory_index already references project_cr_rollout.md"
    fi
  else
    printf '%s\n' "$index_line" > "$memory_index"
    echo "  ✓ created $memory_index"
  fi

  echo "  Next: cd $dir && git checkout -b cr-cli-rollout && coderabbit review --plain --base ${default_branch:-main} && git add .coderabbit.yaml && git commit && git push -u origin cr-cli-rollout"
}

for name in "${CANDIDATES[@]}"; do
  echo "──────────────────────────────────────────────────────────"
  echo "Target: $name"

  # apply_to_repo can return non-zero on per-repo errors (default-branch
  # detection failure or invalid branch name). Run in a subshell so the
  # parent script's `set -e` doesn't abort on a single repo's failure —
  # the subshell preserves errexit semantics inside apply_to_repo (each
  # fallible command still triggers exit), but the parent only sees the
  # final non-zero exit code. The function prints its own error message
  # and cleans up its partial output before returning.
  if [ "$MODE" = "--apply" ]; then
    ( apply_to_repo "$name" ) || true
  else
    read -r -p "  Apply yaml + memory to $name? [y/N/q to quit] " ans
    case "$ans" in
      y|Y) ( apply_to_repo "$name" ) || true ;;
      q|Q) echo "Quit."; exit 0 ;;
      *)   echo "  skipped" ;;
    esac
  fi
done

echo
echo "Done. ${#CANDIDATES[@]} candidates processed."
echo "Each affected repo now has an unstaged .coderabbit.yaml + a rollout-context memory file in its memory dir."
echo "Next step: cd into each repo and open a PR. The 'Next:' line above each repo shows the branch+commit recipe."
