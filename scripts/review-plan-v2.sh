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
# (DEEPSEEK_API_KEY, ANTHROPIC_API_KEY, etc.) are picked up automatically
# without requiring them in the shell env. Matches the per-project .env
# convention already used across the fleet.
#
# Security:
# 1. We deliberately do NOT `source` the file (which would execute arbitrary
#    shell). We parse KEY=VALUE lines explicitly. No command substitution,
#    no $variable expansion, no eval.
# 2. Key names are whitelisted to a narrow allowlist of model-API keys +
#    REVIEW_PLAN_V2_* tool config. Prevents an .env that sets PATH /
#    LD_PRELOAD / LD_LIBRARY_PATH / PYTHONPATH from hijacking subsequent
#    python3/git/etc invocations.
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
      DEEPSEEK_API_KEY|DEEPSEEK_API_KEY_FALLBACK|DEEPSEEK_API_BASE) ;;
      ANTHROPIC_API_KEY|ANTHROPIC_API_KEY_FALLBACK|ANTHROPIC_API_BASE) ;;
      OPENAI_API_KEY|OPENAI_API_KEY_FALLBACK|OPENAI_API_BASE) ;;
      GEMINI_API_KEY|GEMINI_API_KEY_FALLBACK|GEMINI_API_BASE) ;;
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
# OPENAI / GEMINI included for symmetry — v2 itself doesn't call them today
# (per FR-003 they're deferred to v2.1) but v1 /review-plan does, and the
# fallback name being available means a wrapper that strips OPENAI_API_KEY
# (similar to the CC wrapper for ANTHROPIC) wouldn't break either tool.
if [[ -z "${OPENAI_API_KEY:-}" && -n "${OPENAI_API_KEY_FALLBACK:-}" ]]; then
  export OPENAI_API_KEY="$OPENAI_API_KEY_FALLBACK"
fi
if [[ -z "${GEMINI_API_KEY:-}" && -n "${GEMINI_API_KEY_FALLBACK:-}" ]]; then
  export GEMINI_API_KEY="$GEMINI_API_KEY_FALLBACK"
fi

# Only prefix a colon if PYTHONPATH is already non-empty (avoid an empty leading entry)
export PYTHONPATH="${SCRIPT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
exec python3 -m review_plan_v2 "$@"
