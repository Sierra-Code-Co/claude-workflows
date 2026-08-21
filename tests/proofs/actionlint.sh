#!/usr/bin/env bash
# Failure proof for gate `analyzer.actionlint` (FR-007).
# Seeds a violation, asserts the ANALYZER CLASS reports it, and asserts the
# clean state on both sides. See tests/proofs/analyzer_proof.py for why the
# assertion is on the wrapper's findings rather than the binary's exit code.
set -euo pipefail
unset CDPATH
PROOF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${PROOF_DIR}/analyzer_proof.py" actionlint
