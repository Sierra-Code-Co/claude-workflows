"""The retry budget can actually pay for a retry, and the deadlines above it agree.

Two retries were configured in every provider and NONE of them could ever run.
The guard refuses an attempt the budget cannot cover —
`elapsed + sleep_for + timeout > max_call_sec` — and with the shipped values that
read `180 + 1 + 180 = 361 > 300`, so a call that used its whole per-attempt wall
gave up immediately. All 10 timeout kills in
`~/.claude/review-plan-v2/logs/calls.jsonl` carry `retry_count: 0`. Nothing
reported it: the run said "transient", which is what a provider fault looks like.

`MAX_CALL_SEC` is therefore derived from `TIMEOUT_SEC` now, and the run-level
deadline in orchestrator.py is derived from `MAX_CALL_SEC`. Derivation is only
half a fix, though, because the next person can still hand-set either one back.
So these tests assert the RULES rather than the numbers:

  * the budget buys exactly one retry after a full-length stall, and not two
  * the same arithmetic buys ZERO at the values that shipped, so the assertion
    above is not vacuous
  * the run deadline exceeds one full provider retry chain, which the old
    constants claimed in a comment while being equal to it
  * the clamp that applies the deadline is not inverted, which would silently
    discard the floor rather than raise
  * no live provider re-declares the retry policy the budget is derived from

The behavioural case at the end drives a real `google.call()` against a socket
that accepts and never answers, so the guard's arithmetic is checked as executed
rather than as re-implemented here.
"""
from __future__ import annotations

import ast
import http.server
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from review_plan_v2 import orchestrator
from review_plan_v2.providers import _budget, google

# The values that shipped, kept as literals on purpose. Every other number in this
# file is read from the module so it cannot go stale, but these two must NOT track
# the source: they are the historical configuration whose retry count was zero, and
# an A/B against them is what makes the "one retry" assertion mean something.
SHIPPED_TIMEOUT_SEC = 180.0
SHIPPED_MAX_CALL_SEC = 300.0

# Worst single-attempt latency measured with the ceiling raised out of the way
# (REVIEW_PLAN_V2_GOOGLE_TIMEOUT=900), re-running a reviewer x file pair that had
# been dying at 180s. It returned a finding, so this is a duration real work takes.
MEASURED_WORST_OK_SEC = 211.2

PROVIDERS_DIR = Path(_budget.__file__).parent
# The two providers a run can actually select. deepseek and anthropic are refused at
# the registry, so their own RETRY_SLEEPS copies bind nothing; touching them would
# add risk without changing any run.
LIVE_PROVIDERS = ("google.py", "openai.py")


