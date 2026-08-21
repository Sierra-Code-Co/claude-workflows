"""The enumerator's answer supersedes reviewer speculation (T020, FR-004 acc. 3).

Shapes DERIVED from `supersede_completeness_speculation`'s decision structure
(FR-008a). It gates on four things, so each gets a negative that violates
exactly that one:

  1. coverage is not None          -> no coverage dict at all
  2. coverage["covered"] is True   -> enumerator ran but INCOMPLETE
  3. the message hedges            -> completeness noun, no hedge
  4. the message names completeness-> hedge, no completeness noun
  plus: the source is a reviewer   -> an analyzer finding that happens to match

The most important negative is #2. If the enumerator did not run, the
reviewer's vague warning is the ONLY answer anyone has, and replacing it with
a confident count would be strictly worse than leaving it alone — a
manufactured certainty, which is the failure this whole portfolio is about.
"""
from __future__ import annotations

from review_plan_v2.aggregator import supersede_completeness_speculation
from review_plan_v2.types import Finding

COVERED = {
    "covered": True,
    "finding_count": 30,
    "file_count": 10,
    "rule_ids": ["raw-caught-to-logger"],
}

SPECULATION = "You may have missed other call sites elsewhere in the codebase."


def _f(message: str, sources=("correctness",), severity="actionable") -> Finding:
    return Finding(
        file="web/src/lib/server/decks.ts", line=42, line_end=None,
        severity=severity, category="correctness", message=message,
        sources=list(sources),
    )


# --- the positive ------------------------------------------------------------


def test_speculation_is_demoted_and_carries_the_real_count():
    out = supersede_completeness_speculation([_f(SPECULATION)], COVERED)
    assert out[0].severity == "info"
    assert "30 site(s) across 10 file(s)" in out[0].message
    assert "raw-caught-to-logger" in out[0].message


def test_the_original_reviewer_text_is_retained_not_discarded():
    """Demote and annotate, never drop.

    The detector is prose matching and therefore approximate; a false positive
    must cost the finding its severity, not its existence.
    """
    out = supersede_completeness_speculation([_f(SPECULATION)], COVERED)
    assert SPECULATION in out[0].message


# --- one violated gate each --------------------------------------------------


def test_no_coverage_dict_leaves_the_finding_alone():
    out = supersede_completeness_speculation([_f(SPECULATION)], None)
    assert out[0].severity == "actionable"
    assert out[0].message == SPECULATION


def test_incomplete_coverage_leaves_the_finding_alone():
    """THE critical negative. An enumerator that did not finish has no answer,
    and a hedge beats a fabricated certainty."""
    incomplete = {**COVERED, "covered": False}
    out = supersede_completeness_speculation([_f(SPECULATION)], incomplete)
    assert out[0].severity == "actionable"
    assert "superseded" not in out[0].message


def test_completeness_noun_without_a_hedge_is_not_speculation():
    """"The call site is wrong" is a specific claim about a specific line, not
    a guess about the rest of the repo."""
    msg = "The call site at line 42 passes the raw error object."
    out = supersede_completeness_speculation([_f(msg)], COVERED)
    assert out[0].severity == "actionable"


def test_hedge_without_a_completeness_noun_is_not_speculation():
    """"This may be a race condition" hedges about THIS line. Demoting it would
    silence ordinary uncertainty, which is not what the enumerator answers."""
    msg = "This may be a race condition under concurrent writes."
    out = supersede_completeness_speculation([_f(msg)], COVERED)
    assert out[0].severity == "actionable"


def test_a_deterministic_analyzer_finding_is_never_superseded():
    """Analyzers do not speculate. If one somehow matched the phrasing, its
    finding is still an enumerated fact and must keep its severity."""
    out = supersede_completeness_speculation(
        [_f(SPECULATION, sources=("ast-grep",))], COVERED
    )
    assert out[0].severity == "actionable"


# --- zero is still an answer -------------------------------------------------


def test_zero_sites_found_still_supersedes():
    """"I found none" is a real answer, and the one most worth substituting:
    the reviewer is hedging about sites that provably do not exist."""
    zero = {**COVERED, "finding_count": 0, "file_count": 0}
    out = supersede_completeness_speculation([_f(SPECULATION)], zero)
    assert out[0].severity == "info"
    assert "0 site(s) across 0 file(s)" in out[0].message
