#!/usr/bin/env bash
# Failure proof for gate `structural.raw-caught-to-logger` (FR-007).
#
# The fixture tests (tests/unit/test_structural_rules.py) prove the rule matches
# the right SHAPES. This proves the GATE fails the run — that a seeded violation
# actually produces a non-zero exit, and that a clean tree produces zero. Those
# are different claims: every silent-degradation incident in this fleet had a
# check whose logic was fine and whose exit code never moved.
#
# Seeds the multi-line / own-line / trailing-comma shape specifically. That is
# the formatting the original sweep's regexes were blind to, so it is the one
# whose absence would go unnoticed longest.
#
# RED step performed 2026-08-14: emptying rules/raw-caught-to-logger.yml makes
# this proof fail at "seeded violation was NOT detected", which is the point —
# a proof that survives its own gate being deleted is not a proof.

set -euo pipefail
unset CDPATH

PROOF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd -- "${PROOF_DIR}/../.." && pwd)}"
RULE="${REPO_ROOT}/rules/raw-caught-to-logger.yml"

if ! command -v ast-grep >/dev/null 2>&1; then
    # Fail, never skip. A completeness gate whose enumerator is missing reports
    # "no findings", which is indistinguishable from "no violations" —
    # constitution Principle I, and the reason ast-grep is in RECOMMENDED with
    # an explicit degradation path rather than being quietly optional.
    echo "FAIL: ast-grep is not installed, so this gate was not proven at all."
    exit 1
fi

if [[ ! -f "${RULE}" ]]; then
    echo "FAIL: rule not found at ${RULE}"
    exit 1
fi

TMP="$(mktemp -d)"
# Cleanup on EVERY path, not just success. Each `exit 1` below (in `scan`, and
# in all three phases) leaked the directory, so iterating on a FAILING proof
# accumulated one tmpdir per run — the success path was the only one that
# cleaned up. Every failure path `cat`s its diagnostics before exiting, so
# nothing needed for debugging is lost by removing the tree on the way out.
trap 'rm -rf "${TMP}"' EXIT
# The seeded file must sit at a path matching the rule's `files:` globs.
# Scope is part of the policy; a proof at an unscoped path silently proves
# nothing, which is exactly how the previous single-file fixture read as valid.
TARGET_DIR="${TMP}/src/lib/server"
mkdir -p "${TARGET_DIR}"
TARGET="${TARGET_DIR}/seeded.ts"

# ast-grep exits 0 (clean), 1 (findings), or >1 for a TOOL failure — measured:
# 6 for a missing rule file, 8 for a malformed one. Returning the raw status
# collapses that third case into "findings detected", so a scanner that never
# ran reads as a gate doing its job. Phase 1 below happens to catch a
# persistently broken scanner, but only by accident of ordering, and a proof
# that is correct by accident stops being correct when someone reorders it.
#
# Named and fatal instead. This is the same fail-open shape review found in the
# PROPAGATED copy of this proof (mtg-cube-ai#2120), which was a hand-written
# variant rather than this script. The two are now one file, so a fix cannot
# land on only one of them — which is precisely how #2110 happened.
scan() {
    local status=0
    ast-grep scan --rule "${RULE}" "${TMP}" >"${TMP}/out.txt" 2>&1 || status=$?
    if (( status > 1 )); then
        echo "FAIL: ast-grep exited ${status}, so the scan did not run and this"
        echo "      proof establishes NOTHING about the gate. Diagnostics:"
        cat "${TMP}/out.txt"
        exit 1
    fi
    return "${status}"
}

# --- 1. clean tree must be green ---------------------------------------------
cat >"${TARGET}" <<'CLEAN'
export async function handler() {
  try {
    await work();
  } catch (err) {
    console.error(
      '[proof] handler failed:',
      describeThrown(err).errMessage,
    );
  }
}
CLEAN

if ! scan; then
    echo "FAIL: clean tree reported findings; the gate cannot distinguish"
    echo "      remediated code from a violation."
    cat "${TMP}/out.txt"
    exit 1
fi

# --- 2. seeded violation must go red -----------------------------------------
cat >"${TARGET}" <<'DIRTY'
export async function handler() {
  try {
    await work();
  } catch (err) {
    console.error(
      '[proof] handler failed:',
      err,
    );
  }
}
DIRTY

if scan; then
    echo "FAIL: seeded violation was NOT detected — the gate exited 0."
    echo "      This is the state the proof exists to make impossible."
    exit 1
fi

if ! grep -q 'seeded.ts' "${TMP}/out.txt"; then
    echo "FAIL: gate exited non-zero but never named the seeded file."
    echo "      A non-zero exit with no location is not an actionable finding."
    cat "${TMP}/out.txt"
    exit 1
fi

# --- 3. restore must go green again ------------------------------------------
# Without this the proof is satisfied by a gate that fails on everything.
cat >"${TARGET}" <<'CLEAN'
export async function handler() {
  try {
    await work();
  } catch (err) {
    console.error(
      '[proof] handler failed:',
      describeThrown(err).errMessage,
    );
  }
}
CLEAN

if ! scan; then
    echo "FAIL: gate stayed red after the violation was removed."
    cat "${TMP}/out.txt"
    exit 1
fi

echo "ok: raw-caught-to-logger goes red on a seeded violation and green on restore"
