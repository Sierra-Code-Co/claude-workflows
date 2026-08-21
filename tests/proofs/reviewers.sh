#!/usr/bin/env bash
# Failure proof for gate `reviewer.wave` (FR-007) — the reasoning_effort=none
# regression guard. Needs a live provider; exits 3 (UNPROVEN) without a key.
# See tests/proofs/reviewer_proof.py for why it cannot be replayed offline.
set -euo pipefail
unset CDPATH
PROOF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${PROOF_DIR}/reviewer_proof.py"
