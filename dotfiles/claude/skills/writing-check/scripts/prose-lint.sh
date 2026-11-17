#!/usr/bin/env bash
# Mechanical prose checks: the phrase-list layer of the writing check.
#
#   prose-lint.sh FILE [banned-names.txt]
#
# Flags: em dashes, "it's not X, it's Y", "not only ... but", double spaces,
# every extended regex in banned-phrases.txt (the skill folder's copy, or
# $PROSE_LINT_PHRASES), and any line containing a name from banned-names.txt
# (one per line, case-insensitive, fixed strings).
#
# Exit 0 clean, 1 on any hit, 2 on a tool error: unreadable or empty document,
# phrase list missing, empty, comments-only or holding an invalid regex. A run
# that loaded zero rules never reports clean.
set -uo pipefail
unset CDPATH   # an exported CDPATH makes `cd` print its target, corrupting $(cd ... && pwd)

FILE="${1:?usage: prose-lint.sh FILE [banned-names.txt]}"
NAMES="${2:-}"
PHRASES="${PROSE_LINT_PHRASES:-$(cd "$(dirname "$0")/.." && pwd)/banned-phrases.txt}"
HITS=0

[[ -f "$FILE" && -r "$FILE" ]] || { echo "prose-lint: cannot read $FILE" >&2; exit 2; }
grep -q '[^[:space:]]' "$FILE" || { echo "prose-lint: $FILE is empty; nothing was checked" >&2; exit 2; }
[[ -s "$PHRASES" ]] || { echo "prose-lint: phrase list missing or empty: $PHRASES" >&2; exit 2; }
if [[ -n "$NAMES" && ! ( -f "$NAMES" && -r "$NAMES" ) ]]; then echo "prose-lint: names file is not a readable file: $NAMES" >&2; exit 2; fi

report() {  # label, grep args...
  local label="$1"; shift
  local out rc
  out="$(grep -n "$@" "$FILE")"; rc=$?
  if [[ $rc -ge 2 ]]; then echo "prose-lint: grep failed (exit $rc) on check: $label" >&2; exit 2; fi
  if [[ -n "$out" ]]; then
    echo "== $label"; echo "$out"; HITS=$((HITS + 1))
  fi
}

report "em dash" -e "—" -e "&mdash;"
report "it's not X, it's Y" -i -E -e "it(’|')?s not [^.]{1,60}, it(’|')?s"
report "not only ... but" -i -E -e "not only .{1,80} but"
report "double space" -E -e "[a-z,.]  [A-Za-z]"

CHECKED=0
while IFS= read -r rx || [[ -n "$rx" ]]; do   # IFS= keeps the spaces in " –( |$)" and " --( |$)"
  [[ -z "${rx//[[:space:]]/}" || "$rx" == \#* ]] && continue
  report "banned phrase: $rx" -i -E -e "$rx"
  CHECKED=$((CHECKED + 1))
done < "$PHRASES"
[[ $CHECKED -gt 0 ]] || { echo "prose-lint: no phrases read from $PHRASES" >&2; exit 2; }

if [[ -n "$NAMES" ]]; then
  while IFS= read -r name || [[ -n "$name" ]]; do
    [[ -z "${name//[[:space:]]/}" ]] && continue
    report "banned name: $name" -i -F -e "$name"
  # Backstop only for the file vanishing between the -f/-r check above and this
  # read. Not covered by a test; the regular-file check is the tested guard (a
  # directory opens fine here and `read` then fails quietly with status 0).
  done < "$NAMES" || { echo "prose-lint: could not read names file $NAMES" >&2; exit 2; }
fi

if [[ $HITS -eq 0 ]]; then echo "prose-lint: clean ($CHECKED phrases checked)"; exit 0; fi
echo "prose-lint: $HITS check(s) hit ($CHECKED phrases checked)"; exit 1
