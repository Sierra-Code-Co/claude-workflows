"""What a provider's FAILURE telemetry row records, and what it refuses to.

Four review gates in one round asked the providers to build their failure row
with `**budget_fields(...)`, as the success row does, so the two share a schema.
The request is reasonable and the answer is no, for a reason that is easy to lose
and expensive to relearn — so it is asserted here rather than argued in a comment
a fifth reviewer will not read.

`budget_fields` returns `{"max_tokens": ..., "near_budget": ...}`, and
`near_budget` is `completion_tokens >= ratio * budget`. On a failure
`completion_tokens` is 0 because the call produced NOTHING, not because it used
nothing, so the answer is not False — it is unknown. A call killed at the wall
may have been about to overrun its token budget; that is one of the likelier
things to want to know from a failure row. Writing `near_budget: false` there
would be a plausible, checkable-looking claim that nothing checked, which is the
defect the rest of this branch exists to remove. An absent key says "not
measured". A false one says "measured, and no".

So the two rows differ, on purpose, in exactly one field. Both halves are
asserted: the budgets that ARE knowable must be present (they were missing, which
was a real gap, on the one class of row where the ceiling is the likely cause),
and the one that is not must stay out.
"""
from __future__ import annotations

import http.client
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from review_plan_v2.providers import _budget, google
from review_plan_v2.providers import openai as openai_mod

# Knowable from a failure and load-bearing for diagnosis: which ceilings were in
# force when the call died. Absent until 2026-08-25, so every timeout kill in the
# log had to be read against constants pulled out of today's source, on the
# assumption they had not moved.
REQUIRED_ON_FAILURE = ("max_tokens", "timeout_sec", "max_call_sec")


class TheFailureRowRecordsTheCeilingsAndNotTheUnknowable(unittest.TestCase):
    def _rows(self, mod, tag):
        """Drive `mod.call()` into the failure path and return its telemetry rows.

        A real call through the real handler, not a hand-built dict: the point is
        what the shipped code writes. `IncompleteRead` is the cheapest fault that
        reaches the failure row, and the tiny MAX_CALL makes the guard refuse the
        retry immediately so the test costs no wall clock.
        """
        with tempfile.TemporaryDirectory() as log_dir:
            env = {
                "GEMINI_API_KEY": "k", "OPENAI_API_KEY": "k",
                "REVIEW_PLAN_V2_GOOGLE_MAX_CALL": "0.01",
                "REVIEW_PLAN_V2_OPENAI_MAX_CALL": "0.01",
                "REVIEW_PLAN_V2_LOG_DIR": log_dir,
            }
            # autospec: without it the mock accepts whatever `mod.call` passes, so a
            # changed `_post_once` signature would leave this test green against
            # production code that can no longer make the call. A mock that cannot
            # notice interface drift is the same fail-silent shape as a guard that
            # cannot fail.
            with mock.patch.object(
                mod, "_post_once", autospec=True,
                side_effect=http.client.IncompleteRead(b"truncated"),
            ), mock.patch.dict(os.environ, env, clear=False):
                result = mod.call("sys", "user", reviewer="schema-test")
            self.assertIsNone(result.content, "expected the failure path, got content")
            rows = []
            for path in Path(log_dir).rglob("*.jsonl"):
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        rows.append(json.loads(line))
        mine = [r for r in rows if r.get("reviewer") == "schema-test"]
        self.assertTrue(mine, f"{tag} wrote no telemetry row for the failed call")
        return mine

    def test_the_knowable_budgets_are_recorded(self):
        for tag, mod in (("google", google), ("openai", openai_mod)):
            for row in self._rows(mod, tag):
                with self.subTest(provider=tag):
                    for field in REQUIRED_ON_FAILURE:
                        self.assertIn(
                            field, row,
                            f"{tag} failure row omits {field}; a timeout kill with no "
                            f"record of the ceiling that killed it has to be diagnosed "
                            f"against constants read out of today's source",
                        )

    def test_near_budget_is_absent_rather_than_false(self):
        """The load-bearing half. `assertNotIn`, not `assertFalse`: a False value
        would satisfy a truthiness check while making exactly the unchecked claim
        this test exists to keep out of the log.
        """
        for tag, mod in (("google", google), ("openai", openai_mod)):
            for row in self._rows(mod, tag):
                with self.subTest(provider=tag):
                    self.assertNotIn(
                        "near_budget", row,
                        f"{tag} failure row asserts near_budget={row.get('near_budget')!r}. "
                        f"On a failure completion_tokens is 0 because the call produced "
                        f"nothing, so this field is unknown, not False. Absent means "
                        f"'not measured'; present means 'measured'.",
                    )

    def test_the_success_row_does_carry_it(self):
        """Anti-over-correction, and the reason the asymmetry is a decision rather
        than an oversight. If `budget_fields` stopped emitting `near_budget` at
        all, the test above would pass for the wrong reason and the near-budget
        warning — a real signal about answers silently truncated to empty — would
        be gone with nothing to say so.
        """
        fields = _budget.budget_fields(1, 100, "schema-test", stream=io.StringIO())
        self.assertIn("near_budget", fields)
        self.assertIn("max_tokens", fields)

    def test_the_two_rows_differ_in_exactly_one_field(self):
        """Pins the size of the asymmetry. A future field added to
        `budget_fields` and not to the failure row would widen the gap silently,
        and the next reviewer to notice would be right to ask about it — this
        fails first, naming what appeared.
        """
        success_keys = set(_budget.budget_fields(
            1, 100, "schema-test", stream=io.StringIO()))
        for tag, mod in (("google", google), ("openai", openai_mod)):
            for row in self._rows(mod, tag):
                with self.subTest(provider=tag):
                    self.assertEqual(
                        success_keys - set(row), {"near_budget"},
                        f"{tag}: the failure row is missing budget fields other than "
                        f"the deliberately-absent near_budget",
                    )


if __name__ == "__main__":
    unittest.main()
