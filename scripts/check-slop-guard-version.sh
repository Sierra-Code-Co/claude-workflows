#!/usr/bin/env bash
# check-slop-guard-version.sh — is the packed slop-guard behind PyPI?
#
#   scripts/check-slop-guard-version.sh [VENDOR.json]
#
# Reads the packed version from the writing-check skill's VENDOR.json and the
# latest release from PyPI (${SLOP_GUARD_PYPI_URL}, overridable for tests; a
# file:// URL works). Prints current=, latest=, needs_update=true|false.
# Never changes anything: bumping is scripts/pull-slop-guard.py plus tests plus
# a PR, done by a person.
#
# Exit 0 compared, 1 when either version could not be determined. "unknown"
# never compares equal to "unknown": a lookup that did not happen is not
# evidence of being up to date.
set -uo pipefail
unset CDPATH

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR="${1:-$REPO_DIR/dotfiles/claude/skills/writing-check/vendor/slop-guard/VENDOR.json}"
URL="${SLOP_GUARD_PYPI_URL:-https://pypi.org/pypi/slop-guard/json}"

current="$(jq -er '.version' "$VENDOR" 2>/dev/null)" || current=""
latest="$(curl -fsSL --max-time 30 "$URL" 2>/dev/null | jq -er '.info.version' 2>/dev/null)" || latest=""

echo "current=${current:-unknown}"
echo "latest=${latest:-unknown}"
if [[ -z "$current" ]]; then
  echo "check-slop-guard-version: could not read the packed version from $VENDOR; nothing was compared" >&2
  exit 1
fi
if [[ -z "$latest" ]]; then
  echo "check-slop-guard-version: could not read the latest version from $URL; nothing was compared" >&2
  exit 1
fi
if [[ "$current" == "$latest" ]]; then echo "needs_update=false"; else echo "needs_update=true"; fi
