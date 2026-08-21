#!/usr/bin/env bash
# Failure proof for US5's reviewer context (T045/T046/T047/T049).
# Breaks one guard at a time and asserts the named test goes red. See
# tests/proofs/context_mutation_proof.py for the four decorative tests this
# found in a suite that was already green.
set -euo pipefail
unset CDPATH
PROOF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${PROOF_DIR}/context_mutation_proof.py"