class TestRetryAffordability(unittest.TestCase):
    def test_one_retry_is_affordable_after_a_full_stall(self):
        self.assertEqual(
            _budget.affordable_attempts(), 2,
            "the budget must pay for one retry after an attempt burns the whole "
            "per-attempt wall, which is the only case retries exist for",
        )

    def test_shipped_values_afforded_none(self):
        # The regression itself. If this ever returns 2, the arithmetic being
        # asserted above has changed shape and the test above proves nothing.
        self.assertEqual(
            _budget.affordable_attempts(
                timeout=SHIPPED_TIMEOUT_SEC, max_call_sec=SHIPPED_MAX_CALL_SEC,
            ), 1,
            "180 + 1 + 180 > 300, so the shipped configuration could not retry a "
            "timed-out call even once",
        )

    def test_a_third_full_length_attempt_is_refused(self):
        # The ceiling half of the derivation: one retry is worth a stalled
        # provider, three attempts is 21 minutes on one doomed chunk.
        self.assertLess(
            _budget.affordable_attempts(), 1 + len(_budget.RETRY_SLEEPS),
            "the budget must not fund every configured retry at full length",
        )

    def test_max_call_sec_is_derived_not_hand_set(self):
        self.assertEqual(_budget.MAX_CALL_SEC, _budget.derive_max_call_sec())

    def test_timeout_covers_the_measured_worst_successful_call(self):
        self.assertGreater(
            _budget.TIMEOUT_SEC, MEASURED_WORST_OK_SEC,
            f"a call measured at {MEASURED_WORST_OK_SEC}s returned findings; a "
            f"per-attempt wall below it discards completed reviews",
        )

    def test_derivation_tracks_a_changed_timeout(self):
        # A derivation that only holds at today's value is a coincidence.
        #
        # This sampled (30, 180, 420, 900) and passed, while `timeout < 12` funded a
        # THREE-attempt chain and `derive_max_call_sec`'s docstring said a third
        # attempt was refused. Every sampled value sat comfortably above the
        # breakpoint, so the test asserted the derivation "tracks a changed timeout"
        # without sampling the range where it did not. A sample chosen from the
        # values one expects to work is not a check on a derivation; it is the same
        # coincidence this test's own comment warns about, one level in.
        #
        # Swept rather than sampled, from well below the breakpoint to well above,
        # and the small end is the point: 0.5 is not a realistic timeout, but
        # `REVIEW_PLAN_V2_GOOGLE_TIMEOUT=10` is an entirely realistic thing for
        # someone to try while testing, and it silently bought a third attempt.
        violations = []
        timeout = 0.5
        while timeout <= 1000.0:
            n = _budget.affordable_attempts(
                timeout=timeout,
                max_call_sec=_budget.derive_max_call_sec(timeout=timeout),
            )
            if n != 2:
                violations.append((timeout, n))
            timeout += 0.5
        self.assertEqual(
            violations, [],
            msg=f"{len(violations)} timeout value(s) do not afford exactly one retry; "
                f"first few: {violations[:5]}",
        )

    def test_the_derivation_brackets_itself_at_every_timeout(self):
        """The two bounds directly, not via the attempt count.

        `affordable_attempts` and the ceiling are both derived from the same sleeps,
        so a single arithmetic slip could move them together and leave the count at 2
        while the guard's own inequality no longer says what it claims. These are the
        bounds as the docstring states them, evaluated independently.
        """
        sleeps = _budget.RETRY_SLEEPS
        timeout = 0.5
        while timeout <= 1000.0:
            with self.subTest(timeout=timeout):
                mx = _budget.derive_max_call_sec(timeout=timeout, sleeps=sleeps)
                self.assertGreaterEqual(
                    mx, 2.0 * timeout + sleeps[0],
                    msg="the ceiling does not afford one full-length retry")
                self.assertLess(
                    mx, 3.0 * timeout + sleeps[0] + sleeps[1],
                    msg="the ceiling funds a third full-length attempt")
            timeout *= 4.0

    def test_the_slack_cap_does_not_bind_at_the_shipped_values(self):
        # The cap exists for small overrides. If it ever starts binding at the
        # shipped timeout, the ceiling has moved and 856.0 is no longer the number
        # the telemetry in these tests was read against.
        self.assertEqual(
            _budget.derive_max_call_sec(),
            2.0 * _budget.TIMEOUT_SEC + _budget.RETRY_SLEEPS[0]
            + _budget.RETRY_BUDGET_SLACK_SEC,
            msg="the slack cap now binds at the shipped timeout; re-read the "
                "measured telemetry values in this file before changing it",
        )

    def test_the_helper_derives_its_own_ceiling_when_none_is_given(self):
        """The case above passes `max_call_sec` explicitly, so it could not have
        caught the helper's own default being the import-time constant.

        With `max_call_sec=MAX_CALL_SEC` as the default,
        `affordable_attempts(timeout=900)` answered for a configuration nobody
        runs — a 900s timeout under a ceiling derived from 420 — so the helper
        written to prove the retry rule would have agreed with the override bug
        below instead of catching it.
        """
        for timeout in (30.0, 180.0, 420.0, 900.0):
            with self.subTest(timeout=timeout):
                self.assertEqual(_budget.affordable_attempts(timeout=timeout), 2)


