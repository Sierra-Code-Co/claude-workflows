"""SC-002: replay the 2026-08-13 gold set through the verification stage (T032).

Measured as SEPARATE assertions — 3/3 real retained, 3/3 checkable-false refuted
— never as one aggregate rate. An aggregate lets a regression in one class be
paid for by an improvement in another, and the two classes fail in opposite
directions: a verifier that refuses everything scores perfectly on false
findings while destroying the review, and one that confirms everything scores
perfectly on real findings while doing nothing at all.

Both of those degenerate verifiers are exercised below as explicit stubs, so the
suite can demonstrate it would catch them rather than asserting that it would.

Hermetic: runs against the vendored corpus, so it behaves identically on a
laptop, in CI, and in the container. A replay gated on "is the proving ground
checked out at the right SHA?" would skip in CI, and a test that skips is a test
that reports nothing (T005i).
"""
from __future__ import annotations

import json
import pathlib
import shutil

import pytest

from review_plan_v2.verification.classify import CONFIRMED, REFUTED, UNVERIFIABLE, claim_from_dict
from review_plan_v2.verification.verify import Verdict, verify_claim

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
GOLD_SET = json.loads((REPO_ROOT / "tests" / "fixtures" / "gold_set_20260813.json").read_text())
CORPUS = REPO_ROOT / GOLD_SET["corpus_root"]
FINDINGS = GOLD_SET["findings"]


def _by_class(name: str) -> list[dict]:
    return [f for f in FINDINGS if f["classification"] == name]


def _replay(verify_fn=verify_claim) -> dict[str, Verdict]:
    return {
        f["id"]: verify_fn(claim_from_dict(f["claim"]), CORPUS, log=lambda m: None)
        for f in FINDINGS
    }


@pytest.fixture(scope="module")
def verdicts() -> dict[str, Verdict]:
    if shutil.which("ast-grep") is None:
        # FAIL, never skip. A skipped replay reports nothing, and reporting
        # nothing as though it were success is the defect this spec closes.
        pytest.fail("ast-grep is required for the gold-set replay; see .github/workflows/tests.yml")
    return _replay()


# --- SC-002, as two independent measurements ---------------------------------


def test_all_three_checkable_false_findings_are_refuted(verdicts):
    cases = _by_class("checkable_false")
    assert len(cases) == 3, "the corpus lost a checkable-false finding"
    got = {f["id"]: verdicts[f["id"]].verdict for f in cases}
    assert got == {f["id"]: REFUTED for f in cases}, got


def test_all_three_real_findings_are_retained(verdicts):
    cases = _by_class("real")
    assert len(cases) == 3, "the corpus lost a real finding"
    for f in cases:
        v = verdicts[f["id"]]
        assert v.verdict != REFUTED, f"{f['id']} — a REAL finding was refuted: {v.detail}"
        assert f["expected_rendered"] is True


def test_at_least_one_real_finding_is_affirmatively_confirmed(verdicts):
    """The anti-vacuous control for the whole stage.

    "Retained" is satisfied by a verifier that never refutes anything, so
    surviving is not evidence of working. At least one real finding must be
    CONFIRMED by an affirmative observation against the checkout.
    """
    confirmed = [f["id"] for f in _by_class("real") if verdicts[f["id"]].verdict == CONFIRMED]
    assert confirmed, "no real finding was affirmatively confirmed — the verifier may be inert"


def test_the_uncheckable_false_finding_is_unverifiable_not_refuted(verdicts):
    """G3 is FALSE in fact, and we still must not claim to have refuted it.

    Settling it means running the TypeScript compiler, which FR-024 defers until
    a sandboxing model exists. Marking it `refuted` would be asserting a
    verification that never happened — presence-vs-substance in a new costume.
    If a future change flips this to refuted without shipping a sandbox, this
    test is the thing that says so.
    """
    cases = _by_class("false_not_checkable")
    assert len(cases) == 1
    v = verdicts[cases[0]["id"]]
    assert v.verdict == UNVERIFIABLE
    assert "FR-024" in (v.detail or "")


def test_every_finding_matches_its_pre_classified_verdict(verdicts):
    """The full 10, so a change cannot quietly re-classify one to make a
    headline number work."""
    mismatches = {
        f["id"]: (f["expected_verdict"], verdicts[f["id"]].verdict)
        for f in FINDINGS
        if verdicts[f["id"]].verdict != f["expected_verdict"]
    }
    assert not mismatches, mismatches


def test_test_blindness_findings_are_untouched_by_this_stage(verdicts):
    """The ×3 test-blindness class is US5's measure, not US2's.

    The fix for them is FR-010 — mark added test files as tests so the finding
    is never generated — not refutation after the fact. They ride in the corpus
    so a US5 change can be measured against the same 10 findings.
    """
    for f in _by_class("test_blindness"):
        assert verdicts[f["id"]].verdict == UNVERIFIABLE


# --- the replay's own RED steps ----------------------------------------------
#
# T032 specifies a RED step: stub the verifier to confirm everything and
# confirm the refutation assertions fail. Written as permanent tests rather than
# a one-off manual run — a RED step performed once and not encoded is a claim
# about the past, and this repo has already shipped a guard that passed its
# mutation because nobody re-ran it.


def _degenerate(verdict: str):
    def stub(claim, repo_root, **kw):
        return Verdict(verdict, "stub")
    return stub


def test_a_verifier_that_confirms_everything_fails_the_refutation_assertions():
    stubbed = _replay(_degenerate(CONFIRMED))
    with pytest.raises(AssertionError):
        test_all_three_checkable_false_findings_are_refuted(stubbed)


def test_a_verifier_that_refutes_everything_fails_the_retention_assertions():
    """The opposite degenerate case, and the more tempting one: refusing
    everything scores 3/3 on false findings while deleting the review."""
    stubbed = _replay(_degenerate(REFUTED))
    with pytest.raises(AssertionError):
        test_all_three_real_findings_are_retained(stubbed)


def test_a_verifier_that_never_confirms_fails_the_anti_vacuous_control():
    stubbed = _replay(_degenerate(UNVERIFIABLE))
    with pytest.raises(AssertionError):
        test_at_least_one_real_finding_is_affirmatively_confirmed(stubbed)
