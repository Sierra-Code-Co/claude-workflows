#!/usr/bin/env bash
# Failure proof for the verification stage (T033, FR-002 / FR-003).
#
# The unit tests prove `verify_claim` returns the right verdicts. This proves the
# STAGE changes what a developer sees — that a refuted finding actually leaves
# the output, that the drop is COUNTED rather than silent, and that an
# unverifiable one is rendered with its marker rather than dropped or promoted.
# Those are different claims. Every silent-degradation incident in this fleet had
# a component whose logic was fine and whose output never moved.
#
# RED step performed 2026-08-14: making `drop_refuted` return `(list(findings),
# [])` — i.e. keeping everything — fails this proof at "refuted finding is still
# in the output". Making it drop without the summary count fails at
# "[VERIFIED-OUT] receipt missing".

set -euo pipefail
unset CDPATH

PROOF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd -- "${PROOF_DIR}/../.." && pwd)}"

if ! command -v ast-grep >/dev/null 2>&1; then
    # Fail, never skip. A verification stage whose reader is missing marks every
    # claim `unchecked`, and a proof that skips cannot tell you that happened.
    echo "FAIL: ast-grep is not installed, so the stage was not proven at all."
    exit 1
fi

cd "${REPO_ROOT}"

PYTHONPATH="${REPO_ROOT}/scripts" python3 - <<'PY'
import pathlib
import sys

from review_plan_v2.aggregator import aggregate
from review_plan_v2.output_format import render_plain
from review_plan_v2.types import Finding

corpus = pathlib.Path("tests/fixtures/gold_set_corpus").resolve()
failures = []


def finding(msg, claim, line=18, file="web/src/lib/server/describe-thrown.ts"):
    return Finding(file=file, line=line, line_end=None, severity="actionable",
                   category="correctness", message=msg, sources=["correctness"],
                   claim=claim)


FALSE_CLAIM = {
    "kind": "return_shape", "subject": "describeThrown", "expected": "name, message",
    "check": {"method": "typecheck",
              "input": "web/src/lib/server/describe-thrown.ts::describeThrown"},
}
TRUE_CLAIM = {
    "kind": "symbol_exists", "subject": "stripBlockComments", "expected": "runs before the parser",
    "check": {"method": "enumerate", "input": "src:stripBlockComments"},
}
DEFERRED_CLAIM = {
    "kind": "predicate_result", "subject": "ts.isCallExpression", "expected": "false",
    "check": {"method": "execute", "input": "ts.isCallExpression"},
}

def batch():
    """Fresh objects each call.

    aggregate() mutates the findings it is given — dedup merges in place and
    verification writes verdicts onto them. Reusing one list for both the
    verified run and the control below made the control see verdicts written by
    the run it was supposed to be independent of, and it reported a failure that
    was an artifact of the harness. Caught by this proof on first execution.

    The judgment finding sits on line 19, one line from the false-claim finding
    on line 18 — inside the dedup window, ON PURPOSE. That collision is what
    exposed the merge defect this proof now guards against.
    """
    return [
        finding("errMessage may be undefined since describeThrown returns {name, message}",
                FALSE_CLAIM),
        finding("regex comment-stripping runs before the parser", TRUE_CLAIM,
                line=20, file="web/src/lib/server/console-guard.ts"),
        finding("isCallExpression misses optional-chain calls", DEFERRED_CLAIM,
                line=26, file="web/src/lib/server/console-guard.ts"),
        finding("this replaces the error object and loses the stack trace", None, line=19),
    ]


refuted = []
kept = aggregate([batch()], repo_root=corpus, refuted_out=refuted,
                 verify_log=lambda m: None)
out = render_plain(kept, {"refuted_dropped": len(refuted)})

# 1. The refuted finding LEAVES the output.
if "may be undefined" in out:
    failures.append("refuted finding is still in the output (FR-002)")
if len(refuted) != 1:
    failures.append(f"expected exactly 1 refutation, got {len(refuted)}")

# 2. The drop is counted. A silent removal is indistinguishable from a prompt
#    change that produced fewer findings, which is how a regression hides.
if "[VERIFIED-OUT]" not in out:
    failures.append("[VERIFIED-OUT] receipt missing — the drop was silent (FR-003)")

# 3. Unverifiable is RENDERED, with its marker. Not dropped, not promoted.
if "optional-chain" not in out:
    failures.append("unverifiable finding was dropped; FR-003 says label it, not lose it")
if "[UNVERIFIED:" not in out:
    failures.append("unverifiable finding rendered without its marker (FR-003)")

# 4. A judgment finding (claim: null) survives untouched. Penalising these would
#    drop exactly what a reviewer is uniquely good at.
if "stack trace" not in out:
    failures.append("a claim:null judgment finding was dropped")

# 5. A confirmed finding is shown WITH its evidence.
if "[verified:" not in out:
    failures.append("confirmed finding rendered without its observation")

# 6. Anti-vacuous control: with the stage off, the refuted finding comes back.
#    Without this, "drop everything" would score a perfect result here.
off = render_plain(aggregate([batch()]), {})
if "may be undefined" not in off:
    failures.append("--no-verify path also dropped the finding; the stage is not what removed it")
if "[VERIFIED-OUT]" in off or "[UNVERIFIED:" in off:
    failures.append("verification markers appear on a run where the stage did not execute")

for f in failures:
    print(f"FAIL: {f}")
sys.exit(1 if failures else 0)
PY

echo "ok: refuted dropped + counted, unverifiable labelled, judgment kept, confirmed evidenced"
exit 0
