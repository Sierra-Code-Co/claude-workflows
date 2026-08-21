#!/usr/bin/env bash
# sync-public.sh — regenerate the public mirror (Sierra-Code-Co/claude-workflows)
# from this repo. One-way: internal → public. See ADR-0010.
#
# What it does:
#   1. Stages allowlisted paths (scripts/public-manifest.txt) into a temp tree
#   2. Overlays public/ (README.md, docs/, LICENSE) at the staged root
#   3. Gates the staged tree: denylist grep (scripts/public-denylist.txt),
#      then gitleaks. Any hit aborts BEFORE the mirror is touched. Fail closed.
#   4. rsync --delete into the mirror clone and commits "sync: internal@<sha>"
#
# Usage:
#   ./scripts/sync-public.sh                 # dry run: stage + gates + diffstat
#   ./scripts/sync-public.sh --apply         # also rsync + commit in the mirror
#   ./scripts/sync-public.sh --apply --push  # and push the mirror's main
#   ./scripts/sync-public.sh --init          # first run: git-init the mirror dir
#
# The mirror clone defaults to ~/dev/projects/claude-workflows-public
# (override: PUBLIC_MIRROR_DIR). The mirror tree is rebuilt from the manifest
# every run, so a file not listed there cannot leak by drift — removing a path
# from the manifest removes it from the mirror on the next --apply.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${PUBLIC_MIRROR_DIR:-$HOME/dev/projects/claude-workflows-public}"
MANIFEST="$REPO_DIR/scripts/public-manifest.txt"
DENYLIST="$REPO_DIR/scripts/public-denylist.txt"
PUBLIC_REMOTE="git@github.com:Sierra-Code-Co/claude-workflows.git"

APPLY=0 PUSH=0 INIT=0
for a in "$@"; do
  case "$a" in
    --apply) APPLY=1 ;;
    --push)  PUSH=1 ;;
    --init)  INIT=1 ;;
    -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
    *) echo "unknown arg: $a" >&2; exit 2 ;;
  esac
done

for f in "$MANIFEST" "$DENYLIST"; do
  [ -f "$f" ] || { echo "missing: $f" >&2; exit 2; }
done
command -v rsync >/dev/null || { echo "rsync required" >&2; exit 2; }
command -v gitleaks >/dev/null || { echo "gitleaks required (brew install gitleaks) — refusing to sync unscanned" >&2; exit 2; }

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# --- 1. stage allowlisted paths ---------------------------------------------
missing=0
while IFS= read -r line; do
  entry="${line%%#*}"; entry="$(echo "$entry" | xargs)"   # strip comments/space
  [ -n "$entry" ] || continue
  if [ ! -e "$REPO_DIR/$entry" ]; then
    echo "manifest path missing in repo: $entry" >&2; missing=1; continue
  fi
  # public-denylist.txt is excluded unconditionally: it enumerates the client
  # names it exists to protect, so publishing it would defeat its purpose (and
  # it would self-trip the grep gate below).
  (cd "$REPO_DIR" && rsync -aR --exclude '.DS_Store' --exclude 'public-denylist.txt' "$entry" "$STAGE/")
done < "$MANIFEST"
[ $missing -eq 0 ] || { echo "aborting: manifest references paths that don't exist" >&2; exit 2; }

# --- 2. overlay public-only files (README, docs, LICENSE) -------------------
[ -d "$REPO_DIR/public" ] || { echo "missing public/ overlay dir" >&2; exit 2; }
rsync -a --exclude '.DS_Store' "$REPO_DIR/public/" "$STAGE/"

# --- 3a. gate: denylist -----------------------------------------------------
hits=0
while IFS= read -r line; do
  pat="${line%%#*}"
  case "$pat" in
    ci:*) if out=$(grep -rInE -i -- "${pat#ci:}" "$STAGE" 2>/dev/null); then
            echo "DENYLIST HIT (${pat}):"; echo "$out" | sed "s|$STAGE/|  |" | head -5; hits=1
          fi ;;
    cs:*) if out=$(grep -rInE -- "${pat#cs:}" "$STAGE" 2>/dev/null); then
            echo "DENYLIST HIT (${pat}):"; echo "$out" | sed "s|$STAGE/|  |" | head -5; hits=1
          fi ;;
    *) : ;;  # comment / blank
  esac
done < "$DENYLIST"
if [ $hits -ne 0 ]; then
  echo "aborting: scrub the file at source (or drop it from the manifest) and re-run" >&2
  exit 2
fi
echo "denylist gate: clean"

# --- 3b. gate: gitleaks on the staged tree ----------------------------------
if gitleaks dir --help >/dev/null 2>&1; then
  gitleaks dir "$STAGE" --no-banner --redact
else
  gitleaks detect --no-git -s "$STAGE" --no-banner --redact
fi
echo "gitleaks gate: clean"

# --- 4. sync into the mirror clone ------------------------------------------
if [ ! -d "$DEST/.git" ]; then
  if [ $INIT -eq 1 ]; then
    mkdir -p "$DEST"
    git -C "$DEST" init -b main
    git -C "$DEST" remote add origin "$PUBLIC_REMOTE"
    echo "initialized mirror at $DEST (remote: $PUBLIC_REMOTE)"
  else
    echo "mirror clone missing at $DEST" >&2
    echo "  git clone $PUBLIC_REMOTE $DEST   (or re-run with --init)" >&2
    exit 2
  fi
fi

SRC_SHA="$(git -C "$REPO_DIR" rev-parse --short HEAD)"
if [ $APPLY -eq 0 ]; then
  echo ">>> DRY RUN — staged tree passed both gates. Changes vs mirror:"
  rsync -rcn --delete --exclude '.git' --out-format='  %o %n' "$STAGE/" "$DEST/" | head -60
  echo "re-run with --apply to commit (source: internal@${SRC_SHA})"
  exit 0
fi

rsync -rc --delete --exclude '.git' "$STAGE/" "$DEST/"
git -C "$DEST" add -A
if git -C "$DEST" diff --cached --quiet; then
  echo "mirror already up to date with internal@${SRC_SHA}"
else
  git -C "$DEST" commit -m "sync: internal@${SRC_SHA}"
  echo "committed sync: internal@${SRC_SHA}"
fi

if [ $PUSH -eq 1 ]; then
  git -C "$DEST" push -u origin main
  echo "pushed mirror to origin/main"
fi
