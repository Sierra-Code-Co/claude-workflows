"""`max_tokens` is a COMBINED reasoning+answer budget — size it for both.

Reviewer calls returned HTTP 200 with `content: ""` because the v4 family
generates reasoning tokens first and charges them to the same allowance as the
answer. At the shipped `max_tokens=8192`, one real diff produced (2026-08-13):

    security      10.6s  reasoning   738  -> answer OK
    tests         64.9s  reasoning 7,249  -> answer OK, 95% of budget consumed
    correctness   78.4s  reasoning 8,192  -> EMPTY (capped)
    consistency   73.4s  reasoning 8,192  -> EMPTY (capped)

Half the reviewers returned nothing, and the failure rate tracked how hard the
analysis was: correctness failed 10.2% of production calls, security 0.77%.
Since the 30s wall killed those calls at 30s (budget exhaustion needs 78-124s to
come back), every one was filed `transient` — a network error.
"""
from __future__ import annotations

import inspect
import io
import json
import os
import pathlib
import unittest
from unittest import mock

# Direct execution needs `scripts` on the path; pytest supplies it via
# pyproject's `pythonpath` and nothing supplies it outside pytest. Without
# this the `__main__` guard below is a promise the file cannot keep —
# T005i-b found seven such modules here, none able to run standalone.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from review_plan_v2.providers import _budget as budget
from review_plan_v2.providers import deepseek as ds  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