class TestAnEnvOverrideCannotBreakTheRetryRule(unittest.TestCase):
    """The derivation held for the CONSTANTS and not for the OVERRIDES.

    Each provider read the two values from two independent env vars, with the
    ceiling defaulting to its import-time value, then clamped
    `timeout = min(timeout, max_call_sec)`. So raising only the timeout left the
    ceiling where it was and the clamp cut the timeout back down to it. At the
    shipped values that is `TIMEOUT=900 -> timeout 856, attempts 1`: zero
    retries, the original defect verbatim, reached through the documented way to
    measure latency above the ceiling — which is how TIMEOUT_SEC was sized.
    The other direction is as bad and less obvious: `TIMEOUT=180 -> attempts 3`,
    a third full-length attempt `derive_max_call_sec` exists to refuse.

    Asserted through `resolve_call_budget` rather than by re-doing the
    arithmetic, and on the RULE (exactly one retry, at every timeout) rather than
    on the numbers.
    """

    def _resolved(self, **env):
        with mock.patch.dict(os.environ, env, clear=False):
            for var in ("X_TIMEOUT", "X_MAX"):
                if var not in env:
                    os.environ.pop(var, None)
            return _budget.resolve_call_budget("X_TIMEOUT", "X_MAX")

    def test_one_retry_survives_every_timeout_override(self):
        for raw in ("30", "180", "420", "900", "1800"):
            with self.subTest(timeout=raw):
                timeout, max_call = self._resolved(X_TIMEOUT=raw)
                self.assertEqual(timeout, float(raw),
                                 "the timeout was silently clamped below what was asked for")
                self.assertEqual(_budget.affordable_attempts(timeout, max_call), 2)

    def test_the_old_two_var_form_bought_zero_retries_at_900(self):
        """A/B against the code this replaces, so the fix is shown to fix
        something. Without it the assertions above would pass on the broken
        version too for the default timeout, which is the only value it got right.
        """
        old_ceiling = _budget.MAX_CALL_SEC          # import-time, derived from 420
        old_timeout = min(900.0, old_ceiling)       # the silent clamp
        self.assertEqual(_budget.affordable_attempts(old_timeout, old_ceiling), 1,
                         "the two-var form is expected to afford zero retries at 900")
        self.assertEqual(_budget.affordable_attempts(min(180.0, old_ceiling), old_ceiling), 3,
                         "the two-var form is expected to afford a refused third attempt at 180")

    def test_junk_in_the_ceiling_var_derives_rather_than_reverting(self):
        """A typo must not silently restore the stale constant, which is the bug.
        `env_float` rejects non-positive and non-finite, so junk, empty, and
        absent all land in the derive branch.
        """
        for raw in ("garbage", "0", "-5", "inf", ""):
            with self.subTest(max_call=raw):
                timeout, max_call = self._resolved(X_TIMEOUT="900", X_MAX=raw)
                self.assertEqual(max_call, _budget.derive_max_call_sec(900.0))
                self.assertEqual(_budget.affordable_attempts(timeout, max_call), 2)

    def test_an_explicitly_lower_ceiling_is_still_honoured(self):
        """Anti-over-correction. Deriving must not override an operator who set
        the ceiling BELOW the timeout on purpose — that is a real choice, and the
        clamp is correct for it.
        """
        timeout, max_call = self._resolved(X_TIMEOUT="900", X_MAX="500")
        self.assertEqual(max_call, 500.0)
        self.assertEqual(timeout, 500.0, "an explicit ceiling below the timeout must clamp it")


class TestRunDeadlineAgrees(unittest.TestCase):
    def test_floor_exceeds_one_provider_retry_chain(self):
        self.assertGreater(
            orchestrator.MIN_WALL_CLOCK_SEC, _budget.MAX_CALL_SEC,
            "the run deadline must not fire while a provider is still inside its "
            "own budget — the banner then blames a provider fault that is ours",
        )

    def test_ceiling_exceeds_floor_so_the_clamp_is_not_inverted(self):
        # min(MAX, max(MIN, x)) with MIN > MAX returns MAX for every input: the
        # floor stops applying and nothing raises.
        self.assertGreater(orchestrator.MAX_WALL_CLOCK_SEC,
                           orchestrator.MIN_WALL_CLOCK_SEC)

    def test_the_floor_actually_applies_to_a_tiny_run(self):
        self.assertEqual(
            orchestrator.wall_clock_budget_sec(1, 4), orchestrator.MIN_WALL_CLOCK_SEC,
            "a one-task run must get the floor; if the clamp were inverted this "
            "would silently be the ceiling instead",
        )


