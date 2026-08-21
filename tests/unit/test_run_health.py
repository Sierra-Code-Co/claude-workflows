"""SC-010: a dead provider leg is named AND the run does not report success (T061).

Asserting what #27 fixed rather than assuming it still holds. The incident: the
openai cascade leg made 136 calls and succeeded 0 times, across three months, and
every run reported "review came back clean" — the leg contributed nothing and
nothing said so.

Two halves, and BOTH are needed. A banner nobody's script reads does not stop
`review-plan-v2 && git push`; a non-zero exit with no explanation sends the
operator to read source. Neither alone is the fix, so neither alone is the test.

The anti-vacuous direction gets equal weight, because it is the reason the
2026-08-14 version of this banner had to be rewritten: it fired on two legs that
were merely STARVED (queued behind 92 tasks that never started) and told the
operator their configuration was broken. A fail-visible mechanism that cries
wolf gets ignored, and then the real 136-for-0 leg goes unnoticed again.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from review_plan_v2 import output_format
from review_plan_v2.orchestrator import all_failed_message
from review_plan_v2.types import Finding


def _leg(provider="openai", calls=8, failed=8, starved=0, attempted=None):
    return {
        "provider": provider, "calls": calls, "failed": failed,
        "starved": starved,
        "attempted": calls - starved if attempted is None else attempted,
    }


def _render(*legs, **summary):
    summary.setdefault("providers_called", list(legs))
    return output_format.render_plain([], summary)


# --- named ------------------------------------------------------------------


def test_a_dead_leg_is_named_in_the_report():
    out = _render(_leg())
    assert "[DEAD-LEG]" in out
    assert "openai" in out, "the banner must name WHICH leg; 'a leg failed' is unactionable"


def test_the_dead_leg_message_states_the_consequence():
    """"failed all 8 calls" is a fact. "contributed NOTHING to this review, so
    treat any clean verdict on its paths as unproven" is the fact the reader
    needs — it is what makes them re-run rather than ship."""
    msg = all_failed_message(_leg())
    assert "openai" in msg
    assert "NOTHING" in msg
    assert "unproven" in msg


def test_a_healthy_leg_produces_no_banner():
    """Anti-vacuous. A banner on every run is a banner nobody reads, which costs
    exactly the signal the banner exists to carry."""
    out = _render(_leg(failed=0))
    assert "[DEAD-LEG]" not in out


def test_a_partially_failing_leg_is_not_dead():
    """7 of 8 failing is a bad run, not a dead leg. Conflating them is how the
    banner stops meaning 'this leg answered nothing'."""
    assert "[DEAD-LEG]" not in _render(_leg(failed=7))


# --- STARVED is not DEAD (the 2026-08-14 false alarm) ------------------------


def test_a_fully_starved_leg_is_reported_as_starved_not_dead():
    """Measured on a real run: two legs reported "configuration failure, not a
    flaky run. Re-running will not fix it." Both were FALSE — every task had
    been queued behind 92 that never started, and a narrower diff fixed it.

    The operator's next move differs (narrow the diff vs fix the config), so
    the two must not print the same banner.
    """
    out = _render(_leg(calls=8, failed=0, starved=8, attempted=0))
    assert "[STARVED]" in out
    assert "[DEAD-LEG]" not in out, "queue pressure was reported as a broken provider"


def test_a_leg_that_is_both_starved_and_dead_still_reports_dead():
    """Starvation must not become a way to suppress a genuine dead leg —
    suppressing false alarms at the cost of the real 136-for-0 signal would be
    worse than the original bug."""
    out = _render(_leg(calls=10, failed=4, starved=6, attempted=4))
    assert "[DEAD-LEG]" in out


def test_a_missing_attempted_field_is_derived_not_defaulted_to_zero():
    """Backward compatibility must fail SAFE. A summary written by an older
    version lacks `attempted`; defaulting it to 0 would make `attempted > 0`
    false and silence the banner on exactly the runs most likely to be broken."""
    legacy = {"provider": "openai", "calls": 8, "failed": 8, "starved": 0}
    assert "[DEAD-LEG]" in _render(legacy)


# --- and the run does not report success -------------------------------------


def test_failed_tasks_make_the_run_exit_non_zero():
    """The other half. A named banner that leaves exit 0 still lets
    `review-plan-v2 && git push` push on the strength of a review that did not
    happen — the 2026-08-01 incident, where 34 of 48 tasks were cancelled and
    the run printed "No findings." and exited 0."""
    assert output_format.exit_code_for([], failed_task_count=8) == 2


def test_a_clean_complete_run_still_exits_zero():
    """Anti-vacuous: if incomplete coverage were inferred from anything less
    than an actual failure count, every clean run would report as broken."""
    assert output_format.exit_code_for([], failed_task_count=0) == 0


def test_actionable_findings_outrank_incomplete_coverage():
    """A real problem was found; surfacing it as a review failure (1) is more
    useful than reclassifying it as a tooling problem (2). The [INCOMPLETE]
    banner renders either way, so the operator sees both facts."""
    f = Finding(file="a.py", line=1, line_end=None, severity="actionable",
                category="correctness", message="x", sources=["gitleaks"])
    assert output_format.exit_code_for([f], failed_task_count=8) == 1