_DEFAULT_BODY = {
    "choices": [{"message": {"content": "[]"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
}


def _capture_payload(captured: list, status: int = 200, body: dict | None = None):
    """Stand in for _post_once, recording the request payload.

    `body if body is not None` rather than `body or` — an empty dict is falsy,
    so the shorter form silently substituted the default and made it impossible
    to simulate an empty response, which is the exact failure under test here.
    """
    def fake(url, headers, payload, timeout):
        captured.append({"payload": payload, "timeout": timeout})
        return status, json.dumps(body if body is not None else _DEFAULT_BODY).encode()
    return fake


class EmptyContentDetectionTests(unittest.TestCase):
    """The motivating failure: HTTP 200, finish_reason=length, content "".

    Every other test in this file pins a constant. This one exercises the shape
    those constants exist to prevent, so the file cannot pass while the
    detection itself is broken.
    """

    def _call_with(self, body: dict):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key-not-real"}), \
                mock.patch.object(ds, "_post_once", _capture_payload([], body=body)):
            return ds.call("sys", "user", reviewer="test")

    def test_budget_exhausted_response_is_a_failure_not_a_clean_review(self):
        result = self._call_with({
            "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
            "usage": {
                "prompt_tokens": 2474, "completion_tokens": 8192,
                "completion_tokens_details": {"reasoning_tokens": 8192},
            },
        })
        self.assertEqual(
            result.error_kind, "empty",
            msg="HTTP 200 with empty content must not read as a successful review",
        )
        self.assertIsNone(result.content)
        # The two numbers that turn this from "a provider hiccup" into a diagnosis.
        self.assertIn("reasoning_tokens=8192", result.error_detail or "")
        self.assertIn("length", result.error_detail or "")

    def test_whitespace_only_content_is_also_empty(self):
        """`is_blank`, not `is None` — the pre-#27 guard tested identity and the
        API returns a string, which is how this survived."""
        result = self._call_with({
            "choices": [{"message": {"content": "  \n\t "}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3},
        })
        self.assertEqual(result.error_kind, "empty")

    def test_malformed_usage_block_does_not_crash_the_diagnostic(self):
        """The detail string digs through usage.completion_tokens_details; a
        provider omitting either must degrade to a message, not a KeyError."""
        for usage in ({}, {"completion_tokens": 1}, {"completion_tokens_details": {}}):
            with self.subTest(usage=usage):
                result = self._call_with({
                    "choices": [{"message": {"content": ""}}],
                    "usage": usage,
                })
                self.assertEqual(result.error_kind, "empty")
                self.assertIn("reasoning_tokens=", result.error_detail or "")


class BudgetSizingTests(unittest.TestCase):
    def test_default_budget_clears_the_measured_reasoning_ceiling(self):
        """The threshold moves when the measurement does.

        It read 22,512 — the largest figure seen under a ceiling of 32768. That
        number could not describe its own tail, and on 2026-08-15 the tail
        arrived: two calls returned empty at reasoning_tokens=32768 of
        budget=32768, on the two largest files of a real diff.

        Re-measured with the ceiling raised (the only way to see past a cutoff),
        the hardest call that ANSWERED used 64,006 combined tokens. So that is
        the figure to clear now, and it will be wrong again the moment a harder
        diff is measured — which is what NEAR_BUDGET_RATIO exists to announce.
        """
        self.assertGreater(
            budget.MAX_TOKENS, 64006,
            msg=f"MAX_TOKENS={budget.MAX_TOKENS} does not clear the 64,006 "
                "combined tokens the hardest ANSWERING call was measured to use",
        )

    def test_call_sends_the_resolved_budget_not_a_hardcoded_8192(self):
        """Regression: the signature defaulted to a literal 8192, so raising the
        module constant alone would have changed nothing at the call site."""
        captured: list = []
        # REVIEW_PLAN_V2_MAX_TOKENS is CLEARED, not merely unset in the dict —
        # `mock.patch.dict` adds to the environment without removing what is
        # already there, so on a machine where the operator exports an override
        # this asserted the default while the code correctly used the override.
        # A test that fails only on someone else's shell is worse than no test.
        env = {k: v for k, v in os.environ.items()
               if k != "REVIEW_PLAN_V2_MAX_TOKENS"}
        env["DEEPSEEK_API_KEY"] = "test-key-not-real"
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(ds, "_post_once", _capture_payload(captured)):
            ds.call("sys", "user", reviewer="test")
        self.assertTrue(captured, "no payload captured — the test proves nothing")
        self.assertEqual(captured[0]["payload"]["max_tokens"], budget.MAX_TOKENS)
        self.assertNotEqual(captured[0]["payload"]["max_tokens"], 8192)

    def test_the_env_override_reaches_the_payload(self):
        """The override has to be resolved at CALL time.

        As a default argument it would be evaluated at import, so an override set
        by a wrapper — or by this test — would be read before it existed and
        silently ignored. The failure mode is a knob that appears to work and
        changes nothing, which is the shape of every other bug in this file.
        """
        captured: list = []
        with mock.patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "test-key-not-real",
            "REVIEW_PLAN_V2_MAX_TOKENS": "12345",
        }), mock.patch.object(ds, "_post_once", _capture_payload(captured)):
            ds.call("sys", "user", reviewer="test")
        self.assertTrue(captured, "no payload captured — the test proves nothing")
        self.assertEqual(captured[0]["payload"]["max_tokens"], 12345)

    def test_a_junk_override_falls_back_rather_than_disabling_the_budget(self):
        """A zero budget returns an empty answer on EVERY call, which this
        pipeline renders as "reviewed, found nothing"."""
        for bad in ("0", "-1", "inf", "nan", "abc"):
            with self.subTest(value=bad):
                captured: list = []
                with mock.patch.dict(os.environ, {
                    "DEEPSEEK_API_KEY": "test-key-not-real",
                    "REVIEW_PLAN_V2_MAX_TOKENS": bad,
                }), mock.patch.object(ds, "_post_once", _capture_payload(captured)):
                    ds.call("sys", "user", reviewer="test")
                self.assertEqual(
                    captured[0]["payload"]["max_tokens"], budget.MAX_TOKENS,
                    msg=f"override {bad!r} did not fall back to the default",
                )

    def test_timeout_clears_the_measured_hard_chunk_latency(self):
        """30s could not cover a 65-125s reasoning-heavy call."""
        self.assertGreaterEqual(
            ds.TIMEOUT_SEC, 125.0,
            msg=f"TIMEOUT_SEC={ds.TIMEOUT_SEC} is below the 125s measured for a "
                "reasoning-heavy reviewer call",
        )

    def test_reasoning_effort_is_never_sent(self):
        """`none` blinds the reviewer and `low` is silently ignored.

        Measured against the repo's own planted-bug fixtures:
          02-pascalcase-bug  effort=none -> 0 findings (baseline: 1, correct)
          03-sql-injection   effort=none -> 0 findings (baseline: 1, correct)
        Fast, complete, and clean on everything — the exact silent-pass failure
        this tool exists to prevent. `low` measured reasoning_tokens=8192 and an
        empty answer, identical to no parameter at all, because the API accepts
        and discards unknown fields (a deliberate nonsense field also got 200).
        """
        captured: list = []
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key-not-real"}), \
                mock.patch.object(ds, "_post_once", _capture_payload(captured)):
            ds.call("sys", "user", reviewer="test")
        self.assertTrue(captured, "no payload captured — the test proves nothing")
        payload = captured[0]["payload"]
        for field in ("reasoning_effort", "thinking", "enable_thinking"):
            self.assertNotIn(
                field, payload,
                msg=f"{field} suppresses reasoning and makes the reviewer miss "
                    "planted bugs; see this test's docstring for the measurement",
            )


class PerCallBudgetTests(unittest.TestCase):
    def test_retries_cannot_exceed_the_per_call_budget(self):
        """Raising the per-attempt timeout must not multiply by the retry count.

        3 x 180s + sleeps is 9 minutes on one doomed chunk, holding a worker for
        all of it. The retry loop must refuse an attempt it cannot finish.
        """
        self.assertLess(
            ds.MAX_CALL_SEC,
            ds.TIMEOUT_SEC * (1 + len(ds.RETRY_SLEEPS)),
            msg="MAX_CALL_SEC must bound the retry loop below "
                "timeout x attempts, otherwise it is not a bound at all",
        )

    def test_the_first_attempt_is_clamped_to_the_per_call_budget(self):
        """A budget checked only before retries is not a budget.

        With REVIEW_PLAN_V2_DEEPSEEK_TIMEOUT above MAX_CALL, attempt 0 alone
        overran the ceiling — nothing had examined it yet.
        """
        captured: list = []
        with mock.patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "test-key-not-real",
            "REVIEW_PLAN_V2_DEEPSEEK_TIMEOUT": "900",
            "REVIEW_PLAN_V2_DEEPSEEK_MAX_CALL": "300",
        }), mock.patch.object(ds, "_post_once", _capture_payload(captured)):
            ds.call("sys", "user", reviewer="test")
        self.assertTrue(captured, "no call captured — the test proves nothing")
        self.assertEqual(
            captured[0]["timeout"], 300.0,
            msg=f"first attempt ran with timeout={captured[0]['timeout']}s "
                "against a 300s per-call budget",
        )

    def test_an_explicit_timeout_argument_is_also_clamped(self):
        """The clamp must not be bypassable by passing `timeout=` directly."""
        captured: list = []
        with mock.patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "test-key-not-real",
            "REVIEW_PLAN_V2_DEEPSEEK_MAX_CALL": "120",
        }), mock.patch.object(ds, "_post_once", _capture_payload(captured)):
            ds.call("sys", "user", reviewer="test", timeout=600.0)
        self.assertTrue(captured, "no call captured — the test proves nothing")
        self.assertEqual(captured[0]["timeout"], 120.0)

    def test_a_doomed_call_stops_at_the_budget_instead_of_retrying(self):
        """A timing-out call must give up rather than start an unpayable attempt."""
        attempts = {"n": 0}

        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key-not-real"}), \
                mock.patch.object(ds, "TIMEOUT_SEC", 180.0), \
                mock.patch.object(ds, "MAX_CALL_SEC", 200.0), \
                mock.patch.object(ds, "time") as fake_time:
            # Simulate real elapsed time: each attempt burns the full timeout.
            clock = {"t": 0.0}

            def monotonic():
                return clock["t"]

            def sleep(_s):
                clock["t"] += _s

            fake_time.monotonic = monotonic
            fake_time.sleep = sleep

            def timing_out(url, headers, payload, timeout):
                attempts["n"] += 1
                clock["t"] += timeout
                raise TimeoutError("read timed out")

            with mock.patch.object(ds, "_post_once", timing_out):
                result = ds.call("sys", "user", reviewer="test")

        self.assertEqual(
            attempts["n"], 1,
            msg=f"made {attempts['n']} attempts; a second 180s attempt cannot "
                "fit inside a 200s per-call budget and must not be started",
        )
        self.assertEqual(result.error_kind, "transient")
        self.assertIn("per-call budget", result.error_detail or "")