class TestNoProviderRedeclaresTheRetryPolicy(unittest.TestCase):
    """A local `RETRY_SLEEPS` would change how many retries a provider tries to
    make without changing the budget that pays for them — a longer local sleep
    would buy FEWER retries, silently.

    Parsed rather than grepped: a regex for `^RETRY_SLEEPS` matches a comment
    mentioning it and misses a formatter-wrapped assignment, and this repo has
    already been bitten by `[^\\n]*` stopping at the first newline.
    """

    def test_live_providers_import_it(self):
        for name in LIVE_PROVIDERS:
            with self.subTest(provider=name):
                tree = ast.parse((PROVIDERS_DIR / name).read_text(encoding="utf-8"))
                assigned = [
                    t.id
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Assign)
                    for t in node.targets
                    if isinstance(t, ast.Name)
                ]
                self.assertNotIn(
                    "RETRY_SLEEPS", assigned,
                    f"{name} assigns its own RETRY_SLEEPS; import it from _budget, "
                    f"which derives MAX_CALL_SEC from it",
                )
                # `from ._budget import X` parses as module="_budget", level=1 — the
                # leading dot is the level, not part of the name. Asserting on
                # "._budget" matched nothing and so passed for the wrong reason
                # until the first run of this file caught it.
                imported = {
                    alias.name
                    for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom)
                    and node.module == "_budget" and node.level == 1
                    for alias in node.names
                }
                self.assertIn("RETRY_SLEEPS", imported,
                              f"{name} must take the shared retry policy")

    def test_the_check_catches_a_provider_that_does_redeclare_it(self):
        """The assertion above can only pass; prove it can also fail.

        Two "no local RETRY_SLEEPS" checks in this repo's history passed because
        they were looking for something that could never be there — a
        formatter-wrapped call a regex missed, and (in the first run of this very
        file) an import name spelled with a leading dot the AST never uses.
        """
        offender = ast.parse(
            "from ._budget import TIMEOUT_SEC\n"
            "RETRY_SLEEPS = (\n    1.0,\n    4.0,\n)\n"  # wrapped, as a formatter leaves it
        )
        assigned = [
            t.id
            for node in ast.walk(offender)
            if isinstance(node, ast.Assign)
            for t in node.targets
            if isinstance(t, ast.Name)
        ]
        self.assertIn("RETRY_SLEEPS", assigned)
        imported = {
            alias.name
            for node in ast.walk(offender)
            if isinstance(node, ast.ImportFrom)
            and node.module == "_budget" and node.level == 1
            for alias in node.names
        }
        self.assertNotIn("RETRY_SLEEPS", imported)


