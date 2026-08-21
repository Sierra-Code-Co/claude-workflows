"""The reviewer-phase wall-clock budget must not discard work it already paid for.

`run_with_cap(deadline_sec=...)` recorded EVERY future still outstanding when
the deadline tripped as a TimeoutError -- and then sat in
`ThreadPoolExecutor.__exit__`, which calls `shutdown(wait=True)`, waiting for
those very tasks to finish. Their return values arrived and were thrown away.

Two consequences, both bad for a gate:
  * `failed_task_count` counted completed reviews as failures, so a run that
    reviewed a chunk successfully still printed
    '[INCOMPLETE] ... its verdict is unproven' and exited 2.
  * The findings from those reviews were dropped, so the gate was blind to
    real defects it had already been told about and paid for.

Measured before the fix: 4 x 10s tasks, concurrency 2, deadline 3.0s ->
elapsed 10.0s (the full run) with all four TaskResults carrying TimeoutError,
including the two that had returned values.

What is NOT claimed here: that the deadline bounds wall-clock time. Python
cannot kill a running thread, and `Future.cancel()` is a no-op once a task has
started, so an in-flight task always runs to completion. The deadline bounds
QUEUED work (never-started futures are genuinely cancelled); per-task time is
what bounds in-flight work, and that is enforced in the provider layer.
"""
from __future__ import annotations

import threading
import time
import unittest

# Direct execution needs `scripts` on the path; pytest supplies it via
# pyproject's `pythonpath` and nothing supplies it outside pytest. Without
# this the `__main__` guard below is a promise the file cannot keep —
# T005i-b found seven such modules here, none able to run standalone.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from review_plan_v2.concurrency import run_with_cap  # noqa: E402


def _sleeper(seconds: float, value: str):
    def f():
        time.sleep(seconds)
        return value
    return f


