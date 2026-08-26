"""Dead-leg vs starvation reporting (T010a).

Its own file rather than appended to `test_provider_failure_visibility.py`,
which is a unittest.TestCase module ending in `unittest.main()`: module-level
functions are invisible to `unittest`'s collector, so the tests would have been
silently uncollected under any runner but pytest. That is a smaller version of
exactly what T005i was — a test present in the tree and absent from the run.
"""
from __future__ import annotations

from review_plan_v2.orchestrator import all_failed_message
from review_plan_v2.output_format import render_plain


def _summary(**over):
    entry = {"provider": "openai", "calls": 2, "starved": 0,
             "attempted": 2, "succeeded": 0, "failed": 2}
    entry.update(over)
    return {"providers_called": [entry]}


def test_a_fully_starved_leg_is_not_called_a_dead_leg():
    """The 2026-08-14 false alarm, pinned.

    Both the openai and google legs reported "failed all 2 calls — this is a
    configuration failure, not a flaky run. Re-running will not fix it." Both
    were false: their tasks were queued behind 92 starved ones and never reached
    a provider. Re-running the identical branch at concurrency 12 produced zero
    such banners with nothing about either provider changed.
    """
    out = render_plain([], _summary(starved=2, attempted=0, failed=0, succeeded=0))
    assert "[DEAD-LEG]" not in out
    assert "[STARVED]" in out
    assert "queue pressure" in out


def test_a_starved_leg_says_what_to_do_next():
    """The operator's next move differs from a dead leg's — narrow the diff or
    raise concurrency, not go debug a provider. A banner that names the wrong
    remedy costs more than one with no remedy at all."""
    out = render_plain([], _summary(starved=1, attempted=1, failed=0, succeeded=1))
    assert "--max-concurrency" in out or "narrower diff" in out


def test_a_genuinely_dead_leg_still_fires():
    """Anti-vacuous control, and the case that matters most.

    The 136-for-0 OpenAI leg ran undetected for three months. If suppressing
    false alarms also suppressed this, the fix would be worse than the bug.
    """
    out = render_plain([], _summary(starved=0, attempted=2, failed=2, succeeded=0))
    assert "[DEAD-LEG]" in out
    assert "configuration failure" in out


def test_a_leg_that_both_starved_and_failed_everything_it_attempted():
    """Both signals, because both are true and they have different remedies."""
    out = render_plain([], _summary(calls=5, starved=3, attempted=2, failed=2, succeeded=0))
    assert "[STARVED]" in out and "[DEAD-LEG]" in out


def test_a_partially_failing_leg_is_neither():
    out = render_plain([], _summary(calls=4, starved=0, attempted=4, failed=1, succeeded=3))
    assert "[DEAD-LEG]" not in out and "[STARVED]" not in out


def test_an_old_summary_without_attempted_still_reports_a_dead_leg():
    """Backward compatibility that fails SAFE. Defaulting a missing `attempted`
    to 0 would silence the banner on every pre-existing summary — trading a
    false alarm for the silence this whole mechanism exists to end."""
    out = render_plain([], {"providers_called": [
        {"provider": "openai", "calls": 3, "failed": 3, "succeeded": 0}
    ]})
    assert "[DEAD-LEG]" in out


def test_a_malformed_attempted_field_does_not_delete_the_banners():
    """`"attempted": ""` used to raise inside the try, skip the whole entry, and
    silently drop BOTH banners for that provider — a malformed field deleting a
    fail-visible warning, committed inside the warning. Empty now derives."""
    out = render_plain([], {"providers_called": [
        {"provider": "openai", "calls": 3, "starved": 0, "attempted": "", "failed": 3}
    ]})
    assert "[DEAD-LEG]" in out


def test_starvation_is_classified_by_a_dedicated_type_not_by_TimeoutError():
    """`socket.timeout IS TimeoutError` since 3.10, so classifying starvation by
    the builtin would let a provider read-timeout that escaped its handler be
    read as "never ran" — SUPPRESSING a real dead-leg banner. The concurrency
    layer raises its own type instead."""
    from review_plan_v2.concurrency import TaskNeverStarted
    assert issubclass(TaskNeverStarted, TimeoutError)
    assert TaskNeverStarted is not TimeoutError



def test_attempted_zero_is_a_number_not_a_missing_value():
    """`x or None` read a legitimate 0 as absent and derived it back up to
    calls - starved, which can fire DEAD-LEG for a leg that never attempted
    anything. The all-starved case passes either way — derivation happens to
    give the same answer — so it could not have caught this."""
    out = render_plain([], {"providers_called": [
        {"provider": "openai", "calls": 3, "starved": 0, "attempted": 0, "failed": 3}
    ]})
    assert "[DEAD-LEG]" not in out


def test_the_all_failed_error_counts_attempts_not_total_calls():
    """A mixed leg — 5 calls, 3 starved, 2 attempted, 2 failed — must not be
    described as having failed all 5.

    The first version of this test asserted on render_plain's DEAD-LEG banner,
    which was already correct, so it passed against the unfixed code and proved
    nothing about the stderr line it was named for. Caught by its RED step. The
    message now comes from a function, because a string built inline inside a
    print() is a claim nothing can check.
    """
    msg = all_failed_message(
        {"provider": "openai", "calls": 5, "starved": 3, "attempted": 2, "failed": 2}
    )
    assert "ALL 2 call(s)" in msg
    assert "5" not in msg


def test_the_all_failed_message_derives_attempted_when_absent():
    """Legacy summaries carry no `attempted`; deriving keeps the number honest
    rather than falling back to the inflated `calls`."""
    assert "ALL 7 call(s)" in all_failed_message(
        {"provider": "google", "calls": 10, "starved": 3, "failed": 7}
    )

