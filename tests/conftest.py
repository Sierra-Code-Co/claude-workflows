"""Keep the test suite out of the operator's real telemetry log.

`telemetry.log_call` resolves its directory per call from
REVIEW_PLAN_V2_LOG_DIR, falling back to ~/.claude/review-plan-v2/logs — the
production log every diagnosis in this repo is run against. Any test that
exercises a provider `call()` therefore appended to it, and 63 such records had
already accumulated under `reviewer="test"`, including mocked-clock entries
claiming `latency_ms=180000` and synthetic `error_kind="empty"` rows.

That is not cosmetic. Working out why a post-fix run showed 15 provider failures
while the review itself reported zero failed tasks cost real time, and the
answer was that every one of those failures was this suite writing into the
dataset being analysed. Telemetry a test can corrupt is telemetry you cannot
diagnose from.

Redirected here rather than per-test for the same reason the budget constants
live in one module: anything each test has to remember, some test will forget.
"""
from __future__ import annotations

import os
import sys

import pytest

# Enforce the declared floor. On macOS `python3` is /usr/bin/python3 — 3.9.6 — so
# running the suite without a venv on a fresh machine lands on an unsupported
# interpreter by default, and CI runs 3.12. A green result on a version nothing
# validates does not mean what the reader takes it to mean.
#
# Being exact about what this buys, because the reason it was added is not the
# reason it stays. It was added after four tests in test_run_budget_bounds failed
# on 3.9 in a way that reads as a concurrency flake:
# `concurrent.futures.TimeoutError` only became an alias of the builtin
# `TimeoutError` in 3.11, run_with_cap caught the builtin, so below 3.11 the
# deadline branch never fired and those tests failed on their own anti-vacuity
# assertion — "no task was starved, so this test did not exercise the branch",
# a true statement about a suite that cannot exercise the branch, and a full
# diagnostic detour to reach on 2026-08-25.
#
# That turned out to be a real bug on a declared-supported version rather than a
# test artifact, and it is fixed at the source in concurrency.py. With that fix
# the whole suite passes on 3.9 too (verified: 1101 passed). So this guard is now
# policy, not a workaround: it refuses an interpreter nothing validates, and it
# names the interpreter rather than leaving the reader to infer it from a
# failure. Do not weaken it because 3.9 happens to work — nothing tests that it
# keeps working, and the next 3.9-only divergence gets found the same expensive
# way this one did.
#
# collect-time and unconditional, not a skip: a skipped test on the wrong
# interpreter is the fail-silent shape this suite exists to remove.
_MIN = (3, 10)
if sys.version_info < _MIN:
    raise RuntimeError(
        f"this suite requires Python >= {'.'.join(map(str, _MIN))} "
        f"(pyproject requires-python); got {sys.version.split()[0]} at "
        f"{sys.executable}. On macOS `python3` is /usr/bin/python3 (3.9), so use "
        f"a venv: `python3.13 -m venv .venv && .venv/bin/pip install -e '.[dev]'` "
        f"then `.venv/bin/python -m pytest`. CI runs 3.12, so a pass on an older "
        f"interpreter is not evidence about the supported configuration."
    )


@pytest.fixture(autouse=True, scope="session")
def _isolate_telemetry_log(tmp_path_factory):
    log_dir = tmp_path_factory.mktemp("rpv2-telemetry")
    prior = os.environ.get("REVIEW_PLAN_V2_LOG_DIR")
    os.environ["REVIEW_PLAN_V2_LOG_DIR"] = str(log_dir)
    try:
        yield log_dir
    finally:
        if prior is None:
            os.environ.pop("REVIEW_PLAN_V2_LOG_DIR", None)
        else:
            os.environ["REVIEW_PLAN_V2_LOG_DIR"] = prior