class TestADroppedConnectionIsRetryable(unittest.TestCase):
    """The fault that made the 2026-08-25 pre-push run report INCOMPLETE.

    One reviewer task of 394 died with
    `unknown (HTTP no-response) — Remote end closed connection without response`,
    and one non-retryable classification of one dropped socket made the whole
    review's verdict unproven (exit 2). RemoteDisconnected subclasses
    ConnectionResetError and BadStatusLine but NOT urllib.error.URLError, so it
    fell past both transient branches into `unknown, False`.

    deepseek.py had already fixed exactly this and carries a comment explaining
    it. deepseek is the one provider that can no longer be selected, so the fix
    lived only where it could never run — which is why this class asserts the
    property across every LIVE provider by module rather than once.
    """

    def _providers(self):
        from review_plan_v2.providers import openai as openai_mod
        return (("google", google), ("openai", openai_mod))

    def _log_dir(self):
        """A telemetry log directory that is removed when the test ends."""
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        return td.name

    def test_a_dropped_connection_is_transient_and_retryable(self):
        import http.client
        faults = (
            http.client.RemoteDisconnected("Remote end closed connection without response"),
            ConnectionResetError(54, "Connection reset by peer"),
            http.client.IncompleteRead(b"half a re"),
        )
        for name, mod in self._providers():
            for exc in faults:
                with self.subTest(provider=name, fault=type(exc).__name__):
                    kind, retryable = mod._classify(None, exc)
                    self.assertEqual(kind, "transient")
                    self.assertTrue(retryable)

    def test_the_handler_actually_catches_what_it_classifies(self):
        """Classifying a fault as retryable does nothing if the `except` clause
        never sees it.

        IncompleteRead is HTTPException and NOT OSError, so on the first version
        of this fix it was classified retryable and still propagated out of
        `call()` as an uncaught exception. A fix that cannot be reached is the
        shape this whole branch is about, so the catch is asserted separately
        from the classification.
        """
        import http.client
        for name, mod in self._providers():
            with self.subTest(provider=name):
                caught = mod._post_once.__module__  # touch it so a rename fails here
                self.assertTrue(caught)
                with mock.patch.object(
                    mod, "_post_once", autospec=True,
                    # autospec so a changed `_post_once` signature fails here
                    # instead of leaving this test green against a call that no
                    # longer exists in that shape. Same reason as
                    # test_failure_row_schema.py's patch of the same function.
                    side_effect=http.client.IncompleteRead(b"truncated"),
                ), mock.patch.dict(os.environ, {
                    "GEMINI_API_KEY": "k", "OPENAI_API_KEY": "k",
                    "REVIEW_PLAN_V2_GOOGLE_MAX_CALL": "0.01",
                    "REVIEW_PLAN_V2_OPENAI_MAX_CALL": "0.01",
                    # TemporaryDirectory, not a bare mkdtemp(). Inline in this
                    # dict it leaked one directory per provider per run, with
                    # nothing to observe but disk — the same defect, and the same
                    # invisibility, as the throwaway HOMEs the sibling installer
                    # harness was leaking on every run.
                    "REVIEW_PLAN_V2_LOG_DIR": self._log_dir(),
                }, clear=False):
                    # The tiny MAX_CALL keeps this instant: the first attempt
                    # raises, and the budget guard then refuses the retry.
                    result = mod.call("sys", "user", reviewer="drop-test")
                self.assertEqual(
                    result.error_kind, "transient",
                    f"{name} did not survive a truncated response body",
                )

    def test_a_genuine_unknown_is_still_not_retried(self):
        """Anti-vacuous control for the over-correction. If everything is
        transient, the retry budget is spent on faults that will never clear."""
        for name, mod in self._providers():
            with self.subTest(provider=name):
                kind, retryable = mod._classify(None, ValueError("bad payload"))
                self.assertEqual(kind, "unknown")
                self.assertFalse(retryable)


class _Stall(http.server.BaseHTTPRequestHandler):
    """Accepts the request, reads the body, then never answers.

    A closed port would fail instantly with a connection error, which the guard
    never gets to weigh in on. Only a stall reproduces the case at issue: an
    attempt that consumes the entire per-attempt wall.
    """

    protocol_version = "HTTP/1.1"
    # Long enough to outlast any per-attempt wall used below, short enough that a
    # leaked handler thread cannot hold the suite open.
    STALL_SEC = 5.0

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        time.sleep(self.STALL_SEC)

    def log_message(self, *args):
        pass


