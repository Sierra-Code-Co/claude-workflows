#!/usr/bin/env bash
set -euo pipefail
# Resolve symlinks so a global symlink (e.g., ~/.local/bin/review-plan-v2)
# still finds the review_plan_v2 Python module alongside this script.
SOURCE="${BASH_SOURCE[0]}"
while [[ -L "$SOURCE" ]]; do
  TARGET="$(readlink "$SOURCE")"
  if [[ "$TARGET" = /* ]]; then SOURCE="$TARGET"; else SOURCE="$(dirname "$SOURCE")/$TARGET"; fi
done
SCRIPT_DIR="$(cd "$(dirname "$SOURCE")" && pwd)"

# Load `.env` from the git repo root if present, so per-project model keys
# (GEMINI_API_KEY, OPENAI_API_KEY, etc.) are picked up automatically without
# requiring them in the shell env. Matches the per-project .env convention
# already used across the fleet.
#
# Security:
# 1. We deliberately do NOT `source` the file (which would execute arbitrary
#    shell). We parse KEY=VALUE lines explicitly. No command substitution,
#    no $variable expansion, no eval.
# 2. Key names are whitelisted to a narrow allowlist of model-API keys +
#    REVIEW_PLAN_V2_* tool config. Prevents an .env that sets PATH /
#    LD_PRELOAD / LD_LIBRARY_PATH / PYTHONPATH from hijacking subsequent
#    python3/git/etc invocations.
# 3. `*_API_BASE` is NOT loadable from this file, only from the real
#    environment. The file being parsed is `$GIT_ROOT/.env` — the root of the
#    repository UNDER REVIEW — and a base URL decides where the key and the
#    diff of every changed file are sent. providers/google.py puts the API key
#    in the query string, and its `_validated_base` only checks scheme and
#    netloc, so `GOOGLE_API_BASE=https://attacker.example/` passes validation
#    and exfiltrates both. That is a different exposure from the key names
#    above: a key name can only carry a credential the operator already chose
#    to configure, whereas a base URL redirects a credential the operator
#    configured for somebody else. There is no out-of-repo allowlist bounding
#    a URL the way registry.REVIEW_CAPABLE bounds broad_provider, which is why
#    this one is refused outright rather than reasoned about.
#    An operator who genuinely needs a base override (a proxy, a local mock)
#    exports it in the shell, which is trusted; the reviewed branch is not.
#    Refusals are announced on stderr below rather than dropped silently — a
#    proxy that stopped applying with no output would be diagnosed as a
#    provider outage.
GIT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -n "$GIT_ROOT" && -f "$GIT_ROOT/.env" ]]; then
  while IFS= read -r _line || [[ -n "$_line" ]]; do
    # Strip leading/trailing whitespace
    _line="${_line#"${_line%%[![:space:]]*}"}"
    _line="${_line%"${_line##*[![:space:]]}"}"
    # Skip blank + comment lines
    [[ -z "$_line" || "$_line" == \#* ]] && continue
    # Strip optional leading `export `
    _line="${_line#export }"
    # Must be KEY=VALUE
    [[ "$_line" != *=* ]] && continue
    _key="${_line%%=*}"
    _val="${_line#*=}"
    # Whitelist key names — first by shape (env-var identifier), then by
    # narrow content (only keys we actually use; refuses PATH/LD_PRELOAD/etc.)
    [[ "$_key" =~ ^[A-Z_][A-Z0-9_]*$ ]] || continue
    case "$_key" in
      # Refused from this file, loud about it. See security note 3 above: a base
      # URL from the reviewed branch redirects both the key and every diff, and
      # no out-of-repo allowlist bounds it. Matched BEFORE the key patterns so a
      # future `FOO_API_KEY|FOO_API_BASE)` line cannot re-admit one by accident.
      *_API_BASE)
        echo "review-plan-v2: refusing '$_key' from $GIT_ROOT/.env — a base URL" \
             "from the repository under review would redirect the API key and the" \
             "diff of every changed file. Export it in your shell instead if you" \
             "meant a proxy or a local mock." >&2
        continue ;;
      # deepseek and anthropic are REFUSED as reviewers (data egress and
      # anti-self-grading respectively — see providers/registry.py REFUSED), so
      # neither key enables a reviewer. They stay in the allowlist so an existing
      # .env carrying them still parses cleanly, and so their client modules stay
      # callable for replaying an old calls.jsonl. Setting them buys nothing.
      DEEPSEEK_API_KEY|DEEPSEEK_API_KEY_FALLBACK) ;;
      ANTHROPIC_API_KEY|ANTHROPIC_API_KEY_FALLBACK) ;;
      OPENAI_API_KEY|OPENAI_API_KEY_FALLBACK) ;;
      GEMINI_API_KEY|GEMINI_API_KEY_FALLBACK) ;;
      # providers/google.py reads GEMINI_API_KEY *or* GOOGLE_API_KEY. The
      # allowlist dropped both GOOGLE_* names until 2026-08-25, so a .env setting
      # either one was silently discarded here and the run then reported google as
      # having no key. Now that broad_provider can put the whole broad pass on
      # google, that silent drop refuses the run.
      GOOGLE_API_KEY|GOOGLE_API_KEY_FALLBACK) ;;
      REVIEW_PLAN_V2_*) ;;
      *) continue ;;
    esac
    # Strip matched surrounding quotes
    if [[ "$_val" == \"*\" ]]; then _val="${_val#\"}"; _val="${_val%\"}"; fi
    if [[ "$_val" == \'*\' ]]; then _val="${_val#\'}"; _val="${_val%\'}"; fi
    export "$_key=$_val"
  done < "$GIT_ROOT/.env"
  unset _line _key _val
fi

# Fallback when the primary ANTHROPIC_API_KEY was stripped by an upstream
# wrapper (e.g., the Claude Code subscription-auth wrapper at ~/bin/claude
# that runs `env -u ANTHROPIC_API_KEY claude ...` so CC uses subscription
# billing instead of API). Users can opt into this by adding
#   export ANTHROPIC_API_KEY_FALLBACK="$ANTHROPIC_API_KEY"
# to their shell rc — the wrapper only strips the primary name, so the
# fallback survives, and v2 reconstitutes the primary here.
if [[ -z "${ANTHROPIC_API_KEY:-}" && -n "${ANTHROPIC_API_KEY_FALLBACK:-}" ]]; then
  export ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY_FALLBACK"
fi
# Same shape for DeepSeek, in case any future wrapper strips it too.
if [[ -z "${DEEPSEEK_API_KEY:-}" && -n "${DEEPSEEK_API_KEY_FALLBACK:-}" ]]; then
  export DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY_FALLBACK"
fi
# OPENAI / GEMINI are load-bearing, not symmetry: they are the two cascade legs
# (#25), and either can now be the broad provider via broad_provider. The comment
# here used to say v2 "doesn't call them today (per FR-003 they're deferred to
# v2.1)", which stopped being true when the cascade shipped.
if [[ -z "${OPENAI_API_KEY:-}" && -n "${OPENAI_API_KEY_FALLBACK:-}" ]]; then
  export OPENAI_API_KEY="$OPENAI_API_KEY_FALLBACK"
fi
if [[ -z "${GEMINI_API_KEY:-}" && -n "${GEMINI_API_KEY_FALLBACK:-}" ]]; then
  export GEMINI_API_KEY="$GEMINI_API_KEY_FALLBACK"
fi
if [[ -z "${GOOGLE_API_KEY:-}" && -n "${GOOGLE_API_KEY_FALLBACK:-}" ]]; then
  export GOOGLE_API_KEY="$GOOGLE_API_KEY_FALLBACK"
fi

# Only prefix a colon if PYTHONPATH is already non-empty (avoid an empty leading entry)
export PYTHONPATH="${SCRIPT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

# Resolve an interpreter that meets pyproject's `requires-python = ">=3.10"`,
# rather than exec'ing bare `python3`.
#
# This line read `exec python3 -m review_plan_v2 "$@"` until 2026-08-25. On
# macOS bare `python3` is /usr/bin/python3 = 3.9.6, so every run of this tool on
# this machine has been one minor version below its own declared floor. It did
# not appear broken — the package compiles and imports fine on 3.9 — and that is
# the problem rather than the reassurance: tests/conftest.py refuses to COLLECT
# below 3.10, so 3.9 is the single version the suite has never exercised, and it
# was the version actually running. A 3.10-ism reaches a user before it reaches
# a test, and one already had (concurrency.py's `_TIMEOUT_ERRORS`: below 3.11
# `concurrent.futures.TimeoutError` is not the builtin, which silently disabled
# a deadline branch and read as four concurrency flakes).
#
# Prefer an in-repo venv, then explicit versions newest-first, then bare
# `python3` — which is now a candidate to be VERSION-CHECKED rather than the
# default to fall into. Mirrors tests/proofs/context_mutations.sh, which needed
# the same resolution for the same reason.
RPV2_PY=""
for _cand in "${SCRIPT_DIR}/../.venv/bin/python" python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
  _res="$(command -v -- "$_cand" 2>/dev/null || true)"
  [[ -n "$_res" ]] || continue
  if "$_res" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    RPV2_PY="$_res"
    break
  fi
done
if [[ -z "$RPV2_PY" ]]; then
  # Exit 2 (tool error). Not 0: a run that never happened must not be
  # indistinguishable from a clean review, which is the same fail-open shape
  # `--require-changes` exists to close on the other end of the pipeline.
  echo "review-plan-v2: no Python >= 3.10 on PATH (tried .venv/bin/python," \
       "python3.14, python3.13, python3.12, python3.11, python3.10, python3)." \
       "pyproject.toml declares requires-python = \">=3.10\" and the test suite" \
       "refuses to run below it, so a verdict from an older interpreter would be" \
       "unproven rather than clean. brew install python@3.13, or create a venv." >&2
  exit 2
fi
# A FILE by absolute path, not `-m review_plan_v2`. `-m` puts the current
# working directory at sys.path[0], ahead of the PYTHONPATH entry set above, and
# this script does not cd anywhere — so cwd is normally the root of the
# repository under review. A branch carrying `review_plan_v2/__init__.py` at its
# root would be imported instead of the real package, with every provider key
# already exported into the environment a few lines up. Running a file makes
# sys.path[0] the script's own directory instead. See scripts/rpv2_entry.py.
exec "$RPV2_PY" "${SCRIPT_DIR}/rpv2_entry.py" "$@"