class TransientClassificationTests(unittest.TestCase):
    def test_connection_reset_is_retryable(self):
        """ConnectionResetError does not subclass URLError, so it was classified
        non-retryable 'unknown'. Peer resets happen on long reviewer responses —
        hit live while probing a 300s call."""
        kind, retryable = ds._classify(None, ConnectionResetError(54, "reset by peer"))
        self.assertEqual(kind, "transient")
        self.assertTrue(retryable)

    def test_a_genuine_unknown_is_still_not_retried(self):
        """Guard the over-correction: not every exception is transient."""
        kind, retryable = ds._classify(None, ValueError("bad payload"))
        self.assertEqual(kind, "unknown")
        self.assertFalse(retryable)


class EnvOverrideTests(unittest.TestCase):
    def test_env_override_applies(self):
        with mock.patch.dict(os.environ, {"REVIEW_PLAN_V2_DEEPSEEK_TIMEOUT": "42.5"}):
            self.assertEqual(ds.env_float("REVIEW_PLAN_V2_DEEPSEEK_TIMEOUT", 180.0), 42.5)

    def test_junk_and_nonpositive_values_fall_back_to_the_default(self):
        """A typo'd override must not silently disable the timeout.

        `inf` is the dangerous one: `float("inf") > 0` is True, so a bare
        positivity check accepts it and removes the ceiling entirely — the same
        outcome as no timeout at all, which reads as "no failures". `nan` fails
        every comparison and would fall back by accident; pin it anyway so the
        guard is `isfinite`, not luck.
        """
        for bad in ("", "abc", "0", "-5", "1e", "None", "inf", "-inf",
                    "Infinity", "nan", "1e309", "   "):
            with mock.patch.dict(os.environ, {"REVIEW_PLAN_V2_DEEPSEEK_TIMEOUT": bad}):
                self.assertEqual(
                    ds.env_float("REVIEW_PLAN_V2_DEEPSEEK_TIMEOUT", 180.0), 180.0,
                    msg=f"override {bad!r} should have fallen back to the default",
                )




