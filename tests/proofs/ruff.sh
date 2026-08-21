#!/usr/bin/env bash
# Failure proof for gate `analyzer.ruff` (FR-007, T005e).
# Seeds an unused import, asserts the ANALYZER CLASS reports it, and asserts the
# clean state on both sides.
set -euo pipefail
unset CDPATH
PROOF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${PROOF_DIR}/analyzer_proof.py" ruff