class TestGuardBehaviourAgainstAStalledProvider(unittest.TestCase):
    """Drive the real retry loop, so what is asserted is the code as executed.

    Everything above re-derives the guard's arithmetic in `affordable_attempts`.
    That is the right way to state the rule, and it is also a re-implementation:
    if the providers' inline `elapsed + sleep_for + timeout > max_call_sec` were
    changed, every test above would still pass. This one would not.
    """

    # Scaled down ~1000x from the shipped 420s so the suite stays fast. The slack is
    # scaled with it: RETRY_BUDGET_SLACK_SEC is an ABSOLUTE 15s, so at a 0.4s
    # per-attempt wall the slack alone would fund several extra attempts and the
    # ratio under test would not be production's. The first run of this file asserted
    # one retry at the unscaled slack and got two, which is how that was found.
    TIMEOUT = 0.4
    SLACK = 0.05

    def setUp(self):
        # Threading, because the handler stalls: on a single-threaded server the
        # SECOND attempt queues behind the first handler's sleep instead of stalling
        # on its own, so the retry would be timed against the wrong thing.
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Stall)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def _retry_count(self, timeout: float, max_call_sec: float) -> int:
        env = {
            "GEMINI_API_KEY": "not-a-real-key-the-server-never-reads-it",
            "GOOGLE_API_BASE": self.base,
            "REVIEW_PLAN_V2_GOOGLE_TIMEOUT": str(timeout),
            "REVIEW_PLAN_V2_GOOGLE_MAX_CALL": str(max_call_sec),
            "REVIEW_PLAN_V2_LOG_DIR": self.tmp.name,
        }
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("GOOGLE_API_KEY", None)
            result = google.call("sys", "user", reviewer="budget-test")
        self.assertEqual(result.error_kind, "transient",
                         "a stalled response is a retryable fault, not a hard one")
        rows = [
            json.loads(line)
            for line in (Path(self.tmp.name) / "calls.jsonl").read_text().splitlines()
            if line.strip()
        ]
        return rows[-1]["retry_count"]

    def test_a_stalled_call_is_retried_under_the_derived_budget(self):
        budget = _budget.derive_max_call_sec(timeout=self.TIMEOUT, slack=self.SLACK)
        got = self._retry_count(self.TIMEOUT, budget)
        # Asserted against the helper rather than a literal, because agreement
        # between the two is the property: `affordable_attempts` states the rule and
        # the providers execute it, and a divergence is the bug this file exists for.
        want = _budget.affordable_attempts(timeout=self.TIMEOUT, max_call_sec=budget) - 1
        self.assertEqual(want, 1, "the scaled fixture must reproduce production's shape")
        self.assertEqual(got, want,
                         "the guard as executed disagrees with affordable_attempts")

    def test_the_shipped_ratio_retried_nothing(self):
        # 300/180 = 1.67x the per-attempt wall, the ratio that shipped. A/B against
        # the case above: same server, same stall, retry count differs only because
        # of the budget.
        ratio = SHIPPED_MAX_CALL_SEC / SHIPPED_TIMEOUT_SEC
        got = self._retry_count(self.TIMEOUT, self.TIMEOUT * ratio)
        self.assertEqual(
            got, 0,
            "if this retries, the guard no longer refuses unaffordable attempts and "
            "the fix above is not what fixed anything",
        )

    def test_the_failure_row_records_the_ceilings_that_produced_it(self):
        timeout = self.TIMEOUT
        with mock.patch.dict(os.environ, {
            "GEMINI_API_KEY": "not-a-real-key",
            "GOOGLE_API_BASE": self.base,
            "REVIEW_PLAN_V2_GOOGLE_TIMEOUT": str(timeout),
            "REVIEW_PLAN_V2_GOOGLE_MAX_CALL": str(
                _budget.derive_max_call_sec(timeout=timeout, slack=self.SLACK)),
            "REVIEW_PLAN_V2_LOG_DIR": self.tmp.name,
        }, clear=False):
            os.environ.pop("GOOGLE_API_KEY", None)
            google.call("sys", "user", reviewer="budget-test")
        row = json.loads(
            (Path(self.tmp.name) / "calls.jsonl").read_text().splitlines()[-1]
        )
        # Diagnosing the original kills meant reading TIMEOUT_SEC out of today's
        # source and assuming it had not moved. A row that names its own ceilings
        # does not need that assumption.
        for key in ("timeout_sec", "max_call_sec", "max_tokens"):
            self.assertIn(key, row, f"a failure row must record {key}")
        self.assertAlmostEqual(row["timeout_sec"], timeout, places=3)


if __name__ == "__main__":
    unittest.main()
