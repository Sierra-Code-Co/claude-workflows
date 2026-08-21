"""Review-run coverage honesty + wall-clock budget scaling.

Incident (2026-08-01, mtg-cube-ai PR #1877): a 12-file diff produced

    WARNING: reviewer task correctness:<file> failed:      <- empty message
    ... x34
    No findings.
    === Summary: 0 actionable, 0 nits, 0 info
    $ echo $?
    0

34 of 48 reviewer tasks never executed, yet the gate exited 0 and printed
"No findings" — indistinguishable from a genuinely clean review.

Root cause was a fixed `WALL_CLOCK_BUDGET_SEC = 180.0` for the ENTIRE run
against 48 tasks (12 files x 4 reviewers) at `max_concurrency = 4`. Measured
DeepSeek latency for a *tiny* hunk is 14-19s, so 12 waves needs ~240s floor
and realistically more. Tasks are submitted in reviewer order, so starvation
was strictly ordered: security 12/12 ok, correctness 2/12, tests 0/12,
consistency 0/12.

Two independent defects, tested separately:
  1. the budget did not scale with the work
  2. incomplete coverage reported as success
"""

from __future__ import annotations

import pytest

from review_plan_v2.orchestrator import wall_clock_budget_sec
from review_plan_v2.output_format import exit_code_for
from review_plan_v2.types import Finding


def _finding(sev: str) -> Finding:
    return Finding(
        file="a.py",
        line=1,
        line_end=None,
        severity=sev,
        category="correctness",
        message="m",
        sources=["correctness"],
    )


class TestWallClockBudgetScaling:
    def test_scales_with_task_count(self):
        """The 48-task/4-worker run that starved must get more than the old
        fixed 180s — 12 waves cannot fit in 180s at ~20s/call."""
        assert wall_clock_budget_sec(n_tasks=48, max_workers=4) > 180.0

    def test_small_runs_keep_a_sane_floor(self):
        """A one-file run should not get a 45s budget — provider tail latency
        (measured p-high ~51s on gemini-3.1-pro-preview) would false-timeout."""
        assert wall_clock_budget_sec(n_tasks=1, max_workers=4) >= 180.0

    def test_is_bounded_so_a_huge_diff_cannot_hang_forever(self):
        assert wall_clock_budget_sec(n_tasks=5000, max_workers=4) <= 1800.0

    def test_more_workers_means_fewer_waves_means_less_wall_clock(self):
        wide = wall_clock_budget_sec(n_tasks=48, max_workers=16)
        narrow = wall_clock_budget_sec(n_tasks=48, max_workers=2)
        assert wide < narrow

    def test_zero_workers_does_not_divide_by_zero(self):
        assert wall_clock_budget_sec(n_tasks=10, max_workers=0) >= 180.0


class TestCoverageAwareExitCode:
    def test_clean_and_complete_is_zero(self):
        assert exit_code_for([], failed_task_count=0) == 0

    def test_actionable_finding_is_one(self):
        assert exit_code_for([_finding("actionable")], failed_task_count=0) == 1

    def test_incomplete_coverage_is_tool_error_not_clean(self):
        """THE incident case: no findings, but the reviewers never ran.
        Must not be 0 — a gate that didn't run is not a gate that passed."""
        assert exit_code_for([], failed_task_count=34) == 2

    def test_incomplete_coverage_outranks_a_clean_finding_set(self):
        """Even one dropped task means the 'clean' verdict is unproven."""
        assert exit_code_for([_finding("nit")], failed_task_count=1) == 2

    def test_actionable_findings_still_reported_when_coverage_incomplete(self):
        """Partial coverage that DID surface a real problem should still fail
        as a review failure (1), not be masked as a tool error — the finding
        is actionable regardless of what else went unreviewed."""
        assert exit_code_for([_finding("actionable")], failed_task_count=5) == 1

    def test_default_keeps_the_old_two_arg_free_call_shape(self):
        """Existing call sites pass findings only; they must keep working."""
        assert exit_code_for([]) == 0
        assert exit_code_for([_finding("actionable")]) == 1


@pytest.mark.parametrize("n_failed", [1, 5, 34, 48])
def test_render_plain_states_incomplete_coverage(n_failed):
    """'No findings.' alone is the dangerous string — the operator must be
    told the run was partial, in the same output they read for findings."""
    from review_plan_v2.output_format import render_plain

    out = render_plain(
        [], {"failed_task_count": n_failed, "total_task_count": 48}
    )
    assert "INCOMPLETE" in out.upper()
    assert str(n_failed) in out
