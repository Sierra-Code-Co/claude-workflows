"""The suite must never write to the operator's real telemetry log.

63 records under `reviewer="test"` had already leaked into
~/.claude/review-plan-v2/logs/calls.jsonl before this guard existed, several
carrying a mocked `latency_ms=180000` and a synthetic `error_kind="empty"`.
Those rows sit in the same file every capacity and failure-rate analysis in this
repo reads, and they cost real time during the #28 investigation: a post-fix run
appeared to log 15 provider failures while reporting zero failed tasks, and the
whole discrepancy was this suite contaminating its own evidence.
"""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest import mock

from review_plan_v2 import telemetry  # noqa: E402
from review_plan_v2.providers import deepseek as ds  # noqa: E402

PRODUCTION_LOG_DIR = Path.home() / ".claude" / "review-plan-v2" / "logs"


class TelemetryIsolationTests(unittest.TestCase):
    def test_the_env_redirect_is_active_during_tests(self):
        """conftest sets it session-wide; without that the fallback is production."""
        configured = os.environ.get("REVIEW_PLAN_V2_LOG_DIR")
        self.assertTrue(
            configured,
            "REVIEW_PLAN_V2_LOG_DIR is unset — log_call would fall back to "
            f"{PRODUCTION_LOG_DIR}",
        )
        self.assertNotEqual(
            Path(configured).resolve(), PRODUCTION_LOG_DIR.resolve(),
            msg="tests are pointed at the production telemetry log",
        )

    def test_a_provider_call_writes_only_to_the_redirected_dir(self):
        """End-to-end: exercise the real path a test would use and confirm the
        record lands in the sandbox, not in the operator's log.

        Compares production by SIZE DELTA across the call, not by searching for
        a marker string. Searching found matches left by earlier runs of this
        very test and failed on residue — a test that cannot distinguish "I just
        wrote this" from "someone wrote this yesterday" is not measuring what it
        claims to.
        """
        prod = PRODUCTION_LOG_DIR / "calls.jsonl"
        before = prod.stat().st_size if prod.exists() else None

        def fake_post(url, headers, payload, timeout):
            return 200, json.dumps({
                "choices": [{"message": {"content": "[]"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            }).encode()

        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key-not-real"}), \
                mock.patch.object(ds, "_post_once", fake_post):
            ds.call("sys", "user", reviewer="telemetry-isolation-probe")

        sandbox = Path(os.environ["REVIEW_PLAN_V2_LOG_DIR"]) / "calls.jsonl"
        self.assertTrue(sandbox.exists(), "no telemetry written to the sandbox at all")
        written = [json.loads(x) for x in sandbox.read_text().splitlines() if x.strip()]
        self.assertTrue(
            any(r.get("reviewer") == "telemetry-isolation-probe" for r in written),
            msg="the probe record did not land in the sandbox log",
        )

        if before is not None:
            after = prod.stat().st_size if prod.exists() else 0
            self.assertEqual(
                after, before,
                msg=f"the suite appended {after - before} bytes to the production "
                    f"telemetry log at {prod}",
            )

    def test_log_dir_is_resolved_per_call_not_cached_at_import(self):
        """The redirect only works because _log_dir() re-reads the env each call.

        If that were hoisted to import time, conftest's session fixture could
        lose a race with module import and silently stop protecting the log.
        """
        with mock.patch.dict(os.environ, {"REVIEW_PLAN_V2_LOG_DIR": "/tmp/rpv2-probe-a"}):
            first = telemetry._log_dir()
        with mock.patch.dict(os.environ, {"REVIEW_PLAN_V2_LOG_DIR": "/tmp/rpv2-probe-b"}):
            second = telemetry._log_dir()
        self.assertNotEqual(first, second)


# NO `__main__` guard, deliberately (T005i-b).
#
# The other seven guarded modules under tests/unit/ were bootstrapped so their
# guards became true. This one cannot be, and adding a path bootstrap only
# moved the lie: these tests assert that REVIEW_PLAN_V2_LOG_DIR is set, which
# `conftest.py` does and nothing else does. Run standalone they fail — and the
# failure is CORRECT, because outside pytest the redirect genuinely is not in
# place. A module that exists to verify the harness cannot be run without it.
#
# So the guard is removed rather than made to pass. A guard that does not work
# is a claim that is false; a guard that "works" by asserting less would be
# worse, because it would look like coverage.