class DeadlineKeepsCompletedWorkTests(unittest.TestCase):
    def test_in_flight_tasks_that_finish_during_drain_are_harvested(self):
        """Every task is running at the deadline and every one finishes.

        The executor waits for all three regardless, so their results cost the
        run nothing extra. Recording them as TimeoutError is pure loss: the
        findings are dropped AND the run is declared incomplete.
        """
        tasks = [(f"t{i}", _sleeper(2.0, f"v{i}")) for i in range(3)]
        results = run_with_cap(tasks, max_workers=3, deadline_sec=0.5)

        failed = [r for r in results if r.exception is not None]
        self.assertEqual(
            failed, [],
            msg="tasks that completed during executor drain were recorded as "
                f"failures: {[(r.name, type(r.exception).__name__) for r in failed]}",
        )
        self.assertEqual([r.value for r in results], ["v0", "v1", "v2"])

    def test_never_started_tasks_are_still_reported_as_timeouts(self):
        """The deadline must remain real for work that never ran.

        Guards the opposite over-correction: harvesting must not silently turn
        a starved queue into a clean run. Two workers, eight tasks -- six can
        never start inside the budget and MUST surface as failures so the
        coverage banner fires.
        """
        # Both workers must actually be in flight before the deadline trips,
        # or a loaded CI box could start one and make this fail for a reason
        # that has nothing to do with harvesting.
        entered = threading.Barrier(2, timeout=10)

        def gated(value):
            def f():
                entered.wait()
                time.sleep(2.0)
                return value
            return f

        tasks = [(f"t{i}", gated(f"v{i}")) for i in range(8)]
        results = run_with_cap(tasks, max_workers=2, deadline_sec=0.5)

        timed_out = [r for r in results if isinstance(r.exception, TimeoutError)]
        completed = [r for r in results if r.exception is None]
        self.assertEqual(
            len(completed), 2,
            msg=f"expected the 2 in-flight tasks to be harvested, got "
                f"{[r.name for r in completed]}",
        )
        self.assertEqual(
            len(timed_out), 6,
            msg=f"expected 6 never-started tasks to be reported as timeouts, got "
                f"{[r.name for r in timed_out]}",
        )

    def test_queued_work_is_cancelled_not_executed(self):
        """A blown budget must stop spending, not merely stop reporting.

        Counts executions rather than timing the run: an `elapsed < 3.0` bound
        on 1s tasks at concurrency 2 still passes if a whole extra wave runs, so
        it could not tell "cancelled" from "ran twice as much as it should".
        """
        ran: list[str] = []
        lock = threading.Lock()

        def counting(name: str):
            def f():
                with lock:
                    ran.append(name)
                time.sleep(1.0)
                return name
            return f

        tasks = [(f"t{i}", counting(f"t{i}")) for i in range(10)]
        run_with_cap(tasks, max_workers=2, deadline_sec=0.2)
        self.assertLessEqual(
            len(ran), 2,
            msg=f"{len(ran)} of 10 tasks executed against a 0.2s budget at "
                f"concurrency 2 — queued futures ran instead of being cancelled: {ran}",
        )

    def test_no_deadline_still_runs_everything_to_completion(self):
        """deadline_sec=None must remain an unbounded run (no behaviour change)."""
        tasks = [(f"t{i}", _sleeper(0.05, f"v{i}")) for i in range(6)]
        results = run_with_cap(tasks, max_workers=3, deadline_sec=None)
        self.assertEqual(len(results), 6)
        self.assertTrue(all(r.exception is None for r in results))
        self.assertEqual([r.value for r in results], [f"v{i}" for i in range(6)])

    def test_results_stay_in_submission_order(self):
        """Callers index findings by task name; order is part of the contract."""
        tasks = [
            ("slow", _sleeper(0.30, "S")),
            ("quick", _sleeper(0.01, "Q")),
            ("mid", _sleeper(0.15, "M")),
        ]
        results = run_with_cap(tasks, max_workers=3, deadline_sec=None)
        self.assertEqual([r.name for r in results], ["slow", "quick", "mid"])

    def test_a_raising_task_is_still_reported_as_that_exception(self):
        """Harvesting must not mask real reviewer failures as successes.

        ProviderCallFailed travels this path; if the harvest step swallowed
        exceptions, a dead provider leg would read as a clean review again.
        """
        def boom():
            raise ValueError("provider exploded")

        results = run_with_cap(
            [("ok", _sleeper(0.01, "V")), ("bad", boom)],
            max_workers=2, deadline_sec=None,
        )
        by = {r.name: r for r in results}
        self.assertIsNone(by["ok"].exception)
        self.assertIsInstance(by["bad"].exception, ValueError)
        self.assertIn("provider exploded", str(by["bad"].exception))

    def test_a_task_raising_its_own_TimeoutError_does_not_abort_the_run(self):
        """The run-budget TimeoutError and a task's own TimeoutError collide.

        Disambiguating them with a bare `raise` inside `except TimeoutError`
        escaped `run_with_cap` entirely: Python does not route an exception
        raised in an `except` clause to a sibling `except` on the same `try`.
        One provider timeout therefore aborted the whole reviewer phase.

        This case is why the ValueError test above is not sufficient — only
        TimeoutError collides with the deadline's own signal.
        """
        def times_out():
            raise TimeoutError("the provider call itself timed out")

        for deadline in (None, 30.0):  # no budget, and an ample one
            with self.subTest(deadline_sec=deadline):
                results = run_with_cap(
                    [("ok", _sleeper(0.01, "V")), ("slow", times_out)],
                    max_workers=2, deadline_sec=deadline,
                )
                by = {r.name: r for r in results}
                self.assertEqual(
                    len(results), 2,
                    msg="a task-raised TimeoutError aborted the run instead of "
                        "being recorded",
                )
                self.assertEqual(by["ok"].value, "V")
                self.assertIsInstance(by["slow"].exception, TimeoutError)
                self.assertIn("provider call itself", str(by["slow"].exception))

    def test_an_empty_task_list_returns_empty(self):
        """Boundary: no work must not trip the drain/harvest path."""
        self.assertEqual(run_with_cap([], max_workers=4, deadline_sec=1.0), [])
        self.assertEqual(run_with_cap([], max_workers=4, deadline_sec=None), [])




def test_an_inflight_task_at_the_deadline_is_not_labelled_never_started():
    """`TaskNeverStarted` must mean NEVER STARTED, or it re-creates the very
    mislabelling T010a fixed — this time suppressing a real dead-leg banner
    instead of inventing one.

    The classification is only safe because `ex.shutdown(wait=True)` runs BEFORE
    the harvest loop, so an in-flight task has finished and `fut.done()` is
    settled. That ordering is load-bearing and easy to lose in a refactor, so it
    is asserted rather than commented.
    """
    import time as _time

    from review_plan_v2.concurrency import TaskNeverStarted, run_with_cap

    def slow():
        _time.sleep(0.6)
        return "finished anyway"

    def instant():
        return "ok"

    # Budget expires while `slow` is executing; `instant` never gets a slot.
    results = run_with_cap(
        [("slow", slow), ("queued-a", slow), ("queued-b", instant)],
        max_workers=1, deadline_sec=0.3,
    )
    by_name = {r.name: r for r in results}

    started = by_name["slow"]
    assert not isinstance(started.exception, TaskNeverStarted), (
        "a task that DID start was labelled never-started; if shutdown(wait=True) "
        "no longer precedes the harvest, this classification is unsafe"
    )
    # And something genuinely never ran, or the test proves nothing.
    assert any(isinstance(r.exception, TaskNeverStarted) for r in results), (
        "no task was starved, so this test did not exercise the branch"
    )


if __name__ == "__main__":
    unittest.main()
