"""Guards for the 2026-08-13 dead-cascade fix.

Context: the OpenAI cascade leg sent `max_tokens`, which the gpt-5.x family
rejects with HTTP 400. It failed 136/136 calls from 2026-05-09 to 2026-08-13
and nothing surfaced it, because four layers each degraded quietly:

  1. the provider discarded the error body that named the fix
  2. a failed call returned `[]`, indistinguishable from "reviewed, found nothing"
  3. `failed_task_count` counted only raised exceptions
  4. `test_cascade.py` asserted the leg was CALLED, never that it ANSWERED

Every test here was verified to FAIL against the pre-fix code before being
committed — a guard that has never been observed failing is not known to be a
guard at all.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock
from pathlib import Path

# Direct execution needs `scripts` on the path; pytest supplies it via
# pyproject's `pythonpath` and nothing supplies it outside pytest. Without
# this the `__main__` guard below is a promise the file cannot keep —
# T005i-b found seven such modules here, none able to run standalone.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from review_plan_v2.providers import _errors, openai as openai_provider  # noqa: E402
from review_plan_v2.reviewers.base import ProviderCallFailed, Reviewer  # noqa: E402
from review_plan_v2.types import CallResult, FileChange  # noqa: E402


class OpenAIPayloadContractTests(unittest.TestCase):
    """Pin the payload shape the real API actually accepts.

    The integration suite cannot cover this: it runs against a FixtureServer
    that re-wraps whatever it receives into a valid response, so it accepts
    `max_tokens` happily and would keep accepting it forever. Only a direct
    assertion on the outgoing request can catch a parameter the live provider
    rejects, so this is deliberately a source-of-truth pin rather than a
    round-trip test.
    """

    def _capture_payload(self, **call_kwargs) -> dict:
        """Capture the outgoing request body.

        The dummy `OPENAI_API_KEY` is load-bearing, not decoration. `call()`
        returns early with error_kind="auth" when no key is present, so without
        it this captures nothing — and CI, which has no key, saw an empty dict
        where a developer shell with a key in ~/.zshrc saw a full payload.
        Caught on the very first CI run of the new tests workflow.
        """
        import os
        from unittest import mock

        captured: dict = {}

        def fake_post(url, headers, payload, timeout):
            captured.update(payload)
            body = json.dumps({
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }).encode()
            return 200, body

        original = openai_provider._post_once
        openai_provider._post_once = fake_post
        try:
            with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key-not-real"}):
                openai_provider.call("sys", "user", reviewer="test", **call_kwargs)
        finally:
            openai_provider._post_once = original
        # Anti-vacuity guard. `assertNotIn("max_tokens", {})` passes trivially,
        # so an empty capture would make the negative test below green while
        # proving nothing whatsoever about the request we actually send.
        self.assertTrue(captured, "no payload captured — the test proves nothing")
        return captured

    def test_sends_max_completion_tokens(self):
        self.assertEqual(self._capture_payload(max_tokens=4096).get("max_completion_tokens"), 4096)

    def test_never_sends_max_tokens(self):
        # The exact 400 that killed this leg for three months:
        # "Unsupported parameter: 'max_tokens' is not supported with this
        #  model. Use 'max_completion_tokens' instead."
        self.assertNotIn("max_tokens", self._capture_payload(max_tokens=4096))


class EmptyContentTests(unittest.TestCase):
    """HTTP 200 with no text is a failure, not a clean review.

    Live-verified against gpt-5.5: a 16-token budget produced 107 reasoning
    tokens, `finish_reason: "length"`, and `content: ""`. Reasoning models
    spend the budget on reasoning FIRST, so this is a routine outcome of a
    budget that is merely too small — not an exotic edge case.
    """

    def test_blank_shapes_are_all_blank(self):
        for value in (None, "", "   ", "\n\t "):
            self.assertTrue(_errors.is_blank(value), msg=repr(value))

    def test_real_content_is_not_blank(self):
        self.assertFalse(_errors.is_blank("RATING: GREEN"))


class RedactionTests(unittest.TestCase):
    """Error bodies reach the operator's terminal, so they must carry no keys.

    `google.py` passes its API key as a URL query parameter, which makes any
    echoed request context a live credential.
    """

    def _msg(self, text: str) -> str:
        return _errors.summarize_error_body(json.dumps({"error": {"message": text}}).encode())

    def test_redacts_credentials(self):
        for secret, text in [
            # query / form
            ("AIzaSyD-REAL-LOOKING-KEY-1234567", "GET https://x?key=AIzaSyD-REAL-LOOKING-KEY-1234567"),
            ("sk-proj-abc123def456ghi789jkl", "Incorrect API key provided: sk-proj-abc123def456ghi789jkl"),
            ("eyJhbGciOiJIUzI1NiJ9", "auth failed: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig"),
            ("Xk39fmQ2pLzR8vN4tY7wB1cD5gH0jK6a", "novel opaque key Xk39fmQ2pLzR8vN4tY7wB1cD5gH0jK6a"),
            # JSON and header shapes. Covering only `=` left these exposed, and
            # a provider quoting the offending request back is exactly when a
            # body carries one. Each secret here is SHORT and/or contains `_`,
            # so the long-opaque-run backstop cannot save us.
            ("shortkey123", 'bad request: {"api_key":"shortkey123"}'),
            ("abc123", "header x-api-key: abc123 rejected"),
            ("tok_underscore_value", 'field "token": "tok_underscore_value" invalid'),
            # HTTP auth schemes put the credential AFTER a space; a value
            # pattern stopping at whitespace masked `Basic` and left the secret.
            ("dXNlcjpwdw==", "authorization: Basic dXNlcjpwdw=="),
            ("hunter2", "secret=hunter2"),
            # Quoted values containing SPACES. A value pattern ending at
            # whitespace masks only the first word and prints the rest, so the
            # quoted form must be consumed through its closing quote. Newlines
            # are collapsed before redaction, so this also covers PEM blocks.
            ("foo bar baz", 'rejected {"secret": "foo bar baz"}'),
            ("spaces here", 'body {"api_key": "key with spaces here"}'),
            ("BEGIN KEY", 'pem {"private_key": "-----BEGIN KEY----- abc -----END KEY-----"}'),
        ]:
            self.assertNotIn(secret, self._msg(text), msg=f"leaked: {secret}")

    def test_preserves_identifiers(self):
        """Over-redaction destroys the diagnosis this feature exists to deliver.

        A greedy `[A-Za-z0-9_-]{32,}` backstop swallows long snake_case symbols
        (this very test name is 50 characters), turning the one useful line
        into `***`.
        """
        for keep in [
            "test_cascade_invokes_openai_and_google_on_high_risk",
            "max_completion_tokens",
            "scripts/review_plan_v2/providers/openai.py",
        ]:
            self.assertIn(keep, self._msg(f"problem near {keep} here"))

    def test_truncates_long_bodies(self):
        out = _errors.summarize_error_body(
            json.dumps({"error": {"message": " ".join(f"word{i}" for i in range(400))}}).encode()
        )
        self.assertLessEqual(len(out), _errors.MAX_DETAIL_CHARS + 1)
        self.assertTrue(out.endswith("…"))

    def test_extracts_provider_envelopes(self):
        openai_body = json.dumps({"error": {"message": "Unsupported parameter: 'max_tokens'"}}).encode()
        self.assertEqual(_errors.summarize_error_body(openai_body), "Unsupported parameter: 'max_tokens'")
        google_body = json.dumps({"error": {"code": 404, "message": "models/x is not found", "status": "NOT_FOUND"}}).encode()
        self.assertEqual(_errors.summarize_error_body(google_body), "models/x is not found")
        self.assertIsNone(_errors.summarize_error_body(b""))
        # Unparseable is not the same as absent — a 502 HTML page still says something.
        self.assertIn("502", _errors.summarize_error_body(b"<html>502 Bad Gateway</html>"))


class ReviewerRaisesOnFailureTests(unittest.TestCase):
    """A failed provider call must not be reportable as "found nothing".

    `run()` returning `[]` on failure is the single line that made the dead leg
    survivable: the orchestrator treats a task as failed only when it raises,
    so a swallowed failure left the coverage banner silent and the exit code 0.
    """

    def _reviewer(self, result: CallResult) -> Reviewer:
        return Reviewer(
            name="security",
            prompt_filename="security.md",
            provider_call=lambda *a, **k: result,
            model="test-model",
        )

    def _chunk(self) -> FileChange:
        return FileChange(
            path="src/x.ts",
            is_binary=False,
            is_renamed_from=None,
            added_lines=((1, 1),),
            diff_text="+const a = 1;",
            language="typescript",
        )

    def test_http_error_raises(self):
        result = CallResult(
            content=None, error_kind="unknown", status_code=400,
            error_detail="Unsupported parameter: 'max_tokens' is not supported with this model.",
        )
        with self.assertRaises(ProviderCallFailed) as ctx:
            self._reviewer(result).run(self._chunk())
        # The operator-facing message must name the CAUSE, not just the fact.
        self.assertIn("max_tokens", str(ctx.exception))
        self.assertIn("400", str(ctx.exception))

    def test_empty_content_raises(self):
        result = CallResult(content="", error_kind=None, status_code=200)
        with self.assertRaises(ProviderCallFailed):
            self._reviewer(result).run(self._chunk())

    def test_successful_call_still_parses(self):
        result = CallResult(content="No issues found.", error_kind=None, status_code=200)
        self.assertIsInstance(self._reviewer(result).run(self._chunk()), list)


class TelemetryTimestampTests(unittest.TestCase):
    """30,956 records carried no time axis, so the breakage had to be dated by
    file line-order and "zero failures since the fix" was unprovable."""

    def test_log_call_stamps_a_timestamp(self):
        import tempfile

        from review_plan_v2 import telemetry

        with tempfile.TemporaryDirectory() as tmp:
            # patch.dict RESTORES the prior value; assigning and then popping
            # in `finally` DELETED one this block never set, disarming the
            # session-wide redirect in tests/conftest.py for every test that
            # ran afterwards. 63 records leaked into the operator's real
            # calls.jsonl that way, including mocked-clock rows claiming
            # latency_ms=180000.
            with mock.patch.dict(os.environ, {"REVIEW_PLAN_V2_LOG_DIR": tmp}):
                telemetry.log_call({"provider": "openai", "model": "m", "reviewer": "r"})
                written = json.loads((Path(tmp) / "calls.jsonl").read_text().strip())
        self.assertIn("timestamp", written)
        self.assertRegex(written["timestamp"], r"^\d{4}-\d{2}-\d{2}T")

    def test_log_call_still_drops_disallowed_keys(self):
        """FR-015: no prompt/diff/message bodies in telemetry, ever.

        `error_detail` rides the return value to stderr precisely so it can
        never land here.
        """
        import tempfile

        from review_plan_v2 import telemetry

        with tempfile.TemporaryDirectory() as tmp:
            # patch.dict RESTORES the prior value; assigning and then popping
            # in `finally` DELETED one this block never set, disarming the
            # session-wide redirect in tests/conftest.py for every test that
            # ran afterwards. 63 records leaked into the operator's real
            # calls.jsonl that way, including mocked-clock rows claiming
            # latency_ms=180000.
            with mock.patch.dict(os.environ, {"REVIEW_PLAN_V2_LOG_DIR": tmp}):
                telemetry.log_call({"provider": "openai", "error_detail": "SECRET-BODY", "diff": "SECRET-DIFF"})
                raw = (Path(tmp) / "calls.jsonl").read_text()
        self.assertNotIn("SECRET-BODY", raw)
        self.assertNotIn("SECRET-DIFF", raw)


class DeadLegRenderingTests(unittest.TestCase):
    """The [DEAD-LEG] banner is the operator-visible half of the whole fix.

    All of these were raised by review-plan-v2 reviewing its own fix — the
    rendering branch had no direct coverage.
    """

    def _render(self, providers_called, findings=()):
        from review_plan_v2 import output_format
        return output_format.render_plain(findings, {"providers_called": providers_called})

    def test_total_failure_emits_dead_leg(self):
        out = self._render([{"provider": "openai", "calls": 4, "succeeded": 0, "failed": 4}])
        self.assertIn("[DEAD-LEG]", out)
        self.assertIn("openai", out)

    def test_partial_failure_does_not_emit_dead_leg(self):
        """A leg that answered some calls is degraded, not misconfigured —
        and the remedy differs, so conflating them misleads."""
        out = self._render([{"provider": "openai", "calls": 4, "succeeded": 3, "failed": 1}])
        self.assertNotIn("[DEAD-LEG]", out)

    def test_healthy_leg_does_not_emit_dead_leg(self):
        out = self._render([{"provider": "deepseek", "calls": 9, "succeeded": 9, "failed": 0}])
        self.assertNotIn("[DEAD-LEG]", out)

    def test_absent_or_empty_providers_called_is_silent(self):
        from review_plan_v2 import output_format
        self.assertNotIn("[DEAD-LEG]", self._render([]))
        self.assertNotIn("[DEAD-LEG]", output_format.render_plain([], {}))
        self.assertNotIn("[DEAD-LEG]", output_format.render_plain([], None))

    def test_zero_calls_is_not_a_dead_leg(self):
        """0 failed == 0 calls is vacuously equal; a leg never called is not dead."""
        self.assertNotIn("[DEAD-LEG]", self._render([{"provider": "google", "calls": 0, "failed": 0}]))

    def test_malformed_entries_do_not_crash(self):
        """This renders a diagnostic about an already-broken run. If it throws,
        it takes the findings down with it — the failure mode it exists to
        prevent, one level up."""
        for bad in (
            [{"calls": "abc", "failed": "xyz"}],
            [{"provider": "openai"}],
            ["not-a-dict"],
            [None],
            [{"provider": "openai", "calls": None, "failed": None}],
        ):
            with self.subTest(bad=bad):
                self.assertIsInstance(self._render(bad), str)

    def test_dead_leg_survives_alongside_findings(self):
        from review_plan_v2.types import Finding
        finding = Finding(
            file="src/x.ts", line=1, line_end=None, severity="actionable",
            category="correctness", message="boom", sources=["security"],
        )
        out = self._render([{"provider": "openai", "calls": 2, "succeeded": 0, "failed": 2}], [finding])
        self.assertIn("[DEAD-LEG]", out)
        self.assertIn("boom", out)


class GeminiFixtureRouteTests(unittest.TestCase):
    """Regression pin for the second dead leg this work uncovered.

    The route regex was anchored `:generateContent$` while google.py passes its
    API key as a query parameter, so every Gemini call in the integration suite
    404'd and that leg was never exercised by any test.
    """

    def _re(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "support"))
        from fixture_server import _GEMINI_PATH_RE
        return _GEMINI_PATH_RE

    def test_matches_with_query_string(self):
        self.assertTrue(self._re().match(
            "/v1beta/models/gemini-3.1-pro-preview:generateContent?key=test-key"
        ))

    def test_matches_without_query_string(self):
        self.assertTrue(self._re().match("/v1beta/models/gemini-3.1-pro-preview:generateContent"))

    def test_does_not_match_other_methods(self):
        self.assertIsNone(self._re().match("/v1beta/models/gemini-3.1-pro-preview:streamGenerateContent"))
        self.assertIsNone(self._re().match("/v1/chat/completions"))


class TimestampPreservationTests(unittest.TestCase):
    """`setdefault` must not overwrite a caller-supplied timestamp."""

    def _write(self, record):
        import os
        import tempfile

        from review_plan_v2 import telemetry

        with tempfile.TemporaryDirectory() as tmp:
            # patch.dict RESTORES the prior value; assigning and then popping
            # in `finally` DELETED one this block never set, disarming the
            # session-wide redirect in tests/conftest.py for every test that
            # ran afterwards. 63 records leaked into the operator's real
            # calls.jsonl that way, including mocked-clock rows claiming
            # latency_ms=180000.
            with mock.patch.dict(os.environ, {"REVIEW_PLAN_V2_LOG_DIR": tmp}):
                telemetry.log_call(record)
                return json.loads((Path(tmp) / "calls.jsonl").read_text().strip())

    def test_caller_supplied_timestamp_is_preserved(self):
        supplied = "2020-01-01T00:00:00+00:00"
        self.assertEqual(self._write({"provider": "openai", "timestamp": supplied})["timestamp"], supplied)

    def test_missing_timestamp_is_stamped(self):
        self.assertIn("timestamp", self._write({"provider": "openai"}))

if __name__ == "__main__":
    unittest.main()
