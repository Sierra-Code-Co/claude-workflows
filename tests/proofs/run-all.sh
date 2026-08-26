#!/usr/bin/env bash
# Execute every registered failure proof. A gate that cannot be shown to fail is
# not a gate (constitution Principle II), so this runner is what turns that from
# a claim in a document into a check that runs.
#
# Exit 0 only if EVERY proof went red on its seeded violation and green again on
# restore. Deliberately no `continue-on-error` anywhere downstream of this: a
# warn-only proof runner would be the thing it exists to prevent.
#
# A proof is any executable `*.sh` in this directory other than this file. There
# is no registration list to forget to update.

set -euo pipefail

# CDPATH must be cleared before any `cd` in a command substitution: when it is
# set, `cd` echoes the resolved directory to stdout, so `$(cd X && pwd)` returns
# TWO lines and every path built from it is garbage. Caught here because the
# script still exited 1 — the code the test expected — while doing nothing it
# was supposed to do. A correct exit code is not evidence of correct behaviour.
unset CDPATH

PROOF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${PROOF_DIR}/../.." && pwd)"
export REPO_ROOT

shopt -s nullglob
proofs=()
skipped_not_executable=()
for f in "${PROOF_DIR}"/*.sh; do
    [[ "$(basename "$f")" == "run-all.sh" ]] && continue
    # The contract above says "any executable *.sh", and until now this loop
    # never checked the bit — so a half-written helper dropped in here counted
    # as a proof. Found by running this repo's own reviewer against it.
    # -f as well as -x: a directory named `something.sh` carries the executable
    # bit by default, so `-x` alone admits it and then `bash <dir>` fails in a
    # way that reads as a failing proof rather than a malformed one.
    if [[ ! -f "$f" || ! -x "$f" ]]; then
        skipped_not_executable+=("$(basename "$f")")
        continue
    fi
    proofs+=("$f")
done

# A file that looks like a proof and silently is not one is the same defect in
# miniature, so name them rather than dropping them quietly.
if [[ ${#skipped_not_executable[@]} -gt 0 ]]; then
    echo "FAIL: not executable, so not run as proofs: ${skipped_not_executable[*]}"
    echo "      chmod +x them, or move them out of ${PROOF_DIR}."
    exit 1
fi

# An empty proof directory must NOT read as success. "Found nothing" and "never
# ran" are the same output otherwise, which is the exact defect this portfolio
# exists to close. Until the first proof lands, say so and exit non-zero.
if [[ ${#proofs[@]} -eq 0 ]]; then
    echo "FAIL: no failure proofs registered in ${PROOF_DIR}"
    echo "      An empty proof suite is not a passing proof suite."
    echo "      Every gate in gates.yml needs an executable proof here (FR-007)."
    exit 1
fi

# SHAPE COVERAGE RUNS FIRST, AND ITS FAILURE IS FATAL (T037, FR-008a).
#
# The ordering is the whole point. A proof that goes red proves the gate CAN
# fail; it says nothing about whether it fails on every shape the gate claims to
# cover. Crediting a red result before checking coverage is how the
# raw-caught-to-logger fixture sat at eleven shapes — with no near-miss
# distinguishing the caught value from any arrow parameter — while its proof
# passed on every run.
#
# So: derive the shape list from each gate's own structure, confirm the fixture
# exercises it, and only then let a red result mean anything.
echo "deriving shape coverage from each gate"
if ! python3 "${PROOF_DIR}/derive_shapes.py"; then
    echo
    echo "FAIL: shape coverage is incomplete, so no proof below can be credited."
    echo "      A gate whose proof under-covers its own constraints goes red for"
    echo "      the one shape it was written against and stays green for the rest."
    exit 1
fi
echo

passed=0
failed=0
failed_names=()

# Predictable log paths in a shared /tmp let a local attacker pre-create a
# symlink and have this script truncate whatever it points at (CWE-377). CI
# runners share /tmp across steps, so this is not purely theoretical.
LOG_DIR="$(mktemp -d)"

echo "running ${#proofs[@]} failure proof(s)"
echo

unproven=0
unproven_names=()

# A proof may exit 3 to say "I could not exercise this gate at all" — the
# reviewer wave needs a live provider key and cannot be replayed offline.
#
# That is NOT a skip. "Could not run" and "passed" printing the same thing is the
# single failure this suite exists to prevent, so an UNPROVEN result fails the
# run unless the proof is named in RPV2_UNPROVEN_OK. The acknowledgement is
# per-proof by design: a blanket "allow unproven" flag would cover the next gate
# that quietly stops working, which is precisely the wrong thing to make easy.
IFS=',' read -r -a acknowledged <<< "${RPV2_UNPROVEN_OK:-}"

is_acknowledged() {
    local needle="$1" item
    # The count guard is required, not defensive. bash 3.2 treats "${arr[@]}" on a
    # ZERO-element array as an unbound variable under `set -u`, and 3.2.57 is what
    # macOS ships as /bin/bash — which is what `#!/usr/bin/env bash` resolves to on
    # a machine without a Homebrew bash ahead of it on PATH. bash fixed this in 4.4.
    #
    # With RPV2_UNPROVEN_OK unset the read above produces exactly that empty array,
    # so this function aborted the script the first time any proof exited 3. The
    # runner then died at line 110 with "acknowledged[@]: unbound variable" BEFORE
    # printing its verdict, which is how an UNPROVEN gate produced no "not
    # acknowledged" line and no non-zero-for-the-right-reason exit. Two tests in
    # test_proof_runner.py have been red on that since this function was written;
    # they were reading as flakes in a list of pre-existing failures.
    #
    # ${#arr[@]} is safe on an empty array in 3.2; only ${arr[@]} is not.
    (( ${#acknowledged[@]} )) || return 1
    for item in "${acknowledged[@]}"; do
        [[ "${item// /}" == "${needle}" ]] && return 0
    done
    return 1
}

for proof in "${proofs[@]}"; do
    name="$(basename "${proof}" .sh)"
    printf '  %-40s ' "${name}"
    rc=0
    bash "${proof}" >"${LOG_DIR}/${name}.log" 2>&1 || rc=$?
    if [[ ${rc} -eq 0 ]]; then
        echo "ok"
        passed=$((passed + 1))
    elif [[ ${rc} -eq 3 ]] && is_acknowledged "${name}"; then
        echo "UNPROVEN (acknowledged via RPV2_UNPROVEN_OK)"
        unproven=$((unproven + 1))
        unproven_names+=("${name}")
    elif [[ ${rc} -eq 3 ]]; then
        echo "UNPROVEN — not acknowledged (log: ${LOG_DIR}/${name}.log)"
        failed=$((failed + 1))
        failed_names+=("${name}")
    else
        echo "FAILED (log: ${LOG_DIR}/${name}.log)"
        failed=$((failed + 1))
        failed_names+=("${name}")
    fi
done

echo
echo "proofs: ${passed} ok, ${failed} failed, ${unproven} unproven"

# Printed on GREEN runs too. An exemption visible only when something else
# breaks is an exemption nobody reads, and this line is the difference between
# "every gate was proven" and "every gate we ran was proven".
if [[ ${unproven} -gt 0 ]]; then
    echo
    echo "NOT PROVEN this run — these gates were neither shown to fail nor shown"
    echo "to work, and a clean verdict above does not cover them:"
    for n in "${unproven_names[@]}"; do
        echo "  - ${n}"
    done
fi

if [[ ${failed} -gt 0 ]]; then
    echo
    echo "gates that could not be shown to fail:"
    for n in "${failed_names[@]}"; do
        echo "  - ${n}"
    done
    exit 1
fi

exit 0
