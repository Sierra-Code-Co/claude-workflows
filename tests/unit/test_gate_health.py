"""GateHealth clean-run semantics (T006a).

`GateHealth` exists so a caller can tell "found nothing" from "never ran". Those
two states produced identical output in three separate checks in this fleet, and
each time the silent one was read as clean for months.

Shapes DERIVED from the invariant's decision structure, not recalled (FR-008a).
The invariant is a biconditional — `skipped_reason` non-null iff `ran` is false —
so the derivation is the 2x2 of (ran, skipped_reason), plus the third state of a
string field that recall always misses: not None, not a sentence, but EMPTY.
`test_ran_false_with_empty_reason_is_rejected` is that case. `""` is falsy, so a
naive `if not self.skipped_reason` happens to catch it, but a naive
`if self.skipped_reason is None` would not — and the empty string is exactly what
an f-string over a missing variable produces.
"""
from __future__ import annotations

import pytest
from review_plan_v2.gates.registry import Gate, GateHealth, RegistryError

# --- the (ran x skipped_reason) matrix, all four cells -----------------------


def test_ran_true_without_reason_is_valid():
    h = GateHealth(ran=True)
    assert h.skipped_reason is None


def test_ran_true_with_reason_is_rejected():
    """A gate that ran cannot also have been skipped."""
    with pytest.raises(RegistryError, match="skipped_reason"):
        GateHealth(ran=True, skipped_reason="binary not installed")


def test_ran_false_with_reason_is_valid():
    h = GateHealth(ran=False, skipped_reason="ast-grep not installed")
    assert not h.is_clean


def test_ran_false_without_reason_is_rejected():
    """An unexplained skip is indistinguishable from a pass."""
    with pytest.raises(RegistryError, match="MUST state why"):
        GateHealth(ran=False)


# --- the derived third state of the string field ----------------------------


def test_ran_false_with_empty_reason_is_rejected():
    """`""` is a distinct shape from `None`, and the one recall forgets.

    An empty reason renders as a skip with no explanation — the same output as
    no reason at all. It is also what an f-string over an unset variable yields,
    so it is the realistic failure, not a contrived one.
    """
    with pytest.raises(RegistryError, match="MUST state why"):
        GateHealth(ran=False, skipped_reason="")


# --- clean-run semantics ----------------------------------------------------


def test_a_run_that_happened_with_no_dead_legs_is_clean():
    assert GateHealth(ran=True).is_clean


def test_a_skipped_gate_is_not_clean():
    assert not GateHealth(ran=False, skipped_reason="not installed").is_clean


def test_a_dead_leg_makes_the_run_not_clean():
    """SC-010. A provider that answered zero times must force a non-zero exit.

    This is the review-plan-v2 incident encoded: an OpenAI cascade leg went
    136-for-0 across months while every run reported clean, so every clean
    verdict it gave was unfalsifiable.
    """
    h = GateHealth(ran=True, calls_attempted=68, calls_succeeded=0, dead_legs=["openai"])
    assert not h.is_clean


def test_a_gate_that_ran_with_partial_failures_is_still_clean_if_no_leg_died():
    """The near-miss for the dead-leg rule: failures, but no leg at zero.

    Without this control the dead-leg test passes just as well against a rule
    that says "any failed call is unclean", which is a different and wrong rule.
    """
    h = GateHealth(ran=True, calls_attempted=68, calls_succeeded=56, dead_legs=[])
    assert h.is_clean


# --- data-model invariant 4: reportability ----------------------------------


def _gate(**over):
    g = {
        "id": "structural.raw-caught-to-logger",
        "tier": "deterministic",
        "blocking": "blocks",
        "order": 20,
        "cost": "free",
        "failure_proof": "tests/proofs/run-all.sh",
    }
    g.update(over)
    return Gate(**g)


def test_a_gate_without_health_is_not_reportable():
    """Invariant 4. `health` is per-run output, absent at registry-load time.

    The renderer must refuse to emit a result for a gate whose health is unset
    rather than rendering it as clean — which is Principle I applied to the
    reporting stage rather than the execution stage.
    """
    assert not _gate().is_reportable


def test_a_gate_with_health_attached_is_reportable():
    g = _gate()
    g.health = GateHealth(ran=True)
    assert g.is_reportable
