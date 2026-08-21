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

import pytest


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
