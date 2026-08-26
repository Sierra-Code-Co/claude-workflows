#!/usr/bin/env bash
# Failure proof for US5's reviewer context (T045/T046/T047/T049).
# Breaks one guard at a time and asserts the named test goes red. See
# tests/proofs/context_mutation_proof.py for the four decorative tests this
# found in a suite that was already green.
set -euo pipefail
unset CDPATH
PROOF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${PROOF_DIR}/../.." && pwd)"

# Resolve an interpreter this repo actually supports, rather than whatever
# `python3` happens to be. The proof re-invokes pytest as `sys.executable`, so
# the interpreter chosen here is the one every mutation runs under — and macOS
# ships 3.9.6 as /usr/bin/python3 while pyproject.toml requires >=3.10. On such a
# machine tests/conftest.py raises at collect time, pytest exits 4, and all 25+
# mutations were reported as "the mutation broke the module": a green-to-red
# transition manufactured by the launcher, blamed on the code under test. The
# proof now also refuses a tree it cannot collect (see run()'s baseline check),
# so this is the first of two independent guards on the same failure.
PY=""
for _c in "${REPO_ROOT}/.venv/bin/python" python3.13 python3.12 python3.11 python3.10 python3; do
  _r="$(command -v -- "$_c" 2>/dev/null || true)"
  [[ -n "$_r" ]] || continue
  if "$_r" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$_r"
    break
  fi
done
if [[ -z "$PY" ]]; then
  echo "context_mutations: no Python >= 3.10 found (tried .venv/bin/python," \
       "python3.13, python3.12, python3.11, python3.10, python3). pyproject.toml" \
       "requires >=3.10 and tests/conftest.py refuses to collect below it, so" \
       "every mutation would report 'the mutation broke the module' when the" \
       "real cause is the interpreter. Install one, or create .venv." >&2
  exit 2
fi
exec "$PY" "${PROOF_DIR}/context_mutation_proof.py"
