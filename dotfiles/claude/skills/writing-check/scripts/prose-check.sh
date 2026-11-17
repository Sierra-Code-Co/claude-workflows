#!/usr/bin/env bash
# The full writing check: phrase list, then slop-guard.
#
#   prose-check.sh FILE [-t MIN_SCORE] [banned-names.txt]
#
# 1. prose-lint.sh: em dashes, "it's not X, it's Y", and every entry in
#    banned-phrases.txt (exit 1 on any hit).
# 2. slop-guard (MIT, eric-tramel/slop-guard): structural patterns a phrase
#    list cannot see (setup-then-resolution, "X, not Y" pairs, bullet runs,
#    pithy fragments, colon density, repeated phrases). Fails if the 0-100
#    score is below MIN_SCORE: default 80 for prose and email; pass -t 60 for
#    step-by-step handouts, whose field labels and repeated file names count
#    against them, and read the findings.
#    Uses the packed copy in ../vendor/slop-guard/ (runs with python3 >= 3.11,
#    nothing to install; $PROSE_CHECK_PYTHON picks the interpreter), and falls
#    back to `sg` on PATH.
# HTML is reduced to its visible text first (no CSS, scripts or comments).
#
# Exit 0 both pass, 1 either flags, 2 tool error: unreadable or empty file,
# HTML that cannot be read, no runnable slop-guard, slop-guard crashing.
set -uo pipefail
unset CDPATH   # an exported CDPATH makes `cd` print its target, corrupting $(cd ... && pwd)

FILE="${1:?usage: prose-check.sh FILE [-t MIN_SCORE] [banned-names.txt]}"; shift
MIN=80
if [[ "${1:-}" == "-t" ]]; then MIN="${2:?-t needs a score}"; shift 2; fi
[[ "$MIN" =~ ^[0-9]+$ && "$MIN" -le 100 ]] || { echo "prose-check: -t needs a score from 0 to 100, got $MIN" >&2; exit 2; }
NAMES="${1:-}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PYZ="$HERE/../vendor/slop-guard/slop-guard.pyz"
[[ -f "$FILE" && -r "$FILE" ]] || { echo "prose-check: cannot read $FILE" >&2; exit 2; }

# --- which Python: $PROSE_CHECK_PYTHON, else the newest python3.x >= 3.11 ---
# macOS puts a 3.9 /usr/bin/python3 ahead of Homebrew's, so plain python3 is
# often too old even when a newer one is installed.
new_enough() { "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; }
if [[ -n "${PROSE_CHECK_PYTHON:-}" ]]; then
  CANDIDATES=("$PROSE_CHECK_PYTHON")
else
  CANDIDATES=(python3.14 python3.13 python3.12 python3.11 python3)
fi
PY=""
for c in "${CANDIDATES[@]}"; do
  command -v "$c" >/dev/null 2>&1 && new_enough "$c" && { PY="$c"; break; }
done
if [[ -z "$PY" ]]; then
  first="${CANDIDATES[0]}"
  PYV="$("$first" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "not found")"
  echo "prose-check: no Python 3.11 or newer (tried ${CANDIDATES[*]}; $first is $PYV); set PROSE_CHECK_PYTHON" >&2
fi

# --- which slop-guard: the packed copy, else slop-guard's sg on PATH, else stop
# (`sg` is also ast-grep's old name, so a foreign sg is refused, not run).
SG=()
if [[ -f "$PYZ" && -n "$PY" ]]; then SG=("$PY" -I "$PYZ"); fi
if [[ ${#SG[@]} -eq 0 ]] && command -v sg >/dev/null 2>&1; then
  # Capture first: with pipefail, `sg --help | grep -q` can fail on SIGPIPE
  # when grep exits early, which would make a real slop-guard look foreign.
  SGHELP="$(sg --help 2>&1 || true)"
  if grep -qi 'slop' <<<"$SGHELP"; then SG=(sg); else echo "prose-check: the sg on PATH is not slop-guard; ignoring it" >&2; fi
fi
if [[ ${#SG[@]} -eq 0 ]]; then
  echo "prose-check: no runnable slop-guard: $PYZ needs Python 3.11 or newer, and slop-guard's sg is not on PATH" >&2
  exit 2
fi
[[ -n "$PY" ]] || PY=python3   # the HTML reducer below runs on any Python 3

TXT="$FILE"
TMP=""
trap '[[ -n "$TMP" ]] && rm -f "$TMP"' EXIT
if [[ "$FILE" == *.html || "$FILE" == *.htm ]]; then
  TMP="$(mktemp "${TMPDIR:-/tmp}/prose-check.XXXXXX")"
  TXT="$TMP"
  "${PY}" -I - "$FILE" > "$TXT" <<'EOF' || { echo "prose-check: could not read HTML from $FILE" >&2; exit 2; }
import sys
from html.parser import HTMLParser
BLOCK = {'p','div','li','tr','h1','h2','h3','h4','h5','h6','td','th','br','section','table','ul','ol','blockquote'}
class T(HTMLParser):
    def __init__(s): super().__init__(); s.buf=[]; s.skip=0
    def handle_starttag(s,t,a):
        if t in ('style','script'): s.skip+=1
        if t in BLOCK: s.buf.append('\n')
    def handle_endtag(s,t):
        if t in ('style','script'): s.skip=max(0, s.skip-1)
        if t in BLOCK: s.buf.append('\n')
    def handle_data(s,d):
        if not s.skip: s.buf.append(d)
p=T(); p.feed(open(sys.argv[1], encoding='utf-8').read()); p.close()
print('\n'.join(l.strip() for l in ''.join(p.buf).splitlines() if l.strip()))
EOF
fi
grep -q '[^[:space:]]' "$TXT" || { echo "prose-check: $FILE has no visible text; nothing was checked" >&2; exit 2; }

echo "== prose-lint"
"$HERE/prose-lint.sh" "$TXT" ${NAMES:+"$NAMES"}; LINT=$?
[[ $LINT -eq 0 || $LINT -eq 1 ]] || exit 2

echo "== slop-guard (${SG[*]##*/}, pass mark $MIN)"
SGOUT="$("${SG[@]}" -v -t "$MIN" "$TXT" 2>&1)"; SGRC=$?
echo "$SGOUT"
# A Python traceback also exits 1, the same code as "below the pass mark", so
# exit 1 counts as a verdict only when slop-guard printed its score line.
[[ $SGRC -eq 0 || $SGRC -eq 1 ]] || { echo "prose-check: slop-guard failed (exit $SGRC)" >&2; exit 2; }
grep -qE ': [0-9]+/100 \[' <<<"$SGOUT" || { echo "prose-check: slop-guard printed no score; treating as a tool error" >&2; exit 2; }

if [[ $LINT -eq 0 && $SGRC -eq 0 ]]; then echo "prose-check: pass"; exit 0; fi
echo "prose-check: FLAGGED (prose-lint exit $LINT, slop-guard exit $SGRC)"; exit 1