class NearBudgetSignalTests(unittest.TestCase):
    """The leading indicator for an undersized budget.

    The failure is binary and gives no warning of its own: at 97.1% of budget the
    answer arrives and the review looks clean; at 100% the answer is empty and
    the reviewer reports nothing, which this pipeline renders as "found nothing".
    Measured 2026-08-15 — the two calls that returned EMPTY at 32768 sat at
    97.1%, and the hardest call that ANSWERED at 65536 sat at 97.7%. Nothing
    told them apart in advance because nothing was watching the ratio.

    This is also the fix for the deeper problem the budget kept reproducing: a
    distribution censored at the ceiling cannot describe its own tail, so
    `output_tokens max ever` always looks comfortably under the limit. Recording
    the ratio is what makes the NEXT budget sizeable without measuring under this
    one.
    """

    def _call_with_usage(self, completion_tokens: int, max_tokens: int = 1000):
        captured: list = []
        logged: list = []
        body = json.dumps({
            "choices": [{"message": {"content": "[]"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": completion_tokens},
        }).encode()
        with mock.patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "test-key-not-real",
            "REVIEW_PLAN_V2_MAX_TOKENS": str(max_tokens),
        }), mock.patch.object(ds, "_post_once", lambda *a, **k: (200, body)), \
             mock.patch.object(ds, "log_call", lambda rec, **k: logged.append(rec)), \
             mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            result = ds.call("sys", "user", reviewer="correctness")
        captured.append(err.getvalue())
        return result, logged, captured[0]

    def test_a_call_near_the_ceiling_warns_even_though_it_succeeded(self):
        _, logged, stderr = self._call_with_usage(970, max_tokens=1000)
        self.assertTrue(logged[0]["near_budget"])
        self.assertIn("97%", stderr)
        self.assertIn("EMPTY", stderr)

    def test_an_ordinary_call_is_silent(self):
        """Anti-vacuous control. A warning on every call is a warning on none —
        the median successful review emits 334 tokens against this ceiling."""
        _, logged, stderr = self._call_with_usage(334, max_tokens=65536)
        self.assertFalse(logged[0]["near_budget"])
        self.assertEqual(stderr, "")

    def test_the_budget_in_force_is_recorded_with_the_usage(self):
        """A token count means nothing without the ceiling it was measured
        against; that pairing is exactly what the old log lacked."""
        _, logged, _ = self._call_with_usage(500, max_tokens=1000)
        self.assertEqual(logged[0]["max_tokens"], 1000)
        self.assertEqual(logged[0]["output_tokens"], 500)

    def test_the_new_fields_survive_the_telemetry_allowlist(self):
        """The allowlist silently DROPS unknown keys — `timestamp` was listed
        from day one and never written, leaving 30,956 records with no time
        axis. A field that never lands is a field that never existed."""
        from review_plan_v2 import telemetry
        self.assertIn("near_budget", telemetry._ALLOWED_KEYS)
        self.assertIn("max_tokens", telemetry._ALLOWED_KEYS)

    def test_the_threshold_boundary_is_inclusive_and_tight(self):
        """Exactly at the ratio fires; one token below does not.

        Off-by-one here is not cosmetic: the whole value of the signal is that
        it lands in the narrow band between "answered comfortably" and "returned
        empty", so a boundary that drifts either way turns it into noise or into
        silence.
        """
        import io as _io
        at = int(budget.NEAR_BUDGET_RATIO * 1000)
        for tokens, expected in ((at, True), (at - 1, False)):
            with self.subTest(tokens=tokens):
                err = _io.StringIO()
                fields = budget.budget_fields(tokens, 1000, "correctness", stream=err)
                self.assertEqual(fields["near_budget"], expected)
                self.assertEqual(bool(err.getvalue()), expected)

    def test_a_zero_budget_does_not_warn_or_divide_by_zero(self):
        """`max_tokens=0` reaches here only via a bug, and a ZeroDivisionError
        inside the warning would take down a call that otherwise succeeded."""
        import io as _io
        err = _io.StringIO()
        fields = budget.budget_fields(0, 0, "correctness", stream=err)
        self.assertFalse(fields["near_budget"])
        self.assertEqual(err.getvalue(), "")

    def test_the_signal_fires_below_total_exhaustion(self):
        """It has to warn while calls still SUCCEED, or it is just a rename of
        the failure it exists to predict."""
        _, logged, _ = self._call_with_usage(
            int(budget.NEAR_BUDGET_RATIO * 1000) + 1, max_tokens=1000)
        self.assertTrue(logged[0]["near_budget"])
        self.assertLess(budget.NEAR_BUDGET_RATIO, 1.0)


class EveryProviderReportsItsBudgetTests(unittest.TestCase):
    """Budget exhaustion is not a DeepSeek quirk.

    Reasoning and answer share one allowance on every current reasoning model —
    v4-pro/v4-flash, Gemini 3.1 Pro, GPT-5.x alike, as _budget.py's own docstring
    says. I wrote the near-exhaustion signal for DeepSeek and shipped it that way;
    ruff caught the constant sitting unused in the other two, which is the only
    reason the other two got it.

    That is the same shape as the `TIMEOUT_SEC = 30.0` this module was created to
    end: a value copy-pasted per provider is wrong in every provider at once, and
    fixing one leaves the rest silently broken. So this asserts the property
    across ALL providers rather than for the one that happened to be noticed.
    """

    PROVIDERS = ("deepseek", "google", "openai")

    def test_every_provider_resolves_the_budget_at_call_time(self):
        import importlib
        for name in self.PROVIDERS:
            with self.subTest(provider=name):
                mod = importlib.import_module(f"review_plan_v2.providers.{name}")
                sig = inspect.signature(mod.call)
                self.assertIsNone(
                    sig.parameters["max_tokens"].default,
                    msg=f"{name}.call pins max_tokens as a default argument, which "
                        f"is evaluated at import — an override set later is read "
                        f"before it exists and silently ignored",
                )

    # Success-response bodies, per provider. Each reports a completion count at
    # 95% of a 1000-token budget, so a correctly wired provider must flag it.
    _BODIES = {
        "deepseek": lambda: json.dumps({
            "choices": [{"message": {"content": "[]"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 950},
        }).encode(),
        "openai": lambda: json.dumps({
            "choices": [{"message": {"content": "[]"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 950},
        }).encode(),
        "google": lambda: json.dumps({
            "candidates": [{"content": {"parts": [{"text": "[]"}]},
                            "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 950},
        }).encode(),
    }
    _KEYS = {"deepseek": "DEEPSEEK_API_KEY", "openai": "OPENAI_API_KEY",
             "google": "GEMINI_API_KEY"}

    def test_every_provider_records_the_near_budget_signal(self):
        """Asserted BEHAVIOURALLY, not by grepping the source.

        The first version of this test searched each provider file for the
        literal "budget_fields(" — which passes if the string appears in a
        comment, in dead code, or on a path the success branch never reaches. A
        test that greps for its own fix is a test of the fix's spelling.
        """
        import importlib
        for name in self.PROVIDERS:
            with self.subTest(provider=name):
                mod = importlib.import_module(f"review_plan_v2.providers.{name}")
                logged: list = []
                body = self._BODIES[name]()
                env = {k: v for k, v in os.environ.items()
                       if k != "REVIEW_PLAN_V2_MAX_TOKENS"}
                env[self._KEYS[name]] = "test-key-not-real"
                env["REVIEW_PLAN_V2_MAX_TOKENS"] = "1000"
                with mock.patch.dict(os.environ, env, clear=True), \
                        mock.patch.object(mod, "_post_once", lambda *a, **k: (200, body)), \
                        mock.patch.object(mod, "log_call", lambda rec, **k: logged.append(rec)), \
                        mock.patch("sys.stderr", new_callable=io.StringIO):
                    mod.call("sys", "user", reviewer="correctness")
                self.assertTrue(logged, f"{name} logged no successful call")
                self.assertIn("near_budget", logged[0], f"{name} omits near_budget")
                self.assertTrue(
                    logged[0]["near_budget"],
                    msg=f"{name} used 950 of a 1000 budget and did not flag it, so "
                        f"its calls cannot be told apart from safe ones until one "
                        f"returns empty",
                )
                self.assertEqual(logged[0]["max_tokens"], 1000)


if __name__ == "__main__":
    unittest.main()
